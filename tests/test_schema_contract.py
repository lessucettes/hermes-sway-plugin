"""Model-facing schema contract stays aligned with handler behavior."""

from __future__ import annotations

from hermes_sway_plugin.schemas import TOOL_SCHEMAS

SCHEMAS = {schema["name"]: schema for schema in TOOL_SCHEMAS}


def test_every_model_visible_top_level_property_explains_its_use():
    for schema in SCHEMAS.values():
        for name, definition in schema["parameters"]["properties"].items():
            assert definition.get("description"), f"{schema['name']}.{name} needs a description"


def test_target_selector_schemas_are_independent_and_describe_their_roles():
    window_target = SCHEMAS["sway_window"]["parameters"]["properties"]["target"]
    layout_properties = SCHEMAS["sway_layout"]["parameters"]["properties"]
    layout_target = layout_properties["target"]
    other_target = layout_properties["other_target"]

    assert window_target["description"] == (
        "Exactly one live window selector; prefer a fresh con_id when known."
    )
    assert layout_target["description"] == "Exactly one container or window selector."
    assert other_target["description"] == "Second exact selector required only by swap."

    selectors = (window_target, layout_target, other_target)
    assert len({id(selector) for selector in selectors}) == 3
    assert len({id(selector["properties"]) for selector in selectors}) == 3
    assert len({id(selector["properties"]["match"]) for selector in selectors}) == 3


def test_schema_defaults_and_enums_match_handlers():
    inspect = SCHEMAS["sway_inspect"]["parameters"]
    assert "view" not in inspect["required"]
    assert inspect["properties"]["view"]["default"] == "summary"

    layout = SCHEMAS["sway_layout"]["parameters"]
    assert layout["properties"]["orientation"]["enum"] == ["horizontal", "vertical"]

    window = SCHEMAS["sway_window"]["parameters"]
    assert "default" not in window["properties"]["unit"]
    assert "one axis" in window["properties"]["width"]["description"]
    assert "one axis" in window["properties"]["height"]["description"]

    rule = SCHEMAS["sway_rule"]["parameters"]
    assert rule["properties"]["intended_cardinality"]["default"] == "many"
    assert "allow_unverified_cardinality" not in rule["properties"]
    assert "allow_external_conflicts" not in rule["properties"]
    assert rule["properties"]["match"]["additionalProperties"] is False
    assert set(rule["properties"]["match"]["properties"]) == {
        "app_id",
        "class",
        "instance",
        "title",
        "window_role",
        "window_type",
        "shell",
        "con_mark",
    }
