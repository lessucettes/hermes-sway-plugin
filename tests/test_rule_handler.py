"""End-to-end managed-resource behavior for ``sway_rule``."""

from __future__ import annotations

import json
from pathlib import Path

from hermes_sway_plugin import handlers


def _settings(config_dir: Path):
    values = {
        "config_dir": str(config_dir),
        "ipc_timeout_seconds": 1.0,
        "reload_timeout_seconds": 1.0,
        "backup_keep": 2,
    }
    return lambda key, default=None: values.get(key, default)


def test_rule_preview_renders_output_destination_without_writing(tmp_path):
    config_dir = tmp_path / "configured-sway"
    bound = handlers.build_handlers(_settings(config_dir))

    result = json.loads(
        bound["sway_rule"](
            {
                "action": "preview",
                "kind": "window",
                "match": {"app_id": {"value": "org.example.App"}},
                "intended_cardinality": "many",
                "destination": {"output": "DP-1"},
            }
        )
    )

    assert result["ok"] is True
    assert result["scope"] == "persistent"
    assert result["data"]["rendered"] == (
        'for_window [app_id="^org\\\\.example\\\\.App$"] move container to output "DP-1"'
    )
    assert "applies_to_new_windows_only" in result["warnings"]
    assert not config_dir.exists()


def test_rule_add_persists_and_list_reads_a_deterministic_managed_include(tmp_path):
    config_dir = tmp_path / "configured-sway"
    config_dir.mkdir()
    include = config_dir / "hermes-sway-plugin-rules.conf"
    (config_dir / "config").write_text(f"include {include}\n", encoding="utf-8")
    validation_calls = []

    def runner(argv, **_kwargs):
        validation_calls.append(argv)
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    bound = handlers.build_handlers(_settings(config_dir), subprocess_run=runner)
    added = json.loads(
        bound["sway_rule"](
            {
                "action": "add",
                "rule_id": "app-to-dev",
                "kind": "window",
                "match": {"app_id": {"value": "org.example.App"}},
                "intended_cardinality": "many",
                "destination": {"workspace": "dev"},
                "reload": False,
            }
        )
    )
    listed = json.loads(bound["sway_rule"]({"action": "list"}))

    assert added["ok"] is True
    assert added["data"]["rule"]["rule_id"] == "app-to-dev"
    assert added["warnings"] == ["applies_to_new_windows_only"]
    assert listed["data"]["rules"] == [added["data"]["rule"]]
    assert 'for_window [app_id="^org\\\\.example\\\\.App$"] move container to workspace "dev"\n' in include.read_text(encoding="utf-8")
    assert len(validation_calls) == 2
