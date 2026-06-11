"""
Unit tests for compute_action_common.py.

Covers:
  - apply_compute_action            (dispatch + tag-based interactive path)
  - _apply_action_by_name_or_id     (named/ID path)
  - _apply_action_to_instance       (instance-level actions)
  - _apply_action_to_node_instance_by_id  (node-level actions)
"""

from unittest.mock import MagicMock, patch

import pytest
from yellowdog_client.model import ComputeRequirementStatus, InstanceStatus

import yellowdog_cli.utils.compute_action_common as cac_module
from yellowdog_cli.utils.compute_action_common import (
    COMPUTE_RESTART,
    COMPUTE_START,
    COMPUTE_STOP,
    _apply_action_by_name_or_id,
    _apply_action_to_instance,
    _apply_action_to_node_instance_by_id,
    apply_compute_action,
)

CR_ID = "ydid:compreq:d9c548:98879b5a-9192-4a56-ad25-fc1330e49185"
CR_ID_2 = "ydid:compreq:d9c548:11111111-2222-3333-4444-555555555555"
NODE_ID = "ydid:node:d9c548:f9d5a10e-5b0e-4b76-b50f-d2bbac0a5cb8"
INSTANCE_ID = "i-0123456789abcdef0"
INSTANCE_SPEC = f"{CR_ID}.{INSTANCE_ID}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cr_summary(
    id_: str = CR_ID,
    name: str = "test-cr",
    status: ComputeRequirementStatus = ComputeRequirementStatus.RUNNING,
) -> MagicMock:
    summary = MagicMock()
    summary.id = id_
    summary.name = name
    summary.status = status
    return summary


def _make_instance(status: InstanceStatus = InstanceStatus.RUNNING) -> MagicMock:
    instance = MagicMock()
    instance.status = status
    instance.id.instanceId = INSTANCE_ID
    return instance


def _config_common(
    namespace: str = "test-ns",
    name_tag: str = "test-tag",
    url: str = "https://test",
) -> MagicMock:
    return MagicMock(namespace=namespace, name_tag=name_tag, url=url)


def _make_args(
    names_or_ids: list[str] | None = None, follow: bool = False
) -> MagicMock:
    mock_args = MagicMock()
    mock_args.compute_requirements_instances_or_nodes = names_or_ids
    mock_args.follow = follow
    return mock_args


# ---------------------------------------------------------------------------
# apply_compute_action: dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_dispatches_to_named_path_when_names_provided(self):
        with (
            patch.object(cac_module, "ARGS_PARSER", _make_args([CR_ID])),
            patch.object(cac_module, "_apply_action_by_name_or_id") as mock_by_name,
            patch.object(
                cac_module, "get_compute_requirement_summaries"
            ) as mock_summaries,
        ):
            apply_compute_action(COMPUTE_STOP)

        mock_by_name.assert_called_once_with(COMPUTE_STOP, [CR_ID])
        mock_summaries.assert_not_called()

    def test_restart_without_names_prints_error_and_does_not_list(self):
        with (
            patch.object(cac_module, "ARGS_PARSER", _make_args(None)),
            patch.object(cac_module, "print_error") as mock_error,
            patch.object(
                cac_module, "get_compute_requirement_summaries"
            ) as mock_summaries,
        ):
            apply_compute_action(COMPUTE_RESTART)

        mock_error.assert_called_once()
        mock_summaries.assert_not_called()


# ---------------------------------------------------------------------------
# apply_compute_action: tag-based interactive path
# ---------------------------------------------------------------------------


class TestTagBasedPath:
    def _call(
        self,
        action,
        summaries: list,
        selected: list | None = None,
        confirm_result: bool = True,
        follow: bool = False,
        action_raises: Exception | None = None,
    ) -> tuple:
        if selected is None:
            selected = summaries

        mock_client = MagicMock()
        if action_raises is not None:
            getattr(
                mock_client.compute_client, action.cr_method_name
            ).side_effect = action_raises

        with (
            patch.object(cac_module, "ARGS_PARSER", _make_args(None, follow=follow)),
            patch.object(cac_module, "CLIENT", mock_client),
            patch.object(cac_module, "CONFIG_COMMON", _config_common()),
            patch.object(
                cac_module,
                "get_compute_requirement_summaries",
                return_value=summaries,
            ) as mock_get_summaries,
            patch.object(cac_module, "select", return_value=selected),
            patch.object(cac_module, "confirmed", return_value=confirm_result),
            patch.object(cac_module, "print_error") as mock_error,
            patch.object(cac_module, "print_info"),
            patch.object(cac_module, "link_entity", return_value="<link>"),
            patch.object(cac_module, "follow_ids") as mock_follow,
        ):
            apply_compute_action(action)

        return mock_client, mock_get_summaries, mock_error, mock_follow

    def test_stop_calls_stop_method_for_each_selected_cr(self):
        summaries = [_make_cr_summary(CR_ID), _make_cr_summary(CR_ID_2)]
        mock_client, _, mock_error, _ = self._call(COMPUTE_STOP, summaries)
        assert mock_client.compute_client.stop_compute_requirement_by_id.call_count == 2
        mock_error.assert_not_called()

    def test_start_calls_start_method(self):
        summaries = [_make_cr_summary(status=ComputeRequirementStatus.STOPPED)]
        mock_client, _, _, _ = self._call(COMPUTE_START, summaries)
        mock_client.compute_client.start_compute_requirement_by_id.assert_called_once_with(
            CR_ID
        )

    def test_summaries_filtered_by_action_valid_statuses(self):
        _, mock_get_summaries, _, _ = self._call(COMPUTE_STOP, [])
        assert mock_get_summaries.call_args.args[3] == COMPUTE_STOP.valid_cr_statuses

    def test_no_crs_found_no_action(self):
        mock_client, _, _, _ = self._call(COMPUTE_STOP, [])
        mock_client.compute_client.stop_compute_requirement_by_id.assert_not_called()

    def test_not_confirmed_no_action(self):
        mock_client, _, _, _ = self._call(
            COMPUTE_STOP, [_make_cr_summary()], confirm_result=False
        )
        mock_client.compute_client.stop_compute_requirement_by_id.assert_not_called()

    def test_select_filters_summaries_before_action(self):
        summaries = [_make_cr_summary(CR_ID), _make_cr_summary(CR_ID_2)]
        mock_client, _, _, _ = self._call(
            COMPUTE_STOP, summaries, selected=[summaries[0]]
        )
        mock_client.compute_client.stop_compute_requirement_by_id.assert_called_once_with(
            CR_ID
        )

    def test_action_exception_prints_error(self):
        _, _, mock_error, _ = self._call(
            COMPUTE_STOP,
            [_make_cr_summary()],
            action_raises=RuntimeError("API failure"),
        )
        mock_error.assert_called_once()

    def test_follow_calls_follow_ids_with_selected_cr_ids(self):
        summaries = [_make_cr_summary(CR_ID)]
        _, _, _, mock_follow = self._call(COMPUTE_STOP, summaries, follow=True)
        mock_follow.assert_called_once_with([CR_ID])

    def test_no_follow_when_nothing_actioned(self):
        _, _, _, mock_follow = self._call(COMPUTE_STOP, [], follow=True)
        mock_follow.assert_not_called()


# ---------------------------------------------------------------------------
# _apply_action_by_name_or_id
# ---------------------------------------------------------------------------


class TestByNameOrId:
    def _call(
        self,
        action,
        names_or_ids: list[str],
        cr_status: ComputeRequirementStatus = ComputeRequirementStatus.RUNNING,
        confirm_result: bool = True,
        follow: bool = False,
        get_cr_raises: Exception | None = None,
        name_lookup_result: str | None = None,
    ) -> tuple:
        mock_client = MagicMock()
        if get_cr_raises is not None:
            mock_client.compute_client.get_compute_requirement_by_id.side_effect = (
                get_cr_raises
            )
        else:
            mock_client.compute_client.get_compute_requirement_by_id.return_value = (
                MagicMock(status=cr_status)
            )

        with (
            patch.object(cac_module, "ARGS_PARSER", _make_args(follow=follow)),
            patch.object(cac_module, "CLIENT", mock_client),
            patch.object(cac_module, "CONFIG_COMMON", _config_common()),
            patch.object(cac_module, "confirmed", return_value=confirm_result),
            patch.object(
                cac_module,
                "get_compute_requirement_id_by_name",
                return_value=name_lookup_result,
            ) as mock_name_lookup,
            patch.object(cac_module, "print_error") as mock_error,
            patch.object(cac_module, "print_warning") as mock_warning,
            patch.object(cac_module, "print_info"),
            patch.object(cac_module, "follow_ids") as mock_follow,
        ):
            _apply_action_by_name_or_id(action, names_or_ids)

        return mock_client, mock_error, mock_warning, mock_follow, mock_name_lookup

    def test_cr_ydid_valid_status_actioned(self):
        mock_client, mock_error, _, _, _ = self._call(COMPUTE_STOP, [CR_ID])
        mock_client.compute_client.stop_compute_requirement_by_id.assert_called_once_with(
            CR_ID
        )
        mock_error.assert_not_called()

    def test_cr_ydid_invalid_status_not_actioned(self):
        mock_client, mock_error, _, _, _ = self._call(
            COMPUTE_STOP, [CR_ID], cr_status=ComputeRequirementStatus.STOPPED
        )
        mock_client.compute_client.stop_compute_requirement_by_id.assert_not_called()
        mock_error.assert_called_once()

    def test_start_requires_stopped_status(self):
        mock_client, _, _, _, _ = self._call(
            COMPUTE_START, [CR_ID], cr_status=ComputeRequirementStatus.STOPPED
        )
        mock_client.compute_client.start_compute_requirement_by_id.assert_called_once_with(
            CR_ID
        )

    def test_cr_ydid_not_found_prints_error(self):
        mock_client, mock_error, _, _, _ = self._call(
            COMPUTE_STOP, [CR_ID], get_cr_raises=RuntimeError("404 not found")
        )
        mock_client.compute_client.stop_compute_requirement_by_id.assert_not_called()
        mock_error.assert_called_once()

    def test_cr_name_lookup_found_and_actioned(self):
        mock_client, _, _, _, mock_name_lookup = self._call(
            COMPUTE_STOP, ["my-cr-name"], name_lookup_result=CR_ID
        )
        mock_client.compute_client.stop_compute_requirement_by_id.assert_called_once_with(
            CR_ID
        )
        assert mock_name_lookup.call_args.args[3] == COMPUTE_STOP.valid_cr_statuses

    def test_cr_name_lookup_not_found_prints_warning(self):
        mock_client, _, mock_warning, _, _ = self._call(
            COMPUTE_STOP, ["my-cr-name"], name_lookup_result=None
        )
        mock_client.compute_client.stop_compute_requirement_by_id.assert_not_called()
        mock_warning.assert_called_once()

    @pytest.mark.parametrize("name_or_id", [CR_ID, "my-cr-name"])
    def test_restart_rejects_compute_requirements(self, name_or_id):
        mock_client, mock_error, _, _, _ = self._call(COMPUTE_RESTART, [name_or_id])
        mock_error.assert_called_once()
        mock_client.compute_client.restart_instances.assert_not_called()

    def test_not_confirmed_no_action(self):
        mock_client, _, _, _, _ = self._call(
            COMPUTE_STOP, [CR_ID], confirm_result=False
        )
        mock_client.compute_client.stop_compute_requirement_by_id.assert_not_called()

    def test_duplicate_names_actioned_once(self):
        mock_client, _, _, _, _ = self._call(COMPUTE_STOP, [CR_ID, CR_ID])
        mock_client.compute_client.stop_compute_requirement_by_id.assert_called_once_with(
            CR_ID
        )

    def test_cr_name_containing_dot_routes_to_name_lookup(self):
        # A CR *name* with one dot must not be misclassified as an
        # instance spec ('cr_id.instance_id')
        mock_client, _, _, _, mock_name_lookup = self._call(
            COMPUTE_STOP, ["my.cr-name"], name_lookup_result=CR_ID
        )
        assert mock_name_lookup.call_args.args[1] == "my.cr-name"
        mock_client.compute_client.stop_compute_requirement_by_id.assert_called_once_with(
            CR_ID
        )

    def test_instance_spec_routes_to_instance_action(self):
        with (
            patch.object(cac_module, "ARGS_PARSER", _make_args(follow=True)),
            patch.object(
                cac_module, "_apply_action_to_instance", return_value=CR_ID
            ) as mock_instance_action,
            patch.object(cac_module, "follow_ids") as mock_follow,
        ):
            _apply_action_by_name_or_id(COMPUTE_RESTART, [INSTANCE_SPEC])

        mock_instance_action.assert_called_once_with(
            COMPUTE_RESTART, CR_ID, INSTANCE_ID
        )
        mock_follow.assert_called_once_with([CR_ID])

    def test_node_ydid_routes_to_node_action(self):
        with (
            patch.object(cac_module, "ARGS_PARSER", _make_args(follow=True)),
            patch.object(
                cac_module,
                "_apply_action_to_node_instance_by_id",
                return_value=CR_ID,
            ) as mock_node_action,
            patch.object(cac_module, "follow_ids") as mock_follow,
        ):
            _apply_action_by_name_or_id(COMPUTE_STOP, [NODE_ID])

        mock_node_action.assert_called_once_with(COMPUTE_STOP, NODE_ID)
        mock_follow.assert_called_once_with([CR_ID])

    def test_follow_called_with_actioned_cr_ids(self):
        _, _, _, mock_follow, _ = self._call(COMPUTE_STOP, [CR_ID], follow=True)
        mock_follow.assert_called_once_with([CR_ID])


# ---------------------------------------------------------------------------
# _apply_action_to_instance
# ---------------------------------------------------------------------------


class TestApplyActionToInstance:
    def _call(
        self,
        action,
        cr_id: str = CR_ID,
        instance: MagicMock | str | None = "default",
        confirm_result: bool = True,
        get_cr_raises: Exception | None = None,
        instance_action_raises: Exception | None = None,
    ) -> tuple:
        if instance == "default":
            instance = _make_instance(status=action.valid_instance_statuses[0])

        mock_client = MagicMock()
        if get_cr_raises is not None:
            mock_client.compute_client.get_compute_requirement_by_id.side_effect = (
                get_cr_raises
            )
        if instance_action_raises is not None:
            getattr(
                mock_client.compute_client, action.instance_method_name
            ).side_effect = instance_action_raises

        with (
            patch.object(cac_module, "CLIENT", mock_client),
            patch.object(cac_module, "get_instance_id_by_id", return_value=instance),
            patch.object(cac_module, "confirmed", return_value=confirm_result),
            patch.object(cac_module, "print_error") as mock_error,
            patch.object(cac_module, "print_info"),
        ):
            result = _apply_action_to_instance(action, cr_id, INSTANCE_ID)

        return result, mock_client, mock_error

    def test_invalid_cr_id_returns_none(self):
        result, _, mock_error = self._call(COMPUTE_STOP, cr_id="not-a-ydid")
        assert result is None
        mock_error.assert_called_once()

    def test_cr_not_found_returns_none(self):
        result, _, mock_error = self._call(
            COMPUTE_STOP, get_cr_raises=RuntimeError("404")
        )
        assert result is None
        mock_error.assert_called_once()

    def test_instance_not_found_returns_none(self):
        result, _, mock_error = self._call(COMPUTE_STOP, instance=None)
        assert result is None
        mock_error.assert_called_once()

    def test_invalid_instance_status_returns_none(self):
        result, mock_client, mock_error = self._call(
            COMPUTE_STOP, instance=_make_instance(status=InstanceStatus.STOPPED)
        )
        assert result is None
        mock_client.compute_client.stop_instances.assert_not_called()
        mock_error.assert_called_once()

    def test_not_confirmed_returns_none(self):
        result, mock_client, _ = self._call(COMPUTE_STOP, confirm_result=False)
        assert result is None
        mock_client.compute_client.stop_instances.assert_not_called()

    @pytest.mark.parametrize(
        "action,method_name",
        [
            (COMPUTE_STOP, "stop_instances"),
            (COMPUTE_START, "start_instances"),
            (COMPUTE_RESTART, "restart_instances"),
        ],
    )
    def test_success_calls_instance_method_and_returns_cr_id(self, action, method_name):
        instance = _make_instance(status=action.valid_instance_statuses[0])
        result, mock_client, mock_error = self._call(action, instance=instance)
        assert result == CR_ID
        getattr(mock_client.compute_client, method_name).assert_called_once_with(
            mock_client.compute_client.get_compute_requirement_by_id.return_value,
            [instance],
        )
        mock_error.assert_not_called()

    def test_instance_action_exception_returns_none_and_prints_error(self):
        result, _, mock_error = self._call(
            COMPUTE_STOP, instance_action_raises=RuntimeError("API failure")
        )
        assert result is None
        mock_error.assert_called_once()

    def test_invalid_cr_status_exception_prints_error(self):
        result, _, mock_error = self._call(
            COMPUTE_STOP,
            instance_action_raises=RuntimeError(
                "InvalidComputeRequirementStatusException"
            ),
        )
        assert result is None
        mock_error.assert_called_once()


# ---------------------------------------------------------------------------
# _apply_action_to_node_instance_by_id
# ---------------------------------------------------------------------------


class TestApplyActionToNodeInstance:
    def _call(
        self,
        action,
        node_raises: Exception | None = None,
        worker_pool_cr_id: str | None = CR_ID,
        instance: MagicMock | str | None = "default",
    ) -> tuple:
        if instance == "default":
            instance = _make_instance(status=action.valid_instance_statuses[0])

        mock_client = MagicMock()
        if node_raises is not None:
            mock_client.worker_pool_client.get_node_by_id.side_effect = node_raises

        with (
            patch.object(cac_module, "CLIENT", mock_client),
            patch.object(
                cac_module,
                "get_compute_requirement_id_by_worker_pool_id",
                return_value=worker_pool_cr_id,
            ),
            patch.object(cac_module, "get_instance_id_by_id", return_value=instance),
            patch.object(
                cac_module, "_apply_action_to_instance", return_value=CR_ID
            ) as mock_instance_action,
            patch.object(cac_module, "print_error") as mock_error,
            patch.object(cac_module, "print_info"),
        ):
            result = _apply_action_to_node_instance_by_id(action, NODE_ID)

        return result, mock_instance_action, mock_error

    def test_node_not_found_returns_none(self):
        result, mock_instance_action, mock_error = self._call(
            COMPUTE_STOP, node_raises=RuntimeError("404")
        )
        assert result is None
        mock_instance_action.assert_not_called()
        mock_error.assert_called_once()

    def test_no_cr_for_worker_pool_returns_none(self):
        result, mock_instance_action, _ = self._call(
            COMPUTE_STOP, worker_pool_cr_id=None
        )
        assert result is None
        mock_instance_action.assert_not_called()

    def test_instance_not_found_returns_none(self):
        result, mock_instance_action, mock_error = self._call(
            COMPUTE_STOP, instance=None
        )
        assert result is None
        mock_instance_action.assert_not_called()
        mock_error.assert_called_once()

    def test_success_delegates_to_instance_action(self):
        result, mock_instance_action, _ = self._call(COMPUTE_RESTART)
        assert result == CR_ID
        mock_instance_action.assert_called_once_with(
            COMPUTE_RESTART, CR_ID, INSTANCE_ID, NODE_ID
        )
