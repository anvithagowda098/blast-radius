"""Parse supply-chain advisories into one shape that Scout can match against.

Accepted inputs, picked by file extension:

- ``.json``: the Blast Radius format (see ``seed/advisories/``), or an
  OSV-style record that uses ``affected[].package.name``
- ``.csv``: Wiz-style IOC exports with a package column and a version column
- anything else: a pasted table (markdown, tab or space separated, or
  ``name@version`` tokens)

Matching is exact name + exact version. OSV online lookup is a stretch goal
and isn't implemented yet.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ROTATE = ["AWS", "GCP", "Kubernetes", "Vault", "GitHub", "npm", "SSH"]
DEFAULT_GUIDANCE = (
    "Anyone who installed an affected version should treat every credential "
    "reachable from that host or CI job as exposed, and rotate it."
)

_SEMVER = r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?"
VERSION_RE = re.compile(r"(?<![\w.])v?(" + _SEMVER + r")(?!\w)")
FULL_VERSION_RE = re.compile(r"^" + _SEMVER + r"$")
# npm names are lowercase; requiring that keeps table headers like "Package" out.
NAME_RE = re.compile(r"^(?:@[a-z0-9~][a-z0-9._~-]*/)?[a-z0-9~][a-z0-9._~-]*$")

NAME_COLUMNS = ("package", "package_name", "package name", "name", "pkg", "library")
VERSION_COLUMNS = (
    "version", "versions", "package_version", "package_versions",
    "affected_versions", "affected versions", "version(s)",
)


@dataclass(frozen=True)
class IocDependency:
    """A dependency whose presence marks a compromise, at any version."""

    name: str
    spec: str = ""
    declared_in: str = "dependencies"


@dataclass
class Advisory:
    id: str
    title: str
    affected: dict[str, set[str]]
    ioc_dependencies: list[IocDependency] = field(default_factory=list)
    ioc_files: list[str] = field(default_factory=list)
    ioc_domains: list[str] = field(default_factory=list)
    rotate: list[str] = field(default_factory=lambda: list(DEFAULT_ROTATE))
    guidance: str = DEFAULT_GUIDANCE
    published: str = ""
    references: list[str] = field(default_factory=list)

    def is_affected(self, name: str, version: str) -> bool:
        return version in self.affected.get(name, ())

    @property
    def ioc_names(self) -> set[str]:
        return {dep.name for dep in self.ioc_dependencies}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "published": self.published,
            "affected": [
                {"name": name, "versions": sorted(versions)}
                for name, versions in sorted(self.affected.items())
            ],
            "iocs": {
                "dependencies": [
                    {"name": d.name, "spec": d.spec, "field": d.declared_in}
                    for d in self.ioc_dependencies
                ],
                "files": list(self.ioc_files),
                "domains": list(self.ioc_domains),
            },
            "rotate": list(self.rotate),
            "guidance": self.guidance,
            "references": list(self.references),
        }


def load_advisory(path: str | Path) -> Advisory:
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    suffix = path.suffix.lower()
    if suffix == ".json":
        return parse_json(text, default_id=path.stem)
    if suffix == ".csv":
        return parse_csv(text, default_id=path.stem)
    return parse_table(text, default_id=path.stem)


def parse_json(text: str, default_id: str = "advisory") -> Advisory:
    data = json.loads(text)
    affected: dict[str, set[str]] = {}
    for item in data.get("affected", []):
        name = item.get("name") or (item.get("package") or {}).get("name")
        if name:
            _add(affected, name, [str(v).strip() for v in item.get("versions", [])])
    iocs = data.get("iocs") or {}
    guidance = data.get("guidance") or {}
    if isinstance(guidance, str):
        guidance = {"text": guidance}
    return Advisory(
        id=data.get("id") or default_id,
        title=data.get("title") or data.get("summary") or default_id,
        affected=affected,
        ioc_dependencies=[
            IocDependency(d["name"], d.get("spec", ""), d.get("field", "dependencies"))
            for d in iocs.get("dependencies", [])
            if d.get("name")
        ],
        ioc_files=list(iocs.get("files", [])),
        ioc_domains=list(iocs.get("domains", [])),
        rotate=list(guidance.get("rotate") or DEFAULT_ROTATE),
        guidance=guidance.get("text") or DEFAULT_GUIDANCE,
        published=str(data.get("published", "")),
        references=[
            r if isinstance(r, str) else r.get("url", "") for r in data.get("references", [])
        ],
    )


def parse_csv(text: str, default_id: str = "advisory") -> Advisory:
    reader = csv.DictReader(io.StringIO(text))
    columns = {(c or "").strip().lower(): c for c in (reader.fieldnames or [])}
    name_col = next((columns[c] for c in NAME_COLUMNS if c in columns), None)
    version_col = next((columns[c] for c in VERSION_COLUMNS if c in columns), None)
    if not name_col or not version_col:
        # No recognisable header: treat it like a pasted table.
        return parse_table(text, default_id)
    affected: dict[str, set[str]] = {}
    for row in reader:
        name, inline_version = _split_spec((row.get(name_col) or "").strip())
        versions = VERSION_RE.findall(row.get(version_col) or "")
        if inline_version:
            versions.append(inline_version)
        if name and versions:
            _add(affected, name, versions)
    return Advisory(id=default_id, title=default_id, affected=affected)


def parse_table(text: str, default_id: str = "advisory") -> Advisory:
    """Read one package per line; versions are any semver tokens after its name."""
    affected: dict[str, set[str]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or set(line) <= set("|-:+= "):
            continue
        name: str | None = None
        versions: list[str] = []
        for token in re.split(r"[\s|,;]+", line):
            token = token.strip("`'\"()[]*")
            if not token:
                continue
            pkg, version = _split_spec(token)
            if pkg and version and name and pkg != name:
                _add(affected, pkg, [version])  # a second name@version on the same line
                continue
            if pkg and name is None:
                name = pkg
            if version and name:
                versions.append(version)
        if name and versions:
            _add(affected, name, versions)
    return Advisory(id=default_id, title=default_id, affected=affected)


def _add(affected: dict[str, set[str]], name: str, versions: list[str]) -> None:
    affected.setdefault(name, set()).update(v for v in versions if v)


def _clean_version(value: str) -> str | None:
    v = value.strip().lstrip("=").strip()
    if v[:1] in ("v", "V"):
        v = v[1:]
    return v if FULL_VERSION_RE.match(v) else None


def _split_spec(token: str) -> tuple[str | None, str | None]:
    """'name@1.2.3' -> (name, '1.2.3'); '1.2.3' -> (None, '1.2.3'); 'name' -> ('name', None)."""
    version = _clean_version(token)
    if version:
        return None, version
    at = token.rfind("@")
    if at > 0:
        name, version = token[:at], _clean_version(token[at + 1:])
        if version and NAME_RE.match(name):
            return name, version
    if NAME_RE.match(token):
        return token, None
    return None, None
