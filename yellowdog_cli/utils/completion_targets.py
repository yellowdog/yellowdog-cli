"""
The entity arguments Tab completion looks up on the Platform: for each verb
and argument, the entity, whether its names or its IDs are offered, and the
statuses offered -- those the command acts on, so the offer is what the
command would accept.

Keyed by the derived command's name and the argument's name (a positional's
name, or an option's long flag, '--within'), as completion.py's _VERB_VALUES
is. The statuses are the SDK enums' member
names, written out so that the table, and completion.py with it, stay
SDK-free: tests/test_completion_targets.py holds them to the enums and to
the commands' own sets. A verb that takes names takes IDs too, but a name is
what a user types; an ID-only verb offers IDs, each described by its name.
"""

from __future__ import annotations

from dataclasses import dataclass

from yellowdog_cli.utils.command_registry import RESOURCE_TYPE_CHOICES
from yellowdog_cli.utils.entity_names import (
    ET_COMPUTE_REQUIREMENTS,
    ET_INSTANCES,
    ET_NODES,
    ET_TASK_GROUPS,
    ET_TASKS,
    ET_WORK_REQUIREMENTS,
    ET_WORKER_POOLS,
    ET_WORKERS,
    RN_ALLOWANCE,
)


@dataclass(frozen=True)
class Lookup:
    entity: str  # ET_WORK_REQUIREMENTS, ET_WORKER_POOLS or ET_COMPUTE_REQUIREMENTS
    ids: bool  # offer IDs, described by name, rather than names
    statuses: frozenset[str] | None  # the statuses offered; None for any
    configured_only: bool = False  # Configured Worker Pools alone
    # Selected by the configured tag, as the command selects them; a name
    # resolved in the namespace ('--within') is not
    tagged: bool = True
    # After 'wr/', the Work Requirement's Task Groups, as 'wr/tg'
    task_groups: bool = False
    # A resource type ('Keyring'): its names, as 'yd resource remove' and
    # 'show' take them after '--type' (a Credential's after 'keyring/')
    resource: str | None = None


# Not finished: what can still be acted on, followed or waited for
_WR_UNFINISHED = frozenset({"RUNNING", "HELD", "FINISHING", "CANCELLING"})
_WP_UNFINISHED = frozenset({"PENDING", "CONFIGURING", "EMPTY", "IDLE", "RUNNING"})
_CR_UNTERMINATED = frozenset(
    {"NEW", "PROVISIONING", "STARTING", "RUNNING", "STOPPING", "STOPPED", "TERMINATING"}
)


def _names(entity: str, statuses: frozenset[str] | None) -> Lookup:
    return Lookup(entity, ids=False, statuses=statuses)


def _task_groups(statuses: frozenset[str] | None) -> Lookup:
    """
    Work Requirements by name, then after 'wr/' their Task Groups.
    """
    return Lookup(ET_WORK_REQUIREMENTS, ids=False, statuses=statuses, task_groups=True)


# '--within' for each type 'yd list' lists within a parent: the parent's
# names, in any status and whatever their tag, since the option resolves a
# name in the namespace (a Work Requirement's then its Task Groups, as 'wr/tg')
_WR_WITHIN = Lookup(
    ET_WORK_REQUIREMENTS, ids=False, statuses=None, tagged=False, task_groups=True
)
WITHIN_LOOKUPS: dict[str, Lookup] = {
    ET_TASK_GROUPS: _WR_WITHIN,
    ET_TASKS: _WR_WITHIN,
    ET_INSTANCES: Lookup(
        ET_COMPUTE_REQUIREMENTS, ids=False, statuses=None, tagged=False
    ),
    ET_NODES: Lookup(ET_WORKER_POOLS, ids=False, statuses=None, tagged=False),
    ET_WORKERS: Lookup(ET_WORKER_POOLS, ids=False, statuses=None, tagged=False),
}


def _resource(resource_type: str) -> Lookup:
    return Lookup(
        "resources",
        # An Allowance has no name: its ID, described by its description
        ids=resource_type == RN_ALLOWANCE,
        statuses=None,
        tagged=False,
        resource=resource_type,
    )


# The names of each resource type, offered after '--type <type>' by
# 'yd resource remove', 'yd resource show' and 'yd show'
RESOURCE_LOOKUPS: dict[str, Lookup] = {
    resource_type: _resource(resource_type) for resource_type in RESOURCE_TYPE_CHOICES
}
# The arguments they complete: a remove's or a show's targets
RESOURCE_TARGETS = frozenset(
    {
        ("yd resource remove", "resource_specifications"),
        ("yd resource show", "yellowdog_ids"),
        ("yd-show", "yellowdog_ids"),
    }
)

_WR = "yd workrequirement"
_TG = "yd taskgroup"
_WP = "yd workerpool"
_CR = "yd computerequirement"
_SHOWN = "yellowdog_ids"  # yd-show, yd-follow and yd-wait's argument

LOOKUPS: dict[tuple[str, str], Lookup] = {
    # Work Requirements
    (f"{_WR} cancel", "work_requirements"): _names(
        ET_WORK_REQUIREMENTS, frozenset({"RUNNING", "HELD", "FINISHING"})
    ),
    (f"{_WR} hold", "work_requirements"): _names(
        ET_WORK_REQUIREMENTS, frozenset({"RUNNING"})
    ),
    (f"{_WR} start", "work_requirements"): _names(
        ET_WORK_REQUIREMENTS, frozenset({"HELD"})
    ),
    (f"{_WR} finish", "work_requirements"): _names(
        ET_WORK_REQUIREMENTS, frozenset({"RUNNING", "HELD"})
    ),
    (f"{_WR} priority", "priority_targets"): _names(
        ET_WORK_REQUIREMENTS, _WR_UNFINISHED
    ),
    (f"{_WR} compare", "wr_or_tg_id"): _names(ET_WORK_REQUIREMENTS, _WR_UNFINISHED),
    (f"{_WR} compare", "worker_pool_ids"): _names(ET_WORKER_POOLS, _WP_UNFINISHED),
    (f"{_WR} show", _SHOWN): _names(ET_WORK_REQUIREMENTS, None),
    (f"{_WR} follow", _SHOWN): _names(ET_WORK_REQUIREMENTS, _WR_UNFINISHED),
    (f"{_WR} wait", _SHOWN): _names(ET_WORK_REQUIREMENTS, _WR_UNFINISHED),
    # Task Groups, as 'wr/tg': a Work Requirement's name, then its Task Groups
    (f"{_TG} show", _SHOWN): _task_groups(None),
    (f"{_TG} compare", "wr_or_tg_id"): _task_groups(_WR_UNFINISHED),
    (f"{_TG} compare", "worker_pool_ids"): _names(ET_WORKER_POOLS, _WP_UNFINISHED),
    # Worker Pools
    (f"{_WP} resize", "worker_pool"): _names(ET_WORKER_POOLS, _WP_UNFINISHED),
    (f"{_WP} shutdown", "worker_pool_nodes_list"): _names(
        ET_WORKER_POOLS, _WP_UNFINISHED
    ),
    (f"{_WP} token", "worker_pools"): Lookup(
        ET_WORKER_POOLS, ids=False, statuses=_WP_UNFINISHED, configured_only=True
    ),
    (f"{_WP} show", _SHOWN): _names(ET_WORKER_POOLS, None),
    (f"{_WP} follow", _SHOWN): _names(ET_WORKER_POOLS, _WP_UNFINISHED),
    (f"{_WP} wait", _SHOWN): _names(ET_WORKER_POOLS, _WP_UNFINISHED),
    # Compute Requirements
    (f"{_CR} resize", "worker_pool"): _names(
        ET_COMPUTE_REQUIREMENTS, frozenset({"RUNNING"})
    ),
    (f"{_CR} stop", "compute_reqs_instances_or_nodes"): _names(
        ET_COMPUTE_REQUIREMENTS, frozenset({"RUNNING"})
    ),
    (f"{_CR} start", "compute_reqs_instances_or_nodes"): _names(
        ET_COMPUTE_REQUIREMENTS, frozenset({"STOPPED"})
    ),
    (f"{_CR} reprovision", "compute_reqs_instances_or_nodes"): _names(
        ET_COMPUTE_REQUIREMENTS, frozenset({"RUNNING"})
    ),
    (f"{_CR} terminate", "compute_reqs_instances_or_nodes"): _names(
        ET_COMPUTE_REQUIREMENTS, _CR_UNTERMINATED - {"TERMINATING"}
    ),
    (f"{_CR} show", _SHOWN): _names(ET_COMPUTE_REQUIREMENTS, None),
    (f"{_CR} follow", _SHOWN): _names(ET_COMPUTE_REQUIREMENTS, _CR_UNTERMINATED),
    (f"{_CR} wait", _SHOWN): _names(ET_COMPUTE_REQUIREMENTS, _CR_UNTERMINATED),
    # The listings within a parent
    ("yd taskgroup list", "--within"): WITHIN_LOOKUPS[ET_TASK_GROUPS],
    ("yd task list", "--within"): WITHIN_LOOKUPS[ET_TASKS],
    ("yd instance list", "--within"): WITHIN_LOOKUPS[ET_INSTANCES],
    ("yd node list", "--within"): WITHIN_LOOKUPS[ET_NODES],
    ("yd worker list", "--within"): WITHIN_LOOKUPS[ET_WORKERS],
}
