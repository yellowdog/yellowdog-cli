"""
utils/tables.py's choice of table for a numbered listing: by the first
object's type, with strings and attribute definitions (dicts, known only by
the name passed) handled ahead of the SDK types, and a type with no table
listed by name alone.
"""

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
