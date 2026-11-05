"""Tracker: team -> secret -> status, rendered as the Commander's room document.

Owners report in CAN format (Condition, Actions, Needs), or just say
"rotated NPM_TOKEN". Parsing is deliberately simple and word-based; anything
it can't match comes back as a warning instead of a silent guess.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import utc_now

STATUSES = ("pending", "rotated", "blocked")
ROTATED_WORDS = {"rotated", "revoked", "replaced", "deleted", "reissued", "regenerated", "rolled", "done"}
BLOCKED_WORDS = {"blocked", "stuck", "cannot", "can't", "cant", "unable", "waiting"}
PENDING_WORDS = {"pending", "todo", "reopen", "reopened"}
CONTAIN_WORDS = {"contained", "isolated", "paused", "disabled", "quarantined"}
NEGATIONS = {"not", "no", "never"}
NO_NEEDS = {"none", "nothing", "n/a", "na", "-", "no", "nope", "all good"}

# Owners start their reply by mentioning the agent ("@br-planner C: ..."); Discord may send "<@123>".
_LEADING_MENTIONS = re.compile(r"^\s*(?:(?:@[\w.-]+|<@!?\w+>)[\s,:]*)+")
_SECTION_RE = re.compile(r"(?:^|(?<=[\n·|]))\s*(condition|actions?|needs?|c|a|n)\s*:\s*", re.IGNORECASE)
_CLAUSE_SPLIT = re.compile(r"[,;.\n]|\band\b|\bbut\b|\bthen\b", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-z][a-z']*")
_UPPER_NAME_RE = re.compile(r"(?<![A-Za-z0-9_])[A-Z][A-Z0-9]*_[A-Z0-9_]*[A-Z0-9](?![A-Za-z0-9_])")


@dataclass
class ReplyResult:
    changes: list[dict] = field(default_factory=list)
    contained: bool = False
    needs: str = ""
    unknown: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- state


def init_state(plans: list, incident: str, now: str | None = None) -> dict:
    now = now or utc_now()
    teams = {}
    for plan in plans:
        plan = plan if isinstance(plan, dict) else plan.to_dict()
        teams[plan["team"]] = {
            "room": plan["room"],
            "owners": plan["owners"],
            "repos": plan["repos"],
            "containment_approved_by": None,
            "containment_approved_at": None,
            "contained": False,
            "contained_by": None,
            "contained_at": None,
            "needs": "",
            "secrets": {
                c["key"]: {
                    "names": c["names"], "aliases": c["aliases"], "category": c["category"],
                    "repos": c["repos"], "status": "pending",
                    "updated_at": None, "updated_by": None, "note": "",
                }
                for c in plan["credentials"]
            },
        }
    state = {"incident": incident, "created_at": now, "teams": teams, "timeline": []}
    total = sum(len(t["secrets"]) for t in teams.values())
    _log(state, now, "br-commander", f"Tracker opened: {total} secrets across {len(teams)} teams")
    return state


def load(path: str | Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found (run `tracker init` first)")
    return json.loads(path.read_text(encoding="utf-8"))


def save(state: dict, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _log(state: dict, at: str, actor: str, event: str) -> None:
    state["timeline"].append({"at": at, "actor": actor, "event": event})


def _team(state: dict, team: str) -> dict:
    try:
        return state["teams"][team]
    except KeyError:
        raise KeyError(f"unknown team {team!r}; teams: {', '.join(state['teams'])}") from None


def _patterns(item: dict) -> list[re.Pattern]:
    """NPM_TOKEN also matches 'npm token' and 'npm-token', but not MY_NPM_TOKEN."""
    pats = []
    for name in item["names"] + item.get("aliases", []):
        parts = [re.escape(p) for p in name.split("_") if p]
        pats.append(re.compile(r"(?<![A-Za-z0-9_])" + r"[\s_-]+".join(parts) + r"(?![A-Za-z0-9_])",
                               re.IGNORECASE))
    return pats


def _resolve_key(team_state: dict, secret: str) -> str:
    for key, item in team_state["secrets"].items():
        if any(p.fullmatch(secret) for p in _patterns(item)):
            return key
    raise KeyError(f"unknown secret {secret!r}; known: {', '.join(team_state['secrets'])}")


def _set(state: dict, team: str, key: str, status: str, actor: str, now: str,
         note: str = "", result: ReplyResult | None = None) -> dict | None:
    team_state = state["teams"][team]
    item = team_state["secrets"][key]
    old = item["status"]
    if old == status and not note:
        return None
    item.update(status=status, updated_at=now, updated_by=actor)
    item["note"] = note if note else ("" if status == "rotated" else item["note"])
    _log(state, now, actor, f"{team}: {key} {old} → {status}" + (f" ({note})" if note else ""))
    if status == "rotated" and not team_state["containment_approved_by"]:
        item["rotated_before_approval"] = True  # the postmortem reports this
        if result is not None:
            result.warnings.append(f"`{key}` marked rotated before the IC approved containment for {team}")
    change = {"team": team, "secret": key, "from": old, "to": status, "note": note}
    if result is not None:
        result.changes.append(change)
    return change


def set_status(state: dict, team: str, secret: str, status: str, actor: str,
               now: str | None = None, note: str = "") -> dict | None:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    team_state = _team(state, team)
    return _set(state, team, _resolve_key(team_state, secret), status, actor, now or utc_now(), note)


def approve_containment(state: dict, team: str, by: str, now: str | None = None) -> list[str]:
    """The IC's approval. `team` may be "all"."""
    now = now or utc_now()
    teams = list(state["teams"]) if team == "all" else [team]
    for name in teams:
        t = _team(state, name)
        t["containment_approved_by"], t["containment_approved_at"] = by, now
    _log(state, now, by, f"IC approved containment for {', '.join(teams)}")
    return teams


# ---------------------------------------------------------------- replies


def parse_can(text: str) -> dict:
    """Split a reply into Condition / Actions / Needs. Unlabelled text counts as Actions."""
    matches = list(_SECTION_RE.finditer(text))
    sections = {"condition": "", "actions": "", "needs": ""}
    if not matches:
        sections["actions"] = text.strip()
        return sections
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end():end].strip().strip("·|").strip()
        key = {"c": "condition", "a": "actions", "n": "needs"}[m.group(1)[0].lower()]
        sections[key] = f"{sections[key]} {body}".strip()
    lead = text[:matches[0].start()].strip()
    if lead:
        sections["actions"] = f"{lead} {sections['actions']}".strip()
    return sections


def _clauses(text: str) -> list[str]:
    return [c.strip() for c in _CLAUSE_SPLIT.split(text) if c.strip()]


def _read_clause(clause: str) -> tuple[str | None, bool]:
    words = _WORD_RE.findall(clause.lower())
    status = None
    for word in words:
        if word in ROTATED_WORDS:
            status = "rotated"
        elif word in BLOCKED_WORDS:
            status = "blocked"
        elif word in PENDING_WORDS:
            status = "pending"
    negated = any(w in NEGATIONS or w.endswith("n't") for w in words)
    if negated and status == "rotated":
        status = "pending"  # "haven't rotated X yet"
    contained = not negated and any(w in CONTAIN_WORDS for w in words)
    return status, contained


def _mentions(text: str, team_state: dict) -> list[str]:
    return [key for key, item in team_state["secrets"].items()
            if any(p.search(text) for p in _patterns(item))]


def apply_reply(state: dict, team: str, text: str, actor: str, now: str | None = None) -> ReplyResult:
    now = now or utc_now()
    team_state = _team(state, team)
    text = _LEADING_MENTIONS.sub("", text)
    sections = parse_can(text)
    result = ReplyResult()

    for clause in _clauses(sections["condition"]):
        _, contained = _read_clause(clause)
        if contained and not _mentions(clause, team_state):
            result.contained = True

    carry = None  # "rotated NPM_TOKEN and RELEASE_GH_PAT": the verb carries over
    for clause in _clauses(sections["actions"]):
        status, contained = _read_clause(clause)
        names = _mentions(clause, team_state)
        status = status or carry
        if names and status:
            for key in names:
                _set(state, team, key, status, actor, now, result=result)
        elif contained and not names:
            result.contained = True
        carry = status

    needs = sections["needs"].strip()
    if needs and needs.lower().strip(" .!") not in NO_NEEDS:
        result.needs = needs
        names = _mentions(needs, team_state)
        for key in names:
            _set(state, team, key, "blocked", actor, now, note=f"needs {needs}", result=result)
        if not names:
            team_state["needs"] = needs
            _log(state, now, actor, f"{team} needs: {needs}")

    if result.contained and not team_state["contained"]:
        team_state.update(contained=True, contained_by=actor, contained_at=now)
        _log(state, now, actor, f"{team}: containment confirmed by owner")

    pats = [p for item in team_state["secrets"].values() for p in _patterns(item)]
    result.unknown = sorted({t for t in _UPPER_NAME_RE.findall(text) if not any(p.fullmatch(t) for p in pats)})
    if result.unknown:
        result.warnings.append(f"unrecognised secret name(s) {', '.join(result.unknown)}; "
                               f"this team has {', '.join(team_state['secrets'])}")
    return result


# ---------------------------------------------------------------- rendering


def summary(state: dict) -> dict:
    items = [i for t in state["teams"].values() for i in t["secrets"].values()]
    done = sum(1 for t in state["teams"].values()
               if (all(i["status"] == "rotated" for i in t["secrets"].values())
                   if t["secrets"] else t["contained"]))
    return {
        "rotated": sum(i["status"] == "rotated" for i in items),
        "blocked": sum(i["status"] == "blocked" for i in items),
        "total": len(items),
        "teams_done": done,
        "teams": len(state["teams"]),
    }


def header(state: dict) -> str:
    s = summary(state)
    teams = "team" if s["teams_done"] == 1 else "teams"
    return f"**{s['rotated']}/{s['total']} secrets rotated** · {s['teams_done']} {teams} done · {s['blocked']} blocked"


def _short(ts: str | None) -> str:
    return f"{ts[11:16]} UTC" if ts and len(ts) >= 16 else (ts or "")


def render_markdown(state: dict) -> str:
    lines = [f"## Blast Radius tracker · {state['incident']}", header(state)]
    if state["timeline"]:
        last = state["timeline"][-1]
        lines.append(f"_Last update {_short(last['at'])} by {last['actor']}_")
    lines += ["", "| Team | Secret | Repos | Status | Updated |", "|---|---|---|---|---|"]
    for name, t in state["teams"].items():
        for item in t["secrets"].values():
            status = f"**{item['status']}**" if item["status"] == "blocked" else item["status"]
            updated = f"{_short(item['updated_at'])} {item['updated_by']}" if item["updated_at"] else "-"
            lines.append(f"| {name} ({', '.join(t['owners']) or '?'}) | `{' + '.join(item['names'])}` "
                         f"| {', '.join(item['repos'])} | {status} | {updated} |")
    lines += ["", "**Containment**"]
    for name, t in state["teams"].items():
        approved = f"approved by {t['containment_approved_by']}" if t["containment_approved_by"] else "awaiting IC approval"
        confirmed = f"confirmed by {t['contained_by']}" if t["contained"] else "not confirmed by the owner yet"
        lines.append(f"- {name}: {approved}; {confirmed}")
    blocked = [(n, k, i) for n, t in state["teams"].items() for k, i in t["secrets"].items() if i["status"] == "blocked"]
    needs = [(n, t["needs"]) for n, t in state["teams"].items() if t["needs"]]
    if blocked or needs:
        lines += ["", "**Blocked / needs**"]
        lines += [f"- {n} · `{k}`: {i['note'] or 'blocked'} ({i['updated_by']})" for n, k, i in blocked]
        lines += [f"- {n}: needs {need}" for n, need in needs]
    return "\n".join(lines)


def reply_markdown(result: ReplyResult, state: dict, team: str) -> str:
    lines = [f"**Tracker update** · team {team}"]
    for c in result.changes:
        lines.append(f"- `{c['secret']}`: {c['from']} → **{c['to']}**" + (f" ({c['note']})" if c["note"] else ""))
    if result.contained:
        lines.append(f"- {team}: containment confirmed")
    if result.needs and not any(c["to"] == "blocked" for c in result.changes):
        lines.append(f"- needs: {result.needs}")
    lines += [f"- warning: {w}" for w in result.warnings]
    if len(lines) == 1:
        lines.append("- no tracker changes: I couldn't match a secret name (try `rotated NPM_TOKEN`)")
    lines.append(header(state))
    return "\n".join(lines)
