from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from cli_test_helpers import shell

import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    ET_ALLOWANCES,
    ET_COMPUTE_REQUIREMENT_TEMPLATES,
    ET_COMPUTE_REQUIREMENTS,
    ET_COMPUTE_SOURCE_TEMPLATES,
    ET_GROUPS,
    ET_IMAGE_FAMILIES,
    ET_KEYRINGS,
    ET_PERMISSIONS,
    ET_ROLES,
    ET_TASKS,
    ET_WORK_REQUIREMENTS,
    ET_WORKER_POOLS,
)


def _ctx() -> RunContext:
    """
    The context a command is given: the wrapper's values, as patched.
    """
    return RunContext(
        wrapper_module.ARGS_PARSER, wrapper_module.CONFIG_COMMON, wrapper_module.CLIENT
    )


@pytest.mark.system
@pytest.mark.parametrize(
    "cmd",
    [
        "yd-list --help",
        f"yd-list {ET_ALLOWANCES} -n='' -t=''",
        f"yd-list {ET_COMPUTE_REQUIREMENT_TEMPLATES} -n='' -t=''",
        f"yd-list {ET_IMAGE_FAMILIES} -n='' -t=''",
        f"yd-list {ET_KEYRINGS} -n='' -t=''",
        f"yd-list {ET_COMPUTE_SOURCE_TEMPLATES} -n='' -t=''",
        f"yd-list {ET_WORKER_POOLS} -n='' -t=''",
        f"yd-list {ET_COMPUTE_REQUIREMENTS} -n='' -t=''",
        f"yd-list {ET_WORK_REQUIREMENTS} -n='' -t=''",
        f"yd-list {ET_GROUPS} -n='' -t=''",
        f"yd-list {ET_PERMISSIONS} -n='' -t=''",
        f"yd-list {ET_ROLES} -n='' -t=''",
    ],
)
def test_list(cmd):
    assert shell(cmd).exit_code == 0


# ---------------------------------------------------------------------------
# '--count' option
# ---------------------------------------------------------------------------


def _args_parser(**overrides) -> MagicMock:
    """
    An ARGS_PARSER stand-in with the attributes consulted by the list
    functions, defaulted to count mode after main()'s normalisation.
    """
    defaults = dict(
        count_only=True,
        json_output=False,
        details=False,
        ids_only=False,
        quiet=True,
        status_filter=None,
        active_only=False,
        entity_type=None,
        name_glob=None,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


class TestCountOption:
    """
    Unit tests for the 'yd-list --count' option.
    """

    def test_apply_count_option_normalises_output_options(self):
        import yellowdog_cli.list as yd_list

        args_parser = MagicMock(
            count_only=True, quiet=False, json_output=True, details=True, ids_only=True
        )
        with patch.object(wrapper_module, "ARGS_PARSER", args_parser):
            yd_list._apply_count_option(_ctx())
        assert args_parser.quiet is True
        assert args_parser.json_output is False
        assert args_parser.details is False
        assert args_parser.ids_only is False

    def test_apply_count_option_noop_when_not_selected(self):
        import yellowdog_cli.list as yd_list

        args_parser = MagicMock(
            count_only=False, quiet=False, json_output=True, details=True, ids_only=True
        )
        with patch.object(wrapper_module, "ARGS_PARSER", args_parser):
            yd_list._apply_count_option(_ctx())
        assert args_parser.quiet is False
        assert args_parser.json_output is True

    def test_print_json_or_count_prints_count(self, capsys):
        import yellowdog_cli.list as yd_list

        with patch.object(wrapper_module, "ARGS_PARSER", _args_parser()):
            yd_list._print_json_or_count(_ctx(), [object(), object(), object()])
        assert capsys.readouterr().out.strip() == "3"

    def test_print_json_or_count_delegates_to_json(self):
        import yellowdog_cli.list as yd_list

        objects = [object()]
        with (
            patch.object(wrapper_module, "ARGS_PARSER", _args_parser(count_only=False)),
            patch.object(yd_list, "print_objects_as_json") as mock_json,
        ):
            yd_list._print_json_or_count(_ctx(), objects)
        mock_json.assert_called_once_with(objects)

    def test_keyrings_count(self, capsys):
        import yellowdog_cli.list as yd_list

        client = MagicMock()
        client.keyring_client.get_keyrings.return_value.list_all.return_value = [
            MagicMock(),
            MagicMock(),
        ]
        with (
            patch.object(wrapper_module, "CLIENT", client),
            patch.object(wrapper_module, "ARGS_PARSER", _args_parser()),
            patch.object(
                yd_list, "sorted_objects", side_effect=lambda objects: objects
            ),
        ):
            yd_list.list_keyrings(_ctx())
        assert capsys.readouterr().out.strip() == "2"

    def test_keyrings_count_empty(self, capsys):
        import yellowdog_cli.list as yd_list

        client = MagicMock()
        client.keyring_client.get_keyrings.return_value.list_all.return_value = []
        with (
            patch.object(wrapper_module, "CLIENT", client),
            patch.object(wrapper_module, "ARGS_PARSER", _args_parser()),
        ):
            yd_list.list_keyrings(_ctx())
        assert capsys.readouterr().out.strip() == "0"

    def test_keyrings_search_by_the_globs_literal_prefix(self, capsys):
        # The server search takes the literal prefix of the glob; the glob
        # itself is applied to what comes back, as for Image Families
        from yellowdog_client.model import KeyringSearch

        import yellowdog_cli.list as yd_list

        client = MagicMock()
        client.keyring_client.get_keyrings.return_value.list_all.return_value = [
            SimpleNamespace(name="proj-a"),
            SimpleNamespace(name="proj-b"),
            SimpleNamespace(name="proj-other"),
        ]
        with (
            patch.object(wrapper_module, "CLIENT", client),
            patch.object(
                wrapper_module, "ARGS_PARSER", _args_parser(name_glob="proj-?")
            ),
        ):
            yd_list.list_keyrings(_ctx())
        client.keyring_client.get_keyrings.assert_called_once_with(
            KeyringSearch(name="proj-")
        )
        assert capsys.readouterr().out.strip() == "2"

    def test_tasks_count_aggregates_without_interaction(self, capsys):
        import yellowdog_cli.list as yd_list

        wr_1, wr_2 = MagicMock(id="wr_1"), MagicMock(id="wr_2")
        tg_1, tg_2 = MagicMock(id="tg_1"), MagicMock(id="tg_2")
        with (
            patch.object(wrapper_module, "CLIENT", MagicMock()),
            patch.object(
                wrapper_module,
                "CONFIG_COMMON",
                MagicMock(namespace="ns", name_tag="tag"),
            ),
            patch.object(
                wrapper_module, "ARGS_PARSER", _args_parser(entity_type=ET_TASKS)
            ),
            patch.object(
                yd_list,
                "get_filtered_work_requirement_summaries",
                return_value=[wr_1, wr_2],
            ),
            patch.object(
                yd_list,
                "get_task_groups_from_wr_by_id",
                side_effect=lambda client, wr_id: [tg_1] if wr_id == "wr_1" else [tg_2],
            ),
            patch.object(
                yd_list,
                "get_all_tasks_in_task_group",
                side_effect=lambda client, tg_id: (
                    [MagicMock()] * (3 if tg_id == "tg_1" else 2)
                ),
            ),
            patch.object(
                yd_list, "sorted_objects", side_effect=lambda objects: objects
            ),
            patch.object(yd_list, "select") as mock_select,
            patch.object(yd_list, "print_info"),
        ):
            yd_list.list_work_requirements(_ctx())
        assert capsys.readouterr().out.strip() == "5"
        mock_select.assert_not_called()
