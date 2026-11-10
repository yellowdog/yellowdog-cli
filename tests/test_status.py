"""
yd status (status.py): each section shows what 'yd list' finds for its
type, everything or with --active-only the active alone
(utils/active_entities.py), without the Namespace and Tag columns, with
its total; an empty section says so; unhealthy items are
counted in a closing warning; a failed search is said in its section, the
others still shown, and its exit code kept, while an authentication or
connection failure stops the command; '--json' prints one document.
"""

from json import loads
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from requests import ConnectionError as RequestsConnectionError
from requests import HTTPError, Response
from yellowdog_client.model import (
    ComputeRequirementStatus,
    ComputeRequirementSummary,
    WorkerPoolStatus,
    WorkerPoolSummary,
    WorkRequirementStatus,
    WorkRequirementSummary,
)

import yellowdog_cli.status as status
from yellowdog_cli.utils import active_entities, output_settings
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.exit_codes import ExitCode, ReportedFailure, classify

NAMESPACE = "image-processing"
TAG = "nightly"
WR_ID = "ydid:workreq:000000:1d0a6a5c-3f9e-4d1e-8a2e-3a2f1b0c9d8e"
WP_ID = "ydid:wrkrpool:000000:1d0a6a5c-3f9e-4d1e-8a2e-3a2f1b0c9d8e"
CR_ID = "ydid:compreq:000000:1d0a6a5c-3f9e-4d1e-8a2e-3a2f1b0c9d8e"


def _forbidden() -> HTTPError:
    response = Response()
    response.status_code = 403
    return HTTPError(
        "403 Client Error: Forbidden "
        'Response Body: {"errorType": "MissingPermissionException"}',
        response=response,
    )


def _work_requirement(**kwargs) -> WorkRequirementSummary:
    values = {
        "id": WR_ID,
        "name": "nightly-render",
        "namespace": NAMESPACE,
        "tag": TAG,
        "status": WorkRequirementStatus.RUNNING,
        "completedTaskCount": 412,
        "totalTaskCount": 1000,
        "healthy": True,
    }
    return WorkRequirementSummary(**{**values, **kwargs})


def _worker_pool(**kwargs) -> WorkerPoolSummary:
    values = {
        "id": WP_ID,
        "name": f"{TAG}-pool",
        "namespace": NAMESPACE,
        "status": WorkerPoolStatus.RUNNING,
        "registeredNodeCount": 7,
        "claimedWorkerCount": 15,
        "registeredWorkerCount": 28,
        "healthy": True,
    }
    return WorkerPoolSummary(**{**values, **kwargs})


def _compute_requirement(**kwargs) -> ComputeRequirementSummary:
    values = {
        "id": CR_ID,
        "name": f"{TAG}-cr",
        "namespace": NAMESPACE,
        "tag": TAG,
        "status": ComputeRequirementStatus.RUNNING,
        "targetInstanceCount": 7,
        "expectedInstanceCount": 7,
        "aliveInstanceCount": 7,
        "healthy": True,
    }
    return ComputeRequirementSummary(**{**values, **kwargs})


def _searches(monkeypatch, wrs=(), wps=(), crs=()) -> list:
    """
    Stand the three searches in, each returning what it is given or raising
    it; the calls are returned.
    """
    calls = []

    def search(found):
        def run(client, namespace, tag, active_only):
            calls.append((namespace, tag, active_only))
            if isinstance(found, Exception):
                raise found
            return list(found)

        return run

    monkeypatch.setattr(status, "work_requirements", search(wrs))
    monkeypatch.setattr(status, "worker_pools", search(wps))
    monkeypatch.setattr(status, "compute_requirements", search(crs))
    return calls


def _show(
    capsys,
    json_output=False,
    quiet=False,
    namespace=NAMESPACE,
    tag=TAG,
    active_only=False,
):
    """
    Run yd status; its stdout, stderr and the failure it raised, if any.
    """
    args = SimpleNamespace(
        json_output=json_output,
        json=json_output,
        quiet=quiet,
        no_format=True,
        sort=None,
        reverse=None,
        active_only=active_only,
    )
    ctx = RunContext(
        args=args,
        config=SimpleNamespace(namespace=namespace, name_tag=tag),
        client=MagicMock(),
    )
    raised = None
    with output_settings.configured(args):
        try:
            status.show_status(ctx)
        except ReportedFailure as e:
            raised = e
    captured = capsys.readouterr()
    return captured.out, captured.err, raised


class TestTheReport:
    def test_each_section_and_its_total(self, monkeypatch, capsys):
        calls = _searches(
            monkeypatch,
            wrs=[_work_requirement()],
            wps=[_worker_pool(), _worker_pool(name=f"{TAG}-pool-2")],
            crs=[_compute_requirement()],
        )
        out, err, raised = _show(capsys)
        assert raised is None and err == ""
        assert calls == [(NAMESPACE, TAG, False)] * 3
        assert f"Items in namespace '{NAMESPACE}' with tags including '{TAG}'" in out
        assert "1 Work Requirement: 412 of 1,000 Tasks done" in out
        assert "2 Worker Pools: 14 Nodes, 30 of 56 Workers claimed" in out
        assert "1 Compute Requirement: 7 of 7 Instances alive" in out
        assert out.index("Work Requirements:") < out.index("Worker Pools:")
        assert out.index("Worker Pools:") < out.index("Compute Requirements:")
        assert "nightly-render" in out and WR_ID in out

    def test_the_scope_columns_are_left_out(self, monkeypatch, capsys):
        _searches(monkeypatch, wrs=[_work_requirement()])
        out, _, _ = _show(capsys)
        header = next(
            line for line in out.splitlines() if "Work Requirement Name" in line
        )
        assert "Namespace" not in header and "Tag" not in header

    def test_an_empty_section_says_so(self, monkeypatch, capsys):
        _searches(monkeypatch)
        out, _, raised = _show(capsys)
        assert raised is None
        for name in ("Work Requirements", "Worker Pools", "Compute Requirements"):
            assert f"No {name}" in out

    def test_active_only_searches_and_says_so(self, monkeypatch, capsys):
        calls = _searches(monkeypatch)
        out, _, _ = _show(capsys, active_only=True)
        assert calls == [(NAMESPACE, TAG, True)] * 3
        assert f"Active items in namespace '{NAMESPACE}'" in out
        assert "No active Worker Pools" in out

    def test_a_null_count_is_said_to_be_unknown(self, monkeypatch, capsys):
        _searches(
            monkeypatch,
            wrs=[_work_requirement(), _work_requirement(totalTaskCount=None)],
        )
        out, _, _ = _show(capsys)
        assert "412 of 1,000 Tasks done (some counts unknown)" not in out
        assert "824 of 1,000 Tasks done (some counts unknown)" in out

    def test_quiet_prints_the_tables_alone(self, monkeypatch, capsys):
        _searches(monkeypatch, wrs=[_work_requirement(healthy=False)])
        out, err, _ = _show(capsys, quiet=True)
        assert "nightly-render" in out
        for left_out in (
            "Items in",
            "Work Requirements:",
            "Tasks done",
            "No Worker Pools",
        ):
            assert left_out not in out
        assert "unhealthy" not in out + err

    def test_quiet_still_says_a_search_failed(self, monkeypatch, capsys):
        _searches(monkeypatch, wps=_forbidden())
        _, err, raised = _show(capsys, quiet=True)
        assert "Cannot list Worker Pools" in err and raised is not None

    def test_the_whole_namespace_names_no_tag(self, monkeypatch, capsys):
        _searches(monkeypatch)
        out, _, _ = _show(capsys, tag="")
        assert f"Items in namespace '{NAMESPACE}'\n" in out


class TestHealth:
    def test_unhealthy_items_are_counted(self, monkeypatch, capsys):
        _searches(
            monkeypatch,
            wrs=[_work_requirement(healthy=False), _work_requirement(healthy=False)],
            wps=[_worker_pool(healthy=False)],
            crs=[_compute_requirement()],
        )
        out, err, raised = _show(capsys)
        assert raised is None
        assert "2 Work Requirements and 1 Worker Pool unhealthy" in out + err

    def test_nothing_is_said_when_all_is_healthy(self, monkeypatch, capsys):
        _searches(monkeypatch, wrs=[_work_requirement()], wps=[_worker_pool()])
        out, err, _ = _show(capsys)
        assert "unhealthy" not in out + err


class TestFailures:
    def test_a_failed_search_leaves_the_others_shown(self, monkeypatch, capsys):
        _searches(
            monkeypatch,
            wrs=[_work_requirement()],
            wps=_forbidden(),
            crs=[_compute_requirement()],
        )
        out, err, raised = _show(capsys)
        assert "Cannot list Worker Pools: 403" in err
        assert "nightly-render" in out and "7 of 7 Instances alive" in out
        assert raised is not None and classify(raised) == ExitCode.PERMISSION

    def test_failures_of_different_kinds_exit_1(self, monkeypatch, capsys):
        _searches(monkeypatch, wps=_forbidden(), crs=RuntimeError("broken"))
        _, _, raised = _show(capsys)
        assert raised is not None and classify(raised) == ExitCode.FAILURE

    def test_a_session_failure_stops_the_command(self, monkeypatch, capsys):
        calls = _searches(monkeypatch, wrs=RequestsConnectionError("reset"))
        with pytest.raises(RequestsConnectionError):
            _show(capsys)
        assert len(calls) == 1


class TestJson:
    def test_one_document(self, monkeypatch, capsys):
        _searches(monkeypatch, wrs=[_work_requirement()], wps=[_worker_pool()])
        out, _, raised = _show(capsys, json_output=True)
        assert raised is None
        document = loads(out)
        assert list(document) == [
            "namespace",
            "tag",
            "workRequirements",
            "workerPools",
            "computeRequirements",
            "failures",
        ]
        assert document["namespace"] == NAMESPACE and document["tag"] == TAG
        assert [wr["id"] for wr in document["workRequirements"]] == [WR_ID]
        assert [wp["id"] for wp in document["workerPools"]] == [WP_ID]
        assert document["computeRequirements"] == []
        assert document["failures"] == []

    def test_a_failure_is_in_the_document(self, monkeypatch, capsys):
        _searches(monkeypatch, crs=_forbidden())
        out, _, raised = _show(capsys, json_output=True)
        document = loads(out)
        assert [f["type"] for f in document["failures"]] == ["compute-requirements"]
        assert raised is not None


class TestWhatIsActive:
    """
    The searches 'yd list --active-only' and 'yd status' share.
    """

    def test_worker_pools_shut_down_or_elsewhere_are_left_out(self, monkeypatch):
        pools = [
            _worker_pool(name="running"),
            _worker_pool(name="shut", status=WorkerPoolStatus.SHUTDOWN),
            _worker_pool(name="gone", status=WorkerPoolStatus.TERMINATED),
            _worker_pool(name="other", namespace=f"{NAMESPACE}-team"),
        ]
        monkeypatch.setattr(
            active_entities, "get_worker_pool_summaries", lambda *a, **k: pools
        )
        found = active_entities.worker_pools(MagicMock(), NAMESPACE, TAG, True)
        assert [p.name for p in found] == ["running"]
        everything = active_entities.worker_pools(MagicMock(), NAMESPACE, TAG, False)
        assert [p.name for p in everything] == ["running", "shut", "gone"]

    def test_finished_work_requirements_are_excluded(self, monkeypatch):
        seen = {}

        def search(client, **kwargs):
            seen.update(kwargs)
            return []

        monkeypatch.setattr(
            active_entities, "get_filtered_work_requirement_summaries", search
        )
        active_entities.work_requirements(MagicMock(), NAMESPACE, TAG, True)
        assert set(seen["exclude_filter"]) == {
            WorkRequirementStatus.COMPLETED,
            WorkRequirementStatus.CANCELLED,
            WorkRequirementStatus.FAILED,
        }
        assert (seen["namespace"], seen["tag"]) == (NAMESPACE, TAG)
