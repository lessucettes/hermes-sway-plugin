"""Verified geometry-changing runtime window operations."""

from __future__ import annotations

import pytest

from hermes_sway_plugin.errors import SwayPluginError
from hermes_sway_plugin.runtime import RuntimeService

from .helpers import RuntimeClient, load_fixture, moved_window_tree, updated_node_tree


def test_set_fullscreen_verifies_requested_state():
    before = load_fixture("tree_mixed.json")
    after = updated_node_tree(before, 103, fullscreen_mode=1)
    client = RuntimeClient([before, after])

    result = RuntimeService(client).window({"con_id": 103}, "set_fullscreen", enabled=True)

    assert result == {"con_id": 103, "action": "set_fullscreen", "warnings": []}
    assert client.commands == ["[con_id=103] fullscreen enable"]


def test_set_floating_verifies_requested_state():
    before = load_fixture("tree_mixed.json")
    after = moved_window_tree(before, 108, 95)
    client = RuntimeClient([before, after])

    RuntimeService(client).window({"con_id": 108}, "set_floating", enabled=False)

    assert client.commands == ["[con_id=108] floating disable"]


def test_resize_requires_a_floating_non_fullscreen_window_and_checks_dimensions():
    tiled = RuntimeClient([load_fixture("tree_mixed.json")])
    with pytest.raises(SwayPluginError, match="floating") as excinfo:
        RuntimeService(tiled).window({"con_id": 103}, "resize", width=700, height=500, unit="px")
    assert excinfo.value.code == "precondition_failed"
    assert tiled.commands == []

    before = load_fixture("tree_mixed.json")
    after = updated_node_tree(before, 108, rect={"x": 20, "y": 30, "width": 700, "height": 500})
    client = RuntimeClient([before, after])
    RuntimeService(client).window({"con_id": 108}, "resize", width=700, height=500, unit="px")

    assert client.commands == ["[con_id=108] resize set 700 px 500 px"]


def test_resize_reports_sways_observed_size_instead_of_failing_on_clamping_or_ppt():
    before = load_fixture("tree_mixed.json")
    after = updated_node_tree(before, 108, rect={"x": 20, "y": 30, "width": 960, "height": 540})
    client = RuntimeClient([before, after])

    result = RuntimeService(client).window(
        {"con_id": 108}, "resize", width=50, height=50, unit="ppt"
    )

    assert client.commands == ["[con_id=108] resize set 50 ppt 50 ppt"]
    assert result["requested"] == {"width": 50, "height": 50, "unit": "ppt"}
    assert result["observed"]["rect"]["width"] == 960
    assert result["observed"]["rect"]["height"] == 540


def test_relative_position_verifies_against_the_focused_workspace_origin():
    before = updated_node_tree(
        load_fixture("tree_mixed.json"),
        93,
        rect={"x": 2000, "y": 100, "width": 1920, "height": 1080},
    )
    after = updated_node_tree(before, 108, rect={"x": 2050, "y": 160, "width": 400, "height": 300})
    client = RuntimeClient([before, after])

    result = RuntimeService(client).window(
        {"con_id": 108}, "position", position={"mode": "coordinates", "x": 50, "y": 60}
    )

    assert client.commands == ["[con_id=108] move position 50 px 60 px"]
    assert result["observed"]["rect"]["x"] == 2050
    assert result["observed"]["rect"]["y"] == 160


def test_absolute_position_emits_absolute_and_verifies_global_coordinates():
    before = load_fixture("tree_mixed.json")
    after = updated_node_tree(before, 108, rect={"x": 2050, "y": 160, "width": 400, "height": 300})
    client = RuntimeClient([before, after])

    RuntimeService(client).window(
        {"con_id": 108},
        "position",
        position={"mode": "coordinates", "x": 2050, "y": 160, "absolute": True},
    )

    assert client.commands == ["[con_id=108] move absolute position 2050 px 160 px"]


def test_position_center_keeps_floating_precondition_and_reports_placement_warning():
    before = load_fixture("tree_mixed.json")
    client = RuntimeClient([before, before])

    result = RuntimeService(client).window({"con_id": 108}, "position", position={"mode": "center"})

    assert result["warnings"] == ["centering is compositor-dependent; inspect the resulting geometry"]
    assert client.commands == ["[con_id=108] move position center"]
