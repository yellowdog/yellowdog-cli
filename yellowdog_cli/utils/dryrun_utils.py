"""
Shared reporting for the '--dry-run' mode of yd-cancel / yd-shutdown /
yd-terminate: list the entities an action would affect, without acting.
"""

from yellowdog_client import PlatformClient

from yellowdog_cli.utils.printing import (
    print_info,
    print_numbered_object_list,
    print_objects_as_json,
)


def report_dry_run(
    client: PlatformClient,
    summaries: list,
    noun: str,
    verb: str,
    as_json: bool,
) -> None:
    """
    Report the entities a dry-run would affect, without acting.

    'noun' is the singular entity name (e.g. 'Work Requirement'); 'verb' is the
    past-tense action (e.g. 'cancelled'). With as_json, emit a JSON array of the
    summaries (same serialisation as 'yd-list --json'); otherwise print the same
    tabular listing that 'yd-list' produces, preceded by a dry-run summary line.
    The empty set is handled in both forms.
    """
    if as_json:
        print_objects_as_json(summaries)
        return
    if not summaries:
        print_info(f"No {noun}s would be {verb}")
        return
    print_info(f"Dry run: {len(summaries)} {noun}(s) would be {verb}:")
    print_numbered_object_list(client, summaries, object_type_name=noun)
