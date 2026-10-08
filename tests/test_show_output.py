"""
The shape of yd-show's output, and its exit status.

Every branch of resolve_details() used to print its own object, and only ten of
the nineteen passed on the JSON array's indentation and separating commas. The
other nine produced an array whose elements ran together without commas: not
parseable, for Compute Requirements, Compute Sources, Nodes, Workers, Work
Requirements, Task Groups, Tasks, Image Groups and Images. Nothing caught it,
because the tests asserted the arguments handed to print_yd_object() rather
than what came out.

Also '--show-source-report' and '--show-exhaustion', the reports on a Compute
Requirement (or a Provisioned Worker Pool's) that follow it in the array.

These tests therefore parse the output. Resolution and printing are now
separate, so the framing is applied in one place and cannot be forgotten in a
branch -- but the guard is 'json.loads() succeeds', which holds however the
code is arranged.
"""

from json import loads
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from requests import HTTPError, Response

import yellowdog_cli.show as show_module
from yellowdog_cli.show import show_ydids
from yellowdog_cli.utils import output_settings
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.exit_codes import ExitCode
from yellowdog_cli.utils.ydid_utils import YDIDType

UUID = "98879b5a-9192-4a56-ad25-fc1330e49185"


def _ydid(type_token: str, suffix: str = "") -> str:
    return f"ydid:{type_token}:000000:{UUID}{suffix}"


class _Obj:
    """
    A stand-in for an SDK model object: the stubbed Json.dump() below returns
    its payload, and 'id' is what the Compute Source, Worker and Task Group
    branches match on when searching their parent.
    """

    def __init__(self, name: str, id: str | None = None):
        self.payload = {"name": name}
        self.id = id


class _StubJson:
    @staticmethod
    def dump(yd_object):
        # '--show-exhaustion' shows a dict holding SDK objects
        if isinstance(yd_object, dict):
            return {key: _StubJson.dump(value) for key, value in yd_object.items()}
        if isinstance(yd_object, list):
            return [_StubJson.dump(item) for item in yd_object]
        if isinstance(yd_object, _Obj):
            return yd_object.payload
        return yd_object


class _FakeConfiguredWorkerPool(_Obj):
    """
    Stands in for ConfiguredWorkerPool, which show.py isinstance()-checks.
    """


class _FakeProvisionedWorkerPool(_Obj):
    """
    Stands in for ProvisionedWorkerPool, likewise.
    """

    def __init__(self, name: str, compute_requirement_id: str):
        super().__init__(name)
        self.computeRequirementId = compute_requirement_id


def _args(**overrides) -> MagicMock:
    args = MagicMock()
    args.strip_ids = False
    args.hide_user_data = False
    args.substitute_ids = False
    args.show_token = False
    args.show_source_report = False
    args.show_exhaustion = False
    args.show_members = False
    args.output_file = None
    args.quiet = True  # Keep the status messages out of the parsed output
    args.json_output = False
    args.count_only = False
    args.no_format = True
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


# ---------------------------------------------------------------------------
# One client setup per entity type: returns the YDID and the object to expect
# ---------------------------------------------------------------------------


def _compute_requirement(client: MagicMock) -> tuple[str, _Obj]:
    obj = _Obj("compute-requirement")
    client.compute_client.get_compute_requirement_by_id.return_value = obj
    return _ydid("compreq"), obj


def _compute_source(client: MagicMock) -> tuple[str, _Obj]:
    ydid = _ydid("compsrc", ":1")
    obj = _Obj("compute-source", id=ydid)
    client.compute_client.get_compute_requirement_by_id.return_value = MagicMock(
        provisionStrategy=MagicMock(sources=[_Obj("other", id="ydid:compsrc:x"), obj])
    )
    return ydid, obj


def _node(client: MagicMock) -> tuple[str, _Obj]:
    obj = _Obj("node")
    client.worker_pool_client.get_node_by_id.return_value = obj
    return _ydid("node"), obj


def _worker(client: MagicMock) -> tuple[str, _Obj]:
    ydid = _ydid("wrkr", ":1")
    obj = _Obj("worker", id=ydid)
    client.worker_pool_client.get_node_by_id.return_value = MagicMock(
        workers=[_Obj("other", id="ydid:wrkr:x"), obj]
    )
    return ydid, obj


def _work_requirement(client: MagicMock) -> tuple[str, _Obj]:
    obj = _Obj("work-requirement")
    client.work_client.get_work_requirement_by_id.return_value = obj
    return _ydid("workreq"), obj


def _task_group(client: MagicMock) -> tuple[str, _Obj]:
    ydid = _ydid("taskgrp", ":1")
    obj = _Obj("task-group", id=ydid)
    client.work_client.get_work_requirement_by_id.return_value = MagicMock(
        taskGroups=[_Obj("other", id="ydid:taskgrp:x"), obj]
    )
    return ydid, obj


def _task(client: MagicMock) -> tuple[str, _Obj]:
    obj = _Obj("task")
    client.work_client.get_task_by_id.return_value = obj
    return _ydid("task"), obj


def _image_group(client: MagicMock) -> tuple[str, _Obj]:
    obj = _Obj("image-group")
    client.images_client.get_image_group_by_id.return_value = obj
    return _ydid("imggrp"), obj


def _image(client: MagicMock) -> tuple[str, _Obj]:
    obj = _Obj("image")
    client.images_client.get_image.return_value = obj
    return _ydid("image"), obj


def _image_family(client: MagicMock) -> tuple[str, _Obj]:
    obj = _Obj("image-family")
    client.images_client.get_image_family_by_id.return_value = obj
    return _ydid("imgfam"), obj


def _worker_pool(client: MagicMock) -> tuple[str, _Obj]:
    obj = _Obj("worker-pool")
    client.worker_pool_client.get_worker_pool_by_id.return_value = obj
    return _ydid("wrkrpool"), obj


def _keyring(client: MagicMock) -> tuple[str, _Obj]:
    # Fetched by ID in one call; the deprecated find_all_keyrings() is never used
    obj = _Obj("keyring")
    client.keyring_client.get_keyring.return_value = obj
    client.keyring_client.find_all_keyrings.side_effect = AssertionError(
        "find_all_keyrings() is deprecated and must not be called"
    )
    return _ydid("keyring"), obj


# The nine that dropped the array framing, plus two that kept it, as controls
SETUPS = [
    _compute_requirement,
    _compute_source,
    _node,
    _worker,
    _work_requirement,
    _task_group,
    _task,
    _image_group,
    _image,
    _image_family,
    _worker_pool,
    _keyring,
]


def _names(parsed) -> list[str]:
    """
    The 'name' of each object in the parsed output. Compared rather than the
    whole payload because several branches legitimately add a 'resource' field
    of their own; what is under test here is the framing around the objects.
    """
    return [item["name"] for item in (parsed if isinstance(parsed, list) else [parsed])]


# The warnings the last _run() printed
_WARNINGS: list[str] = []


def _run(
    ydids: list[str], client: MagicMock, args: MagicMock, capsys
) -> tuple[int, str]:
    _WARNINGS.clear()
    ctx = RunContext(args=args, config=MagicMock(), client=client)
    with (
        patch.object(show_module, "ConfiguredWorkerPool", _FakeConfiguredWorkerPool),
        patch.object(show_module, "ProvisionedWorkerPool", _FakeProvisionedWorkerPool),
        patch.object(show_module, "print_warning", _WARNINGS.append),
        output_settings.configured(args),
        # printing.py imports Json where it uses it, from the SDK's module
        patch("yellowdog_client.common.json.Json", _StubJson),
        patch.object(show_module, "print_error"),
    ):
        failures = show_ydids(ctx, ydids)
    return failures, capsys.readouterr().out


# ---------------------------------------------------------------------------
# Every YellowDog ID type has a resolver
# ---------------------------------------------------------------------------


def test_every_ydid_type_has_a_resolver():
    assert set(show_module._RESOLVERS) == set(YDIDType)


# ---------------------------------------------------------------------------
# The array framing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("setup", SETUPS, ids=lambda s: s.__name__.lstrip("_"))
def test_two_ids_of_one_type_produce_a_parseable_array(setup, capsys):
    client = MagicMock()
    ydid, obj = setup(client)

    failures, output = _run([ydid, ydid], client, _args(), capsys)

    assert failures == 0
    assert _names(loads(output)) == [obj.payload["name"], obj.payload["name"]]


@pytest.mark.parametrize("setup", SETUPS, ids=lambda s: s.__name__.lstrip("_"))
def test_one_id_produces_a_bare_object(setup, capsys):
    client = MagicMock()
    ydid, obj = setup(client)

    failures, output = _run([ydid], client, _args(), capsys)

    assert failures == 0
    parsed = loads(output)
    assert isinstance(parsed, dict)  # A bare object, not an array of one
    assert _names(parsed) == [obj.payload["name"]]


def test_mixed_types_produce_a_parseable_array(capsys):
    # The real mixed case: one branch that used to carry the framing and one
    # that used to drop it, in the same array
    client = MagicMock()
    family_id, family = _image_family(client)
    task_id, task = _task(client)

    failures, output = _run([family_id, task_id], client, _args(), capsys)

    assert failures == 0
    assert _names(loads(output)) == [family.payload["name"], task.payload["name"]]


def test_show_token_yields_an_array_from_a_single_id(capsys):
    # A Configured Worker Pool shown with '--show-token' is the one case where
    # a single ID produces two objects; concatenated, they did not parse
    client = MagicMock()
    pool = _FakeConfiguredWorkerPool("configured-pool")
    token = _Obj("token")
    client.worker_pool_client.get_worker_pool_by_id.return_value = pool
    client.worker_pool_client.get_configured_worker_pool_token_by_id.return_value = (
        token
    )

    failures, output = _run([_ydid("wrkrpool")], client, _args(show_token=True), capsys)

    assert failures == 0
    assert _names(loads(output)) == [pool.payload["name"], token.payload["name"]]


# ---------------------------------------------------------------------------
# '--show-source-report' and '--show-exhaustion'
# ---------------------------------------------------------------------------


def _diagnosable(client: MagicMock) -> tuple[str, _Obj, _Obj, _Obj]:
    """
    A Compute Requirement with a source report and one exhausted Allowance.
    """
    cr_id = _ydid("compreq")
    compute_requirement = _Obj("compute-requirement", id=cr_id)
    report = _Obj("source-report")
    notification = _Obj("allowance-a")
    client.compute_client.get_compute_requirement_by_id.return_value = (
        compute_requirement
    )
    compute = client.compute_client
    compute.get_best_compute_source_report_by_compute_requirement.return_value = report
    client.allowances_client.check_compute_requirement_exhaustion.return_value = [
        notification
    ]
    return cr_id, compute_requirement, report, notification


class TestDiagnostics:
    def test_the_source_report_follows_the_compute_requirement(self, capsys):
        client = MagicMock()
        cr_id, cr, report, _ = _diagnosable(client)
        failures, output = _run([cr_id], client, _args(show_source_report=True), capsys)
        assert failures == 0
        assert loads(output) == [cr.payload, report.payload]
        client.compute_client.get_best_compute_source_report_by_compute_requirement.assert_called_once_with(
            cr_id
        )
        client.allowances_client.check_compute_requirement_exhaustion.assert_not_called()

    def test_exhaustion_is_shown_as_one_object_naming_the_requirement(self, capsys):
        client = MagicMock()
        cr_id, cr, _, notification = _diagnosable(client)
        failures, output = _run([cr_id], client, _args(show_exhaustion=True), capsys)
        assert failures == 0
        assert loads(output) == [
            cr.payload,
            {
                "computeRequirementId": cr_id,
                "exhaustedAllowances": [notification.payload],
            },
        ]
        client.allowances_client.check_compute_requirement_exhaustion.assert_called_once_with(
            cr
        )

    def test_nothing_exhausted_is_an_empty_list(self, capsys):
        client = MagicMock()
        cr_id, _, _, _ = _diagnosable(client)
        client.allowances_client.check_compute_requirement_exhaustion.return_value = []
        _, output = _run([cr_id], client, _args(show_exhaustion=True), capsys)
        assert loads(output)[1]["exhaustedAllowances"] == []

    def test_both_in_order(self, capsys):
        client = MagicMock()
        cr_id, cr, report, _ = _diagnosable(client)
        _, output = _run(
            [cr_id],
            client,
            _args(show_source_report=True, show_exhaustion=True),
            capsys,
        )
        parsed = loads(output)
        assert parsed[:2] == [cr.payload, report.payload]
        assert parsed[2]["computeRequirementId"] == cr_id

    def test_a_provisioned_worker_pool_reports_on_its_compute_requirement(self, capsys):
        client = MagicMock()
        cr_id, _, report, _ = _diagnosable(client)
        pool = _FakeProvisionedWorkerPool("provisioned-pool", cr_id)
        client.worker_pool_client.get_worker_pool_by_id.return_value = pool
        failures, output = _run(
            [_ydid("wrkrpool")], client, _args(show_source_report=True), capsys
        )
        assert failures == 0
        assert loads(output) == [pool.payload, report.payload]
        client.compute_client.get_compute_requirement_by_id.assert_called_once_with(
            cr_id
        )

    def test_a_configured_worker_pool_is_warned_of(self, capsys):
        client = MagicMock()
        pool = _FakeConfiguredWorkerPool("configured-pool")
        client.worker_pool_client.get_worker_pool_by_id.return_value = pool
        failures, output = _run(
            [_ydid("wrkrpool")], client, _args(show_exhaustion=True), capsys
        )
        assert failures == 0
        assert loads(output)["name"] == "configured-pool"  # Alone: no reports
        assert "not a Provisioned Worker Pool" in _WARNINGS[0]
        client.allowances_client.check_compute_requirement_exhaustion.assert_not_called()

    def test_a_missing_report_is_warned_of_and_the_rest_shown(self, capsys):
        client = MagicMock()
        cr_id, cr, _, notification = _diagnosable(client)
        compute = client.compute_client
        compute.get_best_compute_source_report_by_compute_requirement.side_effect = (
            _http_error(404)
        )
        failures, output = _run(
            [cr_id],
            client,
            _args(show_source_report=True, show_exhaustion=True),
            capsys,
        )
        assert failures == 0
        assert loads(output)[0] == cr.payload
        assert loads(output)[1]["exhaustedAllowances"] == [notification.payload]
        assert "No source report" in _WARNINGS[0]

    def test_another_report_failure_fails_the_id(self, capsys):
        client = MagicMock()
        cr_id, _, _, _ = _diagnosable(client)
        compute = client.compute_client
        compute.get_best_compute_source_report_by_compute_requirement.side_effect = (
            _http_error(500)
        )
        exit_code, _ = _run([cr_id], client, _args(show_source_report=True), capsys)
        assert exit_code == ExitCode.FAILURE

    def test_a_session_failure_stops_the_run(self, capsys):
        from yellowdog_cli.utils.exit_codes import ReportedFailure, classify

        client = MagicMock()
        cr_id, _, _, _ = _diagnosable(client)
        client.allowances_client.check_compute_requirement_exhaustion.side_effect = (
            _http_error(401)
        )
        with pytest.raises(ReportedFailure) as raised:
            _run([cr_id, cr_id], client, _args(show_exhaustion=True), capsys)
        assert classify(raised.value) == ExitCode.AUTHENTICATION


# ---------------------------------------------------------------------------
# '--show-members', and a User's groups
# ---------------------------------------------------------------------------

ROLE_ID = "ydid:role:6357e440-eb8d-44f4-8c0c-0b58fb535312"  # As the Platform gives it


def _member(id_: str, name: str, **extra) -> SimpleNamespace:
    return SimpleNamespace(id=id_, name=name, **extra)


class TestMembers:
    def test_a_groups_users_and_applications_follow_it(self, capsys):
        client = MagicMock()
        group_id = _ydid("group")
        group = _Obj("my-group")
        client.account_client.get_group.return_value = group
        client.account_client.get_group_users.return_value.list_all.return_value = [
            _member("ydid:user:1", "Alan Parry", username="alan"),
            _member("ydid:user:2", "Alan Parry"),  # External: no username
        ]
        applications = client.account_client.get_group_applications.return_value
        applications.list_all.return_value = [_member("ydid:app:1", "yd-demo")]

        failures, output = _run([group_id], client, _args(show_members=True), capsys)

        assert failures == 0
        parsed = loads(output)
        assert parsed[0]["name"] == "my-group"
        assert parsed[1] == {
            "groupId": group_id,
            "users": [
                {"id": "ydid:user:1", "username": "alan", "name": "Alan Parry"},
                {"id": "ydid:user:2", "username": None, "name": "Alan Parry"},
            ],
            "applications": [{"id": "ydid:app:1", "name": "yd-demo"}],
        }

    def test_a_group_with_no_members(self, capsys):
        client = MagicMock()
        client.account_client.get_group.return_value = _Obj("empty")
        client.account_client.get_group_users.return_value.list_all.return_value = []
        applications = client.account_client.get_group_applications.return_value
        applications.list_all.return_value = []
        _, output = _run([_ydid("group")], client, _args(show_members=True), capsys)
        assert loads(output)[1]["users"] == []
        assert loads(output)[1]["applications"] == []

    def test_the_groups_holding_a_role_follow_it(self, capsys):
        client = MagicMock()
        client.account_client.get_role.return_value = _Obj("work-manager")
        groups = client.account_client.get_role_groups.return_value
        groups.list_all.return_value = [_member("ydid:group:1", "raydog")]

        failures, output = _run([ROLE_ID], client, _args(show_members=True), capsys)

        assert failures == 0
        assert loads(output)[1] == {
            "roleId": ROLE_ID,
            "groups": [{"id": "ydid:group:1", "name": "raydog"}],
        }

    def test_without_the_option_nothing_is_looked_up(self, capsys):
        client = MagicMock()
        client.account_client.get_group.return_value = _Obj("my-group")
        _, output = _run([_ydid("group")], client, _args(), capsys)
        assert loads(output)["name"] == "my-group"
        client.account_client.get_group_users.assert_not_called()

    def test_a_session_failure_stops_the_run(self, capsys):
        from yellowdog_cli.utils.exit_codes import ReportedFailure, classify

        client = MagicMock()
        client.account_client.get_role.return_value = _Obj("work-manager")
        client.account_client.get_role_groups.side_effect = _http_error(401)
        with pytest.raises(ReportedFailure) as raised:
            _run([ROLE_ID, ROLE_ID], client, _args(show_members=True), capsys)
        assert classify(raised.value) == ExitCode.AUTHENTICATION

    def test_a_user_is_shown_with_its_groups(self, capsys):
        client = MagicMock()
        client.account_client.get_user.return_value = _Obj("pwt")
        client.account_client.get_user_groups.return_value.list_all.return_value = [
            _member("ydid:group:1", "administrators")
        ]
        _, output = _run([_ydid("user")], client, _args(), capsys)
        assert loads(output)["groups"] == ["administrators"]


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------


class TestFailures:
    def test_an_unresolvable_id_is_counted(self, capsys):
        failures, _ = _run(["not-a-ydid"], MagicMock(), _args(), capsys)
        assert failures == 1

    def test_a_failure_among_several_still_leaves_a_parseable_array(self, capsys):
        client = MagicMock()
        ydid, obj = _task(client)

        failures, output = _run([ydid, "not-a-ydid"], client, _args(), capsys)

        assert failures == 1
        # An array, not a bare object: the shape follows what was asked for,
        # not how much of it succeeded
        parsed = loads(output)
        assert isinstance(parsed, list)
        assert _names(parsed) == [obj.payload["name"]]

    def test_a_trailing_failure_leaves_no_trailing_comma(self, capsys):
        # The last ID failing is the case a streaming 'comma unless last index'
        # cannot get right
        client = MagicMock()
        ydid, obj = _node(client)

        failures, output = _run([ydid, ydid, "not-a-ydid"], client, _args(), capsys)

        assert failures == 1
        assert _names(loads(output)) == [obj.payload["name"], obj.payload["name"]]

    def test_every_id_failing_leaves_an_empty_array(self, capsys):
        exit_code, output = _run(
            ["not-a-ydid", "also-not"], MagicMock(), _args(), capsys
        )
        assert exit_code == ExitCode.FAILURE
        assert loads(output) == []


# ---------------------------------------------------------------------------
# Exit codes, and the IDs not attempted after a session failure
# ---------------------------------------------------------------------------


def _http_error(status_code: int) -> HTTPError:
    response = Response()
    response.status_code = status_code
    return HTTPError(f"{status_code} Client Error", response=response)


class TestExitCodes:
    def test_every_failure_a_not_found_exits_6(self, capsys):
        client = MagicMock()
        client.work_client.get_task_by_id.side_effect = _http_error(404)
        exit_code, output = _run(
            [_ydid("task"), _ydid("task")], client, _args(), capsys
        )
        assert exit_code == ExitCode.NOT_FOUND
        assert loads(output) == []

    def test_a_not_found_among_other_failures_exits_1(self, capsys):
        client = MagicMock()
        client.work_client.get_task_by_id.side_effect = _http_error(404)
        exit_code, _ = _run([_ydid("task"), "not-a-ydid"], client, _args(), capsys)
        assert exit_code == ExitCode.FAILURE

    def test_a_not_found_found_by_search_counts_as_not_found(self, capsys):
        # A Task Group absent from its (existing) Work Requirement
        client = MagicMock()
        client.work_client.get_work_requirement_by_id.return_value = SimpleNamespace(
            taskGroups=[]
        )
        tg = "ydid:taskgrp:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:1"
        exit_code, _ = _run([tg], client, _args(), capsys)
        assert exit_code == ExitCode.NOT_FOUND

    def test_a_session_failure_stops_and_keeps_what_was_shown(self, capsys):
        from yellowdog_cli.utils.exit_codes import ReportedFailure, classify

        client = MagicMock()
        ydid, obj = _task(client)
        node = _ydid("node")
        client.worker_pool_client.get_node_by_id.side_effect = _http_error(401)
        with pytest.raises(ReportedFailure) as raised:
            _run([ydid, node, _ydid("node"), _ydid("node")], client, _args(), capsys)
        assert classify(raised.value) == ExitCode.AUTHENTICATION
        # The one shown is still printed, as the array the request asked for
        assert _names(loads(capsys.readouterr().out)) == [obj.payload["name"]]
        assert client.worker_pool_client.get_node_by_id.call_count == 1


class TestCommandLine:
    def test_an_id_is_required(self, capsys):
        from yellowdog_cli.utils.args import CLIParser

        with pytest.raises(SystemExit) as raised:
            CLIParser(command="yd-show", argv=[])
        assert raised.value.code == 2

    def test_substitute_ids_needs_an_id_it_applies_to(self, capsys):
        from yellowdog_cli.utils.args import CLIParser

        with pytest.raises(SystemExit) as raised:
            CLIParser(command="yd-show", argv=["-U", _ydid("task")])
        assert raised.value.code == 2
        assert "--substitute-ids applies only to" in capsys.readouterr().err
        CLIParser(command="yd-show", argv=["-U", _ydid("task"), _ydid("allow")])

    @pytest.mark.parametrize("flag", ["--show-source-report", "--show-exhaustion"])
    def test_a_diagnostic_needs_an_id_it_applies_to(self, flag, capsys):
        from yellowdog_cli.utils.args import CLIParser

        with pytest.raises(SystemExit) as raised:
            CLIParser(command="yd-show", argv=[flag, _ydid("task")])
        assert raised.value.code == 2
        assert f"{flag} applies only to" in capsys.readouterr().err
        CLIParser(command="yd-show", argv=[flag, _ydid("task"), _ydid("compreq")])
        CLIParser(command="yd-show", argv=[flag, _ydid("wrkrpool")])

    def test_show_members_needs_a_group_or_role_id(self, capsys):
        from yellowdog_cli.utils.args import CLIParser

        with pytest.raises(SystemExit) as raised:
            CLIParser(command="yd-show", argv=["--show-members", _ydid("task")])
        assert raised.value.code == 2
        assert "--show-members applies only to" in capsys.readouterr().err
        CLIParser(command="yd-show", argv=["--show-members", ROLE_ID])
        CLIParser(command="yd-show", argv=["--show-members", _ydid("group")])

    def test_namespace_and_tag_are_not_options(self, capsys):
        from yellowdog_cli.utils.args import CLIParser

        with pytest.raises(SystemExit):
            CLIParser(command="yd-show", argv=["-n", "ns", _ydid("task")])


# ---------------------------------------------------------------------------
# '--hide-user-data'
# ---------------------------------------------------------------------------


def test_hide_user_data_summarises_a_compute_source_template(tmp_path, capsys):
    script = "#!/bin/sh\necho one\n"
    summary = "<user data: 19 characters, 2 lines>"
    client = MagicMock()
    obj = _Obj("cst")
    obj.payload["source"] = {"userData": script}
    client.compute_client.get_compute_source_template.return_value = obj
    output_file = tmp_path / "cst.json"

    failures, output = _run(
        [_ydid("cst")],
        client,
        _args(hide_user_data=True, output_file=str(output_file)),
        capsys,
    )

    assert failures == 0
    assert loads(output)["source"]["userData"] == summary
    written = loads(output_file.read_text(encoding="utf-8"))
    assert written["source"]["userData"] == summary
