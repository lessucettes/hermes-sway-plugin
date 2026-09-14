"""Model-facing adapters for verified runtime window/workspace services."""

from __future__ import annotations

import json

from hermes_sway_plugin import handlers

from .helpers import RuntimeClient, focused_tree, load_fixture


def _bound(client):
    return handlers.build_handlers(
        lambda _key, default=None: default,
        ipc_factory=lambda **_kwargs: client,
    )


def test_window_handler_returns_runtime_envelope_after_verified_focus():
    before = load_fixture("tree_mixed.json")
    client = RuntimeClient([before, focused_tree(before, 103)])

    result = json.loads(_bound(client)["sway_window"]({"target": {"con_id": 103}, "action": "focus"}))

    assert result == {
        "ok": True,
        "scope": "runtime",
        "data": {"con_id": 103, "action": "focus", "warnings": []},
        "warnings": [],
    }
    assert client.commands == ["[con_id=103] focus"]


def test_window_handler_returns_typed_error_without_sending_command_for_stale_target():
    client = RuntimeClient([load_fixture("tree_mixed.json")])

    result = json.loads(_bound(client)["sway_window"]({"target": {"con_id": 999999}, "action": "focus"}))

    assert result["ok"] is False
    assert result["error"]["code"] == "target_not_found"
    assert client.commands == []


def test_workspace_handler_returns_runtime_envelope_after_verified_focus():
    before = load_fixture("tree_mixed.json")
    client = RuntimeClient([before, focused_tree(before, 103)])

    result = json.loads(_bound(client)["sway_workspace"]({"action": "focus_or_create", "workspace": "2"}))

    assert result["ok"] is True
    assert result["scope"] == "runtime"
    assert result["data"]["workspace"] == "2"
    assert client.commands == ['workspace --no-auto-back-and-forth "2"']
