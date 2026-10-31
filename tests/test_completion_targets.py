"""
Tests for the table of entity arguments Tab completion looks up on the
Platform (utils/completion_targets.py): every entry names a real verb and
argument, and offers the statuses the command itself acts on.
"""

from argparse import SUPPRESS

import pytest
from yellowdog_client.model import (
    AutoShutdown,
    ComputeRequirementStatus,
    WorkerPoolStatus,
    WorkRequirementStatus,
)

from yellowdog_cli import cancel
from yellowdog_cli.utils import compute_action_common, start_hold_common
from yellowdog_cli.utils.command_registry import LIST_WITHIN_TYPES, Completes
from yellowdog_cli.utils.completion_targets import (
    LOOKUPS,
    RESOURCE_LOOKUPS,
    WITHIN_LOOKUPS,
)
from yellowdog_cli.utils.entity_names import (
    ET_COMPUTE_REQUIREMENTS,
    ET_WORK_REQUIREMENTS,
    ET_WORKER_POOLS,
)
from yellowdog_cli.utils.noun_registry import NOUN_COMMANDS

_STATUSES = {
    ET_WORK_REQUIREMENTS: WorkRequirementStatus,
    ET_COMPUTE_REQUIREMENTS: ComputeRequirementStatus,
    ET_WORKER_POOLS: WorkerPoolStatus,
}


def _names(statuses) -> frozenset[str]:
    return frozenset(status.name for status in statuses)


@pytest.mark.parametrize("key", sorted(LOOKUPS))
def test_every_entry_is_a_visible_argument_of_a_verb(key):
    # A positional by name, or an option ('--within') by its long flag
    command_name, argument = key
    command = NOUN_COMMANDS[command_name]
    arguments = {
        option.name: option
        for option in command.flat_options()
        if option.kwargs.get("help") != SUPPRESS
    }
    assert argument in arguments
    assert arguments[argument].completes is Completes.NONE, "not a local file"


def test_within_is_looked_up_for_every_type_it_applies_to():
    assert set(WITHIN_LOOKUPS) == set(LIST_WITHIN_TYPES)
    for verb, entity_type in (
        ("yd task list", "tasks"),
        ("yd taskgroup list", "task-groups"),
        ("yd instance list", "instances"),
        ("yd node list", "nodes"),
        ("yd worker list", "workers"),
    ):
        assert LOOKUPS[(verb, "--within")] is WITHIN_LOOKUPS[entity_type]


def test_within_offers_any_status_untagged_as_the_option_resolves_names():
    for lookup in WITHIN_LOOKUPS.values():
        assert lookup.statuses is None and lookup.tagged is False


@pytest.mark.parametrize(
    "key", sorted(key for key, lookup in LOOKUPS.items() if lookup.resource is None)
)
def test_the_statuses_are_the_entitys(key):
    lookup = LOOKUPS[key]
    assert lookup.entity in _STATUSES
    if lookup.statuses is not None:
        assert lookup.statuses <= _names(_STATUSES[lookup.entity])


@pytest.mark.parametrize(
    "verb, statuses",
    [
        ("yd workrequirement cancel", cancel._CANCELLABLE_STATUSES),
        ("yd workrequirement hold", start_hold_common.HOLD.statuses),
        ("yd workrequirement start", start_hold_common.START.statuses),
        ("yd workrequirement finish", start_hold_common.FINISH.statuses),
        (
            "yd computerequirement stop",
            compute_action_common.COMPUTE_STOP.valid_cr_statuses,
        ),
        (
            "yd computerequirement start",
            compute_action_common.COMPUTE_START.valid_cr_statuses,
        ),
        (
            "yd computerequirement terminate",
            compute_action_common.COMPUTE_TERMINATE.valid_cr_statuses,
        ),
        (
            "yd computerequirement reprovision",
            compute_action_common.COMPUTE_REPROVISION.valid_cr_statuses,
        ),
        (
            "yd computerequirement autoshutdown",
            compute_action_common.compute_auto_shutdown(
                AutoShutdown(enabled=False)
            ).valid_cr_statuses,
        ),
    ],
)
def test_an_action_offers_what_the_command_acts_on(verb, statuses):
    (lookup,) = [lookup for (name, _), lookup in LOOKUPS.items() if name == verb]
    assert lookup.statuses == _names(statuses)


def test_every_verb_offers_names():
    # Each takes names, as well as IDs: the actions, the listings' '--within',
    # and show, follow, wait and compare, whose noun gives a name its type
    for (verb, _), lookup in LOOKUPS.items():
        if lookup.resource is None:
            assert lookup.ids is False, verb


def test_the_allowance_verbs_offer_ids_as_the_resource_lookup_does():
    # An Allowance has no name: its ID, described by its description
    for key in (
        ("yd allowance boost", "allowances"),
        ("yd allowance show", "yellowdog_ids"),
    ):
        assert LOOKUPS[key] is RESOURCE_LOOKUPS["Allowance"]
        assert LOOKUPS[key].ids is True


def test_a_task_groups_verbs_offer_wr_slash_tg():
    for verb, dest in (
        ("yd taskgroup show", "yellowdog_ids"),
        ("yd taskgroup compare", "wr_or_tg_id"),
    ):
        lookup = LOOKUPS[(verb, dest)]
        assert lookup.entity == "work-requirements" and lookup.task_groups, verb


def test_only_token_is_for_configured_worker_pools():
    configured = {
        verb for (verb, _), lookup in LOOKUPS.items() if lookup.configured_only
    }
    assert configured == {"yd workerpool token"}


def test_every_resource_type_has_a_lookup():
    from yellowdog_cli.utils.command_registry import RESOURCE_TYPE_CHOICES

    assert set(RESOURCE_LOOKUPS) == set(RESOURCE_TYPE_CHOICES)
    for resource_type, lookup in RESOURCE_LOOKUPS.items():
        assert lookup.resource == resource_type
        assert lookup.statuses is None and lookup.tagged is False
        # An Allowance has no name: its ID is offered
        assert lookup.ids is (resource_type == "Allowance")


def test_the_task_verbs_offer_wr_tg_and_tasks():
    from yellowdog_client.model import TaskStatus

    from yellowdog_cli.utils.completion_targets import TASK_UNFINISHED

    abort = LOOKUPS[("yd task abort", "task_id_list")]
    assert abort.task_groups and not abort.tasks
    for key in (
        ("yd task cancel", "work_requirements"),
        ("yd task show", "yellowdog_ids"),
    ):
        assert LOOKUPS[key].task_groups and LOOKUPS[key].tasks, key
    assert LOOKUPS[("yd task show", "yellowdog_ids")].task_statuses is None
    # Those cancel still applies to: the SDK's own test, as the command's
    assert TASK_UNFINISHED == _names(s for s in TaskStatus if not s.finished)
    assert LOOKUPS[("yd task cancel", "work_requirements")].task_statuses == (
        TASK_UNFINISHED
    )
