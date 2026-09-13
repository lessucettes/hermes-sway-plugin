"""Verified runtime workspace mutations."""

from __future__ import annotations

from hermes_sway_plugin.runtime import RuntimeService

from .helpers import RuntimeClient, focused_workspace_tree, load_fixture, moved_node_tree, updated_node_tree


def test_workspace_focus_or_create_verifies_focused_workspace():
    before = load_fixture("tree_mixed.json")
    after = focused_workspace_tree(before, 95)
    client = RuntimeClient([before, after])

    result = RuntimeService(client).workspace("focus_or_create", "2")

    assert result == {"workspace": "2", "action": "focus_or_create", "warnings": []}
    assert client.commands == ['workspace "2"']


def test_workspace_rename_verifies_exact_new_name():
    before = load_fixture("tree_mixed.json")
    after = updated_node_tree(before, 95, name="dev")
    client = RuntimeClient([before, after])

    result = RuntimeService(client).workspace("rename", "2", new_name="dev")

    assert result == {"workspace": "dev", "action": "rename", "warnings": []}
    assert client.commands == ['rename workspace "2" to "dev"']


def test_workspace_move_to_output_verifies_destination_and_restores_prior_focus():
    before = load_fixture("tree_mixed.json")
    after = moved_node_tree(before, 95, 4)
    client = RuntimeClient([before, after], command_replies=[[{"success": True}], [{"success": True}]])

    result = RuntimeService(client).workspace("move_to_output", "2", output="DP-2", restore_focus=True)

    assert result == {"workspace": "2", "action": "move_to_output", "warnings": []}
    assert client.commands == ['workspace "2"; move workspace to output "DP-2"', 'workspace "1"']
