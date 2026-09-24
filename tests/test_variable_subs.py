"""
Unit tests for yellowdog_cli.utils.variables

Tests cover process_typed_variable_substitution (pure, no global state)
and process_variable_substitutions / process_variable_substitutions_in_file_contents
(require patching the VARIABLE_SUBSTITUTIONS global).
"""

import json
import subprocess
import sys
from unittest.mock import MagicMock

import pytest

import yellowdog_cli.utils.variables as var_module
from yellowdog_cli.utils.misc_utils import BASE36_DIGITS
from yellowdog_cli.utils.settings import (
    ARRAY_TYPE_TAG,
    BOOL_TYPE_TAG,
    FORMAT_NAME_TYPE_TAG,
    NUMBER_TYPE_TAG,
    TABLE_TYPE_TAG,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

KNOWN_SUBS = {"myvar": "hello", "num_var": "42", "bool_var": "true", "pi": "3.14"}


@pytest.fixture()
def patched_subs(monkeypatch):
    """Replace VARIABLE_SUBSTITUTIONS with a known, predictable dict."""
    monkeypatch.setattr(var_module, "VARIABLE_SUBSTITUTIONS", dict(KNOWN_SUBS))


# ---------------------------------------------------------------------------
# process_typed_variable_substitution
# ---------------------------------------------------------------------------


class TestProcessTypedVariableSubstitution:
    """This function is pure — no global state involved."""

    @pytest.mark.parametrize(
        "s,expected", [("42", 42), ("3.14", 3.14), ("-7", -7), ("0", 0)]
    )
    def test_number_valid(self, s, expected):
        assert (
            var_module.process_typed_variable_substitution(NUMBER_TYPE_TAG, s)
            == expected
        )

    def test_number_invalid_raises(self):
        with pytest.raises(Exception, match="Non-number"):
            var_module.process_typed_variable_substitution(
                NUMBER_TYPE_TAG, "not-a-number"
            )

    @pytest.mark.parametrize("s", ["true", "True", "TRUE"])
    def test_bool_true(self, s):
        assert var_module.process_typed_variable_substitution(BOOL_TYPE_TAG, s) is True

    @pytest.mark.parametrize("s", ["false", "False"])
    def test_bool_false(self, s):
        assert var_module.process_typed_variable_substitution(BOOL_TYPE_TAG, s) is False

    @pytest.mark.parametrize("s", ["yes", "1"])
    def test_bool_invalid_raises(self, s):
        with pytest.raises(Exception, match="Non-boolean"):
            var_module.process_typed_variable_substitution(BOOL_TYPE_TAG, s)

    @pytest.mark.parametrize(
        "s,expected",
        [
            ("[1, 2, 3]", [1, 2, 3]),
            ('["a", "b", "c"]', ["a", "b", "c"]),
            ("[true, false]", [True, False]),
            ("[]", []),
        ],
    )
    def test_array_valid(self, s, expected):
        assert (
            var_module.process_typed_variable_substitution(ARRAY_TYPE_TAG, s)
            == expected
        )

    @pytest.mark.parametrize("s", ['{"a": 1}', "not-a-list", "['single', 'quotes']"])
    def test_array_invalid_raises(self, s):
        with pytest.raises(Exception, match="array"):
            var_module.process_typed_variable_substitution(ARRAY_TYPE_TAG, s)

    @pytest.mark.parametrize(
        "s,expected",
        [
            ('{"a": 1}', {"a": 1}),
            ('{"x": {"y": 2}}', {"x": {"y": 2}}),
            ('{"flag": true}', {"flag": True}),
        ],
    )
    def test_table_valid(self, s, expected):
        assert (
            var_module.process_typed_variable_substitution(TABLE_TYPE_TAG, s)
            == expected
        )

    @pytest.mark.parametrize("s", ["[1, 2]", "not-a-dict", "{'single': 'quotes'}"])
    def test_table_invalid_raises(self, s):
        with pytest.raises(Exception, match="table"):
            var_module.process_typed_variable_substitution(TABLE_TYPE_TAG, s)

    @pytest.mark.parametrize(
        "s,expected",
        [("My Name/Value", "my_name-value"), ("Test@Job#2024", "testjob2024")],
    )
    def test_format_name(self, s, expected):
        assert (
            var_module.process_typed_variable_substitution(FORMAT_NAME_TYPE_TAG, s)
            == expected
        )

    def test_unknown_type_tag_returns_none(self):
        assert (
            var_module.process_typed_variable_substitution("unknown:", "value") is None
        )


# ---------------------------------------------------------------------------
# process_variable_substitutions
# ---------------------------------------------------------------------------


class TestProcessVariableSubstitutions:
    @pytest.fixture(autouse=True)
    def use_known_subs(self, patched_subs):
        pass

    def test_none_input_returns_none(self):
        assert var_module.process_variable_substitutions(None) is None

    def test_no_delimiters_returns_unchanged(self):
        assert var_module.process_variable_substitutions("plain text") == "plain text"

    def test_simple_substitution(self):
        assert var_module.process_variable_substitutions("{{myvar}}") == "hello"

    def test_substitution_embedded_in_string(self):
        assert (
            var_module.process_variable_substitutions("say {{myvar}} world")
            == "say hello world"
        )

    def test_multiple_substitutions(self):
        assert (
            var_module.process_variable_substitutions("{{myvar}} and {{myvar}}")
            == "hello and hello"
        )

    def test_unresolved_var_left_unchanged(self):
        assert var_module.process_variable_substitutions("{{unknown}}") == "{{unknown}}"

    def test_default_value_used_when_var_missing(self):
        assert (
            var_module.process_variable_substitutions("{{missing:=default}}")
            == "default"
        )

    def test_default_value_not_used_when_var_present(self):
        assert (
            var_module.process_variable_substitutions("{{myvar:=fallback}}") == "hello"
        )

    def test_num_type_tag_returns_int(self):
        result = var_module.process_variable_substitutions("{{num:num_var}}")
        assert result == 42
        assert isinstance(result, int)

    def test_num_type_tag_returns_float(self):
        result = var_module.process_variable_substitutions("{{num:pi}}")
        assert result == 3.14

    def test_bool_type_tag_returns_bool(self):
        result = var_module.process_variable_substitutions("{{bool:bool_var}}")
        assert result is True

    def test_array_type_tag(self):
        var_module.VARIABLE_SUBSTITUTIONS["arr"] = "[1, 2, 3]"
        result = var_module.process_variable_substitutions("{{array:arr}}")
        assert result == [1, 2, 3]

    def test_type_tag_in_larger_string_stringified(self):
        # When type-tagged var is not the only element, result is stringified
        result = var_module.process_variable_substitutions("count={{num:num_var}}")
        assert result == "count=42"

    def test_env_var_substitution(self, monkeypatch):
        monkeypatch.setenv("_YD_TEST_MY_ENV_VAR", "from-env")
        result = var_module.process_variable_substitutions(
            "{{env:_YD_TEST_MY_ENV_VAR}}"
        )
        assert result == "from-env"

    def test_env_var_default_used_when_missing(self):
        result = var_module.process_variable_substitutions(
            "{{env:_YD_TEST_NONEXISTENT_XYZ:=fallback}}"
        )
        assert result == "fallback"

    def test_env_var_value_overrides_default(self, monkeypatch):
        monkeypatch.setenv("_YD_TEST_VAR_WITH_DEFAULT", "real-value")
        result = var_module.process_variable_substitutions(
            "{{env:_YD_TEST_VAR_WITH_DEFAULT:=fallback}}"
        )
        assert result == "real-value"

    def test_malformed_default_empty_var_name_raises(self):
        with pytest.raises(Exception, match="Malformed"):
            var_module.process_variable_substitutions("{{:=value}}")

    def test_malformed_multiple_separators_raises(self):
        # '{{a:=b:=c}}' has two ':=' separators — should raise ValueError
        with pytest.raises(ValueError, match="Malformed"):
            var_module.process_variable_substitutions("{{a:=b:=c}}")


# ---------------------------------------------------------------------------
# Type tag / default interaction
# ---------------------------------------------------------------------------


class TestTypeTagAndDefault:
    """
    The regex lookahead '(?!=)' prevents a type tag from being matched when
    immediately followed by '=', keeping '{{num:=5}}' (variable 'num' with
    default '5') distinct from '{{num:myvar}}' (typed substitution).
    """

    @pytest.fixture(autouse=True)
    def use_known_subs(self, patched_subs):
        pass

    def test_var_named_like_type_tag_uses_default(self):
        # '{{num:=5}}': 'num' is not in the substitutions dict, ':=' is the
        # default separator — NOT a typed variable. Should return default '5'.
        result = var_module.process_variable_substitutions("{{num:=5}}")
        assert result == "5"

    def test_type_tag_with_default_var_missing(self):
        # '{{num:missing:=42}}': type tag 'num:', variable 'missing' (undefined),
        # default '42'. Should return 42 as int.
        result = var_module.process_variable_substitutions("{{num:missing:=42}}")
        assert result == 42
        assert isinstance(result, int)

    def test_type_tag_with_default_var_defined(self):
        # '{{num:num_var:=99}}': type tag 'num:', variable 'num_var' (defined
        # as '42'), default '99' ignored. Should return 42 as int.
        result = var_module.process_variable_substitutions("{{num:num_var:=99}}")
        assert result == 42
        assert isinstance(result, int)


# ---------------------------------------------------------------------------
# Multi-variable strings and nested variable names
# ---------------------------------------------------------------------------


class TestMixedAndNested:
    @pytest.fixture(autouse=True)
    def use_known_subs(self, patched_subs):
        pass

    def test_simple_and_defaulted_var_in_same_string(self):
        # '{{myvar}}' is resolved in the first substitution pass;
        # '{{unknown:=fallback}}' is resolved via the default mechanism.
        # Both must work together in a single string.
        result = var_module.process_variable_substitutions(
            "{{myvar}} and {{unknown:=fallback}}"
        )
        assert result == "hello and fallback"

    def test_doubly_nested_variable_name(self):
        # '{{{{dyn_key}}}}': inner '{{dyn_key}}' resolves to 'myvar', which is
        # then used as the variable name, resolving to 'hello'.
        var_module.VARIABLE_SUBSTITUTIONS["dyn_key"] = "myvar"
        result = var_module.process_variable_substitutions("{{{{dyn_key}}}}")
        assert result == "hello"


# ---------------------------------------------------------------------------
# Unset suffix ('::')
# ---------------------------------------------------------------------------


class TestUnsetSuffix:
    """
    '{{varname::}}' removes the property when varname is undefined,
    and uses the variable's value when it is defined.
    """

    @pytest.fixture(autouse=True)
    def use_known_subs(self, patched_subs):
        pass

    # process_variable_substitutions: value-level behaviour

    def test_unset_returns_sentinel_when_var_missing(self):
        result = var_module.process_variable_substitutions("{{missing::}}")
        assert result is var_module._UNSET

    def test_unset_returns_value_when_var_defined(self):
        result = var_module.process_variable_substitutions("{{myvar::}}")
        assert result == "hello"

    def test_unset_with_numeric_var_defined(self):
        result = var_module.process_variable_substitutions("{{num_var::}}")
        assert result == "42"

    # process_variable_substitutions_insitu: dict-level removal

    def test_dict_key_removed_when_var_missing(self):
        data = {"name": "job", "tag": "{{missing::}}"}
        var_module.process_variable_substitutions_insitu(data)
        assert "tag" not in data
        assert data["name"] == "job"

    def test_dict_key_kept_when_var_defined(self):
        data = {"name": "job", "tag": "{{myvar::}}"}
        var_module.process_variable_substitutions_insitu(data)
        assert data["tag"] == "hello"

    def test_multiple_dict_keys_removed(self):
        data = {"name": "job", "tag": "{{missing1::}}", "ns": "{{missing2::}}"}
        var_module.process_variable_substitutions_insitu(data)
        assert "tag" not in data
        assert "ns" not in data
        assert data["name"] == "job"

    def test_nested_dict_key_removed(self):
        data = {"outer": {"name": "x", "optional": "{{missing::}}"}}
        var_module.process_variable_substitutions_insitu(data)
        assert "optional" not in data["outer"]
        assert data["outer"]["name"] == "x"

    # process_variable_substitutions_insitu: list-level removal

    def test_list_element_removed_when_var_missing(self):
        data = {"items": ["keep", "{{missing::}}", "also-keep"]}
        var_module.process_variable_substitutions_insitu(data)
        assert data["items"] == ["keep", "also-keep"]

    def test_list_element_kept_when_var_defined(self):
        data = {"items": ["{{myvar::}}", "other"]}
        var_module.process_variable_substitutions_insitu(data)
        assert data["items"] == ["hello", "other"]

    # env: prefix with '::' unset suffix

    def test_env_unset_returns_value_when_env_var_set(self, monkeypatch):
        monkeypatch.setenv("_YD_TEST_UNSET_VAR", "from-env")
        result = var_module.process_variable_substitutions(
            "{{env:_YD_TEST_UNSET_VAR::}}"
        )
        assert result == "from-env"

    def test_env_unset_returns_sentinel_when_env_var_missing(self):
        result = var_module.process_variable_substitutions(
            "{{env:_YD_TEST_NONEXISTENT_UNSET_XYZ::}}"
        )
        assert result is var_module._UNSET

    def test_env_unset_dict_key_kept_when_env_var_set(self, monkeypatch):
        monkeypatch.setenv("_YD_TEST_UNSET_VAR", "cfg-value")
        data = {"key": "{{env:_YD_TEST_UNSET_VAR::}}"}
        var_module.process_variable_substitutions_insitu(data)
        assert data["key"] == "cfg-value"

    def test_env_unset_dict_key_removed_when_env_var_missing(self):
        data = {"name": "job", "key": "{{env:_YD_TEST_NONEXISTENT_UNSET_XYZ::}}"}
        var_module.process_variable_substitutions_insitu(data)
        assert "key" not in data
        assert data["name"] == "job"

    # bare '{{::}}' — always-unset shorthand

    def test_bare_unset_returns_sentinel(self):
        result = var_module.process_variable_substitutions("{{::}}")
        assert result is var_module._UNSET

    def test_bare_unset_removes_dict_key(self):
        data = {"name": "job", "taskType": "{{::}}"}
        var_module.process_variable_substitutions_insitu(data)
        assert "taskType" not in data
        assert data["name"] == "job"

    def test_bare_unset_removes_list_element(self):
        data = {"items": ["keep", "{{::}}", "also-keep"]}
        var_module.process_variable_substitutions_insitu(data)
        assert data["items"] == ["keep", "also-keep"]

    # Nested: an unset expression inside another one. The property is removed
    # when the unset expression's value would be needed -- to build a
    # variable's name, or as a default that is used -- and kept when it would
    # not. Its token used to be left in place instead, so the outer
    # expression looked up a name with '{{missing::}}' in it, found nothing,
    # and the whole expression reached the specification unresolved

    def test_nested_unset_in_a_variable_name(self):
        var_module.VARIABLE_SUBSTITUTIONS["template_hello"] = "T"
        result = var_module.process_variable_substitutions("{{template_{{missing::}}}}")
        assert result is var_module._UNSET

    def test_nested_unset_in_a_variable_name_when_defined(self):
        var_module.VARIABLE_SUBSTITUTIONS["template_hello"] = "T"
        result = var_module.process_variable_substitutions("{{template_{{myvar::}}}}")
        assert result == "T"

    def test_nested_unset_two_levels_down(self):
        result = var_module.process_variable_substitutions("{{a_{{b_{{missing::}}}}}}")
        assert result is var_module._UNSET

    def test_nested_bare_unset(self):
        result = var_module.process_variable_substitutions("{{template_{{::}}}}")
        assert result is var_module._UNSET

    def test_nested_unset_in_a_larger_string(self):
        result = var_module.process_variable_substitutions(
            "x-{{template_{{missing::}}}}"
        )
        assert result is var_module._UNSET

    def test_nested_unset_with_a_type_tag(self):
        result = var_module.process_variable_substitutions(
            "{{num:count_{{missing::}}}}"
        )
        assert result is var_module._UNSET

    def test_nested_unset_as_a_default_that_is_used(self):
        result = var_module.process_variable_substitutions(
            "{{undefined:={{missing::}}}}"
        )
        assert result is var_module._UNSET

    def test_nested_unset_as_a_default_that_is_not_used(self):
        result = var_module.process_variable_substitutions("{{myvar:={{missing::}}}}")
        assert result == "hello"

    def test_nested_unset_removes_dict_key(self):
        data = {"name": "job", "templateId": "{{template_{{missing::}}}}"}
        var_module.process_variable_substitutions_insitu(data)
        assert data == {"name": "job"}

    def test_nested_unset_removes_list_element(self):
        data = {"items": ["keep", "{{template_{{missing::}}}}"]}
        var_module.process_variable_substitutions_insitu(data)
        assert data["items"] == ["keep"]

    def test_variable_defined_with_a_nested_unset_is_removed(self):
        # A variable whose value needs an unset expression is itself unset,
        # as a variable whose value is '{{missing::}}' already is
        var_module.add_substitutions_without_overwriting(
            {"derived": "{{template_{{missing::}}}}"}
        )
        assert var_module.get_user_variable("derived") is None

    # JSON file content path

    def test_unset_in_file_contents_leaves_token_intact(self):
        """process_variable_substitutions_in_file_contents must not corrupt
        unset tokens — they must survive for dict-level removal."""
        import json

        raw = '{"name": "job", "taskType": "{{::}}"}'
        processed = var_module.process_variable_substitutions_in_file_contents(raw)
        # Token left intact → JSON is still valid
        data = json.loads(processed)
        assert data["taskType"] == "{{::}}"

    def test_unset_removed_after_json_parse(self):
        """Full pipeline: file content → json.loads → insitu gives clean dict."""
        import json

        raw = '{"name": "job", "taskType": "{{::}}"}'
        processed = var_module.process_variable_substitutions_in_file_contents(raw)
        data = json.loads(processed)
        var_module.process_variable_substitutions_insitu(data)
        assert "taskType" not in data
        assert data["name"] == "job"

    def test_missing_var_unset_in_file_contents_leaves_token_intact(self):
        """Same pipeline with a named-but-missing variable."""
        import json

        raw = '{"name": "job", "tag": "{{missing_var::}}"}'
        processed = var_module.process_variable_substitutions_in_file_contents(raw)
        data = json.loads(processed)
        var_module.process_variable_substitutions_insitu(data)
        assert "tag" not in data
        assert data["name"] == "job"


# ---------------------------------------------------------------------------
# add_substitutions_without_overwriting
# ---------------------------------------------------------------------------


class TestAddSubstitutionsWithoutOverwriting:
    """
    Tests for the merging/resolution step that runs after a TOML
    [common.variables] section is loaded.
    """

    @pytest.fixture(autouse=True)
    def reset_subs(self, monkeypatch):
        monkeypatch.setattr(var_module, "VARIABLE_SUBSTITUTIONS", dict(KNOWN_SUBS))

    def test_new_var_added(self):
        var_module.add_substitutions_without_overwriting({"newvar": "world"})
        assert var_module.VARIABLE_SUBSTITUTIONS["newvar"] == "world"

    def test_existing_var_not_overwritten_by_incoming(self):
        # Existing entries (CLI / env vars) take priority over incoming TOML values
        var_module.add_substitutions_without_overwriting({"myvar": "overridden"})
        assert var_module.VARIABLE_SUBSTITUTIONS["myvar"] == "hello"

    def test_existing_var_preserved_when_not_in_incoming(self):
        # Pre-existing entries not in the incoming subs are still kept
        var_module.add_substitutions_without_overwriting({"newvar": "world"})
        assert var_module.VARIABLE_SUBSTITUTIONS["myvar"] == "hello"

    def test_resolved_reference_stored_as_string(self):
        # newvar = "{{myvar}}" → should resolve to "hello"
        var_module.add_substitutions_without_overwriting({"newvar": "{{myvar}}"})
        assert var_module.VARIABLE_SUBSTITUTIONS["newvar"] == "hello"

    def test_unset_var_removed_from_substitutions(self):
        # zzz = "{{missing::}}" — 'missing' not defined → zzz should be deleted,
        # not stored as the _UNSET sentinel (regression test for the bug that
        # produced "<object object at 0x...>" in yd-show output)
        var_module.add_substitutions_without_overwriting({"zzz": "{{missing::}}"})
        assert "zzz" not in var_module.VARIABLE_SUBSTITUTIONS

    def test_unset_var_not_stored_as_sentinel(self):
        # The sentinel must not leak into the substitutions table as a string
        var_module.add_substitutions_without_overwriting({"zzz": "{{missing::}}"})
        assert var_module.VARIABLE_SUBSTITUTIONS.get("zzz") is not var_module._UNSET
        stored = var_module.VARIABLE_SUBSTITUTIONS.get("zzz", "")
        assert "<object object" not in stored

    def test_unset_var_defined_kept(self):
        # zzz = "{{myvar::}}" — 'myvar' IS defined → zzz should be kept with its value
        var_module.add_substitutions_without_overwriting({"zzz": "{{myvar::}}"})
        assert var_module.VARIABLE_SUBSTITUTIONS["zzz"] == "hello"


# ---------------------------------------------------------------------------
# add_substitutions_from_config_file
# ---------------------------------------------------------------------------


class TestAddSubstitutionsFromConfigFile:
    """
    TOML [common.variables] merging. With an explicitly selected config file
    ('--config'/'-c'), TOML variables override env-derived definitions but
    never command-line-defined ones.
    """

    @pytest.fixture(autouse=True)
    def reset_state(self, monkeypatch):
        monkeypatch.setattr(var_module, "VARIABLE_SUBSTITUTIONS", dict(KNOWN_SUBS))
        monkeypatch.setattr(var_module, "CLI_DEFINED_VARIABLES", set())

    def _set_config_file(self, monkeypatch, value):
        monkeypatch.setattr(var_module, "ARGS_PARSER", MagicMock(config_file=value))

    def test_default_existing_value_wins(self, monkeypatch):
        self._set_config_file(monkeypatch, None)
        var_module.add_substitutions_from_config_file({"myvar": "from-toml"})
        assert var_module.VARIABLE_SUBSTITUTIONS["myvar"] == "hello"

    def test_explicit_config_toml_overrides_existing(self, monkeypatch):
        self._set_config_file(monkeypatch, "my-config.toml")
        var_module.add_substitutions_from_config_file({"myvar": "from-toml"})
        assert var_module.VARIABLE_SUBSTITUTIONS["myvar"] == "from-toml"

    def test_explicit_config_never_overrides_cli_variable(self, monkeypatch):
        self._set_config_file(monkeypatch, "my-config.toml")
        var_module.CLI_DEFINED_VARIABLES.add("myvar")
        var_module.add_substitutions_from_config_file(
            {"myvar": "from-toml", "other": "value"}
        )
        assert var_module.VARIABLE_SUBSTITUTIONS["myvar"] == "hello"
        assert var_module.VARIABLE_SUBSTITUTIONS["other"] == "value"

    def test_explicit_config_new_vars_added(self, monkeypatch):
        self._set_config_file(monkeypatch, "my-config.toml")
        var_module.add_substitutions_from_config_file({"newvar": "world"})
        assert var_module.VARIABLE_SUBSTITUTIONS["newvar"] == "world"


# ---------------------------------------------------------------------------
# process_variable_substitutions_in_file_contents
# ---------------------------------------------------------------------------


class TestProcessVariableSubstitutionsInFileContents:
    @pytest.fixture(autouse=True)
    def use_known_subs(self, patched_subs):
        pass

    def test_no_vars_unchanged(self):
        content = "no variables here"
        assert (
            var_module.process_variable_substitutions_in_file_contents(content)
            == content
        )

    def test_simple_string_substitution(self):
        content = 'key = "{{myvar}}"'
        result = var_module.process_variable_substitutions_in_file_contents(content)
        assert result == 'key = "hello"'

    def test_number_type_tag_strips_quotes(self):
        # "{{num:num_var}}" → 42 (int) → replace quoted expression with bare value
        content = '"{{num:num_var}}"'
        result = var_module.process_variable_substitutions_in_file_contents(content)
        assert result == "42"

    def test_bool_type_tag_strips_quotes_and_lowercases(self):
        var_module.VARIABLE_SUBSTITUTIONS["flag"] = "true"
        content = '"{{bool:flag}}"'
        result = var_module.process_variable_substitutions_in_file_contents(content)
        assert result == "true"

    def test_single_quotes_also_stripped(self):
        content = "'{{num:num_var}}'"
        result = var_module.process_variable_substitutions_in_file_contents(content)
        assert result == "42"

    def test_unresolved_var_left_unchanged(self):
        content = '"{{unknown_var}}"'
        result = var_module.process_variable_substitutions_in_file_contents(content)
        assert result == '"{{unknown_var}}"'

    def test_multiple_vars_substituted(self):
        content = "{{myvar}} has {{num_var}} items"
        result = var_module.process_variable_substitutions_in_file_contents(content)
        assert result == "hello has 42 items"

    def test_array_type_tag_emits_valid_json(self):
        var_module.VARIABLE_SUBSTITUTIONS["arr"] = '["Alpha", "Beta"]'
        content = '{"items": "{{array:arr}}"}'
        result = var_module.process_variable_substitutions_in_file_contents(content)
        import json

        assert json.loads(result) == {"items": ["Alpha", "Beta"]}

    def test_table_type_tag_emits_valid_json(self):
        var_module.VARIABLE_SUBSTITUTIONS["tbl"] = '{"Key": "Value", "flag": true}'
        content = '{"table": "{{table:tbl}}"}'
        result = var_module.process_variable_substitutions_in_file_contents(content)
        import json

        assert json.loads(result) == {"table": {"Key": "Value", "flag": True}}

    def test_array_type_tag_single_quotes_jsonnet(self):
        var_module.VARIABLE_SUBSTITUTIONS["arr"] = '["Alpha", "Beta"]'
        content = "'{{array:arr}}'"
        result = var_module.process_variable_substitutions_in_file_contents(content)
        assert result == '["Alpha", "Beta"]'

    # Several expressions on one line, which is what compact (unindented)
    # JSON puts them on. Each has to be found as the expression it is: taken
    # together, as one match from the first '{{' to the last '}}', a type-
    # tagged one was substituted as text and its value came back a string

    def test_typed_expressions_on_one_line(self):
        content = '{"a":"{{num:num_var}}","b":"{{bool:bool_var}}"}'
        result = var_module.process_variable_substitutions_in_file_contents(content)
        assert json.loads(result) == {"a": 42, "b": True}

    def test_typed_expression_followed_by_closing_braces(self):
        # The object's own '}}' is not a closing delimiter
        content = '{"env":{"n":"{{num:num_var}}"}}'
        result = var_module.process_variable_substitutions_in_file_contents(content)
        assert json.loads(result) == {"env": {"n": 42}}

    def test_untyped_expression_followed_by_closing_braces(self):
        # This one raised 'Mismatched variable delimiters' outright
        content = '{"env":{"A":"{{myvar}}"}}'
        result = var_module.process_variable_substitutions_in_file_contents(content)
        assert json.loads(result) == {"env": {"A": "hello"}}

    def test_nested_typed_expressions_on_one_line(self):
        var_module.VARIABLE_SUBSTITUTIONS["which"] = "num_var"
        content = '{"a":"{{num:{{which}}}}","b":"{{bool:bool_var}}"}'
        result = var_module.process_variable_substitutions_in_file_contents(content)
        assert json.loads(result) == {"a": 42, "b": True}

    def test_typed_and_untyped_expressions_on_one_line(self):
        content = "{a:'{{myvar}}',b:'{{num:num_var}}'}"
        result = var_module.process_variable_substitutions_in_file_contents(content)
        assert result == "{a:'hello',b:42}"


# ---------------------------------------------------------------------------
# The '{{random}}' and '{{random6}}' default substitutions
# ---------------------------------------------------------------------------


class TestRandomDefaultSubstitutions:
    """
    Both are base 36 rather than hexadecimal, which is what gives them their
    range: 46,656 values for '{{random}}' and 2,176,782,336 for '{{random6}}'.
    """

    def test_random_is_three_base36_digits(self):
        value = var_module.VARIABLE_SUBSTITUTIONS["random"]
        assert len(value) == 3
        assert all(character in BASE36_DIGITS for character in value)

    def test_random6_is_six_base36_digits(self):
        value = var_module.VARIABLE_SUBSTITUTIONS["random6"]
        assert len(value) == 6
        assert all(character in BASE36_DIGITS for character in value)

    def test_the_same_value_is_used_for_the_duration_of_a_command(self):
        # Drawn once at import, so every substitution in one command agrees
        content = "{{random}} {{random}} {{random6}} {{random6}}"
        first, second, third, fourth = (
            var_module.process_variable_substitutions_in_file_contents(content).split()
        )
        assert first == second
        assert third == fourth


# ---------------------------------------------------------------------------
# The '{{pid}}' and '{{pid2}}' default substitutions
# ---------------------------------------------------------------------------


class TestPidDefaultSubstitutions:
    """
    '{{pid}}' is the full PID of the running command. '{{pid2}}' exposes the
    process discriminator that generate_id() appends to an automatically
    generated name, so that a hand-written name can be made to disambiguate
    simultaneous launches in exactly the same way.
    """

    def test_are_default_substitutions(self):
        from yellowdog_cli.utils.misc_utils import PID, PROCESS_DISCRIMINATOR

        assert var_module.VARIABLE_SUBSTITUTIONS["pid"] == str(PID)
        assert var_module.VARIABLE_SUBSTITUTIONS["pid2"] == PROCESS_DISCRIMINATOR

    def test_substitutes_the_pid_of_the_running_process(self):
        # Run in a subprocess: the PID is the *interpreter's*, so this both
        # isolates the process-global substitutions dict and proves that the
        # substituted value is the PID of the process doing the substituting
        # The marker is needed because importing the module announces any
        # environment-defined substitutions it finds on the way past
        snippet = (
            "import os; "
            "from yellowdog_cli.utils.variables import "
            "process_variable_substitutions as p; "
            "print('RESULT', p('{{pid}}'), os.getpid())"
        )
        _, pid_substitution, actual_pid = self._run(snippet)
        assert pid_substitution == actual_pid

    def test_substitutes_the_discriminator_of_the_running_process(self):
        # As above, and additionally proves that the substituted value and the
        # generated name agree for one run
        snippet = (
            "from yellowdog_cli.utils.misc_utils import generate_id; "
            "from yellowdog_cli.utils.variables import "
            "process_variable_substitutions as p; "
            "print('RESULT', p('{{pid2}}'), generate_id('name'))"
        )
        _, pid_substitution, generated_name = self._run(snippet)
        assert len(pid_substitution) == 2
        assert generated_name.endswith(f"-{pid_substitution}")

    @staticmethod
    def _run(snippet: str) -> list[str]:
        output = subprocess.run(
            [sys.executable, "-c", snippet],
            stdout=subprocess.PIPE,
            text=True,
            check=True,
        ).stdout
        result = [line for line in output.splitlines() if line.startswith("RESULT ")]
        assert len(result) == 1, f"no single result line in {output!r}"
        return result[0].split()


# ---------------------------------------------------------------------------
# Non-scalar variable values
# ---------------------------------------------------------------------------


class TestVariableValueRendering:
    """
    Variable values are held as strings, so a value arriving as something
    else -- a TOML array, table, number or boolean from a configuration
    file's '[common.variables]' section, or a '--property' override -- has
    to be rendered as text on the way in. It is rendered as JSON rather than
    with str()'s Python repr, because the 'array:' and 'table:' type tags
    read the value back with json_loads(): a repr's single quotes are not
    JSON, so ["a", "b"] defined in TOML could not be used as an array at
    all. Strings are passed through, and a value with no JSON form falls
    back to str().
    """

    @pytest.fixture(autouse=True)
    def use_known_subs(self, patched_subs):
        pass

    def test_list_of_strings_round_trips_through_the_array_tag(self):
        var_module.add_substitutions_without_overwriting({"strs": ["a", "b"]})
        assert var_module.process_variable_substitutions("{{array:strs}}") == ["a", "b"]

    def test_table_round_trips_through_the_table_tag(self):
        var_module.add_substitutions_without_overwriting({"tbl": {"x": "y"}})
        assert var_module.process_variable_substitutions("{{table:tbl}}") == {"x": "y"}

    def test_nested_containers_round_trip(self):
        value = {"outer": [{"inner": "a"}, 2, True]}
        var_module.add_substitutions_without_overwriting({"nested": value})
        assert var_module.process_variable_substitutions("{{table:nested}}") == value

    def test_variables_inside_a_non_scalar_are_substituted(self):
        var_module.add_substitutions_without_overwriting({"strs": ["{{myvar}}", "b"]})
        assert var_module.process_variable_substitutions("{{array:strs}}") == [
            "hello",
            "b",
        ]

    def test_reported_as_json(self):
        var_module.add_substitutions_without_overwriting({"strs": ["a", "b"]})
        assert var_module.get_user_variable("strs") == '["a", "b"]'

    @pytest.mark.parametrize(
        "value,expected",
        [(7, "7"), (3.5, "3.5"), (True, "true"), (False, "false"), (None, "null")],
    )
    def test_scalars_are_rendered_as_json(self, value, expected):
        var_module.add_substitutions_without_overwriting({"scalar": value})
        assert var_module.get_user_variable("scalar") == expected

    @pytest.mark.parametrize("value", ["a", "[a", '"a"', "{{myvar}}"])
    def test_a_string_is_never_requoted(self, value):
        # Every value is re-rendered on each resolution pass, so a string that
        # gained JSON quotes would gain another pair on every pass
        var_module.add_substitutions_without_overwriting({"s": value})
        var_module.add_substitutions_without_overwriting({"other": "x"})
        expected = "hello" if value == "{{myvar}}" else value
        assert var_module.get_user_variable("s") == expected

    def test_toml_boolean_round_trips_through_the_bool_tag(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text("[common.variables]\nb = true\n")
        var_module.load_toml_file_with_variable_substitutions(str(toml_file))
        assert var_module.get_user_variable("b") == "true"
        assert var_module.process_variable_substitutions("{{bool:b}}") is True

    def test_toml_date_falls_back_to_its_text(self, tmp_path):
        # TOML dates and datetimes are date/datetime objects, which have no
        # JSON form at all: rendering them must fall back to str()
        toml_file = tmp_path / "config.toml"
        toml_file.write_text("[common.variables]\nd = 2024-01-01\n")
        var_module.load_toml_file_with_variable_substitutions(str(toml_file))
        assert var_module.get_user_variable("d") == "2024-01-01"

    def test_toml_array_of_strings_round_trips(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text('[common.variables]\nstrs = ["a", "b"]\n')
        var_module.load_toml_file_with_variable_substitutions(str(toml_file))
        assert var_module.process_variable_substitutions("{{array:strs}}") == ["a", "b"]

    def test_toml_table_round_trips(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text('[common.variables]\ntbl = { x = "y" }\n')
        var_module.load_toml_file_with_variable_substitutions(str(toml_file))
        assert var_module.process_variable_substitutions("{{table:tbl}}") == {"x": "y"}


# ---------------------------------------------------------------------------
# Nested variables in every specification format
# ---------------------------------------------------------------------------


def _write_json(path, props: dict) -> None:
    path.write_text(json.dumps(props, indent=2))


def _write_jsonnet(path, props: dict) -> None:
    fields = ",\n".join(f"  {key}: '{value}'" for key, value in props.items())
    path.write_text(f"{{\n{fields}\n}}\n")


def _write_toml(path, props: dict) -> None:
    lines = "".join(f"{key} = '{value}'\n" for key, value in props.items())
    path.write_text(f"[spec]\n{lines}")


def _load_json(path) -> dict:
    return var_module.load_json_file_with_variable_substitutions(str(path))


def _load_jsonnet(path) -> dict:
    from yellowdog_cli.utils.check_imports import check_jsonnet_import

    try:
        check_jsonnet_import()
    except ImportError as exc:
        pytest.skip(str(exc))
    return var_module.load_jsonnet_file_with_variable_substitutions(str(path))


def _load_toml(path) -> dict:
    return var_module.load_toml_file_with_variable_substitutions(str(path))["spec"]


SPEC_FORMATS = {
    "json": (_write_json, _load_json),
    "jsonnet": (_write_jsonnet, _load_jsonnet),
    "toml": (_write_toml, _load_toml),
}


class TestNestedVariablesInEveryFormat:
    """
    Nested variables are not a TOML feature: the recursion that resolves the
    innermost expression first is in process_untyped_variable_substitutions(),
    which every loader goes through, and each loader repeats its in-situ pass
    until a pass changes nothing, so that a value which substitutes in a
    further variable reference is resolved however long the chain. A chain
    that never settles is circular, and is an error at the pass cap,
    VAR_SUBSTITUTION_MAX_PASSES.
    """

    @pytest.fixture(autouse=True)
    def use_nesting_subs(self, patched_subs, monkeypatch):
        var_module.VARIABLE_SUBSTITUTIONS.update(
            {"region": "phoenix", "template_phoenix": "TP", "count_phoenix": "7"}
        )
        monkeypatch.setattr(var_module, "ARGS_PARSER", MagicMock(jsonnet_dry_run=False))

    @pytest.fixture(params=sorted(SPEC_FORMATS))
    def load_spec(self, request, tmp_path):
        write, load = SPEC_FORMATS[request.param]

        def _load(props: dict) -> dict:
            path = tmp_path / f"spec.{request.param}"
            write(path, props)
            return load(path)

        return _load

    def test_variable_name_built_from_a_variable(self, load_spec):
        assert load_spec({"t": "{{template_{{region}}}}"}) == {"t": "TP"}

    def test_nested_variable_in_a_default(self, load_spec):
        assert load_spec({"t": "{{undefined:={{region}}-x}}"}) == {"t": "phoenix-x"}

    def test_three_levels(self, load_spec):
        assert load_spec({"t": "{{template_{{reg{{undefined:=ion}}}}}}"}) == {"t": "TP"}

    def test_nested_variable_with_a_type_tag(self, load_spec):
        assert load_spec({"t": "{{num:count_{{region}}}}"}) == {"t": 7}

    def test_nested_alongside_a_plain_variable(self, load_spec):
        assert load_spec({"t": "{{template_{{region}}}}-{{region}}"}) == {
            "t": "TP-phoenix"
        }

    def test_nested_unset_removes_the_property(self, load_spec):
        assert load_spec({"keep": "k", "t": "{{template_{{missing::}}}}"}) == {
            "keep": "k"
        }

    def test_nested_unset_keeps_the_property_when_defined(self, load_spec):
        assert load_spec({"t": "{{template_{{region::}}}}"}) == {"t": "TP"}

    def test_value_substituting_in_further_references(self, load_spec, monkeypatch):
        # Each reference is only revealed by resolving the one before it,
        # about a link a pass. A fixed three passes stopped at three or four
        # links, leaving '{{env:YD_TEST_n}}' in the specification
        _chain_env_vars(monkeypatch, 8)
        assert load_spec({"t": "{{env:YD_TEST_0}}"}) == {"t": "phoenix"}

    def test_undefined_variable_is_not_a_cycle(self, load_spec):
        # Unchanged after the first pass, so the passes stop and it is passed
        # through as it always was
        assert load_spec({"t": "{{undefined}}"}) == {"t": "{{undefined}}"}

    def test_mutually_referring_variables_are_an_error(self, load_spec, monkeypatch):
        monkeypatch.setenv("YD_TEST_A", "{{env:YD_TEST_B}}")
        monkeypatch.setenv("YD_TEST_B", "{{env:YD_TEST_A}}")
        with pytest.raises(
            ValueError, match=r"circular.*(spec\.jsonnet|spec\.json|loop)'"
        ):
            load_spec({"fine": "{{region}}", "loop": "{{env:YD_TEST_A}}"})

    def test_self_referring_variable_is_an_error(self, load_spec, monkeypatch):
        # Never repeats itself, but grows on every pass, so never settles
        monkeypatch.setenv("YD_TEST_G", "x{{env:YD_TEST_G}}")
        with pytest.raises(
            ValueError, match=r"circular.*(spec\.jsonnet|spec\.json|grows)'"
        ):
            load_spec({"grows": "{{env:YD_TEST_G}}"})

    @pytest.mark.parametrize("order", [("p", "q"), ("q", "p")])
    def test_circular_table_variables_are_an_error(self, load_spec, order):
        # Defined, each resolves to its own token, which every pass then
        # substitutes back to itself: settled, but never resolved. Checked in
        # both definition orders, which decide what the values settle to
        values = {"p": "{{q}}", "q": "{{p}}"}
        var_module.add_substitutions_without_overwriting(
            {name: values[name] for name in order}
        )
        with pytest.raises(
            ValueError, match=r"(?i)circular.*(spec\.jsonnet|spec\.json|t)'"
        ):
            load_spec({"t": "{{p}}"})

    def test_self_referring_table_variable_is_an_error(self, load_spec):
        var_module.add_substitutions_without_overwriting({"s": "{{s}}"})
        with pytest.raises(ValueError, match="Circular variable reference: 's'"):
            load_spec({"t": "x-{{s}}"})


def _chain_env_vars(monkeypatch, links: int) -> None:
    """YD_TEST_0 -> '{{env:YD_TEST_1}}' -> ... -> '{{region}}'."""
    for i in range(links):
        monkeypatch.setenv(
            f"YD_TEST_{i}",
            f"{{{{env:YD_TEST_{i + 1}}}}}" if i < links - 1 else "{{region}}",
        )


class TestSubstitutionPasses:
    """
    resolve_variables_insitu() repeats the in-situ pass until one changes
    nothing, and raises at VAR_SUBSTITUTION_MAX_PASSES.
    """

    @pytest.fixture(autouse=True)
    def use_known_subs(self, patched_subs):
        pass

    @pytest.fixture()
    def pass_count(self, monkeypatch):
        passes = []
        real_pass = var_module._substitute_insitu_pass

        def _counting_pass(*args, **kwargs):
            passes.append(None)
            return real_pass(*args, **kwargs)

        monkeypatch.setattr(var_module, "_substitute_insitu_pass", _counting_pass)
        return passes

    def test_nothing_to_substitute_takes_one_pass(self, pass_count):
        var_module.resolve_variables_insitu({"a": "plain", "b": ["x", 1]})
        assert len(pass_count) == 1

    def test_plain_substitution_takes_two_passes(self, pass_count):
        # One to substitute, one to find there is nothing more to do
        data = {"a": "{{myvar}}"}
        var_module.resolve_variables_insitu(data)
        assert data == {"a": "hello"}
        assert len(pass_count) == 2

    def test_a_removed_property_is_a_change(self, pass_count):
        data = {"a": "{{missing::}}", "b": ["{{missing::}}"]}
        var_module.resolve_variables_insitu(data)
        assert data == {"b": []}
        assert len(pass_count) == 2

    @staticmethod
    def _passes_that_change(monkeypatch, changing: int) -> None:
        """Stand in for a pass: the first 'changing' passes change 'p'."""
        calls = []

        def _pass(data, prefix="", postfix=""):
            calls.append(None)
            return ["p"] if len(calls) <= changing else []

        monkeypatch.setattr(var_module, "_substitute_insitu_pass", _pass)

    def test_settling_on_the_last_pass_is_not_an_error(self, monkeypatch):
        cap = var_module.VAR_SUBSTITUTION_MAX_PASSES
        self._passes_that_change(monkeypatch, cap - 1)
        var_module.resolve_variables_insitu({})

    def test_still_changing_on_the_last_pass_is_an_error(self, monkeypatch):
        cap = var_module.VAR_SUBSTITUTION_MAX_PASSES
        self._passes_that_change(monkeypatch, cap)
        with pytest.raises(ValueError, match="circular"):
            var_module.resolve_variables_insitu({})

    def test_mustache_left_for_the_server_is_not_circular(self):
        # Only expressions in the delimiters being substituted are checked: a
        # Worker Pool specification's '__{{v}}__' is substituted and its
        # '{{v}}' left to the platform, whether or not 'v' is defined
        var_module.VARIABLE_SUBSTITUTIONS["v"] = "{{v}}"
        data = {"t": "{{v}}", "u": "__{{myvar}}__"}
        var_module.resolve_variables_insitu(data, prefix="__", postfix="__")
        assert data == {"t": "{{v}}", "u": "hello"}

    def test_a_long_chain_resolves(self, monkeypatch):
        _chain_env_vars(monkeypatch, 8)
        var_module.VARIABLE_SUBSTITUTIONS["region"] = "end"
        data = {"t": "{{env:YD_TEST_0}}"}
        var_module.resolve_variables_insitu(data)
        assert data == {"t": "end"}

    def test_the_cap_is_an_error_naming_the_property(self, monkeypatch):
        monkeypatch.setenv("YD_TEST_A", "{{env:YD_TEST_B}}")
        monkeypatch.setenv("YD_TEST_B", "{{env:YD_TEST_A}}")
        data = {"tasks": [{"name": "{{env:YD_TEST_A}}"}]}
        with pytest.raises(ValueError) as exc:
            var_module.resolve_variables_insitu(data)
        message = str(exc.value)
        assert f"{var_module.VAR_SUBSTITUTION_MAX_PASSES} passes" in message
        assert "'tasks[0].name'" in message


class TestCompactSpecifications:
    """
    A specification written without indentation, as a program writing JSON
    usually writes it, keeps its type-tagged values' types.
    """

    @pytest.fixture(autouse=True)
    def use_known_subs(self, patched_subs, monkeypatch):
        monkeypatch.setattr(var_module, "ARGS_PARSER", MagicMock(jsonnet_dry_run=False))

    def test_compact_json(self, tmp_path):
        path = tmp_path / "spec.json"
        path.write_text(
            json.dumps(
                {
                    "taskCount": "{{num:num_var}}",
                    "fiaft": "{{bool:bool_var}}",
                    "name": "{{num:num_var}}-{{myvar}}",
                    "task": {"env": {"PI": "{{num:pi}}"}},
                }
            )
        )
        assert var_module.load_json_file_with_variable_substitutions(str(path)) == {
            "taskCount": 42,
            "fiaft": True,
            "name": "42-hello",
            "task": {"env": {"PI": 3.14}},
        }

    def test_compact_jsonnet(self, tmp_path):
        path = tmp_path / "spec.jsonnet"
        path.write_text(
            "{taskCount:'{{num:num_var}}',fiaft:'{{bool:bool_var}}',"
            "task:{env:{PI:'{{num:pi}}'}}}"
        )
        assert _load_jsonnet(path) == {
            "taskCount": 42,
            "fiaft": True,
            "task": {"env": {"PI": 3.14}},
        }


# ---------------------------------------------------------------------------
# Warnings for undefined variables
# ---------------------------------------------------------------------------


class TestUndefinedVariableWarnings:
    """
    Once a command's own processing has begun -- every configuration
    variable defined -- an expression still unsubstituted after the passes
    have settled names a variable nothing defines, and is reported, once per
    expression, as a warning. The lazy variables yd-submit defines as it goes
    are not, and nor is anything that does not look like a variable at all.
    """

    @pytest.fixture(autouse=True)
    def enabled(self, patched_subs, monkeypatch):
        monkeypatch.setattr(var_module, "_UNDEFINED_VARIABLE_WARNINGS", True)
        monkeypatch.setattr(var_module, "_UNDEFINED_VARIABLES_REPORTED", set())
        warning = MagicMock()
        monkeypatch.setattr(var_module, "print_warning", warning)
        return warning

    @staticmethod
    def _warnings(warning: MagicMock) -> list[str]:
        return [str(call.args[0]) for call in warning.call_args_list]

    def test_undefined_variable_is_reported_with_its_property(self, enabled):
        data = {"tasks": [{"arguments": ["run", "{{regoin}}"]}]}
        var_module.resolve_variables_insitu(data)
        assert data == {"tasks": [{"arguments": ["run", "{{regoin}}"]}]}
        [warning] = self._warnings(enabled)
        assert "'{{regoin}}'" in warning
        assert "'tasks[0].arguments[1]'" in warning

    def test_each_expression_is_reported_once(self, enabled):
        data = {"a": "{{nope}}", "b": "x-{{nope}}", "c": "{{other}}"}
        var_module.resolve_variables_insitu(data)
        var_module.resolve_variables_insitu({"d": "{{nope}}"})
        warnings = self._warnings(enabled)
        assert len(warnings) == 2
        [nope] = [w for w in warnings if "{{nope}}" in w]
        assert "'a'" in nope and "'b'" in nope

    def test_many_properties_are_summarised(self, enabled):
        data = {"tasks": [{"name": "{{nope}}"} for _ in range(8)]}
        var_module.resolve_variables_insitu(data)
        [warning] = self._warnings(enabled)
        assert "and 3 more" in warning

    @pytest.mark.parametrize(
        "expression", ["{{num:nope}}", "{{env:YD_TEST_NOT_SET_XYZ}}", "{{a.b-c}}"]
    )
    def test_typed_env_and_dotted_forms_are_reported(self, enabled, expression):
        var_module.resolve_variables_insitu({"t": expression})
        [warning] = self._warnings(enabled)
        assert f"'{expression}'" in warning

    def test_undefined_inner_variable_is_reported(self, enabled):
        var_module.resolve_variables_insitu({"t": "{{template_{{nope}}}}"})
        [warning] = self._warnings(enabled)
        assert "'{{nope}}'" in warning

    def test_undefined_built_name_is_reported(self, enabled):
        var_module.resolve_variables_insitu({"t": "{{template_{{myvar}}}}"})
        [warning] = self._warnings(enabled)
        assert "'{{template_hello}}'" in warning

    @pytest.mark.parametrize(
        "text",
        [
            "docker ps --format '{{.ID}}'",
            "{{ .Values.image }}",
            "{{range .Items}}",
            "{{#each items}}",
        ],
    )
    def test_text_that_is_not_a_variable_is_not_reported(self, enabled, text):
        var_module.resolve_variables_insitu({"t": text})
        assert self._warnings(enabled) == []

    def test_lazy_variables_are_not_reported(self, enabled):
        from yellowdog_cli.utils.settings import L_TASK_NAME, L_WR_NAME

        var_module.resolve_variables_insitu(
            {"a": f"{{{{{L_TASK_NAME}}}}}", "b": f"{{{{{L_WR_NAME}}}}}"}
        )
        assert self._warnings(enabled) == []

    def test_defined_and_removed_variables_are_not_reported(self, enabled):
        data = {"a": "{{myvar}}", "b": "{{missing::}}", "c": "{{nope:=d}}"}
        var_module.resolve_variables_insitu(data)
        assert data == {"a": "hello", "c": "d"}
        assert self._warnings(enabled) == []

    def test_mustache_left_for_the_server_is_not_reported(self, enabled):
        data = {"t": "{{server_side}}", "u": "__{{nope}}__"}
        var_module.resolve_variables_insitu(data, prefix="__", postfix="__")
        [warning] = self._warnings(enabled)
        assert "'__{{nope}}__'" in warning

    def test_user_data_is_checked_with_its_own_delimiters(self, enabled):
        data = {"userData": "echo {{server_side}} __{{nope}}__"}
        var_module.resolve_variables_insitu(data)
        [warning] = self._warnings(enabled)
        assert "'__{{nope}}__'" in warning

    def test_nothing_is_reported_until_enabled(self, enabled, monkeypatch):
        monkeypatch.setattr(var_module, "_UNDEFINED_VARIABLE_WARNINGS", False)
        var_module.resolve_variables_insitu({"t": "{{nope}}"})
        assert self._warnings(enabled) == []

    def test_enabling(self, monkeypatch):
        monkeypatch.setattr(var_module, "_UNDEFINED_VARIABLE_WARNINGS", False)
        var_module.enable_undefined_variable_warnings()
        assert var_module._UNDEFINED_VARIABLE_WARNINGS is True

    def test_a_circular_reference_is_still_an_error(self, enabled):
        var_module.add_substitutions_without_overwriting({"s": "{{s}}"})
        with pytest.raises(ValueError, match="Circular"):
            var_module.resolve_variables_insitu({"t": "{{s}} {{nope}}"})


class TestWrappersEnableUndefinedVariableWarnings:
    """Both command wrappers turn the warnings on before the command runs."""

    @pytest.fixture(autouse=True)
    def disabled(self, monkeypatch):
        monkeypatch.setattr(var_module, "_UNDEFINED_VARIABLE_WARNINGS", False)

    @staticmethod
    def _run(wrapped) -> list[bool]:
        seen: list[bool] = []
        with pytest.raises(SystemExit):
            wrapped(lambda: seen.append(var_module._UNDEFINED_VARIABLE_WARNINGS))()
        return seen

    def test_main_wrapper(self, monkeypatch):
        import yellowdog_cli.utils.wrapper as wrapper_module

        monkeypatch.setattr(wrapper_module, "set_proxy", lambda: None)
        monkeypatch.setattr(wrapper_module, "CLIENT", MagicMock())
        assert self._run(wrapper_module.main_wrapper) == [True]

    def test_dataclient_wrapper(self):
        from yellowdog_cli.utils.dataclient_wrapper import dataclient_wrapper

        assert self._run(dataclient_wrapper) == [True]


class TestWarnOfUndefinedVariables:
    """
    warn_of_undefined_variables() reports, without substituting, what
    resolve_variables_insitu() would: for data resolved before the warnings
    were enabled, such as the configuration's Worker Pool sections.
    """

    @pytest.fixture(autouse=True)
    def enabled(self, patched_subs, monkeypatch):
        monkeypatch.setattr(var_module, "_UNDEFINED_VARIABLE_WARNINGS", True)
        monkeypatch.setattr(var_module, "_UNDEFINED_VARIABLES_REPORTED", set())
        warning = MagicMock()
        monkeypatch.setattr(var_module, "print_warning", warning)
        return warning

    def test_reports_without_substituting(self, enabled):
        data = {"a": "{{nope}}", "b": "{{myvar}}"}
        var_module.warn_of_undefined_variables(data)
        assert data == {"a": "{{nope}}", "b": "{{myvar}}"}
        [call] = enabled.call_args_list
        assert "'{{nope}}'" in call.args[0] and "'a'" in call.args[0]

    def test_shares_the_once_only_record(self, enabled):
        var_module.resolve_variables_insitu({"a": "{{nope}}"})
        var_module.warn_of_undefined_variables({"b": "{{nope}}"})
        assert enabled.call_count == 1

    def test_nothing_until_enabled(self, enabled, monkeypatch):
        monkeypatch.setattr(var_module, "_UNDEFINED_VARIABLE_WARNINGS", False)
        var_module.warn_of_undefined_variables({"a": "{{nope}}"})
        assert enabled.call_count == 0


class TestFileContentsPasses:
    """
    process_variable_substitutions_in_file_contents() repeats its pass over
    the text until one changes nothing, as the in-situ passes do, with the
    same cap and the same circular-reference check, naming the file. It
    serves User Data, Task Data and 'writeFile' content files, which nothing
    walks afterwards, and the text of a JSON or Jsonnet specification before
    it is parsed -- which for Jsonnet is before it is evaluated, so a chain
    has to be resolved here for the Jsonnet code to compute with its value.
    """

    @pytest.fixture(autouse=True)
    def use_known_subs(self, patched_subs, monkeypatch):
        monkeypatch.setattr(var_module, "ARGS_PARSER", MagicMock(jsonnet_dry_run=False))

    def test_a_chain_resolves(self, monkeypatch):
        _chain_env_vars(monkeypatch, 8)
        var_module.VARIABLE_SUBSTITUTIONS["region"] = "end"
        result = var_module.process_variable_substitutions_in_file_contents(
            "echo {{env:YD_TEST_0}}\n"
        )
        assert result == "echo end\n"

    def test_a_type_tag_revealed_by_a_pass_takes_effect(self, monkeypatch):
        monkeypatch.setenv("YD_TEST_TYPED", "{{num:num_var}}")
        result = var_module.process_variable_substitutions_in_file_contents(
            '{"n": "{{env:YD_TEST_TYPED}}"}'
        )
        assert json.loads(result) == {"n": 42}

    def test_nothing_to_substitute_is_returned_unchanged(self):
        text = "no variables, {{undefined}}, {{missing::}}"
        assert var_module.process_variable_substitutions_in_file_contents(text) == text

    def test_mutually_referring_variables_are_an_error(self, monkeypatch):
        monkeypatch.setenv("YD_TEST_A", "{{env:YD_TEST_B}}")
        monkeypatch.setenv("YD_TEST_B", "{{env:YD_TEST_A}}")
        with pytest.raises(ValueError, match=r"circular.*'setup\.sh'"):
            var_module.process_variable_substitutions_in_file_contents(
                "echo {{env:YD_TEST_A}}", source="setup.sh"
            )

    def test_circular_table_variables_are_an_error(self):
        var_module.add_substitutions_without_overwriting({"s": "{{s}}"})
        with pytest.raises(
            ValueError, match=r"Circular variable reference: 's'.*'setup\.sh'"
        ):
            var_module.process_variable_substitutions_in_file_contents(
                "echo {{s}}", source="setup.sh"
            )

    def test_the_error_names_the_file_contents_without_a_source(self, monkeypatch):
        var_module.add_substitutions_without_overwriting({"s": "{{s}}"})
        with pytest.raises(ValueError, match="Circular"):
            var_module.process_variable_substitutions_in_file_contents("{{s}}")

    def test_only_the_delimiters_being_substituted_are_checked(self):
        var_module.VARIABLE_SUBSTITUTIONS["v"] = "{{v}}"
        text = "echo {{v}} __{{myvar}}__"
        result = var_module.process_variable_substitutions_in_file_contents(
            text, prefix="__", postfix="__"
        )
        assert result == "echo {{v}} hello"

    def test_a_typed_expression_left_for_the_in_situ_pass_is_not_circular(self):
        # Inside a longer string, a type-tagged expression is substituted as
        # text by the in-situ pass, not here
        text = '{"name": "{{num:num_var}}-{{myvar}}"}'
        result = var_module.process_variable_substitutions_in_file_contents(text)
        assert result == '{"name": "{{num:num_var}}-hello"}'

    def test_jsonnet_computes_with_a_chained_value(self, tmp_path, monkeypatch):
        _chain_env_vars(monkeypatch, 4)
        var_module.VARIABLE_SUBSTITUTIONS["region"] = "41"
        path = tmp_path / "spec.jsonnet"
        path.write_text("local n = std.parseInt('{{env:YD_TEST_0}}');\n{x: n + 1}\n")
        assert _load_jsonnet(path) == {"x": 42}

    def test_task_data_file_chain_resolves(self, tmp_path, monkeypatch):
        from yellowdog_cli.utils.property_names import TASK_DATA_FILE
        from yellowdog_cli.utils.submit_utils import resolve_task_data

        _chain_env_vars(monkeypatch, 6)
        var_module.VARIABLE_SUBSTITUTIONS["region"] = "end"
        data = tmp_path / "input.txt"
        data.write_text("{{env:YD_TEST_0}}")
        assert resolve_task_data({TASK_DATA_FILE: str(data)}) == "end"


class TestStringResolution:
    """
    resolve_variables_in_string() is resolve_variables_insitu() for a single
    value: the configuration values and data client paths substituted one at
    a time. It used to be a single process_variable_substitutions() call,
    which stopped a chain after a link and let the undefined-variable warning
    call a defined variable undefined.
    """

    @pytest.fixture(autouse=True)
    def use_known_subs(self, patched_subs):
        pass

    @pytest.fixture()
    def warnings(self, monkeypatch) -> MagicMock:
        monkeypatch.setattr(var_module, "_UNDEFINED_VARIABLE_WARNINGS", True)
        monkeypatch.setattr(var_module, "_UNDEFINED_VARIABLES_REPORTED", set())
        warning = MagicMock()
        monkeypatch.setattr(var_module, "print_warning", warning)
        return warning

    def test_a_chain_resolves(self, monkeypatch):
        _chain_env_vars(monkeypatch, 8)
        var_module.VARIABLE_SUBSTITUTIONS["region"] = "end"
        assert var_module.resolve_variables_in_string("t-{{env:YD_TEST_0}}") == "t-end"

    def test_a_type_tag_revealed_by_a_pass_takes_effect(self, monkeypatch):
        monkeypatch.setenv("YD_TEST_TYPED", "{{num:num_var}}")
        assert var_module.resolve_variables_in_string("{{env:YD_TEST_TYPED}}") == 42

    @pytest.mark.parametrize("value", [None, 7, True, ["{{myvar}}"]])
    def test_a_value_that_is_not_a_string_is_returned_as_it_is(self, value):
        assert var_module.resolve_variables_in_string(value) == value

    def test_the_unset_marker_is_passed_through(self):
        result = var_module.resolve_variables_in_string("{{missing::}}")
        assert result is var_module._UNSET

    def test_mutually_referring_variables_are_an_error(self, monkeypatch):
        monkeypatch.setenv("YD_TEST_A", "{{env:YD_TEST_B}}")
        monkeypatch.setenv("YD_TEST_B", "{{env:YD_TEST_A}}")
        with pytest.raises(ValueError, match=r"did not settle.*'common\.tag'"):
            var_module.resolve_variables_in_string(
                "{{env:YD_TEST_A}}", source="common.tag"
            )

    def test_circular_table_variables_are_an_error(self):
        var_module.add_substitutions_without_overwriting({"s": "{{s}}"})
        with pytest.raises(ValueError, match="Circular variable reference: 's'"):
            var_module.resolve_variables_in_string("{{s}}")

    def test_an_undefined_variable_is_reported_by_its_source(self, warnings):
        var_module.resolve_variables_in_string("x-{{nope}}", source="common.tag")
        [call] = warnings.call_args_list
        assert "'{{nope}}'" in call.args[0] and "'common.tag'" in call.args[0]

    def test_the_source_defaults_to_the_value(self, warnings):
        var_module.resolve_variables_in_string("x/{{nope}}")
        [call] = warnings.call_args_list
        assert "'x/{{nope}}'" in call.args[0]

    def test_a_chained_variable_is_not_reported_as_undefined(
        self, warnings, monkeypatch
    ):
        monkeypatch.setenv("YD_TEST_A", "{{env:YD_TEST_B}}")
        monkeypatch.setenv("YD_TEST_B", "end")
        assert var_module.resolve_variables_in_string("{{env:YD_TEST_A}}") == "end"
        assert warnings.call_count == 0

    def test_no_single_value_substitution_outside_variables_py(self):
        # Every value substituted outside variables.py goes through a
        # resolving call; a bare process_variable_substitutions() brings the
        # one-link chains, and the misreported variables, back
        from pathlib import Path

        import yellowdog_cli

        package = Path(yellowdog_cli.__file__).parent
        callers = [
            str(path.relative_to(package))
            for path in package.rglob("*.py")
            if path.name != "variables.py"
            and "process_variable_substitutions(" in path.read_text()
        ]
        assert callers == []
