import json
import subprocess
from pathlib import Path

import pytest

from .helpers import ROOT, ensure_hermes_repo_on_path


EXPECTED_TOOLS = {
    "sway_inspect",
    "sway_window",
    "sway_workspace",
    "sway_layout",
    "sway_launch",
    "sway_rule",
    "sway_startup",
}
CONFIG_SCHEMA_DEFAULTS = {
    "ipc_timeout_seconds": 3.0,
    "reload_timeout_seconds": 5.0,
    "launch_timeout_seconds": 10.0,
    "config_dir": "",
    "backup_keep": 10,
}


def test_manifest_declares_exact_public_surface():
    result = subprocess.run(
        ["hermes", "plugins", "validate", str(ROOT), "--json"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert all(check["ok"] for check in payload["checks"]), payload

    if not ensure_hermes_repo_on_path():
        pytest.fail(
            "Hermes checkout not found; set HERMES_REPO to a clean checkout at or after "
            "commit 5aa17c05908ab97c6db3b066deba9dcfb86a6a46"
        )

    from hermes_cli.plugins_manifest import parse_manifest_file

    manifest_file = ROOT / "plugin.yaml"
    manifest = parse_manifest_file(manifest_file, ROOT, "user", "")
    assert manifest is not None
    assert manifest.name == "sway"
    assert manifest.kind == "standalone"
    assert set(manifest.provides_tools) == EXPECTED_TOOLS
    assert "manifest_version" not in manifest_file.read_text(encoding="utf-8")
    settings = manifest.config_schema
    assert set(settings) == set(CONFIG_SCHEMA_DEFAULTS)
    assert {key: settings[key]["default"] for key in settings} == CONFIG_SCHEMA_DEFAULTS
    assert manifest.license == "MIT"


def test_release_versions_are_consistent():
    from hermes_sway_plugin.registration import SKILL_FRONTMATTER

    project_lines = (ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines()
    project_start = project_lines.index("[project]")
    project_version = next(
        line.split("=", 1)[1].strip().strip('"')
        for line in project_lines[project_start + 1 :]
        if line.startswith("version = ")
    )
    manifest_version = next(
        line.split(":", 1)[1].strip()
        for line in (ROOT / "plugin.yaml").read_text(encoding="utf-8").splitlines()
        if line.startswith("version:")
    )

    assert project_version == "0.2.1"
    assert manifest_version == "0.2.1"
    assert SKILL_FRONTMATTER["version"] == "0.2.1"
