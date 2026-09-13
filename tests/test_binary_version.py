"""`sway --version` parsing must report the real major/minor pair.

Regression: the parser collected only the leading integer component of each
whitespace token, so the real `sway version 1.9` output was reported as
``major=1, minor=0``.  That made the persistent tools' availability gate fail and
hid ``sway_rule`` / ``sway_startup`` from every session.
"""

from __future__ import annotations

import subprocess

import pytest

from hermes_sway_plugin import ipc, registration
from hermes_sway_plugin.errors import SwayPluginError


class Completed:
    def __init__(self, stdout: str, stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _fake_run(monkeypatch, **kwargs):
    def run(argv, **options):
        assert argv == ["sway", "--version"]
        return Completed(**kwargs)

    monkeypatch.setattr(subprocess, "run", run)


def test_binary_version_reports_the_real_major_and_minor(monkeypatch):
    _fake_run(monkeypatch, stdout="sway version 1.9\n")

    version = ipc.sway_binary_version()

    assert (version["major"], version["minor"]) == (1, 9)
    assert version["human_readable"] == "1.9"
    assert ipc.assert_sway_19(version) == version


def test_binary_version_handles_a_multi_digit_minor_and_a_release_candidate(monkeypatch):
    _fake_run(monkeypatch, stdout="sway version 1.10-rc2\n")

    version = ipc.sway_binary_version()

    assert (version["major"], version["minor"]) == (1, 10)
    # Parsing must not mask an unsupported release: 1.10 has to fail closed.
    with pytest.raises(SwayPluginError) as excinfo:
        ipc.assert_sway_19(version)
    assert excinfo.value.code == "unsupported_sway_version"


def test_binary_version_rejects_unparseable_output(monkeypatch):
    _fake_run(monkeypatch, stdout="not a version\n")

    with pytest.raises(ipc.SwayUnavailable):
        ipc.sway_binary_version()


def test_persistent_availability_gate_accepts_a_local_sway_19(monkeypatch):
    monkeypatch.setattr(ipc, "sway_binary_version", lambda *a, **k: {"major": 1, "minor": 9, "human_readable": "1.9"})

    assert registration._persistent_available() is True


def test_persistent_availability_gate_rejects_a_different_minor(monkeypatch):
    monkeypatch.setattr(ipc, "sway_binary_version", lambda *a, **k: {"major": 1, "minor": 10, "human_readable": "1.10"})

    assert registration._persistent_available() is False
