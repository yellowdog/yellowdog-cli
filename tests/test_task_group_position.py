"""
TaskGroupPosition (utils/task_group_position.py): a Task Group's lazy
substitutions are its name, its number zero-padded to the Work
Requirement's count of Task Groups, that count, and the Tasks it is being
given -- not those it already holds.
"""

import pytest

from yellowdog_cli.utils import variable_substitution
from yellowdog_cli.utils.task_group_position import TaskGroupPosition
from yellowdog_cli.utils.variable_syntax import (
    L_TASK_COUNT,
    L_TASK_GROUP_COUNT,
    L_TASK_GROUP_NAME,
    L_TASK_GROUP_NUMBER,
)


@pytest.fixture
def substitutions(monkeypatch) -> dict:
    """
    The substitution table, emptied for the test and put back after it: it
    is process-global.
    """
    table: dict = {}
    monkeypatch.setattr(variable_substitution, "VARIABLE_SUBSTITUTIONS", table)
    monkeypatch.setattr(variable_substitution, "_DEFINITIONS", {})
    return table


def test_a_new_work_requirements_task_group(substitutions):
    TaskGroupPosition(spec_index=0, number=0, count=1).substitute("grp", 5)
    assert substitutions == {
        L_TASK_GROUP_NAME: "grp",
        L_TASK_GROUP_NUMBER: "1",
        L_TASK_GROUP_COUNT: "1",
        L_TASK_COUNT: "5",
    }


def test_a_task_group_added_after_existing_ones(substitutions):
    # The third of ten in the Work Requirement, the first in the
    # specification, already holding 4 Tasks: numbered by its place in the
    # Work Requirement, padded to its count, and counting only the new Tasks
    TaskGroupPosition(spec_index=0, number=2, count=10, existing_tasks=4).substitute(
        "grp", 3
    )
    assert substitutions[L_TASK_GROUP_NUMBER] == "03"
    assert substitutions[L_TASK_GROUP_COUNT] == "10"
    assert substitutions[L_TASK_COUNT] == "3"
