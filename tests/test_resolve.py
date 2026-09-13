"""Exactly-one runtime target resolution from one immutable snapshot."""

from __future__ import annotations

import pytest

from hermes_sway_plugin.errors import SwayPluginError
from hermes_sway_plugin.resolve import resolve_target
from hermes_sway_plugin.tree import build_snapshot

from .helpers import load_fixture


@pytest.fixture()
def snapshot():
    return build_snapshot(load_fixture("tree_mixed.json"))


def test_resolves_a_current_con_id(snapshot):
    target = resolve_target(snapshot, {"con_id": 101}, window_only=True)
    assert target.id == 101
    assert target.app_id == "org.telegram.desktop"


def test_resolves_an_exact_mark(snapshot):
    target = resolve_target(snapshot, {"mark": "image"}, window_only=True)
    assert target.id == 106


def test_resolves_conjunctive_exact_identity(snapshot):
    target = resolve_target(
        snapshot,
        {"match": {"app_id": "org.telegram.desktop", "workspace": "1", "floating": False}},
        window_only=True,
    )
    assert target.id == 101


def test_rejects_a_missing_target(snapshot):
    with pytest.raises(SwayPluginError) as excinfo:
        resolve_target(snapshot, {"match": {"app_id": "missing"}}, window_only=True)
    assert excinfo.value.code == "target_not_found"


def test_reports_all_ambiguous_candidates(snapshot):
    with pytest.raises(SwayPluginError) as excinfo:
        resolve_target(snapshot, {"match": {"workspace": "2"}}, window_only=True)
    assert excinfo.value.code == "target_ambiguous"
    assert {candidate["con_id"] for candidate in excinfo.value.details["candidates"]} == {103, 104, 105}


def test_rejects_split_container_for_window_actions_but_allows_layout_target(snapshot):
    with pytest.raises(SwayPluginError) as excinfo:
        resolve_target(snapshot, {"con_id": 120}, window_only=True)
    assert excinfo.value.code == "precondition_failed"

    assert resolve_target(snapshot, {"con_id": 120}, window_only=False).id == 120


def test_rejects_selector_zero_or_multiple_forms(snapshot):
    for target in ({}, {"con_id": 101, "mark": "chat"}, {"match": {}}):
        with pytest.raises(SwayPluginError) as excinfo:
            resolve_target(snapshot, target, window_only=True)
        assert excinfo.value.code == "invalid_argument"
