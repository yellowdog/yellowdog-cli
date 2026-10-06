"""
Tests for what yd-submit makes of its inputs before submitting anything
(submit.py): the CSV files named, the shape of 'taskGroups', the path a
specification is reported by, the 'taskType' shorthand, and the type a Task
without one of its own is given.
"""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest

import yellowdog_cli.submit as submit_module
import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli.utils.args import CLIParser
from yellowdog_cli.utils.config_types import ConfigWorkRequirement
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.property_names import (
    TASK_GROUPS,
    TASK_TYPE,
    TASK_TYPES,
    TASKS,
)


def _ctx() -> RunContext:
    """The context a command is given: the wrapper's values, as patched."""
    return RunContext(
        wrapper_module.ARGS_PARSER, wrapper_module.CONFIG_COMMON, wrapper_module.CLIENT
    )


# ---------------------------------------------------------------------------
# The CSV files named
# ---------------------------------------------------------------------------


class TestCsvFiles:
    def _csv_files(self, from_config, from_command_line):
        with (
            patch.object(
                submit_module,
                "CONFIG_WR",
                ConfigWorkRequirement(csv_files=from_config),
            ),
            patch.object(
                CLIParser,
                "csv_files",
                new_callable=PropertyMock,
                return_value=from_command_line,
            ),
        ):
            return submit_module._csv_files(_ctx())

    def test_an_empty_list_in_the_configuration_names_none(self):
        # 'csvFiles = []' used to reach csv_files[0]: 'list index out of range'
        assert self._csv_files([], None) is None

    def test_the_configurations_files(self):
        assert self._csv_files(["a.csv"], None) == ["a.csv"]

    def test_the_command_line_wins(self):
        assert self._csv_files(["a.csv"], ["b.csv"]) == ["b.csv"]


class TestWorkRequirementFromCsv:
    def test_more_than_one_csv_file_is_an_error(self):
        # Without a specification there is one Task Group, so the files after
        # the first used to be ignored without a word
        with pytest.raises(ValueError, match=r"Number of CSV files \(2\) exceeds"):
            submit_module._work_requirement_from_csv(["a.csv", "b.csv"], ".")

    def test_one_csv_file_is_expanded(self):
        with patch.object(
            submit_module, "csv_expand_toml_tasks", return_value={"x": 1}
        ) as expand:
            assert submit_module._work_requirement_from_csv(["a.csv"], "d") == {"x": 1}
        assert expand.call_args.args[1:] == ("a.csv", "d")


# ---------------------------------------------------------------------------
# The shape of 'taskGroups'
# ---------------------------------------------------------------------------


class TestCheckTaskGroups:
    """
    A missing 'tasks' used to be reported as "ERROR : 'tasks'", and a
    missing 'taskGroups' submitted a Work Requirement with no Task Groups.
    """

    def test_missing_task_groups_is_named(self):
        with pytest.raises(ValueError, match=f"'{TASK_GROUPS}' is not defined"):
            submit_module.check_task_groups({})

    def test_missing_task_groups_points_at_empty(self):
        with pytest.raises(ValueError, match="--empty"):
            submit_module.check_task_groups({})

    def test_missing_tasks_is_named_with_its_task_group(self):
        with pytest.raises(
            ValueError, match=f"'{TASKS}' is not defined in Task Group 2 of 2"
        ):
            submit_module.check_task_groups({TASK_GROUPS: [{TASKS: []}, {}]})

    def test_task_groups_must_be_a_list(self):
        with pytest.raises(TypeError, match=f"'{TASK_GROUPS}'"):
            submit_module.check_task_groups({TASK_GROUPS: {}})

    def test_a_task_group_must_be_a_table(self):
        with pytest.raises(TypeError, match="Task Group 1 of 1"):
            submit_module.check_task_groups({TASK_GROUPS: ["tg"]})

    def test_a_task_must_be_a_table(self):
        with pytest.raises(TypeError, match="Task 2 in Task Group 1 of 1"):
            submit_module.check_task_groups({TASK_GROUPS: [{TASKS: [{}, "t"]}]})

    def test_empty_task_groups_and_tasks_are_allowed(self):
        submit_module.check_task_groups({TASK_GROUPS: []})
        submit_module.check_task_groups({TASK_GROUPS: [{TASKS: []}]})


# ---------------------------------------------------------------------------
# The path a specification is reported by
# ---------------------------------------------------------------------------


class TestRelativeIfPossible:
    # utils/paths.py, shared by the configuration loader, the CSV loader,
    # yd-submit and Commander

    def test_a_relative_path_where_there_is_one(self, tmp_path, monkeypatch):
        from yellowdog_cli.utils.paths import relative_if_possible

        monkeypatch.chdir(tmp_path)
        assert relative_if_possible(str(tmp_path / "wr.json")) == "wr.json"

    def test_the_absolute_path_where_there_is_none(self, tmp_path, monkeypatch):
        # As on Windows, for a file on a different drive from the current
        # directory, where relpath() raises
        import yellowdog_cli.utils.paths as paths_module

        monkeypatch.chdir(tmp_path)
        with patch.object(
            paths_module, "relpath", side_effect=ValueError("different mount")
        ):
            assert paths_module.relative_if_possible("wr.json") == str(
                tmp_path / "wr.json"
            )


# ---------------------------------------------------------------------------
# The 'taskType' shorthand
# ---------------------------------------------------------------------------


class TestPromoteTaskType:
    def test_task_type_stands_for_task_types(self):
        data = {TASK_TYPE: "bash"}
        submit_module.promote_task_type(data)
        assert data[TASK_TYPES] == ["bash"]

    def test_task_types_already_set_is_kept(self):
        data = {TASK_TYPE: "bash", TASK_TYPES: ["docker"]}
        submit_module.promote_task_type(data)
        assert data[TASK_TYPES] == ["docker"]

    def test_nothing_to_promote(self):
        data: dict = {}
        submit_module.promote_task_type(data)
        assert data == {}


# ---------------------------------------------------------------------------
# The type a Task without one of its own is given
# ---------------------------------------------------------------------------


def _task_group(task_types: list[str], template_type: str | None = None):
    task_group = MagicMock()
    task_group.name = "tg"
    task_group.runSpecification.taskTypes = task_types
    task_group.taskTemplate = (
        None if template_type is None else MagicMock(taskType=template_type)
    )
    return task_group


def _task_type_of(task: dict, task_group, config_type: str | None = None):
    return submit_module._task_type_of(
        task, task_group, ConfigWorkRequirement(task_type=config_type), "t1", 0
    )


class TestTaskTypeOf:
    def test_the_tasks_own(self):
        assert _task_type_of({TASK_TYPE: "docker"}, _task_group(["bash"])) == "docker"

    def test_the_task_groups_sole_type(self):
        assert _task_type_of({}, _task_group(["bash"])) == "bash"

    def test_the_configurations_when_the_task_group_allows_it(self):
        assert (
            _task_type_of({}, _task_group(["bash", "docker"]), config_type="docker")
            == "docker"
        )

    def test_none_when_the_template_supplies_one(self):
        assert _task_type_of({}, _task_group(["bash", "docker"], "bash")) is None

    def test_a_configured_type_the_task_group_disallows_is_an_error(self):
        # It used to be sent, for the Platform to refuse
        with pytest.raises(ValueError, match="has no 'taskType'"):
            _task_type_of({}, _task_group(["bash", "docker"]), config_type="python")

    def test_no_type_to_be_had_is_an_error_naming_the_task(self):
        # It used to be sent as None
        with pytest.raises(ValueError, match=r"Task 1 \('t1'\) in Task Group 'tg'"):
            _task_type_of({}, _task_group(["bash", "docker"]))
