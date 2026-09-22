"""
Unit tests for --property CLI override helpers in load_config.py.
"""

import re
from pathlib import Path

import pytest

from yellowdog_cli.utils import load_config, property_names
from yellowdog_cli.utils import variables as var_module
from yellowdog_cli.utils.load_config import (
    _apply_property_overrides,
    _parse_property_value,
)
from yellowdog_cli.utils.property_names import (
    ALL_KEYS,
    COMMON_SECTION,
    DATA_CLIENT_SECTION,
    STRING_PROPERTIES,
    VARIABLES,
    WORK_REQUIREMENT_SECTION,
    WORKER_POOL_SECTION,
)


class TestParsePropertyValue:
    """
    Tests for _parse_property_value: value string → Python object.
    """

    @pytest.mark.parametrize(
        "s,expected",
        [
            ("hello", "hello"),
            ("42", 42),
            ("3.14", pytest.approx(3.14)),
            ("true", True),
            ("false", False),
            ('["a", "b"]', ["a", "b"]),
            ('{"k": "v"}', {"k": "v"}),
            ("null", None),
            ("hello world", "hello world"),
            ("https://api.example.com", "https://api.example.com"),
        ],
    )
    def test_parse(self, s, expected):
        assert _parse_property_value(s) == expected


class TestApplyPropertyOverrides:
    """
    Tests for _apply_property_overrides: inject overrides into CONFIG_TOML.
    """

    def test_single_override(self):
        config = {COMMON_SECTION: {}}
        _apply_property_overrides(config, [f"{COMMON_SECTION}.namespace=myns"])
        assert config[COMMON_SECTION]["namespace"] == "myns"

    def test_creates_section_if_missing(self):
        config = {}
        _apply_property_overrides(config, [f"{WORK_REQUIREMENT_SECTION}.priority=1.5"])
        assert config[WORK_REQUIREMENT_SECTION]["priority"] == pytest.approx(1.5)

    def test_overrides_existing_value(self):
        config = {DATA_CLIENT_SECTION: {"bucket": "oldbucket"}}
        _apply_property_overrides(config, [f"{DATA_CLIENT_SECTION}.bucket=newbucket"])
        assert config[DATA_CLIENT_SECTION]["bucket"] == "newbucket"

    def test_json_list_value(self):
        config = {}
        _apply_property_overrides(
            config, [f'{WORK_REQUIREMENT_SECTION}.workerTags=["tag1","tag2"]']
        )
        assert config[WORK_REQUIREMENT_SECTION]["workerTags"] == ["tag1", "tag2"]

    def test_bool_value(self):
        config = {}
        _apply_property_overrides(
            config, [f"{WORKER_POOL_SECTION}.maintainInstanceCount=true"]
        )
        assert config[WORKER_POOL_SECTION]["maintainInstanceCount"] is True

    def test_multiple_overrides(self):
        config = {}
        _apply_property_overrides(
            config,
            [
                f"{COMMON_SECTION}.namespace=ns1",
                f"{DATA_CLIENT_SECTION}.bucket=b1",
            ],
        )
        assert config[COMMON_SECTION]["namespace"] == "ns1"
        assert config[DATA_CLIENT_SECTION]["bucket"] == "b1"

    def test_invalid_format_missing_equals_raises(self):
        with pytest.raises(SystemExit):
            _apply_property_overrides({}, ["workRequirement.priority"])

    def test_invalid_format_missing_section_raises(self):
        with pytest.raises(SystemExit):
            _apply_property_overrides({}, ["priority=1"])

    def test_unknown_section_raises(self):
        with pytest.raises(SystemExit):
            _apply_property_overrides({}, ["unknownSection.key=value"])


class TestStringPropertiesKeepTheirText:
    """
    A property that takes a String keeps the text as supplied, rather than
    whatever JSON makes of it: a Work Requirement named '123' is a name, not
    an integer.
    """

    @pytest.mark.parametrize(
        "property_name,value_str",
        [
            ("name", "123"),
            ("name", "true"),
            ("tag", "2024"),
            ("namespace", "01"),
            ("taskType", "3.5"),
            ("bucket", "[1, 2]"),
            ("workerTag", "-1"),
        ],
    )
    def test_string_property_keeps_its_text(self, property_name, value_str):
        result = _parse_property_value(value_str, property_name)
        assert isinstance(result, str)
        assert result == value_str

    def test_quoted_value_is_still_unwrapped(self):
        # JSON that already yields a string is used as such, so the explicit
        # form keeps working
        assert _parse_property_value('"123"', "name") == "123"

    def test_null_still_unsets_a_string_property(self):
        # 'null' is the only way to clear a property set in the TOML file,
        # and is not a name anyone means to use
        assert _parse_property_value("null", "name") is None

    @pytest.mark.parametrize(
        "property_name,value_str,expected",
        [
            ("priority", "1.5", pytest.approx(1.5)),
            ("targetInstanceCount", "4", 4),
            ("maintainInstanceCount", "true", True),
            ("workerTags", '["a", "b"]', ["a", "b"]),
            ("notAPropertyName", "123", 123),
        ],
    )
    def test_other_properties_are_unaffected(self, property_name, value_str, expected):
        assert _parse_property_value(value_str, property_name) == expected

    def test_numeric_name_override_end_to_end(self):
        config = {}
        _apply_property_overrides(config, [f"{WORK_REQUIREMENT_SECTION}.name=123"])
        assert config[WORK_REQUIREMENT_SECTION]["name"] == "123"

    def test_string_property_nested_under_a_profile(self):
        # Data client profiles nest the property one level down; the property
        # name is what identifies it, not the path it sits at
        config = {}
        _apply_property_overrides(
            config, [f"{DATA_CLIENT_SECTION}.myprofile.prefix=2024"]
        )
        assert config[DATA_CLIENT_SECTION]["myprofile"]["prefix"] == "2024"


class TestStringPropertiesRegistry:
    """
    STRING_PROPERTIES is maintained by hand, so it is checked against the
    types recorded in the comment column of 'property_names.py'.
    """

    @staticmethod
    def _documented_string_properties() -> set[str]:
        source = Path(property_names.__file__).read_text().split("ALL_KEYS")[0]
        # Fold the one definition wrapped over several lines
        source = re.sub(r"= \(\s*\n\s*", "= ", source)
        return {
            match.group(2)
            for match in re.finditer(
                r'^([A-Z_0-9]+) = "([^"]+)"\s+#\s*String\b', source, re.M
            )
        }

    def test_every_documented_string_property_is_registered(self):
        assert self._documented_string_properties() - STRING_PROPERTIES == set()

    def test_registry_contains_nothing_else(self):
        assert STRING_PROPERTIES - self._documented_string_properties() == set()

    def test_registry_contains_only_known_keys(self):
        assert STRING_PROPERTIES <= set(ALL_KEYS)


class TestVariableOverridesAreHeldAsJson:
    """
    '--property common.variables.<name>=<value>' JSON-parses its value, so a
    variable can arrive here as a real list or dict. It is stored as JSON
    rather than as str()'s Python repr, so that the 'array:' and 'table:'
    type tags can read it back.
    """

    @pytest.fixture(autouse=True)
    def isolated_substitutions(self, monkeypatch):
        monkeypatch.setattr(var_module, "VARIABLE_SUBSTITUTIONS", {})
        monkeypatch.setattr(load_config, "CLI_DEFINED_VARIABLES", set())

    def test_array_variable_round_trips(self):
        _apply_property_overrides({}, [f'{COMMON_SECTION}.{VARIABLES}.strs=["a", "b"]'])
        assert var_module.process_variable_substitutions("{{array:strs}}") == ["a", "b"]

    def test_table_variable_round_trips(self):
        _apply_property_overrides(
            {}, [f'{COMMON_SECTION}.{VARIABLES}.tbl={{"x": "y"}}']
        )
        assert var_module.process_variable_substitutions("{{table:tbl}}") == {"x": "y"}

    @pytest.mark.parametrize(
        "override,expected", [("n=7", "7"), ("b=true", "true"), ("s=abc", "abc")]
    )
    def test_scalar_variable_is_rendered_as_json(self, override, expected):
        _apply_property_overrides({}, [f"{COMMON_SECTION}.{VARIABLES}.{override}"])
        assert var_module.get_user_variable(override.partition("=")[0]) == expected
