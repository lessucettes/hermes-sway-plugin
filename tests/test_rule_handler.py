"""End-to-end managed-resource behavior for ``sway_rule``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_sway_plugin import handlers, persistent
from hermes_sway_plugin.errors import SwayPluginError

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
        'assign [app_id="^org\\\\.example\\\\.App$"] output "DP-1"'
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
    assert added["data"]["applies_to_new_windows_only"] is True
    assert added["warnings"] == ["applies_to_new_windows_only"]
    assert listed["data"]["rules"] == [added["data"]["rule"]]
    assert 'assign [app_id="^org\\\\.example\\\\.App$"] workspace "dev"\n' in include.read_text(encoding="utf-8")
    assert "move container to workspace" not in include.read_text(encoding="utf-8")
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


def test_active_config_recognizes_the_documented_owned_glob(tmp_path, monkeypatch):
    config_home = tmp_path / ".config"
    include = config_home / "sway" / "hermes" / "hermes-sway-plugin-rules.conf"
    include.parent.mkdir(parents=True)
    client = _ConfigClient("include ~/.config/sway/hermes/*.conf\n")
    monkeypatch.setenv("HOME", str(tmp_path))

    assert handlers._active_config_has_include(client, include, config_home / "sway" / "config") is True


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


def test_rule_write_treats_live_cardinality_as_advisory(tmp_path):
    config_dir = tmp_path / "configured-sway"
    config_dir.mkdir()
    (config_dir / "config").write_text("# configured\n", encoding="utf-8")
    client = _TreeClient(load_fixture("tree_mixed.json"))

    def runner(*_args, **_kwargs):
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    bound = handlers.build_handlers(
        _settings(config_dir),
        ipc_factory=lambda **_kwargs: client,
        subprocess_run=runner,
    )
    result = json.loads(
        bound["sway_rule"](
            {
                "action": "add",
                "rule_id": "future-app",
                "kind": "window",
                "match": {"app_id": {"value": "not-running-yet"}},
                "intended_cardinality": "one",
                "effects": {"floating": True},
                "reload": False,
            }
        )
    )

    assert result["ok"] is True
    assert result["data"]["cardinality_audit"]["verified"] is False
    assert result["data"]["cardinality_audit"]["match_count"] == 0
    assert "cardinality_unverified" in result["warnings"]
    assert (config_dir / "hermes-sway-plugin-rules.conf").exists()


def test_window_rule_defaults_to_many_for_future_application_windows(tmp_path):
    result = json.loads(
        handlers.build_handlers(_settings(tmp_path / "configured-sway"))["sway_rule"](
            {
                "action": "preview",
                "kind": "window",
                "match": {"app_id": {"value": "org.example.App"}},
                "effects": {"floating": True},
            }
        )
    )

    assert result["ok"] is True
    assert result["data"]["rule"]["intended_cardinality"] == "many"


def test_rule_write_reports_external_statements_without_blocking_unrelated_rules(tmp_path):
    config_dir = tmp_path / "configured-sway"
    config_dir.mkdir()
    (config_dir / "config").write_text(
        'for_window [app_id="^other$"] floating enable\n', encoding="utf-8"
    )

    def runner(*_args, **_kwargs):
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

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
                "rule_id": "independent-rule",
                "kind": "window",
                "match": {"app_id": {"value": "org.example.App"}},
                "effects": {"floating": True},
                "reload": False,
            }
        )
    )

    assert result["ok"] is True
    assert "external_rule_statements_present" in result["warnings"]
    assert result["data"]["external_conflicts"][0]["kind"] == "for_window"
    assert (config_dir / "hermes-sway-plugin-rules.conf").exists()


def test_rule_handler_restores_the_previous_file_when_reload_rolls_back(tmp_path):
    from hermes_sway_plugin import persistent

    config_dir = tmp_path / "configured-sway"
    config_dir.mkdir()
    include = config_dir / "hermes-sway-plugin-rules.conf"
    (config_dir / "config").write_text(f"include {include}\n", encoding="utf-8")
    client = _ConfigClient(f"include {include}\n")

    def runner(*_args, **_kwargs):
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    settings = {
        "config_dir": str(config_dir),
        "ipc_timeout_seconds": 1.0,
        "reload_timeout_seconds": 1.0,
        "backup_keep": 2,
    }
    first = {
        "action": "add",
        "rule_id": "workspace-placement",
        "kind": "workspace_output",
        "workspace": "dev",
        "outputs": ["DP-1"],
        "reload": False,
    }
    assert json.loads(
        handlers.sway_rule(first, settings, subprocess_run=runner, ipc_factory=lambda **_kwargs: client)
    )["ok"] is True
    assert list(config_dir.glob("*.rollback.*")) == []

    updated_without_reload = {
        **first,
        "action": "update",
        "outputs": ["DP-0"],
    }
    assert json.loads(
        handlers.sway_rule(
            updated_without_reload,
            settings,
            subprocess_run=runner,
            ipc_factory=lambda **_kwargs: client,
        )
    )["ok"] is True
    assert list(config_dir.glob("*.rollback.*")) == []
    previous = include.read_text(encoding="utf-8")

    def rollback(_client, restore, *, timeout):
        restore()
        return persistent.ReloadResult(False, True, "injected reload failure")

    changed = {
        **first,
        "action": "update",
        "outputs": ["DP-2"],
        "reload": True,
    }
    with pytest.raises(SwayPluginError) as excinfo:
        handlers.sway_rule(
            changed,
            settings,
            subprocess_run=runner,
            ipc_factory=lambda **_kwargs: client,
            reload_fn=rollback,
        )

    assert excinfo.value.code == "reload_rolled_back"
    assert excinfo.value.details["rolled_back"] is True
    assert include.read_text(encoding="utf-8") == previous
    assert list(config_dir.glob("*.rollback.*")) == []


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


def test_rule_store_rejects_a_stale_read_modify_write(tmp_path):
    config_dir = tmp_path / "configured-sway"
    config_dir.mkdir()
    (config_dir / "config").write_text("# configured\n", encoding="utf-8")
    store = persistent.ManagedRuleStore(config_dir)

    def runner(*_args, **_kwargs):
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    competing_rule = {
        "rule_id": "competing",
        "kind": "workspace_output",
        "workspace": "web",
        "outputs": ["HDMI-A-1"],
    }
    injected = False

    def interleaving_writer(*args, **kwargs):
        nonlocal injected
        if not injected:
            injected = True
            store.add(competing_rule, subprocess_run=runner, backup_count=0)
        return persistent.atomic_replace(*args, **kwargs)

    with pytest.raises(persistent.AtomicWriteError, match="changed since it was read"):
        store.add(
            {
                "rule_id": "stale",
                "kind": "workspace_output",
                "workspace": "dev",
                "outputs": ["DP-1"],
            },
            subprocess_run=runner,
            atomic_replace_fn=interleaving_writer,
            backup_count=0,
        )

    assert [rule["rule_id"] for rule in store.list()] == ["competing"]


@pytest.mark.parametrize(
    ("tool_name", "include_name", "invalid_setting", "invalid_value", "reload_value"),
    (
        ("sway_rule", "hermes-sway-plugin-rules.conf", "ipc_timeout_seconds", 0, True),
        ("sway_rule", "hermes-sway-plugin-rules.conf", "reload_timeout_seconds", 0, True),
        ("sway_rule", "hermes-sway-plugin-rules.conf", None, None, "yes"),
        ("sway_startup", "hermes-sway-plugin-startup.conf", "ipc_timeout_seconds", 0, True),
        ("sway_startup", "hermes-sway-plugin-startup.conf", "reload_timeout_seconds", 0, True),
        ("sway_startup", "hermes-sway-plugin-startup.conf", None, None, "yes"),
    ),
)
def test_persistent_settings_are_validated_before_writing(
    tmp_path,
    tool_name,
    include_name,
    invalid_setting,
    invalid_value,
    reload_value,
):
    config_dir = tmp_path / "configured-sway"
    config_dir.mkdir()
    include = config_dir / include_name
    (config_dir / "config").write_text(f"include {include}\n", encoding="utf-8")
    values = {
        "config_dir": str(config_dir),
        "ipc_timeout_seconds": 1.0,
        "reload_timeout_seconds": 1.0,
        "backup_keep": 0,
    }
    if invalid_setting is not None:
        values[invalid_setting] = invalid_value

    def runner(*_args, **_kwargs):
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    client = _ConfigClient(f"include {include}\n")
    bound = handlers.build_handlers(
        lambda key, default=None: values.get(key, default),
        ipc_factory=lambda **_kwargs: client,
        subprocess_run=runner,
    )
    if tool_name == "sway_rule":
        args = {
            "action": "add",
            "rule_id": "no-write",
            "kind": "workspace_output",
            "workspace": "dev",
            "outputs": ["DP-1"],
            "reload": reload_value,
        }
    else:
        args = {
            "action": "add",
            "startup_id": "no-write",
            "argv": ["waybar"],
            "run_on": "sway_start_only",
            "reload": reload_value,
        }

    result = json.loads(bound[tool_name](args))

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_argument"
    assert not include.exists()
