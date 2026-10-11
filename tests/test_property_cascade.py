"""
utils/property_cascade.py: a Work Requirement property taken from the lowest
level that sets it, consulting only the levels the dictionary allows it at,
and every lookup the CLI makes through it naming an inherited property.
"""

import ast
import json
from pathlib import Path

import pytest
from cli_test_helpers import shell

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
from yellowdog_cli.utils.specs.properties import WORK_REQUIREMENT_PROPERTIES
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


_CONFIG = """
[common]
key = "k"
secret = "s"
namespace = "ns"
tag = "t"
[workRequirement]
taskType = "bash"
arguments = ["from-toml"]
priority = 5.0
setTaskNames = true
timeout = 30.0
taskData = "from-toml"
"""


def _dry_run(tmp_path: Path, specification: dict) -> tuple[dict, str]:
    """
    The Work Requirement yd-submit would submit, and what it printed.
    """
    (tmp_path / "config.toml").write_text(_CONFIG, encoding="utf-8")
    (tmp_path / "wr.json").write_text(json.dumps(specification), encoding="utf-8")
    result = shell(
        f"cd {tmp_path} && yd-workrequirement submit -c config.toml wr.json --dry-run"
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    out = result.stdout
    return json.loads(out[out.index("{") : out.rindex("}") + 1]), out + result.stderr


class TestNullStopsInheritance:
    """
    A level setting a property to null stops it being inherited from the
    levels above: the property has its default, as though no level set it.
    """

    def test_null_and_empty_stop_inheritance_and_unset_does_not(self, tmp_path):
        wr, output = _dry_run(
            tmp_path,
            {
                "taskTypes": ["bash", "docker"],
                "taskGroups": [
                    {"name": "null", "arguments": None, "tasks": [{}]},
                    {"name": "empty", "arguments": [], "tasks": [{}]},
                    {"name": "unset", "arguments": "{{::}}", "tasks": [{}]},
                    {"name": "task-null", "tasks": [{"arguments": None}]},
                ],
            },
        )
        arguments = {
            group["name"]: group["tasks"][0].get("arguments")
            for group in wr["taskGroups"]
        }
        assert arguments == {
            "null": None,
            "empty": None,
            "unset": ["from-toml"],
            "task-null": None,
        }
        assert "WARNING" not in output

    def test_a_scalar_set_to_null_has_its_default(self, tmp_path):
        wr, _ = _dry_run(
            tmp_path,
            {
                "priority": None,
                "taskGroups": [
                    {"tasks": [{"timeout": None}]},
                ],
            },
        )
        assert "priority" not in wr
        task = wr["taskGroups"][0]["tasks"][0]
        assert "timeout" not in task

    def test_null_task_data_stops_it_being_inherited(self, tmp_path):
        # The first level setting any Task Data property supplies it: a
        # null fell through to the next level that set one
        wr, _ = _dry_run(
            tmp_path,
            {
                "taskGroups": [
                    {"taskDataFile": None, "tasks": [{}, {"taskData": "own"}]}
                ]
            },
        )
        tasks = wr["taskGroups"][0]["tasks"]
        assert [task.get("taskData") for task in tasks] == [None, "own"]

    def test_null_task_types_declares_none(self, tmp_path):
        # It raised a TypeError: the Task Group's types are then its Tasks'
        wr, _ = _dry_run(
            tmp_path,
            {
                "taskTypes": ["bash", "docker"],
                "taskGroups": [{"taskTypes": None, "tasks": [{"taskType": "bash"}]}],
            },
        )
        assert wr["taskGroups"][0]["runSpecification"]["taskTypes"] == ["bash"]

    def test_a_null_task_type_is_no_type_of_its_own(self, tmp_path):
        # A Task must have a type, so it takes its Task Group's, as without one
        wr, output = _dry_run(
            tmp_path, {"taskGroups": [{"tasks": [{"taskType": None}]}]}
        )
        assert wr["taskGroups"][0]["runSpecification"]["taskTypes"] == ["bash"]
        assert wr["taskGroups"][0]["tasks"][0]["taskType"] == "bash"
        assert "taskType: must be string" in " ".join(output.split())

    def test_null_set_task_names_has_the_default(self, tmp_path):
        # The default is to name Tasks; null gave False
        wr, _ = _dry_run(
            tmp_path,
            {
                "setTaskNames": False,
                "taskGroups": [{"setTaskNames": None, "tasks": [{}]}],
            },
        )
        assert wr["taskGroups"][0]["tasks"][0].get("name")
