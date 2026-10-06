"""
A value built the first time it is used, so that importing the module
holding it does nothing.

ARGS_PARSER, CONFIG_COMMON, CLIENT and the commands' configuration sections
are each a Lazy: an object that stands in for the value, builds it on first
attribute access, and from then on passes every attribute read and write
through to it. Importing a module that names one -- every command module,
and the shared utilities -- therefore parses no command line, reads no
configuration file and builds no client.

The wrappers build what their command will use before running it
(prepare()), in the order importing once did, so that an argument error or
a broken configuration is still reported, and exits, before the command
starts. A Lazy whose builder raises is not built, and is tried again on
next use.

Only attribute access, truthiness, equality and repr pass through: nothing
in the CLI uses one of these values with isinstance(), dataclasses.asdict()
or the like, which a stand-in cannot satisfy. built() and value() are the
ways to ask about one without building it, or to get the value itself.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, TypeVar, cast

T = TypeVar("T")


class Lazy:
    """
    The stand-in for a value 'builder' makes on first use. 'prepare' says
    whether the wrappers build it before the command runs (see prepare()).
    """

    __slots__ = ("_builder", "_built", "_lock", "_prepare", "_value")
    _builder: Callable[[], Any]
    _built: bool
    _lock: threading.RLock
    _prepare: bool
    _value: Any

    def __init__(self, builder: Callable[[], Any], prepare: bool) -> None:
        object.__setattr__(self, "_builder", builder)
        object.__setattr__(self, "_built", False)
        object.__setattr__(self, "_lock", threading.RLock())
        object.__setattr__(self, "_prepare", prepare)
        object.__setattr__(self, "_value", None)

    def _get(self) -> Any:
        if not self._built:
            with self._lock:
                if not self._built:
                    object.__setattr__(self, "_value", self._builder())
                    object.__setattr__(self, "_built", True)
        return self._value

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._get(), name, value)

    def __delattr__(self, name: str) -> None:
        delattr(self._get(), name)

    def __bool__(self) -> bool:
        return bool(self._get())

    def __eq__(self, other: object) -> bool:
        return self._get() == other

    def __hash__(self) -> int:
        return hash(self._get())

    def __repr__(self) -> str:
        return repr(self._value) if self._built else "<not built yet>"


def lazy(builder: Callable[[], T], prepare: bool = True) -> T:
    """
    A stand-in for what 'builder' returns, typed as it, built on first use.
    """
    return cast(T, Lazy(builder, prepare))


def built(obj: object) -> bool:
    """
    Whether 'obj' is a value, or a Lazy that has been built. A test's
    stand-in (a mock) counts as built.
    """
    return not isinstance(obj, Lazy) or obj._built


def value(obj: T) -> T:
    """
    The value itself: a Lazy's, built if need be, or 'obj' as it is.
    """
    return cast(T, obj._get()) if isinstance(obj, Lazy) else obj


def prepare(*objects: object) -> None:
    """
    Build each Lazy given that is marked to be prepared, in the order
    given; anything else (a value, a test's stand-in) is left alone.
    """
    for obj in objects:
        if isinstance(obj, Lazy) and obj._prepare:
            obj._get()
