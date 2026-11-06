import pytest
from conftest import NOW

from blast_radius import tracker


@pytest.fixture
def state(plans):
    return tracker.init_state(list(plans.values()), "BR-TEST", now=NOW)


def _status(state, team, key):
    return state["teams"][team]["secrets"][key]["status"]


def test_init(state):
    assert tracker.summary(state) == {"rotated": 0, "blocked": 0, "total": 7, "teams_done": 0, "teams": 2}
    assert tracker.header(state) == "**0/7 secrets rotated** · 0 teams done · 0 blocked"
    assert state["timeline"][0]["event"] == "Tracker opened: 7 secrets across 2 teams"


def test_simple_reply_warns_before_containment_approval(state):
    result = tracker.apply_reply(state, "web", "rotated NPM_TOKEN", "@maya", now=NOW)
    assert _status(state, "web", "NPM_TOKEN") == "rotated"
    assert result.changes == [{"team": "web", "secret": "NPM_TOKEN", "from": "pending", "to": "rotated", "note": ""}]
    assert any("before the IC approved containment" in w for w in result.warnings)


def test_multiline_can_reply(state):
    tracker.approve_containment(state, "all", "@anvi", now=NOW)
    text = ("Condition: deploys paused\n"
            "Actions: rotated the AWS access key, revoked DEPLOY_SSH_KEY\n"
            "Needs: Vault admin to revoke VAULT_TOKEN")
    result = tracker.apply_reply(state, "payments", text, "@devon", now=NOW)
    assert _status(state, "payments", "AWS_ACCESS_KEY_ID") == "rotated"
    assert _status(state, "payments", "DEPLOY_SSH_KEY") == "rotated"
    assert _status(state, "payments", "VAULT_TOKEN") == "blocked"
    assert "Vault admin" in state["teams"]["payments"]["secrets"]["VAULT_TOKEN"]["note"]
    assert _status(state, "payments", "NPM_READ_TOKEN") == "pending"
    assert result.contained and state["teams"]["payments"]["contained_by"] == "@devon"
    assert result.warnings == []


def test_one_line_can_reply_with_carried_verb(state):
    result = tracker.apply_reply(
        state, "web", "C: runners paused · A: rotated NPM_TOKEN and RELEASE_GH_PAT · N: none", "@maya", now=NOW)
    assert _status(state, "web", "NPM_TOKEN") == "rotated"
    assert _status(state, "web", "RELEASE_GH_PAT") == "rotated"
    assert _status(state, "web", "VERCEL_TOKEN") == "pending"
    assert result.contained and result.needs == ""


@pytest.mark.parametrize("mention", ["@br-planner ", "@br-planner: ", "<@1234567890> ", "<@&1568258002660622407> ",
                                     "@br-planner @br-commander "])
def test_leading_mentions_are_ignored(state, mention):
    result = tracker.apply_reply(state, "web", mention + "C: runners paused · A: rotated NPM_TOKEN · N: none",
                                 "@maya", now=NOW)
    assert _status(state, "web", "NPM_TOKEN") == "rotated"
    assert result.contained and result.needs == ""


def test_dictated_lowercase_name(state):
    tracker.apply_reply(state, "web", "Rotated the vercel token.", "@maya", now=NOW)
    assert _status(state, "web", "VERCEL_TOKEN") == "rotated"


def test_status_after_the_name_and_negation(state):
    tracker.apply_reply(state, "web", "VERCEL_TOKEN blocked on team admin; haven't rotated NPM_TOKEN yet",
                        "@maya", now=NOW)
    assert _status(state, "web", "VERCEL_TOKEN") == "blocked"
    assert _status(state, "web", "NPM_TOKEN") == "pending"


def test_unknown_and_lookalike_names_change_nothing(state):
    result = tracker.apply_reply(state, "web", "rotated NPM_TOKNE and MY_NPM_TOKEN_OLD", "@maya", now=NOW)
    assert result.changes == []
    assert result.unknown == ["MY_NPM_TOKEN_OLD", "NPM_TOKNE"]
    assert _status(state, "web", "NPM_TOKEN") == "pending"
    assert "couldn't match" not in tracker.reply_markdown(result, state, "web")  # warnings are shown instead


def test_team_level_need_without_a_secret(state):
    tracker.apply_reply(state, "payments", "N: someone with org owner rights", "@devon", now=NOW)
    assert state["teams"]["payments"]["needs"] == "someone with org owner rights"
    assert "needs someone with org owner rights" in tracker.render_markdown(state)


def test_set_status_by_alias_and_errors(state):
    tracker.set_status(state, "payments", "AWS_SECRET_ACCESS_KEY", "rotated", "@devon", now=NOW)
    assert _status(state, "payments", "AWS_ACCESS_KEY_ID") == "rotated"
    with pytest.raises(KeyError):
        tracker.set_status(state, "payments", "NOPE", "rotated", "@devon", now=NOW)
    with pytest.raises(KeyError):
        tracker.set_status(state, "nobody", "NPM_TOKEN", "rotated", "@devon", now=NOW)
    with pytest.raises(ValueError):
        tracker.set_status(state, "payments", "VAULT_TOKEN", "maybe", "@devon", now=NOW)


def test_demo_flow_header_and_render(state, tmp_path):
    tracker.approve_containment(state, "all", "@anvi", now=NOW)
    tracker.apply_reply(state, "web", "C: runners paused · A: rotated NPM_TOKEN and RELEASE_GH_PAT · N: none",
                        "@maya", now=NOW)
    tracker.apply_reply(state, "web", "rotated the vercel token", "@maya", now=NOW)
    tracker.apply_reply(state, "payments", "Condition: deploys paused\nActions: rotated the AWS access key\n"
                        "Needs: Vault admin to revoke VAULT_TOKEN", "@devon", now=NOW)
    assert tracker.header(state) == "**4/7 secrets rotated** · 1 team done · 1 blocked"

    md = tracker.render_markdown(state)
    assert "| payments (@devon) | `AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY` | payments-api | rotated | 10:00 UTC @devon |" in md
    assert "- payments · `VAULT_TOKEN`: needs Vault admin to revoke VAULT_TOKEN (@devon)" in md
    assert "- web: approved by @anvi; confirmed by @maya" in md

    path = tmp_path / "tracker.json"
    tracker.save(state, path)
    assert tracker.load(path) == state
