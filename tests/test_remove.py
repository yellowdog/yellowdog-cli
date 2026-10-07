"""
yd-remove (utils/resource_removal.py, and the run it shares with yd-create in
utils/resource_processing.py): the behaviour its review changed. A run exits
with its failures' shared code and stops at a session failure, each failure
printed once naming the resource; '--ids' is checked as it is parsed, each
ID removed once, fetched before anything is asked, and one that does not
exist is not found (exit 6); a Configured Worker Pool's name shuts down only
its unfinished pools; Allowances removed by description are recorded each
with its ID; Attribute Definitions carry a timeout, a 404 skipped; a Keyring
is looked up by name before it is confirmed; a Namespace looked up once.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from requests import HTTPError, Response

import yellowdog_cli.utils.resource_removal as yd_remove
import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli.utils import resource_processing
from yellowdog_cli.utils.args import CLIParser
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.exit_codes import ExitCode, ReportedFailure, classify
from yellowdog_cli.utils.limits import RAW_REQUEST_TIMEOUT
from yellowdog_cli.utils.ydid_utils import REMOVABLE_YDID_TYPES, YDIDType


def _ctx() -> RunContext:
    """
    The context a command is given: the wrapper globals, as patched.
    """
    return RunContext(
        wrapper_module.ARGS_PARSER, wrapper_module.CONFIG_COMMON, wrapper_module.CLIENT
    )


GROUP_ID = "ydid:group:000000:99999999-9999-9999-9999-999999999999"
POOL_ID = "ydid:wrkrpool:000000:99999999-9999-9999-9999-999999999999"
TASK_ID = "ydid:task:000000:99999999-9999-9999-9999-999999999999:1:1"


def _http_error(status: int) -> HTTPError:
    response = Response()
    response.status_code = status
    response._content = b"error"
    return HTTPError(f"HTTP {status}", response=response)


def _response(status: int, text: str = "") -> Response:
    response = Response()
    response.status_code = status
    response._content = text.encode()
    return response


@pytest.fixture
def env(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(wrapper_module, "CLIENT", client)
    args = SimpleNamespace(
        ids=False, resource_specifications=[], match_allowances_by_description=False
    )
    monkeypatch.setattr(yd_remove, "_OPTIONS", args)
    monkeypatch.setattr(
        wrapper_module,
        "CONFIG_COMMON",
        SimpleNamespace(url="https://api.x/api", key="k", secret="s"),
    )
    asked: list[str] = []
    monkeypatch.setattr(
        yd_remove, "confirmed", lambda question: asked.append(question) or True
    )
    records: list[dict] = []

    def _record(resource_type, name, id, action, error=None, **extra):
        records.append(
            {"resource": resource_type, "name": name, "id": id, "action": action}
            | ({"error": error} if error else {})
            | extra
        )

    monkeypatch.setattr(yd_remove, "record_resource", _record)
    monkeypatch.setattr(resource_processing, "record_resource", _record)
    return SimpleNamespace(client=client, args=args, records=records, asked=asked)


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def test_a_session_failure_stops_the_run(env, monkeypatch):
    monkeypatch.setattr(yd_remove, "get_group_id_by_name", lambda *a: GROUP_ID)
    env.client.account_client.delete_group.side_effect = _http_error(401)
    groups = [{"resource": "Group", "name": name} for name in ("a", "b")]
    with pytest.raises(ReportedFailure) as raised:
        yd_remove.remove_resources(_ctx(), groups)
    assert classify(raised.value) == ExitCode.AUTHENTICATION
    assert env.client.account_client.delete_group.call_count == 1
    assert [(r["name"], r["action"]) for r in env.records] == [
        ("a", "failed"),
        ("b", "skipped"),
    ]


def test_a_failure_is_printed_once_naming_the_resource(env, monkeypatch, capsys):
    monkeypatch.setattr(yd_remove, "get_group_id_by_name", lambda *a: GROUP_ID)
    env.client.account_client.delete_group.side_effect = _http_error(403)
    with pytest.raises(ReportedFailure) as raised:
        yd_remove.remove_resources(_ctx(), [{"resource": "Group", "name": "a"}])
    captured = capsys.readouterr()
    text = " ".join((captured.out + captured.err).split())
    assert text.count("Failed to remove Group 'a': HTTP 403") == 1
    assert classify(raised.value) == ExitCode.PERMISSION


def test_a_missing_property_is_named_without_quotes_round_it(env):
    with pytest.raises(ReportedFailure) as raised:
        yd_remove.remove_resources(_ctx(), [{"resource": "Group"}])
    assert str(raised.value) == "Expected property 'name' to be defined"


# ---------------------------------------------------------------------------
# --ids
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv, message",
    [
        (["--ids", "not-an-id"], "not the ID of a resource yd-remove can remove"),
        (["--ids", TASK_ID], "not the ID of a resource yd-remove can remove"),
        (["--ids", "-M", GROUP_ID], "--match-allowances-by-description applies"),
        (["--ids", "-J", GROUP_ID], "--jsonnet-dry-run applies"),
    ],
)
def test_ids_are_checked_as_they_are_parsed(argv, message, capsys):
    with pytest.raises(SystemExit) as raised:
        CLIParser(command="yd-remove", argv=argv)
    assert raised.value.code == 2
    assert message in capsys.readouterr().err


def test_removable_ids_are_accepted():
    CLIParser(command="yd-remove", argv=["--ids", GROUP_ID, POOL_ID])


def test_every_removable_type_has_a_removal(env):
    for ydid_type in REMOVABLE_YDID_TYPES:
        assert yd_remove._removable_by_id(_ctx(), ydid_type).resource_type
    with pytest.raises(ValueError):
        yd_remove._removable_by_id(_ctx(), YDIDType.TASK)


def test_a_repeated_id_is_removed_once(env):
    env.client.account_client.get_group.return_value = SimpleNamespace(name="g")
    yd_remove.remove_resources_by_id(_ctx(), [GROUP_ID, GROUP_ID])
    env.client.account_client.delete_group.assert_called_once_with(GROUP_ID)
    assert env.records == [
        {"resource": "Group", "name": "g", "id": GROUP_ID, "action": "removed"}
    ]


def test_an_id_that_does_not_exist_is_not_found_before_anything_is_asked(env):
    env.client.account_client.get_group.side_effect = _http_error(404)
    with pytest.raises(ReportedFailure) as raised:
        yd_remove.remove_resources_by_id(_ctx(), [GROUP_ID])
    assert classify(raised.value) == ExitCode.NOT_FOUND
    assert env.asked == []
    assert env.records[0]["error"] == f"Cannot find Group {GROUP_ID}"


def test_a_finished_worker_pool_is_not_shut_down_again(env):
    env.client.worker_pool_client.get_worker_pool_by_id.return_value = SimpleNamespace(
        name="p", namespace="ns", status=SimpleNamespace(finished=True)
    )
    assert yd_remove.remove_resource_by_id(_ctx(), POOL_ID) is True
    env.client.worker_pool_client.shutdown_worker_pool_by_id.assert_not_called()
    assert env.records[0]["action"] == "skipped"
    assert env.records[0]["name"] == "ns/p"


def test_the_cloud_wizard_entry_point_reports_a_failure(env):
    env.client.account_client.get_group.side_effect = _http_error(404)
    assert yd_remove.remove_resource_by_id(_ctx(), GROUP_ID) is False
    assert env.records[0]["action"] == "failed"


# ---------------------------------------------------------------------------
# Resources by specification
# ---------------------------------------------------------------------------


def _pool(id_: str, finished: bool, type_: str = "ConfiguredWorkerPool"):
    return SimpleNamespace(
        id=id_,
        type=f"co.yellowdog.platform.model.{type_}",
        status=SimpleNamespace(finished=finished),
    )


def test_only_the_unfinished_configured_pools_of_a_name_are_shut_down(env, monkeypatch):
    monkeypatch.setattr(
        yd_remove,
        "get_worker_pool_summaries",
        lambda *a, **k: [_pool("old", True), _pool("live", False)],
    )
    yd_remove.remove_configured_worker_pool(_ctx(), {"name": "p", "namespace": "ns"})
    env.client.worker_pool_client.shutdown_worker_pool_by_id.assert_called_once_with(
        "live"
    )
    assert [(r["id"], r["action"]) for r in env.records] == [("live", "removed")]


def test_allowances_removed_by_description_are_recorded_each_with_its_id(
    env, monkeypatch
):
    env.args.match_allowances_by_description = True
    monkeypatch.setattr(
        yd_remove, "remove_allowances_matching_description", lambda *a: ["a1", "a2"]
    )
    yd_remove.remove_allowance(_ctx(), {"description": "d"})
    assert [(r["id"], r["action"]) for r in env.records] == [
        ("a1", "removed"),
        ("a2", "removed"),
    ]
    assert all("count" not in r for r in env.records)


def test_an_allowance_without_a_description_is_skipped_with_a_warning(env, capsys):
    env.args.match_allowances_by_description = True
    yd_remove.remove_allowance(_ctx(), {"type": "AccountAllowance"})
    assert env.records[0]["action"] == "skipped"
    assert "without a 'description'" in " ".join(capsys.readouterr().out.split())


def test_attribute_definitions_carry_a_timeout_and_keep_the_exit_code(env, monkeypatch):
    delete = MagicMock(return_value=_response(401, "Unauthorized"))
    monkeypatch.setattr(yd_remove, "delete", delete)
    with pytest.raises(HTTPError) as raised:
        yd_remove.remove_attribute_definition(
            _ctx(), {"name": "a"}, "StringAttributeDefinition"
        )
    assert delete.call_args.kwargs["timeout"] == RAW_REQUEST_TIMEOUT
    assert classify(raised.value) == ExitCode.AUTHENTICATION


def test_an_attribute_definition_not_found_is_skipped(env, monkeypatch):
    monkeypatch.setattr(yd_remove, "delete", MagicMock(return_value=_response(404)))
    yd_remove.remove_attribute_definition(
        _ctx(), {"name": "a"}, "StringAttributeDefinition"
    )
    assert env.records[0]["action"] == "skipped"


def test_a_keyring_not_found_is_skipped_before_anything_is_asked(env, monkeypatch):
    monkeypatch.setattr(yd_remove, "get_keyring_summary_by_name", lambda *a: None)
    yd_remove.remove_keyring(_ctx(), {"name": "kr"})
    assert env.asked == []
    env.client.keyring_client.delete_keyring_by_name.assert_not_called()
    assert env.records[0]["action"] == "skipped"


def test_a_removed_keyring_is_recorded_with_its_id(env, monkeypatch):
    monkeypatch.setattr(
        yd_remove,
        "get_keyring_summary_by_name",
        lambda *a: SimpleNamespace(id="kr-id"),
    )
    yd_remove.remove_keyring(_ctx(), {"name": "kr"})
    assert env.records[0]["id"] == "kr-id"


def test_a_credential_removal_that_fails_is_not_taken_as_not_found(env):
    env.client.keyring_client.delete_credential_by_name.side_effect = _http_error(403)
    with pytest.raises(HTTPError):
        yd_remove.remove_credential(
            _ctx(), {"keyringName": "kr", "credential": {"name": "c"}}
        )


def test_a_namespace_is_looked_up_once_and_a_conflict_fails(env, monkeypatch):
    lookup = MagicMock(return_value="ns-id")
    monkeypatch.setattr(yd_remove, "get_namespace_id_by_name", lookup)
    env.client.namespaces_client.delete_namespace.side_effect = RuntimeError(
        "ConflictException"
    )
    with pytest.raises(RuntimeError, match="have been populated"):
        yd_remove.remove_namespace(_ctx(), {"name": "ns"})
    lookup.assert_called_once()
    env.client.namespaces_client.delete_namespace.assert_called_once_with("ns-id")


def test_a_namespace_not_found_is_not_a_failure(env, monkeypatch):
    monkeypatch.setattr(yd_remove, "get_namespace_id_by_name", lambda *a: None)
    yd_remove.remove_namespace(_ctx(), {"name": "ns"})
    assert env.records[0]["action"] == "skipped"


def test_an_image_family_not_found_is_skipped_with_a_warning(env, monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(yd_remove, "print_warning", warnings.append)
    env.client.images_client.get_image_family_by_name.side_effect = _http_error(404)
    yd_remove.remove_image_family(_ctx(), {"name": "f", "namespace": "ns"})
    assert warnings == ["Cannot find Machine Image Family 'ns/f'"]
    assert [(r["name"], r["action"]) for r in env.records] == [("ns/f", "skipped")]
    env.client.images_client.delete_image_family.assert_not_called()
    assert env.asked == []  # Nothing to confirm


def test_an_image_family_lookup_failing_other_than_404_is_raised(env):
    env.client.images_client.get_image_family_by_name.side_effect = _http_error(401)
    with pytest.raises(HTTPError):
        yd_remove.remove_image_family(_ctx(), {"name": "f", "namespace": "ns"})
    assert env.records == []
    env.client.images_client.delete_image_family.assert_not_called()
