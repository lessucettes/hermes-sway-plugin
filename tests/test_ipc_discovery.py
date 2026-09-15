"""Tests for socket discovery, version gating, framing, and subscriptions."""

from __future__ import annotations

import socket
import subprocess

import pytest

from hermes_sway_plugin import ipc
from hermes_sway_plugin.errors import SwayPluginError


def test_socket_discovery_prefers_explicit_path(monkeypatch):
    monkeypatch.setenv("SWAYSOCK", "/tmp/from-env.sock")
    monkeypatch.setattr(ipc, "socket_is_live", lambda path: path == "/tmp/explicit.sock")
    assert ipc.discover_socket_path("/tmp/explicit.sock") == "/tmp/explicit.sock"


def test_socket_discovery_uses_swaysock(monkeypatch):
    monkeypatch.setenv("SWAYSOCK", "/tmp/from-env.sock")
    monkeypatch.setenv("I3SOCK", "/tmp/from-i3.sock")
    monkeypatch.setattr(ipc, "socket_is_live", lambda path: path == "/tmp/from-env.sock")
    assert ipc.discover_socket_path() == "/tmp/from-env.sock"


def test_socket_discovery_falls_back_to_sway_binary(monkeypatch):
    for variable in ("SWAYSOCK", "SWAYSOCK_WLR", "I3SOCK"):
        monkeypatch.delenv(variable, raising=False)

    def run(argv, **_kwargs):
        if argv == ["sway", "--get-socketpath"]:
            return subprocess.CompletedProcess(argv, 0, "/tmp/from-binary.sock\n", "")
        return subprocess.CompletedProcess(argv, 1, "", "no user bus")

    monkeypatch.setattr(ipc.subprocess, "run", run)
    monkeypatch.setattr(ipc, "socket_is_live", lambda path: path == "/tmp/from-binary.sock")
    assert ipc.discover_socket_path() == "/tmp/from-binary.sock"


def test_socket_discovery_uses_i3sock_after_binary_failure(monkeypatch):
    monkeypatch.delenv("SWAYSOCK", raising=False)
    monkeypatch.delenv("SWAYSOCK_WLR", raising=False)
    monkeypatch.setenv("I3SOCK", "/tmp/from-i3.sock")
    monkeypatch.setattr(
        ipc.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "no display"),
    )
    monkeypatch.setattr(ipc, "socket_is_live", lambda path: path == "/tmp/from-i3.sock")
    assert ipc.discover_socket_path() == "/tmp/from-i3.sock"


def test_socket_discovery_skips_stale_inherited_socket(monkeypatch):
    monkeypatch.setenv("SWAYSOCK", "/tmp/stale.sock")
    monkeypatch.delenv("SWAYSOCK_WLR", raising=False)
    monkeypatch.delenv("I3SOCK", raising=False)

    def run(argv, **_kwargs):
        if argv == ["sway", "--get-socketpath"]:
            return subprocess.CompletedProcess(argv, 0, "/tmp/current.sock\n", "")
        return subprocess.CompletedProcess(argv, 1, "", "no user bus")

    monkeypatch.setattr(ipc.subprocess, "run", run)
    monkeypatch.setattr(ipc, "socket_is_live", lambda path: path == "/tmp/current.sock")

    assert ipc.discover_socket_path() == "/tmp/current.sock"


def test_socket_discovery_refuses_to_fall_back_from_unreachable_explicit_path(monkeypatch):
    monkeypatch.setenv("SWAYSOCK", "/tmp/current.sock")
    monkeypatch.setattr(ipc, "socket_is_live", lambda _path: False)
    monkeypatch.setattr(
        ipc.subprocess,
        "run",
        lambda *_a, **_k: pytest.fail("explicit paths must not trigger automatic discovery"),
    )

    with pytest.raises(ipc.SwayUnavailable, match="explicit.*unreachable"):
        ipc.discover_socket_path("/tmp/requested.sock")


def test_socket_discovery_uses_optional_systemd_user_environment(monkeypatch):
    for variable in ("SWAYSOCK", "SWAYSOCK_WLR", "I3SOCK"):
        monkeypatch.delenv(variable, raising=False)

    def run(argv, **_kwargs):
        if argv == ["sway", "--get-socketpath"]:
            return subprocess.CompletedProcess(argv, 1, "", "sway socket not detected")
        assert argv == ["systemctl", "--user", "show-environment"]
        return subprocess.CompletedProcess(
            argv,
            0,
            "UNRELATED=value\nSWAYSOCK=/run/user/1000/current.sock\n",
            "",
        )

    monkeypatch.setattr(ipc.subprocess, "run", run)
    monkeypatch.setattr(
        ipc,
        "socket_is_live",
        lambda path: path == "/run/user/1000/current.sock",
    )

    assert ipc.discover_socket_path() == "/run/user/1000/current.sock"


def test_socket_discovery_reports_missing_inherited_environment(monkeypatch):
    for variable in ("SWAYSOCK", "SWAYSOCK_WLR", "I3SOCK"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(
        ipc.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "failed"),
    )
    with pytest.raises(ipc.SwayUnavailable, match="process environment has no"):
        ipc.discover_socket_path()


def test_socket_discovery_reports_stale_automatic_candidates(monkeypatch):
    monkeypatch.setenv("SWAYSOCK", "/tmp/stale.sock")
    monkeypatch.delenv("SWAYSOCK_WLR", raising=False)
    monkeypatch.delenv("I3SOCK", raising=False)
    monkeypatch.setattr(ipc, "socket_is_live", lambda _path: False)
    monkeypatch.setattr(
        ipc.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "failed"),
    )

    with pytest.raises(ipc.SwayUnavailable, match="stale SWAYSOCK"):
        ipc.discover_socket_path()


def test_socket_discovery_survives_subprocess_timeout(monkeypatch):
    for variable in ("SWAYSOCK", "SWAYSOCK_WLR", "I3SOCK"):
        monkeypatch.delenv(variable, raising=False)

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

    monkeypatch.setattr(ipc.subprocess, "run", boom)
    with pytest.raises(ipc.SwayUnavailable):
        ipc.discover_socket_path()


def test_socket_discovery_never_globs(monkeypatch, tmp_path):
    """A stray socket in a plausible directory must not be picked up."""
    stray = tmp_path / "sway-ipc.1000.4242.sock"
    stray.write_text("", encoding="utf-8")
    for variable in ("SWAYSOCK", "SWAYSOCK_WLR", "I3SOCK"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(
        ipc.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "failed"),
    )
    with pytest.raises(ipc.SwayUnavailable):
        ipc.discover_socket_path()


def test_socket_is_live_distinguishes_live_deleted_and_refusing_paths(tmp_path):
    deleted = tmp_path / "deleted.sock"
    refusing_path = tmp_path / "refusing.sock"
    live_path = tmp_path / "live.sock"
    refusing = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    live = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    refusing.bind(str(refusing_path))
    live.bind(str(live_path))
    live.listen(1)
    try:
        assert ipc.socket_is_live(str(live_path), timeout=0.1) is True
        assert ipc.socket_is_live(str(deleted), timeout=0.1) is False
        assert ipc.socket_is_live(str(refusing_path), timeout=0.1) is False
    finally:
        live.close()
        refusing.close()


def test_assert_sway_19_accepts_19_and_rejects_others():
    ipc.assert_sway_19({"major": 1, "minor": 9, "human_readable": "1.9"})
    with pytest.raises(SwayPluginError) as excinfo:
        ipc.assert_sway_19({"major": 1, "minor": 10, "human_readable": "1.10"})
    assert excinfo.value.code == "unsupported_sway_version"
    with pytest.raises(ipc.SwayProtocolError):
        ipc.assert_sway_19({"human_readable": "1.9"})
