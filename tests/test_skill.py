"""Bundled Sway operating skill contract."""

from __future__ import annotations

from .helpers import ROOT
from hermes_sway_plugin import registration

from .test_registration import RecordingContext


def test_sway_skill_is_registered_with_valid_frontmatter_and_operational_guidance():
    context = RecordingContext()
    registration.register(context)
    skill_path = context.skills[0]["path"]
    text = skill_path.read_text(encoding="utf-8")

    assert text.startswith("---\nname: sway\n")
    assert "\n---\n\n# Sway 1.9 Operating Skill\n" in text
    assert "Do not call `sway_inspect` first by habit." in text
    assert "Call `sway_inspect` first." not in text
    assert "`sway_start_only`" in text
    assert "best-effort" in text
    assert "raw Sway command" in text
    assert skill_path == ROOT / "skills" / "sway" / "SKILL.md"
