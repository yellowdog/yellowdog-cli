"""Name/ID selection tests for yd-terminate."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _summary(name, id_):
    return SimpleNamespace(name=name, id=id_)


def _args(**overrides):
    defaults = dict(
        compute_requirements_instances_or_nodes=[],
        dry_run=False,
        json_output=False,
        follow=False,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def test_glob_routes_through_dry_run_with_filtered_summaries():
    import yellowdog_cli.terminate as yd_terminate

    fetched = [_summary("cr-1", "a"), _summary("other", "b")]
    with (
        patch.object(yd_terminate, "CLIENT", MagicMock()),
        patch.object(
            yd_terminate,
            "CONFIG_COMMON",
            MagicMock(namespace="default", name_tag="tag"),
        ),
        patch.object(
            yd_terminate,
            "ARGS_PARSER",
            _args(compute_requirements_instances_or_nodes=["cr-*"], dry_run=True),
        ),
        patch.object(
            yd_terminate, "get_compute_requirement_summaries", return_value=fetched
        ),
        patch.object(yd_terminate, "report_dry_run") as mock_report,
    ):
        with pytest.raises(SystemExit) as exc_info:
            yd_terminate.main()
        assert exc_info.value.code == 0

    reported = mock_report.call_args.args[1]
    assert [s.id for s in reported] == ["a"]


def test_literal_uses_by_name_path():
    import yellowdog_cli.terminate as yd_terminate

    with (
        patch.object(yd_terminate, "CLIENT", MagicMock()),
        patch.object(yd_terminate, "CONFIG_COMMON", MagicMock(namespace="default")),
        patch.object(
            yd_terminate,
            "ARGS_PARSER",
            _args(compute_requirements_instances_or_nodes=["cr-1"]),
        ),
        patch.object(yd_terminate, "terminate_by_name_or_id") as mock_by_name,
    ):
        with pytest.raises(SystemExit) as exc_info:
            yd_terminate.main()
        assert exc_info.value.code == 0

    mock_by_name.assert_called_once_with(["cr-1"])


CR_ID = "ydid:compreq:d9c548:98879b5a-9192-4a56-ad25-fc1330e49185"
# OCI instance IDs (OCIDs) contain dots of their own
OCI_INSTANCE_ID = (
    "ocid1.instance.oc1.uk-london-1."
    "anwgiljtbfkcyvycib2ubsewuwqqffx2jzyp7dolkhxanfvdsgvjzjrytepa"
)


@pytest.mark.parametrize("instance_id", ["i-0123456789abcdef0", OCI_INSTANCE_ID])
def test_instance_spec_routes_to_instance_termination(instance_id):
    import yellowdog_cli.terminate as yd_terminate

    with (
        patch.object(yd_terminate, "CLIENT", MagicMock()),
        patch.object(yd_terminate, "CONFIG_COMMON", MagicMock(namespace="default")),
        patch.object(yd_terminate, "ARGS_PARSER", _args(follow=False)),
        patch.object(
            yd_terminate, "_terminate_instance", return_value=CR_ID
        ) as mock_terminate_instance,
    ):
        yd_terminate.terminate_by_name_or_id([f"{CR_ID}.{instance_id}"])

    mock_terminate_instance.assert_called_once_with(CR_ID, instance_id)
