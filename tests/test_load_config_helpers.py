"""
Unit tests for load_config.py helpers not already covered by other test files.

Already covered elsewhere:
  - _parse_property_value / _apply_property_overrides → test_property_overrides.py
  - _build_dc_substitutions                          → test_build_dc_substitutions.py
  - _select_dc_section                               → test_select_dc_section.py

Covers here:
  - _load_namespace_and_tag: CLI > env var > TOML [common] > default priority chain
  - load_config_common: CLI > env var > TOML precedence
  - load_config_work_requirement: no section, basic fields, CLI overrides, csv conflict
"""

import os
from unittest.mock import MagicMock, patch

import pytest

import yellowdog_cli.utils.load_config as lc_module
from yellowdog_cli.utils.config_types import ConfigWorkRequirement
from yellowdog_cli.utils.load_config import (
    _load_namespace_and_tag,
    load_config_common,
    load_config_work_requirement,
)
from yellowdog_cli.utils.property_names import (
    COMMON_SECTION,
    CSV_FILE,
    CSV_FILES,
    KEY,
    NAME_TAG,
    NAMESPACE,
    PRIORITY,
    SECRET,
    TASK_BATCH_SIZE,
    TASK_COUNT,
    TASK_GROUP_COUNT,
    TASK_TYPE,
    WORK_REQUIREMENT_SECTION,
)
from yellowdog_cli.utils.settings import (
    TASK_BATCH_SIZE_DEFAULT,
    YD_KEY,
    YD_NAMESPACE,
    YD_SECRET,
    YD_TAG,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_args(
    namespace=None,
    tag=None,
    task_type=None,
    task_batch_size=None,
    task_count=None,
    task_group_count=None,
):
    args = MagicMock()
    args.namespace = namespace
    args.tag = tag
    args.task_type = task_type
    args.task_batch_size = task_batch_size
    args.task_count = task_count
    args.task_group_count = task_group_count
    return args


# ---------------------------------------------------------------------------
# _load_namespace_and_tag
# ---------------------------------------------------------------------------


class TestLoadNamespaceAndTag:
    """
    Tests for the namespace/tag priority chain in _load_namespace_and_tag.
    Priority: CLI flag > env var > TOML [common] section > default.
    """

    def _call(self, toml_common=None, args=None, env=None):
        """
        Call _load_namespace_and_tag in a controlled environment.

        Uses clear=True on patch.dict so only the explicitly supplied env keys
        are present — this ensures YD_NAMESPACE/YD_TAG from the real environment
        cannot leak into the test.

        Returns the subs dict that was passed to add_substitutions_without_overwriting.
        """
        if toml_common is None:
            toml_common = {}
        if args is None:
            args = _mock_args()
        if env is None:
            env = {}

        captured = {}

        def capture_subs(subs):
            captured.update(subs)

        with (
            patch.object(lc_module, "CONFIG_TOML", {COMMON_SECTION: toml_common}),
            patch.object(lc_module, "ARGS_PARSER", args),
            patch.dict(os.environ, env, clear=True),
            patch.object(
                lc_module,
                "process_variable_substitutions",
                side_effect=lambda x: x,
            ),
            patch.object(
                lc_module,
                "add_substitutions_without_overwriting",
                side_effect=capture_subs,
            ),
        ):
            _load_namespace_and_tag()

        return captured

    # --- namespace ---

    def test_cli_namespace_beats_toml(self):
        subs = self._call(
            toml_common={NAMESPACE: "toml-ns"},
            args=_mock_args(namespace="cli-ns"),
        )
        assert subs[NAMESPACE] == "cli-ns"

    def test_cli_namespace_beats_env_var(self):
        subs = self._call(
            args=_mock_args(namespace="cli-ns"),
            env={YD_NAMESPACE: "env-ns"},
        )
        assert subs[NAMESPACE] == "cli-ns"

    def test_env_var_namespace_beats_toml(self):
        subs = self._call(
            toml_common={NAMESPACE: "toml-ns"},
            env={YD_NAMESPACE: "env-ns"},
        )
        assert subs[NAMESPACE] == "env-ns"

    def test_toml_namespace_beats_default(self):
        subs = self._call(toml_common={NAMESPACE: "toml-ns"})
        assert subs[NAMESPACE] == "toml-ns"

    def test_env_var_namespace_beats_default(self):
        subs = self._call(env={YD_NAMESPACE: "env-ns"})
        assert subs[NAMESPACE] == "env-ns"

    def test_default_namespace_is_default(self):
        subs = self._call()
        assert subs[NAMESPACE] == "default"

    # --- tag ---

    def test_cli_tag_beats_toml(self):
        subs = self._call(
            toml_common={NAME_TAG: "toml-tag"},
            args=_mock_args(tag="cli-tag"),
        )
        assert subs[NAME_TAG] == "cli-tag"

    def test_cli_tag_beats_env_var(self):
        subs = self._call(
            args=_mock_args(tag="cli-tag"),
            env={YD_TAG: "env-tag"},
        )
        assert subs[NAME_TAG] == "cli-tag"

    def test_env_var_tag_beats_toml(self):
        subs = self._call(
            toml_common={NAME_TAG: "toml-tag"},
            env={YD_TAG: "env-tag"},
        )
        assert subs[NAME_TAG] == "env-tag"

    def test_toml_tag_beats_default(self):
        subs = self._call(toml_common={NAME_TAG: "toml-tag"})
        assert subs[NAME_TAG] == "toml-tag"

    def test_env_var_tag_beats_default(self):
        subs = self._call(env={YD_TAG: "env-tag"})
        assert subs[NAME_TAG] == "env-tag"

    def test_default_tag_is_username_placeholder(self):
        subs = self._call()
        assert subs[NAME_TAG] == "{{username}}"

    def test_both_namespace_and_tag_resolved_together(self):
        subs = self._call(args=_mock_args(namespace="my-ns", tag="my-tag"))
        assert subs[NAMESPACE] == "my-ns"
        assert subs[NAME_TAG] == "my-tag"


# ---------------------------------------------------------------------------
# load_config_common
# ---------------------------------------------------------------------------


class TestLoadConfigCommonPrecedence:
    """
    load_config_common applies CLI > env var > TOML precedence for
    key/secret/namespace/tag/url.
    """

    def _call(self, toml_common=None, args=None, env=None):
        if toml_common is None:
            toml_common = {KEY: "toml-key", SECRET: "toml-secret"}
        if args is None:
            args = _common_mock_args()
        if env is None:
            env = {}

        with (
            patch.object(lc_module, "CONFIG_TOML", {COMMON_SECTION: toml_common}),
            patch.object(lc_module, "ARGS_PARSER", args),
            patch.dict(os.environ, env, clear=True),
            patch.object(
                lc_module,
                "process_variable_substitutions",
                side_effect=lambda x: x,
            ),
            patch.object(lc_module, "add_substitutions_without_overwriting"),
            patch.object(lc_module, "register_dc_substitutions"),
        ):
            return load_config_common()

    def test_env_namespace_beats_toml(self):
        config = self._call(
            toml_common={KEY: "k", SECRET: "s", NAMESPACE: "toml-ns"},
            env={YD_NAMESPACE: "env-ns"},
        )
        assert config.namespace == "env-ns"

    def test_cli_namespace_beats_env_and_toml(self):
        config = self._call(
            toml_common={KEY: "k", SECRET: "s", NAMESPACE: "toml-ns"},
            args=_common_mock_args(namespace="cli-ns"),
            env={YD_NAMESPACE: "env-ns"},
        )
        assert config.namespace == "cli-ns"

    def test_toml_namespace_used_when_no_env_or_cli(self):
        config = self._call(toml_common={KEY: "k", SECRET: "s", NAMESPACE: "toml-ns"})
        assert config.namespace == "toml-ns"

    def test_env_tag_beats_toml(self):
        config = self._call(
            toml_common={KEY: "k", SECRET: "s", NAME_TAG: "toml-tag"},
            env={YD_TAG: "env-tag"},
        )
        assert config.name_tag == "env-tag"

    def test_env_key_and_secret_beat_toml(self):
        config = self._call(
            toml_common={KEY: "toml-key", SECRET: "toml-secret"},
            env={YD_KEY: "env-key", YD_SECRET: "env-secret"},
        )
        assert config.key == "env-key"
        assert config.secret == "env-secret"


def _common_mock_args(namespace=None, tag=None):
    args = MagicMock()
    args.key = None
    args.secret = None
    args.namespace = namespace
    args.tag = tag
    args.url = None
    args.use_pac = None
    args.namespace_required = False
    args.tag_required = False
    return args


# ---------------------------------------------------------------------------
# load_config_work_requirement
# ---------------------------------------------------------------------------


class TestLoadConfigWorkRequirement:
    """
    Tests for load_config_work_requirement.
    """

    def _call(self, toml_wr_section=None, args=None):
        """
        Call load_config_work_requirement with a controlled CONFIG_TOML dict
        and ARGS_PARSER.  Variable substitutions are no-ops so TOML values
        pass through unchanged.
        """
        if args is None:
            args = _mock_args()
        config_toml = (
            {}
            if toml_wr_section is None
            else {WORK_REQUIREMENT_SECTION: toml_wr_section}
        )

        with (
            patch.object(lc_module, "CONFIG_TOML", config_toml),
            patch.object(lc_module, "ARGS_PARSER", args),
            patch.object(lc_module, "process_variable_substitutions_insitu"),
            patch.object(
                lc_module,
                "process_variable_substitutions",
                side_effect=lambda x: x,
            ),
            patch.object(
                lc_module,
                "pathname_relative_to_config_file",
                side_effect=lambda base, path: path,
            ),
        ):
            return load_config_work_requirement()

    # --- no section ---

    def test_no_wr_section_returns_default_config(self):
        result = self._call()
        assert isinstance(result, ConfigWorkRequirement)
        assert result.task_count == 1
        assert result.task_group_count == 1
        assert result.task_batch_size == TASK_BATCH_SIZE_DEFAULT
        assert result.task_type is None
        assert result.csv_files is None

    # --- basic TOML fields ---

    def test_task_count_from_toml(self):
        result = self._call(toml_wr_section={TASK_COUNT: 5})
        assert result.task_count == 5

    def test_task_group_count_from_toml(self):
        result = self._call(toml_wr_section={TASK_GROUP_COUNT: 3})
        assert result.task_group_count == 3

    def test_priority_from_toml(self):
        result = self._call(toml_wr_section={PRIORITY: 0.75})
        assert result.priority == pytest.approx(0.75)

    def test_task_batch_size_from_toml(self):
        result = self._call(toml_wr_section={TASK_BATCH_SIZE: 50})
        assert result.task_batch_size == 50

    def test_task_type_from_toml(self):
        result = self._call(toml_wr_section={TASK_TYPE: "docker"})
        assert result.task_type == "docker"

    # --- CLI overrides ---

    def test_cli_task_type_overrides_toml(self):
        result = self._call(
            toml_wr_section={TASK_TYPE: "bash"},
            args=_mock_args(task_type="docker"),
        )
        assert result.task_type == "docker"

    def test_cli_task_batch_size_overrides_toml(self):
        result = self._call(
            toml_wr_section={TASK_BATCH_SIZE: 10},
            args=_mock_args(task_batch_size=200),
        )
        assert result.task_batch_size == 200

    def test_cli_task_count_overrides_toml(self):
        result = self._call(
            toml_wr_section={TASK_COUNT: 3},
            args=_mock_args(task_count=99),
        )
        assert result.task_count == 99

    def test_cli_task_group_count_overrides_toml(self):
        result = self._call(
            toml_wr_section={TASK_GROUP_COUNT: 2},
            args=_mock_args(task_group_count=7),
        )
        assert result.task_group_count == 7

    def test_cli_none_leaves_toml_value_in_place(self):
        result = self._call(
            toml_wr_section={TASK_COUNT: 42},
            args=_mock_args(task_count=None),
        )
        assert result.task_count == 42

    # --- csvFile / csvFiles ---

    def test_csv_file_promoted_to_csv_files_list(self):
        result = self._call(toml_wr_section={CSV_FILE: "data.csv"})
        assert result.csv_files == ["data.csv"]

    def test_csv_files_list_passed_through(self):
        result = self._call(toml_wr_section={CSV_FILES: ["a.csv", "b.csv"]})
        assert result.csv_files == ["a.csv", "b.csv"]

    def test_neither_csv_option_leaves_csv_files_none(self):
        result = self._call(toml_wr_section={})
        assert result.csv_files is None

    def test_csv_file_and_csv_files_both_set_exits(self):
        with (
            patch.object(lc_module, "print_error"),
            pytest.raises(SystemExit),
        ):
            self._call(toml_wr_section={CSV_FILE: "x.csv", CSV_FILES: ["a.csv"]})
