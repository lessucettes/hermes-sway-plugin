"""A close reports the request separately from observed disappearance.

Sway's ``kill`` asks the view to close; it does not guarantee when the client will
comply. Bounded polling provides useful observation without turning a responsive
but still-open client into a false command failure.
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


def test_close_waits_for_disappearance_and_reports_observation(tmp_path):
    before = load_fixture("tree_mixed.json")
    clock = Clock()
    client = RuntimeClient([before, before, without_node_tree(before, 101)])

    result = RuntimeService(
        client, monotonic=clock.monotonic, sleep=clock.sleep, close_verify_seconds=2.0
    ).window({"con_id": 101}, "close", confirm_close=True)

    assert result == {
        "con_id": 101,
        "action": "close",
        "close_requested": True,
        "closed_observed": True,
        "warnings": [],
    }
    assert client.commands == ["[con_id=101] kill"]
    assert clock.slept and sum(clock.slept) <= 2.0


def test_close_reports_an_unobserved_close_request_instead_of_failing():
    before = load_fixture("tree_mixed.json")
    clock = Clock()
    client = RuntimeClient([before] * 30)

    result = RuntimeService(
        client, monotonic=clock.monotonic, sleep=clock.sleep, close_verify_seconds=1.0
    ).window({"con_id": 101}, "close", confirm_close=True)

    assert result == {
        "con_id": 101,
        "action": "close",
        "close_requested": True,
        "closed_observed": False,
        "warnings": ["close_requested_but_window_still_observed"],
    }
    assert clock.now >= 1.0
    assert client.requests.count(ipc.GET_TREE) >= 3
