"""
Unit tests for compute_action_common.py: yd-compute-stop, yd-compute-start
and yd-compute-restart, against a fake Platform.

Covers:
  - the tag-based listing, and glob patterns expanded to Compute Requirements
  - explicit targets: Compute Requirement IDs and names, Instances in
    'cr_id.instance_id' form, and Node IDs, resolved in the order given,
    confirmed once, and acted on with one call per Compute Requirement for
    its Instances
  - what each outcome records ('stopped', 'skipped', 'failed'), and that a
    session failure (authentication, connection) stops the run, recording
    the rest as not attempted
  - '--follow', given only the Compute Requirements actioned, once each
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from requests import ConnectionError as RequestsConnectionError
from requests import HTTPError, Response
from yellowdog_client.model import (
    ComputeRequirementStatus,
    ConfiguredWorkerPool,
    InstanceStatus,
    NodeStatus,
    ProvisionedWorkerPool,
)

import yellowdog_cli.utils.compute_action_common as cac_module
from yellowdog_cli.utils import entity_utils
from yellowdog_cli.utils.command_registry import COMMANDS, build_parser
from yellowdog_cli.utils.compute_action_common import (
    COMPUTE_RESTART,
    COMPUTE_START,
    COMPUTE_STOP,
    COMPUTE_TERMINATE,
    apply_compute_action,
)
from yellowdog_cli.utils.exit_codes import SESSION_FAILURES, ReportedFailure, classify
from yellowdog_cli.utils.ydid_utils import get_ydid_type

CR_ID = "ydid:compreq:d9c548:98879b5a-9192-4a56-ad25-fc1330e49185"
CR_ID_2 = "ydid:compreq:d9c548:11111111-2222-3333-4444-555555555555"
CR_ID_OLD = "ydid:compreq:d9c548:00000000-0000-0000-0000-000000000000"
NODE_ID = "ydid:node:d9c548:f9d5a10e-5b0e-4b76-b50f-d2bbac0a5cb8"
WP_ID = "ydid:wrkrpool:d9c548:f9d5a10e-5b0e-4b76-b50f-d2bbac0a5cb8"
INSTANCE_ID = "i-0123456789abcdef0"
INSTANCE_ID_2 = "i-0fedcba9876543210"
# OCI instance IDs (OCIDs) contain dots of their own
OCI_INSTANCE_ID = (
    "ocid1.instance.oc1.uk-london-1."
    "anwgiljtbfkcyvycib2ubsewuwqqffx2jzyp7dolkhxanfvdsgvjzjrytepa"
)

RUNNING = ComputeRequirementStatus.RUNNING
STOPPED = ComputeRequirementStatus.STOPPED
TERMINATED = ComputeRequirementStatus.TERMINATED


def _http_error(status_code: int) -> HTTPError:
    response = Response()
    response.status_code = status_code
    return HTTPError(f"{status_code} Client Error", response=response)


def _cr(id_: str, name: str, status=RUNNING, namespace: str = "ns") -> Any:
    return SimpleNamespace(id=id_, name=name, status=status, namespace=namespace)


def _instance(instance_id: str, status=InstanceStatus.RUNNING) -> Any:
    return SimpleNamespace(id=SimpleNamespace(instanceId=instance_id), status=status)


def _provisioned_pool(cr_id: str | None = CR_ID) -> ProvisionedWorkerPool:
    pool = ProvisionedWorkerPool()
    pool.computeRequirementId = cr_id
    return pool


class FakePlatform:
    """
    Compute Requirements, Instances, Nodes and Worker Pools, served through a
    mock client; 'calls' lists every action taken, and 'records' every
    outcome recorded.
    """

    def __init__(self):
        self.crs: dict[str, Any] = {CR_ID: _cr(CR_ID, "cr-a")}
        self.instances: dict[tuple[str, str], Any] = {
            (CR_ID, INSTANCE_ID): _instance(INSTANCE_ID)
        }
        self.nodes: dict[str, Any] = {}
        self.pools: dict[str, Any] = {}
        self.calls: list[tuple] = []
        self.records: list[dict] = []
        self.failures: dict[str, Exception] = {}  # action method -> exception
        self.lookup_failure: Exception | None = None

        client = MagicMock()
        compute = client.compute_client
        compute.get_compute_requirement_by_id.side_effect = self._get_cr
        compute.get_instances.side_effect = lambda search: SimpleNamespace(
            list_all=lambda: [
                instance
                for (cr_id, _), instance in self.instances.items()
                if cr_id == search.computeRequirementId
            ]
        )
        for method in (
            "stop_compute_requirement_by_id",
            "start_compute_requirement_by_id",
            "stop_instances",
            "start_instances",
            "restart_instances",
            "terminate_compute_requirement_by_id",
            "terminate_instances",
        ):
            getattr(compute, method).side_effect = self._action(method)
        client.worker_pool_client.get_node_by_id.side_effect = self._lookup(self.nodes)
        client.worker_pool_client.get_worker_pool_by_id.side_effect = self._lookup(
            self.pools
        )
        self.client = client

    def _get_cr(self, cr_id):
        if self.lookup_failure is not None:
            raise self.lookup_failure
        if cr_id not in self.crs:
            raise _http_error(404)
        return self.crs[cr_id]

    def _lookup(self, table):
        def lookup(entity_id):
            if entity_id not in table:
                raise _http_error(404)
            return table[entity_id]

        return lookup

    def _action(self, method):
        def act(*args):
            if method in self.failures:
                raise self.failures[method]
            if method.endswith("_by_id"):
                self.calls.append((method, args[0]))
                return self.crs.get(args[0])
            compute_requirement, instances = args
            self.calls.append(
                (method, compute_requirement.id, [i.id.instanceId for i in instances])
            )
            return None

        return act

    def outcomes(self) -> list[tuple]:
        return [(r["id"], r["type"], r["outcome"]) for r in self.records]


@pytest.fixture
def platform(monkeypatch):
    fake = FakePlatform()
    monkeypatch.setattr(cac_module, "CLIENT", fake.client)
    monkeypatch.setattr(
        cac_module,
        "CONFIG_COMMON",
        SimpleNamespace(namespace="ns", name_tag="tag", url="https://api.x"),
    )
    monkeypatch.setattr(cac_module, "confirmed", lambda message: True)
    monkeypatch.setattr(cac_module, "select", lambda client, objects: objects)
    monkeypatch.setattr(cac_module, "follow_ids", MagicMock())

    def get_summaries(client, namespace, tag=None, statuses=None, name=None):
        return [
            cr
            for cr in fake.crs.values()
            if cr.namespace == namespace
            and (statuses is None or cr.status in statuses)
            and (name is None or name in cr.name)
        ]

    monkeypatch.setattr(cac_module, "get_compute_requirement_summaries", get_summaries)

    def record_action(entity, entity_type, action, outcome, error=None):
        if isinstance(entity, str):  # as results.record_action() names it
            is_ydid = get_ydid_type(entity) is not None
            entity = {
                "id": entity if is_ydid else None,
                "name": None if is_ydid else entity,
            }
        elif not isinstance(entity, dict):
            entity = {"id": entity.id, "name": entity.name}
        fake.records.append(
            {**entity, "type": entity_type, "outcome": outcome, "error": error}
        )

    monkeypatch.setattr(cac_module, "record_action", record_action)
    cac_module.get_instance_by_id.cache_clear()
    entity_utils._get_instances.cache_clear()
    yield fake
    cac_module.get_instance_by_id.cache_clear()
    entity_utils._get_instances.cache_clear()


def _run(
    monkeypatch,
    action,
    targets: list[str],
    follow: bool = False,
    dry_run: bool | None = None,
):
    monkeypatch.setattr(
        cac_module,
        "ARGS_PARSER",
        SimpleNamespace(
            compute_requirements_instances_or_nodes=targets,
            follow=follow,
            dry_run=dry_run,
            json_output=False,
        ),
    )
    apply_compute_action(action)


# ---------------------------------------------------------------------------
# Listing: by tag, or by glob pattern
# ---------------------------------------------------------------------------


class TestListing:
    def test_the_tag_path_acts_on_crs_in_a_valid_state(self, platform, monkeypatch):
        platform.crs[CR_ID_2] = _cr(CR_ID_2, "cr-b", STOPPED)
        _run(monkeypatch, COMPUTE_STOP, [])
        assert platform.calls == [("stop_compute_requirement_by_id", CR_ID)]
        assert platform.outcomes() == [(CR_ID, "compute-requirements", "stopped")]

    def test_a_glob_selects_matching_names_only(self, platform, monkeypatch):
        platform.crs[CR_ID_2] = _cr(CR_ID_2, "other")
        _run(monkeypatch, COMPUTE_STOP, ["cr-*"])
        assert platform.calls == [("stop_compute_requirement_by_id", CR_ID)]

    def test_a_glob_respects_the_actions_states(self, platform, monkeypatch):
        _run(monkeypatch, COMPUTE_START, ["cr-*"])  # cr-a is RUNNING
        assert platform.calls == []

    def test_declining_skips_everything(self, platform, monkeypatch):
        monkeypatch.setattr(cac_module, "confirmed", lambda message: False)
        _run(monkeypatch, COMPUTE_STOP, [])
        assert platform.calls == []
        assert platform.outcomes() == [(CR_ID, "compute-requirements", "skipped")]

    def test_a_failure_carries_on(self, platform, monkeypatch):
        platform.crs[CR_ID_2] = _cr(CR_ID_2, "cr-b")
        platform.failures["stop_compute_requirement_by_id"] = _http_error(500)
        _run(monkeypatch, COMPUTE_STOP, [])
        assert [r["outcome"] for r in platform.records] == ["failed", "failed"]

    @pytest.mark.parametrize(
        "error", [_http_error(401), RequestsConnectionError("reset")]
    )
    def test_a_session_failure_stops(self, platform, monkeypatch, error):
        platform.crs[CR_ID_2] = _cr(CR_ID_2, "cr-b")
        platform.failures["stop_compute_requirement_by_id"] = error
        with pytest.raises(ReportedFailure) as raised:
            _run(monkeypatch, COMPUTE_STOP, [])
        assert classify(raised.value) in SESSION_FAILURES
        assert [r["outcome"] for r in platform.records] == ["failed", "skipped"]
        assert platform.records[1]["error"].startswith("not attempted:")

    def test_follow_is_given_only_what_was_actioned(self, platform, monkeypatch):
        _run(monkeypatch, COMPUTE_STOP, [], follow=True)
        cac_module.follow_ids.assert_called_once_with([CR_ID])


# ---------------------------------------------------------------------------
# Explicit Compute Requirements
# ---------------------------------------------------------------------------


class TestComputeRequirements:
    def test_by_id_records_its_name(self, platform, monkeypatch):
        _run(monkeypatch, COMPUTE_STOP, [CR_ID])
        assert platform.calls == [("stop_compute_requirement_by_id", CR_ID)]
        assert platform.records[0]["name"] == "cr-a"

    def test_by_name(self, platform, monkeypatch):
        _run(monkeypatch, COMPUTE_STOP, ["cr-a"])
        assert platform.calls == [("stop_compute_requirement_by_id", CR_ID)]
        assert platform.records[0]["name"] == "cr-a"

    def test_by_namespaced_name(self, platform, monkeypatch):
        platform.crs[CR_ID_2] = _cr(CR_ID_2, "cr-a", namespace="other")
        _run(monkeypatch, COMPUTE_STOP, ["other/cr-a"])
        assert platform.calls == [("stop_compute_requirement_by_id", CR_ID_2)]

    def test_a_name_prefers_the_live_cr_over_a_terminated_one(
        self, platform, monkeypatch
    ):
        platform.crs = {
            CR_ID_OLD: _cr(CR_ID_OLD, "cr-a", TERMINATED),
            CR_ID: _cr(CR_ID, "cr-a"),
        }
        _run(monkeypatch, COMPUTE_STOP, ["cr-a"])
        assert platform.calls == [("stop_compute_requirement_by_id", CR_ID)]

    def test_a_name_matched_by_two_live_crs_fails(self, platform, monkeypatch):
        platform.crs[CR_ID_2] = _cr(CR_ID_2, "cr-a")
        _run(monkeypatch, COMPUTE_STOP, ["cr-a"])
        assert platform.calls == []
        assert platform.outcomes() == [(None, "compute-requirements", "failed")]

    def test_a_partial_name_is_not_a_match(self, platform, monkeypatch):
        _run(monkeypatch, COMPUTE_STOP, ["cr"])
        assert platform.calls == []
        assert platform.records[0]["outcome"] == "failed"

    @pytest.mark.parametrize("target", [CR_ID, "cr-a"])
    def test_the_wrong_state_is_skipped_by_id_or_name(
        self, platform, monkeypatch, target
    ):
        _run(monkeypatch, COMPUTE_START, [target])
        assert platform.calls == []
        assert platform.records[0]["outcome"] == "skipped"
        assert "RUNNING" in platform.records[0]["error"]

    def test_not_found(self, platform, monkeypatch):
        _run(monkeypatch, COMPUTE_STOP, [CR_ID_2])
        assert platform.outcomes() == [(CR_ID_2, "compute-requirements", "failed")]

    def test_a_cr_name_containing_a_dot_is_a_name(self, platform, monkeypatch):
        platform.crs[CR_ID] = _cr(CR_ID, "my.cr")
        _run(monkeypatch, COMPUTE_STOP, ["my.cr"])
        assert platform.calls == [("stop_compute_requirement_by_id", CR_ID)]

    @pytest.mark.parametrize("target", [CR_ID, "cr-a"])
    def test_restart_refuses_compute_requirements(self, platform, monkeypatch, target):
        _run(monkeypatch, COMPUTE_RESTART, [target])
        assert platform.calls == []
        assert platform.records[0]["outcome"] == "failed"


# ---------------------------------------------------------------------------
# Instances and Nodes
# ---------------------------------------------------------------------------


class TestInstances:
    @pytest.mark.parametrize(
        "action, method",
        [
            (COMPUTE_STOP, "stop_instances"),
            (COMPUTE_RESTART, "restart_instances"),
        ],
    )
    def test_an_instance(self, platform, monkeypatch, action, method):
        _run(monkeypatch, action, [f"{CR_ID}.{INSTANCE_ID}"])
        assert platform.calls == [(method, CR_ID, [INSTANCE_ID])]
        assert platform.outcomes() == [
            (f"{CR_ID}.{INSTANCE_ID}", "instances", action.past_tense.lower())
        ]

    def test_an_oci_instance_id_with_dots(self, platform, monkeypatch):
        platform.instances[(CR_ID, OCI_INSTANCE_ID)] = _instance(OCI_INSTANCE_ID)
        _run(monkeypatch, COMPUTE_STOP, [f"{CR_ID}.{OCI_INSTANCE_ID}"])
        assert platform.calls == [("stop_instances", CR_ID, [OCI_INSTANCE_ID])]

    def test_instances_in_one_cr_are_one_call_and_one_confirmation(
        self, platform, monkeypatch
    ):
        prompts = []
        monkeypatch.setattr(
            cac_module, "confirmed", lambda message: prompts.append(message) or True
        )
        platform.instances[(CR_ID, INSTANCE_ID_2)] = _instance(INSTANCE_ID_2)
        _run(
            monkeypatch,
            COMPUTE_STOP,
            [f"{CR_ID}.{INSTANCE_ID}", f"{CR_ID}.{INSTANCE_ID_2}"],
        )
        assert platform.calls == [
            ("stop_instances", CR_ID, [INSTANCE_ID, INSTANCE_ID_2])
        ]
        assert len(prompts) == 1
        assert "2 Instance(s)" in prompts[0]

    def test_crs_and_instances_share_one_confirmation(self, platform, monkeypatch):
        prompts = []
        monkeypatch.setattr(
            cac_module, "confirmed", lambda message: prompts.append(message) or True
        )
        platform.crs[CR_ID_2] = _cr(CR_ID_2, "cr-b")
        _run(monkeypatch, COMPUTE_STOP, [f"{CR_ID}.{INSTANCE_ID}", CR_ID_2])
        assert prompts == [
            "Stop 1 Compute Requirement(s) ('cr-b') and"
            f" 1 Instance(s) ({CR_ID}.{INSTANCE_ID})?"
        ]

    def test_targets_are_handled_in_the_order_given_without_duplicates(
        self, platform, monkeypatch
    ):
        platform.crs[CR_ID_2] = _cr(CR_ID_2, "cr-b", STOPPED)
        targets = ["nope", CR_ID_2, "nope", f"{CR_ID}.missing"]
        _run(monkeypatch, COMPUTE_STOP, targets)
        assert [(r["name"], r["outcome"]) for r in platform.records] == [
            ("nope", "failed"),
            ("cr-b", "skipped"),
            ("missing", "failed"),
        ]

    def test_the_wrong_state_is_skipped(self, platform, monkeypatch):
        _run(monkeypatch, COMPUTE_START, [f"{CR_ID}.{INSTANCE_ID}"])
        assert platform.calls == []
        assert platform.records[0]["outcome"] == "skipped"

    def test_an_unknown_instance_fails(self, platform, monkeypatch):
        _run(monkeypatch, COMPUTE_STOP, [f"{CR_ID}.i-unknown"])
        assert platform.outcomes() == [(f"{CR_ID}.i-unknown", "instances", "failed")]

    def test_an_unknown_cr_fails_as_not_found(self, platform, monkeypatch):
        _run(monkeypatch, COMPUTE_STOP, [f"{CR_ID_2}.{INSTANCE_ID}"])
        assert "Cannot find Compute Requirement" in platform.records[0]["error"]

    def test_a_cr_lookup_error_is_not_called_not_found(self, platform, monkeypatch):
        platform.lookup_failure = _http_error(500)
        _run(monkeypatch, COMPUTE_STOP, [f"{CR_ID}.{INSTANCE_ID}"])
        assert "Cannot find" not in platform.records[0]["error"]
        assert "500" in platform.records[0]["error"]

    def test_a_failed_call_fails_each_instance(self, platform, monkeypatch):
        platform.instances[(CR_ID, INSTANCE_ID_2)] = _instance(INSTANCE_ID_2)
        platform.failures["stop_instances"] = Exception(
            "InvalidComputeRequirementStatusException: no"
        )
        _run(
            monkeypatch,
            COMPUTE_STOP,
            [f"{CR_ID}.{INSTANCE_ID}", f"{CR_ID}.{INSTANCE_ID_2}"],
            follow=True,
        )
        assert [r["outcome"] for r in platform.records] == ["failed", "failed"]
        cac_module.follow_ids.assert_not_called()

    def test_follow_names_each_cr_once(self, platform, monkeypatch):
        platform.instances[(CR_ID, INSTANCE_ID_2)] = _instance(INSTANCE_ID_2)
        _run(
            monkeypatch,
            COMPUTE_STOP,
            [f"{CR_ID}.{INSTANCE_ID}", f"{CR_ID}.{INSTANCE_ID_2}"],
            follow=True,
        )
        cac_module.follow_ids.assert_called_once_with([CR_ID])

    def test_declining_skips_everything(self, platform, monkeypatch):
        monkeypatch.setattr(cac_module, "confirmed", lambda message: False)
        _run(monkeypatch, COMPUTE_STOP, [f"{CR_ID}.{INSTANCE_ID}", CR_ID])
        assert platform.calls == []
        assert {r["outcome"] for r in platform.records} == {"skipped"}


class TestNodes:
    def _node(self, platform, details=True, pool=None):
        platform.nodes[NODE_ID] = SimpleNamespace(
            status=NodeStatus.RUNNING,
            workerPoolId=WP_ID,
            details=SimpleNamespace(instanceId=INSTANCE_ID) if details else None,
        )
        platform.pools[WP_ID] = pool if pool is not None else _provisioned_pool()

    def test_a_node_stands_for_its_instance(self, platform, monkeypatch):
        self._node(platform)
        _run(monkeypatch, COMPUTE_STOP, [NODE_ID])
        assert platform.calls == [("stop_instances", CR_ID, [INSTANCE_ID])]

    def test_a_node_and_its_instance_are_one_target(self, platform, monkeypatch):
        self._node(platform)
        _run(monkeypatch, COMPUTE_STOP, [NODE_ID, f"{CR_ID}.{INSTANCE_ID}"])
        assert platform.calls == [("stop_instances", CR_ID, [INSTANCE_ID])]
        assert len(platform.records) == 1

    def test_a_configured_pools_node_fails_and_says_why(
        self, platform, monkeypatch, capsys
    ):
        self._node(platform, pool=ConfiguredWorkerPool())
        errors = []
        monkeypatch.setattr(cac_module, "print_error", errors.append)
        _run(monkeypatch, COMPUTE_STOP, [NODE_ID])
        assert platform.outcomes() == [(NODE_ID, "nodes", "failed")]
        assert "Configured Worker Pool" in errors[0]

    def test_a_node_without_details_fails_and_says_why(self, platform, monkeypatch):
        self._node(platform, details=False)
        _run(monkeypatch, COMPUTE_STOP, [NODE_ID])
        assert "has not yet reported its Instance" in platform.records[0]["error"]

    def test_an_unknown_node(self, platform, monkeypatch):
        _run(monkeypatch, COMPUTE_STOP, [NODE_ID])
        assert platform.outcomes() == [(NODE_ID, "nodes", "failed")]


# ---------------------------------------------------------------------------
# A session failure stops the run
# ---------------------------------------------------------------------------


class TestSessionFailures:
    def test_while_resolving(self, platform, monkeypatch):
        platform.crs[CR_ID_2] = _cr(CR_ID_2, "cr-b")
        targets = [CR_ID, CR_ID_2]
        calls = {"n": 0}

        def get_cr(cr_id):
            calls["n"] += 1
            if calls["n"] == 2:
                raise _http_error(401)
            return platform.crs[cr_id]

        platform.client.compute_client.get_compute_requirement_by_id.side_effect = (
            get_cr
        )
        with pytest.raises(ReportedFailure) as raised:
            _run(monkeypatch, COMPUTE_STOP, [*targets, f"{CR_ID}.{INSTANCE_ID}"])
        assert classify(raised.value) in SESSION_FAILURES
        assert platform.calls == []  # nothing is acted on
        assert [(r["id"], r["outcome"]) for r in platform.records] == [
            (CR_ID_2, "failed"),
            (CR_ID, "skipped"),  # resolved, not attempted
            (f"{CR_ID}.{INSTANCE_ID}", "skipped"),  # not resolved
        ]

    def test_while_acting(self, platform, monkeypatch):
        platform.crs[CR_ID_2] = _cr(CR_ID_2, "cr-b")
        platform.failures["stop_compute_requirement_by_id"] = _http_error(401)
        with pytest.raises(ReportedFailure) as raised:
            _run(monkeypatch, COMPUTE_STOP, [CR_ID, CR_ID_2, f"{CR_ID}.{INSTANCE_ID}"])
        assert classify(raised.value) in SESSION_FAILURES
        assert [r["outcome"] for r in platform.records] == [
            "failed",
            "skipped",
            "skipped",
        ]
        assert platform.calls == []


# ---------------------------------------------------------------------------
# Termination: yd-terminate
# ---------------------------------------------------------------------------


class TestTerminate:
    @pytest.mark.parametrize(
        "status",
        [ComputeRequirementStatus.PROVISIONING, RUNNING, STOPPED],
    )
    def test_any_live_cr_can_be_terminated(self, platform, monkeypatch, status):
        platform.crs[CR_ID] = _cr(CR_ID, "cr-a", status)
        _run(monkeypatch, COMPUTE_TERMINATE, [CR_ID])
        assert platform.calls == [("terminate_compute_requirement_by_id", CR_ID)]
        assert platform.outcomes() == [(CR_ID, "compute-requirements", "terminated")]

    def test_a_terminated_cr_is_skipped(self, platform, monkeypatch):
        platform.crs[CR_ID] = _cr(CR_ID, "cr-a", TERMINATED)
        _run(monkeypatch, COMPUTE_TERMINATE, ["cr-a"])
        assert platform.calls == []
        assert platform.records[0]["outcome"] == "skipped"

    @pytest.mark.parametrize("status", [InstanceStatus.STOPPED, InstanceStatus.PENDING])
    def test_an_instance_in_any_live_state(self, platform, monkeypatch, status):
        platform.instances[(CR_ID, INSTANCE_ID)] = _instance(INSTANCE_ID, status)
        _run(monkeypatch, COMPUTE_TERMINATE, [f"{CR_ID}.{INSTANCE_ID}"])
        assert platform.calls == [("terminate_instances", CR_ID, [INSTANCE_ID])]

    def test_an_instance_already_terminating_is_skipped(self, platform, monkeypatch):
        platform.instances[(CR_ID, INSTANCE_ID)] = _instance(
            INSTANCE_ID, InstanceStatus.TERMINATING
        )
        _run(monkeypatch, COMPUTE_TERMINATE, [f"{CR_ID}.{INSTANCE_ID}"])
        assert platform.records[0]["outcome"] == "skipped"

    def test_a_terminated_node_is_skipped(self, platform, monkeypatch):
        platform.nodes[NODE_ID] = SimpleNamespace(
            status=NodeStatus.TERMINATED, workerPoolId=WP_ID, details=None
        )
        _run(monkeypatch, COMPUTE_TERMINATE, [NODE_ID])
        assert platform.outcomes() == [(NODE_ID, "nodes", "skipped")]

    def test_the_confirmation_says_immediately(self, platform, monkeypatch):
        prompts = []
        monkeypatch.setattr(
            cac_module, "confirmed", lambda message: prompts.append(message) or True
        )
        _run(monkeypatch, COMPUTE_TERMINATE, [CR_ID])
        platform.crs[CR_ID] = _cr(CR_ID, "cr-a")  # the fake left it as it was
        _run(monkeypatch, COMPUTE_TERMINATE, [])
        assert len(prompts) == 2
        assert all(p.startswith("Immediately terminate ") for p in prompts)

    def test_a_dry_run_reports_and_does_nothing(self, platform, monkeypatch):
        platform.crs[CR_ID_2] = _cr(CR_ID_2, "other")
        report = MagicMock()
        monkeypatch.setattr(cac_module, "report_dry_run", report)
        _run(monkeypatch, COMPUTE_TERMINATE, ["cr-*"], dry_run=True)
        assert platform.calls == []
        assert [s.id for s in report.call_args.args[1]] == [CR_ID]
        assert report.call_args.args[3:6] == (
            "terminated",
            "compute-requirements",
            "terminate",
        )

    def test_the_command_is_the_action(self, monkeypatch):
        import yellowdog_cli.terminate as yd_terminate

        apply = MagicMock()
        monkeypatch.setattr(yd_terminate, "apply_compute_action", apply)
        monkeypatch.setattr(
            "yellowdog_cli.utils.wrapper.ARGS_PARSER",
            MagicMock(debug=True, print_pid=True),
        )
        with pytest.raises(SystemExit):
            yd_terminate.main()
        apply.assert_called_once_with(COMPUTE_TERMINATE)


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


class TestCommandLine:
    def test_restart_requires_a_target(self, capsys):
        parser = build_parser(COMMANDS["yd-compute-restart"], prog="yd-compute-restart")
        with pytest.raises(SystemExit) as raised:
            parser.parse_args([])
        assert raised.value.code == 2

    def test_restart_takes_no_listing_options(self):
        command = COMMANDS["yd-compute-restart"]
        flags = {
            flag
            for option in command.all_options()
            for member in getattr(option, "options", (option,))
            for flag in member.flags
        }
        assert not {"--sort", "--interactive", "--namespace", "--tag"} & flags

    @pytest.mark.parametrize("command", ["yd-compute-stop", "yd-compute-start"])
    def test_globs_and_explicit_names_do_not_mix(self, command):
        from yellowdog_cli.utils.command_registry import check_glob_and_literal_names

        assert check_glob_and_literal_names in COMMANDS[command].validators
