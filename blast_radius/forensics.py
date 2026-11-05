"""Forensics: what could an affected repo's CI reach, and who owns the repo?

This reports *exposure* (what a job that installed dependencies could read),
never proof of exfiltration. A secret can be referenced but unset, in which
case it evaluates to an empty string. We say "referenced", never "stolen".
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from . import utc_now

SECRET_RE = re.compile(r"secrets\.([A-Za-z0-9_]+)|secrets\[\s*['\"]([A-Za-z0-9_]+)['\"]\s*\]")
AUTO_SECRETS = {"GITHUB_TOKEN"}  # minted per job, expires when the job ends
CODEOWNERS_LOCATIONS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")
PR_CODE_MARKERS = (
    "github.event.pull_request.head.sha",
    "github.event.pull_request.head.ref",
    "head.repo.full_name",
    "refs/pull/",
    "github.event.workflow_run.head_sha",
    "github.event.workflow_run.head_branch",
    "gh pr checkout",
)
NPM_INSTALL = {"install", "i", "ci", "add", "install-test", "it", "install-ci-test", "cit"}
PNPM_BUN_INSTALL = {"install", "i", "add"}
YARN_NOT_INSTALL = {"-v", "--version", "-h", "--help"}
OWNER_RE = re.compile(
    r"^(?:@[A-Za-z0-9][A-Za-z0-9-]*(?:/[A-Za-z0-9._-]+)?|[^@\s]+@[^@\s]+\.[^@\s]+)$"
)
SUSPICIOUS_HOOK = re.compile(
    r"router_init|getsession\.org|curl\s|wget\s|base64|node\s+-e|bun\s+-e|nohup|/tmp/",
    re.IGNORECASE,
)


# ---------------------------------------------------------------- workflows


@dataclass
class JobExposure:
    workflow: str  # path relative to the repo, e.g. .github/workflows/release.yml
    job: str
    triggers: list[str]
    installs_deps: bool
    install_commands: list[str]
    ignore_scripts: bool
    secrets: list[str]
    inherits_all_secrets: bool
    id_token_write: bool
    write_scopes: list[str]
    permissions_set: bool
    risky: list[str]


def install_commands(script: str) -> list[str]:
    """Commands in a `run:` script that install npm dependencies."""
    found = []
    for line in script.splitlines():
        for part in re.split(r"&&|\|\||[;|]", line):
            tokens = part.split()
            while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
                tokens.pop(0)  # FOO=bar npm ci
            if tokens and tokens[0] in ("sudo", "time", "exec"):
                tokens.pop(0)
            if not tokens or tokens[0].startswith("#"):
                continue
            tool, sub = tokens[0], tokens[1] if len(tokens) > 1 else ""
            if (
                (tool == "npm" and sub in NPM_INSTALL)
                or (tool in ("pnpm", "bun") and sub in PNPM_BUN_INSTALL)
                or (tool == "yarn" and (sub in ("", "install", "add")
                                        or (sub.startswith("-") and sub not in YARN_NOT_INSTALL)))
            ):
                found.append(" ".join(tokens))
    return found


def _uses_installer(step: dict) -> str | None:
    uses = str(step.get("uses", ""))
    options = step.get("with") or {}
    if "npm-install" in uses:  # e.g. bahmutov/npm-install
        return f"uses: {uses}"
    if uses.startswith("pnpm/action-setup") and str(options.get("run_install", "false")).lower() not in ("false", ""):
        return f"uses: {uses} (run_install)"
    return None


def _strings(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield str(key)
            yield from _strings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _strings(value)
    elif obj is not None:
        yield str(obj)


def _secrets_in(obj) -> set[str]:
    return {m.group(1) or m.group(2) for s in _strings(obj) for m in SECRET_RE.finditer(s)}


def _has_true_key(obj, key: str) -> bool:
    if isinstance(obj, dict):
        return any(
            (str(k) == key and str(v).lower() == "true") or _has_true_key(v, key)
            for k, v in obj.items()
        )
    if isinstance(obj, list):
        return any(_has_true_key(v, key) for v in obj)
    return False


def _triggers(wf: dict) -> list[str]:
    on = wf.get("on", wf.get(True))  # PyYAML reads a bare `on:` key as the boolean True
    if isinstance(on, str):
        return [on]
    if isinstance(on, list):
        return [str(x) for x in on]
    if isinstance(on, dict):
        return [str(k) for k in on]
    return []


def _id_token_write(perms) -> bool:
    return perms == "write-all" or (isinstance(perms, dict) and perms.get("id-token") == "write")


def _write_scopes(perms) -> list[str]:
    if perms == "write-all":
        return ["all"]
    if isinstance(perms, dict):
        return sorted(str(k) for k, v in perms.items() if str(v) == "write")
    return []


def analyze_workflow(path: str | Path, rel: str | None = None) -> list[JobExposure]:
    wf = yaml.safe_load(Path(path).read_text(encoding="utf-8-sig")) or {}
    if not isinstance(wf, dict):
        return []
    rel = rel or Path(path).name
    triggers = _triggers(wf)
    workflow_env_secrets = _secrets_in(wf.get("env"))
    jobs = []
    for job_id, job in (wf.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        commands = []
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            commands += install_commands(str(step.get("run", "")))
            uses = _uses_installer(step)
            if uses:
                commands.append(uses)
        perms = job.get("permissions", wf.get("permissions"))
        runs_pr_code = any(marker in s for s in _strings(job) for marker in PR_CODE_MARKERS)
        risky = []
        if "pull_request_target" in triggers and runs_pr_code:
            risky.append("pull_request_target checks out PR code: untrusted code runs with this repo's secrets (pwn request)")
        for trigger in ("issue_comment", "workflow_run"):
            if trigger in triggers and runs_pr_code:
                risky.append(f"{trigger} runs PR code with this repo's secrets (pwn request)")
        if _has_true_key(job, "allow-unsafe-pr-checkout"):
            risky.append("allow-unsafe-pr-checkout: true")
        jobs.append(JobExposure(
            workflow=rel,
            job=str(job_id),
            triggers=triggers,
            installs_deps=bool(commands),
            install_commands=commands,
            ignore_scripts=bool(commands) and all("--ignore-scripts" in c for c in commands),
            secrets=sorted(_secrets_in(job) | workflow_env_secrets),
            inherits_all_secrets=job.get("secrets") == "inherit",
            id_token_write=_id_token_write(perms),
            write_scopes=_write_scopes(perms),
            permissions_set=perms is not None,
            risky=risky,
        ))
    return jobs


# ---------------------------------------------------------------- CODEOWNERS


@dataclass
class CodeownersRule:
    pattern: str
    owners: list[str]
    line: int
    regex: re.Pattern


def _compile_pattern(pattern: str) -> re.Pattern:
    """gitignore-style matching, with GitHub's CODEOWNERS reading of `dir/*`."""
    if pattern in ("*", "**", "/", "/*", "/**"):
        return re.compile(r"^.*$")
    directory = pattern.endswith("/")
    core = pattern.strip("/")
    anchored = pattern.startswith("/") or "/" in core
    rx, i = "", 0
    while i < len(core):
        if core.startswith("**/", i):
            rx, i = rx + "(?:.*/)?", i + 3
        elif core.startswith("/**", i) and i + 3 == len(core):
            rx, i = rx + "/.*", i + 3
        elif core.startswith("**", i):
            rx, i = rx + ".*", i + 2
        elif core[i] == "*":
            rx, i = rx + "[^/]*", i + 1
        elif core[i] == "?":
            rx, i = rx + "[^/]", i + 1
        else:
            rx, i = rx + re.escape(core[i]), i + 1
    if directory:
        tail = "/.*"
    elif core.endswith("*"):
        tail = ""  # `docs/*` owns direct children only
    else:
        tail = "(?:/.*)?"  # a file, or everything under a directory
    head = "^" if anchored else "^(?:.*/)?"
    return re.compile(head + rx + tail + "$")


def parse_codeowners(text: str) -> tuple[list[CodeownersRule], list[int]]:
    """Returns (rules, invalid line numbers). GitHub skips invalid lines, so do we."""
    rules, invalid = [], []
    for number, raw in enumerate(text.splitlines(), 1):
        line = re.sub(r"(^|\s)#.*$", "", raw).strip()
        if not line:
            continue
        pattern, *owners = line.split()
        if (pattern.startswith(("!", "\\#")) or "[" in pattern or "]" in pattern
                or not all(OWNER_RE.match(o) for o in owners)):
            invalid.append(number)
            continue
        rules.append(CodeownersRule(pattern, owners, number, _compile_pattern(pattern)))
    return rules, invalid


def owners_for(rules: list[CodeownersRule], path: str) -> list[str]:
    owners: list[str] = []
    for rule in rules:  # the last matching rule wins
        if rule.regex.match(path):
            owners = rule.owners
    return list(owners)


def find_codeowners(repo_dir: str | Path) -> tuple[str | None, str]:
    for rel in CODEOWNERS_LOCATIONS:
        path = Path(repo_dir) / rel
        if path.is_file():
            return rel, path.read_text(encoding="utf-8-sig")
    return None, ""


@dataclass
class OwnerDirectory:
    """seed/owners.yml: GitHub handle -> {chat, team}."""

    owners: dict[str, dict]
    security_lead: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "OwnerDirectory":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        owners = {str(k).lower(): v or {} for k, v in (data.get("owners") or {}).items()}
        return cls(owners, data.get("security_lead") or {})

    def resolve(self, github_handle: str) -> dict | None:
        return self.owners.get(github_handle.lower())


# ---------------------------------------------------------------- per repo


@dataclass
class RepoExposure:
    repo: str
    path: str
    codeowners_file: str | None
    github_owners: list[str]
    chat_owners: list[str]
    team: str | None
    jobs: list[JobExposure]
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def job(self, workflow_file: str, job_id: str) -> JobExposure:
        for j in self.jobs:
            if Path(j.workflow).name == workflow_file and j.job == job_id:
                return j
        raise KeyError(f"{workflow_file}:{job_id}")

    @property
    def exposed_secrets(self) -> list[str]:
        """Secrets referenced by jobs that install dependencies."""
        return sorted({s for j in self.jobs if j.installs_deps for s in j.secrets} - AUTO_SECRETS)

    @property
    def referenced_not_exposed(self) -> list[str]:
        referenced = {s for j in self.jobs for s in j.secrets} - AUTO_SECRETS
        return sorted(referenced - set(self.exposed_secrets))

    def to_dict(self) -> dict:
        data = asdict(self)
        data["exposed_secrets"] = self.exposed_secrets
        data["referenced_not_exposed"] = self.referenced_not_exposed
        return data


def analyze_repo(repo_dir: str | Path, owners: OwnerDirectory | None = None,
                 name: str | None = None) -> RepoExposure:
    repo_dir = Path(repo_dir)
    jobs, errors, notes = [], [], []
    wf_dir = repo_dir / ".github" / "workflows"
    for path in sorted([*wf_dir.glob("*.yml"), *wf_dir.glob("*.yaml")]):
        try:
            jobs += analyze_workflow(path, path.relative_to(repo_dir).as_posix())
        except (OSError, yaml.YAMLError) as exc:
            errors.append(f"{path.name}: {exc}")

    co_file, co_text = find_codeowners(repo_dir)
    rules, invalid = parse_codeowners(co_text)
    if invalid:
        notes.append(f"{co_file}: skipped invalid lines {', '.join(map(str, invalid))}")
    github_owners = owners_for(rules, "package.json")  # falls back to the catch-all rule

    chat, team = [], None
    for handle in github_owners:
        entry = owners.resolve(handle) if owners else None
        if not entry:
            continue
        if entry.get("chat") and entry["chat"] not in chat:
            chat.append(entry["chat"])
        team = team or entry.get("team")
    return RepoExposure(
        repo=name or repo_dir.name, path=str(repo_dir.resolve()), codeowners_file=co_file,
        github_owners=github_owners, chat_owners=chat, team=team, jobs=jobs,
        notes=notes, errors=errors,
    )


def run_forensics(scout_report: dict, owners: OwnerDirectory | None = None,
                  now: str | None = None) -> dict:
    """Analyse every repo Scout flagged. Returns a JSON-ready dict."""
    repos = [
        analyze_repo(r["path"], owners, r["repo"])
        for r in scout_report["repos"] if r["findings"]
    ]
    return {
        "tool": "forensics",
        "generated_at": now or utc_now(),
        "advisory": scout_report.get("advisory", {}),
        "security_lead": owners.security_lead if owners else {},
        "repos": [r.to_dict() for r in repos],
    }


# ---------------------------------------------------------------- room message


def _job_line(job: dict) -> str:
    label = f"`{Path(job['workflow']).name}` › `{job['job']}`"
    secrets = [s for s in job["secrets"] if s not in AUTO_SECRETS]
    if job["installs_deps"]:
        bits = [f"installs deps (`{job['install_commands'][0]}`)"]
        if job["ignore_scripts"]:
            bits.append("with `--ignore-scripts` (install scripts blocked; code still runs if imported)")
        bits.append("secrets referenced: " + ", ".join(f"`{s}`" for s in secrets)
                    if secrets else "no secrets referenced")
    else:
        bits = ["no dependency install"]
        if secrets:
            bits.append("references " + ", ".join(f"`{s}`" for s in secrets) + " (not exposed by an install)")
    if job["inherits_all_secrets"]:
        bits.append("**inherits all secrets**")
    if job["id_token_write"]:
        bits.append("`id-token: write` (can mint OIDC tokens)")
    bits += [f"**{risk}**" for risk in job["risky"]]
    return f"- {label}: " + "; ".join(bits)


def forensics_markdown(report: dict, repo: str | None = None) -> str:
    lines = ["**Forensics** · exposure from CI config: what jobs could reach, not proof anything was taken"]
    repos = [r for r in report["repos"] if not repo or r["repo"] == repo]
    for r in repos:
        owner = ", ".join(r["chat_owners"]) or ", ".join(r["github_owners"]) or "**no owner found**"
        team = f" (team {r['team']})" if r["team"] else " (no team mapped: IC to assign)"
        via = f" via `{r['codeowners_file']}`" if r["codeowners_file"] else " (no CODEOWNERS)"
        lines.append(f"**`{r['repo']}`** · owner {owner}{team}{via}")
        lines += [_job_line(j) for j in r["jobs"]] or ["- no workflows found"]
    exposed = sum(len(r["exposed_secrets"]) for r in repos)
    teams = {r["team"] or "unowned" for r in repos}
    lines.append(
        f"Total: {exposed} secret references in jobs that install deps, across {len(repos)} repos "
        f"and {len(teams)} teams. A referenced secret may be unset (it then reads as an empty string)."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------- host check


def check_claude_settings(path: str | Path) -> dict:
    """Owners run this on their own machine: list SessionStart hooks in Claude Code settings."""
    path = Path(path)
    result = {"path": str(path), "exists": path.is_file(), "session_start_hooks": [],
              "suspicious": [], "error": ""}
    if not result["exists"]:
        return result
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        result["error"] = f"could not parse: {exc}"
        return result
    for group in ((data.get("hooks") or {}).get("SessionStart") or []):
        for hook in (group.get("hooks") or []) if isinstance(group, dict) else []:
            if isinstance(hook, dict) and hook.get("type") == "command":
                result["session_start_hooks"].append(str(hook.get("command", "")))
    result["suspicious"] = [c for c in result["session_start_hooks"] if SUSPICIOUS_HOOK.search(c)]
    return result


def hostcheck_markdown(result: dict) -> str:
    if result["error"]:
        return f"`{result['path']}`: {result['error']}"
    if not result["exists"]:
        return f"No Claude Code settings at `{result['path']}`: nothing to check."
    hooks = result["session_start_hooks"]
    if not hooks:
        return f"`{result['path']}`: no `SessionStart` hooks. OK."
    lines = [f"`{result['path']}`: {len(hooks)} `SessionStart` hook(s). Remove any you didn't add yourself:"]
    for command in hooks:
        flag = " **suspicious**" if command in result["suspicious"] else ""
        lines.append(f"- `{command}`{flag}")
    return "\n".join(lines)
