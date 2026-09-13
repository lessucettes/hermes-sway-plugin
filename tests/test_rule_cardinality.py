from __future__ import annotations

import pytest

from hermes_sway_plugin.persistent import CardinalityError, audit_cardinality


def test_cardinality_audit_reports_matches_and_rejects_ambiguous_one():
    windows = [{"app_id": "org.example.App"}, {"app_id": "org.example.App"}, {"app_id": "other"}]
    audit = audit_cardinality({"app_id": {"value": "org.example.App"}}, "one", windows)
    assert audit.match_count == 2
    assert audit.verified is False
    assert audit.matched_indices == (0, 1)
    with pytest.raises(CardinalityError, match="expected one"):
        audit_cardinality({"app_id": {"value": "org.example.App"}}, "one", windows, require_verified=True)


def test_cardinality_many_requires_at_least_one_current_match():
    audit = audit_cardinality({"app_id": {"value": "none"}}, "many", [{"app_id": "other"}])
    assert audit.verified is False
