"""Verified scratchpad, sticky, mark, and close window mutations."""

from __future__ import annotations

import pytest

from hermes_sway_plugin.errors import SwayPluginError
from hermes_sway_plugin.runtime import RuntimeService

from .helpers import RuntimeClient, load_fixture, moved_window_tree, updated_node_tree, without_node_tree


def test_scratchpad_moves_and_shows_only_when_the_current_state_allows_it():
    before = load_fixture("tree_mixed.json")
    to_scratch = moved_window_tree(before, 101, 2147483646)
    client = RuntimeClient([before, to_scratch])
    RuntimeService(client).window({"con_id": 101}, "move_to_scratchpad")
    assert client.commands == ["[con_id=101] move scratchpad"]

    shown = moved_window_tree(to_scratch, 101, 95)
    client = RuntimeClient([to_scratch, shown])
    RuntimeService(client).window({"con_id": 101}, "show_from_scratchpad")
    assert client.commands == ["[con_id=101] scratchpad show"]


def test_sticky_and_mark_mutations_verify_their_postconditions():
    before = load_fixture("tree_mixed.json")
    sticky = updated_node_tree(before, 108, sticky=True)
    client = RuntimeClient([before, sticky])
    RuntimeService(client).window({"con_id": 108}, "set_sticky", enabled=True)
    assert client.commands == ["[con_id=108] sticky enable"]

    marked = updated_node_tree(before, 101, marks=["chat", "review"])
    client = RuntimeClient([before, marked])
    RuntimeService(client).window({"con_id": 101}, "mark", mark="review")
    assert client.commands == ['[con_id=101] mark --add "review"']


def test_close_requires_explicit_confirmation_and_verifies_removal():
    before = load_fixture("tree_mixed.json")
    with pytest.raises(SwayPluginError) as excinfo:
        RuntimeService(RuntimeClient([before])).window({"con_id": 101}, "close")
    assert excinfo.value.code == "precondition_failed"

    client = RuntimeClient([before, without_node_tree(before, 101)])
    RuntimeService(client).window({"con_id": 101}, "close", confirm_close=True)
    assert client.commands == ["[con_id=101] kill"]
