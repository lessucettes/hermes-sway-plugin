"""End-to-end managed-resource behavior for ``sway_startup``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_sway_plugin import handlers, persistent


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


class _ConfigClient:
    """Live IPC double whose running configuration lacks the plugin include."""

    def __init__(self, config=""):
        self.config = config
        self.requests = []
        self.commands = []

    def request(self, message_type):
        self.requests.append(message_type)
        return {"config": self.config}

    def command(self, command):
        self.commands.append(command)


def _runner(calls):
    def run(argv, **_kwargs):
        calls.append(argv)
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    return run


def _configured(tmp_path: Path) -> Path:
    config_dir = tmp_path / "configured-sway"
    config_dir.mkdir()
    include = config_dir / "hermes-sway-plugin-startup.conf"
    (config_dir / "config").write_text(f"include {include}\n", encoding="utf-8")
    return config_dir


def test_startup_preview_renders_exec_without_writing(tmp_path):
    config_dir = tmp_path / "configured-sway"
    bound = handlers.build_handlers(_settings(config_dir))

    result = json.loads(
        bound["sway_startup"](
            {
                "action": "preview",
                "startup_id": "telegram",
                "argv": ["telegram-desktop", "--start-intro"],
                "run_on": "sway_start_only",
            }
        )
    )

    assert result["ok"] is True
    assert result["scope"] == "persistent"
    assert result["data"]["rendered"] == "exec telegram-desktop --start-intro"
    assert result["data"]["entry"]["startup_id"] == "telegram"
    assert "config_rollback_cannot_terminate_launched_processes" not in result["warnings"]
    assert not config_dir.exists()


def test_startup_exec_always_requires_explicit_reload_acknowledgement(tmp_path):
    config_dir = tmp_path / "configured-sway"
    config_dir.mkdir()
    bound = handlers.build_handlers(_settings(config_dir))

    refused = json.loads(
        bound["sway_startup"](
            {
                "action": "preview",
                "startup_id": "panel",
                "argv": ["waybar"],
                "run_on": "sway_start_and_every_reload",
            }
        )
    )
    allowed = json.loads(
        bound["sway_startup"](
            {
                "action": "preview",
                "startup_id": "panel",
                "argv": ["waybar"],
                "run_on": "sway_start_and_every_reload",
                "acknowledge_reload_relaunch": True,
            }
        )
    )

    assert refused["ok"] is False
    assert refused["error"]["code"] == "reload_relaunch_not_acknowledged"
    assert allowed["ok"] is True
    assert allowed["data"]["rendered"] == "exec_always waybar"
    assert "config_rollback_cannot_terminate_launched_processes" in allowed["warnings"]


def test_startup_add_persists_shell_safe_command_and_list_reads_it_back(tmp_path):
    config_dir = _configured(tmp_path)
    calls = []
    client = _ConfigClient("include /other/rules.conf\n")
    bound = handlers.build_handlers(
        _settings(config_dir), ipc_factory=lambda **_kwargs: client, subprocess_run=_runner(calls)
    )

    added = json.loads(
        bound["sway_startup"](
            {
                "action": "add",
                "startup_id": "quoted-app",
                "argv": ["kitty", "--title", "it's here", "a b"],
                "run_on": "sway_start_only",
            }
        )
    )
    listed = json.loads(bound["sway_startup"]({"action": "list"}))
    fetched = json.loads(bound["sway_startup"]({"action": "get", "startup_id": "quoted-app"}))

    include = config_dir / "hermes-sway-plugin-startup.conf"
    text = include.read_text(encoding="utf-8")
    assert added["ok"] is True
    assert added["data"]["entry"]["argv"] == ["kitty", "--title", "it's here", "a b"]
    assert "exec kitty --title 'it'\"'\"'s here' 'a b'" in text
    assert listed["data"]["entries"] == [added["data"]["entry"]]
    assert fetched["data"]["entry"] == added["data"]["entry"]
    assert fetched["data"]["entry"]["startup_id"] == "quoted-app"
    assert "include_not_configured" in added["warnings"]
    assert client.commands == []
    assert len(calls) == 2


def test_startup_add_rejects_a_duplicate_normalized_command(tmp_path):
    config_dir = _configured(tmp_path)
    calls = []
    bound = handlers.build_handlers(_settings(config_dir), ipc_factory=_offline, subprocess_run=_runner(calls))

    bound["sway_startup"](
        {
            "action": "add",
                            "startup_id": "first",
            "argv": ["waybar"],
            "run_on": "sway_start_only",
        }
    )
    duplicate = json.loads(
        bound["sway_startup"](
            {
                "action": "add",
                "startup_id": "second",
                "argv": ["waybar"],
                "run_on": "sway_start_only",
            }
        )
    )

    assert duplicate["ok"] is False
    assert duplicate["error"]["code"] == "duplicate_startup_entry"
    listed = json.loads(bound["sway_startup"]({"action": "list"}))
    assert [entry["startup_id"] for entry in listed["data"]["entries"]] == ["first"]


def test_missing_startup_entry_uses_startup_specific_error_code(tmp_path):
    config_dir = _configured(tmp_path)
    bound = handlers.build_handlers(_settings(config_dir), ipc_factory=_offline, subprocess_run=_runner([]))

    result = json.loads(bound["sway_startup"]({"action": "get", "startup_id": "missing"}))

    assert result["ok"] is False
    assert result["error"]["code"] == "startup_not_found"


def test_startup_update_and_remove_keep_the_managed_include_deterministic(tmp_path):
    config_dir = _configured(tmp_path)
    calls = []
    bound = handlers.build_handlers(_settings(config_dir), ipc_factory=_offline, subprocess_run=_runner(calls))

    bound["sway_startup"]({"action": "add", "startup_id": "panel", "argv": ["waybar"], "run_on": "sway_start_only"})
    updated = json.loads(
        bound["sway_startup"](
            {
                "action": "update",
                "startup_id": "panel",
                "argv": ["waybar", "--log-level", "warning"],
                "run_on": "sway_start_only",
            }
        )
    )
    removed = json.loads(bound["sway_startup"]({"action": "remove", "startup_id": "panel"}))
    listed = json.loads(bound["sway_startup"]({"action": "list"}))

    assert updated["data"]["entry"]["argv"] == ["waybar", "--log-level", "warning"]
    assert removed["data"]["entry"]["startup_id"] == "panel"
    assert "runs_on_sway_start_only" not in removed["warnings"]
    assert listed["data"]["entries"] == []
    assert "exec_always" not in (config_dir / "hermes-sway-plugin-startup.conf").read_text(encoding="utf-8")


def test_startup_write_refuses_an_empty_argv_array(tmp_path):
    config_dir = _configured(tmp_path)
    bound = handlers.build_handlers(_settings(config_dir))

    result = json.loads(
        bound["sway_startup"]({"action": "preview", "startup_id": "broken", "argv": [], "run_on": "sway_start_only"})
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_argument"


def test_startup_store_rejects_a_stale_read_modify_write(tmp_path):
    config_dir = _configured(tmp_path)
    store = persistent.ManagedStartupStore(config_dir)
    runner = _runner([])
    competing_entry = {
        "entry_id": "competing",
        "argv": ["waybar"],
        "run_on": "sway_start_only",
    }
    injected = False

    def interleaving_writer(*args, **kwargs):
        nonlocal injected
        if not injected:
            injected = True
            store.add(competing_entry, subprocess_run=runner, backup_count=0)
        return persistent.atomic_replace(*args, **kwargs)

    with pytest.raises(persistent.AtomicWriteError, match="changed since it was read"):
        store.add(
            {
                "entry_id": "stale",
                "argv": ["mako"],
                "run_on": "sway_start_only",
            },
            subprocess_run=runner,
            atomic_replace_fn=interleaving_writer,
            backup_count=0,
        )

    assert [entry["entry_id"] for entry in store.list()] == ["competing"]
