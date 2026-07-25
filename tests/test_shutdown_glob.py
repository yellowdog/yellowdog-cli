"""Glob-selection tests for yd-shutdown."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _summary(name, id_, finished=False):
    return SimpleNamespace(
        name=name,
        id=id_,
        namespace="default",
        status=SimpleNamespace(finished=finished),
    )


def _args(**overrides):
    defaults = dict(
        worker_pool_nodes_list=[], dry_run=False, json_output=False, follow=False
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def test_glob_filters_and_excludes_finished():
    import yellowdog_cli.shutdown as yd_shutdown

    fetched = [
        _summary("wp-1", "a"),
        _summary("wp-2", "b", finished=True),
        _summary("other", "c"),
    ]
    with (
        patch.object(yd_shutdown, "CLIENT", MagicMock()),
        patch.object(
            yd_shutdown, "CONFIG_COMMON", MagicMock(namespace="default", name_tag="tag")
        ),
        patch.object(
            yd_shutdown,
            "ARGS_PARSER",
            _args(worker_pool_nodes_list=["wp-*"], dry_run=True),
        ),
        patch.object(yd_shutdown, "get_worker_pool_summaries", return_value=fetched),
        patch.object(yd_shutdown, "report_dry_run") as mock_report,
    ):
        with pytest.raises(SystemExit) as exc_info:
            yd_shutdown.main()
        assert exc_info.value.code == 0

    reported = mock_report.call_args.args[1]
    assert [s.id for s in reported] == ["a"]  # wp-2 finished, other unmatched


def test_literal_uses_by_name_path():
    import yellowdog_cli.shutdown as yd_shutdown

    with (
        patch.object(yd_shutdown, "CLIENT", MagicMock()),
        patch.object(yd_shutdown, "CONFIG_COMMON", MagicMock(namespace="default")),
        patch.object(
            yd_shutdown, "ARGS_PARSER", _args(worker_pool_nodes_list=["wp-1"])
        ),
        patch.object(yd_shutdown, "shutdown_by_names_or_ids") as mock_by_name,
    ):
        with pytest.raises(SystemExit) as exc_info:
            yd_shutdown.main()
        assert exc_info.value.code == 0

    mock_by_name.assert_called_once_with(["wp-1"])
