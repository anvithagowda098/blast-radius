"""Command line entry points: `python -m blast_radius <command>`.

Each step reads the previous step's JSON from the state directory (`out/` by
default) and prints the markdown its agent posts to the room:

    scout -> forensics -> plan -> tracker init / approve / reply / show

`demo` runs the whole pipeline offline on the seed data and prints every room
message in order, with the human replies simulated.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import forensics, postmortem, rotation, scout, tracker
from .advisory import load_advisory

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "seed"
DEFAULT_ADVISORY = SEED / "advisories" / "tanstack-2026-05-11.json"
DEFAULT_REPOS = SEED / "repos"
DEFAULT_OWNERS = SEED / "owners.yml"
DEFAULT_OUT = ROOT / "out"

# (team, owner, reply, minutes after the first scan on the demo's simulated clock)
DEMO_REPLIES = [
    ("web", "@maya", "@br-planner C: release and preview workflows disabled, runner paused · "
                     "A: rotated NPM_TOKEN and RELEASE_GH_PAT · N: none", 34),
    ("payments", "@devon", "@br-planner Condition: deploys paused\nActions: rotated the AWS access key\n"
                           "Needs: Vault admin to revoke VAULT_TOKEN", 51),
    ("web", "@maya", "@br-planner rotated the vercel token", 68),
]


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path):
    if not path.is_file():
        raise SystemExit(f"error: {path} not found (run the previous step first)")
    return json.loads(path.read_text(encoding="utf-8"))


def _owners(path) -> forensics.OwnerDirectory | None:
    return forensics.OwnerDirectory.load(path) if path and Path(path).is_file() else None


def _print(text: str) -> None:
    print(text, flush=True)


# ---------------------------------------------------------------- pipeline steps


def cmd_scout(args) -> int:
    advisory = load_advisory(args.advisory)
    repos = [Path(p) for p in args.repo] if args.repo else Path(args.repos)
    report = scout.scan_repos(repos, advisory).to_dict()
    _write_json(Path(args.out) / "scout.json", report)
    _print(json.dumps(report, indent=2) if args.json else scout.summary_markdown(report))
    return 0


def cmd_forensics(args) -> int:
    report = forensics.run_forensics(_read_json(Path(args.out) / "scout.json"), _owners(args.owners))
    _write_json(Path(args.out) / "forensics.json", report)
    _print(json.dumps(report, indent=2) if args.json else forensics.forensics_markdown(report, repo=args.only))
    return 0


def cmd_plan(args) -> int:
    report = _read_json(Path(args.out) / "forensics.json")
    plans = [p.to_dict() for p in rotation.build_plans(report)]
    incident = (report.get("advisory") or {}).get("id", "incident")
    _write_json(Path(args.out) / "plan.json", {"tool": "plan", "incident": incident, "plans": plans})
    chosen = [p for p in plans if not args.team or p["team"] == args.team]
    if args.team and not chosen:
        raise SystemExit(f"error: no team {args.team!r}; teams: {', '.join(p['team'] for p in plans)}")
    _print(json.dumps(chosen, indent=2) if args.json else "\n\n".join(rotation.plan_markdown(p) for p in chosen))
    return 0


# ---------------------------------------------------------------- tracker


def _state_path(args) -> Path:
    return Path(args.out) / "tracker.json"


def _load_state(args) -> dict:
    try:
        return tracker.load(_state_path(args))
    except FileNotFoundError as exc:
        raise SystemExit(f"error: {exc}") from None


def _save_state(args, state: dict) -> None:
    tracker.save(state, _state_path(args))
    (Path(args.out) / "tracker.md").write_text(tracker.render_markdown(state) + "\n", encoding="utf-8")


def cmd_tracker_init(args) -> int:
    if _state_path(args).exists() and not args.force:
        raise SystemExit(f"error: {_state_path(args)} exists; pass --force to start over (progress is lost)")
    plan = _read_json(Path(args.out) / "plan.json")
    state = tracker.init_state(plan["plans"], plan.get("incident", "incident"))
    _save_state(args, state)
    _print(tracker.render_markdown(state))
    return 0


def cmd_tracker_approve(args) -> int:
    state = _load_state(args)
    try:
        tracker.approve_containment(state, args.team, args.by)
    except KeyError as exc:
        raise SystemExit(f"error: {exc.args[0]}") from None
    _save_state(args, state)
    _print(tracker.header(state))
    return 0


def cmd_tracker_reply(args) -> int:
    if args.text_file:
        # Agents save the owner's message to a file instead of putting chat text on a command line.
        path = Path(args.text_file)
        if not path.is_file():
            raise SystemExit(f"error: {path} not found")
        text = path.read_text(encoding="utf-8-sig")
    elif args.text:
        text = " ".join(args.text)
    else:
        raise SystemExit("error: give the reply text, or --text-file PATH")
    state = _load_state(args)
    try:
        result = tracker.apply_reply(state, args.team, text, args.actor)
    except KeyError as exc:
        raise SystemExit(f"error: {exc.args[0]}") from None
    _save_state(args, state)
    _print(tracker.reply_markdown(result, state, args.team))
    return 0


def cmd_tracker_set(args) -> int:
    state = _load_state(args)
    try:
        tracker.set_status(state, args.team, args.secret, args.status, args.actor, note=args.note)
    except (KeyError, ValueError) as exc:
        raise SystemExit(f"error: {exc.args[0]}") from None
    _save_state(args, state)
    _print(tracker.header(state))
    return 0


def cmd_tracker_show(args) -> int:
    state = _load_state(args)
    _print(json.dumps(tracker.summary(state)) if args.json else tracker.render_markdown(state))
    return 0


# ---------------------------------------------------------------- postmortem


def _optional_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _write_postmortem(out: Path, state: dict, now: str | None = None) -> str:
    text = postmortem.build(state, _optional_json(out / "scout.json"),
                            _optional_json(out / "forensics.json"), _optional_json(out / "plan.json"), now=now)
    (out / "postmortem.md").write_text(text + "\n", encoding="utf-8")
    return text


def cmd_postmortem(args) -> int:
    _print(_write_postmortem(Path(args.out), _load_state(args)))
    return 0


# ---------------------------------------------------------------- reset

STATE_FILES = ("scout.json", "forensics.json", "plan.json", "tracker.json", "tracker.md", "postmortem.md")
STATE_GLOBS = ("advisory-pasted.*",)
STATE_DIRS = ("inbox", "patches")


def reset_state(out: Path) -> list[Path]:
    """Delete only the files this tool writes, in `out` and `out/demo`. Anything else is left alone."""
    removed = []
    for folder in (out, out / "demo"):
        targets = [folder / name for name in STATE_FILES]
        targets += [p for pattern in STATE_GLOBS for p in folder.glob(pattern)]
        for path in targets:
            if path.is_file():
                path.unlink()
                removed.append(path)
        for name in STATE_DIRS:
            if (folder / name).is_dir():
                shutil.rmtree(folder / name)
                removed.append(folder / name)
    return removed


def reset_seed(root: Path = ROOT) -> str:
    """Discard changes under seed/repos (e.g. from br-patcher) with git. Touches nothing else."""
    if not (root / ".git").exists():
        return "seed/repos not reset: this checkout isn't a git repository"
    git = shutil.which("git")
    if not git:
        return "seed/repos not reset: git isn't installed"
    for cmd in (["restore", "--source=HEAD", "--staged", "--worktree", "--", "seed/repos"],
                ["clean", "-fd", "--", "seed/repos"]):
        result = subprocess.run([git, "-C", str(root), *cmd], capture_output=True, text=True)
        if result.returncode != 0:
            return f"seed/repos not reset: git {cmd[0]} failed: {result.stderr.strip()}"
    return "seed/repos restored to the last commit"


def cmd_reset(args) -> int:
    removed = reset_state(Path(args.out))
    _print(f"Removed {len(removed)} state file(s) from {args.out}" if removed else f"No state to remove in {args.out}")
    if args.seed:
        _print(reset_seed())
    return 0


# ---------------------------------------------------------------- host check + demo


def cmd_hostcheck(args) -> int:
    result = forensics.check_claude_settings(Path(args.settings).expanduser())
    _print(json.dumps(result, indent=2) if args.json else forensics.hostcheck_markdown(result))
    return 1 if result["suspicious"] else 0


def cmd_demo(args) -> int:
    out = Path(args.out)
    owners = forensics.OwnerDirectory.load(DEFAULT_OWNERS)
    ic = owners.security_lead.get("chat", "@ic")
    advisory = load_advisory(DEFAULT_ADVISORY)
    t0 = datetime.now(timezone.utc).replace(second=0, microsecond=0)

    def at(minutes: int) -> str:  # simulated clock, so the timeline and durations look real
        return (t0 + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")

    def post(room: str, who: str, body: str) -> None:
        _print(f"\n=== {room} · {who} ===\n{body}")

    _print("Blast Radius offline demo: every message below is what that agent or person would post in "
           "Switch. Times are simulated.")
    post("#sec-alerts", f"{ic} (IC, human)",
         f"Advisory: {advisory.title} ({advisory.id}). @br-scout which of our repos installed it?")

    scout_report = scout.scan_repos(DEFAULT_REPOS, advisory, now=at(0)).to_dict()
    _write_json(out / "scout.json", scout_report)
    post("#sec-alerts", "br-scout", scout.summary_markdown(scout_report))

    fr = forensics.run_forensics(scout_report, owners, now=at(2))
    _write_json(out / "forensics.json", fr)
    post("#sec-alerts", "br-forensics", forensics.forensics_markdown(fr))

    plans = [p.to_dict() for p in rotation.build_plans(fr)]
    _write_json(out / "plan.json", {"tool": "plan", "incident": advisory.id, "plans": plans})
    post("#sec-alerts", f"{ic} (IC, human)",
         f"Scope approved: {len(fr['repos'])} repos across {len(plans)} teams. Containment approved for all "
         "teams. @br-commander open the team rooms.")
    state = tracker.init_state(plans, advisory.id, now=at(9))
    tracker.approve_containment(state, "all", ic, now=at(9))
    rooms = ", ".join(f"`{p['room']}` ({', '.join(p['owners'])})" for p in plans)
    post("#sec-alerts", "br-commander",
         f"Opened {rooms}, each linked to #sec-alerts both ways (incident / parent), and invited the owner "
         "and br-planner. The tracker document is up and I'll keep it current.\n"
         "_(Simulated here: in Switch, the commander creates the rooms, links and invites.)_")

    for plan in plans:
        post(plan["room"], "br-planner", rotation.plan_markdown(plan))
    for team, who, text, minutes in DEMO_REPLIES:
        post(f"br-{team}", f"{who} (team owner, human)", text)
        result = tracker.apply_reply(state, team, text, who, now=at(minutes))
        post(f"br-{team}", "br-planner", tracker.reply_markdown(result, state, team))

    tracker.save(state, out / "tracker.json")
    (out / "tracker.md").write_text(tracker.render_markdown(state) + "\n", encoding="utf-8")
    post("#sec-alerts", "br-commander (tracker document)", tracker.render_markdown(state))
    post("#sec-alerts", f"{ic} (IC, human)", "@br-commander draft the postmortem.")
    post("#sec-alerts", "br-commander (document: Postmortem draft)", _write_postmortem(out, state, now=at(75)))
    _print(f"\nState written to {out}")
    return 0


# ---------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m blast_radius",
                                     description="Blast Radius: npm supply-chain incident coordination")
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name, func, help_text, out_default=DEFAULT_OUT, parent=sub):
        p = parent.add_parser(name, help=help_text, description=help_text)
        p.add_argument("--out", default=str(out_default), help=f"state directory (default: {out_default})")
        p.set_defaults(func=func)
        return p

    p = command("scout", cmd_scout, "Find affected installs in lockfiles; writes scout.json")
    p.add_argument("--advisory", default=str(DEFAULT_ADVISORY), help="advisory file (.json, .csv, or a pasted table)")
    p.add_argument("--repos", default=str(DEFAULT_REPOS), help="directory whose subdirectories are repos")
    p.add_argument("--repo", action="append", help="a single repo directory (repeatable; overrides --repos)")
    p.add_argument("--json", action="store_true", help="print JSON instead of the room summary")

    p = command("forensics", cmd_forensics, "Map CI exposure and owners for affected repos; writes forensics.json")
    p.add_argument("--owners", default=str(DEFAULT_OWNERS), help="owners.yml (GitHub handle -> chat handle, team)")
    p.add_argument("--only", help="print one repo only")
    p.add_argument("--json", action="store_true")

    p = command("plan", cmd_plan, "Build the ordered rotation checklist per team; writes plan.json")
    p.add_argument("--team", help="print one team's checklist only")
    p.add_argument("--json", action="store_true")

    tracker_parser = sub.add_parser("tracker", help="Tracker state: init, approve, reply, set, show")
    tsub = tracker_parser.add_subparsers(dest="tracker_command", required=True)
    p = command("init", cmd_tracker_init, "Create tracker.json from plan.json", parent=tsub)
    p.add_argument("--force", action="store_true", help="overwrite an existing tracker")
    p = command("approve", cmd_tracker_approve, "Record the IC's containment approval", parent=tsub)
    p.add_argument("--team", required=True, help='team name, or "all"')
    p.add_argument("--by", required=True, help="the IC's chat handle")
    p = command("reply", cmd_tracker_reply, "Apply an owner's CAN reply", parent=tsub)
    p.add_argument("--team", required=True)
    p.add_argument("--from", dest="actor", required=True, help="who sent the reply")
    p.add_argument("--text-file", help="read the reply from this file (what the agents use)")
    p.add_argument("text", nargs="*", help="the reply text")
    p = command("set", cmd_tracker_set, "Set one secret's status directly", parent=tsub)
    p.add_argument("--team", required=True)
    p.add_argument("--secret", required=True)
    p.add_argument("--status", required=True, choices=tracker.STATUSES)
    p.add_argument("--by", dest="actor", required=True)
    p.add_argument("--note", default="")
    p = command("show", cmd_tracker_show, "Print the tracker document", parent=tsub)
    p.add_argument("--json", action="store_true", help="print the counts as JSON")

    command("postmortem", cmd_postmortem, "Draft the blameless postmortem from the tracker; writes postmortem.md")

    p = command("hostcheck", cmd_hostcheck, "Check ~/.claude/settings.json for SessionStart hooks (run on your machine)")
    p.add_argument("--settings", default="~/.claude/settings.json")
    p.add_argument("--json", action="store_true")

    p = command("reset", cmd_reset, "Delete pipeline state so the demo can rerun (out/ and out/demo/)")
    p.add_argument("--seed", action="store_true",
                   help="also discard any changes under seed/repos (git restore + git clean, seed/repos only)")

    command("demo", cmd_demo, "Run the whole pipeline offline on the seed data", out_default=DEFAULT_OUT / "demo")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    args = build_parser().parse_args(argv)
    return args.func(args) or 0
