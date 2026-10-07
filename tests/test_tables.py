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
