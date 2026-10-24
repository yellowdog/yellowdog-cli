"""
yd-list: the filtering options refused where they do not apply
(check_list_options), and the listings' behaviour: PROVISIONING is active, '--details' fetches full Compute
Requirements, '--ids-only' lists every parent's children without asking (an
Instance as 'cr_id.instance_id'), the raw calls carry a timeout and keep
their exit codes, Groups and Roles are not fetched just for their IDs, and
Worker Pools are matched to the namespace exactly.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from requests import HTTPError, Response
from yellowdog_client.model import ComputeRequirementStatus

import yellowdog_cli.list as yd_list
import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli.utils.args import CLIParser
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    ET_ATTRIBUTE_DEFINITIONS,
    ET_COMPUTE_REQUIREMENTS,
    ET_GROUPS,
    ET_INSTANCES,
    ET_ROLES,
    ET_TASK_GROUPS,
    ET_TASKS,
    ET_WORKER_POOLS,
    ET_WORKERS,
)
from yellowdog_cli.utils.exit_codes import ExitCode, classify


def _ctx() -> RunContext:
    """
    The context a command is given: the wrapper's values, as patched.
    """
    return RunContext(
        wrapper_module.ARGS_PARSER, wrapper_module.CONFIG_COMMON, wrapper_module.CLIENT
    )


CR_ID = "ydid:compreq:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _args(entity_type: str, **values) -> Any:
    defaults = dict(
        entity_type=entity_type,
        json_output=False,
        count_only=False,
        ids_only=False,
        details=False,
        active_only=False,
        name_glob=None,
        status_filter=None,
        public_ips_only=False,
        substitute_ids=False,
        deletable=False,
        unhealthy=False,
        provider=None,
        description_glob=None,
        with_errors=False,
        within_target=None,
        list_limit=0,
    )
    defaults.update(values)
    return SimpleNamespace(**defaults)


@pytest.fixture
def listing(monkeypatch):
    """
    Patch list.py's collaborators; the test sets ARGS_PARSER itself.
    """
    client = MagicMock()
    monkeypatch.setattr(wrapper_module, "CLIENT", client)
    monkeypatch.setattr(
        wrapper_module,
        "CONFIG_COMMON",
        SimpleNamespace(
            namespace="ns",
            name_tag="tag",
            url="https://api.x",
            key="k",
            secret="s",
            request_timeout=(10.0, 90.0),
        ),
    )
    monkeypatch.setattr(yd_list, "sorted_objects", lambda objects: list(objects))
    monkeypatch.setattr(yd_list, "print_info", lambda *a, **k: None)
    select = MagicMock(side_effect=AssertionError("asked the user to choose"))
    monkeypatch.setattr(yd_list, "select", select)
    printed: list = []
    monkeypatch.setattr(yd_list, "print_objects_as_json", printed.append)
    monkeypatch.setattr(
        yd_list, "_print_json_or_count", lambda _ctx, objects: printed.append(objects)
    )
    return SimpleNamespace(client=client, printed=printed)


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv, message",
    [
        (["keyrings", "--status", "x"], "--status does not apply to keyrings"),
        (["users", "--active-only"], "--active-only does not apply to users"),
        (["permissions", "--ids-only"], "--ids-only does not apply to permissions"),
        (["users", "--substitute-ids"], "--substitute-ids does not apply to users"),
        (["nodes", "--public-ips-only"], "--public-ips-only does not apply to nodes"),
        (["instances", "--public-ips-only", "--json"], "cannot be used with --json"),
        (["nodes", "--name", "x*"], "--name does not apply to nodes"),
        (["keyrings", "--deletable"], "--deletable does not apply to keyrings"),
        (["keyrings", "--unhealthy"], "--unhealthy does not apply to keyrings"),
        (["tasks", "--provider", "aws"], "--provider does not apply to tasks"),
        (
            ["keyrings", "--description", "x*"],
            "--description does not apply to keyrings",
        ),
        (["instances", "--provider", "nimbus"], "invalid choice"),
        (
            ["task-groups", "--with-errors"],
            "--with-errors does not apply to task-groups",
        ),
        (
            ["work-requirements", "--within", "wr"],
            "--within does not apply to work-requirements",
        ),
        (
            ["tasks", "--within", CR_ID],
            "--within takes a Work Requirement or Task Group, not a Compute Requirement",
        ),
        (
            ["instances", "--within", CR_ID.replace("compreq", "wrkrpool")],
            "--within takes a Compute Requirement, not a Worker Pool",
        ),
        (
            ["nodes", "--within", CR_ID],
            "--within takes a Worker Pool, not a Compute Requirement",
        ),
        (
            ["workers", "--within", CR_ID],
            "--within takes a Worker Pool or Node, not a Compute Requirement",
        ),
        (
            ["compute-requirements", "--within", "cr"],
            "--within does not apply to compute-requirements",
        ),
        (["task-groups", "--limit", "5"], "--limit does not apply to task-groups"),
        (["worker-pools", "--limit", "5"], "--limit does not apply to worker-pools"),
        (
            ["instances", "--limit", "5", "--count"],
            "--limit cannot be used with --count",
        ),
        (["tasks", "--limit", "5", "--count"], "--limit cannot be used with --count"),
        (["tasks", "--limit", "-1"], "argument --limit"),
    ],
)
def test_an_option_that_does_not_apply_is_refused(argv, message, capsys):
    with pytest.raises(SystemExit) as raised:
        CLIParser(command="yd-list", argv=argv)
    assert raised.value.code == 2
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["instances", "--status", "RUNNING", "--active-only"],
        ["instances", "--public-ips-only"],
        ["compute-requirement-templates", "--substitute-ids"],
        ["tasks", "--ids-only", "--status", "FAILED"],
        ["worker-pools", "--name", "wp-*", "--active-only"],
        ["namespaces", "--name", "yd-*", "--deletable"],
        ["tasks", "--name", "row-*"],
        ["task-groups", "--name", "tg-*"],
        ["worker-pools", "--unhealthy"],
        ["instances", "--provider", "google"],
        ["nodes", "--provider", "on-premise"],
        ["compute-source-templates", "--provider", "aws"],
        ["allowances", "--description", "*-allowance"],
        ["tasks", "--with-errors", "--status", "COMPLETED"],
        ["tasks", "--within", "my-wr/tg-1", "--status", "failed"],
        ["task-groups", "--within", CR_ID.replace("compreq", "workreq")],
        ["instances", "--within", CR_ID, "--status", "running"],
        ["instances", "--within", "ns/my-cr", "--public-ips-only"],
        ["nodes", "--within", "my-pool", "--provider", "aws"],
        ["workers", "--within", CR_ID.replace("compreq", "node")],
        ["workers", "--within", CR_ID.replace("compreq", "wrkrpool")],
        ["tasks", "--limit", "10", "--json"],
        ["tasks", "--limit", "0"],
        ["instances", "--limit", "50", "--ids-only"],
        ["nodes", "--limit", "0", "--json"],
        ["workers", "--limit", "20", "--status", "doing_task"],
    ],
)
def test_an_option_that_applies_is_accepted(argv):
    CLIParser(command="yd-list", argv=argv)


# ---------------------------------------------------------------------------
# The listings
# ---------------------------------------------------------------------------


def test_active_compute_requirements_include_provisioning(listing, monkeypatch):
    monkeypatch.setattr(
        wrapper_module,
        "ARGS_PARSER",
        _args(ET_COMPUTE_REQUIREMENTS, active_only=True, json_output=True),
    )
    fetch = MagicMock(return_value=[])
    monkeypatch.setattr(yd_list, "get_compute_requirement_summaries", fetch)
    monkeypatch.setattr(yd_list, "_print_empty", lambda _ctx, message: None)
    yd_list.list_compute_requirements(_ctx())
    assert ComputeRequirementStatus.PROVISIONING in fetch.call_args.args[3]


def test_compute_requirement_details_are_the_full_objects(listing, monkeypatch):
    monkeypatch.setattr(
        wrapper_module,
        "ARGS_PARSER",
        _args(ET_COMPUTE_REQUIREMENTS, json_output=True, details=True),
    )
    summary = SimpleNamespace(id=CR_ID, name="cr", status=None)
    monkeypatch.setattr(
        yd_list, "get_compute_requirement_summaries", lambda *a, **k: [summary]
    )
    full = SimpleNamespace(id=CR_ID, name="cr", provisionStrategy="...")
    listing.client.compute_client.get_compute_requirement_by_id.return_value = full
    yd_list.list_compute_requirements(_ctx())
    assert listing.printed == [[full]]


def test_ids_only_lists_every_work_requirements_tasks_without_asking(
    listing, monkeypatch, capsys
):
    monkeypatch.setattr(wrapper_module, "ARGS_PARSER", _args(ET_TASKS, ids_only=True))
    monkeypatch.setattr(
        yd_list,
        "get_filtered_work_requirement_summaries",
        lambda *a, **k: [SimpleNamespace(id="wr1"), SimpleNamespace(id="wr2")],
    )
    monkeypatch.setattr(
        yd_list,
        "get_task_groups_from_wr_by_id",
        lambda client, wr_id: [SimpleNamespace(id=f"{wr_id}-tg", status=None)],
    )
    monkeypatch.setattr(
        yd_list,
        "iterate_tasks_in_task_group",
        lambda client, tg_id: [SimpleNamespace(id=f"{tg_id}-t", status=None)],
    )
    yd_list.list_work_requirements(_ctx())
    assert capsys.readouterr().out.split() == ["wr1-tg-t", "wr2-tg-t"]


def test_ids_only_names_an_instance_by_its_compute_requirement(
    listing, monkeypatch, capsys
):
    monkeypatch.setattr(
        wrapper_module, "ARGS_PARSER", _args(ET_INSTANCES, ids_only=True)
    )
    monkeypatch.setattr(
        yd_list,
        "get_compute_requirement_summaries",
        lambda *a, **k: [SimpleNamespace(id=CR_ID, name="cr", status=None)],
    )
    listing.client.compute_client.get_instances.return_value.iterate.return_value = [
        SimpleNamespace(id=SimpleNamespace(instanceId="i-1"), status=None)
    ]
    yd_list.list_compute_requirements(_ctx())
    assert capsys.readouterr().out.split() == [f"{CR_ID}.i-1"]


def test_attribute_definitions_carry_a_timeout_and_keep_the_exit_code(
    listing, monkeypatch
):
    monkeypatch.setattr(wrapper_module, "ARGS_PARSER", _args(ET_ATTRIBUTE_DEFINITIONS))
    response = Response()
    response.status_code = 401
    response._content = b"no"
    get = MagicMock(return_value=response)
    from yellowdog_cli.utils import entity_utils

    monkeypatch.setattr(entity_utils, "get", get)
    with pytest.raises(HTTPError) as raised:
        yd_list.list_attribute_definitions(_ctx())
    assert get.call_args.kwargs["timeout"] == _ctx().config.request_timeout
    assert classify(raised.value) == ExitCode.AUTHENTICATION


@pytest.mark.parametrize(
    "entity_type, lister, summaries, fetch",
    [
        (ET_GROUPS, "list_groups", "get_all_groups", "get_group"),
        (ET_ROLES, "list_roles", "get_all_roles", "get_role"),
    ],
)
def test_ids_only_does_not_fetch_each_one(
    listing, monkeypatch, capsys, entity_type, lister, summaries, fetch
):
    monkeypatch.setattr(
        wrapper_module, "ARGS_PARSER", _args(entity_type, ids_only=True)
    )
    monkeypatch.setattr(
        yd_list,
        summaries,
        lambda client: [
            SimpleNamespace(id="a", name="a"),
            SimpleNamespace(id="b", name="b"),
        ],
    )
    getattr(yd_list, lister)(_ctx())
    assert capsys.readouterr().out.split() == ["a", "b"]
    getattr(listing.client.account_client, fetch).assert_not_called()


def test_worker_pools_are_matched_to_the_namespace_exactly(listing, monkeypatch):
    monkeypatch.setattr(
        wrapper_module, "ARGS_PARSER", _args(ET_WORKER_POOLS, json_output=True)
    )
    monkeypatch.setattr(
        wrapper_module,
        "CONFIG_COMMON",
        SimpleNamespace(
            namespace="dev",
            name_tag="tag",
            url="https://api.x",
            request_timeout=(10.0, 90.0),
        ),
    )
    pools = [
        SimpleNamespace(id="a", name="a", namespace="dev", status=None),
        SimpleNamespace(id="b", name="b", namespace="dev-team", status=None),
    ]
    monkeypatch.setattr(yd_list, "get_worker_pool_summaries", lambda *a, **k: pools)
    yd_list.list_worker_pools(_ctx())
    assert [p.id for p in listing.printed[0]] == ["a"]


class TestActiveInstancesAndWorkers:
    """
    '--active-only' filters the Instances themselves as well as their Compute
    Requirements, so terminated ones are not listed; and a Worker on a Node
    without details is listed, not dropped.
    """

    @staticmethod
    def _instances(listing, monkeypatch, **args):
        monkeypatch.setattr(
            wrapper_module, "ARGS_PARSER", _args(ET_INSTANCES, active_only=True, **args)
        )
        monkeypatch.setattr(
            yd_list,
            "get_compute_requirement_summaries",
            lambda *a, **k: [SimpleNamespace(id=CR_ID, name="cr", status=None)],
        )
        listing.client.compute_client.get_instances.return_value.iterate.return_value = [
            SimpleNamespace(id=SimpleNamespace(instanceId="i-up"), status="RUNNING"),
            SimpleNamespace(
                id=SimpleNamespace(instanceId="i-gone"), status="TERMINATED"
            ),
        ]

    def test_terminated_instances_are_not_active(self, listing, monkeypatch):
        self._instances(listing, monkeypatch, json_output=True)
        yd_list.list_compute_requirements(_ctx())
        assert [i.id.instanceId for i in listing.printed[0]] == ["i-up"]

    def test_nor_in_the_listing_of_one_compute_requirement(self, listing, monkeypatch):
        self._instances(listing, monkeypatch)
        shown: list = []
        monkeypatch.setattr(
            yd_list,
            "print_numbered_object_list",
            lambda _c, objects: shown.extend(objects),
        )
        yd_list.list_instances(_ctx(), CR_ID)
        assert [i.id.instanceId for i in shown] == ["i-up"]

    def test_active_workers_are_those_the_sdk_calls_available(
        self, listing, monkeypatch
    ):
        # RUNNING is a busy Worker's status; DOING_TASK and SLEEPING are only
        # single allocation's
        from yellowdog_client.model import WorkerStatus

        monkeypatch.setattr(
            wrapper_module,
            "ARGS_PARSER",
            _args(ET_WORKERS, json_output=True, active_only=True),
        )
        workers = [SimpleNamespace(status=status) for status in WorkerStatus]
        node = SimpleNamespace(details=None, workers=workers, workerPoolName="wp")
        printed: list = []
        monkeypatch.setattr(
            yd_list, "_print_all", lambda _c, objects: printed.append(objects)
        )
        yd_list.list_workers(_ctx(), [node])
        assert {w.status.name for w in printed[0]} == {
            s.name
            for s in WorkerStatus
            if s not in (WorkerStatus.LOST, WorkerStatus.SHUTDOWN)
        }

    def test_a_worker_on_a_node_without_details_is_listed(self, listing, monkeypatch):
        monkeypatch.setattr(
            wrapper_module, "ARGS_PARSER", _args(ET_WORKERS, json_output=True)
        )
        worker = SimpleNamespace(status="SLEEPING")
        node = SimpleNamespace(details=None, workers=[worker], workerPoolName="wp")
        printed: list = []
        monkeypatch.setattr(
            yd_list, "_print_all", lambda _c, objects: printed.append(objects)
        )
        yd_list.list_workers(_ctx(), [node])
        assert printed == [[worker]]


@pytest.mark.parametrize(
    "lister, entity_type, fetcher",
    [
        ("list_users", "users", "get_all_users"),
        ("list_applications", "applications", "get_all_applications"),
        ("list_groups", "groups", "get_all_groups"),
        ("list_roles", "roles", "get_all_roles"),
    ],
)
def test_sort_and_reverse_apply_to_every_listing(
    listing, monkeypatch, lister, entity_type, fetcher
):
    # These follow --sort and --reverse outside the interactive selection too,
    # rather than a fixed sort by name
    monkeypatch.setattr(
        wrapper_module, "ARGS_PARSER", _args(entity_type, json_output=True)
    )
    entities = [SimpleNamespace(name=n, id=n) for n in ("a", "b", "c")]
    monkeypatch.setattr(yd_list, fetcher, lambda *a, **k: list(entities))
    # Groups and Roles are fetched in full for '--json', by their IDs
    for call in ("get_group", "get_role"):
        getattr(listing.client.account_client, call).side_effect = lambda id_: (
            SimpleNamespace(name=id_, permissions=[])
        )
    monkeypatch.setattr(
        yd_list, "sorted_objects", lambda objects: list(reversed(objects))
    )
    getattr(yd_list, lister)(_ctx())
    assert [e.name for e in listing.printed[0]] == ["c", "b", "a"]


@pytest.mark.parametrize(
    "lister, entity_type, client_call",
    [
        ("list_namespaces", "namespaces", "get_namespaces"),
        ("list_namespace_policies", "namespace-policies", "get_namespace_policies"),
    ],
)
def test_namespaces_and_policies_are_sorted(
    listing, monkeypatch, lister, entity_type, client_call
):
    monkeypatch.setattr(
        wrapper_module, "ARGS_PARSER", _args(entity_type, json_output=True)
    )
    monkeypatch.setattr(
        yd_list, "search_namespaces", lambda *a, **k: None, raising=False
    )
    entities = [SimpleNamespace(name=n, id=n, namespace=n) for n in ("a", "b")]
    getattr(
        listing.client.namespaces_client, client_call
    ).return_value.list_all.return_value = list(entities)
    monkeypatch.setattr(
        yd_list, "sorted_objects", lambda objects: list(reversed(objects))
    )
    getattr(yd_list, lister)(_ctx())
    assert [e.name for e in listing.printed[0]] == ["b", "a"]


class TestNamespaceFilters:
    """
    'yd list namespaces --name <glob>' and '--deletable': the Platform asked
    for names containing the glob's literal prefix and, with '--deletable',
    only namespaces that can be deleted; the glob applied to the namespace's
    name in what comes back.
    """

    def _listed(self, listing, monkeypatch, names, **values):
        monkeypatch.setattr(
            wrapper_module,
            "ARGS_PARSER",
            _args("namespaces", json_output=True, **values),
        )
        get = listing.client.namespaces_client.get_namespaces
        get.return_value.list_all.return_value = [
            SimpleNamespace(id=f"id-{n}", namespace=n, deletable=True) for n in names
        ]
        yd_list.list_namespaces(_ctx())
        (search,) = get.call_args.args
        return search, listing.printed

    def test_nothing_given_asks_for_every_namespace(self, listing, monkeypatch):
        search, printed = self._listed(listing, monkeypatch, ["a", "b"])
        assert search.namespaceContains is None
        assert search.deletable is None
        assert sorted(n.namespace for n in printed[0]) == ["a", "b"]

    def test_a_name_glob_narrows_the_search_and_is_matched_exactly(
        self, listing, monkeypatch
    ):
        # The Platform matches a substring: the glob decides
        search, printed = self._listed(
            listing,
            monkeypatch,
            ["yd-cli-tests", "my-yd-cli-x", "yd-cli-system-tests"],
            name_glob="yd-cli-*",
        )
        assert search.namespaceContains == "yd-cli-"
        assert sorted(n.namespace for n in printed[0]) == [
            "yd-cli-system-tests",
            "yd-cli-tests",
        ]

    def test_a_name_without_wildcards_is_that_namespace_alone(
        self, listing, monkeypatch
    ):
        search, printed = self._listed(
            listing, monkeypatch, ["ns", "ns-2"], name_glob="ns"
        )
        assert search.namespaceContains == "ns"
        assert [n.namespace for n in printed[0]] == ["ns"]

    def test_deletable_asks_for_deletable_namespaces(self, listing, monkeypatch):
        search, _ = self._listed(listing, monkeypatch, ["a"], deletable=True)
        assert search.deletable is True


class TestTheNewFilters:
    """
    The filters applied as each listing is built: '--name' on a Task's or
    Task Group's own name (never then on the Work Requirements walked to reach
    them), '--unhealthy' on 'healthy', '--provider' on an Instance's, a Node's
    or a Compute Source Template's provider, '--description' on an Allowance's.
    """

    @staticmethod
    def _ctx(entity_type, **values):
        return RunContext(args=_args(entity_type, **values), config=None, client=None)

    def test_a_name_glob_filters_the_type_listed_alone(self):
        tasks = [SimpleNamespace(name=n) for n in ("row-1", "row-2", "other", None)]
        ctx = self._ctx("tasks", name_glob="row-*")
        assert [t.name for t in yd_list._apply_name_filter(ctx, tasks, "tasks")] == [
            "row-1",
            "row-2",
        ]
        # The Task Groups walked to reach the Tasks are not filtered by it
        groups = [SimpleNamespace(name="tg")]
        assert yd_list._apply_name_filter(ctx, groups, "task-groups") == groups

    def test_unhealthy_keeps_only_what_the_platform_marks_unhealthy(self):
        entities = [
            SimpleNamespace(id=i, healthy=h)
            for i, h in ((1, True), (2, False), (3, None))
        ]
        ctx = self._ctx("worker-pools", unhealthy=True)
        assert [e.id for e in yd_list._apply_health_filter(ctx, entities)] == [2]
        assert (
            yd_list._apply_health_filter(self._ctx("worker-pools"), entities)
            == entities
        )

    def test_a_provider_is_matched_by_its_platform_name(self):
        from yellowdog_client.model import CloudProvider

        nodes = [
            SimpleNamespace(
                id=1, details=SimpleNamespace(provider=CloudProvider.GOOGLE)
            ),
            SimpleNamespace(id=2, details=SimpleNamespace(provider=CloudProvider.AWS)),
            SimpleNamespace(id=3, details=None),
        ]
        ctx = self._ctx("nodes", provider="google")
        kept = yd_list._apply_provider_filter(
            ctx, nodes, lambda n: n.details.provider if n.details else None
        )
        assert [n.id for n in kept] == [1]
        on_premise = [SimpleNamespace(provider=CloudProvider.ON_PREMISE)]
        ctx = self._ctx("instances", provider="on-premise")
        assert (
            yd_list._apply_provider_filter(ctx, on_premise, lambda i: i.provider)
            == on_premise
        )

    def test_a_description_glob_filters_allowances(self):
        allowances = [
            SimpleNamespace(id=i, description=d)
            for i, d in ((1, "ydst-x-allowance"), (2, "budget"), (3, None))
        ]
        ctx = self._ctx("allowances", description_glob="*-allowance")
        assert [a.id for a in yd_list._apply_description_filter(ctx, allowances)] == [1]

    def test_tasks_by_name_search_the_work_requirements_unfiltered(
        self, listing, monkeypatch
    ):
        monkeypatch.setattr(
            wrapper_module,
            "ARGS_PARSER",
            _args("tasks", json_output=True, name_glob="row-*"),
        )
        calls = []

        def summaries(client, **kwargs):
            calls.append(kwargs)
            return []

        monkeypatch.setattr(
            yd_list, "get_filtered_work_requirement_summaries", summaries
        )
        monkeypatch.setattr(yd_list, "_print_empty", lambda *a, **k: None)
        yd_list.list_work_requirements(_ctx())
        (kwargs,) = calls
        assert "name" not in kwargs


def test_with_errors_keeps_only_tasks_that_recorded_an_error():
    tasks = [
        SimpleNamespace(id=1, errors=[SimpleNamespace(message="boom")]),
        SimpleNamespace(id=2, errors=[]),
        SimpleNamespace(id=3, errors=None),
    ]
    ctx = RunContext(args=_args("tasks", with_errors=True), config=None, client=None)
    assert [t.id for t in yd_list._apply_errors_filter(ctx, tasks)] == [1]
    unset = RunContext(args=_args("tasks"), config=None, client=None)
    assert yd_list._apply_errors_filter(unset, tasks) == tasks


@pytest.mark.parametrize(
    "argv, statuses",
    [
        (["tasks", "--status", "failed,aborted"], ["failed", "aborted"]),
        (
            ["tasks", "--status", "failed, aborted", "--status", "completed"],
            ["failed", "aborted", "completed"],
        ),
        (["tasks", "--status", "FAILED"], ["FAILED"]),
        (["tasks", "--status", "failed,,"], ["failed"]),
    ],
)
def test_a_status_list_may_be_comma_separated(argv, statuses):
    assert CLIParser(command="yd-list", argv=argv).status_filter == statuses


class TestTaskSearchTerms:
    """
    The Task filters the Platform applies itself, so a Task Group of millions
    of Tasks sends only what is asked for: '--status' as 'statuses' (the
    Task statuses among those given), '--with-errors' as 'hasErrors', and
    '--name' as a substring every match contains (the Platform's 'name' is a
    case-sensitive substring, with no wildcards). The client-side filters
    still decide.
    """

    def _terms(self, monkeypatch, entity_type="tasks", **values):
        fetched = []
        monkeypatch.setattr(
            yd_list,
            "iterate_tasks_in_task_group",
            lambda client, tg_id, **terms: fetched.append(terms) or [],
        )
        ctx = RunContext(
            args=_args(entity_type, **values), config=None, client=MagicMock()
        )
        yd_list.list_tasks(ctx, SimpleNamespace(id="tg"), None)
        (terms,) = fetched
        return terms

    def test_nothing_given_sends_nothing(self, monkeypatch):
        assert self._terms(monkeypatch) == {}

    def test_the_filters_go_to_the_platform(self, monkeypatch):
        terms = self._terms(
            monkeypatch,
            status_filter=["failed", "Aborted", "bogus"],
            with_errors=True,
            name_glob="*-1",
        )
        assert terms == {
            "statuses": ("ABORTED", "FAILED"),
            "has_errors": True,
            "name_contains": "-1",
        }

    def test_a_glob_with_no_literal_run_sends_no_name(self, monkeypatch):
        assert self._terms(monkeypatch, name_glob="*") == {}


def test_the_task_search_carries_the_terms():
    from yellowdog_client.model import TaskStatus

    from yellowdog_cli.utils import entity_utils

    client = MagicMock()
    client.work_client.get_tasks.return_value.iterate.return_value = iter(())
    list(
        entity_utils.iterate_tasks_in_task_group(
            client, "tg", statuses=("FAILED",), has_errors=True, name_contains="row-"
        )
    )
    (search,) = client.work_client.get_tasks.call_args.args
    assert search.taskGroupId == "tg"
    assert search.statuses == [TaskStatus.FAILED]
    assert search.hasErrors is True
    assert search.name == "row-"


WR = "ydid:workreq:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TG1 = WR.replace("workreq", "taskgrp") + ":1"
TG2 = WR.replace("workreq", "taskgrp") + ":2"


class TestWithin:
    """
    '--within <target>': the Task Groups or Tasks of one Work Requirement or
    Task Group, named as yd-abort names one ('wr', 'wr/tg', 'namespace/wr',
    'namespace/wr/tg') or by its YDID, listed without asking which.
    """

    @staticmethod
    def _groups():
        return [
            SimpleNamespace(id=TG1, name="tg-1", status=None, taskSummary=None),
            SimpleNamespace(id=TG2, name="tg-2", status=None, taskSummary=None),
        ]

    def _ctx(self, monkeypatch, entity_type, target, **values):
        monkeypatch.setattr(
            yd_list,
            "get_task_groups_from_wr_by_id",
            lambda client, wr_id: self._groups(),
        )
        return RunContext(
            args=_args(entity_type, within_target=target, **values),
            config=SimpleNamespace(namespace="ns"),
            client=MagicMock(),
        )

    def test_a_work_requirement_id_gives_its_task_groups(self, monkeypatch):
        ctx = self._ctx(monkeypatch, "task-groups", WR)
        assert [g.id for g in yd_list._task_groups_within(ctx)] == [TG1, TG2]

    def test_a_task_group_id_gives_that_task_group(self, monkeypatch):
        ctx = self._ctx(monkeypatch, "tasks", TG2)
        assert [g.id for g in yd_list._task_groups_within(ctx)] == [TG2]

    def test_a_task_group_id_not_in_its_work_requirement_is_not_found(
        self, monkeypatch
    ):
        from yellowdog_cli.utils.exit_codes import ExitCode, NotFoundError, classify

        ctx = self._ctx(monkeypatch, "tasks", WR.replace("workreq", "taskgrp") + ":9")
        with pytest.raises(NotFoundError) as raised:
            yd_list._task_groups_within(ctx)
        assert classify(raised.value) == ExitCode.NOT_FOUND

    def test_another_kind_of_id_is_refused(self, monkeypatch):
        ctx = self._ctx(monkeypatch, "tasks", CR_ID)
        with pytest.raises(ValueError, match="not a Work Requirement or Task Group"):
            yd_list._task_groups_within(ctx)

    def test_a_name_is_resolved_as_yd_abort_resolves_it(self, monkeypatch):
        from yellowdog_cli.utils.work_targets import NamedTarget

        ctx = self._ctx(monkeypatch, "tasks", "my-wr/tg-1")
        seen = []

        def resolve(client, target, namespace):
            seen.append((target, namespace))
            return NamedTarget(SimpleNamespace(id=WR), self._groups()[0])

        monkeypatch.setattr(yd_list, "resolve_named_target", resolve)
        assert [g.id for g in yd_list._task_groups_within(ctx)] == [TG1]
        assert seen == [("my-wr/tg-1", "ns")]

    def test_the_tasks_within_are_listed_without_asking(
        self, listing, monkeypatch, capsys
    ):
        monkeypatch.setattr(
            wrapper_module,
            "ARGS_PARSER",
            _args("tasks", within_target=TG1, ids_only=True),
        )
        monkeypatch.setattr(
            yd_list,
            "get_task_groups_from_wr_by_id",
            lambda client, wr_id: self._groups(),
        )
        monkeypatch.setattr(
            yd_list,
            "iterate_tasks_in_task_group",
            lambda client, tg_id, **terms: [
                SimpleNamespace(
                    id=f"{tg_id}-t{i}", name=f"t{i}", status=None, errors=None
                )
                for i in (1, 2)
            ],
        )
        monkeypatch.setattr(yd_list, "select", MagicMock(side_effect=AssertionError))
        monkeypatch.setattr(
            yd_list,
            "get_filtered_work_requirement_summaries",
            MagicMock(side_effect=AssertionError),
        )
        yd_list.list_work_requirements(_ctx())
        assert capsys.readouterr().out.split() == [f"{TG1}-t1", f"{TG1}-t2"]

    def test_nothing_within_is_an_empty_array_under_json(self, listing, monkeypatch):
        monkeypatch.setattr(
            wrapper_module,
            "ARGS_PARSER",
            _args("tasks", within_target=TG1, json_output=True),
        )
        monkeypatch.setattr(
            yd_list,
            "get_task_groups_from_wr_by_id",
            lambda client, wr_id: self._groups(),
        )
        monkeypatch.setattr(
            yd_list, "iterate_tasks_in_task_group", lambda client, tg_id, **terms: []
        )
        yd_list.list_work_requirements(_ctx())
        assert listing.printed == [[]]

    def test_the_tasks_within_a_work_requirement_are_grouped_by_task_group(
        self, listing, monkeypatch, capsys
    ):
        monkeypatch.setattr(
            wrapper_module,
            "ARGS_PARSER",
            _args("tasks", within_target=WR, ids_only=True),
        )
        monkeypatch.setattr(
            yd_list,
            "get_task_groups_from_wr_by_id",
            lambda client, wr_id: self._groups(),
        )
        monkeypatch.setattr(
            yd_list,
            "iterate_tasks_in_task_group",
            lambda client, tg_id, **terms: [
                SimpleNamespace(
                    id=f"{tg_id}-t{i}", number=i, name=f"t{i}", status=None, errors=None
                )
                for i in (2, 1)
            ],
        )
        # Tasks sort by their number, which a Task Group's tasks share with
        # every other's
        monkeypatch.setattr(
            yd_list,
            "sorted_objects",
            lambda objects: sorted(objects, key=lambda o: getattr(o, "number", 0)),
        )
        yd_list.list_work_requirements(_ctx())
        assert capsys.readouterr().out.split() == [
            f"{TG1}-t1",
            f"{TG1}-t2",
            f"{TG2}-t1",
            f"{TG2}-t2",
        ]


WP_ID = CR_ID.replace("compreq", "wrkrpool")
NODE_ID = CR_ID.replace("compreq", "node")


class TestWithinCompute:
    """
    '--within' for Instances (a Compute Requirement), Nodes (a Worker Pool)
    and Workers (a Worker Pool or a Node): listed without searching the
    namespace or asking which.
    """

    @staticmethod
    def _no_search(monkeypatch):
        for searched in (
            "get_compute_requirement_summaries",
            "get_worker_pool_summaries",
        ):
            monkeypatch.setattr(
                yd_list, searched, MagicMock(side_effect=AssertionError(searched))
            )

    def test_the_instances_within_a_compute_requirement_id(
        self, listing, monkeypatch, capsys
    ):
        monkeypatch.setattr(
            wrapper_module,
            "ARGS_PARSER",
            _args(ET_INSTANCES, within_target=CR_ID, ids_only=True),
        )
        self._no_search(monkeypatch)
        listing.client.compute_client.get_instances.return_value.iterate.return_value = [
            SimpleNamespace(id=SimpleNamespace(instanceId="i-1"), status=None)
        ]
        yd_list.list_compute_requirements(_ctx())
        assert capsys.readouterr().out.split() == [f"{CR_ID}.i-1"]

    def test_a_compute_requirement_name_is_found_as_the_actions_find_it(
        self, listing, monkeypatch
    ):
        monkeypatch.setattr(
            wrapper_module,
            "ARGS_PARSER",
            _args(ET_INSTANCES, within_target="other/my-cr", json_output=True),
        )
        self._no_search(monkeypatch)
        seen = []

        def find(client, name, namespace, statuses):
            seen.append((name, namespace))
            return SimpleNamespace(id=CR_ID)

        monkeypatch.setattr(yd_list, "find_compute_requirement_by_name", find)
        listing.client.compute_client.get_instances.return_value.iterate.return_value = []
        yd_list.list_compute_requirements(_ctx())
        assert seen == [("other/my-cr", "ns")]
        assert listing.printed == [[]]

    def test_the_nodes_within_a_worker_pool_id(self, listing, monkeypatch):
        monkeypatch.setattr(
            wrapper_module,
            "ARGS_PARSER",
            _args("nodes", within_target=WP_ID, json_output=True),
        )
        self._no_search(monkeypatch)
        pool = SimpleNamespace(id=WP_ID, name="pool")
        monkeypatch.setattr(yd_list, "get_worker_pool_by_id", lambda c, wp_id: pool)
        listed = []
        monkeypatch.setattr(
            yd_list, "list_nodes", lambda _c, pools: listed.append(pools)
        )
        yd_list.list_worker_pools(_ctx())
        assert listed == [[pool]]

    def test_a_worker_pool_name_that_names_nothing_is_not_found(
        self, listing, monkeypatch
    ):
        from yellowdog_cli.utils.exit_codes import NotFoundError

        monkeypatch.setattr(
            wrapper_module,
            "ARGS_PARSER",
            _args("nodes", within_target="no-pool", json_output=True),
        )
        self._no_search(monkeypatch)
        monkeypatch.setattr(
            yd_list, "get_worker_pool_id_by_name", lambda c, name, namespace: None
        )
        with pytest.raises(NotFoundError, match="no-pool"):
            yd_list.list_worker_pools(_ctx())

    def test_the_workers_within_a_node_id(self, listing, monkeypatch):
        monkeypatch.setattr(
            wrapper_module,
            "ARGS_PARSER",
            _args(ET_WORKERS, within_target=NODE_ID, json_output=True),
        )
        self._no_search(monkeypatch)
        node = SimpleNamespace(id=NODE_ID, workerPoolId=WP_ID, workers=[])
        listing.client.worker_pool_client.get_node_by_id.return_value = node
        monkeypatch.setattr(
            yd_list,
            "get_worker_pool_by_id",
            lambda c, wp_id: SimpleNamespace(id=wp_id, name="pool"),
        )
        listed = []
        monkeypatch.setattr(
            yd_list, "list_workers", lambda _c, nodes: listed.append(nodes)
        )
        yd_list.list_worker_pools(_ctx())
        assert listed == [[node]]
        assert node.workerPoolName == "pool"


def test_a_worker_status_does_not_filter_their_nodes(listing, monkeypatch):
    # A Node is RUNNING while its Workers are DOING_TASK: '--status' is the
    # Workers'
    monkeypatch.setattr(
        wrapper_module,
        "ARGS_PARSER",
        _args(ET_WORKERS, status_filter=["DOING_TASK"], json_output=True),
    )
    worker = SimpleNamespace(status="DOING_TASK")
    node = SimpleNamespace(details=None, workers=[worker], status="RUNNING")
    listing.client.worker_pool_client.get_nodes.return_value.iterate.return_value = [
        node
    ]
    printed: list = []
    monkeypatch.setattr(
        yd_list, "_print_all", lambda _c, objects: printed.append(objects)
    )
    yd_list.list_nodes(_ctx(), [SimpleNamespace(id=WP_ID, name="pool")])
    assert printed == [[worker]]


@pytest.mark.parametrize("entity_type", [ET_TASKS, ET_TASK_GROUPS])
def test_a_task_status_does_not_filter_their_task_groups(
    listing, monkeypatch, entity_type
):
    # A Task Group is RUNNING while its Tasks are EXECUTING: '--status' is
    # the Tasks' when listing Tasks, and the Task Groups' only when listing them
    monkeypatch.setattr(
        wrapper_module,
        "ARGS_PARSER",
        _args(entity_type, status_filter=["EXECUTING"]),
    )
    task_group = SimpleNamespace(name="tg", status=SimpleNamespace(value="RUNNING"))
    monkeypatch.setattr(
        yd_list, "get_task_groups_from_wr_by_id", lambda client, wr_id: [task_group]
    )
    monkeypatch.setattr(yd_list, "select", lambda client, objects, **k: objects)
    shown: list = []
    monkeypatch.setattr(
        yd_list, "print_numbered_object_list", lambda _c, objects: shown.extend(objects)
    )
    walked: list[str] = []
    monkeypatch.setattr(
        yd_list, "list_tasks", lambda _c, tg, _wr: walked.append(tg.name)
    )
    yd_list.list_task_groups(_ctx(), SimpleNamespace(id="wr"))
    if entity_type == ET_TASKS:
        assert walked == ["tg"]
    else:
        assert shown == []


def _not_found(*_args, **_kwargs):
    response = Response()
    response.status_code = 404
    raise HTTPError("404 Client Error", response=response)


@pytest.mark.parametrize(
    "entity_type, target, patch, kind",
    [
        (
            ET_INSTANCES,
            CR_ID,
            ("client", "compute_client.get_compute_requirement_by_id"),
            "Compute Requirement",
        ),
        ("nodes", WP_ID, ("module", "get_worker_pool_by_id"), "Worker Pool"),
        (ET_WORKERS, NODE_ID, ("client", "worker_pool_client.get_node_by_id"), "Node"),
        (
            ET_TASKS,
            CR_ID.replace("compreq", "workreq"),
            ("module", "get_task_groups_from_wr_by_id"),
            "Work Requirement",
        ),
    ],
)
def test_an_id_within_that_names_nothing_is_not_found(
    listing, monkeypatch, entity_type, target, patch, kind
):
    from yellowdog_cli.utils.exit_codes import NotFoundError

    monkeypatch.setattr(
        wrapper_module,
        "ARGS_PARSER",
        _args(entity_type, within_target=target, json_output=True),
    )
    where, name = patch
    if where == "module":
        monkeypatch.setattr(yd_list, name, _not_found)
    else:
        owner, method = name.split(".")
        setattr(
            getattr(listing.client, owner), method, MagicMock(side_effect=_not_found)
        )
    listing.client.compute_client.get_instances.return_value.iterate.return_value = []
    lister = {
        ET_INSTANCES: yd_list.list_compute_requirements,
        "nodes": yd_list.list_worker_pools,
        ET_WORKERS: yd_list.list_worker_pools,
        ET_TASKS: yd_list.list_work_requirements,
    }[entity_type]
    with pytest.raises(NotFoundError) as raised:
        lister(_ctx())
    assert str(raised.value) == f"{kind} '{target}' not found"
    assert isinstance(raised.value.__cause__, HTTPError)


def test_the_limit_defaults_to_1000_and_0_lifts_it():
    assert CLIParser(command="yd-list", argv=["tasks"]).list_limit == 1000
    assert CLIParser(command="yd-list", argv=["nodes"]).list_limit == 1000
    assert CLIParser(command="yd-list", argv=["tasks", "--limit", "0"]).list_limit == 0
    assert CLIParser(command="yd-list", argv=["tasks", "--limit", "7"]).list_limit == 7


class TestTaskLimit:
    """
    '--limit': at most N Tasks across the listing, the search read only as
    far as N + 1 matches (to know whether more match), a warning on stderr
    when more do, and '--count' never limited.
    """

    @staticmethod
    def _run(listing, monkeypatch, groups, **values):
        """
        List the Tasks of one Work Requirement whose Task Groups' searches
        are 'groups' (a Task Group ID to its Tasks), counting how far each
        search was read; return the Tasks listed, the reads and the warnings.
        """
        monkeypatch.setattr(
            wrapper_module,
            "ARGS_PARSER",
            _args(ET_TASKS, within_target=WR, json_output=True, **values),
        )
        monkeypatch.setattr(
            yd_list,
            "get_task_groups_from_wr_by_id",
            lambda client, wr_id: [
                SimpleNamespace(id=tg_id, name=tg_id, status=None, taskSummary=None)
                for tg_id in groups
            ],
        )
        reads = {tg_id: 0 for tg_id in groups}

        def search(client, tg_id, **terms):
            for task in groups[tg_id]:
                reads[tg_id] += 1
                yield task

        monkeypatch.setattr(yd_list, "iterate_tasks_in_task_group", search)
        warnings: list[str] = []
        monkeypatch.setattr(
            yd_list, "print_warning", lambda text, **k: warnings.append(text)
        )
        yd_list.list_work_requirements(_ctx())
        (listed,) = listing.printed
        return [t.name for t in listed], reads, warnings

    @staticmethod
    def _tasks(prefix, count, **values):
        return [
            SimpleNamespace(
                id=f"{prefix}-{i}",
                name=f"{prefix}-{i}",
                status=None,
                **{"errors": None, **values},
            )
            for i in range(1, count + 1)
        ]

    def test_the_search_stops_one_past_the_limit(self, listing, monkeypatch):
        listed, reads, warnings = self._run(
            listing,
            monkeypatch,
            {TG1: self._tasks("a", 1000), TG2: self._tasks("b", 1000)},
            list_limit=3,
        )
        assert listed == ["a-1", "a-2", "a-3"]
        assert reads == {TG1: 4, TG2: 0}
        (warning,) = warnings
        assert "first 3 Tasks" in warning and "--limit 0" in warning

    def test_the_limit_is_across_task_groups(self, listing, monkeypatch):
        listed, reads, warnings = self._run(
            listing,
            monkeypatch,
            {TG1: self._tasks("a", 2), TG2: self._tasks("b", 5)},
            list_limit=3,
        )
        assert listed == ["a-1", "a-2", "b-1"]
        assert reads == {TG1: 2, TG2: 2}
        assert len(warnings) == 1

    def test_the_limit_reached_exactly_with_no_more_is_no_warning(
        self, listing, monkeypatch
    ):
        listed, reads, warnings = self._run(
            listing,
            monkeypatch,
            {TG1: self._tasks("a", 3), TG2: []},
            list_limit=3,
        )
        assert listed == ["a-1", "a-2", "a-3"]
        assert reads == {TG1: 3, TG2: 0}
        assert warnings == []

    def test_more_in_the_next_task_group_is_found(self, listing, monkeypatch):
        listed, reads, warnings = self._run(
            listing,
            monkeypatch,
            {TG1: self._tasks("a", 3), TG2: self._tasks("b", 2)},
            list_limit=3,
        )
        assert listed == ["a-1", "a-2", "a-3"]
        assert reads == {TG1: 3, TG2: 1}
        assert len(warnings) == 1

    def test_0_lists_them_all(self, listing, monkeypatch):
        listed, reads, warnings = self._run(
            listing, monkeypatch, {TG1: self._tasks("a", 1500)}, list_limit=0
        )
        assert len(listed) == 1500
        assert reads == {TG1: 1500}
        assert warnings == []

    def test_the_limit_counts_only_the_tasks_a_name_glob_keeps(
        self, listing, monkeypatch
    ):
        # The Platform matches '--name' as a substring; the glob is applied
        # as the search is read, so the limit is of matching Tasks
        tasks = [
            SimpleNamespace(id=str(i), name=name, status=None, errors=None)
            for i, name in enumerate(
                ["xrow-1", "row-1", "xrow-2", "xrow-3", "row-2", "row-3"]
            )
        ]
        listed, reads, warnings = self._run(
            listing, monkeypatch, {TG1: tasks}, list_limit=2, name_glob="row-*"
        )
        assert listed == ["row-1", "row-2"]
        assert reads == {TG1: 6}
        assert len(warnings) == 1

    def test_count_is_never_limited(self, listing, monkeypatch, capsys):
        monkeypatch.setattr(
            wrapper_module,
            "ARGS_PARSER",
            _args(
                ET_TASKS,
                within_target=WR,
                count_only=True,
                with_errors=True,
                list_limit=1000,
            ),
        )
        monkeypatch.setattr(
            yd_list,
            "get_task_groups_from_wr_by_id",
            lambda client, wr_id: [
                SimpleNamespace(id=TG1, name="tg", status=None, taskSummary=None)
            ],
        )
        monkeypatch.setattr(
            yd_list,
            "iterate_tasks_in_task_group",
            lambda client, tg_id, **terms: iter(
                self._tasks("a", 1200, errors=[SimpleNamespace(message="boom")])
            ),
        )
        yd_list.list_work_requirements(_ctx())
        assert capsys.readouterr().out.strip() == "1200"


class TestInstanceAndNodeLimit:
    """
    '--limit' for Instances and Nodes, which can number in the tens of
    thousands: across Compute Requirements or Worker Pools, each search read
    one past it, the filters applied as it is read; never for Workers (whose
    Nodes are all read) or '--count'.
    """

    @staticmethod
    def _searches(owner, method, groups):
        """
        Fake a search per parent ('groups', a parent ID to its items),
        counting how far each is read.
        """
        reads = {parent: 0 for parent in groups}

        def search(**kwargs):
            (criteria,) = kwargs.values()
            parent = getattr(criteria, "computeRequirementId", None) or getattr(
                criteria, "workerPoolId", None
            )

            def read():
                for item in groups[parent]:
                    reads[parent] += 1
                    yield item

            return SimpleNamespace(iterate=read)

        setattr(owner, method, search)
        return reads

    @staticmethod
    def _warnings(monkeypatch):
        warnings: list[str] = []
        monkeypatch.setattr(
            yd_list, "print_warning", lambda text, **k: warnings.append(text)
        )
        return warnings

    @staticmethod
    def _instances(prefix, count, status="RUNNING"):
        return [
            SimpleNamespace(
                id=SimpleNamespace(instanceId=f"{prefix}-{i}"),
                status=status,
                provider=None,
            )
            for i in range(1, count + 1)
        ]

    def test_instances_across_compute_requirements(self, listing, monkeypatch, capsys):
        cr2 = CR_ID.replace("aaaa-aaaa-aaaaaaaaaaaa", "bbbb-bbbb-bbbbbbbbbbbb")
        monkeypatch.setattr(
            wrapper_module,
            "ARGS_PARSER",
            _args(ET_INSTANCES, ids_only=True, list_limit=3),
        )
        monkeypatch.setattr(
            yd_list,
            "get_compute_requirement_summaries",
            lambda *a, **k: [
                SimpleNamespace(id=cr, name=cr, status=None) for cr in (CR_ID, cr2)
            ],
        )
        reads = self._searches(
            listing.client.compute_client,
            "get_instances",
            {CR_ID: self._instances("a", 2), cr2: self._instances("b", 50)},
        )
        warnings = self._warnings(monkeypatch)
        yd_list.list_compute_requirements(_ctx())
        assert capsys.readouterr().out.split() == [
            f"{CR_ID}.a-1",
            f"{CR_ID}.a-2",
            f"{cr2}.b-1",
        ]
        assert reads == {CR_ID: 2, cr2: 2}
        (warning,) = warnings
        assert "first 3 Instances" in warning

    def test_the_instance_limit_counts_what_the_filters_keep(
        self, listing, monkeypatch
    ):
        monkeypatch.setattr(
            wrapper_module,
            "ARGS_PARSER",
            _args(
                ET_INSTANCES,
                within_target=CR_ID,
                json_output=True,
                list_limit=2,
                active_only=True,
            ),
        )
        instances = [
            *self._instances("gone", 5, status="TERMINATED"),
            *self._instances("up", 3),
        ]
        reads = self._searches(
            listing.client.compute_client, "get_instances", {CR_ID: instances}
        )
        warnings = self._warnings(monkeypatch)
        yd_list.list_compute_requirements(_ctx())
        (listed,) = listing.printed
        assert [i.id.instanceId for i in listed] == ["up-1", "up-2"]
        assert reads == {CR_ID: 8}
        assert len(warnings) == 1

    def test_nodes_across_worker_pools(self, listing, monkeypatch):
        monkeypatch.setattr(
            wrapper_module,
            "ARGS_PARSER",
            _args("nodes", json_output=True, list_limit=3),
        )
        wp2 = WP_ID.replace("aaaa-aaaa-aaaaaaaaaaaa", "bbbb-bbbb-bbbbbbbbbbbb")
        nodes = {
            wp: [
                SimpleNamespace(id=f"{wp}-{i}", status="RUNNING", details=None)
                for i in range(4)
            ]
            for wp in (WP_ID, wp2)
        }
        reads = self._searches(listing.client.worker_pool_client, "get_nodes", nodes)
        warnings = self._warnings(monkeypatch)
        printed: list = []
        monkeypatch.setattr(
            yd_list, "_print_all", lambda _c, objects: printed.append(objects)
        )
        yd_list.list_nodes(
            _ctx(),
            [SimpleNamespace(id=WP_ID, name="a"), SimpleNamespace(id=wp2, name="b")],
        )
        (listed,) = printed
        assert [n.id for n in listed] == [f"{WP_ID}-{i}" for i in range(3)]
        assert reads == {WP_ID: 4, wp2: 0}
        (warning,) = warnings
        assert "first 3 Nodes" in warning

    def test_workers_read_their_nodes_only_as_far_as_the_limit(
        self, listing, monkeypatch
    ):
        monkeypatch.setattr(
            wrapper_module,
            "ARGS_PARSER",
            _args(ET_WORKERS, json_output=True, list_limit=3),
        )
        nodes = [
            SimpleNamespace(
                id=str(i),
                status="RUNNING",
                details=None,
                workers=[
                    SimpleNamespace(id=f"w{i}-{j}", status="SLEEPING") for j in range(2)
                ],
            )
            for i in range(5)
        ]
        reads = self._searches(
            listing.client.worker_pool_client, "get_nodes", {WP_ID: nodes}
        )
        warnings = self._warnings(monkeypatch)
        printed: list = []
        monkeypatch.setattr(
            yd_list, "_print_all", lambda _c, objects: printed.append(objects)
        )
        yd_list.list_nodes(_ctx(), [SimpleNamespace(id=WP_ID, name="a")])
        (listed,) = printed
        assert [w.id for w in listed] == ["w0-0", "w0-1", "w1-0"]
        assert reads == {WP_ID: 2}
        (warning,) = warnings
        assert "first 3 Workers" in warning

    def test_counting_instances_is_never_limited(self, listing, monkeypatch, capsys):
        monkeypatch.setattr(
            wrapper_module,
            "ARGS_PARSER",
            _args(ET_INSTANCES, within_target=CR_ID, count_only=True, list_limit=1000),
        )
        self._searches(
            listing.client.compute_client,
            "get_instances",
            {CR_ID: self._instances("a", 1200)},
        )
        monkeypatch.setattr(
            yd_list, "_print_json_or_count", lambda _c, objects: print(len(objects))
        )
        yd_list.list_compute_requirements(_ctx())
        assert capsys.readouterr().out.strip() == "1200"


class TestPlatformSideFilters:
    """
    '--status', '--provider' and '--active-only' sent with the Instance and
    Node searches, so the Platform sends only what can match; nothing
    searched when nothing can.
    """

    @staticmethod
    def _search(owner, method, monkeypatch, entity_type, **values):
        from yellowdog_cli.utils.output_settings import configured

        args = _args(entity_type, **values)
        client = MagicMock()
        getattr(client, owner).__getattr__(
            method
        ).return_value.iterate.return_value = []
        ctx = RunContext(args=args, config=None, client=client)
        with configured(args):
            if entity_type == ET_INSTANCES:
                list(yd_list._matching_instances(ctx, CR_ID))
            else:
                list(yd_list._matching_nodes(ctx, SimpleNamespace(id=WP_ID, name="a")))
        calls = getattr(getattr(client, owner), method).call_args_list
        return calls[0].kwargs.popitem()[1] if calls else None

    def test_an_instance_search_carries_statuses_and_provider(self, monkeypatch):
        from yellowdog_client.model import CloudProvider, InstanceStatus

        search = self._search(
            "compute_client",
            "get_instances",
            monkeypatch,
            ET_INSTANCES,
            status_filter=["running", "bogus"],
            provider="aws",
        )
        assert search.computeRequirementId == CR_ID
        assert search.statuses == [InstanceStatus.RUNNING]
        assert search.providers == [CloudProvider.AWS]

    def test_active_instances_are_any_but_terminated(self, monkeypatch):
        from yellowdog_client.model import InstanceStatus

        search = self._search(
            "compute_client",
            "get_instances",
            monkeypatch,
            ET_INSTANCES,
            active_only=True,
        )
        assert set(search.statuses) == set(InstanceStatus) - {InstanceStatus.TERMINATED}
        assert search.providers is None

    def test_no_instance_can_match_so_none_is_searched(self, monkeypatch):
        for values in (
            {"status_filter": ["terminated"], "active_only": True},
            {"status_filter": ["bogus"]},
        ):
            assert (
                self._search(
                    "compute_client",
                    "get_instances",
                    monkeypatch,
                    ET_INSTANCES,
                    **values,
                )
                is None
            ), values

    def test_a_node_search_carries_statuses_and_provider(self, monkeypatch):
        from yellowdog_client.model import CloudProvider, NodeStatus

        search = self._search(
            "worker_pool_client",
            "get_nodes",
            monkeypatch,
            "nodes",
            status_filter=["lost"],
            provider="on-premise",
        )
        assert search.workerPoolId == WP_ID
        assert search.statuses == [NodeStatus.LOST]
        assert search.providers == [CloudProvider.ON_PREMISE]

    def test_active_nodes_are_running(self, monkeypatch):
        from yellowdog_client.model import NodeStatus

        search = self._search(
            "worker_pool_client", "get_nodes", monkeypatch, "nodes", active_only=True
        )
        assert search.statuses == [NodeStatus.RUNNING]
        assert (
            self._search(
                "worker_pool_client",
                "get_nodes",
                monkeypatch,
                "nodes",
                active_only=True,
                status_filter=["lost"],
            )
            is None
        )

    def test_a_workers_status_is_not_sent_for_their_nodes(self, monkeypatch):
        from yellowdog_client.model import NodeStatus

        search = self._search(
            "worker_pool_client",
            "get_nodes",
            monkeypatch,
            ET_WORKERS,
            status_filter=["doing_task"],
            active_only=True,
        )
        assert search.statuses == [NodeStatus.RUNNING]


def test_a_limit_of_one_is_worded_in_the_singular(monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(
        yd_list, "print_warning", lambda text, **k: warnings.append(text)
    )
    ctx = RunContext(args=_args(ET_INSTANCES, list_limit=1), config=None, client=None)
    limit = yd_list._ListLimit(ctx)
    assert limit.take(iter(["a", "b"])) == ["a"]
    limit.warn()
    (warning,) = warnings
    assert warning.startswith("Listed the first Instance; more match.")


class TestEmit:
    """
    The output the resource listers share (list.py's _emit()).
    """

    @staticmethod
    def _objects():
        return [SimpleNamespace(id="b", name="b"), SimpleNamespace(id="a", name="a")]

    def _emit(self, monkeypatch, capsys, **values):
        printed: dict = {}
        monkeypatch.setattr(
            yd_list, "sorted_objects", lambda o: sorted(o, key=lambda x: x.id)
        )
        monkeypatch.setattr(
            yd_list, "print_objects_as_json", lambda o: printed.update(json=o)
        )
        monkeypatch.setattr(yd_list, "select", lambda client, o, **k: o)
        monkeypatch.setattr(
            yd_list, "print_yd_object_list", lambda o: printed.update(details=o)
        )
        monkeypatch.setattr(
            yd_list, "print_info", lambda m, **k: printed.update(info=m)
        )
        monkeypatch.setattr(
            yd_list,
            "print_numbered_object_list",
            lambda client, o, object_type_name=None: printed.update(
                table=(o, object_type_name)
            ),
        )
        ctx = SimpleNamespace(args=_args("keyrings", **values), client=None)
        yd_list._emit(
            ctx,
            self._objects(),
            detail=lambda o: f"full {o.id}",
            extra=lambda o: {"resource": "X"},
            type_name="Thing",
            announce="substituting",
        )
        return printed, capsys.readouterr().out

    def test_json_with_details_is_each_in_full(self, monkeypatch, capsys):
        printed, _ = self._emit(monkeypatch, capsys, json_output=True, details=True)
        assert printed["json"] == ["full a", "full b"]

    def test_ids_are_sorted(self, monkeypatch, capsys):
        _, out = self._emit(monkeypatch, capsys, ids_only=True)
        assert out.split() == ["a", "b"]

    def test_the_table_names_the_type(self, monkeypatch, capsys):
        printed, _ = self._emit(monkeypatch, capsys)
        assert [o.id for o in printed["table"][0]] == ["a", "b"]
        assert printed["table"][1] == "Thing"

    def test_details_are_in_full_with_their_extra_after_the_announcement(
        self, monkeypatch, capsys
    ):
        printed, _ = self._emit(monkeypatch, capsys, details=True, substitute_ids=True)
        assert printed["details"] == [
            ("full a", {"resource": "X"}),
            ("full b", {"resource": "X"}),
        ]
        assert printed["info"] == "substituting"
