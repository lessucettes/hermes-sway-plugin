"""Runtime window focus and move operations."""

from __future__ import annotations

from hermes_sway_plugin import ipc
from hermes_sway_plugin.runtime import RuntimeService

from .helpers import RuntimeClient, focused_tree, load_fixture, moved_window_tree


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
    assert client.commands == ['[con_id=103] move container to workspace "1"']
