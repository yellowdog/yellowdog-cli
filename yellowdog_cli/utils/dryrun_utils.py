"""
Shared reporting for the '--dry-run' mode of yd-cancel / yd-shutdown /
yd-terminate: list the entities an action would affect, without acting.
"""

from yellowdog_client import PlatformClient

from yellowdog_cli.utils.printing import (
    print_dry_run,
    print_info,
    print_numbered_object_list,
)
from yellowdog_cli.utils.results import record_action


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
