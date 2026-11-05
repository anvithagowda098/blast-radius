import pytest

from blast_radius import rotation


def test_two_teams_seven_credentials(plans):
    assert sorted(plans) == ["payments", "web"]
    assert plans["web"].repos == ["docs-site", "web-app"]
    assert plans["web"].owners == ["@maya"] and plans["payments"].owners == ["@devon"]
    assert plans["web"].room == "br-web"
    assert sum(len(p.credentials) for p in plans.values()) == 7


def test_contain_first_and_only_it_needs_ic_approval(plans):
    for plan in plans.values():
        assert plan.steps[0].category == "contain"
        assert plan.steps[0].requires_ic_approval is True
        assert not any(s.requires_ic_approval for s in plan.steps[1:])
        assert plan.steps[1].category == "host-check"
        assert [s.category for s in plan.steps[-2:]] == ["host-creds", "unlisted"]
        assert [s.n for s in plan.steps] == list(range(1, len(plan.steps) + 1))


def test_trigger_dev_order(plans):
    for plan in plans.values():
        cats = [s.category for s in plan.steps]
        assert cats == sorted(cats, key=rotation.CATEGORY_ORDER.index)
    assert [c.key for c in plans["payments"].credentials] == [
        "VAULT_TOKEN", "AWS_ACCESS_KEY_ID", "NPM_READ_TOKEN", "DEPLOY_SSH_KEY"]
    assert [c.key for c in plans["web"].credentials] == ["RELEASE_GH_PAT", "VERCEL_TOKEN", "NPM_TOKEN"]


def test_aws_pair_is_one_credential(plans):
    aws = next(c for c in plans["payments"].credentials if c.key == "AWS_ACCESS_KEY_ID")
    assert aws.names == ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
    assert "AWS_ACCESS_KEY" in aws.aliases


def test_session_blocks_for_aws_and_oidc(plans):
    pay = next(s for s in plans["payments"].steps if s.category == "sessions")
    assert "aws:TokenIssueTime" in pay.detail and "SSO" in pay.detail
    web = next(s for s in plans["web"].steps if s.category == "sessions")
    assert "web-app › release.yml › publish" in web.detail


def test_host_check_uses_advisory_iocs(plans):
    detail = plans["web"].steps[1].detail
    assert "SessionStart" in detail and "`router_init.js`" in detail and "`*.getsession.org`" in detail


def test_hardening_flags_pwn_request_repo(plans):
    tips = plans["web"].hardening
    assert any("docs-site" in t and "pull_request_target" in t for t in tips)
    assert any("trusted publishing" in t for t in tips)
    assert not any("pull_request_target" in t for t in plans["payments"].hardening)


def test_unowned_repo_gets_its_own_plan():
    report = {"advisory": {}, "repos": [{
        "repo": "orphan", "team": None, "chat_owners": [], "github_owners": [],
        "jobs": [{"workflow": ".github/workflows/x.yml", "job": "build", "installs_deps": True,
                  "secrets": ["GITHUB_TOKEN", "SENTRY_AUTH_TOKEN"], "id_token_write": False,
                  "inherits_all_secrets": True, "risky": []}],
    }]}
    [plan] = rotation.build_plans(report)
    assert plan.team == "unowned" and plan.owners == []
    assert [c.key for c in plan.credentials] == ["SENTRY_AUTH_TOKEN"]  # GITHUB_TOKEN expires with the job
    assert "inherit every repo secret" in plan.steps[-1].detail
    assert "unassigned" in rotation.plan_markdown(plan.to_dict())


@pytest.mark.parametrize("name, category", [
    ("DEPLOY_SSH_KEY", "ssh"), ("NPM_READ_TOKEN", "npm"), ("NODE_AUTH_TOKEN", "npm"),
    ("RELEASE_GH_PAT", "identity"), ("VAULT_TOKEN", "secrets-manager"),
    ("AWS_SECRET_ACCESS_KEY", "cloud"), ("GOOGLE_APPLICATION_CREDENTIALS", "cloud"),
    ("VERCEL_TOKEN", "hosting"), ("CF_API_TOKEN", "hosting"), ("DATABASE_URL", "other"),
])
def test_categorize(name, category):
    assert rotation.categorize(name) == category


def test_plan_markdown(plans):
    md = rotation.plan_markdown(plans["web"].to_dict())
    assert md.startswith("**Rotation checklist** · team **web** · owner @maya")
    assert "1. [ ] **Contain: pause CI and isolate hosts that installed the bad version** (needs IC approval)" in md
    assert "`npm token delete <id>`" in md
    assert "CAN format" in md
