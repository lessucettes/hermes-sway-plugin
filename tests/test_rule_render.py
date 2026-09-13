"""Declarative window and workspace-output rules render to bounded Sway syntax."""

from __future__ import annotations

import pytest

from hermes_sway_plugin.persistent import RuleRenderError, render_rule, render_window_rule, render_workspace_output_rule


def test_window_rule_renders_destination_and_effects_in_stable_order():
    rule = {
        "match": {"app_id": {"value": "org.example.App"}},
        "destination": {"workspace": "2"},
        "effects": {
            "center": True,
            "floating": True,
            "width_px": 800,
            "height_px": 600,
            "border": {"style": "pixel", "width": 2},
            "opacity": 0.75,
        },
    }

    assert render_window_rule(rule) == (
        'for_window [app_id="^org\\\\.example\\\\.App$"] move container to workspace "2", '
        'floating enable, resize set width 800 px, resize set height 600 px, '
        'move position center, border pixel 2, opacity 0.75'
    )
    assert render_rule({"kind": "window", **rule}) == render_window_rule(rule)


def test_window_rule_requires_match_and_an_effect_or_destination():
    with pytest.raises(RuleRenderError, match="match"):
        render_window_rule({"destination": {"workspace": "2"}})
    with pytest.raises(RuleRenderError, match="effect or destination"):
        render_window_rule({"match": {"app_id": {"value": "org.example.App"}}})


def test_workspace_output_rule_requires_workspace_and_unique_outputs():
    rule = {"workspace": "dev", "outputs": ["DP-1", "HDMI-A-1"]}
    assert render_workspace_output_rule(rule) == 'workspace "dev" output "DP-1" "HDMI-A-1"'
    assert render_rule({"kind": "workspace_output", **rule}) == render_workspace_output_rule(rule)

    with pytest.raises(RuleRenderError, match="unique"):
        render_workspace_output_rule({"workspace": "dev", "outputs": ["DP-1", "DP-1"]})
