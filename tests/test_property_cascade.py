"""
utils/property_cascade.py: a Work Requirement property taken from the lowest
level that sets it, consulting only the levels the dictionary allows it at,
and every lookup the CLI makes through it naming an inherited property.
"""

import ast
from pathlib import Path

import pytest

from yellowdog_cli.utils import property_names
from yellowdog_cli.utils.property_cascade import Cascade
from yellowdog_cli.utils.property_names import (
    ARGS,
    ARGS_PREFIX,
    NAME,
    PRIORITY,
    TASK_LEVEL_TIMEOUT,
    TASK_TYPES,
)
from yellowdog_cli.utils.spec_properties import WORK_REQUIREMENT_PROPERTIES
from yellowdog_cli.utils.type_check import check_int, check_list

PACKAGE = Path(__file__).resolve().parent.parent / "yellowdog_cli"


class TestLevels:
    def test_the_lowest_level_setting_it_wins(self):
        wr = {ARGS: ["wr"]}
        tg = {ARGS: ["tg"]}
        task = {ARGS: ["task"]}
        assert Cascade(wr, tg, task).get(ARGS) == ["task"]
        assert Cascade(wr, tg, {}).get(ARGS) == ["tg"]
        assert Cascade(wr, {}, {}).get(ARGS) == ["wr"]
        assert Cascade({}, {}, {}).get(ARGS, ["toml"]) == ["toml"]
        assert Cascade({}, {}, {}).get(ARGS) is None

    def test_a_level_without_the_property_in_the_dictionary_is_skipped(self):
        # 'argumentsPrefix' may not be set on a Task: a Task's is ignored
        task = {ARGS_PREFIX: ["task"]}
        assert Cascade({}, {ARGS_PREFIX: ["tg"]}, task).get(ARGS_PREFIX) == ["tg"]
        # 'timeout' is a Task's own, or the configuration's
        assert (
            Cascade({TASK_LEVEL_TIMEOUT: 1}, {TASK_LEVEL_TIMEOUT: 2}, {}).get(
                TASK_LEVEL_TIMEOUT, 3
            )
            == 3
        )
        # 'taskTypes' is not a Task's
        assert Cascade({}, {}, {TASK_TYPES: ["x"]}).get(TASK_TYPES, []) == []

    def test_a_null_sets_it(self):
        # As dict.get() did: a level holding the property stops the search,
        # whatever its value
        assert Cascade({PRIORITY: 5}, {PRIORITY: None}).get(PRIORITY, 1) is None

    def test_the_levels_are_the_specification_itself(self):
        # A substitution made in place after the Cascade is built is seen
        task: dict = {}
        cascade = Cascade({}, {}, task)
        task[ARGS] = ["late"]
        assert cascade.get(ARGS) == ["late"]

    def test_checked_names_the_property(self):
        with pytest.raises(TypeError, match="priority"):
            Cascade({PRIORITY: "high"}).checked(PRIORITY, check_int)
        assert Cascade({ARGS: ["a"]}).checked(ARGS, check_list) == ["a"]


class TestRefusals:
    def test_an_unknown_property_is_refused(self):
        with pytest.raises(ValueError, match="'nope' is not a Work Requirement"):
            Cascade({}).get("nope")

    def test_a_property_not_inherited_is_refused(self):
        with pytest.raises(ValueError, match="'name' is not inherited"):
            Cascade({NAME: "wr"}).get(NAME)


def _cascade_lookups() -> list[tuple[str, int, str]]:
    """
    (file, line, property name) for every Cascade(...).get()/checked() call in
    the package whose property is a property_names constant, which is how
    every one of them is written.
    """
    lookups = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("get", "checked")
                and node.args
                and isinstance(node.args[0], ast.Name)
            ):
                continue
            receiver = node.func.value
            is_cascade = (
                isinstance(receiver, ast.Call)
                and isinstance(receiver.func, ast.Name)
                and receiver.func.id == "Cascade"
            ) or (isinstance(receiver, ast.Name) and receiver.id == "levels")
            if is_cascade:
                constant = node.args[0].id
                lookups.append(
                    (
                        path.name,
                        node.lineno,
                        getattr(property_names, constant, constant),
                    )
                )
    return lookups


class TestEveryLookup:
    def test_there_are_lookups_to_check(self):
        # The scan finds what it is meant to, so the test below is not vacuous
        assert len(_cascade_lookups()) > 30

    def test_every_lookup_names_an_inherited_property(self):
        # Caught here rather than when a run first reaches the lookup
        inherited = {p.name for p in WORK_REQUIREMENT_PROPERTIES if p.inherited}
        wrong = [lookup for lookup in _cascade_lookups() if lookup[2] not in inherited]
        assert wrong == []
