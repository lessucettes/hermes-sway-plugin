"""Declarative window and workspace-output rules render to Sway 1.9 syntax."""

from __future__ import annotations

import pytest

from hermes_sway_plugin.persistent import (
    RuleRenderError,
    render_rule,
    render_window_rule,
    render_workspace_output_rule,
)


def test_window_rule_uses_assignment_for_placement_and_for_window_only_for_effects():
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
        'assign [app_id="^org\\\\.example\\\\.App$"] workspace number 2\n'
        'for_window [app_id="^org\\\\.example\\\\.App$"] floating enable, '
        'resize set width 800 px, resize set height 600 px, move position center, '
        'border pixel 2, opacity 0.75'
    )
    assert render_rule({"kind": "window", **rule}) == render_window_rule(rule)


def test_window_rule_keeps_a_named_workspace_destination_quoted():
    rule = {
        "match": {"class": {"value": "TelegramDesktop"}},
        "destination": {"workspace": "chat"},
        "effects": {"floating": True},
    }

    assert render_window_rule(rule) == (
        'assign [class="^TelegramDesktop$"] workspace "chat"\n'
        'for_window [class="^TelegramDesktop$"] floating enable'
    )


def test_window_rule_uses_assignment_for_output_destination():
    rule = {
        "match": {"app_id": {"value": "org.example.App"}},
        "destination": {"output": "DP-2"},
        "effects": {"center": True, "floating": True},
    }

    assert render_window_rule(rule) == (
        'assign [app_id="^org\\\\.example\\\\.App$"] output "DP-2"\n'
        'for_window [app_id="^org\\\\.example\\\\.App$"] floating enable, move position center'
    )


def test_no_focus_is_a_top_level_criteria_command():
    rule = {
        "match": {"app_id": {"value": "org.example.App"}},
        "effects": {"no_focus": True, "opacity": 0.9},
    }

    assert render_window_rule(rule) == (
        'no_focus [app_id="^org\\\\.example\\\\.App$"]\n'
        'for_window [app_id="^org\\\\.example\\\\.App$"] opacity 0.9'
    )


def test_no_focus_can_be_the_only_effect():
    assert render_window_rule(
        {"match": {"app_id": {"value": "org.example.App"}}, "effects": {"no_focus": True}}
    ) == 'no_focus [app_id="^org\\\\.example\\\\.App$"]'


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
