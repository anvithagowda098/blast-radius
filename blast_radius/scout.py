"""Scout: find installs of affected package versions in lockfiles.

Reads npm ``package-lock.json`` / ``npm-shrinkwrap.json`` (v1, v2, v3) and
``pnpm-lock.yaml`` (v9, plus the older layout without ``snapshots``).

Dev dependencies are kept on purpose: install scripts run on laptops and CI
runners too. Every install path is reported, not just the first.
"""

from __future__ import annotations

import json
import os
import re
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from . import utc_now
from .advisory import Advisory

LOCKFILE_NAMES = ("package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml")
SKIP_DIRS = {"node_modules", ".git"}
_NODE_MODULES = "node_modules/"
# An npm alias inside pnpm, e.g. "string-width@4.2.3" as a dependency ref.
_ALIAS_REF = re.compile(r"^(?:@[^/@()]+/)?[^/@:()]+@")


@dataclass
class InstalledPackage:
    name: str
    version: str
    path: str  # npm: install path; pnpm: dependency chain from the importer
    depth: int = 1  # 1 = top-level / direct, 2+ = nested / transitive
    dev: bool = False
    optional: bool = False
    has_install_script: bool | None = None  # None = the lockfile doesn't say
    deps: list[str] = field(default_factory=list)
    resolved: str = ""


@dataclass
class Finding:
    repo: str
    lockfile: str
    name: str
    version: str
    path: str
    depth: int
    dev: bool
    optional: bool
    has_install_script: bool | None
    reason: str  # affected-version | ioc-dependency | ioc-reference
    notes: list[str] = field(default_factory=list)


@dataclass
class RepoResult:
    repo: str
    path: str
    lockfiles: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class ScoutReport:
    advisory: dict
    generated_at: str
    repos: list[RepoResult]

    @property
    def affected_repos(self) -> list[str]:
        return [r.repo for r in self.repos if r.findings]

    @property
    def clean_repos(self) -> list[str]:
        return [r.repo for r in self.repos if not r.findings and not r.errors and r.lockfiles]

    def to_dict(self) -> dict:
        return {
            "tool": "scout",
            "generated_at": self.generated_at,
            "advisory": self.advisory,
            "repos_scanned": len(self.repos),
            "affected_repos": self.affected_repos,
            "clean_repos": self.clean_repos,
            "repos": [asdict(r) for r in self.repos],
        }


# ---------------------------------------------------------------- npm lockfiles


def parse_package_lock(path: str | Path) -> list[InstalledPackage]:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    packages = data.get("packages")
    if isinstance(packages, dict) and packages:  # lockfile v2 / v3
        return list(_from_packages_map(packages))
    return list(_from_v1_tree(data.get("dependencies") or {}, "", 1))


def _from_packages_map(packages: dict):
    for key, entry in packages.items():
        if not key or not isinstance(entry, dict) or entry.get("link"):
            continue  # "" is the root project; links point at another entry
        idx = key.rfind(_NODE_MODULES)
        name = entry.get("name") or (key[idx + len(_NODE_MODULES):] if idx >= 0 else "")
        version = entry.get("version")
        if not name or not version:
            continue
        yield InstalledPackage(
            name=name,
            version=str(version),
            path=key,
            depth=key.count(_NODE_MODULES) or 1,
            dev=bool(entry.get("dev")),
            optional=bool(entry.get("optional") or entry.get("devOptional")),
            has_install_script=bool(entry.get("hasInstallScript")),
            deps=list(entry.get("dependencies") or {}) + list(entry.get("optionalDependencies") or {}),
            resolved=entry.get("resolved", ""),
        )


def _from_v1_tree(deps: dict, prefix: str, depth: int):
    for name, entry in deps.items():
        if not isinstance(entry, dict):
            continue
        path = f"{prefix}node_modules/{name}"
        version = str(entry.get("version", ""))
        real_name = name
        if version.startswith("npm:"):  # alias: "npm:real-name@1.2.3"
            spec = version[4:]
            at = spec.rfind("@")
            if at > 0:
                real_name, version = spec[:at], spec[at + 1:]
        yield InstalledPackage(
            name=real_name,
            version=version,
            path=path,
            depth=depth,
            dev=bool(entry.get("dev")),
            optional=bool(entry.get("optional")),
            has_install_script=None,  # v1 lockfiles don't record install scripts
            deps=list(entry.get("requires") or {}),
            resolved=entry.get("resolved", ""),
        )
        yield from _from_v1_tree(entry.get("dependencies") or {}, path + "/", depth + 1)


# ---------------------------------------------------------------- pnpm lockfiles


def _ref_to_key(name: str, ref) -> str | None:
    ref = str(ref)
    if ref.startswith(("link:", "file:", "workspace:")):
        return None
    if not ref[:1].isdigit() and _ALIAS_REF.match(ref):
        return ref  # npm alias: the ref already is "real-name@version"
    return f"{name}@{ref}"


def _split_pnpm_key(key: str) -> tuple[str, str] | None:
    base = key.lstrip("/").split("(", 1)[0]  # drop the peer suffix
    at = base.find("@", 1)  # skip the leading @ of a scoped name
    if at > 0:
        return base[:at], base[at + 1:]
    head, _, tail = base.rpartition("/")  # pnpm v5 wrote "/name/version"
    if head and tail[:1].isdigit():
        return head, tail
    return None


def _walk(roots: list[tuple[str, str]], graph: dict) -> dict[str, str]:
    """Breadth-first from the importers; returns key -> first dependency chain."""
    seen: dict[str, str] = {}
    queue = deque(roots)
    while queue:
        key, trail = queue.popleft()
        if key in seen:
            continue
        seen[key] = trail
        entry = graph.get(key) or {}
        for field_name in ("dependencies", "optionalDependencies"):
            for dep, ref in (entry.get(field_name) or {}).items():
                child = _ref_to_key(dep, ref)
                if child and child not in seen:
                    queue.append((child, f"{trail} > {dep}"))
    return seen


def parse_pnpm_lock(path: str | Path) -> list[InstalledPackage]:
    text = Path(path).read_text(encoding="utf-8-sig")
    # Newer pnpm can write more than one YAML document; the lockfile is the last.
    docs = [d for d in yaml.safe_load_all(text) if d]
    if not docs:
        return []
    lock = docs[-1]
    packages = {str(k).lstrip("/"): v or {} for k, v in (lock.get("packages") or {}).items()}
    snapshots = lock.get("snapshots")
    graph = {str(k).lstrip("/"): v or {} for k, v in snapshots.items()} if snapshots else packages

    importers = lock.get("importers") or {}
    if not importers and any(k in lock for k in ("dependencies", "devDependencies")):
        importers = {".": lock}  # older single-project layout

    prod_roots: list[tuple[str, str]] = []
    dev_roots: list[tuple[str, str]] = []
    for importer, spec in importers.items():
        for field_name, bucket in (
            ("dependencies", prod_roots),
            ("optionalDependencies", prod_roots),
            ("devDependencies", dev_roots),
        ):
            for dep, ref in ((spec or {}).get(field_name) or {}).items():
                ref = ref.get("version") if isinstance(ref, dict) else ref
                key = _ref_to_key(dep, ref) if ref is not None else None
                if key:
                    bucket.append((key, f"{importer} > {dep}"))
    prod = _walk(prod_roots, graph)
    dev = _walk(dev_roots, graph)

    result = []
    for key, entry in graph.items():
        parsed = _split_pnpm_key(key)
        if not parsed:
            continue
        name, version = parsed
        trail = prod.get(key) or dev.get(key)
        meta = packages.get(key.split("(", 1)[0], {})
        build = meta.get("requiresBuild", entry.get("requiresBuild"))
        resolution = meta.get("resolution")
        result.append(InstalledPackage(
            name=name,
            version=version,
            path=trail or key,
            depth=trail.count(" > ") if trail else 1,
            dev=(key in dev and key not in prod) or (not trail and bool(entry.get("dev"))),
            optional=bool(entry.get("optional")),
            has_install_script=bool(build) if build is not None else None,
            deps=list(entry.get("dependencies") or {}) + list(entry.get("optionalDependencies") or {}),
            resolved=str(resolution.get("tarball", "")) if isinstance(resolution, dict) else "",
        ))
    return result


# ---------------------------------------------------------------- scanning


def parse_lockfile(path: str | Path) -> list[InstalledPackage]:
    path = Path(path)
    if path.name == "pnpm-lock.yaml":
        return parse_pnpm_lock(path)
    return parse_package_lock(path)


def find_lockfiles(repo_dir: str | Path) -> list[Path]:
    found = []
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        found += [Path(root) / name for name in LOCKFILE_NAMES if name in files]
    return found


def _match(pkg: InstalledPackage, advisory: Advisory, ioc_names: set[str],
           repo: str, lockfile: str) -> Finding | None:
    refs = sorted(set(pkg.deps) & ioc_names)
    notes = [f"declares IOC dependency {', '.join(refs)}"] if refs else []
    if advisory.is_affected(pkg.name, pkg.version):
        reason = "affected-version"
    elif pkg.name in ioc_names:
        reason = "ioc-dependency"
        notes.append(f"IOC package, flagged at any version ({pkg.resolved or pkg.version})")
    elif refs:
        reason = "ioc-reference"  # not in the advisory yet, but carries the IOC
    else:
        return None
    return Finding(
        repo=repo, lockfile=lockfile, name=pkg.name, version=pkg.version, path=pkg.path,
        depth=pkg.depth, dev=pkg.dev, optional=pkg.optional,
        has_install_script=pkg.has_install_script, reason=reason, notes=notes,
    )


def scan_repo(repo_dir: str | Path, advisory: Advisory, name: str | None = None) -> RepoResult:
    repo_dir = Path(repo_dir)
    result = RepoResult(repo=name or repo_dir.name, path=str(repo_dir.resolve()))
    ioc_names = advisory.ioc_names
    for lockfile in find_lockfiles(repo_dir):
        rel = lockfile.relative_to(repo_dir).as_posix()
        result.lockfiles.append(rel)
        try:
            packages = parse_lockfile(lockfile)
        except (OSError, ValueError, AttributeError, TypeError, yaml.YAMLError) as exc:
            result.errors.append(f"{rel}: {exc}")
            continue
        for pkg in packages:
            finding = _match(pkg, advisory, ioc_names, result.repo, rel)
            if finding:
                result.findings.append(finding)
    return result


def scan_repos(repos: str | Path | list, advisory: Advisory, now: str | None = None) -> ScoutReport:
    """`repos` is either a directory whose subdirectories are repos, or a list of repo dirs."""
    if isinstance(repos, (str, Path)):
        repo_dirs = sorted(p for p in Path(repos).iterdir() if p.is_dir() and not p.name.startswith("."))
    else:
        repo_dirs = [Path(p) for p in repos]
    return ScoutReport(
        advisory=advisory.to_dict(),
        generated_at=now or utc_now(),
        repos=[scan_repo(d, advisory) for d in repo_dirs],
    )


# ---------------------------------------------------------------- room message


def summary_markdown(report: dict, max_lines: int = 10) -> str:
    """At most `max_lines` lines for the room. Full detail stays in the JSON."""
    adv = report["advisory"]
    repos = report["repos"]
    affected = [r for r in repos if r["findings"]]
    clean = [r["repo"] for r in repos if not r["findings"] and not r["errors"] and r["lockfiles"]]
    unscanned = [r for r in repos if not r["findings"] and (r["errors"] or not r["lockfiles"])]

    counts = f"Scanned {len(repos)} repos: **{len(affected)} affected**, {len(clean)} clean"
    if unscanned:
        counts += f", {len(unscanned)} not scanned"
    head = [f"**Scout** · {adv['id']}: {adv['title']}", counts + "."]
    body = []
    for r in affected:
        partial = f" (partial: {len(r['errors'])} lockfile errors)" if r["errors"] else ""
        body.append(f"- `{r['repo']}`: {_describe(r['findings'])}{partial}")
    for r in unscanned:
        why = "; ".join(r["errors"]) or "no lockfile found"
        body.append(f"- `{r['repo']}`: not scanned ({why})")
    tail = ["- Clean: " + ", ".join(f"`{c}`" for c in clean)] if clean else []

    room = max_lines - len(head) - len(tail)
    if len(body) > room:
        keep = max(room - 1, 0)
        body = body[:keep] + [f"- …and {len(body) - keep} more (see the scout JSON)"]
    return "\n".join(head + body + tail)


def _describe(findings: list[dict]) -> str:
    groups: dict[str, list[dict]] = {}
    for f in findings:
        if f["reason"] == "affected-version":
            groups.setdefault(f"{f['name']}@{f['version']}", []).append(f)
    parts = []
    for spec, fs in groups.items():
        flags = ["dev only" if all(f["dev"] for f in fs) else "prod"]
        if any(f["depth"] > 1 for f in fs):
            flags.append("nested")
        if any(f["has_install_script"] for f in fs):
            flags.append("install script")
        if len(fs) > 1:
            flags.append(f"{len(fs)} paths")
        parts.append(f"{spec} ({', '.join(flags)})")
    iocs = sorted({f["name"] for f in findings if f["reason"] == "ioc-dependency"})
    if iocs:
        parts.append("IOC package " + ", ".join(iocs))
    refs = sorted({f"{f['name']}@{f['version']}" for f in findings if f["reason"] == "ioc-reference"})
    if refs:
        parts.append("declares the IOC dependency but isn't in the advisory: " + ", ".join(refs))
    return "; ".join(parts)
