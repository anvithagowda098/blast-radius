"""Docs stay honest: every relative link points at a real file, and the diagram is valid SVG."""

import re
import xml.etree.ElementTree as ET

import pytest
from conftest import ROOT

DOCS = [ROOT / "README.md", ROOT / "switch" / "README.md", ROOT / "seed" / "README.md"]
LINK_RE = re.compile(r"\]\(([^)\s#]+)\)")


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_relative_links_exist(doc):
    for target in LINK_RE.findall(doc.read_text(encoding="utf-8")):
        if "://" in target:
            continue
        assert (doc.parent / target).exists(), f"{doc.name} links to missing {target}"


def test_architecture_svg_is_valid_xml():
    root = ET.parse(ROOT / "docs" / "architecture.svg").getroot()
    assert root.tag.endswith("svg")


def test_readme_commands_exist():
    from blast_radius import cli

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    commands = set(re.findall(r"python -m blast_radius ([a-z]+)", readme))
    choices = cli.build_parser()._subparsers._group_actions[0].choices
    assert commands and commands <= set(choices)
