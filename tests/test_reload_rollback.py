from __future__ import annotations

from hermes_sway_plugin.persistent import reload_with_rollback


class Subscription:
    def __init__(self, events, record):
        self.events, self.record = events, record

    def __enter__(self):
        self.record.append("subscribe")
        return self

    def __exit__(self, *_args):
        self.record.append("close")

    def wait_for(self, predicate, timeout):
        self.record.append(("wait", timeout))
        assert predicate(0, {"change": "reload"})
        return 0, {"change": "reload"}


class Client:
    def __init__(self):
        self.record = []
        self.fail = True

    def subscribe(self, events):
        assert events == ["workspace"]
        return Subscription(events, self.record)

    def command(self, command):
        self.record.append(command)
        if self.fail:
            self.fail = False
            raise RuntimeError("candidate rejected")
        return [{"success": True}]


def test_reload_subscribes_before_command_and_rolls_back_then_reloads():
    client = Client()
    restored = []

    result = reload_with_rollback(client, lambda: restored.append("restore"), timeout=1.5)

    assert result.reloaded is False
    assert result.rolled_back is True
    assert restored == ["restore"]
    assert client.record == ["subscribe", "reload", "close", "subscribe", "reload", ("wait", 1.5), "close"]


def test_successful_reload_waits_for_workspace_reload_event():
    client = Client()
    client.fail = False
    result = reload_with_rollback(client, lambda: None, timeout=2)
    assert result.reloaded is True
    assert result.rolled_back is False
    assert client.record == ["subscribe", "reload", ("wait", 2), "close"]
