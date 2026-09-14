"""End-to-end behavior tests for the compact read-only inspection tool."""

from __future__ import annotations

import json

from hermes_sway_plugin import handlers, ipc

from .fakes import FakeSway, version_payload
from .helpers import load_fixture


def _inspect(tmp_path, *, version=None):
    fake = FakeSway(
        str(tmp_path / "sway-ipc.sock"),
        replies={
            ipc.GET_VERSION: version or version_payload(),
            ipc.GET_TREE: load_fixture("tree_mixed.json"),
            ipc.GET_OUTPUTS: load_fixture("outputs.json"),
            ipc.GET_WORKSPACES: load_fixture("workspaces.json"),
            ipc.GET_MARKS: load_fixture("marks.json"),
        },
    )
    bound = handlers.build_handlers(
        lambda _key, default=None: default,
        ipc_factory=lambda **kwargs: ipc.SwayIPC(socket_path=fake.socket_path, **kwargs),
    )["sway_inspect"]
    return fake, bound


def test_inspect_defaults_to_summary_for_minimal_focus_queries(tmp_path):
    fake, inspect = _inspect(tmp_path)
    try:
        payload = json.loads(inspect({}))
    finally:
        fake.close()

    assert payload["ok"] is True
    assert payload["data"]["focused"]["window"]["con_id"] == 101


def test_inspect_summary_reports_version_focus_and_compact_counts(tmp_path):
    fake, inspect = _inspect(tmp_path)
    try:
        payload = json.loads(inspect({"view": "summary"}))
    finally:
        fake.close()

    assert payload["ok"] is True
    assert payload["scope"] == "read_only"
    data = payload["data"]
    assert data["version"]["major"] == 1
    assert data["focused"]["window"]["con_id"] == 101
    assert data["focused"]["workspace"] == "1"
    assert data["focused"]["output"] == "DP-1"
    assert data["counts"] == {"windows": 7, "workspaces": 3, "outputs": 2, "marks": 2}
    assert {request[0] for request in fake.requests} == {
        ipc.GET_VERSION,
        ipc.GET_TREE,
        ipc.GET_OUTPUTS,
        ipc.GET_WORKSPACES,
        ipc.GET_MARKS,
    }


def test_inspect_uses_live_workspace_state_when_the_tree_omits_the_flags(tmp_path):
    """Sway 1.9 omits ``visible``/``focused`` on workspace nodes in GET_TREE.

    These assertions use recorded Sway 1.9 output, where the tree node carries no
    flag at all, so the workspace record and the focused workspace must come from
    GET_WORKSPACES instead of reporting a misleading ``false``/``null``.
    """
    fake = FakeSway(
        str(tmp_path / "sway-ipc.sock"),
        replies={
            ipc.GET_VERSION: version_payload(),
            ipc.GET_TREE: load_fixture("recorded_tree.json"),
            ipc.GET_OUTPUTS: load_fixture("recorded_outputs.json"),
            ipc.GET_WORKSPACES: load_fixture("recorded_workspaces.json"),
            ipc.GET_MARKS: load_fixture("recorded_marks.json"),
        },
    )
    bound = handlers.build_handlers(
        lambda _key, default=None: default,
        ipc_factory=lambda **kwargs: ipc.SwayIPC(socket_path=fake.socket_path, **kwargs),
    )["sway_inspect"]
    try:
        workspaces = json.loads(bound({"view": "workspaces"}))["data"]
        summary = json.loads(bound({"view": "summary"}))["data"]
    finally:
        fake.close()

    records = {record["name"]: record for record in workspaces["items"]}
    assert records["1"]["visible"] is False
    assert records["1"]["focused"] is False
    assert records["2"]["visible"] is True
    assert records["2"]["focused"] is True
    assert summary["focused"]["workspace"] == "2"
    assert summary["focused"]["output"] == "DP-1"


def test_inspect_windows_filters_wayland_xwayland_and_substrings(tmp_path):
    fake, inspect = _inspect(tmp_path)
    try:
        xterm = json.loads(inspect({"view": "windows", "filter": {"class": "XTerm"}}))
        telegram = json.loads(
            inspect({"view": "windows", "filter": {"app_id": "org.telegram.desktop"}})
        )
        title = json.loads(inspect({"view": "windows", "filter": {"title_contains": "kitty"}}))
    finally:
        fake.close()

    assert [window["con_id"] for window in xterm["data"]["items"]] == [105]
    assert xterm["data"]["items"][0]["instance"] == "xterm"
    assert [window["con_id"] for window in telegram["data"]["items"]] == [101]
    assert {window["con_id"] for window in title["data"]["items"]} == {103, 104}


def test_inspect_bounds_results_and_reports_truncation(tmp_path):
    fake, inspect = _inspect(tmp_path)
    try:
        payload = json.loads(inspect({"view": "windows", "max_results": 2}))
    finally:
        fake.close()

    data = payload["data"]
    assert data["matched_count"] == 7
    assert data["returned_count"] == 2
    assert data["truncated"] is True
    assert len(data["items"]) == 2


def test_inspect_omits_geometry_when_requested(tmp_path):
    fake, inspect = _inspect(tmp_path)
    try:
        payload = json.loads(inspect({"view": "windows", "include_geometry": False}))
    finally:
        fake.close()

    assert all("rect" not in window for window in payload["data"]["items"])


def test_inspect_compact_tree_and_marks_have_no_raw_sway_dump(tmp_path):
    fake, inspect = _inspect(tmp_path)
    try:
        tree_result = json.loads(inspect({"view": "tree"}))
        marks_result = json.loads(inspect({"view": "marks"}))
    finally:
        fake.close()

    compact_tree = tree_result["data"]["tree"]
    assert compact_tree["type"] == "root"
    assert "window_properties" not in str(compact_tree)
    assert marks_result["data"]["items"] == ["chat", "image"]


def test_inspect_rejects_non_19_versions(tmp_path):
    fake, inspect = _inspect(tmp_path, version=version_payload(minor=10))
    try:
        payload = json.loads(inspect({"view": "summary"}))
    finally:
        fake.close()

    assert payload["ok"] is False
    assert payload["error"]["code"] == "unsupported_sway_version"
