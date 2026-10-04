"""
Unit tests for nodeaction.py (yd-nodeaction): targeting and failure handling,
against a fake Platform. Parsing the specification is tested in
test_nodeaction_parsing.py, and the '--json' records in test_json_output.py.

Covers:
  - a faulty specification failing before anything is looked up
  - the Worker Pool: by name or YDID, not found (NotFoundError), finished
  - nodes given with --node: each once, all in one Worker Pool (theirs, or
    the one --worker-pool names), finished ones skipped and recorded
  - a session failure stopping the per-node submissions
  - --follow's --timeout, and --status's failures
  - the command-line rules (check_node_action_args, --node / --all-nodes)
"""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from requests import HTTPError, Response
from yellowdog_client.model import (
    NodeActionQueueStatus,
    NodeStatus,
    WorkerPoolStatus,
)

import yellowdog_cli.nodeaction as na_module
from yellowdog_cli.utils.args import CLIParser
from yellowdog_cli.utils.exit_codes import (
    NotFoundError,
    ReportedFailure,
    classify,
)
from yellowdog_cli.utils.settings import ExitCode

WP_A = "ydid:wrkrpool:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
WP_B = "ydid:wrkrpool:000000:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
NODE_1 = "ydid:node:000000:11111111-1111-1111-1111-111111111111"
NODE_2 = "ydid:node:000000:22222222-2222-2222-2222-222222222222"
NODE_3 = "ydid:node:000000:33333333-3333-3333-3333-333333333333"


def _http_error(status_code: int) -> HTTPError:
    response = Response()
    response.status_code = status_code
    return HTTPError(f"{status_code} Client Error", response=response)


def _pool(id_=WP_A, name="wp-a", status=WorkerPoolStatus.RUNNING) -> Any:
    return SimpleNamespace(id=id_, name=name, namespace="ns", status=status)


def _node(id_, pool=WP_A, status=NodeStatus.RUNNING) -> Any:
    return SimpleNamespace(id=id_, workerPoolId=pool, status=status)


class FakePlatform:
    def __init__(self):
        self.pools: dict[str, Any] = {WP_A: _pool()}
        self.nodes: dict[str, Any] = {
            NODE_1: _node(NODE_1),
            NODE_2: _node(NODE_2),
        }
        self.submissions: list[tuple] = []
        self.records: list[dict] = []
        self.failures: dict[str, Exception] = {}
        self.spec = ""  # the specification file, written by the fixture

        client = MagicMock()
        pools = client.worker_pool_client
        pools.get_worker_pool_by_id.side_effect = lambda worker_pool_id: self._get(
            self.pools, worker_pool_id
        )
        pools.get_node_by_id.side_effect = lambda node_id: self._get(
            self.nodes, node_id
        )
        pools.get_worker_pool_by_name.side_effect = self._by_name
        pools.get_nodes.side_effect = lambda search: SimpleNamespace(
            list_all=lambda: [
                n for n in self.nodes.values() if n.workerPoolId == search.workerPoolId
            ]
        )
        pools.add_node_actions_for_node_by_id.side_effect = self._submit
        self.client = client

    @staticmethod
    def _get(table, key):
        if key not in table:
            raise _http_error(404)
        return table[key]

    def _by_name(self, namespace, name):
        for pool in self.pools.values():
            if (pool.namespace, pool.name) == (namespace, name):
                return pool
        raise _http_error(404)

    def _submit(self, wp_id, node_id, *actions):
        if "submit" in self.failures:
            raise self.failures["submit"]
        self.submissions.append((wp_id, node_id))


@pytest.fixture
def platform(monkeypatch, tmp_path):
    fake = FakePlatform()
    spec = tmp_path / "actions.json"
    spec.write_text(json.dumps({"actions": [{"type": "runCommand", "path": "ls"}]}))
    fake.spec = str(spec)
    monkeypatch.setattr(na_module, "CLIENT", fake.client)
    monkeypatch.setattr(
        na_module,
        "CONFIG_COMMON",
        SimpleNamespace(namespace="ns", name_tag=None, url="https://api.x"),
    )
    monkeypatch.setattr(na_module, "confirmed", lambda message: True)
    monkeypatch.setattr(na_module, "check_specification", lambda f, spec, *a: spec)
    monkeypatch.setattr(na_module, "record", lambda row: fake.records.append(dict(row)))
    return fake


def _submit(monkeypatch, platform, nodes=None, worker_pool=None, **extra):
    args = dict(
        node_action_spec=platform.spec,
        content_path=None,
        node_ids=nodes,
        worker_pool_name=worker_pool,
        all_nodes=False,
        follow=False,
        timeout=None,
        validate=False,
        status=False,
        details=False,
        json_output=False,
    )
    args.update(extra)
    monkeypatch.setattr(na_module, "ARGS_PARSER", SimpleNamespace(**args))
    na_module._submit_actions()


class TestSpecification:
    def test_a_faulty_one_fails_before_anything_is_looked_up(
        self, platform, monkeypatch, tmp_path
    ):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"actions": [{"type": "nope"}]}))
        platform.spec = str(bad)
        with pytest.raises(ReportedFailure) as raised:
            _submit(monkeypatch, platform, nodes=[NODE_1])
        assert classify(raised.value) == ExitCode.FAILURE
        platform.client.worker_pool_client.get_node_by_id.assert_not_called()

    def test_one_with_neither_actions_nor_groups_fails(
        self, platform, monkeypatch, tmp_path
    ):
        empty = tmp_path / "empty.json"
        empty.write_text("{}")
        platform.spec = str(empty)
        with pytest.raises(ReportedFailure):
            _submit(monkeypatch, platform, nodes=[NODE_1])

    def test_content_files_are_read_as_utf_8(self, platform, tmp_path):
        content = tmp_path / "script.sh"
        content.write_bytes("echo 'café ✓'\n".encode())
        action: Any = na_module._parse_action(
            {"type": "writeFile", "path": "/tmp/x", "contentFile": "script.sh"},
            str(tmp_path),
        )
        assert action.content == "echo 'café ✓'\n"


class TestWorkerPool:
    def test_by_name(self, platform, monkeypatch):
        monkeypatch.setattr(na_module, "_choose_nodes", lambda pool: [NODE_1])
        _submit(monkeypatch, platform, worker_pool="wp-a")
        assert platform.submissions == [(WP_A, NODE_1)]

    @pytest.mark.parametrize("worker_pool", ["nope", WP_B])
    def test_not_found(self, platform, monkeypatch, worker_pool):
        with pytest.raises(NotFoundError):
            _submit(monkeypatch, platform, worker_pool=worker_pool)

    def test_a_finished_pool_is_refused(self, platform, monkeypatch):
        platform.pools[WP_A].status = WorkerPoolStatus.SHUTDOWN
        with pytest.raises(ValueError, match="is SHUTDOWN"):
            _submit(monkeypatch, platform, worker_pool=WP_A)

    def test_choosing_offers_only_running_nodes(self, platform, monkeypatch):
        platform.nodes[NODE_3] = _node(NODE_3, status=NodeStatus.TERMINATED)
        offered = []

        def select(client, objects, **kwargs):
            offered.extend(o.id for o in objects)
            return objects

        monkeypatch.setattr(na_module, "select", select)
        _submit(monkeypatch, platform, worker_pool="wp-a")
        assert offered == [NODE_1, NODE_2]


class TestNodes:
    def test_the_pool_is_theirs(self, platform, monkeypatch):
        _submit(monkeypatch, platform, nodes=[NODE_1, NODE_2])
        assert platform.submissions == [(WP_A, NODE_1), (WP_A, NODE_2)]

    def test_a_repeated_node_is_sent_the_actions_once(self, platform, monkeypatch):
        _submit(monkeypatch, platform, nodes=[NODE_1, NODE_1])
        assert platform.submissions == [(WP_A, NODE_1)]

    def test_a_node_that_does_not_exist(self, platform, monkeypatch):
        with pytest.raises(NotFoundError):
            _submit(monkeypatch, platform, nodes=[NODE_1, NODE_3])
        assert platform.submissions == []

    def test_nodes_in_two_pools_are_refused(self, platform, monkeypatch):
        platform.pools[WP_B] = _pool(WP_B, "wp-b")
        platform.nodes[NODE_3] = _node(NODE_3, WP_B)
        with pytest.raises(ValueError, match="2 Worker Pools"):
            _submit(monkeypatch, platform, nodes=[NODE_1, NODE_3])
        assert platform.submissions == []

    def test_a_node_outside_the_named_pool_is_refused(self, platform, monkeypatch):
        platform.pools[WP_B] = _pool(WP_B, "wp-b")
        with pytest.raises(ValueError, match="not in Worker Pool"):
            _submit(monkeypatch, platform, nodes=[NODE_1], worker_pool="wp-b")

    def test_a_finished_node_is_skipped_and_recorded(self, platform, monkeypatch):
        platform.nodes[NODE_2].status = NodeStatus.TERMINATED
        _submit(monkeypatch, platform, nodes=[NODE_1, NODE_2])
        assert platform.submissions == [(WP_A, NODE_1)]
        assert [(r["nodeId"], r["outcome"]) for r in platform.records] == [
            (NODE_2, "skipped"),
            (NODE_1, "submitted"),
        ]

    def test_a_session_failure_stops_the_submissions(self, platform, monkeypatch):
        platform.failures["submit"] = _http_error(401)
        with pytest.raises(ReportedFailure) as raised:
            _submit(monkeypatch, platform, nodes=[NODE_1, NODE_2])
        assert classify(raised.value) == ExitCode.AUTHENTICATION
        assert [(r["nodeId"], r["outcome"]) for r in platform.records] == [
            (NODE_1, "failed"),
            (NODE_2, "skipped"),
        ]
        assert platform.records[1]["error"].startswith("not attempted:")

    def test_another_failure_carries_on(self, platform, monkeypatch):
        platform.failures["submit"] = _http_error(500)
        _submit(monkeypatch, platform, nodes=[NODE_1, NODE_2])
        assert [r["outcome"] for r in platform.records] == ["failed", "failed"]


class TestFollow:
    def test_a_timeout_fails_with_the_latest_queues(self, platform, monkeypatch):
        platform.client.worker_pool_client.get_node_actions_by_id.return_value = (
            SimpleNamespace(
                status=NodeActionQueueStatus.EXECUTING,
                waiting=[],
                executing=None,
                failed=None,
            )
        )
        monkeypatch.setattr(na_module.time, "sleep", lambda seconds: None)
        clock = iter(range(0, 1000, 10))
        monkeypatch.setattr(na_module.time, "monotonic", lambda: next(clock))
        monkeypatch.setattr(na_module, "print_node_action_queue_table", lambda r: None)
        with pytest.raises(ReportedFailure) as raised:
            _submit(monkeypatch, platform, nodes=[NODE_1], follow=True, timeout=25)
        assert isinstance(raised.value.__cause__, TimeoutError)
        assert classify(raised.value) == ExitCode.FAILURE


class TestStatus:
    def _status(self, monkeypatch, nodes):
        monkeypatch.setattr(
            na_module,
            "ARGS_PARSER",
            SimpleNamespace(
                node_ids=nodes,
                worker_pool_name=None,
                all_nodes=False,
                follow=False,
                timeout=None,
                details=False,
                json_output=True,
                status=True,
            ),
        )
        monkeypatch.setattr(na_module, "json_requested", lambda: True)
        na_module._show_status()

    def test_a_queue_that_cannot_be_fetched_fails_the_run(self, platform, monkeypatch):
        get = platform.client.worker_pool_client.get_node_actions_by_id
        snapshot = SimpleNamespace(
            status=NodeActionQueueStatus.EMPTY, waiting=[], executing=None, failed=None
        )
        get.side_effect = lambda node_id: (
            snapshot if node_id == NODE_1 else (_ for _ in ()).throw(_http_error(404))
        )
        with pytest.raises(ReportedFailure):
            self._status(monkeypatch, [NODE_1, NODE_2, NODE_1])
        assert [r["nodeId"] for r in platform.records] == [NODE_1]


class TestCommandLine:
    @pytest.mark.parametrize(
        "argv, message",
        [
            ([], "--actions is required"),
            (["--status", "-S", "a.json"], "--actions cannot be used with --status"),
            (["-S", "a.json", "--node", "nope"], "not a YellowDog Node ID"),
            (
                ["-S", "a.json", "--worker-pool", "ydid:node:000000:x"],
                "not a YellowDog Worker Pool ID",
            ),
            (["-S", "a.json", "--timeout", "30"], "--timeout needs --follow"),
            (
                ["-S", "a.json", "--node", NODE_1, "--all-nodes"],
                "not allowed with argument",
            ),
        ],
    )
    def test_refused_as_parsed(self, argv, message, capsys):
        with pytest.raises(SystemExit) as raised:
            CLIParser(command="yd-nodeaction", argv=argv)
        assert raised.value.code == 2
        assert message in capsys.readouterr().err

    def test_a_follow_timeout(self):
        args = CLIParser(
            command="yd-nodeaction",
            argv=["-S", "a.json", "--follow", "--timeout", "30"],
        )
        assert args.timeout == 30
