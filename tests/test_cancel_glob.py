"""Glob-selection tests for yd-cancel."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from yellowdog_client.model import WorkRequirementStatus


def _summary(name, id_):
    return SimpleNamespace(name=name, id=id_, status=WorkRequirementStatus.RUNNING)


def _args(**overrides):
    defaults = dict(
        work_requirement_names=[],
        dry_run=False,
        json_output=False,
        abort=False,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def test_glob_routes_through_dry_run_with_filtered_summaries():
    import yellowdog_cli.cancel as yd_cancel

    fetched = [_summary("proj-1", "a"), _summary("other", "b")]
    with (
        patch.object(yd_cancel, "CLIENT", MagicMock()),
        patch.object(
            yd_cancel, "CONFIG_COMMON", MagicMock(namespace="default", name_tag="tag")
        ),
        patch.object(
            yd_cancel,
            "ARGS_PARSER",
            _args(work_requirement_names=["proj-*"], dry_run=True),
        ),
        patch.object(
            yd_cancel,
            "get_filtered_work_requirement_summaries",
            return_value=fetched,
        ),
        patch.object(yd_cancel, "report_dry_run") as mock_report,
    ):
        with pytest.raises(SystemExit):
            yd_cancel.main()

    reported = mock_report.call_args.args[1]
    assert [s.id for s in reported] == ["a"]


def test_literal_name_uses_exact_path():
    import yellowdog_cli.cancel as yd_cancel

    with (
        patch.object(yd_cancel, "CLIENT", MagicMock()),
        patch.object(yd_cancel, "CONFIG_COMMON", MagicMock(namespace="default")),
        patch.object(
            yd_cancel, "ARGS_PARSER", _args(work_requirement_names=["some-wr"])
        ),
        patch.object(
            yd_cancel, "_cancel_work_requirements_by_name_or_id"
        ) as mock_by_name,
    ):
        with pytest.raises(SystemExit):
            yd_cancel.main()

    mock_by_name.assert_called_once_with(["some-wr"])


def test_glob_path_excludes_terminal_statuses():
    import yellowdog_cli.cancel as yd_cancel

    captured = {}

    def fake_fetch(client, **kwargs):
        captured.update(kwargs)
        return [_summary("proj-1", "a")]

    with (
        patch.object(yd_cancel, "CLIENT", MagicMock()),
        patch.object(
            yd_cancel, "CONFIG_COMMON", MagicMock(namespace="default", name_tag="tag")
        ),
        patch.object(
            yd_cancel,
            "ARGS_PARSER",
            _args(work_requirement_names=["proj-*"], dry_run=True),
        ),
        patch.object(
            yd_cancel,
            "get_filtered_work_requirement_summaries",
            side_effect=fake_fetch,
        ),
        patch.object(yd_cancel, "report_dry_run"),
    ):
        with pytest.raises(SystemExit):
            yd_cancel.main()

    # the glob-branch fetch must request the same terminal-status exclusion
    # as the tag path, so cancelled/completed/failed WRs aren't re-cancelled
    assert captured.get("exclude_filter") == [
        WorkRequirementStatus.COMPLETED,
        WorkRequirementStatus.CANCELLED,
        WorkRequirementStatus.FAILED,
    ]


def test_ydid_literal_uses_exact_path():
    import yellowdog_cli.cancel as yd_cancel

    ydid = "ydid:workreq:0123:00000000-0000-0000-0000-000000000000"

    with (
        patch.object(yd_cancel, "CLIENT", MagicMock()),
        patch.object(yd_cancel, "CONFIG_COMMON", MagicMock(namespace="default")),
        patch.object(yd_cancel, "ARGS_PARSER", _args(work_requirement_names=[ydid])),
        patch.object(
            yd_cancel, "_cancel_work_requirements_by_name_or_id"
        ) as mock_by_name,
    ):
        with pytest.raises(SystemExit):
            yd_cancel.main()

    # a colon-containing YDID has no glob metachars, so it must be classified
    # as a literal (not a glob) at the whole-string level
    mock_by_name.assert_called_once_with([ydid])
