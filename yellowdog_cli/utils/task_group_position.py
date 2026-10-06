"""
Where a Task Group stands in a yd-submit run, for finding its specification
and for numbering and naming it and its Tasks: one value, built once per Task
Group, in place of the indexes, counts and offsets that were passed down
separately through each layer and recomputed in each.
"""

from dataclasses import dataclass

from yellowdog_cli.utils.submit_utils import formatted_number_str
from yellowdog_cli.utils.variable_substitution import add_or_update_substitution
from yellowdog_cli.utils.variable_syntax import (
    L_TASK_COUNT,
    L_TASK_GROUP_COUNT,
    L_TASK_GROUP_NAME,
    L_TASK_GROUP_NUMBER,
)


@dataclass(frozen=True)
class TaskGroupPosition:
    """
    A Task Group's place: 'spec_index' in the specification's 'taskGroups';
    'number' (zero-based) of 'count' in the Work Requirement; and
    'existing_tasks', the Tasks it already holds, which new ones are numbered
    on from. The two indexes differ, and Tasks already exist, only when
    adding to an existing Work Requirement ('--add-to').
    """

    spec_index: int
    number: int
    count: int
    existing_tasks: int = 0

    def substitute(self, task_group_name: str, num_tasks: int) -> None:
        """
        Define the Task Group's lazy substitutions, for its own properties
        and its Tasks': its name, its number and the Work Requirement's count
        of Task Groups, and 'num_tasks', the Tasks it is being given.
        """
        add_or_update_substitution(L_TASK_COUNT, str(num_tasks))
        add_or_update_substitution(L_TASK_GROUP_NAME, task_group_name)
        add_or_update_substitution(
            L_TASK_GROUP_NUMBER, formatted_number_str(self.number, self.count)
        )
        add_or_update_substitution(L_TASK_GROUP_COUNT, str(self.count))
