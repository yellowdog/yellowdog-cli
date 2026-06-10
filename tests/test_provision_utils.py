"""
Unit tests for provision_utils.py.

Covers:
  - _read_user_data (via get_user_data_property): file reading, concatenation,
    variable substitution, chdir/restore, error handling
  - get_user_data_property: mutex validation, content_path/CONFIG_FILE_DIR selection
  - resolve_user_data_in_spec: mutex validation, no-op cases, spec dict mutation,
    base_dir/CONFIG_FILE_DIR selection
  - get_template_id: YDID passthrough, name lookup, name not found
"""

from unittest.mock import MagicMock, mock_open, patch

import pytest

import yellowdog_cli.utils.provision_utils as pu_module
from yellowdog_cli.utils.provision_utils import (
    get_template_id,
    get_user_data_property,
    resolve_user_data_in_spec,
)
from yellowdog_cli.utils.ydid_utils import YDIDType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    user_data: str | None = None,
    user_data_file: str | None = None,
    user_data_files: list[str] | None = None,
) -> MagicMock:
    config = MagicMock()
    config.user_data = user_data
    config.user_data_file = user_data_file
    config.user_data_files = user_data_files
    return config


def _identity_subs(text, **_kwargs):
    """Variable substitution stub that returns the text unchanged."""
    return text


# ---------------------------------------------------------------------------
# _read_user_data — tested via get_user_data_property (simplest public caller)
# ---------------------------------------------------------------------------


class TestReadUserData:
    """
    Core logic tests for _read_user_data, exercised through
    get_user_data_property so the private function stays private.
    """

    def _call(self, config, content_path=None):
        with (
            patch.object(pu_module, "chdir"),
            patch.object(pu_module, "getcwd", return_value="/original"),
            patch.object(pu_module, "CONFIG_FILE_DIR", "/config/dir"),
            patch.object(
                pu_module,
                "process_variable_substitutions_in_file_contents",
                side_effect=_identity_subs,
            ),
        ):
            return get_user_data_property(config, content_path)

    def test_all_none_returns_none(self):
        assert self._call(_make_config()) is None

    def test_inline_string_returned_after_subs(self):
        config = _make_config(user_data="plain text")
        assert self._call(config) == "plain text"

    def test_variable_substitution_applied(self):
        config = _make_config(user_data="raw")
        with (
            patch.object(pu_module, "chdir"),
            patch.object(pu_module, "getcwd", return_value="/original"),
            patch.object(pu_module, "CONFIG_FILE_DIR", ""),
            patch.object(
                pu_module,
                "process_variable_substitutions_in_file_contents",
                return_value="substituted",
            ),
        ):
            result = get_user_data_property(config)
        assert result == "substituted"

    def test_user_data_file_read_and_returned(self):
        config = _make_config(user_data_file="startup.sh")
        with (
            patch.object(pu_module, "chdir"),
            patch.object(pu_module, "getcwd", return_value="/original"),
            patch.object(pu_module, "CONFIG_FILE_DIR", "/config/dir"),
            patch.object(
                pu_module,
                "process_variable_substitutions_in_file_contents",
                side_effect=_identity_subs,
            ),
            patch("builtins.open", mock_open(read_data="#!/bin/bash\necho hi")),
        ):
            result = get_user_data_property(config)
        assert result == "#!/bin/bash\necho hi"

    def test_user_data_files_concatenated_with_newlines(self):
        config = _make_config(user_data_files=["a.sh", "b.sh"])
        read_mock = mock_open()
        read_mock.return_value.__enter__.return_value.read.side_effect = [
            "content-a",
            "content-b",
        ]
        with (
            patch.object(pu_module, "chdir"),
            patch.object(pu_module, "getcwd", return_value="/original"),
            patch.object(pu_module, "CONFIG_FILE_DIR", "/config/dir"),
            patch.object(
                pu_module,
                "process_variable_substitutions_in_file_contents",
                side_effect=_identity_subs,
            ),
            patch("builtins.open", read_mock),
        ):
            result = get_user_data_property(config)
        assert result == "content-a\ncontent-b\n"

    def test_restores_original_directory_on_file_error(self):
        config = _make_config(user_data_file="missing.sh")
        with (
            patch.object(pu_module, "chdir") as mock_chdir,
            patch.object(pu_module, "getcwd", return_value="/original"),
            patch.object(pu_module, "CONFIG_FILE_DIR", "/config/dir"),
            patch("builtins.open", side_effect=OSError("not found")),
        ):
            with pytest.raises(OSError):
                get_user_data_property(config)
        assert "/original" in [c.args[0] for c in mock_chdir.call_args_list]

    def test_chdir_failure_raises_runtime_error(self):
        config = _make_config(user_data="data")

        def _fail_on_config_dir(path):
            if path == "/config/dir":
                raise OSError("no such dir")

        with (
            patch.object(pu_module, "chdir", side_effect=_fail_on_config_dir),
            patch.object(pu_module, "getcwd", return_value="/original"),
            patch.object(pu_module, "CONFIG_FILE_DIR", "/config/dir"),
        ):
            with pytest.raises(
                RuntimeError, match="Unable to switch to content directory"
            ):
                get_user_data_property(config)


# ---------------------------------------------------------------------------
# get_user_data_property — unique behaviour only
# ---------------------------------------------------------------------------


class TestGetUserDataProperty:
    def test_mutex_raises_value_error(self):
        config = _make_config(user_data="inline", user_data_file="file.sh")
        with pytest.raises(ValueError, match="Only one of"):
            get_user_data_property(config)

    def test_content_path_used_for_chdir_when_provided(self):
        config = _make_config(user_data="data")
        with (
            patch.object(pu_module, "chdir") as mock_chdir,
            patch.object(pu_module, "getcwd", return_value="/original"),
            patch.object(pu_module, "CONFIG_FILE_DIR", "/config/dir"),
            patch.object(
                pu_module,
                "process_variable_substitutions_in_file_contents",
                side_effect=_identity_subs,
            ),
        ):
            get_user_data_property(config, content_path="/custom/path")
        assert "/custom/path" in [c.args[0] for c in mock_chdir.call_args_list]

    def test_config_file_dir_used_when_no_content_path(self):
        config = _make_config(user_data="data")
        with (
            patch.object(pu_module, "chdir") as mock_chdir,
            patch.object(pu_module, "getcwd", return_value="/original"),
            patch.object(pu_module, "CONFIG_FILE_DIR", "/config/dir"),
            patch.object(
                pu_module,
                "process_variable_substitutions_in_file_contents",
                side_effect=_identity_subs,
            ),
        ):
            get_user_data_property(config)
        assert "/config/dir" in [c.args[0] for c in mock_chdir.call_args_list]


# ---------------------------------------------------------------------------
# resolve_user_data_in_spec — unique behaviour only
# ---------------------------------------------------------------------------


class TestResolveUserDataInSpec:
    def _call(self, spec, base_dir=None):
        with (
            patch.object(pu_module, "chdir"),
            patch.object(pu_module, "getcwd", return_value="/original"),
            patch.object(pu_module, "CONFIG_FILE_DIR", "/config/dir"),
            patch.object(
                pu_module,
                "process_variable_substitutions_in_file_contents",
                side_effect=_identity_subs,
            ),
        ):
            resolve_user_data_in_spec(spec, base_dir)

    def test_mutex_raises_value_error(self):
        with pytest.raises(ValueError, match="Only one of"):
            self._call({"userData": "x", "userDataFile": "a.sh"})

    def test_all_absent_is_noop(self):
        spec = {"name": "src", "region": "eu-west-1"}
        self._call(spec)
        assert spec == {"name": "src", "region": "eu-west-1"}

    def test_inline_user_data_is_noop(self):
        spec = {"userData": "#!/bin/bash\necho hi"}
        self._call(spec)
        assert spec == {"userData": "#!/bin/bash\necho hi"}

    def test_user_data_file_replaced_with_user_data(self):
        spec = {"name": "src", "userDataFile": "s.sh"}
        with (
            patch.object(pu_module, "chdir"),
            patch.object(pu_module, "getcwd", return_value="/original"),
            patch.object(pu_module, "CONFIG_FILE_DIR", "/config/dir"),
            patch.object(
                pu_module,
                "process_variable_substitutions_in_file_contents",
                side_effect=_identity_subs,
            ),
            patch("builtins.open", mock_open(read_data="script content")),
        ):
            resolve_user_data_in_spec(spec)
        assert spec == {"name": "src", "userData": "script content"}

    def test_user_data_files_replaced_with_user_data(self):
        spec = {"userDataFiles": ["a.sh", "b.sh"]}
        read_mock = mock_open()
        read_mock.return_value.__enter__.return_value.read.side_effect = ["aa", "bb"]
        with (
            patch.object(pu_module, "chdir"),
            patch.object(pu_module, "getcwd", return_value="/original"),
            patch.object(pu_module, "CONFIG_FILE_DIR", "/config/dir"),
            patch.object(
                pu_module,
                "process_variable_substitutions_in_file_contents",
                side_effect=_identity_subs,
            ),
            patch("builtins.open", read_mock),
        ):
            resolve_user_data_in_spec(spec)
        assert spec == {"userData": "aa\nbb\n"}

    def test_base_dir_used_for_chdir_when_provided(self):
        spec = {"userDataFile": "s.sh"}
        with (
            patch.object(pu_module, "chdir") as mock_chdir,
            patch.object(pu_module, "getcwd", return_value="/original"),
            patch.object(pu_module, "CONFIG_FILE_DIR", "/config/dir"),
            patch.object(
                pu_module,
                "process_variable_substitutions_in_file_contents",
                side_effect=_identity_subs,
            ),
            patch("builtins.open", mock_open(read_data="x")),
        ):
            resolve_user_data_in_spec(spec, base_dir="/custom/base")
        assert "/custom/base" in [c.args[0] for c in mock_chdir.call_args_list]

    def test_config_file_dir_used_when_no_base_dir(self):
        spec = {"userDataFile": "s.sh"}
        with (
            patch.object(pu_module, "chdir") as mock_chdir,
            patch.object(pu_module, "getcwd", return_value="/original"),
            patch.object(pu_module, "CONFIG_FILE_DIR", "/config/dir"),
            patch.object(
                pu_module,
                "process_variable_substitutions_in_file_contents",
                side_effect=_identity_subs,
            ),
            patch("builtins.open", mock_open(read_data="x")),
        ):
            resolve_user_data_in_spec(spec)
        assert "/config/dir" in [c.args[0] for c in mock_chdir.call_args_list]


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
            with pytest.raises(KeyError, match="not found"):
                get_template_id(client, "nonexistent-template")
