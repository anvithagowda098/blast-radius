from conftest import FIXTURES, REPOS

from blast_radius import scout


def _by_reason(result, reason):
    return [f for f in result.findings if f.reason == reason]


def test_web_app_top_level_install_and_ioc_package(advisory):
    result = scout.scan_repo(REPOS / "web-app", advisory)
    [hit] = _by_reason(result, "affected-version")
    assert (hit.name, hit.version, hit.path) == (
        "@tanstack/react-router", "1.169.5", "node_modules/@tanstack/react-router")
    assert hit.depth == 1 and hit.dev is False
    assert hit.notes == ["declares IOC dependency @tanstack/setup"]

    [ioc] = _by_reason(result, "ioc-dependency")
    assert ioc.name == "@tanstack/setup"
    assert ioc.has_install_script is True and ioc.optional is True
    # The safe @tanstack/history@1.161.6 next to it is not flagged.
    assert not any(f.name == "@tanstack/history" for f in result.findings)


def test_payments_nested_copy_only(advisory):
    result = scout.scan_repo(REPOS / "payments-api", advisory)
    [hit] = _by_reason(result, "affected-version")
    assert hit.name == "@tanstack/history" and hit.version == "1.161.9"
    assert hit.path == "node_modules/@tanstack/router-core/node_modules/@tanstack/history"
    assert hit.depth == 2
    assert hit.has_install_script is False
    # IOC declared but not installed (no entry in the lockfile): noted, not a separate finding.
    assert hit.notes == ["declares IOC dependency @tanstack/setup"]
    assert len(result.findings) == 1


def test_docs_site_lockfile_v1_dev_only(advisory):
    result = scout.scan_repo(REPOS / "docs-site", advisory)
    [hit] = _by_reason(result, "affected-version")
    assert (hit.name, hit.version) == ("@tanstack/react-router", "1.169.8")
    assert hit.dev is True
    assert hit.has_install_script is None  # v1 doesn't record it
    [ioc] = _by_reason(result, "ioc-dependency")
    assert ioc.name == "@tanstack/setup" and ioc.dev is True


def test_infra_tools_clean_and_reads_last_yaml_document(advisory):
    packages = scout.parse_pnpm_lock(REPOS / "infra-tools" / "pnpm-lock.yaml")
    found = {(p.name, p.version) for p in packages}
    assert ("@tanstack/history", "1.161.6") in found
    assert ("pnpm", "9.15.0") not in found  # first document ignored
    result = scout.scan_repo(REPOS / "infra-tools", advisory)
    assert result.lockfiles == ["pnpm-lock.yaml"]
    assert result.findings == [] and result.errors == []


def test_pnpm_peer_suffix_dev_reachability_and_ioc(advisory):
    result = scout.scan_repo(FIXTURES / "pnpm-affected", advisory)
    hits = {(f.name, f.version): f for f in _by_reason(result, "affected-version")}
    router = hits[("@tanstack/react-router", "1.169.5")]  # peer suffix stripped
    assert router.dev is False and router.depth == 1
    assert router.path == ". > @tanstack/react-router"
    assert router.notes == ["declares IOC dependency @tanstack/setup"]

    history = hits[("@tanstack/history", "1.161.9")]
    assert history.dev is True  # only reachable from devDependencies
    assert history.path == ". > @tanstack/router-devtools > @tanstack/history"
    assert history.depth == 2

    [ioc] = _by_reason(result, "ioc-dependency")
    assert ioc.name == "@tanstack/setup" and ioc.optional is True and ioc.dev is False


def test_scan_repos_and_summary(scout_report):
    assert scout_report["affected_repos"] == ["docs-site", "payments-api", "web-app"]
    assert scout_report["clean_repos"] == ["infra-tools"]
    md = scout.summary_markdown(scout_report)
    lines = md.splitlines()
    assert len(lines) <= 10
    assert "**3 affected**, 1 clean" in lines[1]
    assert "- `web-app`: @tanstack/react-router@1.169.5 (prod); IOC package @tanstack/setup" in lines
    assert "- `payments-api`: @tanstack/history@1.161.9 (prod, nested)" in lines
    assert "- `docs-site`: @tanstack/react-router@1.169.8 (dev only); IOC package @tanstack/setup" in lines
    assert lines[-1] == "- Clean: `infra-tools`"


def test_summary_never_exceeds_ten_lines():
    finding = {"reason": "affected-version", "name": "x", "version": "1.0.0",
               "dev": False, "depth": 1, "has_install_script": False}
    repos = [{"repo": f"r{i}", "findings": [finding], "errors": [], "lockfiles": ["package-lock.json"]}
             for i in range(15)]
    md = scout.summary_markdown({"advisory": {"id": "A", "title": "T"}, "repos": repos})
    assert len(md.splitlines()) == 10
    assert "…and 8 more" in md


def test_ioc_reference_on_unlisted_package(advisory, tmp_path):
    (tmp_path / "package-lock.json").write_text(
        '{"lockfileVersion": 3, "packages": {"": {}, "node_modules/other-pkg": '
        '{"version": "2.0.0", "optionalDependencies": {"@tanstack/setup": "github:x/y#z"}}}}',
        encoding="utf-8")
    result = scout.scan_repo(tmp_path, advisory)
    [f] = result.findings
    assert (f.name, f.reason) == ("other-pkg", "ioc-reference")


def test_broken_lockfile_is_reported_not_raised(advisory, tmp_path):
    (tmp_path / "package-lock.json").write_text("{not json", encoding="utf-8")
    result = scout.scan_repo(tmp_path, advisory)
    assert result.findings == [] and len(result.errors) == 1
