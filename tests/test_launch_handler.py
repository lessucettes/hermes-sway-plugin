"""Model-facing adapter for safe launch and correlation."""

from __future__ import annotations

import json

from hermes_sway_plugin import handlers, ipc

from .helpers import RuntimeClient, load_fixture


class Process:
    pid = 4242


def test_launch_handler_can_start_without_window_wait_or_ipc_access(tmp_path):
    captured = {}

    def factory(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return Process()

    bound = handlers.build_handlers(
        lambda _key, default=None: default,
        process_factory=factory,
    )["sway_launch"]

    result = json.loads(bound({"argv": ["kitty", "--single-instance"], "cwd": str(tmp_path), "wait_for_window": False}))

    assert result == {
        "ok": True,
        "scope": "runtime",
        "data": {"pid": 4242, "started": True, "correlation": {"status": "not_requested"}},
        "warnings": ["window correlation was not requested"],
    }
    assert captured["argv"] == ["kitty", "--single-instance"]
    assert captured["shell"] is False


def test_launch_handler_returns_a_bounded_timeout_result_when_correlation_has_no_new_window():
    baseline = load_fixture("tree_mixed.json")
    client = RuntimeClient([baseline, baseline])

    def factory(_argv, **_kwargs):
        return Process()

    bound = handlers.build_handlers(
        lambda _key, default=None: default,
        ipc_factory=lambda **_kwargs: client,
        process_factory=factory,
    )["sway_launch"]
    result = json.loads(bound({"argv": ["kitty"], "wait_for_window": True, "timeout_seconds": 0.5}))

    assert result["ok"] is True
    assert result["scope"] == "runtime"
    assert result["data"]["pid"] == 4242
    assert result["data"]["correlation"]["status"] == "timeout"
    assert "not guaranteed" in result["data"]["correlation"]["reasons"][-1]
    assert client.requests == [ipc.GET_VERSION, ipc.GET_TREE, ipc.GET_TREE]
