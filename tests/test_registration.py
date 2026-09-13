import json
from pathlib import Path

from .helpers import ROOT

from hermes_sway_plugin import registration


EXPECTED_TOOLS = {
    "sway_inspect",
    "sway_window",
    "sway_workspace",
    "sway_layout",
    "sway_launch",
    "sway_rule",
    "sway_startup",
}


class RecordingContext:
    """Minimal stand-in for Hermes PluginContext that records register() calls."""

    def __init__(self, settings=None):
        self.settings = dict(settings or {})
        self.tools = []
        self.skills = []
        self.skill_frontmatter = []
        self.config_reads = []
        self.registration_kwargs = []
        self.skill_namespace = "sway"

    def get_config(self, key, default=None):
        self.config_reads.append(key)
        return self.settings.get(key, default)

    def register_tool(self, name, toolset, schema, handler, **kwargs):
        self.tools.append(
            {"name": name, "toolset": toolset, "schema": schema, "handler": handler}
        )
        self.registration_kwargs.append(kwargs)

    def register_skill(self, name, path, description="", frontmatter=None):
        self.skills.append({"name": name, "path": Path(path), "description": description})
        self.skill_frontmatter.append(frontmatter)


def test_register_declares_seven_tools_and_namespaced_skill():
    ctx = RecordingContext()
    registration.register(ctx)

    assert {entry["name"] for entry in ctx.tools} == EXPECTED_TOOLS
    assert {entry["toolset"] for entry in ctx.tools} == {"sway"}
    for entry in ctx.tools:
        schema = entry["schema"]
        assert schema["name"] == entry["name"]
        assert isinstance(schema["parameters"], dict)
        assert callable(entry["handler"])

    assert len(ctx.skills) == 1
    skill = ctx.skills[0]
    assert skill["name"] == "sway"
    assert ":" not in skill["name"]
    assert skill["path"] == ROOT / "skills" / "sway" / "SKILL.md"
    assert skill["path"].is_file()
    assert skill["description"]


def test_register_returns_json_string_results_from_every_handler():
    ctx = RecordingContext()
    registration.register(ctx)

    for entry in ctx.tools:
        result = entry["handler"]({"__unused__": True}, task_id="test")
        assert isinstance(result, str)
        payload = json.loads(result)
        assert "ok" in payload
