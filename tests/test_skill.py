"""The dwg-catalogue skill: one source file, sent to the planning AI, installed for Claude Code and Codex."""

import json
import re
from pathlib import Path

import pytest

from dwg_takeoff import cli
from dwg_takeoff.ai.prompt import GUIDE_END, LOOKUP_FILES, SKILL_FILE, catalogue_guide, instructions

ROOT = Path(__file__).resolve().parents[1]


def frontmatter(text: str) -> dict:
    head = text.split("---", 2)[1]
    out, key = {}, None
    for line in head.splitlines():
        m = re.match(r"^(\w[\w-]*):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            out[key] = "" if val in (">-", "|") else val
        elif key and line.strip():
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


def test_skill_follows_the_agent_skills_format():
    text = SKILL_FILE.read_text()
    meta = frontmatter(text)
    assert meta["name"] == SKILL_FILE.parent.name == "dwg-catalogue"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", meta["name"]) and len(meta["name"]) <= 64
    assert 50 < len(meta["description"]) <= 1024
    assert GUIDE_END in text


def test_installed_copies_match_the_source():
    """Run `uv run dwg-takeoff install-skill` after editing the skill."""
    for base in (".claude", ".agents"):
        copy = ROOT / base / "skills" / "dwg-catalogue" / "SKILL.md"
        assert copy.exists(), f"{copy} missing: run `uv run dwg-takeoff install-skill`"
        assert copy.read_text() == SKILL_FILE.read_text(), f"{copy} is outdated: run `uv run dwg-takeoff install-skill`"


def test_planner_prompt_carries_the_guide():
    guide = catalogue_guide()
    prompt = instructions(LOOKUP_FILES)
    assert guide in prompt and "=== CATALOGUE GUIDE ===" in prompt
    assert "## From request to plan" in guide and "subtract_entries" in guide
    assert "Working with this repository" not in prompt and "name: dwg-catalogue" not in prompt


def test_install_skill_and_catalogue_command(tmp_path, drawing, capsys):
    paths = cli.install_skill(tmp_path)
    assert [p.relative_to(tmp_path).as_posix() for p in paths] == [
        ".claude/skills/dwg-catalogue/SKILL.md",
        ".agents/skills/dwg-catalogue/SKILL.md",
    ]
    cli.main(["catalogue", drawing.dxf_path, "--search", "pavaj_8"])
    out = capsys.readouterr().out
    assert "1 entries match" in out and "'PAVAJ_8CM'" in out and "750.00 m²" in out


def test_ask_with_a_plan_written_in_entry_ids(tmp_path, drawing, capsys):
    """The workflow the skill documents for agents: a plan naming catalogue ids, measured by the CLI."""
    cli.main(["catalogue", drawing.dxf_path, "--search", "pavaj_8"])
    eid = capsys.readouterr().out.splitlines()[1].split()[0]  # "S1 'PAVAJ_8CM' ..."
    comp = {
        "label": "pavaj",
        "measure": "area",
        "entries": [eid],
        "subtract_entries": [],
        "sources": [],
        "subtract_sources": [],
        "region": None,
        "tolerance_m": None,
        "factors": [],
    }
    plan = {"items": [{"id": "pavaj", "label": "Pavaj", "unit": "m²", "components": [comp]}]}
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    cli.main(
        ["ask", drawing.dxf_path, "pavaj", "--plan", str(tmp_path / "plan.json"), "--json", str(tmp_path / "out.json")]
    )
    assert json.loads((tmp_path / "out.json").read_text())["items"][0]["value"] == pytest.approx(750)
