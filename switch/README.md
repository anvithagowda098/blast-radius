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
