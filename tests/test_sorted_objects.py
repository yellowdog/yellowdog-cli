"""
Tests for sorted_objects() and the '--sort' keys it reads: each key alone
('created' orders by creation time, earliest first, with --reverse inverting
to latest first), several keys in turn, a key the objects lack passed over,
and the parsing of a comma-separated '--sort' value.
"""

from argparse import ArgumentTypeError
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from yellowdog_cli.utils import output_settings
from yellowdog_cli.utils.command_registry import entity_sort_keys
from yellowdog_cli.utils.tables import sorted_objects

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture()
def args():
    """
    The output settings sorted_objects() reads, sorting by name, for a test
    to set its sort and reverse on (restored after it by conftest).
    """
    output_settings.configure_output(SimpleNamespace(sort=("name",), reverse=None))
    return output_settings.OUTPUT


def _summary(name: str, minutes: int):
    """
    An object shaped like a summary: has 'name' and 'createdTime'.
    """
    return SimpleNamespace(name=name, createdTime=_T0 + timedelta(minutes=minutes))


def test_default_sorts_by_name(args):
    objs = [_summary("charlie", 0), _summary("alpha", 10), _summary("bravo", 20)]
    assert [o.name for o in sorted_objects(objs)] == ["alpha", "bravo", "charlie"]


def test_sort_created_earliest_first(args):
    args.sort = ("created",)
    # Name order is the reverse of creation order, to prove it's not name-sorting.
    objs = [_summary("charlie", 20), _summary("bravo", 10), _summary("alpha", 0)]
    assert [o.name for o in sorted_objects(objs)] == ["alpha", "bravo", "charlie"]


def test_sort_created_reverse_latest_first(args):
    args.sort = ("created",)
    args.reverse = True
    objs = [_summary("alpha", 0), _summary("bravo", 10), _summary("charlie", 20)]
    assert [o.name for o in sorted_objects(objs)] == ["charlie", "bravo", "alpha"]


def test_sort_created_falls_back_to_name_when_no_created_time(args):
    args.sort = ("created",)
    # Objects without a createdTime attribute -> name-based ordering.
    objs = [SimpleNamespace(name="charlie"), SimpleNamespace(name="alpha")]
    assert [o.name for o in sorted_objects(objs)] == ["alpha", "charlie"]


def test_sort_created_falls_back_on_none_created_time(args):
    args.sort = ("created",)
    # A None createdTime would break datetime comparison; must fall back safely.
    objs = [
        SimpleNamespace(name="charlie", createdTime=None),
        SimpleNamespace(name="alpha", createdTime=None),
    ]
    assert [o.name for o in sorted_objects(objs)] == ["alpha", "charlie"]


def _status_summary(name: str, status):
    """
    An object shaped like a summary: has 'name' and 'status'.
    """
    return SimpleNamespace(name=name, status=status)


def test_sort_status_orders_by_status_name(args):
    args.sort = ("status",)
    objs = [
        _status_summary("a", "RUNNING"),
        _status_summary("b", "COMPLETED"),
        _status_summary("c", "PENDING"),
    ]
    # Alphabetical by status name: COMPLETED, PENDING, RUNNING
    assert [o.name for o in sorted_objects(objs)] == ["b", "c", "a"]


def test_sort_status_secondary_sort_by_name(args):
    args.sort = ("status",)
    objs = [
        _status_summary("charlie", "RUNNING"),
        _status_summary("alpha", "RUNNING"),
        _status_summary("bravo", "RUNNING"),
    ]
    # Same status -> ordered by name.
    assert [o.name for o in sorted_objects(objs)] == ["alpha", "bravo", "charlie"]


def test_sort_status_works_with_enum_like_status(args):
    args.sort = ("status",)

    class _Status:
        def __init__(self, name):
            self._name = name

        def __str__(self):
            return self._name

    objs = [
        _status_summary("a", _Status("RUNNING")),
        _status_summary("b", _Status("COMPLETED")),
    ]
    assert [o.name for o in sorted_objects(objs)] == ["b", "a"]


def test_sort_status_reverse(args):
    args.sort = ("status",)
    args.reverse = True
    objs = [
        _status_summary("b", "COMPLETED"),
        _status_summary("a", "RUNNING"),
    ]
    assert [o.name for o in sorted_objects(objs)] == ["a", "b"]


def test_sort_status_falls_back_when_no_status(args):
    args.sort = ("status",)
    objs = [SimpleNamespace(name="charlie"), SimpleNamespace(name="alpha")]
    assert [o.name for o in sorted_objects(objs)] == ["alpha", "charlie"]


def _ns_summary(name: str, namespace: str):
    """
    An object shaped like a summary: has 'name' and 'namespace'.
    """
    return SimpleNamespace(name=name, namespace=namespace)


def test_sort_namespace_orders_by_namespace(args):
    args.sort = ("namespace",)
    objs = [
        _ns_summary("a", "zeta"),
        _ns_summary("b", "alpha"),
        _ns_summary("c", "mu"),
    ]
    # Alphabetical by namespace: alpha, mu, zeta
    assert [o.name for o in sorted_objects(objs)] == ["b", "c", "a"]


def test_sort_namespace_secondary_sort_by_name(args):
    args.sort = ("namespace",)
    objs = [
        _ns_summary("charlie", "ns"),
        _ns_summary("alpha", "ns"),
        _ns_summary("bravo", "ns"),
    ]
    # Same namespace -> ordered by name.
    assert [o.name for o in sorted_objects(objs)] == ["alpha", "bravo", "charlie"]


def test_sort_namespace_reverse(args):
    args.sort = ("namespace",)
    args.reverse = True
    objs = [_ns_summary("a", "alpha"), _ns_summary("b", "zeta")]
    assert [o.name for o in sorted_objects(objs)] == ["b", "a"]


def test_sort_namespace_falls_back_when_no_namespace(args):
    args.sort = ("namespace",)
    objs = [SimpleNamespace(name="charlie"), SimpleNamespace(name="alpha")]
    assert [o.name for o in sorted_objects(objs)] == ["alpha", "charlie"]


def test_empty_list_unchanged(args):
    args.sort = ("created",)
    assert sorted_objects([]) == []


def _entity(name: str, status: str, minutes: int | None, namespace: str = "ns"):
    """
    An object shaped like a summary, with every attribute a '--sort' key reads.
    """
    return SimpleNamespace(
        name=name,
        status=status,
        namespace=namespace,
        createdTime=None if minutes is None else _T0 + timedelta(minutes=minutes),
    )


def test_several_keys_sort_by_each_in_turn(args):
    args.sort = ("status", "created")
    objs = [
        _entity("a", "RUNNING", 30),
        _entity("b", "COMPLETED", 20),
        _entity("c", "RUNNING", 10),
        _entity("d", "COMPLETED", 40),
    ]
    assert [o.name for o in sorted_objects(objs)] == ["b", "d", "c", "a"]


def test_the_name_breaks_a_tie_left_by_every_key(args):
    args.sort = ("namespace", "status")
    objs = [
        _entity("charlie", "RUNNING", 0, "ns-b"),
        _entity("bravo", "RUNNING", 0, "ns-a"),
        _entity("alpha", "RUNNING", 0, "ns-b"),
    ]
    assert [o.name for o in sorted_objects(objs)] == ["bravo", "alpha", "charlie"]


def test_name_first_makes_later_keys_tie_breakers(args):
    args.sort = ("name", "created")
    objs = [_entity("b", "X", 10), _entity("a", "X", 30), _entity("a", "X", 20)]
    assert [o.createdTime.minute for o in sorted_objects(objs)] == [20, 30, 10]


def test_reverse_inverts_the_whole_order(args):
    args.sort = ("status", "created")
    args.reverse = True
    objs = [
        _entity("a", "RUNNING", 30),
        _entity("b", "COMPLETED", 20),
        _entity("c", "RUNNING", 10),
    ]
    assert [o.name for o in sorted_objects(objs)] == ["a", "c", "b"]


def test_a_missing_created_time_sorts_first_among_the_rest(args):
    # Mixed None and datetime values must never be compared with each other
    args.sort = ("created",)
    objs = [_entity("a", "X", 10), _entity("b", "X", None), _entity("c", "X", 5)]
    assert [o.name for o in sorted_objects(objs)] == ["b", "c", "a"]


def test_a_key_the_objects_lack_is_passed_over(args):
    args.sort = ("created", "status")
    objs = [
        SimpleNamespace(name="charlie", status="A"),
        SimpleNamespace(name="alpha", status="B"),
        SimpleNamespace(name="bravo", status="A"),
    ]
    assert [o.name for o in sorted_objects(objs)] == ["bravo", "charlie", "alpha"]


def test_no_sort_setting_sorts_by_name(args):
    args.sort = None
    objs = [SimpleNamespace(name="b"), SimpleNamespace(name="a")]
    assert [o.name for o in sorted_objects(objs)] == ["a", "b"]


@pytest.mark.parametrize(
    "text, keys",
    [
        ("name", ("name",)),
        ("status,created", ("status", "created")),
        (" namespace , name ", ("namespace", "name")),
    ],
)
def test_a_sort_value_is_keys_separated_by_commas(text, keys):
    assert entity_sort_keys(text) == keys


@pytest.mark.parametrize(
    "text, message",
    [
        ("size", "invalid sort key 'size'"),
        ("name,", "empty sort key"),
        ("", "empty sort key"),
        ("status,name,status", "sort key given more than once: status"),
    ],
)
def test_a_bad_sort_value_is_refused(text, message):
    with pytest.raises(ArgumentTypeError, match=message):
        entity_sort_keys(text)
