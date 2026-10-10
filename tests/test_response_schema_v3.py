"""JSON Schema metadata must never remove real property/definition names."""
from copy import deepcopy

from cadstudio.native.cloud_ai import response_schema


def test_required_properties_named_title_default_and_type_survive():
    source = dict(type="object", title="Model metadata", properties={
        "title": dict(type="string", title="Field metadata"),
        "default": dict(type="number", default=1),
        "type": dict(type="string"),
        "minLength": dict(type="integer")}, required=["title", "default", "type", "minLength"])
    before = deepcopy(source)
    converted = response_schema(source)
    assert source == before and "title" not in converted
    assert set(converted["properties"]) == set(source["properties"])
    assert converted["properties"]["title"] == {"type": "string"}
    assert converted["properties"]["default"] == {"type": "number"}
    assert converted["additionalProperties"] is False


def test_optional_title_remains_present_and_nullable_without_invented_values():
    converted = response_schema(dict(type="object", properties={"title": dict(type="string", default="")}, required=[]))
    assert converted["required"] == ["title"]
    assert converted["properties"]["title"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}


def test_arbitrary_definition_and_property_map_names_are_preserved():
    source = {"$defs": {"title": {"type": "object", "properties": {"default": {"type": "string"}}, "required": ["default"]},
                       "default": {"type": "string", "title": "Metadata"}},
              "definitions": {"title": {"type": "number"}},
              "patternProperties": {"title": {"type": "string"}},
              "dependentSchemas": {"default": {"type": "string"}},
              "type": "object", "properties": {"title": {"$ref": "#/$defs/title"}}, "required": ["title"]}
    converted = response_schema(source)
    assert set(converted["$defs"]) == {"title", "default"}
    assert converted["$defs"]["title"]["properties"]["default"] == {"type": "string"}
    assert converted["$defs"]["default"] == {"type": "string"}
    assert "title" in converted["definitions"] and "title" in converted["patternProperties"]
    assert "default" in converted["dependentSchemas"]
    assert converted["properties"]["title"]["$ref"] == "#/$defs/title"


def test_empty_property_maps_stay_maps_and_dimension_encoding_is_unchanged():
    assert response_schema(dict(type="object", properties={}, required=[]))["properties"] == {}
    encoded = response_schema(dict(type="object", additionalProperties={}))
    assert encoded["type"] == "array" and encoded["items"]["required"] == ["key", "value_json"]
