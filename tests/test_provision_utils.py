"""
Unit tests for provision_utils.py.

Covers:
  - _read_user_data (via get_user_data_property): file reading, concatenation,
    variable substitution, files found from the content directory without
    changing the working directory, the properties type-checked, a missing
    file named with where it was looked for
  - get_user_data_property: mutex validation, content_path/CONFIG_FILE_DIR selection
  - resolve_user_data_in_spec: mutex validation, no-op cases, spec dict mutation,
    base_dir/CONFIG_FILE_DIR selection
  - get_template_id: YDID passthrough, name lookup, name not found
"""

import os
from unittest.mock import MagicMock, patch

import pytest

import yellowdog_cli.utils.provision_utils as pu_module
from yellowdog_cli.utils.exit_codes import NotFoundError
from yellowdog_cli.utils.provision_utils import (
    get_template_id,
    get_user_data_property,
    resolve_user_data_in_spec,
    shown_value,
)
from yellowdog_cli.utils.ydid_utils import YDIDType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    user_data: object = None,
    user_data_file: object = None,
    user_data_files: object = None,
) -> MagicMock:
    config = MagicMock()
    config.user_data = user_data
    config.user_data_file = user_data_file
    config.user_data_files = user_data_files
    return config


def _identity_subs(text, **_kwargs):
    """Variable substitution stub that returns the text unchanged."""
    return text


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    """
    A configuration directory and a content directory, each holding a
    script, and the substitution stubbed to change nothing.
    """
    config_dir = tmp_path / "config"
    content_dir = tmp_path / "content"
    for directory in (config_dir, content_dir):
        directory.mkdir()
        (directory / "a.sh").write_text(f"a in {directory.name}", encoding="utf-8")
        (directory / "b.sh").write_text(f"b in {directory.name}", encoding="utf-8")
    monkeypatch.setattr(pu_module, "config_file_dir", lambda: str(config_dir))
    monkeypatch.setattr(
        pu_module,
        "process_variable_substitutions_in_file_contents",
        _identity_subs,
    )
    return config_dir, content_dir


# ---------------------------------------------------------------------------
# _read_user_data — tested via get_user_data_property (simplest public caller)
# ---------------------------------------------------------------------------


class TestReadUserData:
    def test_all_none_returns_none(self, dirs):
        assert get_user_data_property(_make_config()) is None

    def test_inline_string_returned_after_subs(self, dirs):
        assert get_user_data_property(_make_config(user_data="plain")) == "plain"

    def test_variable_substitution_applied(self, dirs):
        with patch.object(
            pu_module,
            "process_variable_substitutions_in_file_contents",
            return_value="substituted",
        ):
            result = get_user_data_property(_make_config(user_data="raw"))
        assert result == "substituted"

    def test_user_data_file_read_from_the_config_directory(self, dirs):
        assert (
            get_user_data_property(_make_config(user_data_file="a.sh")) == "a in config"
        )

    def test_user_data_files_concatenated_with_newlines(self, dirs):
        config = _make_config(user_data_files=["a.sh", "b.sh"])
        assert get_user_data_property(config) == "a in config\nb in config\n"

    def test_an_absolute_path_is_itself(self, dirs):
        _, content_dir = dirs
        config = _make_config(user_data_file=str(content_dir / "a.sh"))
        assert get_user_data_property(config) == "a in content"

    def test_the_working_directory_is_never_changed(self, dirs, monkeypatch):
        monkeypatch.setattr(os, "chdir", MagicMock(side_effect=AssertionError))
        assert get_user_data_property(_make_config(user_data_file="a.sh"))

    def test_a_missing_file_names_where_it_was_looked_for(self, dirs):
        config_dir, _ = dirs
        with pytest.raises(FileNotFoundError, match="looked for at") as raised:
            get_user_data_property(_make_config(user_data_file="missing.sh"))
        assert str(config_dir / "missing.sh") in str(raised.value)

    def test_user_data_files_must_be_a_list(self, dirs):
        with pytest.raises(Exception, match="userDataFiles"):
            get_user_data_property(_make_config(user_data_files="a.sh"))

    def test_user_data_file_must_be_a_string(self, dirs):
        with pytest.raises(Exception, match="userDataFile"):
            get_user_data_property(_make_config(user_data_file=["a.sh"]))

    def test_a_substitution_failure_names_the_file_and_keeps_its_cause(self, dirs):
        error = ValueError("circular")
        with patch.object(
            pu_module,
            "process_variable_substitutions_in_file_contents",
            side_effect=error,
        ):
            with pytest.raises(RuntimeError, match=r"in 'a\.sh'") as raised:
                get_user_data_property(_make_config(user_data_file="a.sh"))
        assert raised.value.__cause__ is error


# ---------------------------------------------------------------------------
# get_user_data_property — unique behaviour only
# ---------------------------------------------------------------------------


class TestGetUserDataProperty:
    def test_mutex_raises_value_error(self):
        config = _make_config(user_data="inline", user_data_file="file.sh")
        with pytest.raises(ValueError, match="Only one of"):
            get_user_data_property(config)

    def test_content_path_used_when_provided(self, dirs):
        _, content_dir = dirs
        config = _make_config(user_data_file="a.sh")
        assert get_user_data_property(config, str(content_dir)) == "a in content"

    def test_config_file_dir_used_when_no_content_path(self, dirs):
        config = _make_config(user_data_file="a.sh")
        assert get_user_data_property(config, "") == "a in config"


# ---------------------------------------------------------------------------
# resolve_user_data_in_spec — unique behaviour only
# ---------------------------------------------------------------------------


class TestResolveUserDataInSpec:
    def test_mutex_raises_value_error(self, dirs):
        with pytest.raises(ValueError, match="Only one of"):
            resolve_user_data_in_spec({"userData": "x", "userDataFile": "a.sh"})

    def test_all_absent_is_noop(self, dirs):
        spec = {"name": "src", "region": "eu-west-1"}
        resolve_user_data_in_spec(spec)
        assert spec == {"name": "src", "region": "eu-west-1"}

    def test_inline_user_data_is_noop(self, dirs):
        spec = {"userData": "#!/bin/bash\necho hi"}
        resolve_user_data_in_spec(spec)
        assert spec == {"userData": "#!/bin/bash\necho hi"}

    def test_user_data_file_replaced_with_user_data(self, dirs):
        spec = {"name": "src", "userDataFile": "a.sh"}
        resolve_user_data_in_spec(spec)
        assert spec == {"name": "src", "userData": "a in config"}

    def test_user_data_files_replaced_with_user_data(self, dirs):
        spec = {"userDataFiles": ["a.sh", "b.sh"]}
        resolve_user_data_in_spec(spec)
        assert spec == {"userData": "a in config\nb in config\n"}

    def test_base_dir_used_when_provided(self, dirs):
        _, content_dir = dirs
        spec = {"userDataFile": "a.sh"}
        resolve_user_data_in_spec(spec, base_dir=str(content_dir))
        assert spec == {"userData": "a in content"}

    def test_user_data_files_in_a_specification_must_be_a_list(self, dirs):
        with pytest.raises(Exception, match="userDataFiles"):
            resolve_user_data_in_spec({"userDataFiles": "a.sh"})


# ---------------------------------------------------------------------------
# get_template_id
# ---------------------------------------------------------------------------


class TestGetTemplateId:
    def test_ydid_passthrough_no_lookup(self):
        ydid = "ydid:crt:test:abc123"
        client = MagicMock()
        with (
            patch.object(
                pu_module,
                "get_ydid_type",
                return_value=YDIDType.COMPUTE_REQUIREMENT_TEMPLATE,
            ),
            patch.object(
                pu_module, "get_compute_requirement_template_id_by_name"
            ) as mock_lookup,
        ):
            result = get_template_id(client, ydid)
        assert result == ydid
        mock_lookup.assert_not_called()

    def test_name_triggers_lookup_and_returns_id(self):
        client = MagicMock()
        with (
            patch.object(pu_module, "get_ydid_type", return_value=None),
            patch.object(
                pu_module,
                "get_compute_requirement_template_id_by_name",
                return_value="ydid:crt:test:resolved",
            ),
            patch.object(pu_module, "print_info"),
        ):
            result = get_template_id(client, "my-template")
        assert result == "ydid:crt:test:resolved"

    def test_name_not_found_raises_key_error(self):
        client = MagicMock()
        with (
            patch.object(pu_module, "get_ydid_type", return_value=None),
            patch.object(
                pu_module,
                "get_compute_requirement_template_id_by_name",
                return_value=None,
            ),
        ):
            with pytest.raises(NotFoundError, match="not found"):
                get_template_id(client, "nonexistent-template")


# ---------------------------------------------------------------------------
# shown_value
# ---------------------------------------------------------------------------


class TestShownValue:
    @pytest.mark.parametrize(
        "value, shown",
        [
            ("ydid:crt:x", "ydid:crt:x"),
            (False, "false"),
            (3, "3"),
            (
                {"enabled": True, "timeout": "PT5M"},
                '{"enabled": true, "timeout": "PT5M"}',
            ),
            ({"team": "a"}, '{"team": "a"}'),
        ],
    )
    def test_strings_as_they_are_anything_else_as_json(self, value, shown):
        assert shown_value(value) == shown
