"""
yd-list: the filtering options refused where they do not apply
(check_list_options), and the listings' behaviour the review of list.py
changed: PROVISIONING is active, '--details' fetches full Compute
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
    ET_TASKS,
    ET_WORKER_POOLS,
    ET_WORKERS,
)
from yellowdog_cli.utils.exit_codes import ExitCode, classify
from yellowdog_cli.utils.limits import RAW_REQUEST_TIMEOUT


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
            namespace="ns", name_tag="tag", url="https://api.x", key="k", secret="s"
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
        "get_all_tasks_in_task_group",
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
    listing.client.compute_client.get_instances.return_value.list_all.return_value = [
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
    monkeypatch.setattr(yd_list, "get", get)
    with pytest.raises(HTTPError) as raised:
        yd_list.list_attribute_definitions(_ctx())
    assert get.call_args.kwargs["timeout"] == RAW_REQUEST_TIMEOUT
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
        SimpleNamespace(namespace="dev", name_tag="tag", url="https://api.x"),
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
    '--active-only' filtered Instances' Compute Requirements but not the
    Instances themselves, so terminated ones were listed; and a Worker on a
    Node without details was dropped, its append indented under the details.
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
        listing.client.compute_client.get_instances.return_value.list_all.return_value = [
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
    # These sorted by name whatever --sort or --reverse said (and Namespaces
    # and Namespace Policies not at all), outside the interactive selection
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
