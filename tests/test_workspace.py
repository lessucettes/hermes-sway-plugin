"""Verified runtime workspace mutations."""

from __future__ import annotations

import pytest

from hermes_sway_plugin.errors import SwayPluginError
from hermes_sway_plugin.runtime import RuntimeService

from .helpers import RuntimeClient, focused_workspace_tree, load_fixture, moved_node_tree, updated_node_tree


def test_workspace_focus_or_create_verifies_focused_workspace():
    before = load_fixture("tree_mixed.json")
    after = focused_workspace_tree(before, 95)
    client = RuntimeClient([before, after])

    result = RuntimeService(client).workspace("focus_or_create", "2")

    assert result == {"workspace": "2", "action": "focus_or_create", "warnings": []}
    assert client.commands == ['workspace --no-auto-back-and-forth "2"']


@pytest.mark.parametrize(
    "workspace",
    ["next", "PREV", "next_on_output", "PREV_ON_OUTPUT", "current", "BACK_AND_FORTH", "number"],
)
def test_workspace_focus_or_create_rejects_reserved_selectors_without_a_command(workspace):
    client = RuntimeClient([])

    with pytest.raises(SwayPluginError) as excinfo:
        RuntimeService(client).workspace("focus_or_create", workspace)

    assert excinfo.value.code == "invalid_argument"
    assert client.requests == []
    assert client.commands == []


@pytest.mark.parametrize(
    ("action", "arguments"),
    [
        ("focus_or_create", {}),
        ("rename", {"new_name": "release"}),
        ("move_to_output", {"output": "DP-2"}),
    ],
)
def test_workspace_mutations_reject_a_case_insensitive_source_name_collision(action, arguments):
    before = updated_node_tree(load_fixture("tree_mixed.json"), 93, name="Dev")
    client = RuntimeClient([before])

    with pytest.raises(SwayPluginError) as excinfo:
        RuntimeService(client).workspace(action, "dEV", **arguments)

    assert excinfo.value.code == "precondition_failed"
    assert client.commands == []


def test_workspace_rename_verifies_exact_new_name():
    before = load_fixture("tree_mixed.json")
    after = updated_node_tree(before, 95, name="dev")
    client = RuntimeClient([before, after])

    result = RuntimeService(client).workspace("rename", "2", new_name="dev")

    assert result == {"workspace": "dev", "action": "rename", "warnings": []}
    assert client.commands == ['rename workspace "2" to "dev"']


def test_workspace_rename_rejects_a_reserved_new_name_without_a_command():
    client = RuntimeClient([])

    with pytest.raises(SwayPluginError) as excinfo:
        RuntimeService(client).workspace("rename", "2", new_name="NeXt")

    assert excinfo.value.code == "invalid_argument"
    assert client.requests == []
    assert client.commands == []


@pytest.mark.parametrize(
    ("action", "arguments"),
    [("rename", {"new_name": "dev"}), ("move_to_output", {"output": "DP-2"})],
)
def test_workspace_mutations_reject_a_reserved_source_name_without_a_command(action, arguments):
    client = RuntimeClient([])

    with pytest.raises(SwayPluginError) as excinfo:
        RuntimeService(client).workspace(action, "BaCk_AnD_FoRtH", **arguments)

    assert excinfo.value.code == "invalid_argument"
    assert client.requests == []
    assert client.commands == []


def test_workspace_rename_rejects_a_case_insensitive_existing_name_collision():
    before = updated_node_tree(load_fixture("tree_mixed.json"), 93, name="Dev")
    client = RuntimeClient([before])

    with pytest.raises(SwayPluginError) as excinfo:
        RuntimeService(client).workspace("rename", "2", new_name="dEV")

    assert excinfo.value.code == "precondition_failed"
    assert client.commands == []


def test_workspace_move_to_output_verifies_destination_and_restores_prior_focus():
    before = load_fixture("tree_mixed.json")
    after = moved_node_tree(before, 95, 4)
    client = RuntimeClient([before, after], command_replies=[[{"success": True}], [{"success": True}]])

    result = RuntimeService(client).workspace("move_to_output", "2", output="DP-2", restore_focus=True)

    assert result == {"workspace": "2", "action": "move_to_output", "warnings": []}
    assert client.commands == [
        'workspace --no-auto-back-and-forth "2"; move workspace to output "DP-2"',
        'workspace --no-auto-back-and-forth "1"',
    ]
