"""Handlers reject action-irrelevant fields instead of ignoring model mistakes."""

from __future__ import annotations

import json

from hermes_sway_plugin import handlers


def _never_connect(**_kwargs):
    raise AssertionError("invalid arguments must be rejected before Sway IPC")


def _bound(name):
    return handlers.build_handlers(
        lambda _key, default=None: default,
        ipc_factory=_never_connect,
    )[name]


def test_window_focus_rejects_move_arguments():
    result = json.loads(
        _bound("sway_window")(
            {"action": "focus", "target": {"con_id": 10}, "workspace": "2"}
        )
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_argument"
    assert result["error"]["details"]["fields"] == ["workspace"]


def test_workspace_focus_rejects_output_argument():
    result = json.loads(
        _bound("sway_workspace")(
            {"action": "focus_or_create", "workspace": "2", "output": "DP-1"}
        )
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_argument"


def test_layout_split_rejects_parent_layout_argument():
    result = json.loads(
        _bound("sway_layout")(
            {
                "action": "split_at",
                "target": {"con_id": 10},
                "orientation": "horizontal",
                "layout": "tabbed",
            }
        )
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_argument"
