"""
Check that configuration values are the types we expect.
If not, raise an Exception.
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


def _check(thing: _T, type_) -> _T:
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
        raise TypeError(f"Property value '{thing}' should be of type '{_type(type_)}'")
    return thing


def check_int(thing: _T) -> _T:
    return _check(thing, int)


def check_float(thing: _T) -> _T:
    return _check(thing, float)


def check_float_or_int(thing: _T) -> _T:
    """
    For values that should be Floats but for which an Integer is acceptable.
    """
    if thing is None:
        return thing
    try:
        return _check(thing, float)
    except Exception:
        try:
            return _check(thing, int)
        except Exception:
            raise TypeError(
                f"Property value '{thing}' should be of type 'Float' or 'Integer'"
            )


def check_bool(thing: _T) -> _T:
    return _check(thing, bool)


def check_str(thing: _T) -> _T:
    return _check(thing, str)


def check_list(thing: _T) -> _T:
    return _check(thing, list)


def check_dict(thing: _T) -> _T:
    return _check(thing, dict)
