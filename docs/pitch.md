# Blast Radius: pitch kit

Ready-to-use wording for the README, the video and the submission form. Every number here links to its source.

## One line

> **Blast Radius turns an npm supply-chain incident into Switch rooms: agents do the toil, people make the calls.**

## Why it matters: this keeps happening

Hijacks of popular, trusted npm packages now come roughly every two months:

| When | Incident | Source |
|---|---|---|
| 8 Sep 2025 | chalk, debug and other packages with billions of weekly downloads, via one phished maintainer | [Check Point](https://blog.checkpoint.com/crypto/the-great-npm-heist-september-2025/) |
| Sep 2025 | Shai-Hulud, the first self-spreading npm worm: 500+ packages | [CISA alert, 23 Sep 2025](https://www.cisa.gov/news-events/alerts/2025/09/23/widespread-supply-chain-compromise-impacting-npm-ecosystem) |
| Nov 2025 | Shai-Hulud 2.0: PostHog, Zapier, Postman and others | [PostHog postmortem](https://posthog.com/blog/nov-24-shai-hulud-attack-post-mortem), [Wiz](https://www.wiz.io/blog/shai-hulud-2-0-aftermath-ongoing-supply-chain-attack) |
| 11 May 2026 | TanStack: 84 malicious versions of 42 packages | [TanStack postmortem](https://tanstack.com/blog/npm-supply-chain-compromise-postmortem) |

Detection tools catch these within minutes. What doesn't scale is the response: the same chase, across every team and every secret, every time.

## The SRE angle

Incident response is a solved *discipline*. Blast Radius applies it to supply-chain incidents:

- **It removes toil.** Google SRE defines toil as work that is *"manual, repetitive, automatable, tactical, devoid of enduring value, and that scales linearly"* ([Google SRE book](https://sre.google/sre-book/eliminating-toil/)). Chasing 10 teams for 30 secrets is exactly that.
- **It uses standard incident roles.** The security lead is the Incident Commander; br-commander is the Deputy and Scribe ([PagerDuty incident roles](https://response.pagerduty.com/before/different_roles/)).
- **It turns the runbook into a workflow.** The same ordered checklist for every team, every incident: contain first, then rotate in a fixed order.
- **It ends with a blameless postmortem**, drafted from the record ([Google SRE: postmortem culture](https://sre.google/sre-book/postmortem-culture/)).

## 30-second pitch (spoken)

> A popular npm package gets hacked roughly every two months. Tools spot it in minutes, but then a security lead spends hours in Slack asking every team the same questions: did you install it, which secrets could leak, have you rotated them yet?
>
> Blast Radius turns that into Switch rooms. Agents find who's affected, open a room for each team, hand the owner an ordered checklist, and keep a live tracker. The security lead approves; the agents can't approve for them. Agents do the toil; people make the calls.

## Submission form

**Project title:** Blast Radius

**Project description** (what problem it solves, and who it's for):

> When a popular npm package is hijacked (it has happened roughly every two months since September 2025), detection takes minutes but the response takes hours: someone has to work out which projects installed the bad version, which CI secrets were exposed, who owns each project, and whether they've rotated. Blast Radius turns that response into Switch rooms. Agents run a tested Python core to find affected repos and exposed secrets, then, once the security lead approves, open one linked room per team, give each owner an ordered rotation checklist, track progress live ("4/7 secrets rotated") and draft a blameless postmortem. It's for security and platform teams responding to supply-chain incidents. Agents do the toil; people make the calls.

**How you used Switch:**

> Switch is the workflow itself. A v2 Switch template creates the `#sec-alerts` room, a room group, a `deputy` role, a runbook document and four Claude Code agents, and its kickoff starts the response. After the security lead approves in the room, br-commander creates one private room per affected team, links each to `#sec-alerts` both ways (incident / parent), invites the team owner and br-planner, takes the `deputy` role, and creates and owns the tracker document (only the creating agent can edit it). Addressing rules make br-commander answer only the security lead and their agents. In the live run, br-commander refused an approval that came from another agent and waited for the human. Owners report in their rooms in plain language, and br-planner turns their replies into tracker updates.

**What would break without Switch:**

> Everything that makes it a workflow. Without rooms, links, roles, addressing and room documents, you're back to one Slack thread, with no per-team space, no approval on record and no single tracker.

## Video: opening and closing lines

- **Open (0:00–0:15):** "A popular npm package gets hacked roughly every two months. Spotting it takes minutes. Cleaning it up takes hours of chasing people. This is Blast Radius."
- **Close (last 10 s):** "Same steps, every incident, for every team. Agents do the toil; people make the calls."
- **Track 02 line (optional, 10 s):** "And if you're a solo developer, the same checks run on your own projects and laptop."
