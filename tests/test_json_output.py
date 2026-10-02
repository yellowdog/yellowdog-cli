"""
The action commands' '--json' result: an array of
{"id", "name", "type", "action", "outcome"}, one per entity acted on (or
skipped, or failed), printed once by the wrapper.

Each test drives the command's real main() through main_wrapper, with the
client mocked, and parses stdout: a well-formed document on stdout alone is
the contract, so nothing here asserts what was handed to a printer.
"""

import warnings
from json import loads as json_loads
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from requests import HTTPError, Response
from yellowdog_client.model import (
    ComputeRequirementStatus,
    ComputeRequirementSummary,
    InstanceStatus,
    TaskStatus,
    WorkerPoolStatus,
    WorkerPoolSummary,
    WorkRequirementStatus,
    WorkRequirementSummary,
)

import yellowdog_cli.abort as yd_abort
import yellowdog_cli.boost as yd_boost
import yellowdog_cli.cancel as yd_cancel
import yellowdog_cli.compute_restart as yd_compute_restart
import yellowdog_cli.compute_stop as yd_compute_stop
import yellowdog_cli.finish as yd_finish
import yellowdog_cli.hold as yd_hold
import yellowdog_cli.resize as yd_resize
import yellowdog_cli.shutdown as yd_shutdown
import yellowdog_cli.start as yd_start
import yellowdog_cli.terminate as yd_terminate
import yellowdog_cli.utils.compute_action_common as cac_module
import yellowdog_cli.utils.interactive as interactive_module
import yellowdog_cli.utils.printing as printing_module
import yellowdog_cli.utils.results as results_module
import yellowdog_cli.utils.start_hold_common as shc_module
import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli.utils.entity_utils import get_worker_pool_id_by_name
from yellowdog_cli.utils.results import record_action, reset_results
from yellowdog_cli.utils.settings import RN_REQUIREMENT_TEMPLATE, RN_SOURCE_TEMPLATE

WR_ID_1 = "ydid:workreq:000000:11111111-1111-1111-1111-111111111111"
WR_ID_2 = "ydid:workreq:000000:22222222-2222-2222-2222-222222222222"
WP_ID = "ydid:wrkrpool:000000:33333333-3333-3333-3333-333333333333"
NODE_ID = "ydid:node:000000:44444444-4444-4444-4444-444444444444"
CR_ID = "ydid:compreq:000000:55555555-5555-5555-5555-555555555555"
TASK_ID = "ydid:task:000000:66666666-6666-6666-6666-666666666666"
ALLOWANCE_ID = "ydid:allow:000000:77777777-7777-7777-7777-777777777777"
ALLOWANCE_ID_2 = "ydid:allow:000000:88888888-8888-8888-8888-888888888888"
ALLOWANCE_ID_3 = "ydid:allow:000000:99999999-9999-9999-9999-999999999999"
INSTANCE_ID = "i-0123456789abcdef0"

_DEFAULTS = {
    "json_output": True,
    "dry_run": False,
    "quiet": False,
    "interactive": False,
    "auto_select_all": False,
    "follow": False,
    "abort": False,
    "terminate": False,
    "yes": True,
    "no_format": True,
    "count_only": False,
    "print_pid": False,
    "output_file": None,
    "strip_ids": False,
    "debug": False,
    "details": False,
    "reverse": None,
    "sort": None,
    "validate": False,
}


@pytest.fixture()
def run(monkeypatch, capsys):
    """
    Return run(module, main_module=None, confirm=True, also=(), **args):
    patch every module's ARGS_PARSER (and that of each module in 'also'),
    CLIENT and CONFIG_COMMON, run main_module.main()
    (default: module) through the wrapper, and return (parsed stdout,
    stderr, client). The exit code is left in run.exit_code.
    """
    reset_results()

    def _run(module, main_module=None, confirm=True, client=None, also=(), **values):
        args = MagicMock(**{**_DEFAULTS, **values})
        client = client or MagicMock()
        config = MagicMock(namespace="ns", name_tag="tag", url="https://u")
        for target in (
            module,
            results_module,
            printing_module,
            interactive_module,
            wrapper_module,
            *also,
        ):
            monkeypatch.setattr(target, "ARGS_PARSER", args)
        monkeypatch.setattr(module, "CLIENT", client)
        monkeypatch.setattr(wrapper_module, "CLIENT", MagicMock())
        if hasattr(module, "CONFIG_COMMON"):
            monkeypatch.setattr(module, "CONFIG_COMMON", config)
        if hasattr(module, "confirmed"):
            monkeypatch.setattr(module, "confirmed", lambda msg: confirm)
        with pytest.raises(SystemExit) as exit_info:
            (main_module or module).main()
        _run.exit_code = exit_info.value.code  # type: ignore[attr-defined]
        out, err = capsys.readouterr()
        return json_loads(out), err, client

    yield _run
    reset_results()


def _wr(id_: str, name: str, status=WorkRequirementStatus.RUNNING):
    return WorkRequirementSummary(id=id_, name=name, namespace="ns", status=status)


def _action(id_, name, type_, action, outcome, **extra) -> dict:
    return {
        "id": id_,
        "name": name,
        "type": type_,
        "action": action,
        "outcome": outcome,
        **extra,
    }


# ---------------------------------------------------------------------------
# record_action() itself
# ---------------------------------------------------------------------------


class TestRecordAction:
    def test_an_entity_with_an_error(self, monkeypatch, capsys):
        args = MagicMock(**_DEFAULTS)
        monkeypatch.setattr(results_module, "ARGS_PARSER", args)
        monkeypatch.setattr(printing_module, "ARGS_PARSER", args)
        reset_results()
        record_action(
            SimpleNamespace(id="i", name="n"), "tasks", "abort", "failed", "boom"
        )
        record_action(ALLOWANCE_ID, "allowances", "boost", "boosted", hours=3)
        record_action("a-name", "work-requirements", "cancel", "failed", "not found")
        results_module.flush_results()
        assert json_loads(capsys.readouterr().out) == [
            _action("i", "n", "tasks", "abort", "failed", error="boom"),
            _action(ALLOWANCE_ID, None, "allowances", "boost", "boosted", hours=3),
            _action(
                None,
                "a-name",
                "work-requirements",
                "cancel",
                "failed",
                error="not found",
            ),
        ]
        reset_results()


# ---------------------------------------------------------------------------
# yd-cancel
# ---------------------------------------------------------------------------


class TestCancel:
    def _fetch(self, monkeypatch, summaries):
        monkeypatch.setattr(
            yd_cancel,
            "get_filtered_work_requirement_summaries",
            lambda *a, **k: list(summaries),
        )

    def test_cancelled(self, run, monkeypatch):
        self._fetch(monkeypatch, [_wr(WR_ID_1, "wr-a"), _wr(WR_ID_2, "wr-b")])
        out, _, _ = run(yd_cancel, work_requirement_names=[])
        assert out == [
            _action(WR_ID_1, "wr-a", "work-requirements", "cancel", "cancelled"),
            _action(WR_ID_2, "wr-b", "work-requirements", "cancel", "cancelled"),
        ]

    def test_failed(self, run, monkeypatch):
        self._fetch(monkeypatch, [_wr(WR_ID_1, "wr-a")])
        client = MagicMock()
        client.work_client.cancel_work_requirement_by_id.side_effect = RuntimeError(
            "nope"
        )
        out, _, _ = run(yd_cancel, client=client, work_requirement_names=[])
        assert out == [
            _action(
                WR_ID_1, "wr-a", "work-requirements", "cancel", "failed", error="nope"
            )
        ]

    def test_declined_is_skipped(self, run, monkeypatch):
        self._fetch(monkeypatch, [_wr(WR_ID_1, "wr-a")])
        out, _, client = run(yd_cancel, confirm=False, work_requirement_names=[])
        assert out == [
            _action(WR_ID_1, "wr-a", "work-requirements", "cancel", "skipped")
        ]
        client.work_client.cancel_work_requirement_by_id.assert_not_called()

    def test_nothing_to_cancel_is_an_empty_array(self, run, monkeypatch):
        self._fetch(monkeypatch, [])
        out, _, _ = run(yd_cancel, work_requirement_names=[])
        assert out == []

    def test_dry_run_matches_the_real_path_with_would(self, run, monkeypatch):
        summaries = [_wr(WR_ID_1, "wr-a"), _wr(WR_ID_2, "wr-b")]
        self._fetch(monkeypatch, summaries)
        real, _, _ = run(yd_cancel, work_requirement_names=[])
        reset_results()
        dry, _, client = run(yd_cancel, dry_run=True, work_requirement_names=[])
        client.work_client.cancel_work_requirement_by_id.assert_not_called()
        assert [r["outcome"] for r in dry] == ["would cancel", "would cancel"]
        # The dry run adds the status Commander's confirmation shows
        assert [r.pop("status") for r in dry] == ["RUNNING", "RUNNING"]
        assert [{**r, "outcome": None} for r in dry] == [
            {**r, "outcome": None} for r in real
        ]

    def test_by_name(self, run, monkeypatch):
        monkeypatch.setattr(
            yd_cancel,
            "get_work_requirement_summary_by_name_or_id",
            lambda client, name, namespace: (
                _wr(WR_ID_1, "wr-a") if name == "wr-a" else None
            ),
        )
        out, _, _ = run(yd_cancel, work_requirement_names=["wr-a", "missing"])
        assert out[0] == _action(
            WR_ID_1, "wr-a", "work-requirements", "cancel", "cancelled"
        )
        assert out[1]["name"] == "missing" and out[1]["outcome"] == "failed"
        assert "not found" in out[1]["error"]

    def test_by_name_in_the_wrong_state_is_skipped(self, run, monkeypatch):
        monkeypatch.setattr(
            yd_cancel,
            "get_work_requirement_summary_by_name_or_id",
            lambda *a, **k: _wr(WR_ID_1, "wr-a", WorkRequirementStatus.COMPLETED),
        )
        out, err, _ = run(yd_cancel, work_requirement_names=["wr-a"])
        assert out == [
            _action(WR_ID_1, "wr-a", "work-requirements", "cancel", "skipped")
        ]
        assert "not in a valid state" in err  # the warning, on stderr

    def test_a_task(self, run):
        out, _, _ = run(yd_cancel, work_requirement_names=[TASK_ID])
        assert out == [_action(TASK_ID, None, "tasks", "cancel", "cancelled")]


# ---------------------------------------------------------------------------
# yd-shutdown
# ---------------------------------------------------------------------------


def _wp(id_: str, name: str) -> WorkerPoolSummary:
    return WorkerPoolSummary(
        id=id_, name=name, namespace="ns", status=WorkerPoolStatus.RUNNING
    )


class TestShutdown:
    def test_shut_down(self, run, monkeypatch):
        monkeypatch.setattr(
            yd_shutdown,
            "get_worker_pool_summaries",
            lambda *a, **k: [_wp(WP_ID, "wp-tag")],
        )
        out, _, _ = run(yd_shutdown, worker_pool_nodes_list=[])
        assert out == [
            _action(WP_ID, "wp-tag", "worker-pools", "shutdown", "shut down")
        ]

    def test_dry_run(self, run, monkeypatch):
        monkeypatch.setattr(
            yd_shutdown,
            "get_worker_pool_summaries",
            lambda *a, **k: [_wp(WP_ID, "wp-tag")],
        )
        out, _, _ = run(yd_shutdown, dry_run=True, worker_pool_nodes_list=[])
        assert out == [
            _action(
                WP_ID,
                "wp-tag",
                "worker-pools",
                "shutdown",
                "would shutdown",
                status="RUNNING",
            )
        ]

    def test_by_id_with_a_node_and_the_compute_requirement(self, run):
        client = MagicMock()
        client.worker_pool_client.get_worker_pool_by_id.return_value = SimpleNamespace(
            computeRequirementId=CR_ID
        )
        client.worker_pool_client.shutdown_node_by_id.side_effect = RuntimeError("gone")
        out, _, _ = run(
            yd_shutdown,
            client=client,
            terminate=True,
            worker_pool_nodes_list=[WP_ID, NODE_ID],
        )
        assert out == [
            _action(WP_ID, None, "worker-pools", "shutdown", "shut down"),
            _action(CR_ID, None, "compute-requirements", "terminate", "terminated"),
            _action(NODE_ID, None, "nodes", "shutdown", "failed", error="gone"),
        ]

    def test_a_failed_refetch_records_the_terminate_as_failed(self, run):
        # '-T' refetches the Worker Pool for its Compute Requirement; when
        # that fails the termination is recorded as failed, keyed by the
        # Worker Pool's ID (all that is known), and the command exits 1
        client = MagicMock()
        client.worker_pool_client.get_worker_pool_by_id.side_effect = RuntimeError(
            "refetch failed"
        )
        out, _, _ = run(
            yd_shutdown, client=client, terminate=True, worker_pool_nodes_list=[WP_ID]
        )
        assert out == [
            _action(WP_ID, None, "worker-pools", "shutdown", "shut down"),
            _action(
                WP_ID,
                None,
                "compute-requirements",
                "terminate",
                "failed",
                error="refetch failed",
            ),
        ]
        assert run.exit_code == 1


# ---------------------------------------------------------------------------
# yd-terminate
# ---------------------------------------------------------------------------


def _cr(id_: str, name: str, status=ComputeRequirementStatus.RUNNING):
    return ComputeRequirementSummary(id=id_, name=name, status=status)


class TestTerminate:
    def test_terminated(self, run, monkeypatch):
        monkeypatch.setattr(
            yd_terminate,
            "get_compute_requirement_summaries",
            lambda *a, **k: [_cr(CR_ID, "cr-a")],
        )
        out, _, _ = run(yd_terminate, compute_requirements_instances_or_nodes=[])
        assert out == [
            _action(CR_ID, "cr-a", "compute-requirements", "terminate", "terminated")
        ]

    def test_dry_run(self, run, monkeypatch):
        monkeypatch.setattr(
            yd_terminate,
            "get_compute_requirement_summaries",
            lambda *a, **k: [_cr(CR_ID, "cr-a")],
        )
        out, _, _ = run(
            yd_terminate, dry_run=True, compute_requirements_instances_or_nodes=[]
        )
        assert out == [
            _action(
                CR_ID,
                "cr-a",
                "compute-requirements",
                "terminate",
                "would terminate",
                status="RUNNING",
            )
        ]

    def test_an_instance(self, run, monkeypatch):
        instance = MagicMock(status=InstanceStatus.RUNNING)
        monkeypatch.setattr(
            yd_terminate, "get_instance_by_id", lambda *a, **k: instance
        )
        out, _, _ = run(
            yd_terminate,
            compute_requirements_instances_or_nodes=[f"{CR_ID}.{INSTANCE_ID}"],
        )
        assert out == [
            _action(
                f"{CR_ID}.{INSTANCE_ID}",
                INSTANCE_ID,
                "instances",
                "terminate",
                "terminated",
            )
        ]


# ---------------------------------------------------------------------------
# yd-finish
# ---------------------------------------------------------------------------


class TestFinish:
    def test_finished_and_already_finishing(self, run, monkeypatch):
        monkeypatch.setattr(
            yd_finish,
            "get_filtered_work_requirement_summaries",
            lambda *a, **k: [
                _wr(WR_ID_1, "wr-a"),
                _wr(WR_ID_2, "wr-b", WorkRequirementStatus.FINISHING),
            ],
        )
        out, _, _ = run(yd_finish, work_requirement_names=[])
        assert out == [
            _action(WR_ID_1, "wr-a", "work-requirements", "finish", "finished"),
            _action(WR_ID_2, "wr-b", "work-requirements", "finish", "skipped"),
        ]

    def test_by_name_failed(self, run, monkeypatch):
        monkeypatch.setattr(
            yd_finish,
            "get_work_requirement_summary_by_name_or_id",
            lambda *a, **k: _wr(WR_ID_1, "wr-a"),
        )
        client = MagicMock()
        client.work_client.finish_work_requirement_by_id.side_effect = RuntimeError(
            "no"
        )
        out, _, _ = run(yd_finish, client=client, work_requirement_names=["wr-a"])
        assert out == [
            _action(
                WR_ID_1, "wr-a", "work-requirements", "finish", "failed", error="no"
            )
        ]


# ---------------------------------------------------------------------------
# yd-abort
# ---------------------------------------------------------------------------


TASK_ID_2 = TASK_ID.replace("6666-6666", "6666-7777")
TG_ID = "ydid:taskgrp:000000:11111111-1111-1111-1111-111111111111:1"


def _task(id_=TASK_ID, name="t1", status=TaskStatus.EXECUTING, tg="tg-id"):
    return SimpleNamespace(id=id_, name=name, status=status, taskGroupId=tg)


def _tg(id_="tg-id", name="tg-1"):
    return SimpleNamespace(id=id_, name=name)


class TestAbort:
    @pytest.fixture()
    def wrs(self, monkeypatch):
        """
        Work Requirements by (namespace, name): 'wr-a' (ID WR_ID_1) and
        'wr-b' (ID WR_ID_2) in 'ns', each with Task Group 'tg-1'.
        """
        known = {
            ("ns", "wr-a"): _wr(WR_ID_1, "wr-a"),
            ("ns", "wr-b"): _wr(WR_ID_2, "wr-b"),
        }
        lookups = []

        def lookup(client, name, namespace=None):
            lookups.append((namespace, name))
            return known.get((namespace, name))

        monkeypatch.setattr(
            yd_abort, "get_work_requirement_summary_by_name_or_id", lookup
        )
        monkeypatch.setattr(
            yd_abort, "get_task_groups_from_wr_by_id", lambda client, wr_id: [_tg()]
        )
        return lookups

    def _client(self, tasks=(), by_id=None):
        client = MagicMock()
        client.work_client.get_tasks.return_value.list_all.return_value = list(tasks)
        if by_id is not None:
            client.work_client.get_task_by_id.side_effect = lambda i: by_id[i]
        return client

    def test_task_ids(self, run):
        client = self._client(
            by_id={TASK_ID: _task(), TASK_ID_2: _task(TASK_ID_2, "t2")}
        )
        client.work_client.cancel_task.side_effect = [None, RuntimeError("x")]
        out, _, _ = run(yd_abort, client=client, task_id_list=[TASK_ID, TASK_ID_2])
        assert out == [
            _action(TASK_ID, "t1", "tasks", "abort", "aborted"),
            _action(TASK_ID_2, "t2", "tasks", "abort", "failed", error="x"),
        ]

    def test_a_task_not_executing_is_skipped_not_cancelled(self, run):
        client = self._client(by_id={TASK_ID: _task(status=TaskStatus.PENDING)})
        out, _, _ = run(yd_abort, client=client, task_id_list=[TASK_ID])
        assert out == [
            _action(
                TASK_ID,
                "t1",
                "tasks",
                "abort",
                "skipped",
                error="not executing (PENDING)",
            )
        ]
        client.work_client.cancel_task.assert_not_called()

    def test_a_task_not_found(self, run):
        client = self._client()
        client.work_client.get_task_by_id.side_effect = _http_error(404)
        out, _, _ = run(yd_abort, client=client, task_id_list=[TASK_ID])
        assert out == [
            _action(TASK_ID, None, "tasks", "abort", "failed", error="not found")
        ]
        assert run.exit_code == 1

    def test_declined_is_skipped(self, run, monkeypatch):
        monkeypatch.setattr(yd_abort, "select", lambda client, objects, **k: objects)
        client = self._client(by_id={TASK_ID: _task()})
        out, _, _ = run(
            yd_abort, client=client, confirm=False, yes=False, task_id_list=[TASK_ID]
        )
        assert out == [_action(TASK_ID, "t1", "tasks", "abort", "skipped")]
        client.work_client.cancel_task.assert_not_called()

    def test_tasks_not_selected_are_skipped(self, run, monkeypatch, wrs):
        monkeypatch.setattr(
            yd_abort, "select", lambda client, objects, **k: objects[:1]
        )
        client = self._client([_task(), _task(TASK_ID_2, "t2")])
        out, _, _ = run(yd_abort, client=client, yes=False, task_id_list=["wr-a"])
        assert out == [
            _action(TASK_ID_2, "t2", "tasks", "abort", "skipped", error="not selected"),
            _action(TASK_ID, "t1", "tasks", "abort", "aborted"),
        ]

    def test_tasks_in_a_work_requirement(self, run, wrs):
        client = self._client([_task()])
        out, _, _ = run(yd_abort, client=client, task_id_list=["wr-a"])
        assert out == [_action(TASK_ID, "t1", "tasks", "abort", "aborted")]

    def test_namespace_work_requirement_and_task_group(self, run, wrs):
        """'ns/wr/tg' used to raise ValueError from the namespace split."""
        client = self._client([_task()])
        out, _, _ = run(yd_abort, client=client, task_id_list=["ns/wr-a/tg-1"])
        assert out == [_action(TASK_ID, "t1", "tasks", "abort", "aborted")]
        assert wrs == [("ns", "wr-a")]
        search = client.work_client.get_tasks.call_args.args[0]
        assert search.taskGroupId == "tg-id"

    def test_work_requirement_and_task_group_is_tried_first(self, run, wrs):
        client = self._client([_task()])
        out, _, _ = run(yd_abort, client=client, task_id_list=["wr-a/tg-1"])
        assert out == [_action(TASK_ID, "t1", "tasks", "abort", "aborted")]
        assert wrs == [("ns", "wr-a")]

    def test_namespace_and_work_requirement(self, run, wrs):
        client = self._client([_task()])
        out, _, _ = run(yd_abort, client=client, task_id_list=["ns/wr-b"])
        assert out == [_action(TASK_ID, "t1", "tasks", "abort", "aborted")]
        assert wrs == [("ns", "ns"), ("ns", "wr-b")]
        search = client.work_client.get_tasks.call_args.args[0]
        assert search.workRequirementId == WR_ID_2

    def test_task_group_not_found_by_name(self, run, wrs):
        out, _, _ = run(yd_abort, client=self._client(), task_id_list=["wr-a/nope"])
        assert out == [
            _action(
                None, "wr-a/nope", "task-groups", "abort", "failed", error="not found"
            )
        ]

    def test_nothing_executing_keeps_stdout_a_document(self, run, wrs):
        """The message printed despite --quiet used to land on stdout too."""
        out, _, _ = run(
            yd_abort, client=self._client(), quiet=True, task_id_list=["wr-a"]
        )
        assert out == [
            _action(
                WR_ID_1,
                "wr-a",
                "work-requirements",
                "abort",
                "skipped",
                error="no executing Tasks",
            )
        ]

    def test_task_group_lookup_failing_after_abort_is_still_aborted(
        self, run, wrs, monkeypatch
    ):
        def fails(client, wr_id):
            raise RuntimeError("lookup failed")

        monkeypatch.setattr(yd_abort, "get_task_groups_from_wr_by_id", fails)
        out, _, _ = run(yd_abort, client=self._client([_task()]), task_id_list=["wr-a"])
        assert out == [_action(TASK_ID, "t1", "tasks", "abort", "aborted")]

    def test_a_failing_lookup_does_not_stop_later_targets(self, run, wrs):
        client = self._client()
        client.work_client.get_tasks.side_effect = [
            RuntimeError("boom"),
            MagicMock(list_all=MagicMock(return_value=[_task()])),
        ]
        out, _, _ = run(yd_abort, client=client, task_id_list=["wr-a", "wr-b"])
        assert out == [
            _action(None, "wr-a", "work-requirements", "abort", "failed", error="boom"),
            _action(TASK_ID, "t1", "tasks", "abort", "aborted"),
        ]
        assert run.exit_code == 1

    def test_a_session_failure_attempts_nothing_further(self, run, wrs):
        client = self._client([_task(), _task(TASK_ID_2, "t2")])
        client.work_client.cancel_task.side_effect = _http_error(401)
        out, err, _ = run(yd_abort, client=client, task_id_list=["wr-a", "wr-b"])
        assert out == [
            _action(TASK_ID, "t1", "tasks", "abort", "failed", error="401 error"),
            _action(
                TASK_ID_2,
                "t2",
                "tasks",
                "abort",
                "skipped",
                error="not attempted: 401 error",
            ),
            _action(
                None,
                "wr-b",
                "work-requirements",
                "abort",
                "skipped",
                error="not attempted: 401 error",
            ),
        ]
        assert client.work_client.cancel_task.call_count == 1
        assert "Not attempting the remaining 2 item(s)" in err
        assert run.exit_code == 1

    def test_duplicates_and_overlaps_are_aborted_once(self, run, wrs):
        client = self._client([_task()], by_id={TASK_ID: _task()})
        out, err, _ = run(
            yd_abort, client=client, task_id_list=[TASK_ID, "wr-a", "wr-a"]
        )
        assert out == [_action(TASK_ID, "t1", "tasks", "abort", "aborted")]
        assert client.work_client.cancel_task.call_count == 1
        assert "Ignoring 1 duplicate target(s)" in err

    def test_targets_are_handled_in_the_order_given(self, run, wrs):
        client = self._client([_task()], by_id={TASK_ID_2: _task(TASK_ID_2, "t2")})
        out, _, _ = run(yd_abort, client=client, task_id_list=["wr-a", TASK_ID_2])
        assert [item["id"] for item in out] == [TASK_ID, TASK_ID_2]

    def test_work_requirement_id_in_another_namespace(self, run, wrs):
        client = self._client([_task()])
        client.work_client.get_work_requirement_by_id.return_value = _wr(
            WR_ID_1, "wr-elsewhere"
        )
        out, _, _ = run(yd_abort, client=client, task_id_list=[WR_ID_1])
        assert out == [_action(TASK_ID, "t1", "tasks", "abort", "aborted")]
        assert wrs == []

    def test_task_group_id_not_found_has_no_stray_quotes(self, run, monkeypatch):
        monkeypatch.setattr(
            yd_abort, "get_task_groups_from_wr_by_id", lambda client, wr_id: []
        )
        out, err, _ = run(yd_abort, client=self._client(), task_id_list=[TG_ID])
        assert out == [
            _action(TG_ID, None, "task-groups", "abort", "failed", error="not found")
        ]
        assert f"Task Group '{TG_ID}' not found" in err
        assert '"' not in err

    def test_another_kind_of_id_is_refused(self, run):
        out, _, client = run(yd_abort, task_id_list=[WP_ID])
        assert out[0]["outcome"] == "failed"
        assert "is a Worker Pool ID" in out[0]["error"]
        client.work_client.get_tasks.assert_not_called()


# ---------------------------------------------------------------------------
# yd-resize
# ---------------------------------------------------------------------------


class TestResize:
    def _args(self, **values):
        return {
            "compute_req_resize": False,
            "worker_pool_name": WP_ID,
            "worker_pool_size": 4,
            "auto_cr": False,
            **values,
        }

    def _client(self):
        client = MagicMock()
        client.worker_pool_client.get_worker_pool_by_id.return_value = SimpleNamespace(
            id=WP_ID, name="wp-a"
        )
        return client

    def test_a_worker_pool(self, run):
        out, _, _ = run(yd_resize, client=self._client(), **self._args())
        assert out == [
            _action(
                WP_ID,
                "wp-a",
                "worker-pools",
                "resize",
                "resized",
                targetInstanceCount=4,
            )
        ]

    def test_dry_run(self, run):
        out, _, client = run(
            yd_resize, client=self._client(), **self._args(dry_run=True)
        )
        client.worker_pool_client.resize_worker_pool.assert_not_called()
        assert [r["outcome"] for r in out] == ["would resize"]

    def test_a_failure_is_still_reported(self, run):
        client = self._client()
        client.worker_pool_client.resize_worker_pool.side_effect = RuntimeError(
            "too big"
        )
        out, _, _ = run(yd_resize, client=client, **self._args())
        assert out == [
            _action(
                WP_ID,
                "wp-a",
                "worker-pools",
                "resize",
                "failed",
                error="too big",
                targetInstanceCount=4,
            )
        ]

    def test_a_compute_requirement(self, run, monkeypatch):
        monkeypatch.setattr(
            yd_resize,
            "get_compute_requirement_summaries",
            lambda *a, **k: [_cr(CR_ID, "cr-a")],
        )
        out, _, _ = run(
            yd_resize, **self._args(compute_req_resize=True, worker_pool_name="cr-a")
        )
        assert out == [
            _action(
                CR_ID,
                "cr-a",
                "compute-requirements",
                "resize",
                "resized",
                targetInstanceCount=4,
            )
        ]

    def test_a_401_looking_up_the_name_reaches_the_wrapper(self, run):
        # Not a 'not found': the lookup's failure is classified by the
        # wrapper (exit 4), with nothing recorded before it
        client = MagicMock()
        client.worker_pool_client.get_worker_pool_by_name.side_effect = _http_error(401)
        out, _, _ = run(yd_resize, client=client, **self._args(worker_pool_name="wp-a"))
        assert out == []
        assert run.exit_code == 4


def _http_error(status: int) -> HTTPError:
    response = Response()
    response.status_code = status
    return HTTPError(f"{status} error", response=response)


class TestWorkerPoolIdByName:
    def test_a_404_is_not_found(self):
        client = MagicMock()
        client.worker_pool_client.get_worker_pool_by_name.side_effect = _http_error(404)
        assert get_worker_pool_id_by_name(client, "wp-a", "ns") is None

    def test_any_other_failure_is_raised(self):
        client = MagicMock()
        error = _http_error(401)
        client.worker_pool_client.get_worker_pool_by_name.side_effect = error
        with pytest.raises(HTTPError) as raised:
            get_worker_pool_id_by_name(client, "wp-a", "ns")
        assert raised.value is error


# ---------------------------------------------------------------------------
# yd-boost
# ---------------------------------------------------------------------------


class TestBoost:
    def test_boosted_and_invalid(self, run):
        out, _, _ = run(
            yd_boost, boost_hours=2, allowance_list=[ALLOWANCE_ID, "not-an-id"]
        )
        # The mock client's Allowance has no number of remaining hours
        assert out[0] == _action(
            ALLOWANCE_ID,
            None,
            "allowances",
            "boost",
            "boosted",
            hours=2,
            remainingHours=None,
        )
        assert out[1]["name"] == "not-an-id" and out[1]["outcome"] == "failed"

    def test_remaining_hours_are_recorded(self, run):
        client = MagicMock()
        client.allowances_client.boost_allowance_by_id.return_value = SimpleNamespace(
            id=ALLOWANCE_ID, remainingHours=12.5
        )
        out, _, _ = run(
            yd_boost, client=client, boost_hours=2, allowance_list=[ALLOWANCE_ID]
        )
        assert out[0]["remainingHours"] == 12.5

    def test_a_repeated_id_is_boosted_once(self, run):
        out, err, client = run(
            yd_boost, boost_hours=2, allowance_list=[ALLOWANCE_ID, ALLOWANCE_ID]
        )
        boost = client.allowances_client.boost_allowance_by_id
        assert boost.call_count == 1
        assert [item["outcome"] for item in out] == ["boosted"]
        assert "Ignoring 1 duplicate Allowance ID(s)" in err

    def test_an_authentication_failure_stops_the_rest(self, run):
        response = Response()
        response.status_code = 401
        client = MagicMock()
        boost = client.allowances_client.boost_allowance_by_id
        boost.side_effect = HTTPError("401 Unauthorized", response=response)
        out, _, _ = run(
            yd_boost,
            client=client,
            boost_hours=2,
            allowance_list=[ALLOWANCE_ID, ALLOWANCE_ID_2, ALLOWANCE_ID_3],
        )
        assert boost.call_count == 1
        assert [item["outcome"] for item in out] == ["failed", "skipped", "skipped"]
        assert out[1]["error"].startswith("not attempted:")
        # Still a per-item failure: exit 1, the cause in the record
        assert run.exit_code == 1

    def test_a_failure_of_one_allowance_does_not_stop_the_rest(self, run):
        response = Response()
        response.status_code = 404
        client = MagicMock()
        boost = client.allowances_client.boost_allowance_by_id
        boost.side_effect = [HTTPError("404", response=response), MagicMock()]
        out, _, _ = run(
            yd_boost,
            client=client,
            boost_hours=2,
            allowance_list=[ALLOWANCE_ID, ALLOWANCE_ID_2],
        )
        assert boost.call_count == 2
        assert [item["outcome"] for item in out] == ["failed", "boosted"]
        assert run.exit_code == 1

    @pytest.mark.parametrize(
        "hours, shown",
        [(1, "1 hour"), (10, "10 hours"), (2.5, "2.50 hours"), (1000, "1,000 hours")],
    )
    def test_hours_are_worded_by_number(self, hours, shown):
        assert yd_boost._hours(hours) == shown

    @pytest.mark.parametrize("hours", ["0", "-5"])
    def test_hours_below_one_are_a_usage_error(self, hours, capsys):
        from yellowdog_cli.utils.command_registry import COMMANDS, build_parser

        parser = build_parser(COMMANDS["yd-boost"], prog="yd-boost")
        with pytest.raises(SystemExit) as exit_info:
            parser.parse_args([hours, ALLOWANCE_ID])
        assert exit_info.value.code == 2
        assert "must be a positive integer" in capsys.readouterr().err

    def test_declined_is_skipped(self, run):
        out, _, _ = run(
            yd_boost, confirm=False, boost_hours=2, allowance_list=[ALLOWANCE_ID]
        )
        assert out == [
            _action(ALLOWANCE_ID, None, "allowances", "boost", "skipped", hours=2)
        ]


# ---------------------------------------------------------------------------
# yd-start / yd-hold
# ---------------------------------------------------------------------------


class TestStartHold:
    @pytest.mark.parametrize(
        "command, status, action, outcome",
        [
            (yd_start, WorkRequirementStatus.HELD, "start", "started"),
            (yd_hold, WorkRequirementStatus.RUNNING, "hold", "held"),
        ],
    )
    def test_tag_path(self, run, monkeypatch, command, status, action, outcome):
        monkeypatch.setattr(
            shc_module,
            "get_filtered_work_requirement_summaries",
            lambda *a, **k: [_wr(WR_ID_1, "wr-a", status)],
        )
        out, _, _ = run(shc_module, command, work_requirement_names=[])
        assert out == [_action(WR_ID_1, "wr-a", "work-requirements", action, outcome)]

    def test_by_name_in_the_wrong_state_is_skipped(self, run, monkeypatch):
        monkeypatch.setattr(
            shc_module,
            "get_work_requirement_summary_by_name_or_id",
            lambda *a, **k: _wr(WR_ID_1, "wr-a", WorkRequirementStatus.RUNNING),
        )
        out, _, _ = run(shc_module, yd_start, work_requirement_names=["wr-a"])
        assert out == [
            _action(WR_ID_1, "wr-a", "work-requirements", "start", "skipped")
        ]


# ---------------------------------------------------------------------------
# yd-compute-stop / -start / -restart
# ---------------------------------------------------------------------------


class TestComputeActions:
    def test_stop_tag_path(self, run, monkeypatch):
        monkeypatch.setattr(
            cac_module,
            "get_compute_requirement_summaries",
            lambda *a, **k: [_cr(CR_ID, "cr-a")],
        )
        out, _, _ = run(
            cac_module, yd_compute_stop, compute_requirements_instances_or_nodes=[]
        )
        assert out == [
            _action(CR_ID, "cr-a", "compute-requirements", "stop", "stopped")
        ]

    def test_restart_an_instance(self, run, monkeypatch):
        instance = MagicMock(status=InstanceStatus.RUNNING)
        monkeypatch.setattr(cac_module, "get_instance_by_id", lambda *a, **k: instance)
        out, _, _ = run(
            cac_module,
            yd_compute_restart,
            compute_requirements_instances_or_nodes=[f"{CR_ID}.{INSTANCE_ID}"],
        )
        assert out == [
            _action(
                f"{CR_ID}.{INSTANCE_ID}",
                INSTANCE_ID,
                "instances",
                "restart",
                "restarted",
            )
        ]

    def test_a_compute_requirement_by_id_declined(self, run, monkeypatch):
        client = MagicMock()
        client.compute_client.get_compute_requirement_by_id.return_value = (
            SimpleNamespace(
                id=CR_ID, name="cr-a", status=ComputeRequirementStatus.RUNNING
            )
        )
        out, _, _ = run(
            cac_module,
            yd_compute_stop,
            confirm=False,
            client=client,
            compute_requirements_instances_or_nodes=[CR_ID],
        )
        assert out == [
            _action(CR_ID, "cr-a", "compute-requirements", "stop", "skipped")
        ]


# ---------------------------------------------------------------------------
# An interactive selection under '--json'
# ---------------------------------------------------------------------------


class TestInteractiveSelection:
    def test_stdout_holds_only_the_document(self, run, monkeypatch):
        monkeypatch.setattr(
            yd_cancel,
            "get_filtered_work_requirement_summaries",
            lambda *a, **k: [_wr(WR_ID_1, "wr-a"), _wr(WR_ID_2, "wr-b")],
        )
        monkeypatch.setattr(interactive_module, "_get_user_input", lambda p: "2")
        out, err, _ = run(yd_cancel, interactive=True, work_requirement_names=[])
        # The document parsed, so stdout held nothing else; the numbered
        # list the selection was made from went to stderr
        assert out == [
            _action(WR_ID_2, "wr-b", "work-requirements", "cancel", "cancelled")
        ]
        assert "wr-a" in err and "wr-b" in err


# ===========================================================================
# The creators: yd-create and yd-remove record an array of
# {"resource", "name", "id", "action"}; yd-submit, yd-provision and
# yd-instantiate record one object {"id", "name", "namespace", "type"}
# ===========================================================================

KEYRING_ID = "ydid:keyring:000000:88888888-8888-8888-8888-888888888888"
GROUP_ID = "ydid:group:000000:99999999-9999-9999-9999-999999999999"

_CREATOR_DEFAULTS = {
    "show_keyring_passwords": False,
    "regenerate_app_keys": False,
    "match_allowances_by_description": False,
    "jsonnet_dry_run": False,
    "ids": False,
}


def _resource(resource, name, id_, action, **extra) -> dict:
    return {"resource": resource, "name": name, "id": id_, "action": action, **extra}


def _keyring_and_policy() -> list[dict]:
    return [
        {"resource": "Keyring", "name": "kr", "description": "d"},
        {"resource": "NamespacePolicy", "namespace": "ns1", "autoscalingMaxNodes": 5},
    ]


@pytest.fixture()
def run_create(run, monkeypatch):
    """
    run_create(resources, existing_keyring=None, client=None, **args): drive
    yd-create's main() over 'resources', with the Keyring lookup patched.
    """
    import yellowdog_cli.create as yd_create

    def _run(resources, existing_keyring=None, client=None, **values):
        monkeypatch.setattr(
            yd_create, "load_resource_specifications", lambda **k: resources
        )
        monkeypatch.setattr(
            yd_create, "get_keyring_summary_by_name", lambda *a: existing_keyring
        )
        if client is None:
            client = MagicMock()
            client.keyring_client.add_keyring.return_value = SimpleNamespace(
                keyring=SimpleNamespace(id=KEYRING_ID), keyringPassword="pw"
            )
            client.keyring_client.update_keyring.return_value = SimpleNamespace(
                id=KEYRING_ID
            )
            # No existing Namespace Policy
            client.namespaces_client.get_namespace_policy.side_effect = _http_error(404)
        return run(yd_create, client=client, **{**_CREATOR_DEFAULTS, **values})

    return _run


class TestCreate:
    def test_created(self, run_create):
        out, _, _ = run_create(_keyring_and_policy())
        assert out == [
            _resource("Keyring", "kr", KEYRING_ID, "created"),
            _resource("NamespacePolicy", "ns1", None, "created"),
        ]

    def test_updated(self, run_create):
        out, _, _ = run_create(
            _keyring_and_policy()[:1], existing_keyring=SimpleNamespace(id=KEYRING_ID)
        )
        assert out == [_resource("Keyring", "kr", KEYRING_ID, "updated")]

    def test_an_existing_policy_is_updated(self, run_create):
        client = MagicMock()  # get_namespace_policy() finds one
        out, _, _ = run_create(_keyring_and_policy()[1:], client=client)
        assert out == [_resource("NamespacePolicy", "ns1", None, "updated")]

    def test_declined_update_is_skipped(self, run, monkeypatch):
        import yellowdog_cli.create as yd_create

        resources = _keyring_and_policy()[:1]
        monkeypatch.setattr(
            yd_create, "load_resource_specifications", lambda **k: resources
        )
        monkeypatch.setattr(
            yd_create,
            "get_keyring_summary_by_name",
            lambda *a: SimpleNamespace(id=KEYRING_ID),
        )
        out, _, client = run(yd_create, confirm=False, **_CREATOR_DEFAULTS)
        assert out == [_resource("Keyring", "kr", KEYRING_ID, "skipped")]
        client.keyring_client.update_keyring.assert_not_called()

    def test_a_failure_is_recorded_and_the_run_continues(self, run_create):
        client = MagicMock()
        client.keyring_client.add_keyring.side_effect = RuntimeError("boom")
        client.namespaces_client.get_namespace_policy.side_effect = _http_error(404)
        out, _, _ = run_create(_keyring_and_policy(), client=client)
        assert out == [
            _resource("Keyring", "kr", None, "failed", error="boom"),
            _resource("NamespacePolicy", "ns1", None, "created"),
        ]

    def test_an_unknown_resource_type_fails(self, run_create):
        out, _, _ = run_create([{"resource": "Nonsense", "name": "x"}])
        assert out[0]["resource"] == "Nonsense" and out[0]["action"] == "failed"
        assert "Unknown resource type" in out[0]["error"]

    def test_keyring_password_only_when_asked_for(self, run_create):
        out, _, _ = run_create(_keyring_and_policy()[:1])
        assert "password" not in out[0]
        reset_results()
        out, _, _ = run_create(_keyring_and_policy()[:1], show_keyring_passwords=True)
        assert out == [_resource("Keyring", "kr", KEYRING_ID, "created", password="pw")]

    def test_quiet_json_is_only_the_json(self, run_create):
        # The bare IDs '--quiet' prints would break the document
        out, _, _ = run_create(_keyring_and_policy(), quiet=True)
        assert [r["action"] for r in out] == ["created", "created"]

    def test_dry_run_is_the_processed_specifications(self, run_create):
        allowance = {
            "resource": "Allowance",
            "type": "co.yellowdog.platform.model.AccountAllowance",
            "description": "al",
            "effectiveFrom": "Now",
            "resetType": "NONE",
            "limitEnforcement": "SOFT",
            "monitoredStatuses": ["RUNNING"],
            "allowedHours": 1,
        }
        out, _, client = run_create([*_keyring_and_policy(), allowance], dry_run=True)
        # One document: the array of processed specifications, each keeping
        # its 'resource' (first), so a mixed file's array is still typed --
        # the Allowance's included, which is shown from its own creator
        assert [next(iter(r)) for r in out] == ["resource"] * 3
        assert out[:2] == [
            {"resource": "Keyring", "name": "kr", "description": "d"},
            {
                "resource": "NamespacePolicy",
                "namespace": "ns1",
                "autoscalingMaxNodes": 5,
            },
        ]
        assert out[2]["resource"] == "Allowance"
        assert out[2]["description"] == "al"
        client.keyring_client.add_keyring.assert_not_called()

    def test_dry_run_records_the_template_branches(self, run_create):
        # The Compute Source Template and Compute Requirement Template
        # branches call _show_dry_run_specification() themselves, after
        # their own processing, rather than from the generic dispatch loop
        # every other resource type goes through -- so they need their own
        # coverage of the 'resource' key. Neither specification here needs
        # an image or Compute Source Template name resolved (no 'imageId',
        # and a dynamic template has no 'sources'), so nothing but
        # '_get_model_object' -- the real validation -- runs.
        source_template = {
            "resource": "ComputeSourceTemplate",
            "namespace": "ns1",
            "description": "minimal source template",
            "source": {
                "type": "co.yellowdog.platform.model.SimulatorComputeSource",
                "name": "sim-source",
            },
        }
        requirement_template = {
            "resource": "ComputeRequirementTemplate",
            "type": "co.yellowdog.platform.model.ComputeRequirementDynamicTemplate",
            "name": "dynamic-template",
            "namespace": "ns1",
            "strategyType": "co.yellowdog.platform.model.SplitProvisionStrategy",
        }
        out, _, client = run_create(
            [source_template, requirement_template], dry_run=True
        )
        assert [next(iter(r)) for r in out] == ["resource", "resource"]
        assert out[0]["resource"] == RN_SOURCE_TEMPLATE
        assert out[1]["resource"] == RN_REQUIREMENT_TEMPLATE
        client.compute_client.add_compute_source_template.assert_not_called()
        client.compute_client.add_compute_requirement_template.assert_not_called()

    def test_jsonnet_dry_run_is_an_array_of_files(self, run, monkeypatch, tmp_path):
        import yellowdog_cli.create as yd_create
        import yellowdog_cli.utils.load_resources as load_resources_module
        import yellowdog_cli.utils.variable_substitution as variables_module
        from yellowdog_cli.utils.check_imports import check_jsonnet_import

        try:
            check_jsonnet_import()
        except ImportError as exc:  # The optional 'jsonnet' extra
            pytest.skip(str(exc))
        files = []
        for index in (1, 2):
            path = tmp_path / f"r{index}.jsonnet"
            path.write_text(f'{{resource: "Keyring", name: "kr{index}"}}')
            files.append(str(path))
        out, _, _ = run(
            yd_create,
            also=(load_resources_module, variables_module),
            **{
                **_CREATOR_DEFAULTS,
                "jsonnet_dry_run": True,
                "resource_specifications": files,
            },
        )
        assert out == [
            {"resource": "Keyring", "name": "kr1"},
            {"resource": "Keyring", "name": "kr2"},
        ]


class TestRemove:
    @pytest.fixture()
    def run_remove(self, run, monkeypatch):
        import yellowdog_cli.remove as yd_remove

        def _run(resources=(), confirm=True, client=None, **values):
            monkeypatch.setattr(
                yd_remove, "load_resource_specifications", lambda **k: list(resources)
            )
            monkeypatch.setattr(
                yd_remove,
                "get_group_id_by_name",
                lambda client, name: GROUP_ID if name == "g1" else None,
            )
            return run(
                yd_remove,
                confirm=confirm,
                client=client,
                **{**_CREATOR_DEFAULTS, **values},
            )

        return _run

    def test_removed_and_not_found(self, run_remove):
        out, _, _ = run_remove(
            [
                {"resource": "Group", "name": "g1"},
                {"resource": "Group", "name": "missing"},
            ]
        )
        assert out == [
            _resource("Group", "g1", GROUP_ID, "removed"),
            _resource("Group", "missing", None, "skipped"),
        ]

    def test_declined_is_skipped(self, run_remove):
        out, _, client = run_remove(
            [{"resource": "Group", "name": "g1"}], confirm=False
        )
        assert out == [_resource("Group", "g1", GROUP_ID, "skipped")]
        client.account_client.delete_group.assert_not_called()

    def test_a_failure_is_recorded(self, run_remove):
        client = MagicMock()
        client.account_client.delete_group.side_effect = RuntimeError("in use")
        out, _, _ = run_remove([{"resource": "Group", "name": "g1"}], client=client)
        assert out[0]["action"] == "failed" and "in use" in out[0]["error"]
        assert out[0]["name"] == "g1"

    def test_by_id(self, run_remove):
        out, _, _ = run_remove(
            ids=True, resource_specifications=[GROUP_ID, "not-an-id"]
        )
        assert out[0] == _resource("Group", None, GROUP_ID, "removed")
        assert out[1]["id"] is None and out[1]["action"] == "failed"
        assert out[1]["name"] == "not-an-id"

    def test_an_allowance_by_description_without_one_is_skipped(self, run_remove):
        # Recorded by the display name remove_resources() read, as every
        # other branch is: the description, so null when there is none
        out, _, _ = run_remove(
            [{"resource": "Allowance", "type": "AccountAllowance"}],
            match_allowances_by_description=True,
        )
        assert out == [_resource("Allowance", None, None, "skipped")]

    def test_a_404_on_a_namespace_policy_is_skipped(self, run_remove):
        client = MagicMock()
        client.namespaces_client.get_namespace_policy.side_effect = _http_error(404)
        out, _, _ = run_remove(
            [{"resource": "NamespacePolicy", "namespace": "ns1"}], client=client
        )
        assert out == [_resource("NamespacePolicy", "ns1", None, "skipped")]

    def test_a_401_on_a_namespace_policy_is_a_failure(self, run, run_remove):
        # Not a 'not found': the existence check's failure is recorded as
        # 'failed' with its cause, like any other per-resource failure, and
        # the run goes on to the next resource and exits 1
        client = MagicMock()
        client.namespaces_client.get_namespace_policy.side_effect = _http_error(401)
        out, _, _ = run_remove(
            [{"resource": "NamespacePolicy", "namespace": "ns1"}], client=client
        )
        assert len(out) == 1
        assert out[0]["resource"] == "NamespacePolicy"
        assert out[0]["action"] == "failed"
        assert "401" in out[0]["error"]
        assert run.exit_code == 1


# ---------------------------------------------------------------------------
# yd-submit / yd-provision / yd-instantiate: one object
# ---------------------------------------------------------------------------


class TestSubmit:
    @pytest.fixture()
    def run_submit(self, run, monkeypatch):
        import dataclasses

        import yellowdog_cli.submit as yd_submit

        monkeypatch.setattr(
            yd_submit,
            "CONFIG_WR",
            dataclasses.replace(
                yd_submit.CONFIG_WR, wr_data_file=None, csv_files=None, wr_name=None
            ),
        )
        monkeypatch.setattr(yd_submit, "RcloneUploadedFiles", MagicMock())
        monkeypatch.setattr(
            yd_submit, "update_config_work_requirement_object", lambda c: c
        )
        monkeypatch.setattr(yd_submit, "link_entity", lambda *a: "[link]")
        monkeypatch.setattr(
            yd_submit,
            "WR_SNAPSHOT",
            printing_module.WorkRequirementSnapshot(),
            raising=False,
        )

        def _run(**values):
            client = MagicMock()

            def _add(work_requirement):
                work_requirement.id = WR_ID_1
                return work_requirement

            client.work_client.add_work_requirement.side_effect = _add
            return run(
                yd_submit,
                client=client,
                **{
                    "upgrade_rclone": False,
                    "which_rclone": False,
                    "json_raw": None,
                    "work_req_file": None,
                    "work_requirement_file_positional": None,
                    "csv_files": None,
                    "process_csv_only": False,
                    "content_path": None,
                    "add_to": None,
                    "empty": True,
                    "hold": False,
                    "progress": False,
                    **values,
                },
            )

        return _run

    def test_the_created_work_requirement(self, run_submit):
        out, _, _ = run_submit()
        assert set(out) == {"id", "name", "namespace", "type"}
        assert out["id"] == WR_ID_1
        assert out["namespace"] == "ns"
        assert out["type"] == "work-requirements"
        assert out["name"]

    def test_quiet_json_is_only_the_json(self, run_submit):
        out, _, _ = run_submit(quiet=True)
        assert out["id"] == WR_ID_1

    def test_dry_run_is_the_processed_specification(self, run_submit):
        out, _, client = run_submit(dry_run=True)
        client.work_client.add_work_requirement.assert_not_called()
        assert out["namespace"] == "ns" and out["taskGroups"] == []


class TestProvision:
    @pytest.fixture()
    def run_provision(self, run, monkeypatch):
        import dataclasses

        import yellowdog_cli.provision as yd_provision

        monkeypatch.setattr(
            yd_provision,
            "CONFIG_WP",
            dataclasses.replace(
                yd_provision.CONFIG_WP,
                worker_pool_data_file=None,
                template_id="crt-id",
                name="wp-name",
                target_instance_count=1,
            ),
        )
        monkeypatch.setattr(
            yd_provision, "warn_of_undefined_worker_pool_variables", lambda: None
        )
        monkeypatch.setattr(yd_provision, "get_template_id", lambda **k: "crt-id")
        monkeypatch.setattr(yd_provision, "get_user_data_property", lambda *a: None)
        monkeypatch.setattr(yd_provision, "link_entity", lambda *a: "[link]")

        def _run(**values):
            client = MagicMock()
            client.worker_pool_client.provision_worker_pool.return_value = (
                SimpleNamespace(id=WP_ID, name="wp-name")
            )
            return run(
                yd_provision,
                client=client,
                **{
                    "target": None,
                    "worker_pool_file": None,
                    "worker_pool_file_positional": None,
                    "content_path": None,
                    **values,
                },
            )

        return _run

    def test_the_provisioned_worker_pool(self, run_provision):
        out, _, _ = run_provision()
        assert out == {
            "id": WP_ID,
            "name": "wp-name",
            "namespace": "ns",
            "type": "worker-pools",
        }

    def test_dry_run_is_the_processed_specification(self, run_provision):
        out, _, client = run_provision(dry_run=True)
        client.worker_pool_client.provision_worker_pool.assert_not_called()
        assert out["requirementTemplateUsage"]["requirementName"] == "wp-name"


class TestInstantiate:
    @pytest.fixture()
    def run_instantiate(self, run, monkeypatch):
        import dataclasses

        import yellowdog_cli.instantiate as yd_instantiate

        monkeypatch.setattr(
            yd_instantiate,
            "CONFIG_WP",
            dataclasses.replace(
                yd_instantiate.CONFIG_WP,
                worker_pool_data_file=None,
                compute_requirement_data_file=None,
                template_id="crt-id",
                name="cr-name",
                target_instance_count=1,
            ),
        )
        monkeypatch.setattr(
            yd_instantiate, "warn_of_undefined_worker_pool_variables", lambda: None
        )
        monkeypatch.setattr(yd_instantiate, "get_template_id", lambda **k: "crt-id")
        monkeypatch.setattr(yd_instantiate, "get_user_data_property", lambda *a: None)
        monkeypatch.setattr(yd_instantiate, "link_entity", lambda *a: "[link]")

        def _run(**values):
            client = MagicMock()
            client.compute_client.provision_compute_requirement_template.side_effect = (
                lambda usage: SimpleNamespace(id=CR_ID, name=usage.requirementName)
            )
            return run(
                yd_instantiate,
                client=client,
                **{
                    "target": None,
                    "worker_pool_file": None,
                    "compute_requirement": None,
                    "compute_requirement_file_positional": None,
                    "content_path": None,
                    "report": False,
                    **values,
                },
            )

        return _run

    def test_the_instantiated_compute_requirement(self, run_instantiate):
        out, _, _ = run_instantiate()
        assert out == {
            "id": CR_ID,
            "name": "cr-name",
            "namespace": "ns",
            "type": "compute-requirements",
        }

    def test_dry_run_is_the_processed_specification(self, run_instantiate):
        out, _, client = run_instantiate(dry_run=True)
        client.compute_client.provision_compute_requirement_template.assert_not_called()
        assert out["requirementName"] == "cr-name"

    def test_batches_are_an_array(self, run_instantiate, monkeypatch):
        import dataclasses

        import yellowdog_cli.instantiate as yd_instantiate

        monkeypatch.setattr(
            yd_instantiate,
            "CONFIG_WP",
            dataclasses.replace(
                yd_instantiate.CONFIG_WP,
                compute_requirement_batch_size=1,
                target_instance_count=2,
            ),
        )
        out, _, _ = run_instantiate()
        assert [cr["type"] for cr in out] == ["compute-requirements"] * 2
        assert out[0]["name"] != out[1]["name"]
        reset_results()
        dry, _, _ = run_instantiate(dry_run=True)
        assert [cr["targetInstanceCount"] for cr in dry] == [1, 1]


class TestConfiguredWorkerPoolToken:
    def test_the_token_is_recorded(self, run_create):
        from datetime import datetime, timezone

        client = MagicMock()
        client.worker_pool_client.add_configured_worker_pool.return_value = (
            SimpleNamespace(
                workerPool=SimpleNamespace(id=WP_ID),
                token=SimpleNamespace(
                    secret="tok",
                    expiryTime=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
                ),
            )
        )
        import yellowdog_cli.create as yd_create

        # The request's construction is not what is under test
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(yd_create, "_get_model_object", lambda *a, **k: MagicMock())
            out, _, _ = run_create(
                [{"resource": "ConfiguredWorkerPool", "name": "cwp", "namespace": "n"}],
                client=client,
            )
        assert out == [
            _resource(
                "ConfiguredWorkerPool",
                "n/cwp",
                WP_ID,
                "created",
                token="tok",
                expiryTime="2026-10-01T12:00:00+00:00",
            )
        ]


# ---------------------------------------------------------------------------
# '--json' refused with the options that write their own output to stdout
# ---------------------------------------------------------------------------


class TestJsonExcludesStreaming:
    @pytest.mark.parametrize(
        "command, option",
        [
            ("yd-submit", "--progress"),
            ("yd-instantiate", "--report"),
        ],
    )
    def test_refused(self, command, option, capsys):
        from yellowdog_cli.utils.args import CLIParser

        with pytest.raises(SystemExit) as exit_info:
            CLIParser(command=command, argv=["--json", option])
        assert exit_info.value.code == 2
        assert f"--json cannot be combined with {option}" in capsys.readouterr().err

    @pytest.mark.parametrize("command", ["yd-submit", "yd-provision", "yd-instantiate"])
    def test_follow_alone_is_allowed(self, command):
        from yellowdog_cli.utils.args import CLIParser

        parser = CLIParser(command=command, argv=["--json", "--follow"])
        assert parser.json_output and parser.follow

    def test_each_option_alone_is_allowed(self):
        from yellowdog_cli.utils.args import CLIParser

        assert CLIParser(command="yd-submit", argv=["--progress"]).progress


# ===========================================================================
# The remaining commands: waiting, following, the data client, comparison,
# node actions and the two standalone utilities
# ===========================================================================

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

import yellowdog_cli.compare as yd_compare  # noqa: E402
import yellowdog_cli.copy as yd_copy  # noqa: E402
import yellowdog_cli.delete as yd_delete  # noqa: E402
import yellowdog_cli.download as yd_download  # noqa: E402
import yellowdog_cli.follow as yd_follow  # noqa: E402
import yellowdog_cli.help as yd_help  # noqa: E402
import yellowdog_cli.ls as yd_ls  # noqa: E402
import yellowdog_cli.nodeaction as yd_nodeaction  # noqa: E402
import yellowdog_cli.upload as yd_upload  # noqa: E402
import yellowdog_cli.utils.dataclient_wrapper as dcw_module  # noqa: E402
import yellowdog_cli.utils.rclone_utils as rclone_utils_module  # noqa: E402
import yellowdog_cli.version as yd_version  # noqa: E402
import yellowdog_cli.wait as yd_wait  # noqa: E402
from yellowdog_cli.utils.config_types import ConfigDataClient  # noqa: E402
from yellowdog_cli.utils.rclone_version import find_rclone  # noqa: E402
from yellowdog_cli.utils.results import rows_as_objects  # noqa: E402


class TestRowsAsObjects:
    def test_headings_become_lower_camel_case_keys(self):
        assert rows_as_objects(
            ["Node ID", "Status", "Worker Pool Match?", "Task Group Run Specification"],
            [["n1", "EMPTY", "YES", "spec"]],
        ) == [
            {
                "nodeId": "n1",
                "status": "EMPTY",
                "workerPoolMatch": "YES",
                "taskGroupRunSpecification": "spec",
            }
        ]

    def test_an_unheaded_column_is_dropped(self):
        # yd-compare's summary table numbers its rows in an unheaded column
        assert rows_as_objects(["", "Status"], [[1, "RUNNING"]]) == [
            {"status": "RUNNING"}
        ]


# ---------------------------------------------------------------------------
# yd-wait
# ---------------------------------------------------------------------------


class TestWait:
    def _client(self, wr_status=WorkRequirementStatus.COMPLETED):
        client = MagicMock()
        client.work_client.get_work_requirement_by_id.return_value = SimpleNamespace(
            status=wr_status
        )
        client.worker_pool_client.get_worker_pool_by_id.return_value = SimpleNamespace(
            status=WorkerPoolStatus.TERMINATED
        )
        client.compute_client.get_compute_requirement_by_id.return_value = (
            SimpleNamespace(status=ComputeRequirementStatus.TERMINATED)
        )
        return client

    def _follow(self, monkeypatch, valid):
        monkeypatch.setattr(yd_wait, "follow_ids", lambda ids: valid)

    def test_each_id_is_recorded_with_its_status(self, run, monkeypatch):
        self._follow(monkeypatch, [WR_ID_1, WP_ID, CR_ID])
        out, _, _ = run(
            yd_wait, client=self._client(), yellowdog_ids=[WR_ID_1, WP_ID, CR_ID]
        )
        assert out == [
            {"id": WR_ID_1, "status": "COMPLETED", "succeeded": True},
            {"id": WP_ID, "status": "TERMINATED", "succeeded": True},
            {"id": CR_ID, "status": "TERMINATED", "succeeded": True},
        ]

    def test_a_failed_work_requirement_did_not_succeed(self, run, monkeypatch):
        self._follow(monkeypatch, [WR_ID_1])
        out, err, _ = run(
            yd_wait,
            client=self._client(WorkRequirementStatus.FAILED),
            yellowdog_ids=[WR_ID_1],
        )
        assert out == [{"id": WR_ID_1, "status": "FAILED", "succeeded": False}]
        assert "ended with status 'FAILED'" in err

    def test_a_non_terminal_state_at_exit_did_not_succeed(self, run, monkeypatch):
        self._follow(monkeypatch, [WR_ID_1])
        out, _, _ = run(
            yd_wait,
            client=self._client(WorkRequirementStatus.RUNNING),
            yellowdog_ids=[WR_ID_1],
        )
        assert out == [{"id": WR_ID_1, "status": "RUNNING", "succeeded": False}]

    def test_an_unfetchable_status_is_null(self, run, monkeypatch):
        self._follow(monkeypatch, [WR_ID_1])
        client = self._client()
        client.work_client.get_work_requirement_by_id.side_effect = Exception("boom")
        out, _, _ = run(yd_wait, client=client, yellowdog_ids=[WR_ID_1])
        assert out == [{"id": WR_ID_1, "status": None, "succeeded": False}]

    def test_an_invalid_id_is_recorded_before_the_failure(self, run, monkeypatch):
        self._follow(monkeypatch, [])
        out, _, _ = run(yd_wait, client=self._client(), yellowdog_ids=["not-an-id"])
        assert out == [{"id": "not-an-id", "status": None, "succeeded": False}]


# ---------------------------------------------------------------------------
# yd-follow: '--json' streams the events
# ---------------------------------------------------------------------------


class TestFollow:
    def test_json_streams_the_events(self):
        from yellowdog_cli.utils.args import CLIParser

        parser = CLIParser(command="yd-follow", argv=["--json", WR_ID_1])
        assert parser.events_as_json and parser.json_output

    @pytest.mark.parametrize(
        "command, argv",
        [
            ("yd-follow", ["--raw-events", WR_ID_1]),
            ("yd-cancel", ["--follow", "--raw-events", "wr"]),
            ("yd-submit", ["--follow", "--raw-events"]),
        ],
    )
    def test_raw_events_is_no_longer_an_option(self, command, argv, capsys):
        # The raw event stream is yd-follow's '--json'; the option that
        # duplicated it, on yd-follow and on every command taking '--follow',
        # is gone
        from yellowdog_cli.utils.args import CLIParser

        with pytest.raises(SystemExit) as exit_info:
            CLIParser(command=command, argv=argv)
        assert exit_info.value.code == 2
        assert "--raw-events" in capsys.readouterr().err

    def test_json_is_refused_with_progress(self, capsys):
        from yellowdog_cli.utils.args import CLIParser

        with pytest.raises(SystemExit) as exit_info:
            CLIParser(command="yd-follow", argv=["--json", "--progress", WR_ID_1])
        assert exit_info.value.code == 2
        assert "--json cannot be combined with --progress" in capsys.readouterr().err

    def test_the_events_are_printed_raw_and_nothing_follows(self, monkeypatch, capsys):
        from yellowdog_cli.utils.args import CLIParser

        args = CLIParser(command="yd-follow", argv=["--json", "--nf", WR_ID_1])
        for target in (yd_follow, results_module, printing_module, wrapper_module):
            monkeypatch.setattr(target, "ARGS_PARSER", args)
        monkeypatch.setattr(wrapper_module, "CLIENT", MagicMock())
        event = {"name": "wr", "status": "RUNNING", "taskGroups": []}

        def follow(ids, auto_cr=False):
            printing_module.print_event(
                "data:" + __import__("json").dumps(event), YDIDType_WR
            )
            return ids

        monkeypatch.setattr(yd_follow, "follow_ids", follow)
        monkeypatch.setattr(yd_follow, "follow_errors_occurred", lambda: False)
        with pytest.raises(SystemExit) as exit_info:
            yd_follow.main()
        assert exit_info.value.code == 0
        # The event itself, and no result array after it
        assert json_loads(capsys.readouterr().out) == event

    def test_no_events_print_nothing_rather_than_an_empty_array(
        self, monkeypatch, capsys
    ):
        from yellowdog_cli.utils.args import CLIParser

        args = CLIParser(command="yd-follow", argv=["--json", "--nf", WR_ID_1])
        for target in (yd_follow, results_module, printing_module, wrapper_module):
            monkeypatch.setattr(target, "ARGS_PARSER", args)
        monkeypatch.setattr(wrapper_module, "CLIENT", MagicMock())
        monkeypatch.setattr(yd_follow, "follow_ids", lambda ids, auto_cr=False: ids)
        monkeypatch.setattr(yd_follow, "follow_errors_occurred", lambda: False)
        with pytest.raises(SystemExit):
            yd_follow.main()
        assert capsys.readouterr().out == ""

    def test_only_yd_follow_streams_events_as_json(self):
        from yellowdog_cli.utils.args import CLIParser

        assert not CLIParser(command="yd-follow", argv=[WR_ID_1]).events_as_json
        # Another command's '--follow --json' still follows through status
        # messages, which '--json' silences: its document is the result
        assert not CLIParser(
            command="yd-cancel", argv=["--json", "--follow", "-D"]
        ).events_as_json


from yellowdog_cli.utils.ydid_utils import YDIDType as _YDIDType  # noqa: E402

YDIDType_WR = _YDIDType.WORK_REQUIREMENT


# ---------------------------------------------------------------------------
# The data client, against a local rclone backend
# ---------------------------------------------------------------------------

needs_rclone = pytest.mark.skipif(
    find_rclone() is None, reason="needs an rclone binary"
)

_DC_DEFAULTS = {
    **_DEFAULTS,
    "upgrade_rclone": False,
    "which_rclone": False,
    "sync": False,
    "recursive": False,
    "flatten": False,
    "long_listing": False,
    "destination": None,
    "into": None,
    "remote_paths": [],
}


@pytest.fixture()
def remote(tmp_path, monkeypatch):
    """
    A local rclone 'remote' under tmp_path: 'remote/a.txt' (5 bytes) and
    'remote/sub/b.txt' (3 bytes), with the working directory at tmp_path
    so that the remote's relative bucket resolves there.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "remote" / "sub").mkdir(parents=True)
    (tmp_path / "remote" / "a.txt").write_text("hello")
    (tmp_path / "remote" / "sub" / "b.txt").write_text("abc")
    return tmp_path


@pytest.fixture()
def run_dc(monkeypatch, capsys):
    """
    Return run_dc(module, **args): run a data client command's main()
    through dataclient_wrapper against the local 'remote', and return
    (parsed stdout, stderr, exit code); stdout is left as text when
    'json_output' is false.
    """
    config = ConfigDataClient(remote="loc,type=local", bucket="remote")

    def _run(module, **values):
        args = MagicMock(**{**_DC_DEFAULTS, **values})
        for target in (
            module,
            results_module,
            printing_module,
            interactive_module,
            dcw_module,
            rclone_utils_module,
        ):
            monkeypatch.setattr(target, "ARGS_PARSER", args)
        for name in ("CONFIG_DATA_CLIENT", "CONFIG_SRC", "CONFIG_DST"):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, config)
        with pytest.raises(SystemExit) as exit_info:
            module.main()
        out, err = capsys.readouterr()
        return (json_loads(out) if args.json_output else out), err, exit_info.value.code

    return _run


def _comparable(entries: list[dict]) -> list[dict]:
    """
    The entries without what varies by run and by backend: the modification
    time, and a directory's size (-1 on object stores, the inode's on local).
    """
    return [
        {
            k: v
            for k, v in e.items()
            if k in ("Path", "Name", "IsDir") or (k == "Size" and not e["IsDir"])
        }
        for e in entries
    ]


@needs_rclone
class TestLs:
    def test_the_lsjson_entries(self, remote, run_dc):
        out, _, code = run_dc(yd_ls, remote_paths=["loc:remote"])
        assert code == 0
        # Exactly the spec's keys, as rclone spells them
        assert all(set(e) == {"Path", "Name", "Size", "ModTime", "IsDir"} for e in out)
        assert sorted(_comparable(out), key=lambda e: e["Path"]) == [
            {"Path": "a.txt", "Name": "a.txt", "Size": 5, "IsDir": False},
            {"Path": "sub", "Name": "sub", "IsDir": True},
        ]

    def test_recursive(self, remote, run_dc):
        out, _, _ = run_dc(yd_ls, remote_paths=["loc:remote"], recursive=True)
        assert sorted(e["Path"] for e in out) == ["a.txt", "sub", "sub/b.txt"]

    def test_a_glob(self, remote, run_dc):
        out, _, _ = run_dc(yd_ls, remote_paths=["loc:remote/*.txt"])
        assert [e["Name"] for e in out] == ["a.txt"]

    def test_a_glob_recursive_includes_a_matched_directorys_contents(
        self, remote, run_dc
    ):
        out, _, _ = run_dc(yd_ls, remote_paths=["loc:remote/s*"], recursive=True)
        assert sorted(e["Path"] for e in out) == ["sub", "sub/b.txt"]

    def test_the_default_listing_is_not_printed(self, remote, run_dc):
        # stdout is the document alone: run_dc would fail to parse a table
        out, _, _ = run_dc(yd_ls, remote_paths=["loc:remote"], long_listing=True)
        assert isinstance(out, list)

    def test_an_empty_listing_is_an_empty_array(self, remote, run_dc):
        (remote / "remote" / "empty").mkdir()
        out, _, _ = run_dc(yd_ls, remote_paths=["loc:remote/empty"])
        assert out == []


@needs_rclone
class TestMissingPathWarnings:
    """
    A missing remote path is reported by the command's own message, never by
    rclone_api's UserWarning, which also spells out the whole rclone command
    line, an inline remote's parameters included.
    """

    @pytest.mark.parametrize(
        "module, values",
        [
            ("ls", {"remote_paths": ["loc:remote/nosuch"]}),
            ("ls", {"remote_paths": ["loc:remote/nosuch"], "json_output": False}),
            ("ls", {"remote_paths": ["loc:nosuch/*"]}),
            ("download", {"remote_paths": ["loc:remote/nope"]}),
            ("download", {"remote_paths": ["loc:remote/nope"], "dry_run": True}),
            ("download", {"remote_paths": ["loc:nosuch/*"], "dry_run": True}),
            ("delete", {"remote_paths": ["loc:remote/nosuch"]}),
            ("delete", {"remote_paths": ["loc:remote/nosuch"], "json_output": False}),
            ("copy", {"src_path": "loc:remote/nosuch", "dst_path": "loc:dst"}),
        ],
    )
    def test_no_library_warning(self, remote, run_dc, module, values):
        modules = {"ls": yd_ls, "download": yd_download, "delete": yd_delete}
        modules["copy"] = yd_copy
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _, err, _ = run_dc(modules[module], **values)
        assert [str(w.message) for w in caught] == []
        assert "UserWarning" not in err


@needs_rclone
class TestUpload:
    def test_a_file(self, remote, run_dc):
        (remote / "up.txt").write_text("1234")
        out, _, code = run_dc(yd_upload, local_paths=["up.txt"])
        assert code == 0
        assert out == [
            {
                "source": "up.txt",
                "destination": "loc:remote/up.txt",
                "size": 4,
                "action": "uploaded",
            }
        ]
        assert (remote / "remote" / "up.txt").read_text() == "1234"

    def test_a_directory_records_each_file(self, remote, run_dc):
        (remote / "d" / "e").mkdir(parents=True)
        (remote / "d" / "x.txt").write_text("x")
        (remote / "d" / "e" / "y.txt").write_text("yy")
        out, _, _ = run_dc(yd_upload, local_paths=["d"], recursive=True)
        assert sorted(out, key=lambda r: r["source"]) == [
            {
                "source": str(_Path("d") / "e" / "y.txt"),
                "destination": "loc:remote/d/e/y.txt",
                "size": 2,
                "action": "uploaded",
            },
            {
                "source": str(_Path("d") / "x.txt"),
                "destination": "loc:remote/d/x.txt",
                "size": 1,
                "action": "uploaded",
            },
        ]
        assert (remote / "remote" / "d" / "e" / "y.txt").exists()

    def test_dry_run(self, remote, run_dc):
        (remote / "up.txt").write_text("1234")
        out, _, _ = run_dc(yd_upload, local_paths=["up.txt"], dry_run=True)
        assert [r["action"] for r in out] == ["would upload"]
        assert not (remote / "remote" / "up.txt").exists()

    def test_a_missing_path_failed(self, remote, run_dc):
        out, _, _ = run_dc(yd_upload, local_paths=["nope.txt"])
        assert out == [
            {
                "source": "nope.txt",
                "destination": None,
                "size": None,
                "action": "failed",
                "error": "Path does not exist: 'nope.txt'",
            }
        ]

    def test_a_directory_without_recursive_is_skipped(self, remote, run_dc):
        (remote / "d").mkdir()
        out, _, _ = run_dc(yd_upload, local_paths=["d"])
        assert [(r["source"], r["action"]) for r in out] == [("d", "skipped")]


@needs_rclone
class TestDownload:
    def test_a_file(self, remote, run_dc):
        out, _, code = run_dc(
            yd_download, remote_paths=["loc:remote/a.txt"], into="got"
        )
        assert code == 0
        # '--into' gives the file its own path, which it occupies itself
        assert out == [
            {
                "source": "loc:remote/a.txt",
                "destination": str(_Path("got") / "a.txt"),
                "size": 5,
                "action": "downloaded",
                "match": "loc:remote/a.txt",
            }
        ]
        assert (remote / "got" / "a.txt").read_text() == "hello"

    def test_a_file_dry_run_names_the_same_destination(self, remote, run_dc):
        out, _, _ = run_dc(
            yd_download, remote_paths=["loc:remote/a.txt"], into="got", dry_run=True
        )
        assert [(r["destination"], r["action"]) for r in out] == [
            (str(_Path("got") / "a.txt"), "would download")
        ]
        assert not (remote / "got").exists()

    def test_a_directory_records_each_file(self, remote, run_dc):
        out, _, _ = run_dc(yd_download, remote_paths=["loc:remote/sub"])
        assert out == [
            {
                "source": "loc:remote/sub/b.txt",
                "destination": str(_Path("sub") / "b.txt"),
                "size": 3,
                "action": "downloaded",
                "match": "loc:remote/sub",
            }
        ]
        assert (remote / "sub" / "b.txt").read_text() == "abc"

    def test_a_glob(self, remote, run_dc):
        out, _, _ = run_dc(yd_download, remote_paths=["loc:remote/*"], into="got")
        assert sorted((r["source"], r["destination"]) for r in out) == [
            ("loc:remote/a.txt", str(_Path("got") / "a.txt")),
            ("loc:remote/sub/b.txt", str(_Path("got") / "sub" / "b.txt")),
        ]

    def test_dry_run_records_each_file_and_downloads_nothing(self, remote, run_dc):
        out, _, _ = run_dc(yd_download, remote_paths=["loc:remote/*"], dry_run=True)
        assert sorted(out, key=lambda r: r["source"]) == [
            {
                "source": "loc:remote/a.txt",
                "destination": "a.txt",
                "size": 5,
                "action": "would download",
                "match": "loc:remote/a.txt",
            },
            {
                "source": "loc:remote/sub/b.txt",
                "destination": str(_Path("sub") / "b.txt"),
                "size": 3,
                "action": "would download",
                "match": "loc:remote/sub",
            },
        ]
        assert not (remote / "a.txt").exists()

    def test_the_dry_run_records_group_into_commanders_selection(self, remote, run_dc):
        # Commander offers the top-level items the records name in 'match'
        from yellowdog_cli.commander.selection import (
            ObjectSummary,
            parse_download_summaries,
        )

        out, _, _ = run_dc(yd_download, remote_paths=["loc:remote/*"], dry_run=True)
        assert sorted(parse_download_summaries(out), key=lambda o: o.path) == [
            ObjectSummary(path="loc:remote/a.txt", name="a.txt", is_dir=False),
            ObjectSummary(path="loc:remote/sub", name="sub/", is_dir=True),
        ]

    @pytest.mark.parametrize("path", ["loc:remote/sub", "loc:remote/s*"])
    @pytest.mark.parametrize("dry_run", [False, True])
    def test_flattened_records_name_the_flat_destinations(
        self, remote, run_dc, path, dry_run
    ):
        (remote / "remote" / "sub" / "deeper").mkdir()
        (remote / "remote" / "sub" / "deeper" / "c.txt").write_text("xyz")
        out, _, code = run_dc(
            yd_download,
            remote_paths=[path],
            destination="flat",
            flatten=True,
            dry_run=dry_run,
        )
        assert code == 0
        action = "would download" if dry_run else "downloaded"
        assert sorted((r["source"], r["destination"], r["action"]) for r in out) == [
            ("loc:remote/sub/b.txt", str(_Path("flat") / "b.txt"), action),
            ("loc:remote/sub/deeper/c.txt", str(_Path("flat") / "c.txt"), action),
        ]
        assert all(r["match"] == "loc:remote/sub" for r in out)
        assert (remote / "flat" / "c.txt").exists() != dry_run

    def test_a_missing_path_records_nothing(self, remote, run_dc):
        # The local backend fails the listing, an object store lists nothing
        # and warns; either way no transfer is recorded, and stdout still
        # parses
        out, _, _ = run_dc(yd_download, remote_paths=["loc:remote/nope"])
        assert out == []


@needs_rclone
class TestCopy:
    def test_a_directory_records_each_file(self, remote, run_dc):
        out, _, code = run_dc(yd_copy, src_path="loc:remote/sub", dst_path="loc:dst")
        assert code == 0
        assert out == [
            {
                "source": "loc:remote/sub/b.txt",
                "destination": "loc:dst/b.txt",
                "size": 3,
                "action": "copied",
            }
        ]
        assert (remote / "dst" / "b.txt").read_text() == "abc"

    def test_a_file(self, remote, run_dc):
        out, _, _ = run_dc(yd_copy, src_path="loc:remote/a.txt", dst_path="loc:c.txt")
        assert out == [
            {
                "source": "loc:remote/a.txt",
                "destination": "loc:c.txt",
                "size": 5,
                "action": "copied",
            }
        ]

    def test_dry_run(self, remote, run_dc):
        out, _, _ = run_dc(
            yd_copy, src_path="loc:remote/sub", dst_path="loc:dst", dry_run=True
        )
        assert [(r["destination"], r["action"]) for r in out] == [
            ("loc:dst/b.txt", "would copy")
        ]
        assert not (remote / "dst").exists()


@needs_rclone
class TestDelete:
    def test_a_file(self, remote, run_dc):
        out, _, code = run_dc(yd_delete, remote_paths=["loc:remote/a.txt"])
        assert code == 0
        assert out == [
            {
                "path": "loc:remote/a.txt",
                "action": "deleted",
                "name": "a.txt",
                "isDir": False,
            }
        ]
        assert not (remote / "remote" / "a.txt").exists()

    def test_a_glob_with_recursive(self, remote, run_dc):
        out, _, _ = run_dc(yd_delete, remote_paths=["loc:remote/*"], recursive=True)
        assert sorted((r["path"], r["action"]) for r in out) == [
            ("loc:remote/a.txt", "deleted"),
            ("loc:remote/sub", "deleted"),
        ]
        assert not (remote / "remote" / "sub").exists()

    def test_a_directory_without_recursive_is_not_recorded(self, remote, run_dc):
        out, _, _ = run_dc(yd_delete, remote_paths=["loc:remote/*"])
        assert [r["path"] for r in out] == ["loc:remote/a.txt"]
        assert (remote / "remote" / "sub" / "b.txt").exists()

    def test_a_literal_directory_needs_recursive(self, remote, run_dc):
        out, _, _ = run_dc(yd_delete, remote_paths=["loc:remote/sub"], recursive=True)
        assert out == [
            {
                "path": "loc:remote/sub",
                "action": "deleted",
                "name": "sub/",
                "isDir": True,
            }
        ]
        assert not (remote / "remote" / "sub").exists()

    def test_the_records_are_commanders_selection(self, remote, run_dc):
        from yellowdog_cli.commander.selection import (
            ObjectSummary,
            parse_object_summaries,
        )

        out, _, _ = run_dc(
            yd_delete, remote_paths=["loc:remote/*"], recursive=True, dry_run=True
        )
        assert sorted(parse_object_summaries(out), key=lambda o: o.path) == [
            ObjectSummary(path="loc:remote/a.txt", name="a.txt", is_dir=False),
            ObjectSummary(path="loc:remote/sub", name="sub/", is_dir=True),
        ]

    def test_dry_run(self, remote, run_dc):
        # The per-item records Commander offers its selection from: the path to
        # pass back, the display name and whether the item is a directory
        out, _, _ = run_dc(
            yd_delete, remote_paths=["loc:remote/*"], recursive=True, dry_run=True
        )
        assert sorted(out, key=lambda r: r["path"]) == [
            {
                "path": "loc:remote/a.txt",
                "action": "would delete",
                "name": "a.txt",
                "isDir": False,
            },
            {
                "path": "loc:remote/sub",
                "action": "would delete",
                "name": "sub/",
                "isDir": True,
            },
        ]
        assert (remote / "remote" / "a.txt").exists()


# ---------------------------------------------------------------------------
# yd-compare
# ---------------------------------------------------------------------------


class TestCompare:
    def test_one_row_per_worker_pool_with_its_properties(self, run, monkeypatch):
        from yellowdog_cli.compare import MatchReport, MatchType, PropertyMatch

        def pm(name, match):
            return PropertyMatch(
                property_name=name,
                task_group_values="tg",
                worker_pool_values="wp",
                match=match,
            )

        report = MatchReport(
            worker_pool_name="pool",
            worker_pool_id=WP_ID,
            worker_pool_status="RUNNING",
            worker_tags=pm("Worker Tags", MatchType.YES),
            task_types=pm("Task Types", MatchType.YES),
            instance_types=pm("Instance Types", MatchType.YES),
            providers=pm("Providers", MatchType.YES),
            regions=pm("Regions", MatchType.YES),
            namespaces=pm("Namespaces", MatchType.YES),
            ram=pm("RAM", MatchType.NO),
            vcpus=pm("vCPUs", MatchType.YES),
        )
        task_group = SimpleNamespace(
            name="tg1", id="ydid:taskgrp:000000:11111111-1111-1111-1111-111111111111:1"
        )
        monkeypatch.setattr(
            yd_compare, "_get_provisioned_worker_pool_by_id", lambda i: MagicMock()
        )
        monkeypatch.setattr(yd_compare, "get_task_group_by_id", lambda c, i: task_group)
        monkeypatch.setattr(
            yd_compare,
            "WorkerPools",
            lambda wps: SimpleNamespace(
                check_task_group_for_matching_worker_pools=lambda task_group: [report]
            ),
        )
        out, _, _ = run(
            yd_compare,
            worker_pool_ids=[WP_ID],
            wr_or_tg_id="ydid:taskgrp:000000:11111111-1111-1111-1111-111111111111:1",
        )
        assert len(out) == 1
        row = out[0]
        assert {k: v for k, v in row.items() if k != "properties"} == {
            "taskGroupName": "tg1",
            "taskGroupId": "ydid:taskgrp:000000:11111111-1111-1111-1111-111111111111:1",
            "workerPoolName": "pool",
            "status": "RUNNING",
            "workerPoolId": WP_ID,
            "workerPoolMatch": "NO",
        }
        assert {
            "property": "RAM",
            "taskGroupRunSpecification": "tg",
            "workerPool": "wp",
            "matchStatus": "NO",
        } in row["properties"]
        assert len(row["properties"]) == 8


# ---------------------------------------------------------------------------
# yd-nodeaction
# ---------------------------------------------------------------------------


class TestNodeAction:
    def test_the_queue_status_table(self, run, monkeypatch):
        from yellowdog_client.model import NodeActionQueueStatus

        client = MagicMock()
        client.worker_pool_client.get_node_actions_by_id.return_value = SimpleNamespace(
            status=NodeActionQueueStatus.EMPTY,
            waiting=[],
            executing=[],
            failed=None,
        )
        out, _, _ = run(yd_nodeaction, client=client, status=True, node_ids=[NODE_ID])
        assert out == [
            {
                "nodeId": NODE_ID,
                "status": "EMPTY",
                "waiting": 0,
                "executing": "-",
                "failed": "-",
            }
        ]

    def test_the_submission_table(self, run, monkeypatch):
        monkeypatch.setattr(yd_nodeaction, "_load_spec", lambda f: {"actions": [{}]})
        monkeypatch.setattr(
            yd_nodeaction, "_parse_actions", lambda specs, d: [MagicMock(), MagicMock()]
        )
        monkeypatch.setattr(
            yd_nodeaction, "_get_worker_pool_id_for_node", lambda n: WP_ID
        )
        monkeypatch.setattr(yd_nodeaction, "_resolve_node_ids", lambda wp: [NODE_ID])
        out, _, _ = run(
            yd_nodeaction,
            status=False,
            node_action_spec="spec.json",
            content_path=None,
            node_ids=[NODE_ID],
            worker_pool_name=None,
            all_nodes=False,
        )
        assert out == [
            {
                "workerPoolId": WP_ID,
                "nodeId": NODE_ID,
                "actionGroups": None,
                "actions": 2,
                "outcome": "submitted",
            }
        ]


class TestNodeActionOutcomes:
    def _submit(self, run, monkeypatch, **values):
        monkeypatch.setattr(yd_nodeaction, "_load_spec", lambda f: {"actions": [{}]})
        monkeypatch.setattr(
            yd_nodeaction, "_parse_actions", lambda specs, d: [MagicMock()]
        )
        monkeypatch.setattr(
            yd_nodeaction, "_get_worker_pool_id_for_node", lambda n: WP_ID
        )
        monkeypatch.setattr(yd_nodeaction, "_resolve_node_ids", lambda wp: [NODE_ID])
        return run(
            yd_nodeaction,
            status=False,
            node_action_spec="spec.json",
            content_path=None,
            node_ids=[NODE_ID],
            worker_pool_name=None,
            all_nodes=False,
            **values,
        )

    def test_declined_is_skipped(self, run, monkeypatch):
        out, _, _ = self._submit(run, monkeypatch, confirm=False)
        assert [r["outcome"] for r in out] == ["skipped"]

    def test_a_failed_submission_carries_the_error(self, run, monkeypatch):
        client = MagicMock()
        client.worker_pool_client.add_node_actions_for_node_by_id.side_effect = (
            Exception("boom")
        )
        out, err, _ = self._submit(run, monkeypatch, client=client)
        assert out[0]["outcome"] == "failed"
        assert out[0]["error"] == "Failed to submit: boom"
        assert "boom" in err


# ---------------------------------------------------------------------------
# yd-version and yd-help: standalone, printing their own documents
# ---------------------------------------------------------------------------


class TestVersion:
    def _run(self, monkeypatch, capsys, *argv):
        monkeypatch.setattr(_sys, "argv", ["yd-version", *argv])
        yd_version.main()
        return json_loads(capsys.readouterr().out)

    def test_the_versions(self, monkeypatch, capsys):
        monkeypatch.setattr(yd_version, "_jsonnet_version", lambda: "Not installed")
        out = self._run(monkeypatch, capsys, "--json")
        assert set(out) == {
            "cli",
            "sdk",
            "python",
            "jsonnet",
            "rclone",
            "mcp",
            "author",
            "licence",
        }
        assert out["cli"] == yd_version.__version__
        assert out["jsonnet"] is None

    def test_the_author_and_licence(self, monkeypatch, capsys):
        # The plain report's Author and Licence lines, as structured values
        out = self._run(monkeypatch, capsys, "--json")
        assert out["author"] == {
            "name": yd_version.__author__,
            "email": yd_version.__email__,
        }
        assert out["licence"] == yd_version.cli_licence()

    def test_the_sdk_version_is_the_sdks_own(self, monkeypatch, capsys):
        # Read from package metadata, so that naming it imports no SDK
        from yellowdog_client._version import __version__ as sdk_version

        assert self._run(monkeypatch, capsys, "--json")["sdk"] == sdk_version

    def test_the_mcp_sdk_version(self, monkeypatch, capsys):
        # The 'mcp' extra's SDK, read from package metadata without importing
        # it, so yd-version stays standalone and fast
        monkeypatch.setattr(yd_version, "_mcp_version", lambda: "2.9.9")
        assert self._run(monkeypatch, capsys, "--json")["mcp"] == "2.9.9"
        monkeypatch.setattr(yd_version, "_mcp_version", lambda: "Not installed")
        assert self._run(monkeypatch, capsys, "--json")["mcp"] is None

    def test_mcp_alone_prints_the_bare_version_or_exits_1(self, monkeypatch, capsys):
        monkeypatch.setattr(yd_version, "_mcp_version", lambda: "2.9.9")
        monkeypatch.setattr(_sys, "argv", ["yd-version", "--mcp"])
        yd_version.main()
        assert capsys.readouterr().out.strip() == "2.9.9"
        monkeypatch.setattr(yd_version, "_mcp_version", lambda: "Not installed")
        with pytest.raises(SystemExit) as exit_info:
            yd_version.main()
        assert exit_info.value.code == 1

    def test_the_report_names_the_licence_from_package_metadata(
        self, monkeypatch, capsys
    ):
        # pyproject.toml is the one place the licence is stated
        import tomli

        with open(_Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
            declared = tomli.load(f)["project"]["license"]
        assert yd_version.cli_licence() == declared
        monkeypatch.setattr(_sys, "argv", ["yd-version"])
        yd_version.main()
        assert f"Licence:                 {declared}" in capsys.readouterr().out

    def test_an_unknown_licence(self, monkeypatch):
        def not_found(_name):
            raise yd_version.PackageNotFoundError

        monkeypatch.setattr(yd_version, "metadata", not_found)
        assert yd_version.cli_licence() == yd_version.UNKNOWN_LICENCE

    def test_a_missing_rclone_is_null(self, monkeypatch, capsys):
        monkeypatch.setattr(yd_version, "_rclone_version", lambda: "Not installed")
        assert self._run(monkeypatch, capsys, "--json")["rclone"] is None

    def test_json_excludes_the_single_version_options(self, monkeypatch, capsys):
        monkeypatch.setattr(_sys, "argv", ["yd-version", "--json", "--cli"])
        with pytest.raises(SystemExit) as exit_info:
            yd_version.main()
        assert exit_info.value.code == 2

    def test_debug_adds_the_executable_and_path(self, monkeypatch, capsys):
        out = self._run(monkeypatch, capsys, "--json", "--debug")
        assert out["executable"] == _sys.executable
        assert out["path"] == list(_sys.path)


class TestHelp:
    def test_the_command_list(self, monkeypatch, capsys):
        monkeypatch.setattr(_sys, "argv", ["yd-help", "--json"])
        yd_help.main()
        out = json_loads(capsys.readouterr().out)
        assert {
            "command": "yd-help",
            "summary": yd_help.COMMANDS["yd-help"].summary,
        } in out
        assert [r["command"] for r in out] == sorted(r["command"] for r in out)

    def test_without_json_the_listing_is_text(self, monkeypatch, capsys):
        monkeypatch.setattr(_sys, "argv", ["yd-help"])
        yd_help.main()
        assert "available commands" in capsys.readouterr().out


class TestEntryToName:
    def test_a_directory_is_marked(self):
        from yellowdog_cli.utils.dataclient_utils import entry_to_name

        assert entry_to_name({"Name": "file.txt", "IsDir": False}) == "file.txt"
        assert entry_to_name({"Name": "subdir", "IsDir": True}) == "subdir/"


class TestJoinRemote:
    def test_a_bare_remote_gets_no_slash(self):
        from yellowdog_cli.utils.dataclient_utils import _join_remote

        assert _join_remote("S3:", "x") == "S3:x"
        assert _join_remote("S3:b/", "x") == "S3:b/x"
        assert _join_remote("S3:b", "x") == "S3:b/x"


# ---------------------------------------------------------------------------
# The parsers
# ---------------------------------------------------------------------------


class TestRemainingParsers:
    @pytest.mark.parametrize(
        "command, argv",
        [
            ("yd-wait", [WR_ID_1]),
            ("yd-ls", []),
            ("yd-upload", ["f"]),
            ("yd-copy", ["a", "b"]),
            ("yd-compare", [WR_ID_1, WP_ID]),
            ("yd-nodeaction", []),
        ],
    )
    def test_json_without_a_short_flag(self, command, argv, capsys):
        from yellowdog_cli.utils.args import CLIParser

        assert CLIParser(command=command, argv=["--json", *argv]).json_output
        with pytest.raises(SystemExit):
            CLIParser(command=command, argv=["-J", *argv])
