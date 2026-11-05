"""Postmortem: a blameless draft built from the tracker, its timeline, and the pipeline's JSON.

Every statement comes from recorded data; nothing is invented. The wording is
about systems, not people: running `npm install` is not negligence. The IC
signs off; this module only ever writes a draft.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import tracker, utc_now

DEFAULT_IC = "the IC"


def _parse(ts: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def duration(start: str | None, end: str | None) -> str:
    a, b = _parse(start), _parse(end)
    if not a or not b:
        return "n/a"
    secs = max(int((b - a).total_seconds()), 0)
    if secs < 60:
        return f"{secs}s"
    mins = secs // 60
    return f"{mins} min" if mins < 120 else f"{mins // 60} h {mins % 60} min"


def _when(ts: str) -> str:
    return ts.replace("T", " ").replace("Z", " UTC")


def _ic(state: dict) -> str:
    return next((t["containment_approved_by"] for t in state["teams"].values()
                 if t["containment_approved_by"]), DEFAULT_IC)


def _owners(team: dict) -> str:
    return ", ".join(team["owners"]) or "unassigned"


def build(state: dict, scout: dict | None = None, forensics: dict | None = None,
          plan: dict | None = None, now: str | None = None) -> str:
    now = now or utc_now()
    advisory = (forensics or scout or {}).get("advisory") or {"id": state["incident"], "title": state["incident"]}
    teams = state["teams"]
    counts = tracker.summary(state)
    ic = _ic(state)
    scout_repos = {r["repo"]: r for r in (scout or {}).get("repos", [])}
    exposure = {r["repo"]: r for r in (forensics or {}).get("repos", [])}
    items = [(name, key, item) for name, t in teams.items() for key, item in t["secrets"].items()]
    packages = sorted({a["name"] for a in advisory.get("affected", [])}) or ["the affected packages"]

    lines = [
        f"# Postmortem (draft): {advisory.get('title', state['incident'])}",
        "",
        f"**Incident:** {state['incident']} · **Status:** draft, not signed off by the IC ({ic}) "
        f"· **Written:** {_when(now)}",
        "",
        "Blameless by design: this describes systems and decisions, not people. "
        "Forensics measured exposure (what CI jobs could reach), not proof that anything was taken.",
        "",
        "## Summary",
        "",
    ]
    affected = [r for r in scout_repos.values() if r["findings"]] if scout else []
    repo_count = len(affected) if scout else len({r for t in teams.values() for r in t["repos"]})
    summary = (f"Malicious versions of {', '.join(f'`{p}`' for p in packages)} were published upstream "
               f"({advisory.get('id', state['incident'])}). {repo_count} of our repos installed an affected "
               f"version, across {counts['teams']} teams, and {counts['total']} credentials were referenced by "
               f"CI jobs that installed it. ")
    summary += (f"At the time of writing {counts['rotated']}/{counts['total']} are rotated, "
                f"{counts['blocked']} blocked, and {counts['teams_done']} of {counts['teams']} teams are done.")
    lines += [summary, ""]

    # ------------------------------------------------------------ impact
    lines += ["## Impact", "",
              "| Repo | Team | Bad version installed | Secrets exposed to installing jobs | Also |",
              "|---|---|---|---|---|"]
    repo_names = sorted(set(exposure) | {r["repo"] for r in affected} | {r for t in teams.values() for r in t["repos"]})
    for repo in repo_names:
        exp = exposure.get(repo, {})
        found = scout_repos.get(repo, {}).get("findings", [])
        versions = sorted({f"`{f['name']}@{f['version']}` ({'dev' if f['dev'] else 'prod'})"
                           for f in found if f["reason"] == "affected-version"})
        if any(f["reason"] == "ioc-dependency" for f in found):
            versions.append("IOC package")
        also = []
        for job in exp.get("jobs", []):
            label = f"`{Path(job['workflow']).name}`"
            if job["risky"]:
                also.append(f"{label}: PR code with secrets")
            if job["id_token_write"] and job["installs_deps"]:
                also.append(f"{label}: `id-token: write`")
        team = exp.get("team") or next((n for n, t in teams.items() if repo in t["repos"]), "unowned")
        lines.append(f"| `{repo}` | {team} | {', '.join(versions) or 'n/a'} | "
                     f"{', '.join(f'`{s}`' for s in exp.get('exposed_secrets', [])) or 'none'} | "
                     f"{'; '.join(also) or '-'} |")
    if scout and scout.get("clean_repos"):
        lines += ["", "Clean: " + ", ".join(f"`{r}`" for r in scout["clean_repos"]) + "."]
    lines.append("")

    # ------------------------------------------------------------ timeline
    events = []
    if scout:
        events.append((scout["generated_at"], "br-scout", f"Lockfiles scanned: {len(affected)} repos affected"))
    if forensics:
        events.append((forensics["generated_at"], "br-forensics",
                       f"CI exposure mapped for {len(forensics['repos'])} repos"))
    events += [(e["at"], e["actor"], e["event"]) for e in state["timeline"]]
    events.sort(key=lambda e: e[0])
    lines += ["## Timeline (UTC)", "", "| Time | Who | What |", "|---|---|---|"]
    lines += [f"| {_when(at).replace(' UTC', '')} | {who} | {what} |" for at, who, what in events]

    approvals = sorted(t["containment_approved_at"] for t in teams.values() if t["containment_approved_at"])
    rotated_at = sorted(i["updated_at"] for _, _, i in items if i["status"] == "rotated" and i["updated_at"])
    # Measure from the first scan when we have it: the tracker only opens once the IC approves.
    start, start_label = ((scout["generated_at"], "first scan") if scout else (state["created_at"], "tracker opened"))
    lines += ["", f"- {start_label.capitalize()} to containment approved: "
                  f"{duration(start, approvals[0]) if approvals else 'not approved yet'}"]
    if counts["total"] and counts["rotated"] == counts["total"]:
        lines.append(f"- {start_label.capitalize()} to every credential rotated: {duration(start, rotated_at[-1])}")
    else:
        lines.append(f"- Not finished: {counts['total'] - counts['rotated'] - counts['blocked']} pending, "
                     f"{counts['blocked']} blocked")
    lines.append("")

    # ------------------------------------------------------------ root cause
    lines += ["## Root cause", "",
              f"The root cause is upstream: malicious versions were published to the npm registry "
              f"({advisory.get('id', state['incident'])}). Any install that resolved to them ran attacker code with "
              "whatever credentials that machine or CI job could read. The useful question for us is why that "
              "code could reach so much. Contributing factors in our systems:", ""]
    findings = [f for r in affected for f in r["findings"]]
    if any(f["has_install_script"] or f["reason"] == "ioc-dependency" for f in findings) or not scout:
        lines.append("- Install scripts run by default, so installing a package was enough to execute it.")
    lines.append("- Nothing held back freshly published versions, so a release minutes old could be installed.")
    long_lived = sorted({k for _, k, i in items if i["category"] in ("npm", "identity", "cloud", "hosting", "secrets-manager", "ssh")})
    if long_lived:
        lines.append("- Long-lived credentials (" + ", ".join(f"`{k}`" for k in long_lived)
                     + ") were available to CI jobs that install third-party code.")
    dev_only = sorted({r["repo"] for r in affected
                       if all(f["dev"] for f in r["findings"] if f["reason"] == "affected-version")
                       and any(f["reason"] == "affected-version" for f in r["findings"])})
    if dev_only:
        lines.append("- Dev-only dependencies are still installed in CI and on laptops ("
                     + ", ".join(f"`{r}`" for r in dev_only) + ").")
    for repo, exp in sorted(exposure.items()):
        for job in exp["jobs"]:
            if job["risky"]:
                lines.append(f"- `{repo}` › `{Path(job['workflow']).name}` ran pull-request code with repo "
                             "secrets available (a pwn-request shape).")
    lines += ["", "Running `npm install` is not negligence: it is what our tooling and workflows ask people "
                  "to do. The fixes below change the systems, not the people.", ""]

    # ------------------------------------------------------------ went well / poorly
    well = []
    if scout:
        well.append(f"Lockfiles told us exactly which repos were affected: {len(affected)} of "
                    f"{len(scout_repos)} scanned, including nested and dev-only installs.")
    if exposure and all(e.get("team") for e in exposure.values()):
        well.append("Every affected repo mapped to an owner through CODEOWNERS, so no one had to be hunted down.")
    early = [(n, k) for n, k, i in items if i.get("rotated_before_approval")]
    if approvals and not early:
        well.append(f"Containment was approved by {ic} and recorded before any credential was revoked.")
    for name, t in teams.items():
        done = [i["updated_at"] for i in t["secrets"].values() if i["status"] == "rotated" and i["updated_at"]]
        if t["secrets"] and len(done) == len(t["secrets"]):
            well.append(f"Team {name} ({_owners(t)}) rotated all {len(done)} credentials, "
                        f"{duration(start, max(done))} after the {start_label}.")
    lines += ["## What went well", ""] + [f"- {w}" for w in well or ["Nothing recorded yet."]] + [""]

    poorly = []
    for name, key, item in items:
        if item["status"] == "blocked":
            poorly.append(f"`{key}` ({name}) is blocked: {item['note'] or 'no reason recorded'}.")
    for name, t in teams.items():
        if t["needs"]:
            poorly.append(f"Team {name} needed help: {t['needs']}.")
    for name, key in early:
        poorly.append(f"`{key}` ({name}) was rotated before containment was approved, so the new value may "
                      "have been exposed too.")
    unowned = sorted(r for r, e in exposure.items() if not e.get("team"))
    if unowned:
        poorly.append("No owner could be found for " + ", ".join(f"`{r}`" for r in unowned) + ".")
    if any(job["risky"] for e in exposure.values() for job in e["jobs"]):
        poorly.append("A pull-request workflow already ran untrusted code with secrets before this incident.")
    lines += ["## What went poorly", ""] + [f"- {p}" for p in poorly or ["Nothing recorded."]] + [""]

    # ------------------------------------------------------------ action items
    actions: list[tuple[str, str]] = []
    for name, key, item in items:
        if item["status"] != "rotated":
            actions.append((f"Finish rotating `{key}` ({', '.join(item['repos'])}); now {item['status']}",
                            _owners(teams[name])))
    tips: dict[str, list[str]] = {}
    for p in (plan or {}).get("plans", []):
        for tip in p["hardening"]:
            owners = tips.setdefault(tip, [])
            for o in p["owners"] or ["unassigned"]:
                if o not in owners:
                    owners.append(o)
    actions += [(tip, ", ".join(owners)) for tip, owners in tips.items()]
    actions.append(("Confirm with upstream which versions are safe and update the advisory file", ic))
    actions.append(("Review this draft and sign it off", ic))
    lines += ["## Action items", "", "| # | Action | Owner | Status |", "|---|---|---|---|"]
    lines += [f"| {n} | {action} | {owner} | open |" for n, (action, owner) in enumerate(actions, 1)]
    lines += ["", f"_Sign-off: {ic}, not yet signed._"]
    return "\n".join(lines)
