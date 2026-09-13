"""Prove the plugin loads and registers through the real Hermes discovery path."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from .helpers import HERMES_REPO, ROOT, ensure_hermes_repo_on_path

IGNORE = shutil.ignore_patterns(".venv", ".git", "__pycache__", ".pytest_cache", "*.egg-info")

PROBE = r"""
import json
from hermes_cli.plugins import PluginManager
from tools.registry import registry

manager = PluginManager()
manager.discover_and_load()
plugin = manager._plugins.get("sway")

tools = []
for name in sorted(getattr(manager, "_plugin_tool_names", set())):
    entry = registry.get_entry(name)
    if entry is not None and getattr(entry, "toolset", None) == "sway":
        tools.append({"name": name, "toolset": entry.toolset, "schema_name": entry.schema.get("name")})

skills = {key: str(value.get("path")) for key, value in getattr(manager, "_plugin_skills", {}).items()}

dispatch = None
entry = registry.get_entry("sway_inspect")
if entry is not None:
    try:
        out = entry.handler({"view": "summary"}, task_id="probe")
        dispatch = {"type": type(out).__name__, "parsed": isinstance(json.loads(out), dict)}
    except Exception as exc:
        dispatch = {"error": f"{type(exc).__name__}: {exc}"}

print(json.dumps({
    "enabled": bool(plugin and plugin.enabled),
    "error": (plugin.error if plugin else "plugin not discovered"),
    "tools": tools,
    "skills": skills,
    "dispatch": dispatch,
}))
"""


@pytest.fixture()
def installed_home(tmp_path: Path) -> Path:
    home = tmp_path / "hermes-home"
    plugins_dir = home / "plugins"
    plugins_dir.mkdir(parents=True)
    shutil.copytree(ROOT, plugins_dir / "sway", ignore=IGNORE)
    (home / "config.yaml").write_text("plugins:\n  enabled:\n    - sway\n", encoding="utf-8")
    return home


def _probe(home: Path) -> dict:
    if not ensure_hermes_repo_on_path():
        pytest.fail(
            "Hermes checkout not found; set HERMES_REPO to a clean checkout at or after "
            "commit 5aa17c05908ab97c6db3b066deba9dcfb86a6a46"
        )
    env = dict(os.environ, HERMES_HOME=str(home), PYTHONPATH=str(HERMES_REPO))
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_real_hermes_discovery_loads_sway_plugin(installed_home: Path):
    payload = _probe(installed_home)

    assert payload["error"] in (None, ""), payload["error"]
    assert payload["enabled"] is True
    assert {tool["name"] for tool in payload["tools"]} == {
        "sway_inspect",
        "sway_window",
        "sway_workspace",
        "sway_layout",
        "sway_launch",
        "sway_rule",
        "sway_startup",
    }
    assert {tool["toolset"] for tool in payload["tools"]} == {"sway"}
    for tool in payload["tools"]:
        assert tool["schema_name"] == tool["name"]

    assert "sway:sway" in payload["skills"]
    assert Path(payload["skills"]["sway:sway"]).is_file()

    assert payload["dispatch"] is not None
    assert payload["dispatch"].get("type") == "str", payload["dispatch"]
    assert payload["dispatch"].get("parsed") is True, payload["dispatch"]
