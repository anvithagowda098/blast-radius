import json

from blast_radius.advisory import load_advisory, parse_csv, parse_json, parse_table


def test_seed_advisory(advisory):
    assert advisory.id == "BR-2026-05-11-TANSTACK"
    assert advisory.affected == {
        "@tanstack/react-router": {"1.169.5", "1.169.8"},
        "@tanstack/history": {"1.161.9", "1.161.12"},
    }
    assert advisory.ioc_names == {"@tanstack/setup"}
    assert "router_init.js" in advisory.ioc_files
    assert "seed2.getsession.org" in advisory.ioc_domains
    assert advisory.is_affected("@tanstack/history", "1.161.9")
    assert not advisory.is_affected("@tanstack/history", "1.161.6")


def test_osv_style_json():
    adv = parse_json(json.dumps({
        "id": "MAL-2026-0001",
        "summary": "Malicious code in evil-pkg",
        "affected": [{"package": {"ecosystem": "npm", "name": "evil-pkg"}, "versions": ["1.0.0"]}],
        "references": [{"type": "WEB", "url": "https://example.test/advisory"}],
    }))
    assert adv.id == "MAL-2026-0001"
    assert adv.affected == {"evil-pkg": {"1.0.0"}}
    assert adv.references == ["https://example.test/advisory"]


def test_wiz_style_csv():
    text = (
        "package_name,package_versions,source\n"
        '@tanstack/react-router,"1.169.5, 1.169.8",stepsecurity\n'
        "@tanstack/history,= 1.161.9 || = 1.161.12,wiz\n"
    )
    adv = parse_csv(text, default_id="wiz")
    assert adv.affected == {
        "@tanstack/react-router": {"1.169.5", "1.169.8"},
        "@tanstack/history": {"1.161.9", "1.161.12"},
    }


def test_csv_without_known_header_falls_back_to_table():
    adv = parse_csv("@tanstack/history@1.161.9,critical\n", default_id="x")
    assert adv.affected == {"@tanstack/history": {"1.161.9"}}


def test_pasted_markdown_table_and_lines():
    text = """
| Package | Compromised versions |
|---|---|
| `@tanstack/react-router` | 1.169.5, 1.169.8 |
| @tanstack/history | v1.161.9 / 1.161.12 |

foo-bar@2.0.1 baz@3.1.4-beta.1
Version 2.0.0 of this advisory is final.
"""
    adv = parse_table(text)
    assert adv.affected == {
        "@tanstack/react-router": {"1.169.5", "1.169.8"},
        "@tanstack/history": {"1.161.9", "1.161.12"},
        "foo-bar": {"2.0.1"},
        "baz": {"3.1.4-beta.1"},
    }


def test_load_by_extension(tmp_path):
    table = tmp_path / "pasted.txt"
    table.write_text("@tanstack/history 1.161.12\n", encoding="utf-8")
    adv = load_advisory(table)
    assert adv.id == "pasted"
    assert adv.affected == {"@tanstack/history": {"1.161.12"}}
