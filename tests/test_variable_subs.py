"""
Unit tests for yellowdog_cli.utils.variables

Tests cover process_typed_variable_substitution (pure, no global state)
and process_variable_substitutions / process_variable_substitutions_in_file_contents
(require patching the VARIABLE_SUBSTITUTIONS global).
"""

import pytest

import yellowdog_cli.utils.variables as var_module
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
