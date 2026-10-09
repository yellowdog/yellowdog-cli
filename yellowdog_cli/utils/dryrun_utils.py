"""
Shared reporting for the '--dry-run' mode of yd-cancel / yd-shutdown /
yd-terminate: list the entities an action would affect, without acting.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from yellowdog_cli.utils.printing import print_dry_run, print_info
from yellowdog_cli.utils.results import record_action
from yellowdog_cli.utils.tables import print_numbered_object_list

if TYPE_CHECKING:
    from yellowdog_client import PlatformClient

    from yellowdog_cli.utils.action_runner import Item


def report_dry_run(
    client: PlatformClient,
    summaries: list,
    noun: str,
    verb: str,
    entity_type: str,
    action: str,
    as_json: bool,
) -> None:
    """
    Report the entities a dry-run would affect, without acting.

    'noun' is the singular entity name (e.g. 'Work Requirement'); 'verb' is the
    past-tense action (e.g. 'cancelled'). 'entity_type' ('work-requirements')
    and 'action' ('cancel') are the '--json' record's vocabulary: each entity
    is recorded as the real action would record it, with the outcome
    'would <action>' and the entity's 'status' as yd-list prints it (which
    Commander's confirmation shows beside each name), and the wrapper prints
    the array. Without as_json, print
    the same tabular listing that 'yd-list' produces, preceded by a dry-run
    summary line. The empty set is handled in both forms.
    """
    for summary in summaries:
        status = getattr(summary, "status", None)
        record_action(
            summary,
            entity_type,
            action,
            f"would {action}",
            status=None if status is None else str(status),
        )
    if as_json:
        return
    if not summaries:
        print_info(f"No {noun}s would be {verb}")
        return
    print_dry_run(f"{len(summaries)} {noun}(s) would be {verb}:")
    print_numbered_object_list(client, summaries, object_type_name=noun)


def report_dry_run_items(
    items: Sequence[Item], action: str, record: Callable[[Item, str | None], None]
) -> None:
    """
    Report the targets named on the command line, resolved, that the action
    would affect, without acting: a line each, and record(item, status) for
    the command to record it as the real action would, with the outcome
    'would <action>' and the status, as report_dry_run() records a listing's.
    """
    for item in items:
        status = _status_of(item.entity)
        print_dry_run(
            f"Would {action} {item.entity_type.rstrip('s').replace('-', ' ')}"
            f" {_label(item.entity)}" + ("" if status is None else f" ({status})")
        )
        record(item, status)


def _status_of(entity: Any) -> str | None:
    status = (
        entity.get("status")
        if isinstance(entity, dict)
        else getattr(entity, "status", None)
    )
    return None if status is None else str(status)


def _label(entity: Any) -> str:
    if isinstance(entity, dict):
        name, id_ = entity.get("name"), entity.get("id")
    else:
        name, id_ = getattr(entity, "name", None), getattr(entity, "id", None)
    if name and id_:
        return f"'{name}' ({id_})"
    return f"'{name or id_}'"
