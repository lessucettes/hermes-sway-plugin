"""A close must wait for the asynchronous client exit instead of failing early.

Sway's ``kill`` terminates the client, which exits asynchronously.  Verified on
a real Sway 1.9 session: the window is still present in the tree 5-7 ms after the
command reply and is gone about 250 ms later, so an immediate post-tree check
reports a false ``postcondition_failed``.
"""

from __future__ import annotations

import pytest

from hermes_sway_plugin import ipc
from hermes_sway_plugin.errors import SwayPluginError
from hermes_sway_plugin.runtime import RuntimeService

from .helpers import RuntimeClient, load_fixture, without_node_tree


class Clock:
    """Deterministic clock whose sleeps advance virtual time."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_close_waits_for_the_client_exit_and_reports_success(tmp_path):
    before = load_fixture("tree_mixed.json")
    clock = Clock()
    client = RuntimeClient([before, before, without_node_tree(before, 101)])

    result = RuntimeService(
        client, monotonic=clock.monotonic, sleep=clock.sleep, close_verify_seconds=2.0
    ).window({"con_id": 101}, "close", confirm_close=True)

    assert result == {"con_id": 101, "action": "close", "warnings": []}
    assert client.commands == ["[con_id=101] kill"]
    assert clock.slept and sum(clock.slept) <= 2.0


def test_close_still_fails_when_the_window_never_disappears():
    before = load_fixture("tree_mixed.json")
    clock = Clock()
    client = RuntimeClient([before] * 30)

    with pytest.raises(SwayPluginError) as excinfo:
        RuntimeService(
            client, monotonic=clock.monotonic, sleep=clock.sleep, close_verify_seconds=1.0
        ).window({"con_id": 101}, "close", confirm_close=True)

    assert excinfo.value.code == "postcondition_failed"
    assert "remained after close" in excinfo.value.message
    assert clock.now >= 1.0
    assert client.requests.count(ipc.GET_TREE) >= 3
