# Demo video: script and shot list

Target **2:40** (the hard limit is 3:00). About 330 spoken words.

The video has two parts:
- **0:00 to 1:45** walks through the real run from 6 November, already in Discord.
- **1:45 to 2:25** is **live**: a teammate reports two more keys, the tracker goes from 4/7 to 6/7, and I ask for the postmortem.

## Shots

| # | Time | On screen | Say |
|---|---|---|---|
| 1 | 0:00–0:15 | `docs/diagrams/how-it-works.png`, full screen | "A popular npm package gets hacked roughly every two months. Spotting it takes minutes. Cleaning it up takes hours of chasing people. This is Blast Radius." |
| 2 | 0:15–0:30 | GitHub README, the **This keeps happening** table | "In May, TanStack shipped 84 malicious versions across 42 packages. Every team that installed one has to answer the same questions: did we install it, which keys could leak, have we changed them? That chase is toil, and it's where Blast Radius starts." |
| 3 | 0:30–0:45 | Switch Console → Templates → the Blast Radius template (rooms, role, runbook, agents) | "Blast Radius is a Switch template. Importing it creates the sec-alerts room, a deputy role, a runbook and four Claude Code agents. Underneath is a tested Python core, so the facts come out the same on every run." |
| 4 | 0:45–1:25 | Discord `#sec-alerts`, scrolling slowly from the 19:07 alert. **Pause 2 s on the refusal.** Then my approval, the rooms opening, and `!roles`. | "This is our real run from the sixth of November. br-scout reads every lockfile: three of four repos installed a bad version. br-forensics reads the CI workflows: seven secrets those jobs could reach, and who owns each repo. Then my favourite moment. br-forensics' message reached br-commander, and it refused to act, because only the security lead can say go. I approve, and in under a minute br-commander opens a private room per team, links it back here, takes the deputy role and starts the tracker." |
| 5 | 1:25–1:45 | `#br-web`: the checklist, the owner's CAN reply, br-planner's tracker update | "In each team room, br-planner posts an ordered checklist: pause the runners first, then rotate in a fixed order. Owners reply in plain language, and br-planner turns that into tracker updates." |
| 6 | 1:45–2:25 | **LIVE.** `#br-payments`: teammate posts, br-planner replies. `#sec-alerts`: tracker refresh, then my postmortem request and the `Postmortem draft` document. | "That was yesterday. This is live. My teammate on payments reports two more keys. Six of seven. One is still blocked waiting on a Vault admin, and the tracker says exactly that. Now I ask br-commander for the postmortem. It's drafted from the record: blameless, with an owner on every action item." |
| 7 | 2:25–2:40 | Terminal: `bash scripts/demo.sh` scrolling, then `pytest -q` showing `105 passed` | "Everything except the chat also runs offline: one script replays the whole flow, and 105 tests pass. Same steps, every incident, for every team. Agents do the toil; people make the calls." |

Every number above is checked against the run's own files: `out/scout.json` (4 repos scanned, 3 affected), `out/tracker.json` (7 secrets, 4 rotated before the live part) and the timeline in the blog.

## The live part (shot 6)

**Teammate (payments owner) posts in `#br-payments`.** They type `@br-planner` and pick it from the autocomplete, then paste:

```
C: runners still paused · A: rotated NPM_READ_TOKEN and DEPLOY_SSH_KEY · N: Vault admin for VAULT_TOKEN
```

Dry-run on a copy of the live tracker (not the real file), the result is:

```
- NPM_READ_TOKEN: pending → rotated
- DEPLOY_SSH_KEY: pending → rotated
- VAULT_TOKEN: blocked → blocked (needs Vault admin for VAULT_TOKEN)
**6/7 secrets rotated** · 1 team done · 1 blocked
```

br-planner then tells br-commander, which refreshes the `Blast Radius tracker` document in `#sec-alerts`.

**Then I post in `#sec-alerts`** (dictated with Wispr Flow on camera, if it fits):

```
@br-commander draft the postmortem
```

br-commander runs `python -m blast_radius postmortem` and creates a `Postmortem draft` room document. Open it and scroll for 3 seconds.

Agents take tens of seconds to answer. Cut the waits in editing and put a small caption over the cut, such as "≈40 s later", so the timing stays honest.

## Before recording

1. **Ask both teammates** whether they're OK with their Discord usernames showing in a public video. The video has to show them, because the track asks for "the agent working in a real chat with your teammates".
2. **Agree a time with the payments teammate** and stay on a call during shot 6, so you can say "go".
3. **Start Switch Console:** Home → start the server, then check the Agents page shows all four agents running. Use Console rather than `!agents-status`, so nothing new appears in the chat.
4. **Turn on Do Not Disturb** in Windows (click the notification bell) and quit anything that pops up.
5. **Discord:** zoom to 125% (`Ctrl` + `=`) so text is readable on a phone, and collapse the member list.
6. **Terminal for shot 7:** open PowerShell in the repo, activate the venv and clear the screen:

   ```powershell
   & "$env:USERPROFILE\.venvs\blast-radius\Scripts\Activate.ps1"; cls
   ```

## Record, edit, upload

1. **Record each shot as its own clip** with the Snipping Tool: `Win` + `Shift` + `R`, drag over the window, switch the microphone on, then Start. Read that shot's line while you record. Retake any clip as many times as you like. Clips are saved in `Videos\Screen Recordings`.
2. **Record shot 6 in one continuous take,** because it's live.
3. **Shot 7 commands:**

   ```powershell
   python -m blast_radius demo
   python -m pytest -q
   ```

4. **Edit in Clipchamp** (it comes with Windows 11):
   - import the clips in order and trim the dead air;
   - add the "≈40 s later" captions over the cuts in shot 6;
   - check the total is under 3:00;
   - export at 1080p.
5. **Upload to YouTube as Unlisted,** then open the link in a private window to check that it plays.
