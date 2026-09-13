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
