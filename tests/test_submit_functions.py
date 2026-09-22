"""
Tests for create_task_group and submit_work_requirement in submit.py.
"""

from datetime import timedelta
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from yellowdog_client.model import (
    CloudProvider,
    DoubleRange,
    TaskGroup,
    TaskTemplate,
    WorkRequirement,
)
from yellowdog_client.model.instance_pricing_preference import InstancePricingPreference

import yellowdog_cli.submit as submit_module
from yellowdog_cli.utils.args import CLIParser
from yellowdog_cli.utils.config_types import ConfigWorkRequirement
from yellowdog_cli.utils.property_names import (
    COMPLETED_TASK_TTL,
    INSTANCE_PRICING_PREFERENCE,
    NAME,
    PROVIDERS,
    RAM,
    TASK_GROUP_COUNT,
    TASK_GROUPS,
    TASK_TEMPLATE,
    TASK_TIMEOUT,
    TASK_TYPE,
    TASK_TYPES,
    TASKS,
    VCPUS,
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
        patch.object(submit_module, "CONFIG_WR", config_wr),
        patch.object(
            submit_module,
            "update_config_work_requirement_object",
            side_effect=lambda x: x,
        ),
        patch.object(submit_module, "generate_dependencies", return_value=[]),
        patch.object(
            submit_module, "generate_task_error_matchers_list", return_value=[]
        ),
    ):
        return submit_module.create_task_group(
            tg_number=tg_number,
            wr_data=wr_data,
            task_group_data=task_group_data,
        )


# ---------------------------------------------------------------------------
# create_task_group — task type resolution
# ---------------------------------------------------------------------------


class TestCreateTaskGroupTaskTypes:
    """Task type resolution: remapping, unioning, fallback chain."""

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
    """vcpus, ram, providers, instance_pricing_preference conversions."""

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
    """task_timeout and completed_task_ttl → timedelta conversions."""

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


# ---------------------------------------------------------------------------
# create_task_group — naming
# ---------------------------------------------------------------------------


class TestCreateTaskGroupNaming:
    """Auto-naming and explicit naming of task groups."""

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
    """taskTemplate propagation to the TaskGroup object."""

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
      create_tg_calls:   list of (tg_number, task_group_data) pairs
      add_tasks_calls:   list of tg_number values
      add_wr_mock:       the mock for CLIENT.work_client.add_work_requirement

    Set 'real_task_groups' to let the genuine create_task_group() run, which
    is what makes the ordering of its output against the Work Requirement's
    observable.
    """
    if config_wr is None:
        config_wr = ConfigWorkRequirement()

    mock_wr = _make_mock_wr(wr_id)
    mock_tg = _make_mock_tg()
    add_wr_mock = MagicMock(return_value=mock_wr)

    create_tg_calls: list[tuple] = []
    add_tasks_calls: list[int] = []

    def fake_create_tg(tg_number, wr_data, task_group_data, **kwargs):
        create_tg_calls.append((tg_number, task_group_data))
        return mock_tg

    # Captured before the patch below replaces the module attribute
    real_create_tg = submit_module.create_task_group

    def dispatch_create_tg(*args, **kwargs):
        if real_task_groups:
            return real_create_tg(*args, **kwargs)
        return fake_create_tg(*args, **kwargs)

    def fake_add_tasks(tg_number, *args, **kwargs):
        add_tasks_calls.append(tg_number)

    mock_config_common = MagicMock()
    mock_config_common.namespace = "test-ns"
    mock_config_common.name_tag = "test-tag"
    mock_config_common.url = "https://test.yellowdog.co"

    with (
        patch.object(submit_module, "CONFIG_WR", config_wr),
        patch.object(submit_module, "CONFIG_COMMON", mock_config_common),
        patch.object(submit_module, "ID", wr_id),
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
            submit_module.CLIENT.work_client,
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
    def test_cleanup_called_when_add_tasks_raises(self):
        wr_data = {TASK_GROUPS: [{TASKS: [{}], TASK_TYPES: ["bash"]}]}
        mock_wr = _make_mock_wr()
        cleanup_mock = MagicMock()

        with (
            patch.object(submit_module, "CONFIG_WR", ConfigWorkRequirement()),
            patch.object(
                submit_module,
                "CONFIG_COMMON",
                MagicMock(namespace="test-ns", name_tag="test-tag", url="https://test"),
            ),
            patch.object(submit_module, "ID", "test-wr"),
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
                side_effect=RuntimeError("upload failed"),
            ),
            patch.object(
                submit_module.CLIENT.work_client,
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
            pytest.raises(RuntimeError, match="upload failed"),
        ):
            submit_module.submit_work_requirement(files_directory=".", wr_data=wr_data)

        cleanup_mock.assert_called_once_with(mock_wr)


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
