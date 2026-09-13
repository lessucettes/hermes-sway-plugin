"""Subscription tests: subscribe-before-events, event filtering, timeouts."""

from __future__ import annotations

import json
import time

import pytest

from hermes_sway_plugin import ipc

from .fakes import FakeSway, version_payload


def _socket_path(tmp_path) -> str:
    return str(tmp_path / "sway-ipc.sock")


def _reload_event() -> tuple[int, dict]:
    return (ipc.EVENT_WORKSPACE, {"change": "reload", "current": None, "old": None})


def test_subscribe_verifies_the_initial_reply(tmp_path):
    fake = FakeSway(
        _socket_path(tmp_path),
        replies={ipc.GET_VERSION: version_payload()},
        subscribe_reply={"success": False, "error": "nope"},
    )
    try:
        client = ipc.SwayIPC(socket_path=fake.socket_path, timeout=5.0)
        with pytest.raises(ipc.SwayProtocolError):
            client.subscribe(["workspace"])
    finally:
        fake.close()


def test_subscription_accepts_only_event_frames(tmp_path):
    fake = FakeSway(
        _socket_path(tmp_path),
        events=[_reload_event()],
    )
    try:
        client = ipc.SwayIPC(socket_path=fake.socket_path, timeout=5.0)
        with client.subscribe(["workspace"]) as subscription:
            message_type, body = subscription.recv(timeout=2.0)
    finally:
        fake.close()
    assert message_type == ipc.EVENT_WORKSPACE
    assert body["change"] == "reload"
    assert fake.requests[0][0] == ipc.SUBSCRIBE


def test_subscription_times_out_monotonically(tmp_path):
    fake = FakeSway(_socket_path(tmp_path), events=[])
    try:
        client = ipc.SwayIPC(socket_path=fake.socket_path, timeout=5.0)
        with client.subscribe(["window"]) as subscription:
            started = time.monotonic()
            with pytest.raises(ipc.SwayTimeout):
                subscription.wait_for(lambda _t, _b: True, timeout=0.3)
            elapsed = time.monotonic() - started
    finally:
        fake.close()
    assert 0.2 <= elapsed < 3.0


def test_subscription_close_is_idempotent_and_blocks_further_reads(tmp_path):
    fake = FakeSway(_socket_path(tmp_path), events=[])
    try:
        client = ipc.SwayIPC(socket_path=fake.socket_path, timeout=5.0)
        subscription = client.subscribe(["window"])
        subscription.close()
        subscription.close()
        with pytest.raises(ipc.SwayProtocolError):
            subscription.recv(timeout=0.1)
    finally:
        fake.close()


def test_subscription_requires_an_event_name():
    client = ipc.SwayIPC(socket_path="/nonexistent/socket", timeout=1.0)
    with pytest.raises(ipc.SwayProtocolError):
        client.subscribe([])
