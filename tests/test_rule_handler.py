"""End-to-end managed-resource behavior for ``sway_rule``."""

from __future__ import annotations

import json
from pathlib import Path

from hermes_sway_plugin import handlers

from .helpers import load_fixture


def _settings(config_dir: Path):
    values = {
        "config_dir": str(config_dir),
        "ipc_timeout_seconds": 1.0,
        "reload_timeout_seconds": 1.0,
        "backup_keep": 2,
    }
    return lambda key, default=None: values.get(key, default)


def _offline(**_kwargs):
    from hermes_sway_plugin import ipc

    raise ipc.SwayUnavailable("offline in tests")


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

    def unavailable(**_kwargs):
        from hermes_sway_plugin import ipc

        raise ipc.SwayUnavailable("offline")

    bound = handlers.build_handlers(
        _settings(config_dir), ipc_factory=unavailable, subprocess_run=runner
    )
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


class _ConfigClient:
    def __init__(self, config):
        self.config = config
        self.requests = []
        self.commands = []

    def request(self, message_type):
        self.requests.append(message_type)
        return {"config": self.config}

    def command(self, command):
        self.commands.append(command)


def test_rule_write_skips_reload_when_live_config_lacks_exact_include(tmp_path):
    config_dir = tmp_path / "configured-sway"
    config_dir.mkdir()
    include = config_dir / "hermes-sway-plugin-rules.conf"
    (config_dir / "config").write_text(f"include {include}\n", encoding="utf-8")
    client = _ConfigClient("include /other/rules.conf\n")

    def runner(*_args, **_kwargs):
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    def unavailable(**_kwargs):
        from hermes_sway_plugin import ipc

        raise ipc.SwayUnavailable("offline")

    bound = handlers.build_handlers(
        _settings(config_dir), ipc_factory=lambda **_kwargs: client, subprocess_run=runner
    )
    result = json.loads(
        bound["sway_rule"](
            {
                "action": "add",
                "rule_id": "no-reload-without-include",
                "kind": "window",
                "match": {"app_id": {"value": "org.example.App"}},
                "intended_cardinality": "many",
                "effects": {"floating": True},
            }
        )
    )

    assert result["ok"] is True
    assert "include_not_configured" in result["warnings"]
    assert client.requests
    assert client.commands == []


class _TreeClient:
    def __init__(self, raw_tree):
        self.raw_tree = raw_tree
        self.requests = []

    def request(self, message_type):
        from hermes_sway_plugin import ipc

        self.requests.append(message_type)
        if message_type == ipc.GET_TREE:
            return self.raw_tree
        raise AssertionError(f"unexpected IPC request: {message_type}")


def test_rule_write_refuses_unverified_live_one_cardinality_before_writing(tmp_path):
    config_dir = tmp_path / "configured-sway"
    config_dir.mkdir()
    (config_dir / "config").write_text("# configured\n", encoding="utf-8")
    client = _TreeClient(load_fixture("tree_mixed.json"))

    def runner(*_args, **_kwargs):
        raise AssertionError("validation must not run after cardinality refusal")

    bound = handlers.build_handlers(
        _settings(config_dir),
        ipc_factory=lambda **_kwargs: client,
        subprocess_run=runner,
    )
    result = json.loads(
        bound["sway_rule"](
            {
                "action": "add",
                "rule_id": "ambiguous-kitty",
                "kind": "window",
                "match": {"app_id": {"value": "kitty-.*", "mode": "regex"}},
                "intended_cardinality": "one",
                "effects": {"floating": True},
                "reload": False,
            }
        )
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "cardinality_unverified"
    assert not (config_dir / "hermes-sway-plugin-rules.conf").exists()


def test_rule_write_refuses_external_conflicts_unless_explicitly_allowed(tmp_path):
    config_dir = tmp_path / "configured-sway"
    config_dir.mkdir()
    (config_dir / "config").write_text(
        'for_window [app_id="^other$"] floating enable\n', encoding="utf-8"
    )

    def runner(*_args, **_kwargs):
        raise AssertionError("validation must not run with unapproved conflicts")

    def unavailable(**_kwargs):
        from hermes_sway_plugin import ipc

        raise ipc.SwayUnavailable("offline")

    bound = handlers.build_handlers(
        _settings(config_dir), ipc_factory=unavailable, subprocess_run=runner
    )
    result = json.loads(
        bound["sway_rule"](
            {
                "action": "add",
                "rule_id": "conflicting-rule",
                "kind": "window",
                "match": {"app_id": {"value": "org.example.App"}},
                "intended_cardinality": "many",
                "effects": {"floating": True},
                "reload": False,
            }
        )
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "external_conflict"
    assert not (config_dir / "hermes-sway-plugin-rules.conf").exists()


def test_rule_get_reports_missing_resource_and_update_replaces_one_entry(tmp_path):
    config_dir = tmp_path / "configured-sway"
    config_dir.mkdir()
    include = config_dir / "hermes-sway-plugin-rules.conf"
    (config_dir / "config").write_text(f"include {include}\n", encoding="utf-8")

    def runner(*_args, **_kwargs):
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    def unavailable(**_kwargs):
        from hermes_sway_plugin import ipc

        raise ipc.SwayUnavailable("offline")

    bound = handlers.build_handlers(
        _settings(config_dir), ipc_factory=unavailable, subprocess_run=runner
    )
    bound["sway_rule"](
        {
            "action": "add",
            "rule_id": "first-rule",
            "kind": "workspace_output",
            "workspace": "dev",
            "outputs": ["DP-1"],
            "reload": False,
        }
    )
    bound["sway_rule"](
        {
            "action": "add",
            "rule_id": "second-rule",
            "kind": "workspace_output",
            "workspace": "web",
            "outputs": ["HDMI-A-1"],
            "reload": False,
        }
    )
    updated = json.loads(
        bound["sway_rule"](
            {
                "action": "update",
                "rule_id": "first-rule",
                "kind": "workspace_output",
                "workspace": "dev",
                "outputs": ["DP-1", "HDMI-A-1"],
                "reload": False,
            }
        )
    )
    fetched = json.loads(bound["sway_rule"]({"action": "get", "rule_id": "first-rule"}))
    listed = json.loads(bound["sway_rule"]({"action": "list"}))
    removed = json.loads(bound["sway_rule"]({"action": "remove", "rule_id": "second-rule", "reload": False}))
    after = json.loads(bound["sway_rule"]({"action": "list"}))
    missing = json.loads(bound["sway_rule"]({"action": "get", "rule_id": "second-rule"}))

    assert updated["data"]["rule"]["outputs"] == ["DP-1", "HDMI-A-1"]
    assert fetched["data"]["rule"]["outputs"] == ["DP-1", "HDMI-A-1"]
    assert [rule["rule_id"] for rule in listed["data"]["rules"]] == ["first-rule", "second-rule"]
    assert removed["data"]["rule"]["rule_id"] == "second-rule"
    assert [rule["rule_id"] for rule in after["data"]["rules"]] == ["first-rule"]
    assert missing["ok"] is False
    assert missing["error"]["code"] == "rule_not_found"
    body = include.read_text(encoding="utf-8")
    assert body.count('workspace "dev" output') == 1
    assert 'workspace "web" output' not in body


def test_rule_refuses_hand_edited_managed_include(tmp_path):
    config_dir = tmp_path / "configured-sway"
    config_dir.mkdir()
    include = config_dir / "hermes-sway-plugin-rules.conf"
    (config_dir / "config").write_text(f"include {include}\n", encoding="utf-8")

    def runner(*_args, **_kwargs):
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    def unavailable(**_kwargs):
        from hermes_sway_plugin import ipc

        raise ipc.SwayUnavailable("offline")

    bound = handlers.build_handlers(
        _settings(config_dir), ipc_factory=unavailable, subprocess_run=runner
    )
    bound["sway_rule"](
        {
            "action": "add",
            "rule_id": "hand-edit-target",
            "kind": "workspace_output",
            "workspace": "dev",
            "outputs": ["DP-1"],
            "reload": False,
        }
    )
    tampered = include.read_text(encoding="utf-8").replace("DP-1", "DP-2")
    include.write_text(tampered, encoding="utf-8")

    result = json.loads(bound["sway_rule"]({"action": "list"}))

    assert result["ok"] is False
    assert result["error"]["code"] == "manual_edit_refused"
