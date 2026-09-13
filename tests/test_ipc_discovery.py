"""Tests for socket discovery, version gating, framing, and subscriptions."""

from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path

import pytest

from hermes_sway_plugin import ipc
from hermes_sway_plugin.errors import SwayPluginError


def test_socket_discovery_prefers_explicit_path(monkeypatch):
    monkeypatch.setenv("SWAYSOCK", "/tmp/from-env.sock")
    assert ipc.discover_socket_path("/tmp/explicit.sock") == "/tmp/explicit.sock"


def test_socket_discovery_uses_swaysock(monkeypatch):
    monkeypatch.setenv("SWAYSOCK", "/tmp/from-env.sock")
    monkeypatch.setenv("I3SOCK", "/tmp/from-i3.sock")
    assert ipc.discover_socket_path() == "/tmp/from-env.sock"


def test_socket_discovery_falls_back_to_sway_binary(monkeypatch):
    monkeypatch.delenv("SWAYSOCK", raising=False)
    monkeypatch.delenv("I3SOCK", raising=False)
    monkeypatch.setattr(
        ipc.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "/tmp/from-binary.sock\n", ""),
    )
    assert ipc.discover_socket_path() == "/tmp/from-binary.sock"


def test_socket_discovery_uses_i3sock_after_binary_failure(monkeypatch):
    monkeypatch.delenv("SWAYSOCK", raising=False)
    monkeypatch.setenv("I3SOCK", "/tmp/from-i3.sock")
    monkeypatch.setattr(
        ipc.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "no display"),
    )
    assert ipc.discover_socket_path() == "/tmp/from-i3.sock"


def test_socket_discovery_reports_unavailable(monkeypatch):
    for variable in ("SWAYSOCK", "I3SOCK"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(
        ipc.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "failed"),
    )
    with pytest.raises(ipc.SwayUnavailable):
        ipc.discover_socket_path()


def test_socket_discovery_survives_subprocess_timeout(monkeypatch):
    monkeypatch.delenv("SWAYSOCK", raising=False)
    monkeypatch.delenv("I3SOCK", raising=False)

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="sway", timeout=1)

    monkeypatch.setattr(ipc.subprocess, "run", boom)
    with pytest.raises(ipc.SwayUnavailable):
        ipc.discover_socket_path()


def test_socket_discovery_never_globs(monkeypatch, tmp_path):
    """A stray socket in a plausible directory must not be picked up."""
    stray = tmp_path / "sway-ipc.1000.4242.sock"
    stray.write_text("", encoding="utf-8")
    monkeypatch.delenv("SWAYSOCK", raising=False)
    monkeypatch.delenv("I3SOCK", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(
        ipc.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "failed"),
    )
    with pytest.raises(ipc.SwayUnavailable):
        ipc.discover_socket_path()


def test_assert_sway_19_accepts_19_and_rejects_others():
    ipc.assert_sway_19({"major": 1, "minor": 9, "human_readable": "1.9"})
    with pytest.raises(SwayPluginError) as excinfo:
        ipc.assert_sway_19({"major": 1, "minor": 10, "human_readable": "1.10"})
    assert excinfo.value.code == "unsupported_sway_version"
    with pytest.raises(ipc.SwayProtocolError):
        ipc.assert_sway_19({"human_readable": "1.9"})
