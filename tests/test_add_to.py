"""
Tests for the --add-to feature: offset-aware task/task-group naming and the
dispatch logic in add_to_existing_work_requirement.
"""

from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from yellowdog_client.model import TaskGroup, WorkRequirement, WorkRequirementStatus

import yellowdog_cli.submit as submit_module
import yellowdog_cli.utils.submit_utils as su
from yellowdog_cli.utils.args import CLIParser
from yellowdog_cli.utils.property_names import NAME, TASK_GROUPS, TASK_TYPES, TASKS
from yellowdog_cli.utils.settings import VAR_CLOSING_DELIMITER, VAR_OPENING_DELIMITER

# Lazy-sub placeholder shortcuts
_TN = f"{VAR_OPENING_DELIMITER}{su.L_TASK_NUMBER}{VAR_CLOSING_DELIMITER}"
_TC = f"{VAR_OPENING_DELIMITER}{su.L_TASK_COUNT}{VAR_CLOSING_DELIMITER}"
_TGN = f"{VAR_OPENING_DELIMITER}{su.L_TASK_GROUP_NUMBER}{VAR_CLOSING_DELIMITER}"
_TGC = f"{VAR_OPENING_DELIMITER}{su.L_TASK_GROUP_COUNT}{VAR_CLOSING_DELIMITER}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tg(
    name: str, task_count: int = 0, task_types: list[str] | None = None
) -> TaskGroup:
    tg = MagicMock(spec=TaskGroup)
    tg.name = name
    summary = MagicMock()
    summary.taskCount = task_count
    tg.taskSummary = summary
    run_spec = MagicMock()
    run_spec.taskTypes = list(task_types) if task_types is not None else ["bash"]
    tg.runSpecification = run_spec
    return tg


def _make_wr(name: str, status: WorkRequirementStatus, tgs: list[TaskGroup]):
    wr = MagicMock(spec=WorkRequirement)
    wr.name = name
    wr.id = f"ydid:wr:{name}"
    wr.status = status
    wr.taskGroups = tgs
    return wr


def _make_wr_summary(name: str, status: WorkRequirementStatus, wr_id: str):
    s = MagicMock()
    s.name = name
    s.id = wr_id
    s.status = status
    return s


# ---------------------------------------------------------------------------
# Offset arithmetic in get_task_group_name
# ---------------------------------------------------------------------------


class TestTaskGroupNameWithOffset:
    """
    Verify that passing an effective task_group_number (tg_number + offset)
    into get_task_group_name produces correctly shifted names.
    """

    def test_first_new_tg_after_two_existing(self):
        # 2 existing + 1 new = 3 total; spec index 0 → effective index 2 → "task_group_3"
        assert su.get_task_group_name(None, 2, 3, 1) == "task_group_3"

    def test_second_new_tg_after_two_existing(self):
        # 2 existing + 2 new = 4 total; spec index 1 → effective index 3 → "task_group_4"
        assert su.get_task_group_name(None, 3, 4, 1) == "task_group_4"

    def test_zero_padding_spans_existing_and_new(self):
        # 10 total groups → width 2; effective index 9 → "task_group_10"
        assert su.get_task_group_name(None, 9, 10, 1) == "task_group_10"

    def test_number_placeholder_uses_effective_index(self):
        # effective index 5 of 6 total groups → width 1 → "g6"
        assert su.get_task_group_name(f"g{_TGN}", 5, 6, 1) == "g6"

    def test_count_placeholder_reflects_total(self):
        assert su.get_task_group_name(f"of{_TGC}", 0, 7, 1) == "of7"

    def test_no_offset_unchanged(self):
        # baseline: spec index 0, 1 total → "task_group_1"
        assert su.get_task_group_name(None, 0, 1, 1) == "task_group_1"


# ---------------------------------------------------------------------------
# Offset arithmetic in get_task_name
# ---------------------------------------------------------------------------


class TestTaskNameWithOffset:
    """
    Verify that passing a display task_number and num_tasks (with offset) into
    get_task_name produces correctly shifted names.
    """

    def test_first_new_task_after_three_existing(self):
        # offset=3, task 0 → display 3; total=3+5=8 → width 1; "task_4"
        assert su.get_task_name(None, True, 3, 8, 0, 1, "grp") == "task_4"

    def test_last_task_with_offset(self):
        # offset=5, task 4 → display 9; total=5+5=10 → width 2; "task_10"
        assert su.get_task_name(None, True, 9, 10, 0, 1, "grp") == "task_10"

    def test_number_placeholder_with_offset(self):
        # display task number 5, total 10 → width 2; "task_06"
        assert su.get_task_name(f"task_{_TN}", True, 5, 10, 0, 1, "grp") == "task_06"

    def test_count_placeholder_reflects_display_total(self):
        # display_num_tasks=8 (3 existing + 5 new)
        assert su.get_task_name(f"of{_TC}", True, 3, 8, 0, 1, "grp") == "of8"

    def test_no_offset_unchanged(self):
        assert su.get_task_name(None, True, 0, 3, 0, 1, "grp") == "task_1"

    def test_zero_padded_with_large_offset(self):
        # offset=90, task 0 → display 90; total=100 → width 3; "task_091"
        assert su.get_task_name(None, True, 90, 100, 0, 1, "grp") == "task_091"


# ---------------------------------------------------------------------------
# add_to_existing_work_requirement: not-found rejection
# ---------------------------------------------------------------------------


class TestAddToNotFound:
    def test_raises_when_wr_not_found(self):
        with (
            patch.object(
                submit_module,
                "get_work_requirement_summary_by_name_or_id",
                return_value=None,
            ),
            patch.object(
                CLIParser, "add_to", new_callable=PropertyMock, return_value="ghost-wr"
            ),
            pytest.raises(ValueError, match="not found"),
        ):
            submit_module.add_to_existing_work_requirement(files_directory=".")


# ---------------------------------------------------------------------------
# add_to_existing_work_requirement: terminal status rejection
# ---------------------------------------------------------------------------


class TestAddToTerminalStatusRejection:
    @pytest.mark.parametrize(
        "status",
        [
            WorkRequirementStatus.COMPLETED,
            WorkRequirementStatus.CANCELLED,
            WorkRequirementStatus.FAILED,
            WorkRequirementStatus.CANCELLING,
        ],
    )
    def test_raises_for_terminal_status(self, status: WorkRequirementStatus):
        wr_summary = _make_wr_summary("my-wr", status, "ydid:wr:123")

        with (
            patch.object(
                submit_module,
                "get_work_requirement_summary_by_name_or_id",
                return_value=wr_summary,
            ),
            patch.object(
                CLIParser, "add_to", new_callable=PropertyMock, return_value="my-wr"
            ),
            pytest.raises(ValueError, match="terminal status"),
        ):
            submit_module.add_to_existing_work_requirement(files_directory=".")

    @pytest.mark.parametrize(
        "status",
        [
            WorkRequirementStatus.RUNNING,
            WorkRequirementStatus.HELD,
            WorkRequirementStatus.FINISHING,
        ],
    )
    def test_does_not_raise_for_non_terminal_status(
        self, status: WorkRequirementStatus
    ):
        wr_summary = _make_wr_summary("my-wr", status, "ydid:wr:123")
        existing_wr = _make_wr("my-wr", status, [])

        with (
            patch.object(
                submit_module,
                "get_work_requirement_summary_by_name_or_id",
                return_value=wr_summary,
            ),
            patch.object(
                CLIParser, "add_to", new_callable=PropertyMock, return_value="my-wr"
            ),
            patch.object(
                submit_module.CLIENT.work_client,
                "get_work_requirement_by_id",
                return_value=existing_wr,
            ),
            patch.object(submit_module, "add_substitutions_without_overwriting"),
            patch.object(
                submit_module,
                "update_config_work_requirement_object",
                return_value=submit_module.CONFIG_WR,
            ),
            patch.object(submit_module, "RcloneUploadedFiles"),
            patch.object(submit_module, "create_task_group") as mock_ctg,
            patch.object(submit_module, "add_tasks_to_task_group"),
            patch.object(
                submit_module.CLIENT.work_client,
                "update_work_requirement",
                return_value=existing_wr,
            ),
            patch.object(
                CLIParser, "follow", new_callable=PropertyMock, return_value=False
            ),
        ):
            mock_ctg.return_value = _make_tg("task_group_1")
            submit_module.add_to_existing_work_requirement(
                files_directory=".",
                wr_data={TASK_GROUPS: [{TASKS: [{}], TASK_TYPES: ["bash"]}]},
            )


# ---------------------------------------------------------------------------
# add_to_existing_work_requirement: TG partitioning
# ---------------------------------------------------------------------------


class TestAddToPartitioning:
    """
    Verify that spec TGs are correctly partitioned into 'new' vs 'matched',
    and that the right offsets are passed to add_tasks_to_task_group.
    """

    def _run(
        self,
        existing_tg_names: list[str],
        spec_tg_names: list[str],
        existing_task_count: int = 2,
        existing_task_types: dict[str, list[str]] | None = None,
        spec_task_types: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        existing_task_types = existing_task_types or {}
        spec_task_types = spec_task_types or {}
        existing_tgs = [
            _make_tg(
                n,
                task_count=existing_task_count,
                task_types=existing_task_types.get(n),
            )
            for n in existing_tg_names
        ]
        existing_wr = _make_wr("my-wr", WorkRequirementStatus.RUNNING, existing_tgs)
        updated_wr = _make_wr("my-wr", WorkRequirementStatus.RUNNING, existing_tgs)
        wr_summary = _make_wr_summary(
            "my-wr", WorkRequirementStatus.RUNNING, "ydid:wr:my-wr"
        )

        spec_tgs = [{NAME: n, TASKS: [{}], TASK_TYPES: ["bash"]} for n in spec_tg_names]
        wr_data = {TASK_GROUPS: spec_tgs}

        add_tasks_calls: list[dict] = []
        update_wr_calls: list = []

        def fake_add_tasks(
            tg_number,
            task_group,
            wr_data,
            task_count,
            work_requirement,
            files_directory,
            tg_number_offset,
            total_num_task_groups,
            task_number_offset,
        ):
            add_tasks_calls.append(
                {
                    "tg_name": task_group.name,
                    "tg_number": tg_number,
                    "tg_number_offset": tg_number_offset,
                    "task_number_offset": task_number_offset,
                    "total_num_task_groups": total_num_task_groups,
                }
            )

        def fake_update_wr(wr):
            update_wr_calls.append(list(wr.taskGroups))
            return updated_wr

        def fake_create_tg(
            tg_number,
            wr_data,
            task_group_data,
            tg_number_offset,
            total_num_task_groups,
            files_directory="",
        ):
            return _make_tg(
                task_group_data[NAME],
                task_types=spec_task_types.get(task_group_data[NAME]),
            )

        with (
            patch.object(
                submit_module,
                "get_work_requirement_summary_by_name_or_id",
                return_value=wr_summary,
            ),
            patch.object(
                CLIParser, "add_to", new_callable=PropertyMock, return_value="my-wr"
            ),
            patch.object(
                submit_module.CLIENT.work_client,
                "get_work_requirement_by_id",
                return_value=existing_wr,
            ),
            patch.object(submit_module, "add_substitutions_without_overwriting"),
            patch.object(
                submit_module,
                "update_config_work_requirement_object",
                return_value=submit_module.CONFIG_WR,
            ),
            patch.object(submit_module, "RcloneUploadedFiles"),
            patch.object(
                submit_module, "create_task_group", side_effect=fake_create_tg
            ),
            patch.object(
                submit_module, "add_tasks_to_task_group", side_effect=fake_add_tasks
            ),
            patch.object(
                submit_module.CLIENT.work_client,
                "update_work_requirement",
                side_effect=fake_update_wr,
            ),
            patch.object(
                CLIParser, "follow", new_callable=PropertyMock, return_value=False
            ),
        ):
            submit_module.add_to_existing_work_requirement(
                files_directory=".", wr_data=wr_data
            )

        return {
            "add_tasks_calls": add_tasks_calls,
            "update_wr_calls": update_wr_calls,
        }

    def test_all_new_tgs_triggers_update_work_requirement(self):
        result = self._run(existing_tg_names=["existing_1"], spec_tg_names=["new_tg"])
        assert len(result["update_wr_calls"]) == 1

    def test_no_new_tgs_skips_update_work_requirement(self):
        result = self._run(
            existing_tg_names=["task_group"], spec_tg_names=["task_group"]
        )
        assert len(result["update_wr_calls"]) == 0

    def test_matched_tg_gets_task_offset_from_existing_task_count(self):
        # existing TG has 2 tasks → task_number_offset should be 2
        result = self._run(
            existing_tg_names=["my-group"],
            spec_tg_names=["my-group"],
            existing_task_count=2,
        )
        calls = result["add_tasks_calls"]
        assert len(calls) == 1
        assert calls[0]["tg_name"] == "my-group"
        assert calls[0]["task_number_offset"] == 2

    def test_matched_tg_offset_reflects_actual_task_count(self):
        result = self._run(
            existing_tg_names=["grp"],
            spec_tg_names=["grp"],
            existing_task_count=10,
        )
        assert result["add_tasks_calls"][0]["task_number_offset"] == 10

    def test_new_tg_gets_zero_task_offset(self):
        result = self._run(existing_tg_names=["existing"], spec_tg_names=["brand-new"])
        assert result["add_tasks_calls"][0]["task_number_offset"] == 0

    def test_tg_number_offset_equals_number_of_existing_tgs(self):
        result = self._run(existing_tg_names=["a", "b"], spec_tg_names=["c"])
        assert result["add_tasks_calls"][0]["tg_number_offset"] == 2

    def test_tg_number_offset_zero_when_no_existing_tgs(self):
        result = self._run(existing_tg_names=[], spec_tg_names=["new"])
        assert result["add_tasks_calls"][0]["tg_number_offset"] == 0

    def test_total_num_task_groups_is_existing_plus_new(self):
        # 2 existing + 1 new = 3 total
        result = self._run(existing_tg_names=["a", "b"], spec_tg_names=["c"])
        assert result["add_tasks_calls"][0]["total_num_task_groups"] == 3

    def test_total_num_task_groups_is_existing_plus_spec_when_all_matched(self):
        # 2 existing + 2 spec (all matched) → total = 2+2 = 4
        result = self._run(existing_tg_names=["a", "b"], spec_tg_names=["a", "b"])
        for c in result["add_tasks_calls"]:
            assert c["total_num_task_groups"] == 4

    def test_mixed_new_and_matched(self):
        # existing: ["grp-1"]; spec: ["grp-1" (matched), "grp-2" (new)]
        result = self._run(
            existing_tg_names=["grp-1"],
            spec_tg_names=["grp-1", "grp-2"],
            existing_task_count=3,
        )
        by_name = {c["tg_name"]: c for c in result["add_tasks_calls"]}
        assert set(by_name.keys()) == {"grp-1", "grp-2"}
        assert by_name["grp-1"]["task_number_offset"] == 3  # existing had 3 tasks
        assert by_name["grp-2"]["task_number_offset"] == 0  # new, no offset
        assert len(result["update_wr_calls"]) == 1

    def test_total_for_mixed_scenario(self):
        # 1 existing + 2 spec (1 matched + 1 new) = 1+2 = 3 total
        result = self._run(
            existing_tg_names=["grp-1"], spec_tg_names=["grp-1", "grp-2"]
        )
        for c in result["add_tasks_calls"]:
            assert c["total_num_task_groups"] == 3

    def test_update_wr_called_with_existing_plus_new_tgs(self):
        result = self._run(existing_tg_names=["existing"], spec_tg_names=["new-one"])
        assert len(result["update_wr_calls"]) == 1
        tg_names_in_update = [tg.name for tg in result["update_wr_calls"][0]]
        assert "existing" in tg_names_in_update
        assert "new-one" in tg_names_in_update

    # --- taskTypes validation on matched existing Task Groups ---

    def test_matched_tg_spec_introduces_new_type_raises(self):
        # Existing TG has taskTypes=["bash"]; spec adds "docker".
        # Mutating taskTypes post-creation is not supported by the platform,
        # so the CLI must fail fast with a clear error.
        with pytest.raises(ValueError, match=r"task type\(s\) \['docker'\] are not in"):
            self._run(
                existing_tg_names=["grp"],
                spec_tg_names=["grp"],
                existing_task_types={"grp": ["bash"]},
                spec_task_types={"grp": ["docker"]},
            )

    def test_matched_tg_spec_subset_of_existing_does_not_raise(self):
        # Spec types are a subset of existing → safe to proceed; no
        # update_work_requirement call is needed
        result = self._run(
            existing_tg_names=["grp"],
            spec_tg_names=["grp"],
            existing_task_types={"grp": ["bash", "docker", "powershell"]},
            spec_task_types={"grp": ["bash"]},
        )
        assert len(result["update_wr_calls"]) == 0

    def test_matched_tg_spec_equal_to_existing_does_not_raise(self):
        result = self._run(
            existing_tg_names=["grp"],
            spec_tg_names=["grp"],
            existing_task_types={"grp": ["bash", "docker"]},
            spec_task_types={"grp": ["bash", "docker"]},
        )
        assert len(result["update_wr_calls"]) == 0
