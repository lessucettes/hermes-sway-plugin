"""The live smoke script must stay strictly read-only."""

from __future__ import annotations

import os
import subprocess
import sys

from hermes_sway_plugin import ipc

from .fakes import FakeSway, version_payload
from .helpers import ROOT, load_fixture

SCRIPT = ROOT / "scripts" / "live_smoke.py"


def test_live_smoke_script_reads_only_and_never_sends_a_command(tmp_path):
    fake = FakeSway(
        str(tmp_path / "sway-ipc.sock"),
        replies={
            ipc.GET_VERSION: version_payload(),
            ipc.GET_TREE: load_fixture("tree_mixed.json"),
            ipc.GET_WORKSPACES: load_fixture("workspaces.json"),
            ipc.GET_OUTPUTS: load_fixture("outputs.json"),
        },
    )
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "SWAYSOCK": fake.socket_path},
        )
    finally:
        fake.close()

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Sway 1.9; outputs=2; workspaces=3; windows=7"
    assert ipc.RUN_COMMAND not in {message_type for message_type, _ in fake.requests}
    assert {message_type for message_type, _ in fake.requests} <= {
        ipc.GET_VERSION,
        ipc.GET_TREE,
        ipc.GET_WORKSPACES,
        ipc.GET_OUTPUTS,
    }
    assert all(payload == "" for message_type, payload in fake.requests)


def test_live_smoke_script_fails_closed_when_sway_is_not_19(tmp_path):
    fake = FakeSway(str(tmp_path / "sway-ipc.sock"), replies={ipc.GET_VERSION: version_payload(minor=10)})
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "SWAYSOCK": fake.socket_path},
        )
    finally:
        fake.close()

    assert result.returncode != 0
    assert "1.9" in result.stderr
