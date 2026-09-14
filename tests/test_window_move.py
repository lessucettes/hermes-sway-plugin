"""Runtime window focus and move operations."""

from __future__ import annotations

import pytest

from hermes_sway_plugin import ipc
from hermes_sway_plugin.errors import SwayPluginError
from hermes_sway_plugin.runtime import RuntimeService

from .helpers import RuntimeClient, focused_tree, load_fixture, moved_window_tree, updated_node_tree


def test_focus_resolves_one_fresh_target_executes_typed_command_and_verifies_post_tree():
    before = load_fixture("tree_mixed.json")
    after = focused_tree(before, 103)
    client = RuntimeClient([before, after])

    result = RuntimeService(client).window({"con_id": 103}, "focus")

    assert result == {"con_id": 103, "action": "focus", "warnings": []}
    assert client.commands == ["[con_id=103] focus"]
    assert client.requests == [ipc.GET_VERSION, ipc.GET_TREE, ipc.GET_TREE]


def test_move_to_workspace_uses_exact_name_and_verifies_the_destination():
    before = load_fixture("tree_mixed.json")
    after = moved_window_tree(before, 103, 93)
    client = RuntimeClient([before, after])

    result = RuntimeService(client).window({"con_id": 103}, "move_to_workspace", workspace="1")

    assert result == {"con_id": 103, "action": "move_to_workspace", "warnings": []}
    assert client.commands == ['[con_id=103] move --no-auto-back-and-forth container to workspace "1"']


def test_move_to_workspace_rejects_a_reserved_selector_without_a_command():
    client = RuntimeClient([])

    with pytest.raises(SwayPluginError) as excinfo:
        RuntimeService(client).window({"con_id": 103}, "move_to_workspace", workspace="CuRrEnT")

    assert excinfo.value.code == "invalid_argument"
    assert client.requests == []
    assert client.commands == []


def test_move_to_workspace_rejects_a_case_insensitive_existing_name_collision():
    before = updated_node_tree(load_fixture("tree_mixed.json"), 93, name="Dev")
    client = RuntimeClient([before])

    with pytest.raises(SwayPluginError) as excinfo:
        RuntimeService(client).window({"con_id": 103}, "move_to_workspace", workspace="dEV")

    assert excinfo.value.code == "precondition_failed"
    assert client.commands == []


def test_move_to_output_uses_exact_name_and_verifies_the_destination():
    before = load_fixture("tree_mixed.json")
    after = moved_window_tree(before, 101, 96)
    client = RuntimeClient([before, after])

    result = RuntimeService(client).window({"con_id": 101}, "move_to_output", output="DP-2")

    assert result == {"con_id": 101, "action": "move_to_output", "warnings": []}
    assert client.commands == ['[con_id=101] move container to output "DP-2"']


def test_directional_move_returns_an_explicit_non_determinism_warning():
    before = load_fixture("tree_mixed.json")
    client = RuntimeClient([before, before])

    result = RuntimeService(client).window({"con_id": 103}, "move_direction", direction="left")

    assert result == {
        "con_id": 103,
        "action": "move_direction",
        "warnings": ["directional placement is compositor-dependent; inspect the resulting layout"],
    }
    assert client.commands == ["[con_id=103] move left"]


def test_stale_target_is_rejected_before_any_command_is_sent():
    client = RuntimeClient([load_fixture("tree_mixed.json")])

    with pytest.raises(SwayPluginError) as excinfo:
        RuntimeService(client).window({"con_id": 999_999}, "focus")

    assert excinfo.value.code == "target_not_found"
    assert client.commands == []


def test_failed_move_postcondition_is_reported_from_the_fresh_tree():
    unchanged = load_fixture("tree_mixed.json")
    client = RuntimeClient([unchanged, unchanged])
    with pytest.raises(SwayPluginError) as excinfo:
        RuntimeService(client).window({"con_id": 103}, "move_to_workspace", workspace="1")

    assert excinfo.value.code == "postcondition_failed"
