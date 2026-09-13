"""Best-effort process-to-window correlation for Sway launches."""

from __future__ import annotations

from hermes_sway_plugin import ipc
from hermes_sway_plugin.launch import correlate_launch


def _tree(*windows):
    return {
        "id": 1,
        "type": "root",
        "nodes": [
            {
                "id": 2,
                "type": "output",
                "name": "DP-1",
                "nodes": [
                    {
                        "id": 3,
                        "type": "workspace",
                        "name": "1",
                        "num": 1,
                        "nodes": list(windows),
                    }
                ],
            }
        ],
    }


def _window(con_id, *, app_id="kitty", pid=4242):
    return {"id": con_id, "type": "con", "name": "chat", "app_id": app_id, "pid": pid}


class Subscription:
    def __init__(self, record):
        self.record = record

    def recv(self, timeout):
        self.record.append(("recv", timeout))
        return ipc.EVENT_WINDOW, {"change": "new", "container": {"id": 99}}

    def close(self):
        self.record.append("close")


class Client:
    def __init__(self, trees, record):
        self.trees = list(trees)
        self.record = record

    def subscribe(self, events):
        self.record.append(("subscribe", events))
        return Subscription(self.record)

    def request(self, message_type):
        assert message_type == ipc.GET_TREE
        self.record.append("tree")
        return self.trees.pop(0)


class Events:
    def __init__(self, events):
        self.events = iter(events)
        self.calls = []

    def recv(self, timeout):
        self.calls.append(timeout)
        event = next(self.events)
        if isinstance(event, BaseException):
            raise event
        return event


def test_correlate_launch_subscribes_before_baseline_and_matches_new_exact_identity_and_pid():
    record = []
    client = Client([_tree(_window(10)), _tree(_window(10), _window(99))], record)

    def launch():
        record.append("launch")
        return {"pid": 4242, "started": True}

    result = correlate_launch(client, launch, expected_identity={"app_id": "kitty"}, timeout_seconds=1)

    assert record[:3] == [("subscribe", ["window"]), "tree", "launch"]
    assert result["status"] == "matched"
    assert [candidate["con_id"] for candidate in result["candidates"]] == [99]
    assert any("exact expected identity" in reason for reason in result["reasons"])
    assert "window PID matches launched process PID" in result["reasons"]
    assert "not guaranteed" in result["reasons"][-1]
    assert record[-1] == "close"


def test_correlate_launch_uses_refreshed_tree_not_window_new_event_container():
    record = []
    client = Client([_tree(), _tree(_window(99))], record)
    subscription = Events([(ipc.EVENT_WINDOW, {"change": "new", "container": {"id": 666}})])

    result = correlate_launch(
        client,
        lambda: {"pid": 4242},
        expected_identity={"app_id": "kitty"},
        timeout_seconds=1,
        subscription=subscription,
    )

    assert result["status"] == "matched"
    assert [candidate["con_id"] for candidate in result["candidates"]] == [99]
    assert record == ["tree", "tree"]


def test_correlate_launch_ignores_non_window_new_events_without_refreshing_the_tree():
    record = []
    client = Client([_tree()], record)
    subscription = Events(
        [
            (ipc.EVENT_WORKSPACE, {"change": "new"}),
            TimeoutError(),
        ]
    )

    result = correlate_launch(
        client,
        lambda: {"pid": 4242},
        timeout_seconds=1,
        subscription=subscription,
    )

    assert result["status"] == "timeout"
    assert record == ["tree"]


def test_correlate_launch_accepts_a_window_process_descended_from_the_launcher():
    record = []
    client = Client([_tree(), _tree(_window(99, pid=5000))], record)
    subscription = Events([(ipc.EVENT_WINDOW, {"change": "new"})])

    result = correlate_launch(
        client,
        lambda: {"pid": 4242},
        timeout_seconds=1,
        subscription=subscription,
        ancestor_pids=lambda pid: (4242, 1) if pid == 5000 else (),
    )

    assert result["status"] == "matched"
    assert "launched process PID is an ancestor of the window PID" in result["reasons"]


def test_correlate_launch_reports_ambiguous_when_multiple_new_windows_meet_criteria():
    record = []
    client = Client([_tree(), _tree(_window(99), _window(100))], record)
    subscription = Events([(ipc.EVENT_WINDOW, {"change": "new"})])

    result = correlate_launch(
        client,
        lambda: {"pid": 4242},
        expected_identity={"app_id": "kitty"},
        timeout_seconds=1,
        subscription=subscription,
    )

    assert result["status"] == "ambiguous"
    assert [candidate["con_id"] for candidate in result["candidates"]] == [99, 100]
    assert any("2 new windows" in reason for reason in result["reasons"])
    assert "not guaranteed" in result["reasons"][-1]


def test_correlate_launch_times_out_with_new_identity_mismatch_candidates_and_reasons():
    record = []
    client = Client([_tree(), _tree(_window(99, app_id="xterm"))], record)
    subscription = Events(
        [
            (ipc.EVENT_WINDOW, {"change": "new"}),
            TimeoutError(),
        ]
    )

    result = correlate_launch(
        client,
        lambda: {"pid": 4242},
        expected_identity={"app_id": "kitty"},
        timeout_seconds=1,
        subscription=subscription,
    )

    assert result["status"] == "timeout"
    assert [candidate["con_id"] for candidate in result["candidates"]] == [99]
    assert any("exact expected identity" in reason for reason in result["reasons"])
    assert any("timed out" in reason for reason in result["reasons"])
    assert "not guaranteed" in result["reasons"][-1]
