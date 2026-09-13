"""Verified pure Sway layout primitives without a live compositor."""

from __future__ import annotations

import copy

import pytest

from hermes_sway_plugin import ipc
from hermes_sway_plugin.errors import SwayPluginError
from hermes_sway_plugin.runtime import RuntimeService

from .helpers import RuntimeClient, load_fixture, without_node_tree


WARNING = "Sway may automatically split or flatten containers, changing ancestry; inspect the resulting layout"


def _updated_layout_tree(raw_tree, con_id, layout):
    tree = copy.deepcopy(raw_tree)

    def visit(node):
        if node.get("id") == con_id:
            node["layout"] = layout
            return True
        return any(visit(child) for child in node.get("nodes", []) + node.get("floating_nodes", []))

    assert visit(tree)
    return tree


def test_set_parent_layout_resolves_once_runs_a_typed_command_and_checks_the_fresh_parent():
    before = load_fixture("tree_mixed.json")
    after = _updated_layout_tree(before, 121, "stacking")
    client = RuntimeClient([before, after])

    result = RuntimeService(client).layout("set_parent_layout", {"con_id": 103}, layout="stacking")

    assert result == {
        "action": "set_parent_layout",
        "con_id": 103,
        "parent_con_id": 121,
        "layout": "stacking",
        "warnings": [WARNING],
    }
    assert client.commands == ["[con_id=121] layout stacking"]
    assert client.requests == [ipc.GET_VERSION, ipc.GET_TREE, ipc.GET_TREE]


@pytest.mark.parametrize("layout", [None, "grid", True, []])
def test_set_parent_layout_rejects_invalid_layout_without_a_command(layout):
    client = RuntimeClient([load_fixture("tree_mixed.json")])

    with pytest.raises(SwayPluginError) as excinfo:
        RuntimeService(client).layout("set_parent_layout", {"con_id": 103}, layout=layout)

    assert excinfo.value.code == "invalid_argument"
    assert client.commands == []


def test_set_parent_layout_rejects_a_target_without_a_parent():
    client = RuntimeClient([load_fixture("tree_mixed.json")])

    with pytest.raises(SwayPluginError) as excinfo:
        RuntimeService(client).layout("set_parent_layout", {"con_id": 1}, layout="tabbed")

    assert excinfo.value.code == "precondition_failed"
    assert client.commands == []


def test_set_parent_layout_requires_the_target_to_survive_post_verification():
    before = load_fixture("tree_mixed.json")
    client = RuntimeClient([before, without_node_tree(before, 103)])

    with pytest.raises(SwayPluginError) as excinfo:
        RuntimeService(client).layout("set_parent_layout", {"con_id": 103}, layout="tabbed")

    assert excinfo.value.code == "postcondition_failed"


def test_split_at_uses_only_horizontal_or_vertical_orientation_and_checks_a_fresh_tree():
    before = load_fixture("tree_mixed.json")
    client = RuntimeClient([before, before])

    result = RuntimeService(client).layout("split_at", {"con_id": 103}, orientation="vertical")

    assert result == {
        "action": "split_at",
        "con_id": 103,
        "orientation": "vertical",
        "warnings": [WARNING],
    }
    assert client.commands == ["[con_id=103] split vertical"]
    assert client.requests == [ipc.GET_VERSION, ipc.GET_TREE, ipc.GET_TREE]


@pytest.mark.parametrize("orientation", [None, "none", "diagonal", True, []])
def test_split_at_rejects_invalid_orientation_without_a_command(orientation):
    client = RuntimeClient([load_fixture("tree_mixed.json")])

    with pytest.raises(SwayPluginError) as excinfo:
        RuntimeService(client).layout("split_at", {"con_id": 103}, orientation=orientation)

    assert excinfo.value.code == "invalid_argument"
    assert client.commands == []


def test_layout_propagates_typed_command_rejection():
    before = load_fixture("tree_mixed.json")
    client = RuntimeClient([before], command_replies=[[{"success": False, "error": "bad layout"}]])

    with pytest.raises(SwayPluginError) as excinfo:
        RuntimeService(client).layout("split_at", {"con_id": 103}, orientation="horizontal")

    assert excinfo.value.code == "command_rejected"
