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


def test_resize_accepts_tiled_windows_and_reports_observed_geometry():
    before = load_fixture("tree_mixed.json")
    after = updated_node_tree(before, 103, rect={"x": 0, "y": 0, "width": 1394, "height": 1080})
    client = RuntimeClient([before, after])
    result = RuntimeService(client).window({"con_id": 103}, "resize", width=55, unit="ppt")

    assert client.commands == ["[con_id=103] resize set width 55 ppt"]
    assert result["requested"] == {"width": 55, "unit": "ppt"}
    assert result["before"]["rect"]["width"] != 1394
    assert result["observed"]["rect"]["width"] == 1394
    assert result["axis_changed"] == {"width": True}
    assert result["warnings"] == [
        "tiled resize changes split proportions; observed geometry may differ from the requested size"
    ]


def test_resize_accepts_one_axis_and_uses_contextual_sway_defaults():
    before = load_fixture("tree_mixed.json")
    floating_after = updated_node_tree(
        before, 108, rect={"x": 20, "y": 30, "width": 400, "height": 500}
    )
    floating = RuntimeClient([before, floating_after])

    floating_result = RuntimeService(floating).window(
        {"con_id": 108}, "resize", height=500
    )

    assert floating.commands == ["[con_id=108] resize set height 500 px"]
    assert floating_result["requested"] == {"height": 500, "unit": "px"}

    tiled_after = updated_node_tree(
        before, 103, rect={"x": 0, "y": 0, "width": 960, "height": 1080}
    )
    tiled = RuntimeClient([before, tiled_after])

    tiled_result = RuntimeService(tiled).window({"con_id": 103}, "resize", width=50)

    assert tiled.commands == ["[con_id=103] resize set width 50 ppt"]
    assert tiled_result["requested"] == {"width": 50, "unit": "ppt"}


def test_resize_requires_at_least_one_positive_axis_and_rejects_fullscreen():
    before = load_fixture("tree_mixed.json")
    client = RuntimeClient([before])
    with pytest.raises(SwayPluginError, match="at least one") as excinfo:
        RuntimeService(client).window({"con_id": 108}, "resize")
    assert excinfo.value.code == "invalid_argument"
    assert client.commands == []

    fullscreen_tree = updated_node_tree(before, 103, fullscreen_mode=1)
    fullscreen = RuntimeClient([fullscreen_tree])
    with pytest.raises(SwayPluginError, match="non-fullscreen") as excinfo:
        RuntimeService(fullscreen).window({"con_id": 103}, "resize", width=50)
    assert excinfo.value.code == "precondition_failed"
    assert fullscreen.commands == []


def test_resize_reports_sways_observed_size_instead_of_failing_on_clamping_or_ppt():
    before = load_fixture("tree_mixed.json")
    after = updated_node_tree(before, 108, rect={"x": 20, "y": 30, "width": 960, "height": 540})
    client = RuntimeClient([before, after])

    result = RuntimeService(client).window(
        {"con_id": 108}, "resize", width=50, height=50, unit="ppt"
    )

    assert client.commands == ["[con_id=108] resize set width 50 ppt height 50 ppt"]
    assert result["requested"] == {"width": 50, "height": 50, "unit": "ppt"}
    assert result["observed"]["rect"]["width"] == 960
    assert result["observed"]["rect"]["height"] == 540


def test_tiled_resize_reports_a_successful_noop_without_claiming_geometry_changed():
    before = load_fixture("tree_mixed.json")
    client = RuntimeClient([before, before])

    result = RuntimeService(client).window({"con_id": 103}, "resize", height=40, unit="ppt")

    assert result["axis_changed"] == {"height": False}
    assert result["before"] == result["observed"]
    assert result["warnings"][-1] == (
        "Sway accepted the resize but no requested axis changed in the fresh geometry"
    )


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
