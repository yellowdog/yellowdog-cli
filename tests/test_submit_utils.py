"""
Unit tests for the functions moved from submit.py to submit_utils.py:
  formatted_number_str, get_task_name, get_task_group_name,
  get_task_data_property, create_task
"""

from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import yellowdog_cli.utils.submit_utils as su
from yellowdog_cli.utils.config_types import ConfigWorkRequirement
from yellowdog_cli.utils.property_names import (
    TASK_DATA,
    TASK_DATA_FILE,
    TASK_DATA_FILES,
    TASK_GROUPS,
    TASK_TAG,
    TASKS,
)
from yellowdog_cli.utils.settings import VAR_CLOSING_DELIMITER, VAR_OPENING_DELIMITER

# Convenience aliases for lazy-substitution placeholder tokens
_TN = f"{VAR_OPENING_DELIMITER}{su.L_TASK_NUMBER}{VAR_CLOSING_DELIMITER}"
_TC = f"{VAR_OPENING_DELIMITER}{su.L_TASK_COUNT}{VAR_CLOSING_DELIMITER}"
_TGN = f"{VAR_OPENING_DELIMITER}{su.L_TASK_GROUP_NUMBER}{VAR_CLOSING_DELIMITER}"
_TGC = f"{VAR_OPENING_DELIMITER}{su.L_TASK_GROUP_COUNT}{VAR_CLOSING_DELIMITER}"
_TGNM = f"{VAR_OPENING_DELIMITER}{su.L_TASK_GROUP_NAME}{VAR_CLOSING_DELIMITER}"


# ---------------------------------------------------------------------------
# formatted_number_str
# ---------------------------------------------------------------------------


class TestFormattedNumberStr:
    def test_single_digit_total_no_padding(self):
        # 1 item total → "1" (no padding needed)
        assert su.formatted_number_str(0, 1) == "1"

    def test_zero_indexed_adds_one(self):
        # zero_indexed=True (default): returns current+1; total=5 → width 1
        assert su.formatted_number_str(4, 5) == "5"

    def test_one_indexed_no_addition(self):
        # zero_indexed=False: no +1 offset; total=9 → width 1
        assert su.formatted_number_str(5, 9, zero_indexed=False) == "5"

    def test_zero_padded_to_match_total_width(self):
        # num_items=100 → width 3; item 0 → "001"
        assert su.formatted_number_str(0, 100) == "001"

    def test_last_item_matches_total(self):
        assert su.formatted_number_str(99, 100) == "100"

    def test_single_item(self):
        assert su.formatted_number_str(0, 1) == "1"

    def test_width_matches_total_digits(self):
        # Total 999 → 3-digit width; item 9 → "010"
        assert su.formatted_number_str(9, 999) == "010"


# ---------------------------------------------------------------------------
# get_task_name
# ---------------------------------------------------------------------------


class TestGetTaskName:
    def test_name_none_set_task_names_false_returns_none(self):
        result = su.get_task_name(None, False, 0, 5, 0, 1, "grp")
        assert result is None

    def test_name_none_set_task_names_true_returns_auto_name(self):
        result = su.get_task_name(None, True, 0, 5, 0, 1, "grp")
        assert result == "task_1"

    def test_auto_name_zero_padded(self):
        # 10 tasks → width 2; task 0 → "task_01"
        result = su.get_task_name(None, True, 0, 10, 0, 1, "grp")
        assert result == "task_01"

    def test_explicit_name_returned_unchanged_when_no_placeholders(self):
        result = su.get_task_name("my-task", True, 0, 5, 0, 1, "grp")
        assert result == "my-task"

    def test_task_number_placeholder_substituted(self):
        # 10 tasks → width 2; task 2 (zero-indexed) → "03"
        result = su.get_task_name(f"job-{_TN}", True, 2, 10, 0, 1, "grp")
        assert result == "job-03"

    def test_task_count_placeholder_substituted(self):
        result = su.get_task_name(f"of-{_TC}", True, 0, 7, 0, 1, "grp")
        assert result == "of-7"

    def test_task_group_number_placeholder(self):
        result = su.get_task_name(f"tg-{_TGN}", True, 0, 1, 1, 5, "grp")
        assert result == "tg-2"

    def test_task_group_count_placeholder(self):
        result = su.get_task_name(f"cnt-{_TGC}", True, 0, 1, 0, 3, "grp")
        assert result == "cnt-3"

    def test_task_group_name_placeholder(self):
        result = su.get_task_name(f"name-{_TGNM}", True, 0, 1, 0, 1, "alpha")
        assert result == "name-alpha"

    def test_multiple_placeholders_in_one_name(self):
        # tg 1 of 5 → "2"; task 2 of 10 → "03"
        result = su.get_task_name(f"{_TGN}-{_TN}", True, 2, 10, 1, 5, "grp")
        assert result == "2-03"


# ---------------------------------------------------------------------------
# double_range_from_list
# ---------------------------------------------------------------------------


class TestDoubleRangeFromList:
    def test_none_returns_none(self):
        assert su.double_range_from_list(None, "vcpus") is None

    def test_both_bounds_set(self):
        result = su.double_range_from_list([2.0, 4.0], "vcpus")
        assert result is not None
        assert result.min == 2.0
        assert result.max == 4.0

    def test_integers_coerced_to_float(self):
        result = su.double_range_from_list([2, 4], "vcpus")
        assert result is not None
        assert result.min == 2.0
        assert result.max == 4.0
        assert isinstance(result.min, float)
        assert isinstance(result.max, float)

    def test_no_upper_limit(self):
        result = su.double_range_from_list([2.0, None], "vcpus")
        assert result is not None
        assert result.min == 2.0
        assert result.max is None

    def test_no_lower_limit(self):
        result = su.double_range_from_list([None, 4.0], "ram")
        assert result is not None
        assert result.min is None
        assert result.max == 4.0

    def test_both_bounds_none_returns_none(self):
        # Both bounds unset means no constraint, equivalent to omitting it
        assert su.double_range_from_list([None, None], "ram") is None

    def test_both_bounds_none_string_returns_none(self):
        assert su.double_range_from_list(["none", "null"], "ram") is None

    def test_none_string_sentinel_no_upper_limit(self):
        # TOML has no null literal, so "none" stands in for an unset bound
        result = su.double_range_from_list([2.0, "none"], "vcpus")
        assert result is not None
        assert result.min == 2.0
        assert result.max is None

    def test_none_string_sentinel_no_lower_limit(self):
        result = su.double_range_from_list(["none", 4.0], "ram")
        assert result is not None
        assert result.min is None
        assert result.max == 4.0

    def test_none_string_case_insensitive(self):
        result = su.double_range_from_list([" NONE ", 4.0], "vcpus")
        assert result is not None
        assert result.min is None
        assert result.max == 4.0

    def test_wrong_length_raises(self):
        with pytest.raises(ValueError, match="list of two values"):
            su.double_range_from_list([2.0], "vcpus")

    def test_too_many_values_raises(self):
        with pytest.raises(ValueError, match="list of two values"):
            su.double_range_from_list([1.0, 2.0, 3.0], "vcpus")

    def test_non_numeric_bound_raises(self):
        with pytest.raises(ValueError, match="must be a number"):
            su.double_range_from_list(["x", 4.0], "vcpus")

    def test_bool_bound_rejected(self):
        with pytest.raises(ValueError, match="must be a number"):
            su.double_range_from_list([True, 4.0], "vcpus")

    def test_non_list_raises(self):
        with pytest.raises(TypeError):
            su.double_range_from_list("2.0,4.0", "vcpus")


# ---------------------------------------------------------------------------
# get_task_group_name
# ---------------------------------------------------------------------------


class TestGetTaskGroupName:
    def test_no_name_returns_auto_name(self):
        result = su.get_task_group_name(None, 0, 3, 10)
        assert result == "task_group_1"

    def test_auto_name_zero_padded(self):
        # 10 groups → width 2; group 0 → "task_group_01"
        result = su.get_task_group_name(None, 0, 10, 5)
        assert result == "task_group_01"

    def test_explicit_name_no_placeholders(self):
        result = su.get_task_group_name("batch", 0, 3, 10)
        assert result == "batch"

    def test_group_number_placeholder(self):
        result = su.get_task_group_name(f"g{_TGN}", 2, 5, 10)
        assert result == "g3"

    def test_group_count_placeholder(self):
        result = su.get_task_group_name(f"of{_TGC}", 0, 4, 10)
        assert result == "of4"

    def test_task_count_placeholder(self):
        result = su.get_task_group_name(f"tasks{_TC}", 0, 1, 99)
        assert result == "tasks99"

    def test_multiple_placeholders(self):
        result = su.get_task_group_name(f"{_TGN}-of-{_TGC}", 1, 3, 10)
        assert result == "2-of-3"


# ---------------------------------------------------------------------------
# resolve_task_data
# ---------------------------------------------------------------------------


class TestResolveTaskData:
    def test_returns_none_when_nothing_set(self):
        assert su.resolve_task_data({}) is None

    def test_returns_task_data_string(self):
        assert su.resolve_task_data({TASK_DATA: "hello"}) == "hello"

    def test_reads_task_data_file(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("from-file")
        assert su.resolve_task_data({TASK_DATA_FILE: str(f)}) == "from-file"

    def test_raises_when_both_set(self):
        with pytest.raises(ValueError, match="Only one of"):
            su.resolve_task_data({TASK_DATA: "x", TASK_DATA_FILE: "f.txt"})

    def test_raises_when_task_data_and_files_both_set(self):
        with pytest.raises(ValueError, match="Only one of"):
            su.resolve_task_data({TASK_DATA: "x", TASK_DATA_FILES: ["f.txt"]})

    def test_raises_when_task_data_file_and_files_both_set(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("a")
        with pytest.raises(ValueError, match="Only one of"):
            su.resolve_task_data({TASK_DATA_FILE: str(f), TASK_DATA_FILES: [str(f)]})

    def test_concatenates_task_data_files(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f1.write_text("hello")
        f2 = tmp_path / "b.txt"
        f2.write_text("world")
        result = su.resolve_task_data({TASK_DATA_FILES: [str(f1), str(f2)]})
        assert result == "hello\nworld\n"

    def test_task_data_files_single_file(self, tmp_path):
        f = tmp_path / "only.txt"
        f.write_text("content")
        result = su.resolve_task_data({TASK_DATA_FILES: [str(f)]})
        assert result == "content\n"

    def test_task_data_files_variable_substitution(self, tmp_path, monkeypatch):
        monkeypatch.setenv("_YD_TEST_TDF_VAR", "sub")
        f = tmp_path / "t.txt"
        f.write_text("{{env:_YD_TEST_TDF_VAR}}")
        result = su.resolve_task_data({TASK_DATA_FILES: [str(f)]})
        assert result == "sub\n"

    def test_variable_substitution_applied_to_file_contents(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("_YD_TEST_TD_VAR", "world")
        f = tmp_path / "data.txt"
        f.write_text("hello-{{env:_YD_TEST_TD_VAR}}")
        assert su.resolve_task_data({TASK_DATA_FILE: str(f)}) == "hello-world"


# ---------------------------------------------------------------------------
# get_task_data_property
# ---------------------------------------------------------------------------


@pytest.fixture()
def empty_config_wr():
    return ConfigWorkRequirement()


class TestGetTaskDataProperty:
    def test_returns_none_when_nothing_set(self, empty_config_wr):
        result = su.get_task_data_property(empty_config_wr, {}, {}, {}, "t1")
        assert result is None

    def test_task_level_task_data_wins(self, empty_config_wr):
        task = {TASK_DATA: "task-level"}
        wr_data = {TASK_DATA: "wr-level"}
        result = su.get_task_data_property(empty_config_wr, wr_data, {}, task, "t1")
        assert result == "task-level"

    def test_task_group_level_task_data_used_when_task_missing(self, empty_config_wr):
        tg_data = {TASK_DATA: "tg-level"}
        result = su.get_task_data_property(empty_config_wr, {}, tg_data, {}, "t1")
        assert result == "tg-level"

    def test_wr_data_task_data_used_as_fallback(self, empty_config_wr):
        wr_data = {TASK_DATA: "wr-level"}
        result = su.get_task_data_property(empty_config_wr, wr_data, {}, {}, "t1")
        assert result == "wr-level"

    def test_config_wr_task_data_used_as_final_fallback(self):
        config = ConfigWorkRequirement(task_data="config-level")
        result = su.get_task_data_property(config, {}, {}, {}, "t1")
        assert result == "config-level"

    def test_raises_when_both_task_data_and_file_set_at_same_level(
        self, empty_config_wr
    ):
        task = {TASK_DATA: "inline", TASK_DATA_FILE: "file.txt"}
        with pytest.raises(ValueError, match="Only one of"):
            su.get_task_data_property(empty_config_wr, {}, {}, task, "t1")

    def test_task_data_file_read_from_disk(self, empty_config_wr, tmp_path):
        data_file = tmp_path / "data.txt"
        data_file.write_text("file-contents")
        task = {TASK_DATA_FILE: str(data_file)}
        result = su.get_task_data_property(empty_config_wr, {}, {}, task, "t1")
        assert result == "file-contents"

    def test_config_wr_task_data_file_read_from_disk(self, tmp_path):
        data_file = tmp_path / "cfg.txt"
        data_file.write_text("cfg-file-contents")
        config = ConfigWorkRequirement(task_data_file=str(data_file))
        result = su.get_task_data_property(config, {}, {}, {}, "t1")
        assert result == "cfg-file-contents"

    def test_task_level_task_data_files_wins_over_wr(self, empty_config_wr, tmp_path):
        f = tmp_path / "t.txt"
        f.write_text("task-files")
        task = {TASK_DATA_FILES: [str(f)]}
        wr_data = {TASK_DATA: "wr-level"}
        result = su.get_task_data_property(empty_config_wr, wr_data, {}, task, "t1")
        assert result == "task-files\n"

    def test_config_wr_task_data_files_used_as_final_fallback(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f1.write_text("part1")
        f2 = tmp_path / "b.txt"
        f2.write_text("part2")
        config = ConfigWorkRequirement(task_data_files=[str(f1), str(f2)])
        result = su.get_task_data_property(config, {}, {}, {}, "t1")
        assert result == "part1\npart2\n"

    def test_raises_when_task_data_and_files_set_at_task_level(self, empty_config_wr):
        task = {TASK_DATA: "inline", TASK_DATA_FILES: ["f.txt"]}
        with pytest.raises(ValueError, match="Only one of"):
            su.get_task_data_property(empty_config_wr, {}, {}, task, "t1")


# ---------------------------------------------------------------------------
# create_task
# ---------------------------------------------------------------------------


def _minimal_wr_data(num_task_groups: int = 1, num_tasks: int = 2) -> dict:
    """Minimal wr_data / task_group_data structure for create_task."""
    tasks = [{} for _ in range(num_tasks)]
    tg = {TASKS: tasks}
    return {TASK_GROUPS: [tg for _ in range(num_task_groups)]}


class TestCreateTask:
    def _call(self, **overrides: Any):
        defaults: dict[str, Any] = dict(
            wr_data=_minimal_wr_data(),
            task_group_data={TASKS: [{}, {}]},
            task_data={},
            task_name="my-task",
            task_number=0,
            tg_name="grp",
            tg_number=0,
            task_type="bash",
            args=["echo", "hi"],
            task_data_property=None,
            env=None,
            task_timeout=None,
        )
        defaults.update(overrides)
        return su.create_task(**defaults)

    def test_basic_task_created(self):
        task = self._call()
        assert task.name == "my-task"
        assert task.taskType == "bash"
        assert task.arguments == ["echo", "hi"]

    def test_empty_args_becomes_none(self):
        task = self._call(args=[])
        assert task.arguments is None

    def test_task_data_property_set(self):
        task = self._call(task_data_property="some-data")
        assert task.taskData == "some-data"

    def test_task_timeout_set(self):
        task = self._call(task_timeout=timedelta(minutes=30))
        assert task.timeout == timedelta(minutes=30)

    def test_tag_from_task_data(self):
        task = self._call(task_data={TASK_TAG: "my-tag"})
        assert task.tag == "my-tag"

    def test_env_none_no_add_yd_vars(self):
        task = self._call(env=None, add_yd_env_vars=False)
        assert task.environment is None

    def test_env_dict_preserved(self):
        task = self._call(env={"FOO": "bar"}, add_yd_env_vars=False)
        assert task.environment == {"FOO": "bar"}

    def test_env_not_mutated_by_deepcopy(self):
        original_env = {"FOO": "bar"}
        self._call(env=original_env, add_yd_env_vars=False)
        assert original_env == {"FOO": "bar"}

    def test_add_yd_env_vars_populates_env(self):
        task = self._call(
            env={},
            add_yd_env_vars=True,
            task_name="t1",
            task_number=1,
            tg_name="grp0",
            tg_number=0,
            wr_name="my-wr",
            namespace="my-ns",
        )
        env: dict = task.environment  # type: ignore[assignment]
        assert env[su.YD_TASK_NAME] == "t1"
        assert env[su.YD_TASK_NUMBER] == "1"
        assert env[su.YD_TASK_GROUP_NAME] == "grp0"
        assert env[su.YD_TASK_GROUP_NUMBER] == "0"
        assert env[su.YD_WORK_REQUIREMENT_NAME] == "my-wr"
        assert env[su.YD_NAMESPACE] == "my-ns"

    def test_add_yd_env_vars_includes_num_tasks_and_groups(self):
        wr_data = _minimal_wr_data(num_task_groups=3, num_tasks=5)
        task_group_data = {TASKS: [{} for _ in range(5)]}
        task = su.create_task(
            wr_data=wr_data,
            task_group_data=task_group_data,
            task_data={},
            task_name="t",
            task_number=0,
            tg_name="g",
            tg_number=0,
            task_type="bash",
            args=[],
            task_data_property=None,
            env={},
            task_timeout=None,
            add_yd_env_vars=True,
            wr_name="wr",
            namespace="ns",
        )
        env: dict = task.environment  # type: ignore[assignment]
        assert env[su.YD_NUM_TASKS] == "5"
        assert env[su.YD_NUM_TASK_GROUPS] == "3"

    def test_total_num_task_groups_and_tasks_override_wr_data_counts(self):
        # When adding to an existing WR, the spec wr_data only contains the new
        # TGs/tasks, but YD_NUM_TASK_GROUPS / YD_NUM_TASKS must reflect the
        # combined existing+new totals passed via the explicit override params.
        wr_data = _minimal_wr_data(num_task_groups=1, num_tasks=3)  # spec only
        task_group_data = {TASKS: [{} for _ in range(3)]}
        task = su.create_task(
            wr_data=wr_data,
            task_group_data=task_group_data,
            task_data={},
            task_name="t",
            task_number=0,
            tg_name="g",
            tg_number=0,
            task_type="bash",
            args=[],
            task_data_property=None,
            env={},
            task_timeout=None,
            add_yd_env_vars=True,
            wr_name="wr",
            namespace="ns",
            total_num_task_groups=5,  # 2 existing + 3 spec
            total_num_tasks=10,  # task_number_offset + spec tasks
        )
        env: dict = task.environment  # type: ignore[assignment]
        assert env[su.YD_NUM_TASK_GROUPS] == "5"
        assert env[su.YD_NUM_TASKS] == "10"

    def test_tag_added_to_yd_env_vars_when_present(self):
        task = self._call(
            env={},
            add_yd_env_vars=True,
            task_data={TASK_TAG: "important"},
            wr_name="wr",
            namespace="ns",
        )
        env: dict = task.environment  # type: ignore[assignment]
        assert env[su.YD_TAG] == "important"

    def test_tag_not_in_yd_env_vars_when_absent(self):
        task = self._call(env={}, add_yd_env_vars=True, wr_name="wr", namespace="ns")
        env: dict = task.environment  # type: ignore[assignment]
        assert su.YD_TAG not in env


# ---------------------------------------------------------------------------
# RcloneUploadedFiles._upload_rclone_file_core — overwrite / skip logic
# ---------------------------------------------------------------------------


class TestUploadRcloneFileCore:
    """
    Tests for the skip-if-exists / overwrite behaviour in _upload_rclone_file_core.

    The method is patched at three points:
      - _parse_rclone_connection_string → returns a fixed (remote, None, path) tuple
      - make_rclone → returns a mock rclone client
      - ARGS_PARSER.overwrite → controls whether --overwrite was passed
    """

    _CONN_STR = "rclone:myremote:/bucket/file.txt"
    _PARSED = ("myremote", None, "bucket/file.txt")
    _REMOTE_DEST = "myremote:bucket/file.txt"

    def _run(self, *, remote_exists: bool, overwrite: bool) -> MagicMock:
        """
        Run _upload_rclone_file_core with the given remote-exists / overwrite
        state. Returns the mock rclone instance so callers can inspect calls.
        """
        uploaded_file = su.RcloneUploadedFile(
            local_file_path="file.txt",
            upload_file_path=self._CONN_STR,
        )
        mock_rclone = MagicMock()
        mock_rclone.exists.return_value = remote_exists
        mock_rclone.copy_to.return_value = MagicMock(returncode=0, stderr="")

        instance = su.RcloneUploadedFiles()

        with (
            patch.object(
                su.RcloneUploadedFiles,
                "_parse_rclone_connection_string",
                return_value=self._PARSED,
            ),
            patch.object(su, "make_rclone", return_value=mock_rclone),
            patch.object(
                su.ARGS_PARSER.__class__,
                "overwrite",
                new_callable=lambda: property(lambda self: overwrite),
            ),
            patch("yellowdog_cli.utils.submit_utils.Path") as mock_path,
        ):
            mock_path.return_value.resolve.return_value = "/resolved/file.txt"
            instance._upload_rclone_file_core(uploaded_file)

        return mock_rclone

    def test_file_exists_no_overwrite_skips_upload(self):
        mock_rclone = self._run(remote_exists=True, overwrite=False)
        mock_rclone.copy_to.assert_not_called()

    def test_file_exists_with_overwrite_uploads(self):
        mock_rclone = self._run(remote_exists=True, overwrite=True)
        mock_rclone.copy_to.assert_called_once()

    def test_file_absent_no_overwrite_uploads(self):
        mock_rclone = self._run(remote_exists=False, overwrite=False)
        mock_rclone.copy_to.assert_called_once()

    def test_file_absent_with_overwrite_uploads(self):
        mock_rclone = self._run(remote_exists=False, overwrite=True)
        mock_rclone.copy_to.assert_called_once()

    def test_file_exists_no_overwrite_existence_check_uses_correct_dest(self):
        mock_rclone = self._run(remote_exists=True, overwrite=False)
        mock_rclone.exists.assert_called_once_with(self._REMOTE_DEST)

    def test_file_exists_with_overwrite_skips_existence_check(self):
        # When --overwrite is set we don't need to check existence at all
        mock_rclone = self._run(remote_exists=True, overwrite=True)
        mock_rclone.exists.assert_not_called()

    def test_upload_failure_raises_runtime_error(self):
        uploaded_file = su.RcloneUploadedFile(
            local_file_path="file.txt",
            upload_file_path=self._CONN_STR,
        )
        mock_rclone = MagicMock()
        mock_rclone.exists.return_value = False
        mock_rclone.copy_to.return_value = MagicMock(
            returncode=1, stderr="connection refused"
        )

        instance = su.RcloneUploadedFiles()

        with (
            patch.object(
                su.RcloneUploadedFiles,
                "_parse_rclone_connection_string",
                return_value=self._PARSED,
            ),
            patch.object(su, "make_rclone", return_value=mock_rclone),
            patch.object(
                su.ARGS_PARSER.__class__,
                "overwrite",
                new_callable=lambda: property(lambda self: False),
            ),
            patch("yellowdog_cli.utils.submit_utils.Path") as mock_path,
            pytest.raises(RuntimeError, match="Upload failed"),
        ):
            mock_path.return_value.resolve.return_value = "/resolved/file.txt"
            instance._upload_rclone_file_core(uploaded_file)
