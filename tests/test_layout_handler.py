"""Model-facing adapter for bounded layout primitives."""

from __future__ import annotations

import json

from hermes_sway_plugin import handlers

from .helpers import RuntimeClient, load_fixture


def _bound(client):
    return handlers.build_handlers(
        lambda _key, default=None: default,
        ipc_factory=lambda **_kwargs: client,
    )


def test_layout_handler_returns_runtime_envelope_and_ancestry_warning():
    before = load_fixture("tree_mixed.json")
    client = RuntimeClient([before, before])

    result = json.loads(_bound(client)["sway_layout"]({"action": "split_at", "target": {"con_id": 103}, "orientation": "horizontal"}))

    assert result["ok"] is True
    assert result["scope"] == "runtime"
    assert result["data"]["action"] == "split_at"
    assert result["data"]["con_id"] == 103
    assert result["warnings"] == [
        "Sway may automatically split or flatten containers, changing ancestry; inspect the resulting layout"
    ]
    assert client.commands == ["[con_id=103] split horizontal"]


def test_layout_handler_reports_invalid_orientation_as_argument_error():
    client = RuntimeClient([load_fixture("tree_mixed.json")])

    result = json.loads(_bound(client)["sway_layout"]({"action": "split_at", "target": {"con_id": 103}, "orientation": "diagonal"}))

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_argument"
    assert client.commands == []


def test_layout_handler_requires_an_other_target_for_swap():
    client = RuntimeClient([load_fixture("tree_mixed.json")])

    result = json.loads(_bound(client)["sway_layout"]({"action": "swap", "target": {"con_id": 103}}))

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_argument"
    assert client.commands == []
