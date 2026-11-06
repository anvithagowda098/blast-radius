from pathlib import Path

import pytest

from blast_radius import scout
from blast_radius.advisory import load_advisory

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "seed"
REPOS = SEED / "repos"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
NOW = "2026-11-05T10:00:00Z"


@pytest.fixture
def advisory():
    return load_advisory(SEED / "advisories" / "tanstack-2026-05-11.json")


@pytest.fixture
def owners():
    from blast_radius import forensics

    return forensics.OwnerDirectory.load(FIXTURES / "owners.yml")


@pytest.fixture
def scout_report(advisory):
    return scout.scan_repos(REPOS, advisory, now=NOW).to_dict()


@pytest.fixture
def forensics_report(scout_report, owners):
    from blast_radius import forensics

    return forensics.run_forensics(scout_report, owners, now=NOW)


@pytest.fixture
def plans(forensics_report):
    from blast_radius import rotation

    return {p.team: p for p in rotation.build_plans(forensics_report)}
