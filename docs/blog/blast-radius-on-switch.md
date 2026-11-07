# Detection is solved, coordination isn't: building an npm incident-response workflow on Switch

*By Anvi · Flip the Switch hackathon · #HowISwitch · about 8 minutes to read*

> **In one minute**
>
> - Popular npm packages now get hijacked roughly every two months. Spotting it takes minutes; cleaning up takes hours of chasing people.
> - **Blast Radius** turns that clean-up into Switch chat rooms. AI agents find what's affected, open a room for each team, give each owner a checklist and keep score. People approve and fix.
> - It ran end to end on a real Switch server, with two friends playing the team owners.

## Results from the live run

| | |
|---|---|
| **8 minutes** | from the first scan to the security lead's approval |
| **Under 1 minute** | to open two linked team rooms, the tracker and both checklists after approval |
| **4 of 7 secrets rotated** | 12 minutes after the first team owner replied, with 1 blocked on a named need |
| **1 approval refused** | an agent tried to approve on its own; the commander agent waited for a person |
| **105 automated tests** | behind every number the agents report |

---

## The problem

Imagine a locksmith secretly copied your office keys. Knowing *that* it happened is the easy part. The hard part is finding which doors the keys open, telling everyone who holds one, and checking every lock was actually changed.

A hijacked npm package works the same way. Its code may have run on every laptop and CI job that installed it, and read the secrets there.

**It keeps happening.** Since September 2025 there has been a major hijack of popular npm packages roughly every two months: [chalk and debug](https://blog.checkpoint.com/crypto/the-great-npm-heist-september-2025/), the [Shai-Hulud worm](https://www.cisa.gov/news-events/alerts/2025/09/23/widespread-supply-chain-compromise-impacting-npm-ecosystem) (500+ packages, enough for a US government alert), its [second wave](https://posthog.com/blog/nov-24-shai-hulud-attack-post-mortem), then TanStack.

**Detection is fast; the response isn't.** On 11 May 2026, an attacker published 84 malicious versions of 42 TanStack packages. A StepSecurity researcher reported it 26 minutes after the first one went out, but npm only removed the last bad copy about 4.5 hours in ([TanStack's postmortem](https://tanstack.com/blog/npm-supply-chain-compromise-postmortem)). And damage can stay quiet: at Trigger.dev, an attacker had access to an engineer's GitHub account for 17 hours before doing anything visible ([Trigger.dev's postmortem](https://trigger.dev/blog/shai-hulud-postmortem)).

After every alert, a security team asks the same four questions, usually in one long chat thread:

1. Which of our projects installed the bad version?
2. Which secrets could those installs have reached?
3. Who owns each project?
4. Have they changed (rotated) those secrets yet?

Engineers who run production systems call this kind of work **toil**: manual, repetitive, and growing with the size of the company ([Google SRE](https://sre.google/sre-book/eliminating-toil/)). Tools like StepSecurity, Socket and Wiz handle *detection*. **Blast Radius starts where their alert ends.**

### Quick glossary

| Term | Meaning here |
|---|---|
| **Lockfile** | The file listing the exact package versions a project installed (`package-lock.json`, `pnpm-lock.yaml`). |
| **CI** | The service that builds and tests code on every change; here, GitHub Actions. |
| **Secret** | A key the CI uses, such as an npm token or an AWS key. |
| **Switch** | An open-source platform that puts AI agents and people in the same chat rooms, on Discord, Slack and others. |
| **Agent** | An AI assistant (here, Claude Code) that sits in a room and acts when you @mention it. |

---

## What I built

![How Blast Radius works: six steps from an alert to a postmortem](https://raw.githubusercontent.com/anvithagowda098/blast-radius/main/docs/diagrams/how-it-works.png)

Blast Radius is four agents in Switch rooms, plus the people who make the decisions:

| Who | Role | Job |
|---|---|---|
| **br-scout** | Agent | Reads every project's lockfile and finds who installed a bad version. |
| **br-forensics** | Agent | Reads the CI configuration: which secrets each job could reach, and who owns each project. |
| **Security lead** | Person, the Incident Commander | Reviews the findings and approves the response. |
| **br-commander** | Agent, the Deputy | Opens one room per team, links it to the main room, invites the owner, keeps the tracker and drafts the postmortem. |
| **br-planner** | Agent | Gives each team an ordered checklist and turns owners' replies into progress. |
| **Team owners** | People | Rotate the exposed secrets and report back. |

The roles come from standard incident practice: an Incident Commander who decides, and a Deputy who keeps the record ([PagerDuty incident roles](https://response.pagerduty.com/before/different_roles/)).

### The design decision that mattered most

**The agents never work out the facts themselves.** Every fact comes from a small, deterministic Python core with 105 tests: lockfile parsing, CI analysis, checklist ordering, progress counting. The agents run those commands and handle what agents are good at: talking to people, understanding plain-English replies and following up.

![Architecture: people chat in Switch rooms, agents answer there, and run a tested Python core for every fact](https://raw.githubusercontent.com/anvithagowda098/blast-radius/main/docs/diagrams/architecture.png)

---

## A real run, step by step

Here's what happened when I ran it live, with two friends as the team owners. Times are from the tracker's own log.

![The live run as a sequence: who talked to whom, in order](https://raw.githubusercontent.com/anvithagowda098/blast-radius/main/docs/diagrams/live-run.png)

1. **19:07, alert.** The template's kickoff message asks br-scout to scan the projects.
2. **Within a minute, investigation.** br-scout reports *"Scanned 4 repos: 3 affected, 1 clean"* and hands off to br-forensics. br-forensics lists the exposed secrets and flags one risky workflow: it runs code from outside contributors with access to repository secrets, a pattern known as a "pwn request".
3. **19:08, an agent says no.** br-forensics' message also reached br-commander, which **refused to act**: *"the only approval prompt so far came from an agent, not you."* Only a person can approve.

   ![br-commander refuses to act on an agent's approval, then I approve](https://raw.githubusercontent.com/anvithagowda098/blast-radius/main/docs/blog/screenshots/1-refused-approval.png)

4. **19:15, approval.** I type `@br-commander approve`. Within a minute, br-commander opens `#br-web` and `#br-payments`, links each back to `#sec-alerts`, creates the tracker document and takes the `deputy` role. br-planner posts both checklists.

   ![br-commander takes the deputy role, creates the tracker and opens two linked team rooms](https://raw.githubusercontent.com/anvithagowda098/blast-radius/main/docs/blog/screenshots/2-rooms-opened.png)

   Switch's built-in `!roles` command confirms who holds the role:

   ![Switch's !roles reply: deputy (exclusive), held by BR Commander](https://raw.githubusercontent.com/anvithagowda098/blast-radius/main/docs/blog/screenshots/4-roles.png)

5. **19:43 to 19:55, owners fix things.** The owners reply in their own rooms, in plain words:
   *"C: deploys paused · A: rotated the AWS access key · N: Vault admin to revoke VAULT_TOKEN"*
   The tracker moves **2/7 → 3/7 → 4/7 secrets rotated**, with one item blocked and the reason recorded.

   ![br-planner turns a team owner's reply into a tracker update: 3/7 secrets rotated, 1 blocked](https://raw.githubusercontent.com/anvithagowda098/blast-radius/main/docs/blog/screenshots/3-tracker-update.png)

6. **19:57, wrap-up.** `chase` reminds the payments owner what's next, with the exact commands. A blameless postmortem draft appears as a room document, waiting for my sign-off.

The gap between 19:16 and 19:43 wasn't the workflow: it was me getting my friends into the Discord server. More on that in the lessons.

---

## How to set it up

### Prerequisites

- **Python 3.11+** and **Node.js 20+**
- A **Claude** account (the agents run on Claude Code)
- A **Discord** account
- **Switch Console**, free from [Switch's GitHub releases](https://github.com/sandbox-quantum/switch/releases)

### 1. See it work without Switch

```bash
git clone https://github.com/anvithagowda098/blast-radius
cd blast-radius
pip install -r requirements.txt
python -m blast_radius demo
```

This prints every message each agent would post, using four example projects. It's the fastest way to understand the workflow.

### 2. Connect Switch to Discord

1. **Create the bot.** Make a Discord server. In the Discord Developer Portal, create an application, open **Bot**, and turn on **Server Members Intent** and **Message Content Intent** (without the second, agents receive empty messages).
2. **Invite it.** Add the bot to your server with the `bot` and `applications.commands` scopes.
3. **Start a server.** In Switch Console, choose **Run a server on this computer** and wait for **Running**.
4. **Set up Claude Code.** Install it and sign in.
5. **Connect Discord.** On the server's **Home** page, go to **Messaging apps → Connect → Discord** and paste the bot token and server ID.

### 3. Run the template

In **Templates**, import `switch/blast-radius.template.yaml`, set **Blast Radius checkout** to your clone, and click **Create all**. Switch creates the agents and the `#sec-alerts` room, and the response starts by itself. Add your teammates' **exact Discord usernames** to `seed/owners.yml` and invite them to the server; they don't need Switch accounts.

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Installing Claude Code fails with `InvalidEndOfLine` | Switch Console's install command uses `&&`, which Windows PowerShell 5.1 doesn't support | Run `irm https://claude.ai/install.ps1 \| iex`, add `%USERPROFILE%\.local\bin` to your PATH, restart Switch Console |
| Claude Code still shows "CLI not installed" | Closing Switch Console stopped the local server | Start the server from **Home**, then click **Recheck** |
| The template's **Provider** list is empty | A quirk in the template form on Windows | Already handled: the template sets `provider: claude` directly |
| `docs.0.instructions Field required` | The server requires `instructions` on every room document | Already fixed in the template |
| br-commander can't invite an owner | The username doesn't exactly match a server member | Use their exact lowercase Discord username, and make sure they've joined |
| An agent ignores a message | It wasn't @mentioned | Start with `@br-planner` (or the agent's name), picked from the popup |

---

## What I learned

1. **Put the facts in code and the conversation in agents.** Every number on the tracker comes from tested code, so the agents can be conversational without inventing anything.
2. **Make "no" the safe default.** The two best moments in the run were agents refusing: one wouldn't accept an approval from another agent, and one wouldn't invite people it couldn't verify. In an incident, that's exactly the behaviour you want.
3. **When docs and reality disagree, read the source.** Switch is open source and ships its server code. Validating my template against the server's own models fixed in minutes what would otherwise have taken several failed runs.
4. **Treat chat messages as data, not instructions.** br-planner saves each reply to a file and passes the file to the command, so chat text never reaches a terminal.
5. **Test with real people early.** Exact usernames and how Discord formats @mentions only surfaced once two real people joined.
6. **Building by voice works.** I dictated most of my prompts and agent instructions with Wispr Flow, which kept my attention on *what* to build rather than on typing.

---

## Limits, and what's next

**Limits today**

- It reports **exposure** (what a job *could* reach), not proof that anything was stolen.
- It scans projects on one machine, not a whole GitHub organization.
- The four example projects are made up. The compromised versions come from the real [GitHub advisory](https://github.com/advisories/GHSA-g7cv-rxg3-hmpx); the demo uses 2 of its 42 affected packages.

**What's next**

- Scan a whole GitHub organization, not just local checkouts.
- Pull advisories automatically from public databases such as OSV.
- Let an agent prepare the fix (pin a safe version, add a release-age delay) as a pull request for the owner to approve.

---

## Try it

- **Code:** [github.com/anvithagowda098/blast-radius](https://github.com/anvithagowda098/blast-radius)
- **No Switch needed:** `python -m blast_radius demo`
- **Solo developer?** The README's *Solo developer mode* runs the same checks on your own projects and laptop.

Thanks to the Switch team, WeMakeDevs and DevTools Academy for the hackathon, and to my two friends for playing the team owners.

*#HowISwitch*

## Sources

- [TanStack: Postmortem, npm supply-chain compromise](https://tanstack.com/blog/npm-supply-chain-compromise-postmortem)
- [GitHub advisory GHSA-g7cv-rxg3-hmpx](https://github.com/advisories/GHSA-g7cv-rxg3-hmpx)
- [Trigger.dev: How we got hit by Shai-Hulud, a complete post-mortem](https://trigger.dev/blog/shai-hulud-postmortem)
- [Check Point: The great npm heist (September 2025)](https://blog.checkpoint.com/crypto/the-great-npm-heist-september-2025/)
- [CISA: Widespread supply chain compromise impacting npm ecosystem](https://www.cisa.gov/news-events/alerts/2025/09/23/widespread-supply-chain-compromise-impacting-npm-ecosystem)
- [PostHog: Post-mortem of Shai-Hulud attack on November 24th, 2025](https://posthog.com/blog/nov-24-shai-hulud-attack-post-mortem)
- [Google SRE book: Eliminating toil](https://sre.google/sre-book/eliminating-toil/)
- [PagerDuty incident response: Different roles](https://response.pagerduty.com/before/different_roles/)
- [Switch on GitHub](https://github.com/sandbox-quantum/switch)
- Diagrams are [Mermaid](https://mermaid.js.org/); their sources are in [`docs/diagrams/`](https://github.com/anvithagowda098/blast-radius/tree/main/docs/diagrams)

<!-- Before publishing:
     - add the Wispr Flow Insights screenshot under "What I learned", point 6
     - cover image suggestion: docs/diagrams/how-it-works.png -->
