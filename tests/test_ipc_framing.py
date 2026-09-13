"""Frame-level tests for the Sway IPC transport."""

from __future__ import annotations

import json
import socket
import struct
import time

import pytest

from hermes_sway_plugin import ipc

from .fakes import FakeSway, command_reply, version_payload


def _socket_path(tmp_path) -> str:
    return str(tmp_path / "sway-ipc.sock")


def test_request_reads_a_fragmented_frame(tmp_path):
    fake = FakeSway(_socket_path(tmp_path), replies={ipc.GET_VERSION: version_payload()}, send_all=False)
    try:
        client = ipc.SwayIPC(socket_path=fake.socket_path, timeout=5.0)
        reply = client.request(ipc.GET_VERSION)
    finally:
        fake.close()
    assert reply["major"] == 1 and reply["minor"] == 9


def test_request_rejects_bad_magic(tmp_path):
    fake = FakeSway(
        _socket_path(tmp_path),
        corrupt=lambda _type: ipc.HEADER.pack(b"xx-ipc", 2, ipc.GET_VERSION) + b"{}",
    )
    try:
        client = ipc.SwayIPC(socket_path=fake.socket_path, timeout=5.0)
        with pytest.raises(ipc.SwayProtocolError):
            client.request(ipc.GET_VERSION)
    finally:
        fake.close()


def test_request_rejects_mismatched_reply_type(tmp_path):
    fake = FakeSway(
        _socket_path(tmp_path),
        replies={ipc.GET_TREE: {}},
        reply_type=ipc.GET_VERSION,
    )
    try:
        client = ipc.SwayIPC(socket_path=fake.socket_path, timeout=5.0)
        with pytest.raises(ipc.SwayProtocolError):
            client.request(ipc.GET_TREE)
    finally:
        fake.close()


def test_request_rejects_malformed_json(tmp_path):
    fake = FakeSway(
        _socket_path(tmp_path),
        corrupt=lambda _type: ipc.HEADER.pack(ipc.MAGIC, 5, ipc.GET_VERSION) + b"{oops",
    )
    try:
        client = ipc.SwayIPC(socket_path=fake.socket_path, timeout=5.0)
        with pytest.raises(ipc.SwayProtocolError):
            client.request(ipc.GET_VERSION)
    finally:
        fake.close()


def test_request_rejects_invalid_utf8(tmp_path):
    fake = FakeSway(
        _socket_path(tmp_path),
        corrupt=lambda _type: ipc.HEADER.pack(ipc.MAGIC, 2, ipc.GET_VERSION) + b"\xff\xfe",
    )
    try:
        client = ipc.SwayIPC(socket_path=fake.socket_path, timeout=5.0)
        with pytest.raises(ipc.SwayProtocolError):
            client.request(ipc.GET_VERSION)
    finally:
        fake.close()


def test_request_rejects_oversized_declared_payload(tmp_path):
    fake = FakeSway(
        _socket_path(tmp_path),
        corrupt=lambda _type: ipc.HEADER.pack(
            ipc.MAGIC, ipc.MAX_PAYLOAD_BYTES + 1, ipc.GET_VERSION
        ),
    )
    try:
        client = ipc.SwayIPC(socket_path=fake.socket_path, timeout=5.0)
        with pytest.raises(ipc.SwayPayloadTooLarge):
            client.request(ipc.GET_VERSION)
    finally:
        fake.close()


def test_request_times_out_without_a_reply(tmp_path):
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    path = _socket_path(tmp_path)
    server.bind(path)
    server.listen(1)

    def accept_and_hang() -> None:
        conn, _ = server.accept()
        time.sleep(1.5)
        conn.close()

    import threading

    thread = threading.Thread(target=accept_and_hang, daemon=True)
    thread.start()
    try:
        client = ipc.SwayIPC(socket_path=path, timeout=0.25)
        with pytest.raises(ipc.SwayTimeout):
            client.request(ipc.GET_VERSION)
    finally:
        server.close()


def test_command_parses_a_run_command_reply(tmp_path):
    fake = FakeSway(_socket_path(tmp_path), commands=command_reply(success=True))
    try:
        client = ipc.SwayIPC(socket_path=fake.socket_path, timeout=5.0)
        reply = client.command("focus")
    finally:
        fake.close()
    assert reply == [{"success": True}]
    assert fake.requests[0][0] == ipc.RUN_COMMAND


def test_recv_exact_reports_closed_connection():
    left, right = socket.socketpair()
    try:
        right.close()
        with pytest.raises(ipc.SwayProtocolError):
            ipc.recv_exact(left, 4)
    finally:
        left.close()


def test_request_accepts_an_empty_payload(tmp_path):
    fake = FakeSway(
        _socket_path(tmp_path),
        corrupt=lambda _type: ipc.HEADER.pack(ipc.MAGIC, 0, ipc.GET_MARKS),
    )
    try:
        client = ipc.SwayIPC(socket_path=fake.socket_path, timeout=5.0)
        assert client.request(ipc.GET_MARKS) is None
    finally:
        fake.close()
