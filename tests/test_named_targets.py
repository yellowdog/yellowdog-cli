"""
Names given to the noun verbs that otherwise take YellowDog IDs ('yd wr show
my-wr', 'yd tg show wr/tg', 'yd wp follow my-pool', 'yd wr compare wr pool'):
accepted as the command line is parsed only where the noun gives them a type,
which the verb records; looked up (utils/named_targets.py) in the configured
namespace or the name's own, every one before anything else, those that find
nothing reported together and exiting with their shared cause.
"""

from types import SimpleNamespace

import pytest

import yellowdog_cli.utils.named_targets as named_targets
from yellowdog_cli.utils.args import CLIParser
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.exit_codes import (
    ExitCode,
    NotFoundError,
    ReportedFailure,
    classify,
)
from yellowdog_cli.utils.work_targets import NamedTarget, TargetNotFound
from yellowdog_cli.utils.ydid_utils import YDIDType

WR_ID = "ydid:workreq:000000:11111111-1111-1111-1111-111111111111"
TG_ID = "ydid:taskgrp:000000:11111111-1111-1111-1111-111111111111:1"
WP_ID = "ydid:wrkrpool:000000:11111111-1111-1111-1111-111111111111"
NODE_ID = "ydid:node:000000:11111111-1111-1111-1111-111111111111:1"


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command, argv, named",
    [
        ("yd workrequirement show", ["my-wr", WR_ID], YDIDType.WORK_REQUIREMENT),
        ("yd workrequirement follow", ["my-wr"], YDIDType.WORK_REQUIREMENT),
        ("yd workrequirement wait", ["ns/my-wr"], YDIDType.WORK_REQUIREMENT),
        ("yd workrequirement compare", ["my-wr", "my-pool"], YDIDType.WORK_REQUIREMENT),
        ("yd taskgroup show", ["my-wr/my-tg"], YDIDType.TASK_GROUP),
        ("yd taskgroup compare", ["my-wr/my-tg", WP_ID], YDIDType.TASK_GROUP),
        ("yd task show", ["my-wr/my-tg/my-task"], YDIDType.TASK),
        ("yd workerpool show", ["my-pool"], YDIDType.WORKER_POOL),
        ("yd workerpool follow", ["my-pool"], YDIDType.WORKER_POOL),
        ("yd workerpool wait", ["my-pool"], YDIDType.WORKER_POOL),
        ("yd computerequirement show", ["my-cr"], YDIDType.COMPUTE_REQUIREMENT),
        ("yd computerequirement follow", ["my-cr"], YDIDType.COMPUTE_REQUIREMENT),
        (
            "yd computerequirement wait",
            ["-n", "ns", "my-cr"],
            YDIDType.COMPUTE_REQUIREMENT,
        ),
    ],
)
def test_a_noun_verb_takes_names_of_its_type(command, argv, named):
    assert CLIParser(command=command, argv=argv).named_target_type == named


def test_a_verb_of_a_noun_without_names_still_takes_ids_alone(capsys):
    with pytest.raises(SystemExit) as raised:
        CLIParser(command="yd node show", argv=["my-node"])
    assert raised.value.code == ExitCode.USAGE
    assert "is a name" in capsys.readouterr().err


def test_namespace_is_hidden_where_there_are_no_names(capsys):
    with pytest.raises(SystemExit) as raised:
        CLIParser(command="yd node show", argv=["-n", "ns", NODE_ID])
    assert raised.value.code == ExitCode.USAGE


def test_the_generic_commands_still_take_ids_alone(capsys):
    assert CLIParser(command="yd-show", argv=[WR_ID]).named_target_type is None
    with pytest.raises(SystemExit):
        CLIParser(command="yd-follow", argv=["my-wr"])


# ---------------------------------------------------------------------------
# The lookups
# ---------------------------------------------------------------------------


def _ctx(namespace: str | None = "ns", named=None) -> RunContext:
    return RunContext(
        args=SimpleNamespace(named_target_type=named),
        config=SimpleNamespace(namespace=namespace),
        client=object(),
    )


def test_an_id_is_left_as_it_is(monkeypatch):
    def never(*_):
        raise AssertionError("looked up")

    monkeypatch.setattr(named_targets, "find_work_requirement_by_name", never)
    assert named_targets.resolve_targets(
        _ctx(), [WR_ID], YDIDType.WORK_REQUIREMENT
    ) == [WR_ID]


def test_nothing_is_looked_up_for_a_command_taking_ids_alone():
    assert named_targets.resolve_targets(_ctx(), ["my-wr"], None) == ["my-wr"]


def test_a_work_requirement_is_found_live_or_finished_in_the_namespace(monkeypatch):
    seen = {}

    def find(client, target, namespace, statuses):
        seen.update(target=target, namespace=namespace)
        return SimpleNamespace(id=WR_ID)

    monkeypatch.setattr(named_targets, "find_work_requirement_by_name", find)
    assert named_targets.resolve_targets(
        _ctx(), ["my-wr", WR_ID], YDIDType.WORK_REQUIREMENT
    ) == [WR_ID, WR_ID]
    assert seen == {"target": "my-wr", "namespace": "ns"}


def test_a_bare_name_with_no_namespace_configured_is_refused(capsys):
    with pytest.raises(ReportedFailure):
        named_targets.resolve_targets(_ctx(""), ["my-wr"], YDIDType.WORK_REQUIREMENT)
    assert "'namespace/my-wr'" in " ".join(capsys.readouterr().err.split())


def test_a_name_with_its_namespace_needs_none_configured(monkeypatch):
    monkeypatch.setattr(
        named_targets,
        "get_worker_pool_id_by_name",
        lambda client, target, namespace: WP_ID if target == "other/pool" else None,
    )
    assert named_targets.resolve_targets(
        _ctx(""), ["other/pool"], YDIDType.WORKER_POOL
    ) == [WP_ID]


def test_every_name_not_found_is_reported_before_failing(monkeypatch, capsys):
    monkeypatch.setattr(named_targets, "get_worker_pool_id_by_name", lambda *a: None)
    with pytest.raises(ReportedFailure) as raised:
        named_targets.resolve_targets(_ctx(), ["a", WP_ID, "b"], YDIDType.WORKER_POOL)
    assert classify(raised.value) == ExitCode.NOT_FOUND
    err = " ".join(capsys.readouterr().err.split())
    assert "Cannot find Worker Pool 'a' in namespace 'ns'" in err
    assert "Cannot find Worker Pool 'b'" in err


def test_a_task_group_is_wr_slash_tg(monkeypatch):
    monkeypatch.setattr(
        named_targets,
        "resolve_named_target",
        lambda client, target, namespace: NamedTarget(
            SimpleNamespace(id=WR_ID), SimpleNamespace(id=TG_ID)
        ),
    )
    assert named_targets.target_id(_ctx(), "wr/tg", YDIDType.TASK_GROUP) == TG_ID


def test_a_work_requirement_is_not_a_task_group(monkeypatch):
    monkeypatch.setattr(
        named_targets,
        "resolve_named_target",
        lambda client, target, namespace: NamedTarget(SimpleNamespace(id=WR_ID)),
    )
    with pytest.raises(NotFoundError, match="not a Task Group"):
        named_targets.target_id(_ctx(), "ns/wr", YDIDType.TASK_GROUP)


def test_a_task_is_found_by_its_exact_name_in_its_task_group(monkeypatch):
    monkeypatch.setattr(
        named_targets,
        "resolve_named_target",
        lambda client, target, namespace: NamedTarget(
            SimpleNamespace(id=WR_ID), SimpleNamespace(id=TG_ID)
        ),
    )
    monkeypatch.setattr(
        named_targets,
        "iterate_tasks_in_task_group",
        lambda client, tg_id, name_contains: iter(
            [SimpleNamespace(name="t10", id="x"), SimpleNamespace(name="t1", id="y")]
        ),
    )
    assert named_targets.target_id(_ctx(), "wr/tg/t1", YDIDType.TASK) == "y"
    with pytest.raises(NotFoundError, match="Cannot find Task 't2'"):
        named_targets.target_id(_ctx(), "wr/tg/t2", YDIDType.TASK)


@pytest.mark.parametrize(
    "target, ydid_type",
    [
        ("a/b/c", YDIDType.WORK_REQUIREMENT),
        ("tg-only", YDIDType.TASK_GROUP),
        ("wr//task", YDIDType.TASK),
        ("ydid:workreq:bad", YDIDType.WORK_REQUIREMENT),
    ],
)
def test_a_name_of_the_wrong_form_is_refused(target, ydid_type):
    with pytest.raises(ValueError):
        named_targets.target_id(_ctx(), target, ydid_type)


def test_compare_resolves_its_work_target_and_pools(monkeypatch):
    monkeypatch.setattr(
        named_targets,
        "resolve_named_target",
        lambda client, target, namespace: NamedTarget(
            SimpleNamespace(id=WR_ID), SimpleNamespace(id=TG_ID)
        ),
    )
    monkeypatch.setattr(named_targets, "get_worker_pool_id_by_name", lambda *a: WP_ID)
    # The registry command, given no type, reads 'wr' or 'wr/tg'
    assert named_targets.resolve_compare_targets(_ctx(), "wr/tg", ["pool", WP_ID]) == (
        TG_ID,
        [WP_ID, WP_ID],
    )


def test_compare_reports_a_missing_work_requirement(monkeypatch):
    def missing(client, target, namespace):
        raise TargetNotFound(f"Work Requirement '{target}'", "work-requirements")

    monkeypatch.setattr(named_targets, "resolve_named_target", missing)
    with pytest.raises(ReportedFailure) as raised:
        named_targets.resolve_compare_targets(_ctx(), "nope", [WP_ID])
    assert classify(raised.value) == ExitCode.NOT_FOUND
