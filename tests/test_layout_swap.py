"""Verified exact Sway container swaps without a live compositor."""

from __future__ import annotations

import copy

import pytest

from hermes_sway_plugin import ipc
from hermes_sway_plugin.errors import SwayPluginError
from hermes_sway_plugin.runtime import RuntimeService

from .helpers import RuntimeClient, load_fixture, without_node_tree


WARNING = "Sway may automatically split or flatten containers, changing ancestry; inspect the resulting layout"


def _swapped_tree(raw_tree, first_id, second_id):
    """Return a tree where two existing nodes have exchanged exact child slots."""
    tree = copy.deepcopy(raw_tree)
    slots = {}

    def visit(node):
        for key in ("nodes", "floating_nodes"):
            children = node.get(key, [])
            for index, child in enumerate(children):
                if child.get("id") in {first_id, second_id}:
                    slots[child["id"]] = (children, index)
                visit(child)

    visit(tree)
    assert set(slots) == {first_id, second_id}
    first_children, first_index = slots[first_id]
    second_children, second_index = slots[second_id]
    first_children[first_index], second_children[second_index] = (
        second_children[second_index],
        first_children[first_index],
    )
    return tree


def test_swap_resolves_two_current_targets_runs_the_typed_command_and_verifies_exact_cross_parent_slots():
    before = load_fixture("tree_mixed.json")
    after = _swapped_tree(before, 101, 103)
    client = RuntimeClient([before, after])

    result = RuntimeService(client).layout("swap", {"con_id": 101}, other_target={"con_id": 103})

    assert result == {
        "action": "swap",
        "con_id": 101,
        "other_con_id": 103,
        "warnings": [WARNING],
    }
    assert client.commands == ["[con_id=101] swap container with con_id 103"]
    assert client.requests == [ipc.GET_VERSION, ipc.GET_TREE, ipc.GET_TREE]


def test_swap_verifies_an_exact_sibling_position_exchange():
    before = load_fixture("tree_mixed.json")
    after = _swapped_tree(before, 103, 104)
    client = RuntimeClient([before, after])

    RuntimeService(client).layout("swap", {"con_id": 103}, other_target={"con_id": 104})

    assert client.commands == ["[con_id=103] swap container with con_id 104"]


@pytest.mark.parametrize(
    ("target", "other_target"),
    [
        ({"con_id": 103}, {"con_id": 103}),
        ({"con_id": 121}, {"con_id": 103}),
    ],
)
def test_swap_rejects_self_and_ancestor_descendant_targets_before_a_command(target, other_target):
    client = RuntimeClient([load_fixture("tree_mixed.json")])

    with pytest.raises(SwayPluginError) as excinfo:
        RuntimeService(client).layout("swap", target, other_target=other_target)

    assert excinfo.value.code == "precondition_failed"
    assert client.commands == []


def test_swap_requires_the_other_target_to_resolve_exactly_once():
    client = RuntimeClient([load_fixture("tree_mixed.json")])

    with pytest.raises(SwayPluginError) as excinfo:
        RuntimeService(client).layout("swap", {"con_id": 103}, other_target={"match": {"workspace": "2"}})

    assert excinfo.value.code == "target_ambiguous"
    assert client.commands == []


def test_swap_reports_disappearing_targets_from_the_fresh_post_tree():
    before = load_fixture("tree_mixed.json")
    client = RuntimeClient([before, without_node_tree(before, 104)])

    with pytest.raises(SwayPluginError) as excinfo:
        RuntimeService(client).layout("swap", {"con_id": 103}, other_target={"con_id": 104})

    assert excinfo.value.code == "postcondition_failed"


def test_swap_rejects_a_success_reply_when_the_containers_did_not_exchange_exact_slots():
    before = load_fixture("tree_mixed.json")
    client = RuntimeClient([before, before])

    with pytest.raises(SwayPluginError) as excinfo:
        RuntimeService(client).layout("swap", {"con_id": 103}, other_target={"con_id": 104})

    assert excinfo.value.code == "postcondition_failed"


def test_swap_propagates_a_typed_sway_command_rejection():
    before = load_fixture("tree_mixed.json")
    client = RuntimeClient([before], command_replies=[[{"success": False, "error": "not swappable"}]])

    with pytest.raises(SwayPluginError) as excinfo:
        RuntimeService(client).layout("swap", {"con_id": 103}, other_target={"con_id": 104})

    assert excinfo.value.code == "command_rejected"
