"""Best-effort process-to-window correlation for Sway launches."""

from __future__ import annotations

import pytest

from hermes_sway_plugin import ipc
from hermes_sway_plugin.launch import correlate_launch, launch_and_correlate


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


def _window(con_id: int, *, app_id: str = "kitty", pid: int | None = 4242):
    return {"id": con_id, "type": "con", "name": "chat", "app_id": app_id, "pid": pid}


class Subscription:
    def __init__(self, record):
        self.record = record
        self.sent = False

    def recv(self, timeout):
        self.record.append(("recv", timeout))
        if self.sent:
            raise TimeoutError()
        self.sent = True
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
        if len(self.trees) > 1:
            return self.trees.pop(0)
        return self.trees[0]


class Events:
    def __init__(self, events):
        self.events = iter(events)
        self.calls = []

    def recv(self, timeout):
        self.calls.append(timeout)
        try:
            event = next(self.events)
        except StopIteration:
            raise TimeoutError() from None
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


def test_owned_subscription_close_failure_preserves_post_launch_correlation():
    client = Client([_tree(), _tree(_window(99))], [])

    class CloseFailingEvents(Events):
        def close(self):
            raise OSError("subscription close failed")

    result = correlate_launch(
        client,
        lambda: {"pid": 4242},
        expected_identity={"app_id": "kitty"},
        timeout_seconds=1,
        subscription_factory=lambda: CloseFailingEvents(
            [(ipc.EVENT_WINDOW, {"change": "new"})]
        ),
    )

    assert result["started"] is True
    assert result["pid"] == 4242
    assert result["status"] == "matched"
    assert any("subscription close failed" in reason for reason in result["reasons"])


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


def test_correlate_launch_refreshes_for_any_window_event():
    record = []
    client = Client([_tree(), _tree(_window(99))], record)
    subscription = Events([(ipc.EVENT_WINDOW, {"change": "title"})])

    result = correlate_launch(
        client,
        lambda: {"pid": 4242},
        expected_identity={"app_id": "kitty"},
        timeout_seconds=1,
        subscription=subscription,
    )

    assert result["status"] == "matched"
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
    assert record == ["tree", "tree"]


def test_correlate_launch_performs_a_final_tree_query_when_no_event_arrives():
    record = []
    client = Client([_tree(), _tree(_window(99))], record)
    subscription = Events([TimeoutError()])

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


def test_correlate_launch_settles_before_declaring_one_window_unique():
    record = []
    client = Client(
        [_tree(), _tree(_window(99)), _tree(_window(99), _window(100))],
        record,
    )
    subscription = Events(
        [
            (ipc.EVENT_WINDOW, {"change": "new"}),
            (ipc.EVENT_WINDOW, {"change": "new"}),
        ]
    )

    result = correlate_launch(
        client,
        lambda: {"pid": 4242},
        expected_identity={"app_id": "kitty"},
        timeout_seconds=1,
        subscription=subscription,
    )

    assert result["status"] == "ambiguous"
    assert [candidate["con_id"] for candidate in result["candidates"]] == [99, 100]


def test_correlate_launch_settles_an_ambiguous_provisional_result_for_stronger_evidence():
    record = []
    client = Client(
        [
            _tree(),
            _tree(_window(99, pid=None), _window(100, pid=None)),
            _tree(_window(99, pid=None), _window(100, pid=4242)),
        ],
        record,
    )
    subscription = Events(
        [
            (ipc.EVENT_WINDOW, {"change": "new"}),
            (ipc.EVENT_WINDOW, {"change": "title"}),
        ]
    )

    result = correlate_launch(
        client,
        lambda: {"pid": 4242},
        expected_identity={"app_id": "kitty"},
        timeout_seconds=1,
        subscription=subscription,
    )

    assert result["status"] == "matched"
    assert result["match_basis"] == "pid_exact"
    assert [candidate["con_id"] for candidate in result["candidates"]] == [100]
    assert record == ["tree", "tree", "tree"]


def test_correlate_launch_prefers_strong_pid_evidence_over_identity_only():
    record = []
    client = Client(
        [_tree(), _tree(_window(99, pid=4242), _window(100, pid=None))],
        record,
    )
    subscription = Events([(ipc.EVENT_WINDOW, {"change": "new"})])

    result = correlate_launch(
        client,
        lambda: {"pid": 4242},
        expected_identity={"app_id": "kitty"},
        timeout_seconds=1,
        subscription=subscription,
    )

    assert result["status"] == "matched"
    assert result["match_basis"] == "pid_exact"
    assert [candidate["con_id"] for candidate in result["candidates"]] == [99]


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


def test_post_launch_observation_failure_still_reports_the_started_process():
    record = []

    class FailingClient(Client):
        def request(self, message_type):
            if self.record.count("tree"):
                raise ipc.SwayProtocolError("tree unavailable after launch")
            return super().request(message_type)

    client = FailingClient([_tree()], record)
    subscription = Events([(ipc.EVENT_WINDOW, {"change": "new"})])

    result = correlate_launch(
        client,
        lambda: {"pid": 4242},
        timeout_seconds=1,
        subscription=subscription,
    )

    assert result["started"] is True
    assert result["pid"] == 4242
    assert result["status"] == "observation_failed"
    assert "tree unavailable after launch" in result["observation_error"]


def test_post_launch_oversized_tree_still_reports_the_started_process():
    record = []

    class OversizedTreeClient(Client):
        def request(self, message_type):
            if self.record.count("tree"):
                raise ipc.SwayPayloadTooLarge("tree payload exceeds cap")
            return super().request(message_type)

    client = OversizedTreeClient([_tree()], record)
    subscription = Events([(ipc.EVENT_WINDOW, {"change": "new"})])

    result = correlate_launch(
        client,
        lambda: {"pid": 4242},
        timeout_seconds=1,
        subscription=subscription,
    )

    assert result["started"] is True
    assert result["pid"] == 4242
    assert result["status"] == "observation_failed"
    assert "tree payload exceeds cap" in result["observation_error"]


@pytest.mark.parametrize(
    "error",
    [
        ipc.SwayProtocolError("bad event frame"),
        ipc.SwayPayloadTooLarge("event payload exceeds cap"),
        ipc.SwayUnavailable("subscription socket disappeared"),
        OSError("subscription socket read failed"),
    ],
)
def test_post_launch_subscription_recv_failure_reports_the_started_process(error):
    client = Client([_tree()], [])
    subscription = Events([error])

    result = correlate_launch(
        client,
        lambda: {"pid": 4242},
        timeout_seconds=1,
        subscription=subscription,
    )

    assert result["started"] is True
    assert result["pid"] == 4242
    assert result["status"] == "observation_failed"
    assert str(error) in result["observation_error"]


def test_launch_and_correlate_baselines_before_using_the_injected_safe_process_factory(tmp_path):
    record = []
    client = Client([_tree(), _tree(_window(99))], record)
    subscription = Events([(ipc.EVENT_WINDOW, {"change": "new"})])
    captured = {}

    class Process:
        pid = 4242

    def factory(argv, **kwargs):
        record.append("launch")
        captured["argv"] = argv
        captured.update(kwargs)
        return Process()

    result = launch_and_correlate(
        client,
        ["kitty", "--title", "chat"],
        str(tmp_path),
        expected_identity={"app_id": "kitty"},
        timeout_seconds=1,
        process_factory=factory,
        subscription=subscription,
    )

    assert record == ["tree", "launch", "tree"]
    assert result["status"] == "matched"
    assert captured["argv"] == ["kitty", "--title", "chat"]
    assert captured["shell"] is False
    assert captured["close_fds"] is True
    assert captured["start_new_session"] is True
