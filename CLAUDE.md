# CLAUDE.md: Blast Radius (Flip the Switch Hackathon)

Read this whole file before doing anything. It is the single source of truth for this project.

## 1. Who, what, when

- **Me:** Anvi (GitHub `anvithagowda098`), competing **solo**.
- **Event:** Flip the Switch Hackathon (WeMakeDevs × DevTools Academy × Switch by SandboxAQ).
- **Window:** Nov 4, 12:01 AM IST to **Nov 7, 11:59 PM IST**. **My own submission target is Nov 7, 6 PM IST.**
- **Rule:** existing libraries and agents are fine, but the **Switch setup and the agent workflow must be built during the hackathon.** Everything in this repo is built Nov 4–7.
- **I dictate with Wispr Flow** (that's the $500 "Code with Wispr" side track). My prompts may contain transcription typos: infer what I meant, and ask only if it's genuinely ambiguous.

### What I'm entering

| Prize | Entry | Status |
|---|---|---|
| **Track 01, Best Business Workflow ($2,000)** | **Blast Radius**, this repo | Main focus |
| Track 02, Best Personal/Creative ($2,000) | **Build Log Room**, a separate small repo (section 10) | **Gated:** only after Blast Radius runs end to end |
| Track 03, Core PRs | Already-open PRs to `sandbox-quantum/switch` | **No new PR work.** Only respond to review comments |
| Code with Wispr ($500) | Same project, built by voice | Insights screenshot at submission |
| Best Blog (AirPods), #HowISwitch | Tutorial blog + daily posts | Drafted from the Build Log Room |

## 2. Judging (optimise for this, in this order)

| Weight | Question judges ask | What that means here |
|---|---|---|
| **Use of Switch, 30%** | Is Switch central? Would it stop working without it? | Multiple rooms created by an agent, links, roles, approvals on record, addressing rules, shipped as a Switch **template** |
| **Technical execution, 25%** | Does it run? Can someone clone and reproduce it? | Deterministic Python core, tests, seed repos, one-command setup, a reset script |
| **Creativity and impact, 25%** | A fresh idea? A real team problem? | Real 2026 npm worm attacks. "Detection is solved, coordination isn't" |
| **Presentation, 20%** | Do the video and README make Switch's role clear? | README section "How Switch is used", diagram, 2:30 video |

**Cut order if time runs short:** Patcher's real GitHub PR, then OSV online lookup, then pnpm support. **Never cut:** the multi-room fan-out, human approvals, or the tracker.

## 3. The product in one paragraph

When an npm supply-chain attack drops (Shai-Hulud, the May 2026 TanStack compromise), detection takes about 20 minutes, but the response takes hours of chasing people in Slack: which repos installed the bad version, which CI secrets were exposed, who owns them, and whether they've rotated. **Blast Radius** turns that into Switch rooms.

1. An advisory lands in `#sec-alerts`.
2. **Scout** finds affected repos from lockfiles.
3. **Forensics** maps the exposed CI secrets and the owners.
4. The **security lead (human)** approves scope and containment.
5. **Commander** creates one linked room per affected team.
6. A **Rotation Planner** gives each **team owner (human)** an ordered checklist.
7. Commander keeps a live tracker ("4/7 secrets rotated") and writes a blameless postmortem.

Agents do the paperwork; humans make the calls.

**Positioning:** StepSecurity, Socket and Wiz detect. Blast Radius starts where their alert ends, coordinating owner-level remediation inside the team's chat. We do **not** do runtime network forensics: Forensics reports *exposure* (what a job could reach), not proof of exfiltration.

## 4. Environment: cloud first

- **You (Claude Code) run in a cloud environment** cloned from this GitHub repo. Build and test everything here: Python code, tests, seed data, the template YAML, agent instruction files, the README.
- **Assume no Docker and no Switch server in your environment.** Never claim you ran Switch. Anything that needs a live Switch server is tested by me on my machine, where Switch Console runs the agents.
- **Keep the core runnable offline** (no network needed for Scout or Forensics). OSV lookup is optional and must fail gracefully, falling back to the local advisory file.
- **Python 3.11+**, standard library plus `PyYAML`; `pytest` for tests. Keep dependencies minimal and pinned in `requirements.txt`.
- **Commit small, logical commits** with clear messages. Never force-push. Never commit secrets. Seed data uses obviously fake values like `FAKE_NPM_TOKEN`.

## 5. Repo layout to build

```
blast-radius/
├─ CLAUDE.md
├─ README.md
├─ requirements.txt
├─ blast_radius/
│  ├─ __init__.py
│  ├─ advisory.py      # parse advisories: pasted table, Wiz-style CSV, JSON; optional OSV MAL- lookup
│  ├─ scout.py         # lockfiles -> affected (repo, pkg@version, path, dev, hasInstallScript)
│  ├─ forensics.py     # workflows -> jobs installing deps, secrets referenced, id-token: write, risky triggers; CODEOWNERS -> owner
│  ├─ rotation.py      # exposed secrets -> ordered checklist per team (contain first)
│  ├─ tracker.py       # tracker state (JSON) + markdown render "4/7 rotated"
│  ├─ postmortem.py    # blameless postmortem markdown from tracker + timeline
│  └─ cli.py           # `python -m blast_radius <cmd>` entry points, output JSON + markdown
├─ seed/
│  ├─ advisories/tanstack-2026-05-11.json
│  ├─ owners.yml       # GitHub handle -> chat handle, team name
│  └─ repos/
│     ├─ web-app/        # @tanstack/react-router@1.169.5 top-level; release.yml with NPM_TOKEN + id-token: write
│     ├─ payments-api/   # @tanstack/history@1.161.9 nested; deploy.yml with AWS_ACCESS_KEY_ID
│     ├─ docs-site/      # affected only as devDependency; pull_request_target preview workflow (pwn-request shape)
│     └─ infra-tools/    # clean (control case), pnpm-lock.yaml v9
├─ switch/
│  ├─ blast-radius.template.yaml   # Switch template (v2), validate against Switch docs/TEMPLATES.md
│  └─ agents/                      # instruction files per agent (also pasted into the template)
│     ├─ scout.md  forensics.md  commander.md  planner.md  patcher.md
├─ scripts/
│  ├─ reset-demo.sh   # reset tracker state + seed repos so the demo can rerun
│  └─ demo.sh         # run the whole pipeline offline and print what each agent would post
├─ tests/
└─ docs/architecture.svg (or .png)
```

## 6. Component specs

### Seed advisory (real data)

These are from TanStack's postmortem and StepSecurity's table for the May 11, 2026 compromise:
- `@tanstack/react-router`: `1.169.5`, `1.169.8`
- `@tanstack/history`: `1.161.9`, `1.161.12`

IOCs:
- an `optionalDependencies` entry `@tanstack/setup` → `github:tanstack/router#79ac49eedf774dd4b0cfa308722bc463cfe5885c`
- the file `router_init.js` in the package root
- exfiltration to `filev2.getsession.org` and `seed{1,2,3}.getsession.org`

Guidance: anyone who installed must rotate AWS, GCP, Kubernetes, Vault, GitHub, npm and SSH credentials reachable from that host.

### Scout (`scout.py`)

- **`package-lock.json`, lockfile v2/v3:** read the `packages` map. Keys are install paths (`""` is the root; `node_modules/a/node_modules/b` is nested). The name is whatever follows the last `node_modules/`, and scoped names keep their slash. Capture the `version`, `dev`, `optional` and `hasInstallScript` fields.
- **v1 fallback:** walk the nested `dependencies` tree.
- **`pnpm-lock.yaml` v9:** keys look like `name@version`. Strip any peer suffix from the first `(`. **The file may contain multiple YAML documents:** load it with `yaml.safe_load_all` and take the last one.
- **Matching:** exact name + exact version. **Don't drop dev deps**, because install scripts run on laptops and CI too. Report every path.
- Also flag the `@tanstack/setup` IOC dependency regardless of version.
- **Output:** JSON (machine), plus a ≤10-line markdown summary for the room.

### Forensics (`forensics.py`)

- Parse `.github/workflows/*.yml` per affected repo.
- Per job: does it install deps (`npm install`, `npm ci`, `pnpm install`, `yarn`)? Which `secrets.X` are referenced (regex `secrets\.([A-Za-z0-9_]+)`)? Does it have `permissions: id-token: write`?
- Flag pwn-request shapes:
  - `pull_request_target` combined with checkout of `github.event.pull_request.head.sha`, `refs/pull/<n>/merge`, or `head.repo.full_name`;
  - `allow-unsafe-pr-checkout: true`;
  - `issue_comment` or `workflow_run` running PR code.
- **Wording:** say "referenced", never "stolen". An unset secret evaluates to an empty string.
- **CODEOWNERS:** search `.github/`, the root, then `docs/`, and use the first file found. A later matching line wins. Ignore invalid lines. The repo owner is whoever owns `/`, or `package.json` if that's more specific.
- Map GitHub handles to chat handles via `seed/owners.yml`.
- **Host check:** flag an unexpected `SessionStart` hook in `~/.claude/settings.json`. The open-sourced Mini Shai-Hulud worm persists this way. Include it as a checklist item for owners, since we can't scan their laptops.

### Rotation Planner (`rotation.py`)

Ordered checklist per team. **Step 1 is always "isolate the host / pause the CI runner", and it needs IC approval before any revoke step.** Then, following the Trigger.dev order:

1. Identity: the GitHub org and PATs.
2. The secrets manager.
3. Cloud (AWS / GCP).
4. Hosting (Vercel / Cloudflare).
5. Session blocks (AWS SSO can't be revoked; use a deny policy).
6. npm tokens (`npm token list` / `npm token delete <id>`; revocation can take up to an hour).
7. SSH keys.

Final item: "secrets nobody listed" (keys in trash, local `.env`, downloaded app keys).

**Hardening suggestions:** `ignore-scripts=true`; pnpm `minimumReleaseAge: 4320` or npm `min-release-age=3`; npm trusted publishing via OIDC; branch protection.

### Tracker (`tracker.py`)

- JSON state of team → secret → status (`pending`, `rotated`, `blocked`), plus owner and timestamps.
- Render as markdown for a Switch room document, with a header like `**4/7 secrets rotated** · 2 teams done · 1 blocked`.
- Owners report in **CAN format** (Condition, Actions, Needs). Parse simple replies like `rotated NPM_TOKEN`.

### Postmortem (`postmortem.py`)

A blameless markdown postmortem covering: summary, impact, timeline, root cause (the upstream compromise), what went well, what went poorly, and action items with owners. The wording focuses on systems, not people ("running `npm install` is not negligence").

### Patcher (stretch)

Pin the safe version and add `minimumReleaseAge` / `min-release-age`. In the demo, produce a branch plus diff in the seed repo. A real GitHub PR is optional. When run as a Claude Code agent, the instruction says to run with `--bare` semantics: never execute repo scripts, never `npm install` without `--ignore-scripts`.

## 7. Switch design (for the template and instructions; I test it live)

**Rooms**
- `#sec-alerts` is the main room.
- `br-<team>` rooms are created by Commander on IC approval, linked both ways (`incident` / `parent`).

**Agents** are Claude Code sessions run by my Switch Console. Each one's working directory is this repo, and they call the CLI.

| Agent | Role | Addressing |
|---|---|---|
| `br-scout` | Runs `python -m blast_radius scout …`, posts the summary | Anyone in the BR rooms |
| `br-forensics` | Runs forensics, posts exposure per repo | Anyone in the BR rooms |
| `br-commander` | Deputy, Scribe, Internal Liaison. Creates and links team rooms, invites owners and agents, keeps the tracker document, chases stalled owners, drafts the postmortem | **Owner (security lead) and owner_agents only** |
| `br-planner` | Posts each team's checklist and parses CAN replies into tracker updates | Anyone in the BR rooms |
| `br-patcher` | Stretch: fix branch and diff | Owner and owner_agents |

**Humans**
- **Security lead = Incident Commander (me).** Approves scope and containment and signs off the postmortem.
- **Two team owners**, played by friends on Discord/Mattermost. **Never use multiple accounts of my own** (it's against hackathon rules).

**Switch facts to respect**
- The template `kickoff` must `@` an agent, or nothing starts.
- An agent holds **one role at a time across all rooms**.
- Agents start closed: they answer only their owner and owner_agents.
- An unlinked chat account matches nobody.
- Links are one-way: create both directions. A link grants no access.
- An agent can attach a package only when it creates a room.
- Room documents can only be edited by the agent that created them. **Commander owns the tracker document.**
- Commands must start the message with `!`. Useful ones: `!agents-status`, `!roles`, `!list-documents`.
- Template keys: v2 `resources:` with `type: agent | room | group`, `params:`, and per-agent `provider`/`location`/`directory` (required). **Validate against `docs/TEMPLATES.md` in sandbox-quantum/switch.** Don't invent keys.

## 8. Working agreement

- **Explain before and after.** State the plan in 3–5 bullets, then build, then summarise what changed and how to verify it. I must be able to explain every line.
- **Tests for every module.** Use the seed repos as fixtures. Run `pytest` before saying anything is done.
- **Small diffs, clear commits.** No unrelated refactors.
- **Never post to GitHub** (comments, PRs, issues) or to any chat. Draft the text and I post it.
- **Be honest** about what's verified (ran here), what's untested (needs live Switch), and what's a guess.
- **Be concise.** No over-explaining.

## 9. Build order (check off as we go)

- [x] `seed/`: 4 repos, advisory JSON, `owners.yml`, CODEOWNERS, workflows
- [x] `advisory.py` + `scout.py` + tests
- [x] `forensics.py` + tests (secrets, `id-token`, pwn-request flags, CODEOWNERS last-match)
- [x] `rotation.py` + `tracker.py` + tests
- [x] `cli.py` + `scripts/demo.sh` (offline end to end: prints each agent's room message; `demo.sh` verified under Git Bash on a fresh clone; CI is manual-only until GitHub billing is fixed)
- [x] `switch/agents/*.md` instructions + `switch/blast-radius.template.yaml` (built by `scripts/build_template.py`; not yet imported into a live Switch)
- [x] `postmortem.py` + tests
- [x] `scripts/reset-demo.sh` (wraps `python -m blast_radius reset --seed`; verified on a fresh clone)
- [x] README (outline in section 11) + architecture diagram (GIF, Wispr screenshot and reference links still TODO)
- [ ] Stretch: Patcher, OSV lookup, pnpm edge cases

**Dates**
- **Nov 5:** everything through `cli.py`/`demo.sh`, plus agent instructions. I wire up Switch live.
- **Nov 6 AM:** template, postmortem, reset, README. **Freeze the code at Nov 6, 2 PM IST.**
- **Nov 7:** video by noon. Submit by 6 PM.

## 10. Track 02, Build Log Room (gated: separate repo, start only after Blast Radius runs end to end)

**A personal build-in-public workflow:**
1. I dictate a 30-second Wispr note into a Telegram room after each session.
2. A **Scribe** agent summarises that session's commits and diffs, plus the Blast Radius room history.
3. A **Writer** agent drafts the day's #HowISwitch post and a blog section.
4. A **Fact-checker** agent verifies every claim against the git log and flags anything unbacked.
5. I approve or edit, then post it myself.

Mostly instructions plus a template, so little code. **Time box: 6 hours on Nov 6 PM.** Its drafts become my blog and #HowISwitch content. Before submitting it, confirm in the WeMakeDevs Discord that two separate workflow projects are allowed.

## 11. README outline (presentation, 20%)

1. One-line pitch + a 30-second GIF.
2. The problem: TanStack (detected in about 26 minutes; the last tarball was pulled about 4.5 hours in) and Trigger.dev (an attacker inside for 17 hours). Coordination is the gap.
3. **How Switch is used:** rooms, links, roles, approvals, addressing, template. A diagram. One line on why it can't work without Switch.
4. Architecture: deterministic core vs agents vs humans.
5. Quickstart: `pip install -r requirements.txt`, `scripts/demo.sh` (offline), then the Switch setup: import the template in Switch Console, link accounts, run.
6. Demo script (what to type, in what order).
7. Positioning vs StepSecurity, Socket and Wiz, plus honest limits.
8. Built by voice with Wispr Flow (Insights screenshot).
9. References: the TanStack, Trigger.dev and PostHog postmortems, the Wiz Shai-Hulud 2.0 analysis, PagerDuty incident roles, Google SRE postmortems, and NIST SP 800-61r3.
