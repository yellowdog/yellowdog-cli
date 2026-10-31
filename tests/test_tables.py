"""
utils/tables.py's choice of table for a numbered listing: by the first
object's type, with strings and attribute definitions (dicts, known only by
the name passed) handled ahead of the SDK types, and a type with no table
listed by name alone.
"""

import dataclasses
import enum
import types
import typing
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from yellowdog_cli.utils import tables


@pytest.mark.parametrize(
    "model_class, builder",
    tables._model_table_builders(),
    ids=lambda value: value.__name__,
)
def test_each_type_gets_its_own_table(model_class, builder):
    first = model_class.__new__(model_class)  # No constructor arguments needed
    assert tables._table_builder(first, None) is builder


def test_no_type_is_shadowed_by_an_earlier_one():
    # isinstance() takes the first match, so a subclass listed after its base
    # would never get its own table
    classes = [model_class for model_class, _ in tables._model_table_builders()]
    for index, later in enumerate(classes):
        assert not any(issubclass(later, earlier) for earlier in classes[:index])


def test_strings_get_the_names_table():
    assert tables._table_builder("a", None) is tables._names_table
    assert tables._names_table(["a", "b"]) == (["#", "Name"], [[1, "a"], [2, "b"]])


def test_attribute_definitions_are_known_by_name():
    first = {"name": "x", "type": "NumericAttributeDefinition"}
    assert (
        tables._table_builder(first, "Attribute Definition")
        is tables.attribute_definitions_table
    )


def test_a_type_without_a_table_gets_none():
    assert tables._table_builder(SimpleNamespace(name="x"), None) is None


# ---------------------------------------------------------------------------
# Each table against the SDK model it reads
# ---------------------------------------------------------------------------


def _sample(annotation, depth: int):
    """
    A value of the annotated type: the first member of a union or an Enum,
    a list of one, an SDK model filled in a level deeper; None for what has
    no obvious sample.
    """
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if origin in (typing.Union, types.UnionType):
        members = [a for a in args if a is not type(None)]
        return _sample(members[0], depth) if members else None
    if origin in (list, set, frozenset, tuple):
        item = _sample(args[0], depth) if args else None
        return [] if item is None else [item]
    if origin is dict:
        return {}
    samples = {
        str: "text",
        bool: True,
        int: 1,
        float: 1.5,
        datetime: datetime(2026, 1, 1, tzinfo=timezone.utc),
        timedelta: timedelta(minutes=1),
    }
    if annotation in samples:
        return samples[annotation]
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return next(iter(annotation))
    if isinstance(annotation, type) and depth < 3:
        model = _concrete(annotation)
        return None if model is None else _filled(model, depth + 1)
    return None


def _concrete(model_class: type) -> type | None:
    """
    The class itself if it is a dataclass, else its first concrete dataclass
    subclass by name: an Instance is an AwsInstance or another provider's.
    """
    if dataclasses.is_dataclass(model_class) and not model_class.__subclasses__():
        return model_class
    leaves = []
    pending = list(model_class.__subclasses__())
    while pending:
        subclass = pending.pop()
        if subclass.__subclasses__():
            pending.extend(subclass.__subclasses__())
        elif dataclasses.is_dataclass(subclass):
            leaves.append(subclass)
    if leaves:
        return sorted(leaves, key=lambda c: c.__name__)[0]
    return model_class if dataclasses.is_dataclass(model_class) else None


def _filled(model_class: type, depth: int = 0):
    """
    An instance with every field the dataclass declares set to a sample:
    nothing else is defined on it, so a table reading a field the SDK has
    renamed or dropped raises AttributeError.
    """
    instance = object.__new__(model_class)
    try:
        hints = typing.get_type_hints(model_class)
    except Exception:  # A forward reference the SDK cannot resolve
        hints = {}
    for field in dataclasses.fields(model_class):
        object.__setattr__(
            instance, field.name, _sample(hints.get(field.name, field.type), depth)
        )
    return instance


@pytest.mark.parametrize(
    "model_class, builder",
    tables._model_table_builders(),
    ids=lambda value: value.__name__,
)
def test_each_table_reads_only_what_its_sdk_model_has(model_class, builder):
    model = _concrete(model_class)
    assert model is not None, f"no concrete SDK model for {model_class.__name__}"
    headers, rows = builder([_filled(model)])
    assert len(rows) == 1
    assert len(rows[0]) == len(headers)


# ---------------------------------------------------------------------------
# Text that looks like a number
# ---------------------------------------------------------------------------


def test_a_numbered_list_prints_number_like_text_as_written(capsys):
    # Read as numbers, '1.10' printed as 1.1, '0042' as 42 and '1e3' as 1000
    from yellowdog_cli.utils.tables import print_numbered_object_list

    print_numbered_object_list(None, ["1.10", "0042", "1e3"])  # type: ignore[arg-type]
    out = capsys.readouterr().out
    for name in ("1.10", "0042", "1e3"):
        assert f" {name} " in out


def test_only_the_columns_parsing_would_rewrite_are_left_unparsed():
    from yellowdog_cli.utils.tables import _rewritten_columns

    table = [[9, "1.10", "5", "007", 3.5], [10, "x", "12", "a", 2]]
    # The '#', a count written as text and real numbers stay numbers
    assert _rewritten_columns(table) == [1, 3]


def test_a_task_group_status_reads_the_same_listed_and_followed(monkeypatch):
    # Starved and waiting on a dependency at once: both, in one order
    import json

    import yellowdog_cli.utils.event_printing as event_printing
    from yellowdog_cli.utils.output_style import task_group_status_text
    from yellowdog_cli.utils.ydid_utils import YDIDType

    assert task_group_status_text("RUNNING", True, True) == "RUNNING/STARVED/WAITING"
    printed: list[str] = []
    monkeypatch.setattr(
        event_printing, "print_info", lambda message, **kwargs: printed.append(message)
    )
    task_group = {
        "name": "tg",
        "status": "RUNNING",
        "starved": True,
        "waitingOnDependency": True,
    }
    event = {"name": "wr", "status": "RUNNING", "taskGroups": [task_group]}
    event_printing.print_event("data:" + json.dumps(event), YDIDType.WORK_REQUIREMENT)
    assert "[RUNNING/STARVED/WAITING]" in "".join(printed)


@pytest.mark.parametrize(
    "type_name, count, expected",
    [
        ("Worker Pool", 1, "Worker Pool"),
        ("Worker Pool", 3, "Worker Pools"),
        ("Namespace Policy", 2, "Namespace Policies"),
        ("Machine Image Family", 2, "Machine Image Families"),
        ("Key", 2, "Keys"),
        ("AWS Availability Zones", 2, "AWS Availability Zones"),
    ],
)
def test_a_type_is_named_for_its_count(type_name, count, expected):
    from yellowdog_cli.utils.tables import counted

    assert counted(type_name, count) == expected


@pytest.mark.parametrize(
    "showing_all, count, expected",
    [
        (False, 2, "2 matching Groups:"),
        (False, 1, "1 matching Group:"),
        (True, 2, "All 2 Groups:"),
    ],
)
def test_the_heading_counts_what_was_found(showing_all, count, expected):
    from types import SimpleNamespace
    from unittest.mock import patch

    from yellowdog_cli.utils import tables

    groups = [SimpleNamespace(name=f"g{n}") for n in range(count)]
    with (
        patch.object(tables, "print_info") as info,
        patch.object(tables, "print_table_core"),
        patch.object(tables, "_table_builder", return_value=None),
    ):
        tables.print_numbered_object_list(
            None, groups, object_type_name="Group", showing_all=showing_all
        )
    assert info.call_args.args[0] == expected
