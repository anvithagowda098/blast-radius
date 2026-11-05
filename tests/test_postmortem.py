import re

import pytest
from conftest import NOW

from blast_radius import postmortem, tracker

LATER = "2026-11-05T10:42:00Z"
BLAMEFUL = re.compile(r"\b(blame|fault|careless|mistake|should have|failed to|stolen|leaked)\b", re.IGNORECASE)


@pytest.fixture
def plan(plans):
    return {"plans": [p.to_dict() for p in plans.values()]}


@pytest.fixture
def state(plans):
    s = tracker.init_state(list(plans.values()), "BR-2026-05-11-TANSTACK", now=NOW)
    tracker.approve_containment(s, "all", "@anvi", now="2026-11-05T10:05:00Z")
    tracker.apply_reply(s, "web", "C: runners paused · A: rotated NPM_TOKEN, RELEASE_GH_PAT and VERCEL_TOKEN",
                        "@maya", now="2026-11-05T10:30:00Z")
    tracker.apply_reply(s, "payments", "A: rotated the AWS access key\nN: Vault admin to revoke VAULT_TOKEN",
                        "@devon", now=LATER)
    return s


@pytest.fixture
def draft(state, scout_report, forensics_report, plan):
    return postmortem.build(state, scout_report, forensics_report, plan, now=LATER)


def test_has_every_section(draft):
    for heading in ("## Summary", "## Impact", "## Timeline (UTC)", "## Root cause",
                    "## What went well", "## What went poorly", "## Action items"):
        assert heading in draft
    assert draft.startswith("# Postmortem (draft): TanStack Router npm packages compromised")
    assert "not signed off by the IC (@anvi)" in draft


def test_summary_and_impact_come_from_data(draft):
    assert "3 of our repos installed an affected version, across 2 teams, and 7 credentials" in draft
    assert "4/7 are rotated, 1 blocked, and 1 of 2 teams are done" in draft
    assert ("| `payments-api` | payments | `@tanstack/history@1.161.9` (prod) | `AWS_ACCESS_KEY_ID`, "
            "`AWS_SECRET_ACCESS_KEY`, `DEPLOY_SSH_KEY`, `NPM_READ_TOKEN`, `VAULT_TOKEN` | - |") in draft
    assert "`docs-site` | web | `@tanstack/react-router@1.169.8` (dev), IOC package" in draft
    assert "Clean: `infra-tools`." in draft


def test_timeline_and_durations(draft):
    assert "| 2026-11-05 10:05:00 | @anvi | IC approved containment for payments, web |" in draft
    assert "- First scan to containment approved: 5 min" in draft
    assert "- Not finished: 2 pending, 1 blocked" in draft
    assert "Team web (@maya) rotated all 3 credentials, 30 min after the first scan." in draft


def test_root_cause_is_upstream_and_blameless(draft):
    assert "The root cause is upstream" in draft
    assert "Running `npm install` is not negligence" in draft
    assert "`docs-site` › `preview.yml` ran pull-request code" in draft
    assert "Dev-only dependencies are still installed in CI and on laptops (`docs-site`)" in draft
    assert not BLAMEFUL.search(draft)


def test_went_poorly_and_action_items(draft):
    assert "`VAULT_TOKEN` (payments) is blocked: needs Vault admin to revoke VAULT_TOKEN." in draft
    assert "| Finish rotating `NPM_READ_TOKEN` (payments-api); now pending | @devon | open |" in draft
    # a hardening tip both teams got appears once, owned by both
    assert re.search(r"\| `\.npmrc`: `ignore-scripts=true`.* \| @devon, @maya \| open \|", draft)
    assert draft.count("ignore-scripts=true") == 1
    assert "| Review this draft and sign it off | @anvi | open |" in draft


def test_rotation_before_approval_is_reported(plans):
    s = tracker.init_state(list(plans.values()), "X", now=NOW)
    tracker.apply_reply(s, "web", "rotated NPM_TOKEN", "@maya", now=LATER)
    draft = postmortem.build(s, now=LATER)
    assert "`NPM_TOKEN` (web) was rotated before containment was approved" in draft
    assert "- Tracker opened to containment approved: not approved yet" in draft
    assert "_Sign-off: the IC, not yet signed._" in draft


def test_works_from_tracker_alone(state):
    draft = postmortem.build(state, now=LATER)  # no scout / forensics / plan JSON
    assert "## Action items" in draft and not BLAMEFUL.search(draft)


@pytest.mark.parametrize("start, end, expected", [
    (NOW, "2026-11-05T10:00:42Z", "42s"),
    (NOW, "2026-11-05T11:59:00Z", "119 min"),
    (NOW, "2026-11-05T14:07:00Z", "4 h 7 min"),
    (NOW, None, "n/a"),
])
def test_duration(start, end, expected):
    assert postmortem.duration(start, end) == expected
