"""Checks the Switch template against the rules in Switch's docs/TEMPLATES.md (version 2).

This is our own reading of those docs, not Switch's validator: the real check
is importing the template in Switch Console.
"""

import re
import subprocess
import sys

import pytest
import yaml
from conftest import ROOT

from blast_radius import cli

SWITCH = ROOT / "switch"
TEMPLATE = SWITCH / "blast-radius.template.yaml"
BUILTINS = {"$creator", "$creator_email", "$date", "$timestamp", "$agents_dir"}
ADDRESSING = {"owner", "owner-agents", "anyone"}
NAME_RE = re.compile(r"^[a-z0-9._-]+$")
PLACEHOLDER_RE = re.compile(r"\{([^{}\s]+)\}")
CLI_CMD_RE = re.compile(r"`(python -m blast_radius [^`]+)`")
NOT_BUILT_YET: set[str] = set()  # CLI commands the instructions mention before they exist


@pytest.fixture(scope="module")
def doc():
    return yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))


def _strings(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)
    elif isinstance(obj, str):
        yield obj


def _values(field):
    """A field's possible values: plain, or a list of {if, value} entries."""
    if isinstance(field, list) and field and all(isinstance(e, dict) and "value" in e for e in field):
        return [e["value"] for e in field]
    return [field]


def _of_type(doc, kind):
    return {k: r for k, r in doc["resources"].items() if r["type"] == kind}


def test_template_is_built_from_agent_files():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_template.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_version_and_resource_types(doc):
    assert doc["version"] == 2
    assert {r["type"] for r in doc["resources"].values()} <= {"agent", "room", "group"}


def test_placeholders_resolve_and_every_param_is_used(doc):
    params = set(doc["params"])
    keys = set(doc["resources"])
    used = set()
    body = {k: v for k, v in doc.items() if k != "params"}
    body_strings = list(_strings(body)) + [p.get("if", "") for p in doc["params"].values()]
    for text in body_strings:
        for token in PLACEHOLDER_RE.findall(text):
            if token in BUILTINS:
                continue
            if token.endswith(".name"):
                assert token[:-5] in keys, f"{{{token}}} names no resource"
                continue
            assert token in params, f"undeclared placeholder {{{token}}}"
            used.add(token)
    assert used == params, f"unused params: {params - used}"


def test_agents_complete(doc):
    for key, agent in _of_type(doc, "agent").items():
        assert agent.get("provider") and agent.get("directory"), key
        assert agent.get("machine") or agent.get("location"), key
        assert NAME_RE.match(agent["name"]), agent["name"]
        assert agent["instructions"] == (SWITCH / "agents" / f"{key}.md").read_text(encoding="utf-8")
        rooms = set(_of_type(doc, "room"))
        for value in _values(agent["addressing"]):
            if isinstance(value, dict):
                assert set(value) == {"anyone_in"} and set(value["anyone_in"]) <= rooms
            else:
                assert value in ADDRESSING


def test_commander_answers_only_owner_side(doc):
    assert doc["resources"]["commander"]["addressing"] == "owner-agents"


def test_rooms_reference_real_resources_and_kickoff_wakes_an_agent(doc):
    agents = _of_type(doc, "agent")
    for key, room in _of_type(doc, "room").items():
        assert doc["resources"][room["group"]]["type"] == "group"
        members = set()
        for value in _values(room["agents"]):
            assert set(value) <= set(agents), key
            members |= set(value)
        mentioned = re.findall(r"@\{([a-z_]+)\.name\}", room["kickoff"])
        assert mentioned and set(mentioned) <= members, "kickoff must @ an agent in the room"
        assert not any(r["type"] == "group" and "kickoff" in r for r in doc["resources"].values())


def test_conditions_use_declared_params(doc):
    params = set(doc["params"])
    conditions = [r["if"] for r in doc["resources"].values() if "if" in r]
    conditions += [e["if"] for text in doc["resources"].values() for f in text.values()
                   if isinstance(f, list) for e in f if isinstance(e, dict) and "if" in e]
    for cond in conditions:
        assert re.fullmatch(r"\{(\w+)\}(?: (?:==|!=) \S+)?", cond), cond
        assert re.match(r"\{(\w+)\}", cond)[1] in params


def test_instruction_commands_parse():
    parser = cli.build_parser()
    seen = 0
    for md in sorted((SWITCH / "agents").glob("*.md")):
        for command in CLI_CMD_RE.findall(md.read_text(encoding="utf-8")):
            argv = re.sub(r"<[^>]+>", "X", " ".join(command.split())).split()[3:]
            if argv[0] == "..." or argv[0] in NOT_BUILT_YET:  # "Run only `python -m blast_radius ...`"
                continue
            parser.parse_args(argv)  # raises SystemExit on an unknown command or option
            seen += 1
    assert seen >= 8


# Required fields from the Switch server's own models (switch_core RoomSpec,
# DocSpec, RoleSpec, as shipped in Switch Console v0.40.1). TEMPLATES.md lists
# these fields but doesn't say which are required; the server rejects a room
# that misses one, and then creates nothing.
SERVER_REQUIRED = {
    "room": {"name", "description"},
    "docs": {"name", "description", "instructions", "content"},
    "roles": {"name", "instructions"},
}


def test_rooms_have_every_field_the_server_requires(doc):
    for key, room in _of_type(doc, "room").items():
        assert SERVER_REQUIRED["room"] <= set(room), key
        for d in room.get("docs", []):
            assert SERVER_REQUIRED["docs"] <= set(d), f"{key} doc {d.get('name')}"
        for r in room.get("roles", []):
            assert SERVER_REQUIRED["roles"] <= set(r), f"{key} role {r.get('name')}"


def test_agents_name_their_provider_directly(doc):
    # A `provider` param renders an empty picker on Windows (Console v0.40.1).
    assert not any(p.get("type") == "provider" for p in doc["params"].values())
    for agent in _of_type(doc, "agent").values():
        assert agent["provider"] == "claude"
