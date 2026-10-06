"""
Check that configuration values are the types we expect.
If not, raise an Exception naming the property, where the caller knows it.

A boolean is never a number here, though Python's bool is a subclass of
int: 'taskCount = true' is a mistake to report, not one Task.
"""

from typing import TypeVar

_T = TypeVar("_T")

# A type as a reader of a TOML or JSON file knows it
_TYPE_NAMES: dict[type, str] = {
    int: "Integer",
    bool: "Boolean",
    str: "String",
    list: "List",
    dict: "Table/Object",
}


def _subject(property_name: str | None) -> str:
    """
    The subject of the error message. A property name is supplied wherever
    the caller knows it, which is almost everywhere: 'Property value '123''
    doesn't say which of a section's properties is the wrong type.
    """
    return "Property" if property_name is None else f"Property '{property_name}'"


def _is(thing: object, types: tuple[type, ...]) -> bool:
    """
    Whether 'thing' is one of 'types', a bool counting only as a bool.
    """
    if isinstance(thing, bool):
        return bool in types
    return isinstance(thing, types)


def _check(
    thing: _T, property_name: str | None, *types: type, wanted: str | None = None
) -> _T:
    """
    'thing' if it is one of 'types'; None passes, as an unset value.
    'wanted' names the types in the error, where their names do not.
    """
    if thing is None or _is(thing, types):
        return thing
    wanted = wanted or _TYPE_NAMES[types[0]]
    raise TypeError(
        f"{_subject(property_name)} value '{thing}' should be of type '{wanted}'"
    )


def check_int(thing: _T, property_name: str | None = None) -> _T:
    return _check(thing, property_name, int)


def check_float_or_int(thing: _T, property_name: str | None = None) -> _T:
    """
    For values that should be Floats but for which an Integer is acceptable.
    """
    return _check(thing, property_name, float, int, wanted="Number")


def check_bool(thing: _T, property_name: str | None = None) -> _T:
    return _check(thing, property_name, bool)


def check_str(thing: _T, property_name: str | None = None) -> _T:
    return _check(thing, property_name, str)


def check_list(thing: _T, property_name: str | None = None) -> _T:
    return _check(thing, property_name, list)


def check_dict(thing: _T, property_name: str | None = None) -> _T:
    return _check(thing, property_name, dict)
