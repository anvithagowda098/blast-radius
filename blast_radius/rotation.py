"""Rotation Planner: turn exposed secrets into an ordered checklist per team.

Order: contain first (needs IC approval), remove persistence, then rotate in
the Trigger.dev order (identity, secrets manager, cloud, hosting, session
blocks, npm, SSH), then local credentials, and last the secrets nobody listed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from .advisory import DEFAULT_ROTATE
from .forensics import AUTO_SECRETS

CATEGORY_ORDER = [
    "contain", "host-check",
    "identity", "secrets-manager", "cloud", "hosting", "sessions", "npm", "ssh", "other",
    "host-creds", "unlisted",
]
ROTATION_ORDER = ["identity", "secrets-manager", "cloud", "hosting", "sessions", "npm", "ssh", "other"]

# Secrets that are one credential: rotating one means rotating all of them.
CREDENTIAL_GROUPS = [("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")]
# Extra words owners may use for a credential in chat ("rotated the AWS access key").
ALIASES = {"AWS_ACCESS_KEY_ID": ["AWS_ACCESS_KEY", "AWS_KEY", "AWS_KEYS", "AWS_CREDENTIALS"]}

CATEGORY_TITLES = {
    "identity": "Identity", "secrets-manager": "Secrets manager", "cloud": "Cloud",
    "hosting": "Hosting", "npm": "npm", "ssh": "SSH", "other": "Other",
}
CATEGORY_GUIDE = {
    "identity": ("Revoke it in GitHub (Settings › Developer settings, or the org's PAT list) and issue a "
                 "narrower one; audit org PATs, OAuth apps and deploy keys.", []),
    "secrets-manager": ("Revoke the token, then any leases it issued.",
                        ["vault token revoke -accessor <accessor>", "vault lease revoke -prefix <mount>/"]),
    "cloud": ("Create the new key first, update the CI secret, deactivate the old key, check CloudTrail "
              "for its use, then delete it.",
              ["aws iam create-access-key --user-name <user>",
               "aws iam update-access-key --access-key-id <old-id> --status Inactive --user-name <user>"]),
    "hosting": ("Delete the token in the provider's dashboard and create a new, narrower one.", []),
    "npm": ("Revocation can take up to an hour to apply.", ["npm token list", "npm token delete <id>"]),
    "ssh": ("Install the new public key, then remove the old one (authorized_keys, deploy keys).",
            ["ssh-keygen -t ed25519 -f <new-key>"]),
    "other": ("Rotate it with the issuing service, then update the CI secret.", []),
}


def categorize(secret: str) -> str:
    name = secret.upper()
    parts = set(name.split("_"))
    if "SSH" in parts or "DEPLOY_KEY" in name:
        return "ssh"
    if "NPM" in parts or name.startswith("NODE_AUTH"):
        return "npm"
    if parts & {"GH", "GITHUB", "PAT"}:
        return "identity"
    if parts & {"VAULT", "DOPPLER", "INFISICAL"} or name.startswith("OP_"):
        return "secrets-manager"
    if parts & {"AWS", "GCP", "GCLOUD", "GOOGLE", "AZURE", "KUBE", "KUBECONFIG", "K8S"} or name.startswith("ARM_"):
        return "cloud"
    if parts & {"VERCEL", "CLOUDFLARE", "CF", "NETLIFY", "FLY", "RENDER", "HEROKU"}:
        return "hosting"
    return "other"


@dataclass
class Credential:
    key: str  # tracker id
    names: list[str]  # every secret name this credential covers
    aliases: list[str]
    category: str
    repos: list[str]
    jobs: list[str]


@dataclass
class Step:
    n: int
    category: str
    title: str
    detail: str = ""
    commands: list[str] = field(default_factory=list)
    credential: str | None = None
    requires_ic_approval: bool = False


@dataclass
class TeamPlan:
    team: str
    room: str
    owners: list[str]
    repos: list[str]
    credentials: list[Credential]
    steps: list[Step]
    hardening: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _job_label(repo: dict, job: dict) -> str:
    return f"{repo['repo']} › {Path(job['workflow']).name} › {job['job']}"


def collect_credentials(repos: list[dict]) -> list[Credential]:
    found: dict[str, dict] = {}
    for repo in repos:
        for job in repo["jobs"]:
            if not job["installs_deps"]:
                continue
            for secret in job["secrets"]:
                if secret in AUTO_SECRETS:
                    continue
                entry = found.setdefault(secret, {"repos": set(), "jobs": set()})
                entry["repos"].add(repo["repo"])
                entry["jobs"].add(_job_label(repo, job))
    credentials, grouped = [], set()
    for group in CREDENTIAL_GROUPS:
        present = [name for name in group if name in found]
        if not present:
            continue
        grouped.update(present)
        credentials.append(Credential(
            key=present[0], names=present, aliases=ALIASES.get(present[0], []),
            category=categorize(present[0]),
            repos=sorted(set().union(*(found[n]["repos"] for n in present))),
            jobs=sorted(set().union(*(found[n]["jobs"] for n in present))),
        ))
    for name, entry in found.items():
        if name not in grouped:
            credentials.append(Credential(name, [name], ALIASES.get(name, []), categorize(name),
                                          sorted(entry["repos"]), sorted(entry["jobs"])))
    credentials.sort(key=lambda c: (CATEGORY_ORDER.index(c.category), c.key))
    return credentials


def _host_check_detail(advisory: dict) -> str:
    iocs = advisory.get("iocs") or {}
    parts = ["Look for an unexpected `SessionStart` hook in `~/.claude/settings.json` "
             "(the open-sourced Mini Shai-Hulud worm persists this way)"]
    if iocs.get("files"):
        parts.append("payload files " + ", ".join(f"`{f}`" for f in iocs["files"]) + " under `node_modules/`")
    domains = sorted({".".join(d.split(".")[-2:]) for d in iocs.get("domains") or []})
    if domains:
        parts.append("connections to " + ", ".join(f"`*.{d}`" for d in domains))
    return "; ".join(parts) + ". Remove persistence first, or the new credentials leak too."


def _sessions_detail(credentials: list[Credential], oidc_jobs: list[str]) -> str:
    bits = []
    if any(n.startswith("AWS_") for c in credentials for n in c.names):
        bits.append("AWS sessions already issued outlive a key rotation: use IAM › Roles › Revoke active "
                    "sessions (a deny policy on `aws:TokenIssueTime`). AWS SSO sessions can't be revoked, "
                    "so attach the same kind of deny policy to the permission set")
    if oidc_jobs:
        bits.append("Jobs with `id-token: write` (" + ", ".join(oidc_jobs) + ") could mint OIDC tokens: "
                    "check which cloud roles and registries trust them, and revoke those sessions")
    return ". ".join(bits) + ("." if bits else "")


def _hardening(repos: list[dict], credentials: list[Credential]) -> list[str]:
    tips = [
        "`.npmrc`: `ignore-scripts=true` (allow-list the few packages that need install scripts)",
        "Hold back fresh releases: pnpm `minimumReleaseAge: 4320` or npm `min-release-age=3`",
    ]
    if any(c.category == "npm" for c in credentials):
        tips.append("Publish with npm trusted publishing (OIDC) and delete long-lived npm tokens")
    tips.append("Branch protection on the default branch; CODEOWNERS review for `.github/workflows/`")
    for repo in repos:
        for job in repo["jobs"]:
            if job["risky"]:
                tip = (f"`{repo['repo']}` › `{Path(job['workflow']).name}`: stop checking out PR code under "
                       "`pull_request_target`; build untrusted PRs with `pull_request` and no secrets")
                if tip not in tips:
                    tips.append(tip)
    return tips


def plan_team(team: str, repos: list[dict], advisory: dict) -> TeamPlan:
    repo_names = sorted(r["repo"] for r in repos)
    owners = sorted({h for r in repos for h in (r.get("chat_owners") or r.get("github_owners") or [])})
    credentials = collect_credentials(repos)
    oidc_jobs = [_job_label(r, j) for r in repos for j in r["jobs"] if j["installs_deps"] and j["id_token_write"]]
    steps: list[Step] = []

    def add(category, title, detail="", commands=(), credential=None, approval=False):
        steps.append(Step(len(steps) + 1, category, title, detail, list(commands), credential, approval))

    add("contain", "Contain: pause CI and isolate hosts that installed the bad version",
        f"Disable the affected workflows and pause self-hosted runners for "
        f"{', '.join(f'`{n}`' for n in repo_names)}; take developer machines that ran an install offline. "
        "Needs IC approval before any revoke step.",
        ["gh workflow disable <workflow> --repo <org>/<repo>"], approval=True)
    add("host-check", "Remove persistence before rotating", _host_check_detail(advisory),
        ["python -m blast_radius hostcheck"])
    for category in ROTATION_ORDER:
        if category == "sessions":
            detail = _sessions_detail(credentials, oidc_jobs)
            if detail:
                add("sessions", "Session blocks: cut off sessions that were already issued", detail)
            continue
        guide, commands = CATEGORY_GUIDE[category]
        for c in credentials:
            if c.category == category:
                names = " + ".join(f"`{n}`" for n in c.names)
                add(category, f"{CATEGORY_TITLES[category]}: rotate {names}",
                    f"Referenced by {'; '.join(c.jobs)}. {guide}", commands, credential=c.key)
    rotate = ", ".join(advisory.get("rotate") or DEFAULT_ROTATE)
    add("host-creds", "Developer machines: rotate local credentials",
        f"On every machine that ran an install with the bad version: {rotate} "
        "(AWS profiles, gcloud, kubeconfig, Vault token, `gh auth`, `~/.npmrc`, SSH keys).")
    inherited = [_job_label(r, j) for r in repos for j in r["jobs"] if j["inherits_all_secrets"]]
    unlisted = ("Old keys in trash or other CI systems, local `.env` files, downloaded app keys "
                "(GitHub App private keys, service-account JSON).")
    if inherited:
        unlisted += " These jobs inherit every repo secret, so list them from repo settings: " + "; ".join(inherited) + "."
    add("unlisted", "Secrets nobody listed", unlisted)
    return TeamPlan(team, f"br-{team}", owners, repo_names, credentials, steps, _hardening(repos, credentials))


def build_plans(forensics_report: dict) -> list[TeamPlan]:
    advisory = forensics_report.get("advisory") or {}
    by_team: dict[str, list[dict]] = {}
    for repo in forensics_report["repos"]:
        by_team.setdefault(repo.get("team") or "unowned", []).append(repo)
    return [plan_team(team, repos, advisory) for team, repos in sorted(by_team.items())]


def plan_markdown(plan: dict) -> str:
    owners = ", ".join(plan["owners"]) or "unassigned (IC to assign)"
    lines = [
        f"**Rotation checklist** · team **{plan['team']}** · owner {owners}",
        f"Repos: {', '.join(f'`{r}`' for r in plan['repos'])} · {len(plan['credentials'])} credentials "
        "to rotate. Contain first, then go in order.",
    ]
    for step in plan["steps"]:
        flag = " (needs IC approval)" if step["requires_ic_approval"] else ""
        lines.append(f"{step['n']}. [ ] **{step['title']}**{flag}")
        if step["detail"]:
            lines.append(f"   {step['detail']}")
        lines += [f"   `{cmd}`" for cmd in step["commands"][:2]]
    lines.append("**Hardening after the incident**")
    lines += [f"- {tip}" for tip in plan["hardening"]]
    # The mention stays outside the code span: inside one, Discord shows Switch's raw "<@&id>".
    lines.append("Report back here: mention @br-planner, then write in CAN format, e.g. "
                 "`C: runners paused · A: rotated NPM_TOKEN · N: Vercel admin for VERCEL_TOKEN`")
    return "\n".join(lines)
