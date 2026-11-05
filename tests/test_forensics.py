import json

import pytest
from conftest import REPOS

from blast_radius import forensics


def test_web_app_release_job(owners):
    exp = forensics.analyze_repo(REPOS / "web-app", owners)
    publish = exp.job("release.yml", "publish")
    assert publish.installs_deps and publish.install_commands == ["npm ci"]
    assert publish.secrets == ["NPM_TOKEN", "RELEASE_GH_PAT"]
    assert publish.id_token_write is True
    assert publish.write_scopes == ["contents", "id-token"]  # job-level overrides workflow-level
    assert publish.triggers == ["push", "workflow_dispatch"]

    test = exp.job("ci.yml", "test")
    assert test.installs_deps and test.secrets == []
    assert test.triggers == ["push", "pull_request"]  # `on:` parsed even though YAML reads it as True
    assert test.permissions_set is False

    assert exp.exposed_secrets == ["NPM_TOKEN", "RELEASE_GH_PAT"]
    assert exp.github_owners == ["@maya-web"]
    assert (exp.codeowners_file, exp.team, exp.chat_owners) == (".github/CODEOWNERS", "web", ["@maya"])


def test_payments_exposed_vs_referenced(owners):
    exp = forensics.analyze_repo(REPOS / "payments-api", owners)
    assert exp.exposed_secrets == [
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "DEPLOY_SSH_KEY", "NPM_READ_TOKEN", "VAULT_TOKEN"]
    # migrate job references DATABASE_URL but never installs dependencies
    assert exp.referenced_not_exposed == ["DATABASE_URL"]
    assert exp.job("deploy.yml", "migrate").installs_deps is False
    # root CODEOWNERS: the later /package.json line wins over the earlier one
    assert exp.codeowners_file == "CODEOWNERS"
    assert exp.github_owners == ["@devon-pay"]
    assert (exp.team, exp.chat_owners) == ("payments", ["@devon"])
    assert exp.notes == ["CODEOWNERS: skipped invalid lines 9, 10, 11"]


def test_docs_site_pwn_request_and_docs_codeowners(owners):
    exp = forensics.analyze_repo(REPOS / "docs-site", owners)
    [job] = exp.jobs
    assert job.triggers == ["pull_request_target"]
    assert len(job.risky) == 1 and "pwn request" in job.risky[0]
    assert job.secrets == ["VERCEL_TOKEN"]  # vars.VERCEL_ORG_ID is not a secret
    assert exp.codeowners_file == "docs/CODEOWNERS"
    assert (exp.team, exp.chat_owners) == ("web", ["@maya"])


@pytest.mark.parametrize("script, expected", [
    ("npm ci", ["npm ci"]),
    ("npm i --ignore-scripts", ["npm i --ignore-scripts"]),
    ("cd app && CI=1 npm install", ["npm install"]),
    ("pnpm install --frozen-lockfile", ["pnpm install --frozen-lockfile"]),
    ("yarn", ["yarn"]),
    ("yarn --frozen-lockfile", ["yarn --frozen-lockfile"]),
    ("yarn build", []),
    ("yarn --version", []),
    ("npm run build\nnpm test", []),
    ("echo npm ci", []),
    ("# npm ci", []),
])
def test_install_detection(script, expected):
    assert forensics.install_commands(script) == expected


def _workflow(tmp_path, body):
    path = tmp_path / "wf.yml"
    path.write_text(body, encoding="utf-8")
    return forensics.analyze_workflow(path)


def test_other_pwn_request_shapes_and_bracket_secrets(tmp_path):
    [job] = _workflow(tmp_path, """
on: issue_comment
env:
  GLOBAL: ${{ secrets.ORG_WIDE }}
jobs:
  bot:
    runs-on: ubuntu-latest
    permissions: write-all
    steps:
      - run: gh pr checkout ${{ github.event.issue.number }} && yarn
      - uses: some/action@v1
        with:
          allow-unsafe-pr-checkout: true
          token: ${{ secrets['BOT_TOKEN'] }}
""")
    assert job.installs_deps and job.install_commands == ["yarn"]
    assert job.secrets == ["BOT_TOKEN", "ORG_WIDE"]
    assert job.id_token_write and job.write_scopes == ["all"]
    assert any(r.startswith("issue_comment runs PR code") for r in job.risky)
    assert "allow-unsafe-pr-checkout: true" in job.risky


def test_pull_request_target_without_pr_checkout_is_not_flagged(tmp_path):
    [job] = _workflow(tmp_path, """
on: pull_request_target
jobs:
  label:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/labeler@v5
""")
    assert job.risky == []


def test_reusable_workflow_inheriting_secrets(tmp_path):
    [job] = _workflow(tmp_path, """
on: push
jobs:
  call:
    uses: acme/shared/.github/workflows/build.yml@main
    secrets: inherit
""")
    assert job.inherits_all_secrets and not job.installs_deps


def test_codeowners_matching_rules():
    rules, invalid = forensics.parse_codeowners("""
# comment
*            @org/all
/docs/*      @docs-team
*.js         @js-owner   # inline comment
/build/      @build
!/x/         @nope
/y/[ab]      @nope
/z/          not-valid
apps/web     @web
/unowned
""")
    assert len(invalid) == 3
    owner = lambda p: forensics.owners_for(rules, p)  # noqa: E731
    assert owner("README.md") == ["@org/all"]
    assert owner("docs/a.md") == ["@docs-team"]
    assert owner("docs/sub/b.md") == ["@org/all"]  # docs/* covers one level only
    assert owner("src/deep/x.js") == ["@js-owner"]
    assert owner("build/out/x.txt") == ["@build"]
    assert owner("apps/web/src/x.ts") == ["@web"]
    assert owner("x/thing.txt") == ["@org/all"]  # the invalid negation line was skipped
    assert owner("unowned/file") == []  # a pattern with no owners un-owns the path


def test_codeowners_location_order(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "CODEOWNERS").write_text("* @docs\n", encoding="utf-8")
    (tmp_path / "CODEOWNERS").write_text("* @root\n", encoding="utf-8")
    assert forensics.find_codeowners(tmp_path)[0] == "CODEOWNERS"
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "CODEOWNERS").write_text("* @gh\n", encoding="utf-8")
    assert forensics.find_codeowners(tmp_path)[0] == ".github/CODEOWNERS"


def test_run_forensics_only_affected_repos(forensics_report):
    assert [r["repo"] for r in forensics_report["repos"]] == ["docs-site", "payments-api", "web-app"]
    md = forensics.forensics_markdown(forensics_report)
    assert "stolen" not in md.lower()
    assert "**`payments-api`** · owner @devon (team payments) via `CODEOWNERS`" in md
    assert "Total: 8 secret references in jobs that install deps, across 3 repos and 2 teams." in md


def test_hostcheck(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [
        {"type": "command", "command": "echo hello"},
        {"type": "command", "command": "node ~/.cache/router_init.js"},
    ]}]}}), encoding="utf-8")
    result = forensics.check_claude_settings(settings)
    assert result["session_start_hooks"] == ["echo hello", "node ~/.cache/router_init.js"]
    assert result["suspicious"] == ["node ~/.cache/router_init.js"]
    assert "**suspicious**" in forensics.hostcheck_markdown(result)

    missing = forensics.check_claude_settings(tmp_path / "nope.json")
    assert missing["exists"] is False
