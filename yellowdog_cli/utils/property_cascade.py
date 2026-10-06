"""
The inheritance of a Work Requirement property: a property set at a lower
level overrides its setting at the levels above, so a Task takes it from
itself, else from its Task Group, else from the Work Requirement, else from
the configuration file:

    Task > Task Group > Work Requirement > TOML configuration

Which of those levels a property may be set at is the dictionary's
(specs.properties.WORK_REQUIREMENT_PROPERTIES, held to README.md's table),
so a level is consulted only for a property the dictionary allows there.
The configuration's value is the caller's to give, as the default, since
it comes from the run's ConfigWorkRequirement, re-substituted as the run
proceeds.
"""

from collections.abc import Callable
from typing import Any, TypeVar

from yellowdog_cli.utils.specs.properties import (
    WORK_REQUIREMENT_PROPERTIES,
    Level,
    Property,
)

_PROPERTIES: dict[str, Property] = {
    prop.name: prop for prop in WORK_REQUIREMENT_PROPERTIES
}

T = TypeVar("T")


class Cascade:
    """
    The levels a property is looked up through, from the lowest: a Task (if
    any), its Task Group (if any), and the Work Requirement. Each level is
    the specification's dictionary itself, not a copy, so a substitution
    made in it after the Cascade is built is seen.
    """

    def __init__(
        self,
        work_requirement: dict,
        task_group: dict | None = None,
        task: dict | None = None,
    ):
        self._levels: tuple[tuple[Level, dict | None], ...] = (
            (Level.TASK, task),
            (Level.TASK_GROUP, task_group),
            (Level.WORK_REQUIREMENT, work_requirement),
        )

    def get(self, name: str, default: Any = None) -> Any:
        """
        The property's value at the lowest level that sets it, of those the
        dictionary allows it at, else 'default' (the configuration's). A
        level setting it to None (JSON's null) sets it: the levels above are
        not consulted.
        """
        prop = _PROPERTIES.get(name)
        if prop is None:
            raise ValueError(f"'{name}' is not a Work Requirement property")
        if not prop.inherited:
            raise ValueError(f"'{name}' is not inherited: read it at its own level")
        for level, data in self._levels:
            if data is not None and level in prop.levels and name in data:
                return data[name]
        return default

    def checked(
        self, name: str, check: Callable[[Any, str], T], default: Any = None
    ) -> T:
        """
        The property's value as get() finds it, type-checked by 'check'
        (one of type_check's), which names the property in its error.
        """
        return check(self.get(name, default), name)
