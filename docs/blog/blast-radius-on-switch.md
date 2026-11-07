# I turned a security emergency into a few chat rooms: building Blast Radius on Switch

*#HowISwitch · built for the Flip the Switch hackathon*

> **In one minute**
>
> - When a popular npm package gets hacked, finding out is fast. Cleaning up is slow, because someone has to chase every team.
> - I built **Blast Radius**: AI agents in Switch chat rooms work out what's affected, open a room for each team, and keep score while people fix things.
> - **Agents do the paperwork. People make the calls.**
> - It ran for real, with two friends playing team owners, in a Discord server connected to Switch.

---

## A few words you'll see

| Word | What it means here |
|---|---|
| **npm package** | A ready-made piece of JavaScript code that projects download and reuse. |
| **Lockfile** | A file in each project listing the exact package versions it installed (`package-lock.json`, `pnpm-lock.yaml`). |
| **CI** | The robot that builds and tests your code on every change (here, GitHub Actions). |
| **Secret** | A password or key the CI uses, like an npm token or an AWS key. |
| **Switch** | An open-source tool that puts AI agents and people in the same chat rooms (on Discord, Slack and others). |
| **Room** | A chat channel that Switch manages. |
| **Agent** | An AI assistant (here, Claude Code) that sits in a room and does a job when you @mention it. |

---

## The problem: finding out is fast, cleaning up is slow

Imagine a locksmith secretly copied your office keys. Knowing *that* it happened is step one. The hard part is working out which doors those keys open, telling every person who holds one, and checking that every lock has actually been changed.

A hacked npm package is the same. Its code may have run on every computer and CI job that installed it, and could have read the secrets there.

Here's a real example. On 11 May 2026, an attacker published 84 malicious versions of 42 TanStack packages. A StepSecurity researcher spotted it and reported it 26 minutes after the first one went out. But npm only removed the last bad copy about 4.5 hours in ([TanStack's postmortem](https://tanstack.com/blog/npm-supply-chain-compromise-postmortem)). Every hour in between is time when the bad code could still be installed, and secrets could leak.

And damage can stay quiet. At Trigger.dev, an attacker had access to an engineer's GitHub account for 17 hours before doing anything visible ([Trigger.dev's postmortem](https://trigger.dev/blog/shai-hulud-postmortem)).

After the alert, a security team has to answer, usually in one long chat thread:

1. Which of our projects installed the bad version?
2. Which secrets could those installs have reached?
3. Who owns each project?
4. Have they changed (rotated) those secrets yet?

Tools from companies like StepSecurity, Socket and Wiz handle the *detection*. **Blast Radius starts where their alert ends.**

---

## What I built

![How Blast Radius works: six steps from an alert to a postmortem](https://raw.githubusercontent.com/anvithagowda098/blast-radius/main/docs/diagrams/how-it-works.png)

Blast Radius is a small team of AI agents living in Switch rooms, plus the people who make decisions:

| Who | Person or agent? | Job |
|---|---|---|
| **br-scout** | Agent | Reads every project's lockfile and finds who installed a bad version. |
| **br-forensics** | Agent | Reads the CI settings: which secrets each job could reach, and who owns each project. |
| **You (security lead)** | Person | Read the findings and approve the response. |
| **br-commander** | Agent | Opens one room per team, links it to the main room, invites the owner, keeps the tracker. |
| **br-planner** | Agent | Gives each team an ordered checklist and records their progress. |
| **Team owners** | People | Change the leaked secrets and report back. |

**One design choice made everything easier:** the agents never *guess* what's affected. Every fact comes from small Python commands that I wrote and tested (100+ tests): reading lockfiles, reading CI files, ordering the checklist, counting progress. The agents run those commands and do what they're best at: talking to people, understanding plain-English replies, and following up.

---

## How a response plays out (a real run)

This is what happened when I ran it live, with two friends as the team owners. Times are from the tracker's own log.

![The live run as a sequence: who talked to whom, in order](https://raw.githubusercontent.com/anvithagowda098/blast-radius/main/docs/diagrams/live-run.png)

1. **19:07, alert.** Switch posts the kickoff in `#sec-alerts`, mentioning br-scout.
2. **Within a minute, investigation.** br-scout reports: *"Scanned 4 repos: 3 affected, 1 clean."* It hands off to br-forensics, which lists the exposed secrets and flags one risky workflow that runs outside code with secrets.
3. **19:08, the agent says no.** br-forensics' message also pinged br-commander. It **refused to act**: *"the only approval prompt so far came from an agent, not you."* An agent can't approve for another agent.

   ![br-commander refuses to act on an agent's approval, then I approve](https://raw.githubusercontent.com/anvithagowda098/blast-radius/main/docs/blog/screenshots/1-refused-approval.png)

4. **19:15, I approve.** I type `@br-commander approve`. Within a minute it opens `#br-web` and `#br-payments`, links each back to `#sec-alerts`, creates the tracker document, and br-planner posts both checklists.

   ![br-commander takes the deputy role, creates the tracker and opens two linked team rooms](https://raw.githubusercontent.com/anvithagowda098/blast-radius/main/docs/blog/screenshots/2-rooms-opened.png)

   Switch's built-in `!roles` command confirms who holds the deputy role:

   ![Switch's !roles reply: deputy (exclusive), held by BR Commander](https://raw.githubusercontent.com/anvithagowda098/blast-radius/main/docs/blog/screenshots/4-roles.png)

5. **Owners fix things.** My friends reply in their rooms in plain words:
   *"C: deploys paused · A: rotated the AWS access key · N: Vault admin to revoke VAULT_TOKEN"*
   The tracker updates each time: **2/7 → 3/7 → 4/7 secrets rotated**, with one item blocked waiting for help.

   ![br-planner turns a team owner's reply into a tracker update: 3/7 secrets rotated, 1 blocked](https://raw.githubusercontent.com/anvithagowda098/blast-radius/main/docs/blog/screenshots/3-tracker-update.png)

6. **19:57, wrap-up.** `chase` reminds the payments owner what's next. A blameless postmortem appears as a document, ready for my sign-off.

(The gap between 19:16 and the first reply was me getting my friends into the Discord server. More on that below.)

---

## How I set it up

### What you need

- A computer with **Python 3.11+** and **Node.js 20+**
- A **Claude** account (the agents run on Claude Code)
- A **Discord** account
- **Switch Console**, free from [Switch's GitHub releases](https://github.com/sandbox-quantum/switch/releases)

### Step 1: Try it without Switch first

```bash
git clone https://github.com/anvithagowda098/blast-radius
cd blast-radius
pip install -r requirements.txt
python -m blast_radius demo
```

This prints the whole story in your terminal, every message every agent would post, using four made-up example projects. It's the easiest way to see what Blast Radius does.

### Step 2: Make a Discord server and a bot

1. Create a Discord server.
2. In the Discord Developer Portal, create an **application**, open **Bot**, and turn on **Server Members Intent** and **Message Content Intent**. Without the second one, agents receive empty messages.
3. Invite the bot to your server with the `bot` and `applications.commands` scopes.

### Step 3: Install Switch Console and start a server

Install Switch Console, choose **Run a server on this computer**, and wait until it says **Running**.

### Step 4: Install and sign in to Claude Code

Switch Console can install it for you. If that fails on Windows, see the table below.

### Step 5: Connect Discord to Switch

On the server's **Home** page, under **Messaging apps**, click **Connect → Discord**, then paste your bot token and your server's ID.

### Step 6: Import the template and run it

In **Templates**, import `switch/blast-radius.template.yaml` from the repo. Set **Blast Radius checkout** to the folder you cloned, and click **Create all**. Switch creates the agents and the `#sec-alerts` room, and the response starts on its own.

### Step 7: Invite your teammates

Put your teammates' **exact Discord usernames** in `seed/owners.yml`, and invite them to the Discord server. That's all they need: no Switch account of their own.

### If you see this, do this

| You see | Why | Do this |
|---|---|---|
| Installing Claude Code fails with `InvalidEndOfLine` | Switch Console's install command uses `&&`, which Windows PowerShell 5.1 doesn't understand | Run `irm https://claude.ai/install.ps1 \| iex`, add `%USERPROFILE%\.local\bin` to your PATH, then restart Switch Console |
| Claude Code still shows "CLI not installed" | Closing Switch Console stopped the local server | Start the server again from **Home**, then click **Recheck** |
| The template's **Provider** list is empty | A Windows quirk in the template form | Already handled: the repo's template sets `provider: claude` directly |
| `docs.0.instructions Field required` | The server needs an `instructions` line on every room document | Already fixed in the repo's template |
| br-commander can't invite an owner | The username doesn't exactly match a member of the server | Use their exact lowercase Discord username, and make sure they've joined |
| An agent ignores a message | It wasn't @mentioned | Start with `@br-planner` (or the agent's name), picked from the popup |

---

## What I learned

1. **Let code find the facts, and let agents talk to people.** Every number on the tracker comes from tested code, so the agents can be friendly without making things up.
2. **Make "no" the safe default.** My two favourite moments were agents refusing: one wouldn't take an approval from another agent, and one wouldn't invite people it couldn't verify. In an emergency, that's what you want.
3. **When the docs and reality disagree, read the source.** Switch is open source and ships its server code. Checking my template against the server's own rules fixed in minutes what would otherwise have taken several failed runs.
4. **Treat chat messages as information, not instructions.** br-planner saves each reply to a file and passes the file to the command. It never pastes chat text into a terminal.
5. **Test with real people early.** Exact usernames and how Discord formats @mentions only showed up when two real friends joined.
6. **You can build by voice.** I dictated most of my prompts and instructions with Wispr Flow, which kept me thinking about *what* to build rather than typing.

---

## Honest limits

- It reports **exposure** (what a job *could* reach), not proof that anything was stolen.
- It scans projects on your computer, not a whole GitHub organization (yet).
- The four example projects are made up. The hacked versions come from the real [GitHub advisory](https://github.com/advisories/GHSA-g7cv-rxg3-hmpx); my demo uses 2 of its 42 affected packages.

---

## Try it yourself

- **Code:** https://github.com/anvithagowda098/blast-radius
- **No Switch needed:** `python -m blast_radius demo`
- **Solo developer?** The README's *Solo developer mode* runs the same checks on your own projects and laptop.

Thanks to the Switch team, WeMakeDevs and DevTools Academy for the hackathon, and to my two friends for playing team owners on short notice.

## Sources

- [TanStack: Postmortem, npm supply-chain compromise](https://tanstack.com/blog/npm-supply-chain-compromise-postmortem)
- [GitHub advisory GHSA-g7cv-rxg3-hmpx](https://github.com/advisories/GHSA-g7cv-rxg3-hmpx)
- [Trigger.dev: How we got hit by Shai-Hulud, a complete post-mortem](https://trigger.dev/blog/shai-hulud-postmortem)
- [Switch on GitHub](https://github.com/sandbox-quantum/switch)
- Diagrams are [Mermaid](https://mermaid.js.org/); their sources are in [`docs/diagrams/`](https://github.com/anvithagowda098/blast-radius/tree/main/docs/diagrams)

<!-- TODO before publishing:
     - add the Wispr Flow Insights screenshot -->
