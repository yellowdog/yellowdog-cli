"""
Unit tests for yellowdog_cli.utils.validate_properties
"""

import pytest

from yellowdog_cli.utils.validate_properties import validate_properties


class TestValidProperties:
    """
    Valid property dicts should pass without raising.
    """

    def test_single_valid_key(self):
        validate_properties({"name": "test"}, "ctx")

    def test_multiple_valid_keys(self):
        validate_properties(
            {"name": "job", "namespace": "default", "priority": 1.0}, "ctx"
        )

    def test_empty_dict_is_valid(self):
        validate_properties({}, "ctx")

    def test_valid_nested_in_task_groups(self):
        validate_properties(
            {"taskGroups": [{"taskType": "bash", "taskCount": 4}]}, "ctx"
        )

    def test_valid_nested_in_tasks(self):
        validate_properties(
            {"tasks": [{"taskType": "bash", "arguments": ["--flag"]}]}, "ctx"
        )

    def test_list_of_dicts_with_valid_keys(self):
        validate_properties(
            {"taskGroups": [{"name": "a"}, {"name": "b", "namespace": "ns"}]}, "ctx"
        )


class TestInvalidProperties:
    """
    Unknown keys should raise an exception naming the bad key(s).
    """

    def test_invalid_top_level_key_raises(self):
        with pytest.raises(Exception, match="Invalid properties"):
            validate_properties({"unknownKey999": "value"}, "ctx")

    def test_invalid_key_named_in_error(self):
        with pytest.raises(Exception, match="unknownKey999"):
            validate_properties({"unknownKey999": "value"}, "ctx")

    def test_context_not_required_in_message(self):
        # Context appears in the message when properties are invalid
        with pytest.raises(Exception, match="myContext"):
            validate_properties({"badKey": 1}, "myContext")

    def test_multiple_invalid_keys_raises(self):
        with pytest.raises(Exception, match="Invalid properties"):
            validate_properties({"badKey1": 1, "badKey2": 2}, "ctx")

    def test_invalid_nested_key_raises(self):
        with pytest.raises(Exception, match="Invalid properties"):
            validate_properties({"taskGroups": [{"unknownNestedKey": True}]}, "ctx")

    def test_invalid_key_inside_list_raises(self):
        with pytest.raises(Exception, match="Invalid properties"):
            validate_properties({"tasks": [{"reallyBadKey": "value"}]}, "ctx")


class TestExcludedKeys:
    """
    Contents of excluded keys (environment, variables, instanceTags,
    taskDataInputs, taskDataOutputs) must not be validated.
    """

    def test_environment_contents_not_validated(self):
        # Arbitrary env var names inside 'environment' must not raise
        validate_properties(
            {"environment": {"MY_CUSTOM_VAR": "value", "PATH": "/usr/bin"}}, "ctx"
        )

    def test_variables_contents_not_validated(self):
        validate_properties({"variables": {"myVar": "value", "anotherVar": 42}}, "ctx")

    def test_instance_tags_contents_not_validated(self):
        validate_properties(
            {"instanceTags": {"CostCentre": "eng", "Team": "platform"}}, "ctx"
        )

    def test_task_data_inputs_contents_not_validated(self):
        validate_properties(
            {"taskDataInputs": [{"source": "s3://bucket/key", "destination": "/tmp"}]},
            "ctx",
        )

    def test_task_data_outputs_contents_not_validated(self):
        validate_properties(
            {
                "taskDataOutputs": [
                    {"source": "/tmp/result", "destination": "s3://bucket/out"}
                ]
            },
            "ctx",
        )


class TestDeprecatedKeys:
    """
    Deprecated keys must raise an exception with a helpful migration hint.
    """

    @pytest.mark.parametrize(
        "key",
        [
            "autoShutdown",
            "autoShutdownDelay",
            "nodeBootTimeLimit",
            "nodeIdleTimeLimit",
            "idleNodeShutdownEnabled",
            "idlePoolShutdownEnabled",
            "idleNodeShutdownTimeout",
            "idlePoolShutdownTimeout",
        ],
    )
    def test_deprecated_key_raises(self, key):
        with pytest.raises(Exception, match="update your property names"):
            validate_properties({key: True}, "ctx")


# ---------------------------------------------------------------------------
# Maps whose keys are the user's own, and the error's form
# ---------------------------------------------------------------------------


class TestUserKeyedMaps:
    @pytest.mark.parametrize(
        "data",
        [
            {"addEnvironment": {"MY_VAR": "x"}},
            {"taskGroups": [{"addEnvironment": {"FOO": "1"}}]},
            {"taskGroups": [{"tasks": [{"environment": {"BAR": "2"}}]}]},
        ],
    )
    def test_environment_variable_names_are_not_properties(self, data):
        validate_properties(data, "ctx")


def _free_form_maps(name: str, schema: object) -> set[str]:
    """
    The names, at any depth, of the properties whose schema is an object
    with no fixed properties: a map whose keys the user chooses.
    """
    found: set[str] = set()
    if not isinstance(schema, dict):
        return found
    if (
        schema.get("type") == "object"
        and "properties" not in schema
        and schema.get("additionalProperties") not in (None, False)
    ):
        found.add(name)
    for key, value in (schema.get("properties") or {}).items():
        found |= _free_form_maps(key, value)
    for key in ("items", "additionalProperties"):
        if isinstance(schema.get(key), dict):
            found |= _free_form_maps(name, schema[key])
    return found


def test_every_free_form_map_is_excluded():
    """
    A property whose keys are the user's own -- environment variable names,
    tags -- is excluded from the ALL_KEYS check, or every key in it would be
    an 'invalid property' (as 'addEnvironment's were).
    """
    from yellowdog_cli.utils import spec_properties
    from yellowdog_cli.utils.validate_properties import EXCLUDED_KEYS

    properties = list(spec_properties.WORK_REQUIREMENT_PROPERTIES)
    for section in spec_properties.CONFIG_SECTIONS.values():
        properties += list(section)
    maps: set[str] = set()
    for property_ in properties:
        maps |= _free_form_maps(property_.name, property_.schema)
    assert maps, "the walk found no maps at all"
    assert maps <= set(EXCLUDED_KEYS), sorted(maps - set(EXCLUDED_KEYS))


def test_invalid_properties_are_named_sorted_in_a_value_error():
    with pytest.raises(ValueError, match=r"^Invalid properties in ctx: 'nope', 'zzz'$"):
        validate_properties({"zzz": 1, "nope": 2}, "ctx")
