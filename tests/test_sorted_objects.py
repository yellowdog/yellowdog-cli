"""
Tests for sorted_objects(), focusing on the '--sort created' behaviour that
orders entities (Work Requirement / Compute Requirement / Worker Pool summaries)
by creation time, earliest first, with --reverse inverting to latest first.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import yellowdog_cli.utils.printing as printing
from yellowdog_cli.utils.printing import sorted_objects

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture()
def args(monkeypatch):
    """A stand-in ARGS_PARSER with controllable sort/reverse, applied to the
    module-level singleton sorted_objects() reads."""
    ns = SimpleNamespace(sort="name", reverse=None)
    monkeypatch.setattr(printing, "ARGS_PARSER", ns)
    return ns


def _summary(name: str, minutes: int):
    """An object shaped like a summary: has 'name' and 'createdTime'."""
    return SimpleNamespace(name=name, createdTime=_T0 + timedelta(minutes=minutes))


def test_default_sorts_by_name(args):
    objs = [_summary("charlie", 0), _summary("alpha", 10), _summary("bravo", 20)]
    assert [o.name for o in sorted_objects(objs)] == ["alpha", "bravo", "charlie"]


def test_sort_created_earliest_first(args):
    args.sort = "created"
    # Name order is the reverse of creation order, to prove it's not name-sorting.
    objs = [_summary("charlie", 20), _summary("bravo", 10), _summary("alpha", 0)]
    assert [o.name for o in sorted_objects(objs)] == ["alpha", "bravo", "charlie"]


def test_sort_created_reverse_latest_first(args):
    args.sort = "created"
    args.reverse = True
    objs = [_summary("alpha", 0), _summary("bravo", 10), _summary("charlie", 20)]
    assert [o.name for o in sorted_objects(objs)] == ["charlie", "bravo", "alpha"]


def test_sort_created_falls_back_to_name_when_no_created_time(args):
    args.sort = "created"
    # Objects without a createdTime attribute -> name-based ordering.
    objs = [SimpleNamespace(name="charlie"), SimpleNamespace(name="alpha")]
    assert [o.name for o in sorted_objects(objs)] == ["alpha", "charlie"]


def test_sort_created_falls_back_on_none_created_time(args):
    args.sort = "created"
    # A None createdTime would break datetime comparison; must fall back safely.
    objs = [
        SimpleNamespace(name="charlie", createdTime=None),
        SimpleNamespace(name="alpha", createdTime=None),
    ]
    assert [o.name for o in sorted_objects(objs)] == ["alpha", "charlie"]


def _status_summary(name: str, status):
    """An object shaped like a summary: has 'name' and 'status'."""
    return SimpleNamespace(name=name, status=status)


def test_sort_status_orders_by_status_name(args):
    args.sort = "status"
    objs = [
        _status_summary("a", "RUNNING"),
        _status_summary("b", "COMPLETED"),
        _status_summary("c", "PENDING"),
    ]
    # Alphabetical by status name: COMPLETED, PENDING, RUNNING
    assert [o.name for o in sorted_objects(objs)] == ["b", "c", "a"]


def test_sort_status_secondary_sort_by_name(args):
    args.sort = "status"
    objs = [
        _status_summary("charlie", "RUNNING"),
        _status_summary("alpha", "RUNNING"),
        _status_summary("bravo", "RUNNING"),
    ]
    # Same status -> ordered by name.
    assert [o.name for o in sorted_objects(objs)] == ["alpha", "bravo", "charlie"]


def test_sort_status_works_with_enum_like_status(args):
    args.sort = "status"

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
    args.sort = "status"
    args.reverse = True
    objs = [
        _status_summary("b", "COMPLETED"),
        _status_summary("a", "RUNNING"),
    ]
    assert [o.name for o in sorted_objects(objs)] == ["a", "b"]


def test_sort_status_falls_back_when_no_status(args):
    args.sort = "status"
    objs = [SimpleNamespace(name="charlie"), SimpleNamespace(name="alpha")]
    assert [o.name for o in sorted_objects(objs)] == ["alpha", "charlie"]


def _ns_summary(name: str, namespace: str):
    """An object shaped like a summary: has 'name' and 'namespace'."""
    return SimpleNamespace(name=name, namespace=namespace)


def test_sort_namespace_orders_by_namespace(args):
    args.sort = "namespace"
    objs = [
        _ns_summary("a", "zeta"),
        _ns_summary("b", "alpha"),
        _ns_summary("c", "mu"),
    ]
    # Alphabetical by namespace: alpha, mu, zeta
    assert [o.name for o in sorted_objects(objs)] == ["b", "c", "a"]


def test_sort_namespace_secondary_sort_by_name(args):
    args.sort = "namespace"
    objs = [
        _ns_summary("charlie", "ns"),
        _ns_summary("alpha", "ns"),
        _ns_summary("bravo", "ns"),
    ]
    # Same namespace -> ordered by name.
    assert [o.name for o in sorted_objects(objs)] == ["alpha", "bravo", "charlie"]


def test_sort_namespace_reverse(args):
    args.sort = "namespace"
    args.reverse = True
    objs = [_ns_summary("a", "alpha"), _ns_summary("b", "zeta")]
    assert [o.name for o in sorted_objects(objs)] == ["b", "a"]


def test_sort_namespace_falls_back_when_no_namespace(args):
    args.sort = "namespace"
    objs = [SimpleNamespace(name="charlie"), SimpleNamespace(name="alpha")]
    assert [o.name for o in sorted_objects(objs)] == ["alpha", "charlie"]


def test_empty_list_unchanged(args):
    args.sort = "created"
    assert sorted_objects([]) == []
