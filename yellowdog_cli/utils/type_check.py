"""
Check that configuration values are the types we expect.
If not, raise an Exception naming the property, where the caller knows it.
"""

from typing import TypeVar

_T = TypeVar("_T")


def _type(type_) -> str:
    if "int" in f"{type_}":
        return "Integer"
    if "float" in f"{type_}":
        return "Float"
    if "bool" in f"{type_}":
        return "Boolean"
    if "str" in f"{type_}":
        return "String"
    if "list" in f"{type_}":
        return "List"
    if "dict" in f"{type_}":
        return "Dict"
    raise TypeError(f"Unhandled type '{type_}'")


def _subject(property_name: str | None) -> str:
    """
    The subject of the error message. A property name is supplied wherever
    the caller knows it, which is almost everywhere: 'Property value '123''
    doesn't say which of a section's properties is the wrong type.
    """
    return "Property" if property_name is None else f"Property '{property_name}'"


def _check(thing: _T, type_, property_name: str | None = None) -> _T:
    """
    If None is passed in, just return None.
    """
    if thing is None:
        return thing

    # Bool is a subtype of int, so test for exact match in that case
    is_required_type = (
        type(thing) is type_ if type_ is bool else isinstance(thing, type_)
    )
    if not is_required_type:
        raise TypeError(
            f"{_subject(property_name)} value '{thing}'"
            f" should be of type '{_type(type_)}'"
        )
    return thing


def check_int(thing: _T, property_name: str | None = None) -> _T:
    return _check(thing, int, property_name)


def check_float(thing: _T, property_name: str | None = None) -> _T:
    return _check(thing, float, property_name)


def check_float_or_int(thing: _T, property_name: str | None = None) -> _T:
    """
    For values that should be Floats but for which an Integer is acceptable.
    """
    if thing is None:
        return thing
    try:
        return _check(thing, float, property_name)
    except Exception:
        try:
            return _check(thing, int, property_name)
        except Exception:
            raise TypeError(
                f"{_subject(property_name)} value '{thing}'"
                f" should be of type 'Float' or 'Integer'"
            )


def check_bool(thing: _T, property_name: str | None = None) -> _T:
    return _check(thing, bool, property_name)


def check_str(thing: _T, property_name: str | None = None) -> _T:
    return _check(thing, str, property_name)


def check_list(thing: _T, property_name: str | None = None) -> _T:
    return _check(thing, list, property_name)


def check_dict(thing: _T, property_name: str | None = None) -> _T:
    return _check(thing, dict, property_name)
