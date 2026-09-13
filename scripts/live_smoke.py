#!/usr/bin/env python3
"""Read-only Sway 1.9 smoke check.

Sends only ``GET_VERSION``, ``GET_TREE``, ``GET_WORKSPACES``, and
``GET_OUTPUTS``.  It never sends ``RUN_COMMAND`` or any mutating request, so it
is safe to run against a live session.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hermes_sway_plugin import ipc, tree  # noqa: E402
from hermes_sway_plugin.errors import SwayPluginError  # noqa: E402


def main() -> int:
    try:
        client = ipc.SwayIPC(timeout=3.0)
    except ipc.SwayUnavailable as exc:
        print(f"sway-unavailable: {exc}", file=sys.stderr)
        return 2
    try:
        version = ipc.assert_sway_19(client.request(ipc.GET_VERSION))
        snapshot = tree.build_snapshot(client.request(ipc.GET_TREE))
        workspaces = snapshot.workspaces()
        outputs = tree.parse_outputs(client.request(ipc.GET_OUTPUTS))
    except (
        ipc.SwayTimeout,
        ipc.SwayProtocolError,
        ipc.SwayPayloadTooLarge,
        tree.TreeFormatError,
        SwayPluginError,
    ) as exc:
        print(f"sway-ipc-error: {exc}", file=sys.stderr)
        return 3

    print(
        f"Sway {version.get('major')}.{version.get('minor')}; "
        f"outputs={len(outputs)}; workspaces={len(workspaces)}; windows={len(snapshot.windows())}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
