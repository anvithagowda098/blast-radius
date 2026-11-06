# Switch setup

- `agents/*.md`: one instruction file per agent. These are the source.
- `template.base.yaml`: the template with an `@@agent@@` line where each
  instruction file goes.
- `blast-radius.template.yaml`: the built template you import in Switch
  Console. Rebuild it after editing either of the above:

```bash
python scripts/build_template.py
```

`tests/test_template.py` checks the built file against our reading of
`docs/TEMPLATES.md` (version 2): agent fields, placeholders, references, and
that every `python -m blast_radius` command in the instructions parses. It is
not Switch's validator. Importing the template in Switch Console is the real
check.

## Check these on the first live run

These follow from the docs but haven't been run against a Switch server:

1. **The template imports** without warnings. In particular, check `isolation: shared`,
   `allow_existing: true`, and `{$date}` in the group name.
2. **`owner-agents` lets the IC reach br-commander.** Likely fine: Console's
   agent form calls this setting "Only me and my agents". The IC must have
   linked their chat account, or the commander treats them as a stranger.
3. **`anyone_in: [sec_alerts]` admits agents.** br-scout hands off to
   br-forensics with an @mention. If that's refused, use `anyone`.
4. **br-commander can create rooms, links and room documents.** The docs say
   agents can create rooms and room-scoped documents. They don't say which agent
   operations create links.
5. **Team owners can reach br-planner.** It's set to `anyone` because the
   `br-<team>` rooms don't exist when the template runs. Owners must have
   linked chat accounts.
6. **Shared `out/`.** All agents share one checkout, and br-planner and
   br-commander both touch `out/tracker.json`. Fine for a demo pace, but
   simultaneous replies could race.
7. **`auto_approve` stays false**, so Claude Code may ask before running
   `python -m blast_radius ...`. Approve those in Console.

## Found on the first live run (Windows, Switch Console v0.40.1)

- **A `provider` param shows an empty picker on Windows.** The template form
  fills it from a check that marks every provider unavailable on Windows
  ("SDK sessions require a POSIX SSH execution host"). Adding a single agent
  from **Your Agents** uses a different check that does work. So each agent sets
  `provider: claude` directly instead of asking.
- **Console's built-in Claude Code install fails** in Windows PowerShell 5.1
  (its command uses `&&`). Install with `irm https://claude.ai/install.ps1 | iex`
  and add `%USERPROFILE%\.local\bin` to your user PATH, then restart Console.
- **Quitting Console stops the local server.** Start it again from Home before
  rechecking providers, or the agents controller can't report.
- **Room documents need `instructions`.** The server's `DocSpec` requires
  name, description, instructions and content, and rejects the whole run
  without them. `tests/test_template.py` now checks the fields the server's
  models require.
- **Discord turns `@br-planner` into a role mention, `<@&id>`.** Owner replies
  can start with it, so the reply parser strips it. Inside a code span Discord
  shows it raw, so the checklist keeps the mention outside its example.
- **Verified live:** kickoff → br-scout → br-forensics handoff; br-commander
  refusing an approval from an agent; after the IC's approval, two private team
  rooms in the group, linked both ways, the `deputy` role, the tracker document,
  and both checklists. Owners must be real Discord members with linked accounts
  before br-commander can invite them.
