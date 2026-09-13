"""Tree normalization tests against recorded and synthetic Sway 1.9 payloads."""

from __future__ import annotations

import pytest

from hermes_sway_plugin import tree

from .helpers import load_fixture


@pytest.fixture()
def snapshot() -> tree.Snapshot:
    return tree.build_snapshot(load_fixture("tree_mixed.json"))


def test_wayland_and_xwayland_windows_keep_their_identity(snapshot):
    windows = {window.con_id: window for window in snapshot.windows()}

    telegram = windows[101]
    assert telegram.app_id == "org.telegram.desktop"
    assert telegram.shell == "xdg_shell"
    assert telegram.x11_class is None
    assert telegram.workspace == "1"
    assert telegram.output == "DP-1"

    xterm = windows[105]
    assert xterm.x11_class == "XTerm"
    assert xterm.x11_instance == "xterm"
    assert xterm.window_role == "browser"
    assert xterm.shell == "xwayland"
    assert xterm.app_id is None


def test_split_containers_are_parents_not_windows(snapshot):
    assert 120 in snapshot.nodes
    assert snapshot.nodes[120].window is None
    assert 120 not in {window.con_id for window in snapshot.windows()}
    assert snapshot.nodes[120].layout == "splitv"
    assert snapshot.nodes[101].parent_id == 120
    assert snapshot.windows() and snapshot.nodes[101].child_ids == ()


def test_floating_nodes_are_walked_and_flagged(snapshot):
    floating = [window for window in snapshot.windows() if window.floating]
    assert {window.con_id for window in floating} == {108}
    assert floating[0].output == "DP-1"
    # Sway stores output-level floating containers outside workspace nodes;
    # no declarative workspace association exists, so never guess one.
    assert floating[0].workspace is None
    assert snapshot.nodes[108].type == "con"
    assert snapshot.nodes[108].floating is True
    assert snapshot.nodes[122].floating is True


def test_focus_chain_is_derived_from_the_tree(snapshot):
    assert snapshot.focused_window_id == 101
    assert snapshot.focused_workspace == "1"
    assert snapshot.focused_output == "DP-1"
    assert snapshot.focused_window().con_id == 101


def test_scratchpad_nodes_are_excluded_unless_requested(snapshot):
    assert 107 not in {window.con_id for window in snapshot.windows()}
    scratchpad = [window for window in snapshot.windows(include_scratchpad=True) if window.scratchpad]
    assert {window.con_id for window in scratchpad} == {107}
    assert "__i3_scratch" not in {workspace.name for workspace in snapshot.workspaces()}
    assert "__i3_scratch" in {
        workspace.name for workspace in snapshot.workspaces(include_scratchpad=True)
    }
    assert 2147483647 not in {workspace.num for workspace in snapshot.workspaces()}


def test_ancestor_and_workspace_relationships_are_complete(snapshot):
    assert [node.id for node in snapshot.ancestors(101)] == [1, 3, 93, 120]
    assert snapshot.nodes[101].workspace_number == 1
    assert snapshot.nodes[108].workspace is None
    assert snapshot.nodes[108].output == "DP-1"
    assert snapshot.nodes[107].in_scratchpad is True
    workspaces = {workspace.name: workspace for workspace in snapshot.workspaces()}
    assert workspaces["1"].window_count == 2
    assert workspaces["3"].output == "DP-2"


def test_absent_optional_fields_do_not_break_parsing():
    minimal = {
        "id": 1,
        "type": "root",
        "layout": "splith",
        "nodes": [
            {
                "id": 2,
                "type": "con",
                "nodes": [],
                "floating_nodes": [],
                "rect": {"x": 0, "y": 0, "width": 10, "height": 10},
            }
        ],
        "floating_nodes": [],
    }
    snapshot = tree.build_snapshot(minimal)
    node = snapshot.nodes[2]
    assert node.name is None
    assert node.app_id is None
    assert node.pid is None
    assert node.rect == tree.Rect(0, 0, 10, 10)
    assert node.workspace is None
    assert snapshot.windows() == ()


def test_malformed_tree_fields_are_rejected():
    with pytest.raises(tree.TreeFormatError):
        tree.build_snapshot([])
    with pytest.raises(tree.TreeFormatError):
        tree.build_snapshot({"type": "root", "nodes": []})
    with pytest.raises(tree.TreeFormatError):
        tree.build_snapshot({"id": 1, "type": "root", "nodes": "nope"})
    with pytest.raises(tree.TreeFormatError):
        tree.build_snapshot(
            {"id": 1, "type": "root", "nodes": [{"id": 2, "type": "con", "rect": {"x": 0}}]}
        )


def test_compact_outputs_and_marks_and_workspaces():
    outputs = tree.parse_outputs(load_fixture("outputs.json"))
    assert [output.name for output in outputs] == ["DP-1", "DP-2"]
    dp1 = outputs[0]
    assert dp1.hardware_identifier == "Dell Inc. DELL U2720Q ABC123"
    assert dp1.focused is True
    assert dp1.compact()["current_mode"]["width"] == 1920

    marks = tree.parse_marks(load_fixture("marks.json"))
    assert marks == ("chat", "image")

    workspaces = tree.parse_workspaces(load_fixture("workspaces.json"))
    assert [workspace.name for workspace in workspaces] == ["1", "2", "3"]
    assert workspaces[2].visible is False


def test_recorded_live_tree_normalizes():
    """The recorded real 1.9 tree must normalize without special cases."""
    snapshot = tree.build_snapshot(load_fixture("recorded_tree.json"))
    focused = snapshot.focused_window()
    assert focused is not None
    assert focused.con_id == 94
    assert focused.workspace == "2"
    assert focused.output == "DP-1"
    assert snapshot.focused_workspace == "2"
    assert snapshot.focused_output == "DP-1"
    assert len(snapshot.windows()) == 2
    assert {workspace.name for workspace in snapshot.workspaces()} == {"1", "2"}
    compact = tree.compact_tree(snapshot)
    assert compact["type"] == "root"
    assert compact["children"]


def test_compact_tree_is_not_the_raw_payload(snapshot):
    compact = tree.compact_tree(snapshot)
    assert "window_properties" not in str(compact)
    assert "deco_rect" not in str(compact)
    assert compact["type"] == "root"
    assert len(compact["children"]) == 3
