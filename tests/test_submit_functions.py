"""
Tests for create_task_group (utils/task_groups.py), submit_work_requirement
(submit.py) and generate_batch_of_tasks (utils/task_generation.py).
"""

from datetime import timedelta
from unittest.mock import ANY, MagicMock, PropertyMock, patch

import pytest
from yellowdog_client.model import (
    CloudProvider,
    DoubleRange,
    Task,
    TaskGroup,
    TaskTemplate,
    WorkRequirement,
)
from yellowdog_client.model.instance_pricing_preference import InstancePricingPreference

import yellowdog_cli.submit as submit_module
import yellowdog_cli.utils.task_generation as task_generation_module
import yellowdog_cli.utils.task_groups as task_groups_module
import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli.utils.args import CLIParser
from yellowdog_cli.utils.config_types import ConfigWorkRequirement
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.lazy import value as lazy_value
from yellowdog_cli.utils.property_names import (
    ADD_ENVIRONMENT,
    ARGS,
    ARGS_POSTFIX,
    ARGS_PREFIX,
    COMPLETED_TASK_TTL,
    ENV,
    INSTANCE_PRICING_PREFERENCE,
    MAX_WORKERS,
    MIN_WORKERS,
    NAME,
    PROVIDERS,
    RAM,
    TASK_DATA,
    TASK_DATA_FILE,
    TASK_DATA_INPUTS,
    TASK_GROUP_COUNT,
    TASK_GROUP_TAG,
    TASK_GROUPS,
    TASK_TEMPLATE,
    TASK_TIMEOUT,
    TASK_TYPE,
    TASK_TYPES,
    TASKS,
    TASKS_PER_WORKER,
    VCPUS,
)
from yellowdog_cli.utils.task_group_position import TaskGroupPosition


def _ctx() -> RunContext:
    """
    The context a command is given: the wrapper's values, as patched.
    """
    return RunContext(
        wrapper_module.ARGS_PARSER, wrapper_module.CONFIG_COMMON, wrapper_module.CLIENT
    )


def _submission(**state) -> submit_module._Submission:
    """
    A yd-submit run as main() starts one, from the wrapper globals and
    submit's CONFIG_WR (as patched), with any of its state given.
    """
    return submit_module._Submission(
        _ctx(), config_wr=lazy_value(submit_module.CONFIG_WR), **state
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_mock_wr(name: str = "test-wr") -> WorkRequirement:
    wr = MagicMock(spec=WorkRequirement)
    wr.name = name
    wr.id = f"ydid:wr:{name}"
    wr.taskGroups = []
    return wr


def _make_mock_tg(name: str = "task_group_1") -> TaskGroup:
    tg = MagicMock(spec=TaskGroup)
    tg.name = name
    return tg


# ---------------------------------------------------------------------------
# create_task_group helpers
# ---------------------------------------------------------------------------


def _call_create_task_group(
    task_group_data: dict,
    wr_data: dict | None = None,
    config_wr: ConfigWorkRequirement | None = None,
    tg_number: int = 0,
) -> TaskGroup:
    """
    Call create_task_group with standard mocks in place.
    update_config_work_requirement_object is mocked as identity so that
    whatever ConfigWorkRequirement is passed in is used directly.
    """
    if config_wr is None:
        config_wr = ConfigWorkRequirement()
    if wr_data is None:
        wr_data = {TASK_GROUPS: [task_group_data]}
    with (
        patch.object(
            task_groups_module,
            "update_config_work_requirement_object",
            side_effect=lambda x: x,
        ),
        patch.object(task_groups_module, "generate_dependencies", return_value=[]),
        patch.object(
            task_groups_module, "generate_task_error_matchers_list", return_value=[]
        ),
    ):
        return task_groups_module.create_task_group(
            config_wr,
            TaskGroupPosition(tg_number, tg_number, len(wr_data[TASK_GROUPS])),
            wr_data=wr_data,
            task_group_data=task_group_data,
        )


# ---------------------------------------------------------------------------
# create_task_group — task type resolution
# ---------------------------------------------------------------------------


class TestCreateTaskGroupTaskTypes:
    """
    Task type resolution: remapping, unioning, fallback chain.
    """

    def test_task_type_remapped_to_task_types(self):
        tg_data = {TASK_TYPE: "bash", TASKS: [{}]}
        tg = _call_create_task_group(tg_data)
        assert "bash" in tg.runSpecification.taskTypes

    def test_task_type_not_overwritten_when_task_types_already_set(self):
        # TASK_TYPES takes precedence over TASK_TYPE
        tg_data = {TASK_TYPE: "bash", TASK_TYPES: ["docker"], TASKS: [{}]}
        tg = _call_create_task_group(tg_data)
        assert tg.runSpecification.taskTypes == ["docker"]

    def test_task_types_from_individual_tasks_unioned_with_tg_level(self):
        tg_data = {TASK_TYPES: ["bash"], TASKS: [{TASK_TYPE: "docker"}, {}]}
        tg = _call_create_task_group(tg_data)
        assert set(tg.runSpecification.taskTypes) == {"bash", "docker"}

    def test_task_types_at_wr_level_used_when_tg_has_none(self):
        tg_data = {TASKS: [{}]}
        wr_data = {TASK_GROUPS: [tg_data], TASK_TYPES: ["bash"]}
        tg = _call_create_task_group(tg_data, wr_data=wr_data)
        assert "bash" in tg.runSpecification.taskTypes

    def test_config_wr_task_type_used_as_final_fallback(self):
        tg_data = {TASKS: [{}]}
        tg = _call_create_task_group(
            tg_data, config_wr=ConfigWorkRequirement(task_type="bash")
        )
        assert "bash" in tg.runSpecification.taskTypes

    def test_raises_when_no_task_types_and_tasks_present(self):
        # 2 tasks avoids the single-task TASK_COUNT expansion path
        tg_data = {TASKS: [{}, {}]}
        with pytest.raises(ValueError, match="No Task Type"):
            _call_create_task_group(tg_data)

    def test_no_error_when_no_task_types_but_no_tasks(self):
        # Empty task group: no types required
        tg_data = {TASKS: []}
        _call_create_task_group(tg_data)  # should not raise

    def test_no_error_when_task_type_provided_only_via_task_template(self):
        # taskTemplate.taskType satisfies the requirement
        tg_data = {TASKS: [{}], TASK_TEMPLATE: {"taskType": "docker"}}
        _call_create_task_group(tg_data)  # should not raise

    def test_raises_when_no_task_types_and_task_template_has_no_task_type(self):
        # taskTemplate present but no taskType field — still no type
        tg_data = {TASKS: [{}, {}], TASK_TEMPLATE: {"taskData": "d"}}
        with pytest.raises(ValueError, match="No Task Type"):
            _call_create_task_group(tg_data)


# ---------------------------------------------------------------------------
# create_task_group — resource spec conversions
# ---------------------------------------------------------------------------


class TestCreateTaskGroupResourceConversions:
    """
    vcpus, ram, providers, instance_pricing_preference conversions.
    """

    def _tg(self, **extra) -> dict:
        return {TASKS: [{}], TASK_TYPES: ["bash"], **extra}

    def test_vcpus_converted_to_double_range(self):
        tg = _call_create_task_group(self._tg(**{VCPUS: [2, 4]}))
        assert tg.runSpecification.vcpus == DoubleRange(2.0, 4.0)

    def test_vcpus_none_when_not_set(self):
        tg = _call_create_task_group(self._tg())
        assert tg.runSpecification.vcpus is None

    def test_ram_converted_to_double_range(self):
        tg = _call_create_task_group(self._tg(**{RAM: [8, 32]}))
        assert tg.runSpecification.ram == DoubleRange(8.0, 32.0)

    def test_ram_none_when_not_set(self):
        tg = _call_create_task_group(self._tg())
        assert tg.runSpecification.ram is None

    def test_providers_converted_to_cloud_provider_list(self):
        tg = _call_create_task_group(self._tg(**{PROVIDERS: ["AWS", "GOOGLE"]}))
        assert tg.runSpecification.providers == [
            CloudProvider("AWS"),
            CloudProvider("GOOGLE"),
        ]

    def test_providers_none_when_not_set(self):
        tg = _call_create_task_group(self._tg())
        assert tg.runSpecification.providers is None

    def test_instance_pricing_preference_converted(self):
        tg = _call_create_task_group(
            self._tg(**{INSTANCE_PRICING_PREFERENCE: "SPOT_ONLY"})
        )
        assert (
            tg.runSpecification.instancePricingPreference
            == InstancePricingPreference("SPOT_ONLY")
        )

    def test_instance_pricing_preference_none_when_not_set(self):
        tg = _call_create_task_group(self._tg())
        assert tg.runSpecification.instancePricingPreference is None


# ---------------------------------------------------------------------------
# create_task_group — timeout conversions
# ---------------------------------------------------------------------------


class TestCreateTaskGroupTimeouts:
    """
    task_timeout and completed_task_ttl → timedelta conversions.
    """

    def _tg(self, **extra) -> dict:
        return {TASKS: [{}], TASK_TYPES: ["bash"], **extra}

    def test_task_timeout_converted_to_timedelta(self):
        tg = _call_create_task_group(self._tg(**{TASK_TIMEOUT: 30}))
        assert tg.runSpecification.taskTimeout == timedelta(minutes=30)

    def test_task_timeout_none_when_not_set(self):
        tg = _call_create_task_group(self._tg())
        assert tg.runSpecification.taskTimeout is None

    def test_completed_task_ttl_converted_to_timedelta(self):
        tg = _call_create_task_group(self._tg(**{COMPLETED_TASK_TTL: 60}))
        assert tg.completedTaskTtl == timedelta(minutes=60)

    def test_completed_task_ttl_none_when_not_set(self):
        tg = _call_create_task_group(self._tg())
        assert tg.completedTaskTtl is None


INHERITED_CASES = [
    (MIN_WORKERS, 2, "minWorkers", 2),
    (MAX_WORKERS, 5, "maxWorkers", 5),
    (TASKS_PER_WORKER, 3, "tasksPerWorker", 3),
    (TASK_TIMEOUT, 30, "taskTimeout", timedelta(minutes=30)),
]


class TestCreateTaskGroupInheritsFromWorkRequirement:
    """
    minWorkers, maxWorkers, tasksPerWorker and taskTimeout set at the Work
    Requirement level reach every Task Group that does not set its own, as
    vcpus and ram do: the README's Property Inheritance.
    """

    def _tg(self, **extra) -> dict:
        return {TASKS: [{}], TASK_TYPES: ["bash"], **extra}

    @pytest.mark.parametrize(("prop", "value", "attr", "expected"), INHERITED_CASES)
    def test_work_requirement_value_is_inherited(self, prop, value, attr, expected):
        tg_data = self._tg()
        wr_data = {prop: value, TASK_GROUPS: [tg_data]}
        tg = _call_create_task_group(tg_data, wr_data=wr_data)
        assert getattr(tg.runSpecification, attr) == expected

    @pytest.mark.parametrize(("prop", "value", "attr", "expected"), INHERITED_CASES)
    def test_task_group_value_overrides_work_requirement(
        self, prop, value, attr, expected
    ):
        tg_data = self._tg(**{prop: value})
        wr_data = {prop: value + 1, TASK_GROUPS: [tg_data]}
        tg = _call_create_task_group(tg_data, wr_data=wr_data)
        assert getattr(tg.runSpecification, attr) == expected

    @pytest.mark.parametrize(("prop", "value", "attr", "expected"), INHERITED_CASES)
    def test_work_requirement_value_overrides_toml(self, prop, value, attr, expected):
        field = {
            MIN_WORKERS: "min_workers",
            MAX_WORKERS: "max_workers",
            TASKS_PER_WORKER: "tasks_per_worker",
            TASK_TIMEOUT: "task_timeout",
        }[prop]
        tg_data = self._tg()
        wr_data = {prop: value, TASK_GROUPS: [tg_data]}
        config_wr = ConfigWorkRequirement(**{field: value + 1})
        tg = _call_create_task_group(tg_data, wr_data=wr_data, config_wr=config_wr)
        assert getattr(tg.runSpecification, attr) == expected


# ---------------------------------------------------------------------------
# create_task_group — naming
# ---------------------------------------------------------------------------


class TestCreateTaskGroupNaming:
    """
    Auto-naming and explicit naming of task groups.
    """

    def _tg(self, **extra) -> dict:
        return {TASKS: [{}], TASK_TYPES: ["bash"], **extra}

    def test_auto_name_generated_when_no_name_given(self):
        tg = _call_create_task_group(self._tg())
        assert tg.name == "task_group_1"

    def test_explicit_name_used_when_provided(self):
        tg = _call_create_task_group(self._tg(**{NAME: "my-group"}))
        assert tg.name == "my-group"

    def test_config_wr_task_group_name_used_as_fallback(self):
        tg = _call_create_task_group(
            self._tg(),
            config_wr=ConfigWorkRequirement(task_group_name="cfg-group"),
        )
        assert tg.name == "cfg-group"

    def test_wr_data_name_overrides_config_wr_name(self):
        tg = _call_create_task_group(
            self._tg(**{NAME: "explicit"}),
            config_wr=ConfigWorkRequirement(task_group_name="cfg-group"),
        )
        assert tg.name == "explicit"


# ---------------------------------------------------------------------------
# create_task_group — taskTemplate
# ---------------------------------------------------------------------------


class TestCreateTaskGroupTaskTemplate:
    """
    taskTemplate propagation to the TaskGroup object.
    """

    def _tg(self, **extra) -> dict:
        return {TASKS: [{}], TASK_TYPES: ["bash"], **extra}

    def test_task_template_set_from_tg_data(self):
        tg_data = self._tg(
            **{
                TASK_TEMPLATE: {
                    "taskType": "docker",
                    "taskData": "d",
                    "environment": {"K": "V"},
                }
            }
        )
        tg = _call_create_task_group(tg_data)
        assert tg.taskTemplate == TaskTemplate(  # type: ignore[attr-defined]
            taskType="docker", taskData="d", environment={"K": "V"}
        )

    def test_task_template_set_from_wr_data(self):
        tg_data = self._tg()
        wr_data = {TASK_GROUPS: [tg_data], TASK_TEMPLATE: {"taskType": "docker"}}
        tg = _call_create_task_group(tg_data, wr_data=wr_data)
        assert tg.taskTemplate == TaskTemplate(taskType="docker")  # type: ignore[attr-defined]

    def test_tg_level_task_template_overrides_wr_level(self):
        tg_data = self._tg(**{TASK_TEMPLATE: {"taskType": "bash"}})
        wr_data = {TASK_GROUPS: [tg_data], TASK_TEMPLATE: {"taskType": "docker"}}
        tg = _call_create_task_group(tg_data, wr_data=wr_data)
        assert tg.taskTemplate.taskType == "bash"  # type: ignore[union-attr]

    def test_task_template_set_from_config_wr(self):
        tg_data = self._tg()
        tg = _call_create_task_group(
            tg_data,
            config_wr=ConfigWorkRequirement(task_template={"taskType": "bash"}),
        )
        assert tg.taskTemplate.taskType == "bash"  # type: ignore[union-attr]

    def test_tg_level_task_template_overrides_config_wr(self):
        tg_data = self._tg(**{TASK_TEMPLATE: {"taskType": "docker"}})
        tg = _call_create_task_group(
            tg_data,
            config_wr=ConfigWorkRequirement(task_template={"taskType": "bash"}),
        )
        assert tg.taskTemplate.taskType == "docker"  # type: ignore[union-attr]

    def test_task_template_none_when_not_set(self):
        tg = _call_create_task_group(self._tg())
        assert tg.taskTemplate is None  # type: ignore[attr-defined]

    def test_task_template_partial_fields(self):
        tg_data = self._tg(**{TASK_TEMPLATE: {"taskData": "payload"}})
        tg = _call_create_task_group(tg_data)
        tmpl = tg.taskTemplate  # type: ignore[attr-defined]
        assert tmpl.taskType is None
        assert tmpl.taskData == "payload"
        assert tmpl.environment is None


# ---------------------------------------------------------------------------
# submit_work_requirement helpers
# ---------------------------------------------------------------------------


def _run_submit_wr(
    wr_data: dict | None = None,
    config_wr: ConfigWorkRequirement | None = None,
    wr_id: str = "test-wr",
    real_task_groups: bool = False,
) -> dict:
    """
    Call submit_work_requirement with all external calls mocked out.

    Returns:
      create_tg_calls:   list of (Task Group number, task_group_data) pairs
      add_tasks_calls:   list of Task Group numbers
      add_wr_mock:       the mock for CLIENT.work_client.add_work_requirement

    Set 'real_task_groups' to let the genuine create_task_group() run, which
    is what makes the ordering of its output against the Work Requirement's
    observable.
    """
    if config_wr is None:
        config_wr = ConfigWorkRequirement()

    mock_wr = _make_mock_wr(wr_id)
    add_wr_mock = MagicMock(return_value=mock_wr)

    create_tg_calls: list[tuple] = []
    add_tasks_calls: list[int] = []

    def fake_create_tg(_config_wr, position, wr_data, task_group_data, **kwargs):
        create_tg_calls.append((position.number, task_group_data))
        # Each named by its number, as a real one is by default
        return _make_mock_tg(f"task_group_{position.number + 1}")

    # Captured before the patch below replaces the module attribute
    real_create_tg = submit_module.create_task_group

    def dispatch_create_tg(*args, **kwargs):
        if real_task_groups:
            return real_create_tg(*args, **kwargs)
        return fake_create_tg(*args, **kwargs)

    def fake_add_tasks(_run, position, *args, **kwargs):
        add_tasks_calls.append(position.number)

    mock_config_common = MagicMock()
    mock_config_common.namespace = "test-ns"
    mock_config_common.name_tag = "test-tag"
    mock_config_common.url = "https://test.yellowdog.co"

    with (
        patch.object(submit_module, "CONFIG_WR", config_wr),
        patch.object(wrapper_module, "CONFIG_COMMON", mock_config_common),
        patch.object(submit_module, "RcloneUploadedFiles"),
        patch.object(
            submit_module,
            "update_config_work_requirement_object",
            side_effect=lambda x: x,
        ),
        patch.object(submit_module, "add_substitutions_without_overwriting"),
        patch.object(
            submit_module, "create_task_group", side_effect=dispatch_create_tg
        ),
        patch.object(
            submit_module, "add_tasks_to_task_group", side_effect=fake_add_tasks
        ),
        patch.object(
            wrapper_module.CLIENT.work_client,
            "add_work_requirement",
            add_wr_mock,
        ),
        patch.object(submit_module, "link_entity", return_value="[link]"),
        patch.object(
            CLIParser, "dry_run", new_callable=PropertyMock, return_value=False
        ),
        patch.object(CLIParser, "hold", new_callable=PropertyMock, return_value=False),
        patch.object(CLIParser, "quiet", new_callable=PropertyMock, return_value=False),
        patch.object(
            CLIParser, "progress", new_callable=PropertyMock, return_value=False
        ),
        patch.object(
            CLIParser, "follow", new_callable=PropertyMock, return_value=False
        ),
        patch.object(CLIParser, "empty", new_callable=PropertyMock, return_value=False),
    ):
        submit_module.submit_work_requirement(
            _submission(name=wr_id),
            files_directory=".",
            wr_data=wr_data,
        )

    return {
        "create_tg_calls": create_tg_calls,
        "add_tasks_calls": add_tasks_calls,
        "add_wr_mock": add_wr_mock,
    }


# ---------------------------------------------------------------------------
# submit_work_requirement — task_type remapping at WR level
# ---------------------------------------------------------------------------


class TestSubmitWRTaskTypeRemapping:
    def test_wr_level_task_type_promoted_to_task_types(self):
        # task_type at WR level should be lifted into task_types
        wr_data = {TASK_TYPE: "bash", TASK_GROUPS: [{TASKS: [{}]}]}
        _run_submit_wr(wr_data=wr_data)
        assert wr_data.get(TASK_TYPES) == ["bash"]

    def test_wr_level_task_type_not_overwritten_when_task_types_set(self):
        wr_data = {
            TASK_TYPE: "bash",
            TASK_TYPES: ["docker"],
            TASK_GROUPS: [{TASKS: [{}]}],
        }
        _run_submit_wr(wr_data=wr_data)
        assert wr_data[TASK_TYPES] == ["docker"]


# ---------------------------------------------------------------------------
# submit_work_requirement — WR name priority
# ---------------------------------------------------------------------------


class TestSubmitWRNamePriority:
    def _captured_wr_name(self, **kwargs) -> str:
        result = _run_submit_wr(**kwargs)
        return result["add_wr_mock"].call_args[0][0].name

    def test_wr_data_name_wins(self):
        wr_data = {
            NAME: "from-data",
            TASK_GROUPS: [{TASKS: [{}], TASK_TYPES: ["bash"]}],
        }
        name = self._captured_wr_name(wr_data=wr_data, wr_id="fallback-id")
        assert name == "from-data"

    def test_config_wr_name_used_when_wr_data_has_no_name(self):
        wr_data = {TASK_GROUPS: [{TASKS: [{}], TASK_TYPES: ["bash"]}]}
        name = self._captured_wr_name(
            wr_data=wr_data,
            config_wr=ConfigWorkRequirement(wr_name="config-name"),
            wr_id="fallback-id",
        )
        assert name == "config-name"

    def test_module_id_used_when_neither_wr_data_nor_config_has_name(self):
        wr_data = {TASK_GROUPS: [{TASKS: [{}], TASK_TYPES: ["bash"]}]}
        name = self._captured_wr_name(wr_data=wr_data, wr_id="module-id")
        assert name == "module-id"


# ---------------------------------------------------------------------------
# submit_work_requirement — task group count expansion
# ---------------------------------------------------------------------------


class TestSubmitWRTaskGroupCountExpansion:
    def test_single_tg_expanded_to_task_group_count(self):
        wr_data = {
            TASK_GROUP_COUNT: 3,
            TASK_GROUPS: [{TASKS: [{}], TASK_TYPES: ["bash"]}],
        }
        result = _run_submit_wr(wr_data=wr_data)
        assert len(result["create_tg_calls"]) == 3

    def test_multiple_tgs_not_expanded_when_task_group_count_set(self):
        # Already has 2 TGs → expansion is skipped with a warning
        wr_data = {
            TASK_GROUP_COUNT: 3,
            TASK_GROUPS: [
                {TASKS: [{}], TASK_TYPES: ["bash"]},
                {TASKS: [{}], TASK_TYPES: ["bash"]},
            ],
        }
        result = _run_submit_wr(wr_data=wr_data)
        assert len(result["create_tg_calls"]) == 2

    def test_task_group_count_of_one_does_not_expand(self):
        wr_data = {
            TASK_GROUP_COUNT: 1,
            TASK_GROUPS: [{TASKS: [{}], TASK_TYPES: ["bash"]}],
        }
        result = _run_submit_wr(wr_data=wr_data)
        assert len(result["create_tg_calls"]) == 1

    def test_create_task_group_called_per_task_group(self):
        wr_data = {
            TASK_GROUPS: [
                {TASKS: [{}], TASK_TYPES: ["bash"]},
                {TASKS: [{}], TASK_TYPES: ["docker"]},
            ]
        }
        result = _run_submit_wr(wr_data=wr_data)
        assert len(result["create_tg_calls"]) == 2
        assert result["create_tg_calls"][0][0] == 0
        assert result["create_tg_calls"][1][0] == 1


# ---------------------------------------------------------------------------
# submit_work_requirement — cleanup on failure
# ---------------------------------------------------------------------------


class TestSubmitWRCleanupOnFailure:
    @pytest.mark.parametrize(
        "error",
        [RuntimeError("upload failed"), KeyboardInterrupt()],
        ids=["failure", "interrupt"],
    )
    def test_cleanup_called_when_add_tasks_raises(self, error):
        # An interrupt too: Ctrl-C part-way used to leave the Work
        # Requirement live with only some of its Tasks
        wr_data = {TASK_GROUPS: [{TASKS: [{}], TASK_TYPES: ["bash"]}]}
        mock_wr = _make_mock_wr()
        cleanup_mock = MagicMock()

        with (
            patch.object(submit_module, "CONFIG_WR", ConfigWorkRequirement()),
            patch.object(
                wrapper_module,
                "CONFIG_COMMON",
                MagicMock(namespace="test-ns", name_tag="test-tag", url="https://test"),
            ),
            patch.object(submit_module, "RcloneUploadedFiles"),
            patch.object(
                submit_module,
                "update_config_work_requirement_object",
                side_effect=lambda x: x,
            ),
            patch.object(submit_module, "add_substitutions_without_overwriting"),
            patch.object(
                submit_module, "create_task_group", return_value=_make_mock_tg()
            ),
            patch.object(
                submit_module,
                "add_tasks_to_task_group",
                side_effect=error,
            ),
            patch.object(
                wrapper_module.CLIENT.work_client,
                "add_work_requirement",
                return_value=mock_wr,
            ),
            patch.object(submit_module, "link_entity", return_value="[link]"),
            patch.object(submit_module, "cleanup_on_failure", cleanup_mock),
            patch.object(
                CLIParser, "dry_run", new_callable=PropertyMock, return_value=False
            ),
            patch.object(
                CLIParser, "hold", new_callable=PropertyMock, return_value=False
            ),
            patch.object(
                CLIParser, "quiet", new_callable=PropertyMock, return_value=False
            ),
            patch.object(
                CLIParser, "progress", new_callable=PropertyMock, return_value=False
            ),
            patch.object(
                CLIParser, "follow", new_callable=PropertyMock, return_value=False
            ),
            patch.object(
                CLIParser, "empty", new_callable=PropertyMock, return_value=False
            ),
            pytest.raises(type(error)) as raised,
        ):
            submit_module.submit_work_requirement(
                _submission(name="test-wr"), files_directory=".", wr_data=wr_data
            )

        assert raised.value is error
        cleanup_mock.assert_called_once_with(ANY, mock_wr)


class TestSubmitWRHoldFailure:
    def test_a_failed_hold_cancels_the_work_requirement(self):
        # The Work Requirement is created, then held: a hold that fails used
        # to leave it live without its Tasks, outside the clean-up
        wr_data = {TASK_GROUPS: [{TASKS: [{}], TASK_TYPES: ["bash"]}]}
        mock_wr = _make_mock_wr()
        cleanup_mock = MagicMock()
        add_tasks_mock = MagicMock()
        error = RuntimeError("hold refused")

        with (
            patch.object(submit_module, "CONFIG_WR", ConfigWorkRequirement()),
            patch.object(
                wrapper_module,
                "CONFIG_COMMON",
                MagicMock(namespace="test-ns", name_tag="test-tag", url="https://test"),
            ),
            patch.object(submit_module, "RcloneUploadedFiles"),
            patch.object(
                submit_module,
                "update_config_work_requirement_object",
                side_effect=lambda x: x,
            ),
            patch.object(submit_module, "add_substitutions_without_overwriting"),
            patch.object(
                submit_module, "create_task_group", return_value=_make_mock_tg()
            ),
            patch.object(submit_module, "add_tasks_to_task_group", add_tasks_mock),
            patch.object(
                wrapper_module.CLIENT.work_client,
                "add_work_requirement",
                return_value=mock_wr,
            ),
            patch.object(
                wrapper_module.CLIENT.work_client,
                "hold_work_requirement",
                side_effect=error,
            ),
            patch.object(submit_module, "link_entity", return_value="[link]"),
            patch.object(submit_module, "cleanup_on_failure", cleanup_mock),
            patch.object(
                CLIParser, "dry_run", new_callable=PropertyMock, return_value=False
            ),
            patch.object(
                CLIParser, "hold", new_callable=PropertyMock, return_value=True
            ),
            patch.object(
                CLIParser, "quiet", new_callable=PropertyMock, return_value=False
            ),
            patch.object(
                CLIParser, "progress", new_callable=PropertyMock, return_value=False
            ),
            patch.object(
                CLIParser, "follow", new_callable=PropertyMock, return_value=False
            ),
            patch.object(
                CLIParser, "empty", new_callable=PropertyMock, return_value=False
            ),
            pytest.raises(RuntimeError) as raised,
        ):
            submit_module.submit_work_requirement(
                _submission(name="test-wr"), files_directory=".", wr_data=wr_data
            )

        assert raised.value is error
        cleanup_mock.assert_called_once_with(ANY, mock_wr)
        add_tasks_mock.assert_not_called()


class TestCleanupOnFailure:
    """
    A step of the cleanup that fails is reported, and the rest still made,
    without the cleanup raising: the failure the caller re-raises, the one
    being cleaned up after, is what the command must report.
    """

    def _cleanup(self, cancel_error=None, delete_error=None) -> dict:
        client = MagicMock()
        client.work_client.cancel_work_requirement.side_effect = cancel_error
        uploaded = MagicMock()
        uploaded.delete.side_effect = delete_error
        with (
            patch.object(wrapper_module, "CLIENT", client),
            patch.object(
                CLIParser, "dry_run", new_callable=PropertyMock, return_value=False
            ),
        ):
            submit_module.cleanup_on_failure(
                _submission(uploaded_files=uploaded), _make_mock_wr()
            )
        return {"client": client, "uploaded": uploaded}

    def test_a_failed_cancel_still_deletes_the_uploaded_files(self, capsys):
        result = self._cleanup(cancel_error=RuntimeError("cancel refused"))
        result["uploaded"].delete.assert_called_once()
        assert "cancel refused" in capsys.readouterr().err

    def test_a_failed_delete_does_not_raise(self, capsys):
        self._cleanup(delete_error=RuntimeError("rclone failed"))
        assert "rclone failed" in capsys.readouterr().err

    def test_both_steps_are_made_when_neither_fails(self):
        result = self._cleanup()
        result["client"].work_client.cancel_work_requirement.assert_called_once()
        result["uploaded"].delete.assert_called_once()


# ---------------------------------------------------------------------------
# submit_work_requirement — announcing what was generated
# ---------------------------------------------------------------------------


class TestSubmitWRGeneratedMessage:
    """
    The Work Requirement is announced as it is generated, as each Task Group
    already was — so a dry run names it without having to read the JSON.
    """

    def test_the_work_requirement_is_announced(self, capsys):
        wr_data = {
            NAME: "from-data",
            TASK_GROUPS: [{TASKS: [{}], TASK_TYPES: ["bash"]}],
        }
        _run_submit_wr(wr_data=wr_data)
        assert "Generated Work Requirement 'from-data'" in capsys.readouterr().out

    def test_the_announced_name_is_the_resolved_one(self, capsys):
        # Not the incoming default: the name actually submitted
        _run_submit_wr(
            wr_data={TASK_GROUPS: [{TASKS: [{}], TASK_TYPES: ["bash"]}]},
            wr_id="generated-fallback-id",
        )
        assert (
            "Generated Work Requirement 'generated-fallback-id'"
            in capsys.readouterr().out
        )

    def test_it_precedes_its_task_groups(self, capsys):
        wr_data = {
            NAME: "from-data",
            TASK_GROUPS: [{TASKS: [{}], TASK_TYPES: ["bash"]}],
        }
        _run_submit_wr(wr_data=wr_data, real_task_groups=True)
        output = capsys.readouterr().out
        assert "Generated Work Requirement 'from-data'" in output
        assert "Generated Task Group" in output
        assert output.index("Generated Work Requirement") < output.index(
            "Generated Task Group"
        ), output


# ---------------------------------------------------------------------------
# submit_work_requirement — a whole-valued float taskGroupCount
# ---------------------------------------------------------------------------


class TestSubmitWRTaskGroupCountAsFloat:
    """
    The schema accepts 2.0 as an integer, as JSON Schema does; range() does
    not, so it used to raise "'float' object cannot be interpreted as an
    integer".
    """

    def test_a_whole_valued_float_expands(self):
        wr_data = {
            TASK_GROUP_COUNT: 2.0,
            TASK_GROUPS: [{TASKS: [{}], TASK_TYPES: ["bash"]}],
        }
        assert len(_run_submit_wr(wr_data=wr_data)["create_tg_calls"]) == 2

    def test_a_fractional_count_is_a_type_error_naming_the_property(self):
        wr_data = {
            TASK_GROUP_COUNT: 2.5,
            TASK_GROUPS: [{TASKS: [{}], TASK_TYPES: ["bash"]}],
        }
        with pytest.raises(TypeError, match=f"'{TASK_GROUP_COUNT}' value '2.5'"):
            _run_submit_wr(wr_data=wr_data)


# ---------------------------------------------------------------------------
# generate_batch_of_tasks — Task Group over Work Requirement
# ---------------------------------------------------------------------------


def _generate_one_task(wr_data: dict) -> Task:
    """
    Generate the single Task of wr_data's single Task Group, as submission
    would, with nothing uploaded.
    """
    task_group = MagicMock()
    task_group.name = "tg"
    task_group.runSpecification.taskTypes = ["bash"]
    (task,) = task_generation_module.generate_batch_of_tasks(
        task_generation_module.TaskSource(
            config_wr=ConfigWorkRequirement(),
            wr_name="test-wr",
            namespace="test-ns",
            wr_data=wr_data,
            files_directory=".",
            task_group=task_group,
            position=TaskGroupPosition(0, 0, 1),
            tasks=wr_data[TASK_GROUPS][0][TASKS],
            task_count=None,
            num_tasks=1,
            uploaded_files=MagicMock(),
        ),
        0,
        1,
    )
    return task


class TestTaskPropertiesTaskGroupOverWorkRequirement:
    """
    Task > Task Group > Work Requirement > TOML. 'arguments',
    'argumentsPrefix', 'argumentsPostfix' and 'addEnvironment' used to look at
    the Work Requirement before the Task Group, so a Task Group's own value
    was lost whenever the Work Requirement set one too.
    """

    @pytest.mark.parametrize("prop", [ARGS, ARGS_PREFIX, ARGS_POSTFIX])
    def test_task_group_arguments_win(self, prop):
        wr_data = {
            prop: ["wr"],
            TASK_GROUPS: [{prop: ["tg"], TASKS: [{}]}],
        }
        assert _generate_one_task(wr_data).arguments == ["tg"]

    @pytest.mark.parametrize("prop", [ARGS, ARGS_PREFIX, ARGS_POSTFIX])
    def test_work_requirement_arguments_are_inherited(self, prop):
        wr_data = {prop: ["wr"], TASK_GROUPS: [{TASKS: [{}]}]}
        assert _generate_one_task(wr_data).arguments == ["wr"]

    def test_task_arguments_win_over_both(self):
        wr_data = {
            ARGS: ["wr"],
            TASK_GROUPS: [{ARGS: ["tg"], TASKS: [{ARGS: ["task"]}]}],
        }
        assert _generate_one_task(wr_data).arguments == ["task"]

    def test_task_group_add_environment_wins(self):
        wr_data = {
            ADD_ENVIRONMENT: {"X": "wr"},
            TASK_GROUPS: [{ADD_ENVIRONMENT: {"X": "tg"}, TASKS: [{}]}],
        }
        assert _generate_one_task(wr_data).environment == {"X": "tg"}

    def test_work_requirement_add_environment_is_inherited(self):
        wr_data = {ADD_ENVIRONMENT: {"X": "wr"}, TASK_GROUPS: [{TASKS: [{}]}]}
        assert _generate_one_task(wr_data).environment == {"X": "wr"}


def _generate_tasks(wr_data: dict, files_directory: str = ".") -> list[Task]:
    """
    Generate every Task of wr_data's single Task Group, as submission would,
    with nothing uploaded.
    """
    task_group = MagicMock()
    task_group.name = "tg"
    task_group.runSpecification.taskTypes = ["bash"]
    tasks = wr_data[TASK_GROUPS][0][TASKS]
    return task_generation_module.generate_batch_of_tasks(
        task_generation_module.TaskSource(
            config_wr=ConfigWorkRequirement(),
            wr_name="test-wr",
            namespace="test-ns",
            wr_data=wr_data,
            files_directory=files_directory,
            task_group=task_group,
            position=TaskGroupPosition(0, 0, 1),
            tasks=tasks,
            task_count=None,
            num_tasks=len(tasks),
            uploaded_files=MagicMock(),
        ),
        0,
        len(tasks),
    )


class TestInheritedPropertiesSubstitutedPerTask:
    """
    '{{task_name}}' and '{{task_number}}' in a property a Task inherits from
    its Task Group or the Work Requirement are the Task's, as in its own
    properties and the configuration's. Those levels are substituted as the
    Task Groups are built, before any Task exists, and the inherited values
    were passed on with the references left in them.
    """

    @staticmethod
    def _named(**task_group) -> dict:
        return {TASK_GROUPS: [{**task_group, TASKS: [{NAME: "a"}, {NAME: "b"}]}]}

    def test_task_group_arguments(self):
        wr_data = self._named(**{ARGS: ["{{task_name}}", "{{task_number}}"]})
        assert [t.arguments for t in _generate_tasks(wr_data)] == [
            ["a", "1"],
            ["b", "2"],
        ]

    def test_work_requirement_environment(self):
        wr_data = {ENV: {"N": "{{task_name}}"}, **self._named()}
        assert [t.environment for t in _generate_tasks(wr_data)] == [
            {"N": "a"},
            {"N": "b"},
        ]

    def test_task_group_inline_task_data(self):
        wr_data = self._named(**{TASK_DATA: "for {{task_name}}"})
        assert [t.taskData for t in _generate_tasks(wr_data)] == ["for a", "for b"]

    def test_task_group_task_data_file_path(self, tmp_path):
        for name in ("a", "b"):
            (tmp_path / f"data-{name}.txt").write_text(name, encoding="utf-8")
        wr_data = self._named(**{TASK_DATA_FILE: "data-{{task_name}}.txt"})
        assert [t.taskData for t in _generate_tasks(wr_data, str(tmp_path))] == [
            "a",
            "b",
        ]

    def test_task_group_data_inputs(self):
        wr_data = self._named(
            **{TASK_DATA_INPUTS: [{"source": "in/{{task_name}}", "destination": "x"}]}
        )
        assert [t.data.inputs[0].source for t in _generate_tasks(wr_data)] == [
            "in/a",
            "in/b",
        ]

    def test_the_inherited_value_stays_as_written(self):
        wr_data = self._named(**{ARGS: ["{{task_name}}"]})
        _generate_tasks(wr_data)
        assert wr_data[TASK_GROUPS][0][ARGS] == ["{{task_name}}"]


# ---------------------------------------------------------------------------
# create_task_group — the order of taskTypes, and the tag's type
# ---------------------------------------------------------------------------


class TestCreateTaskGroupTaskTypeOrder:
    """
    The types were gathered through a set, whose order varies from run to
    run with string hashing, so a dry run's output did too. Declared types
    come first, in order, then the Tasks' own, in order of first appearance.
    """

    def test_declared_types_then_the_tasks_types_in_order(self):
        tg = _call_create_task_group(
            {
                TASK_TYPES: ["zeta", "alpha"],
                TASKS: [
                    {TASK_TYPE: "mu"},
                    {TASK_TYPE: "alpha"},
                    {TASK_TYPE: "beta"},
                    {TASK_TYPE: "mu"},
                ],
            }
        )
        assert tg.runSpecification.taskTypes == ["zeta", "alpha", "mu", "beta"]


class TestCreateTaskGroupTag:
    def test_a_string_tag_is_used(self):
        tg = _call_create_task_group(
            {TASK_TYPES: ["bash"], TASK_GROUP_TAG: "t", TASKS: [{}]}
        )
        assert tg.tag == "t"

    def test_a_non_string_tag_is_a_type_error_naming_the_property(self):
        with pytest.raises(TypeError, match=f"'{TASK_GROUP_TAG}'"):
            _call_create_task_group(
                {TASK_TYPES: ["bash"], TASK_GROUP_TAG: 7, TASKS: [{}]}
            )


class TestExitOnFailure:
    """
    yd-submit's --exit-on-failure after following: the code of a Work
    Requirement that failed or could not be followed to its end; without
    the option, nothing, the exit code reflecting the submission alone.
    """

    @staticmethod
    def _run(exit_on_failure: bool):
        from types import SimpleNamespace

        return SimpleNamespace(
            ctx=SimpleNamespace(args=SimpleNamespace(exit_on_failure=exit_on_failure))
        )

    def test_the_outcomes_code_is_the_exit_code(self):
        from yellowdog_cli.utils.exit_codes import ExitCode

        with (
            patch.object(
                submit_module,
                "work_requirement_exit_code",
                return_value=ExitCode.CONNECTION,
            ),
            pytest.raises(SystemExit) as exited,
        ):
            submit_module._exit_on_failure(self._run(True), "wr-id")  # type: ignore[arg-type]
        assert exited.value.code == ExitCode.CONNECTION

    def test_a_successful_outcome_does_not_exit(self):
        from yellowdog_cli.utils.exit_codes import ExitCode

        with patch.object(
            submit_module, "work_requirement_exit_code", return_value=ExitCode.SUCCESS
        ):
            submit_module._exit_on_failure(self._run(True), "wr-id")  # type: ignore[arg-type]

    def test_without_the_option_the_outcome_is_not_fetched(self):
        with patch.object(submit_module, "work_requirement_exit_code") as outcome:
            submit_module._exit_on_failure(self._run(False), "wr-id")  # type: ignore[arg-type]
        outcome.assert_not_called()


class TestDuplicateTaskGroupNamesAreRefused:
    """
    Tasks are added to a Task Group by its name, so two Task Groups of one
    name would share them, or the Platform refuse the second; refused once
    the Task Groups are named, before the Work Requirement is created.
    """

    @pytest.mark.parametrize(
        "wr_data",
        [
            # 'taskGroupCount' copies of a Task Group named without its number
            {
                TASK_GROUP_COUNT: 2,
                TASK_GROUPS: [{NAME: "render", TASKS: [{}], TASK_TYPES: ["bash"]}],
            },
            {
                TASK_GROUPS: [
                    {NAME: "render", TASKS: [{}], TASK_TYPES: ["bash"]},
                    {NAME: "render", TASKS: [{}], TASK_TYPES: ["bash"]},
                ]
            },
        ],
    )
    def test_refused(self, wr_data):
        with pytest.raises(ValueError, match="'render'") as raised:
            _run_submit_wr(wr_data=wr_data, real_task_groups=True)
        assert "more than one Task Group" in str(raised.value)

    def test_numbered_copies_are_not_duplicates(self):
        wr_data = {
            TASK_GROUP_COUNT: 2,
            TASK_GROUPS: [{TASKS: [{}], TASK_TYPES: ["bash"]}],
        }
        result = _run_submit_wr(wr_data=wr_data, real_task_groups=True)
        result["add_wr_mock"].assert_called_once()
