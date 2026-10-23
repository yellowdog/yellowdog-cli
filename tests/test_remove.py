"""
yd-remove (utils/resource_removal.py, and the run it shares with yd-create in
utils/resource_processing.py): the behaviour its review changed. A run exits
with its failures' shared code and stops at a session failure, each failure
printed once naming the resource; an ID is recognised without '--ids',
files and IDs removed in one run in removal order; IDs are checked as they
are parsed, each ID removed once, fetched before anything is asked, and one that does not
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
        SimpleNamespace(
            url="https://api.x/api", key="k", secret="s", request_timeout=(10.0, 90.0)
        ),
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


def test_a_prompt_with_no_answer_stops_the_run(env, monkeypatch):
    # Stdin at its end (a script without --yes): every later prompt would
    # find the same, so the run stops there, as yd-delete's does, rather
    # than prompting, failing and recording each resource in turn
    from yellowdog_cli.utils.interactive import NoAnswerToPrompt

    def unanswered(question):
        env.asked.append(question)
        raise NoAnswerToPrompt()

    monkeypatch.setattr(yd_remove, "get_group_id_by_name", lambda *a: GROUP_ID)
    monkeypatch.setattr(yd_remove, "confirmed", unanswered)
    groups = [{"resource": "Group", "name": name} for name in ("a", "b", "c")]
    with pytest.raises(NoAnswerToPrompt):
        yd_remove.remove_resources(_ctx(), groups)
    assert len(env.asked) == 1
    env.client.account_client.delete_group.assert_not_called()
    assert [(r["name"], r["action"]) for r in env.records] == [
        ("a", "failed"),
        ("b", "skipped"),
        ("c", "skipped"),
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
        (["--ids", "not-an-id"], "not the ID of a resource that can be removed"),
        (["--ids", TASK_ID], "not the ID of a resource that can be removed"),
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


def test_an_id_needs_no_ids_option():
    CLIParser(command="yd-remove", argv=[GROUP_ID, POOL_ID])


def test_files_and_ids_mix_with_the_file_options():
    CLIParser(command="yd-remove", argv=["groups.json", GROUP_ID, "-M"])


def test_a_jsonnet_dry_run_of_ids_alone_is_refused(capsys):
    # Nothing to show: without a file, the IDs would be removed for real
    with pytest.raises(SystemExit) as raised:
        CLIParser(command="yd-remove", argv=["-J", GROUP_ID])
    assert raised.value.code == 2
    assert "--jsonnet-dry-run applies to specification files" in capsys.readouterr().err


def test_an_id_of_a_type_not_removed_is_refused_without_ids_too(capsys):
    with pytest.raises(SystemExit) as raised:
        CLIParser(command="yd-remove", argv=["groups.json", TASK_ID])
    assert raised.value.code == 2
    assert "not the ID of a resource that can be removed" in capsys.readouterr().err


APPLICATION_ID = "ydid:app:000000:99999999-9999-9999-9999-999999999999"


def test_files_and_ids_are_removed_in_one_run_in_removal_order(env, monkeypatch):
    # An Application is created after a Group, so removed before it, though
    # its ID was given after the Group's file
    monkeypatch.setattr(yd_remove, "get_group_id_by_name", lambda *a: GROUP_ID)
    env.client.account_client.get_application.return_value = SimpleNamespace(name="app")
    yd_remove.remove_resources_and_ids(
        _ctx(), [{"resource": "Group", "name": "g"}, APPLICATION_ID, APPLICATION_ID]
    )
    assert [(r["resource"], r["action"]) for r in env.records] == [
        ("Application", "removed"),
        ("Group", "removed"),
    ]
    env.client.account_client.delete_application.assert_called_once_with(APPLICATION_ID)


def test_no_resequence_removes_files_and_ids_in_the_order_given(env, monkeypatch):
    monkeypatch.setattr(yd_remove, "get_group_id_by_name", lambda *a: GROUP_ID)
    env.client.account_client.get_application.return_value = SimpleNamespace(name="app")
    yd_remove.remove_resources_and_ids(
        _ctx(),
        [{"resource": "Group", "name": "g"}, APPLICATION_ID, APPLICATION_ID],
        yd_remove.RemoveOptions(resequence=False),
    )
    assert [(r["resource"], r["action"]) for r in env.records] == [
        ("Group", "removed"),
        ("Application", "removed"),
    ]
    env.client.account_client.delete_application.assert_called_once_with(APPLICATION_ID)


def test_a_failure_among_files_and_ids_fails_the_run_once(env, monkeypatch):
    monkeypatch.setattr(yd_remove, "get_group_id_by_name", lambda *a: GROUP_ID)
    env.client.account_client.get_application.side_effect = _http_error(404)
    with pytest.raises(ReportedFailure) as raised:
        yd_remove.remove_resources_and_ids(
            _ctx(), [{"resource": "Group", "name": "g"}, APPLICATION_ID]
        )
    assert classify(raised.value) == ExitCode.NOT_FOUND
    assert [(r["resource"], r["action"]) for r in env.records] == [
        ("Application", "failed"),
        ("Group", "removed"),
    ]


# ---------------------------------------------------------------------------
# The command line: remove.py's routing
# ---------------------------------------------------------------------------


@pytest.fixture
def routed(monkeypatch):
    import yellowdog_cli.remove as remove_module

    calls: list[tuple] = []
    monkeypatch.setattr(
        remove_module,
        "remove_resources_by_id",
        lambda ctx, ids: calls.append(("ids", ids)),
    )
    monkeypatch.setattr(
        remove_module,
        "remove_resources",
        lambda ctx, specs, options: calls.append(("files", specs)),
    )
    monkeypatch.setattr(
        remove_module,
        "remove_resources_and_ids",
        lambda ctx, given, options: calls.append(("both", given, options.resequence)),
    )

    def load(args, creation_or_update, files=None, per_source=None):
        # One resource per file, named for it
        loaded = [[{"from": name}] for name in files or []]
        if per_source is not None:
            per_source.extend(loaded)
        return [resource for group in loaded for resource in group]

    monkeypatch.setattr(remove_module, "load_resource_specifications", load)

    def run(
        *arguments: str, ids: bool = False, no_resequence: bool = False
    ) -> list[tuple]:
        args = SimpleNamespace(
            ids=ids,
            resource_type=None,
            resource_specifications=list(arguments),
            match_allowances_by_description=False,
            no_resequence=no_resequence,
        )
        remove_module.remove(RunContext(args=args, config=None, client=None))
        return calls

    return run


def test_ids_alone_are_removed_by_id(routed):
    assert routed(GROUP_ID, POOL_ID) == [("ids", [GROUP_ID, POOL_ID])]


def test_files_alone_are_removed_as_specifications(routed):
    assert routed("a.json") == [("files", [{"from": "a.json"}])]


def test_files_and_ids_go_to_one_run_in_the_order_given(routed):
    # Each file's resources where the file was given, among the IDs
    assert routed("a.json", GROUP_ID, "b.json") == [
        ("both", [{"from": "a.json"}, GROUP_ID, {"from": "b.json"}], True)
    ]


def test_no_resequence_reaches_the_run(routed):
    assert routed("a.json", GROUP_ID, no_resequence=True) == [
        ("both", [{"from": "a.json"}, GROUP_ID], False)
    ]


def test_remove_takes_no_resequence():
    parsed = CLIParser(command="yd-remove", argv=["groups.json", "--no-resequence"])
    assert parsed.no_resequence is True


def test_the_ids_option_still_works_and_says_it_is_optional(routed, capsys):
    assert routed(GROUP_ID, ids=True) == [("ids", [GROUP_ID])]
    out = " ".join(capsys.readouterr().out.split())
    assert "--ids is optional" in out
    assert "WARNING" not in out


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
    assert delete.call_args.kwargs["timeout"] == _ctx().config.request_timeout
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
