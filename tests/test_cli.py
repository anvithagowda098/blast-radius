import json

import pytest

from blast_radius import cli


def test_demo_end_to_end(tmp_path, capsys):
    assert cli.main(["demo", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    for speaker in ("=== #sec-alerts · br-scout ===", "=== #sec-alerts · br-forensics ===",
                    "=== br-web · br-planner ===", "=== br-payments · br-planner ===",
                    "=== #sec-alerts · br-commander (tracker document) ==="):
        assert speaker in out
    assert "**4/7 secrets rotated** · 1 team done · 1 blocked" in out
    assert "warning" not in out
    assert "=== #sec-alerts · br-commander (document: Postmortem draft) ===" in out
    for name in ("scout.json", "forensics.json", "plan.json", "tracker.json", "tracker.md", "postmortem.md"):
        assert (tmp_path / name).is_file()


def test_step_by_step_like_the_agents(tmp_path, capsys):
    out = ["--out", str(tmp_path)]
    assert cli.main(["scout", *out]) == 0
    assert "**3 affected**" in capsys.readouterr().out
    assert cli.main(["forensics", *out]) == 0
    assert cli.main(["plan", "--team", "payments", *out]) == 0
    assert "team **payments**" in capsys.readouterr().out
    assert cli.main(["tracker", "init", *out]) == 0
    with pytest.raises(SystemExit):
        cli.main(["tracker", "init", *out])  # refuses to wipe progress
    assert cli.main(["tracker", "approve", "--team", "all", "--by", "@anvi", *out]) == 0
    capsys.readouterr()
    assert cli.main(["tracker", "reply", "--team", "web", "--from", "@maya", "rotated", "NPM_TOKEN", *out]) == 0
    assert "**1/7 secrets rotated**" in capsys.readouterr().out
    assert cli.main(["tracker", "set", "--team", "payments", "--secret", "VAULT_TOKEN",
                     "--status", "blocked", "--by", "@devon", "--note", "needs Vault admin", *out]) == 0
    assert cli.main(["tracker", "show", "--json", *out]) == 0
    counts = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert counts == {"rotated": 1, "blocked": 1, "total": 7, "teams_done": 0, "teams": 2}
    assert "VAULT_TOKEN" in (tmp_path / "tracker.md").read_text(encoding="utf-8")


def test_reply_from_text_file(tmp_path, capsys):
    out = ["--out", str(tmp_path)]
    cli.main(["demo", *out])
    capsys.readouterr()
    reply = tmp_path / "inbox" / "payments-1.txt"
    reply.parent.mkdir()
    reply.write_text("A: revoked DEPLOY_SSH_KEY; $(rm -rf ~) `whoami`\n", encoding="utf-8")
    assert cli.main(["tracker", "reply", "--team", "payments", "--from", "@devon",
                     "--text-file", str(reply), *out]) == 0
    assert "**5/7 secrets rotated**" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["tracker", "reply", "--team", "payments", "--from", "@devon", *out])


def test_reset_removes_only_our_state(tmp_path, capsys):
    cli.main(["demo", "--out", str(tmp_path / "demo")])
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "web-1.txt").write_text("rotated NPM_TOKEN", encoding="utf-8")
    (tmp_path / "advisory-pasted.txt").write_text("x@1.0.0", encoding="utf-8")
    keep = tmp_path / "notes.txt"
    keep.write_text("mine", encoding="utf-8")
    capsys.readouterr()

    assert cli.main(["reset", "--out", str(tmp_path)]) == 0
    assert "Removed 8 state file(s)" in capsys.readouterr().out
    assert keep.is_file()
    assert not any((tmp_path / "demo").iterdir())
    assert not (tmp_path / "inbox").exists() and not (tmp_path / "advisory-pasted.txt").exists()

    assert cli.main(["reset", "--out", str(tmp_path)]) == 0
    assert "No state to remove" in capsys.readouterr().out


def test_reset_seed_without_git(tmp_path):
    assert cli.reset_seed(tmp_path) == "seed/repos not reset: this checkout isn't a git repository"


def test_unknown_team_is_a_clean_error(tmp_path):
    out = ["--out", str(tmp_path)]
    cli.main(["demo", *out])
    with pytest.raises(SystemExit) as exc:
        cli.main(["tracker", "reply", "--team", "nobody", "--from", "@x", "rotated", "X", *out])
    assert "unknown team" in str(exc.value)


def test_missing_previous_step(tmp_path):
    with pytest.raises(SystemExit) as exc:
        cli.main(["forensics", "--out", str(tmp_path)])
    assert "run the previous step first" in str(exc.value)


def test_solo_developer_flow(tmp_path, capsys):
    from conftest import REPOS
    out = ["--out", str(tmp_path)]
    assert cli.main(["scout", "--repo", str(REPOS / "web-app"), "--repo", str(REPOS / "infra-tools"), *out]) == 0
    assert "**1 affected**, 1 clean" in capsys.readouterr().out
    assert cli.main(["forensics", *out]) == 0
    assert cli.main(["plan", "--solo", *out]) == 0
    assert capsys.readouterr().out.count("**Your rotation checklist**") == 1
    assert cli.main(["tracker", "init", *out]) == 0
    capsys.readouterr()
    assert cli.main(["tracker", "reply", "--team", "solo", "--from", "you", "rotated", "NPM_TOKEN", *out]) == 0
    assert "**1/2 secrets rotated**" in capsys.readouterr().out
