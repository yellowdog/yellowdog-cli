"""
The shape of yd-show's output, and its exit status.

Every branch of resolve_details() used to print its own object, and only ten of
the nineteen passed on the JSON array's indentation and separating commas. The
other nine produced an array whose elements ran together without commas: not
parseable, for Compute Requirements, Compute Sources, Nodes, Workers, Work
Requirements, Task Groups, Tasks, Image Groups and Images. Nothing caught it,
because the tests asserted the arguments handed to print_yd_object() rather
than what came out.

These tests therefore parse the output. Resolution and printing are now
separate, so the framing is applied in one place and cannot be forgotten in a
branch -- but the guard is 'json.loads() succeeds', which holds however the
code is arranged.
"""

from json import loads
from unittest.mock import MagicMock, patch

import pytest

import yellowdog_cli.show as show_module
import yellowdog_cli.utils.printing as printing_module
from yellowdog_cli.show import show_ydids

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
        return yd_object.payload


class _FakeConfiguredWorkerPool(_Obj):
    """Stands in for ConfiguredWorkerPool, which show.py isinstance()-checks."""


def _args(**overrides) -> MagicMock:
    args = MagicMock()
    args.strip_ids = False
    args.substitute_ids = False
    args.show_token = False
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
]


def _names(parsed) -> list[str]:
    """
    The 'name' of each object in the parsed output. Compared rather than the
    whole payload because several branches legitimately add a 'resource' field
    of their own; what is under test here is the framing around the objects.
    """
    return [item["name"] for item in (parsed if isinstance(parsed, list) else [parsed])]


def _run(
    ydids: list[str], client: MagicMock, args: MagicMock, capsys
) -> tuple[int, str]:
    with (
        patch.object(show_module, "ARGS_PARSER", args),
        patch.object(show_module, "CLIENT", client),
        patch.object(show_module, "ConfiguredWorkerPool", _FakeConfiguredWorkerPool),
        patch.object(printing_module, "ARGS_PARSER", args),
        patch.object(printing_module, "Json", _StubJson),
        patch.object(show_module, "print_error"),
    ):
        failures = show_ydids(ydids)
    return failures, capsys.readouterr().out


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
        failures, output = _run(
            ["not-a-ydid", "also-not"], MagicMock(), _args(), capsys
        )
        assert failures == 2
        assert loads(output) == []

    def test_no_ids_produces_no_output(self, capsys):
        failures, output = _run([], MagicMock(), _args(), capsys)
        assert failures == 0
        assert output == ""
