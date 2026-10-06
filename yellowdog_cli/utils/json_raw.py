"""
'yd-submit --json-raw': a Work Requirement written as the Platform's own
JSON, its Tasks inside its Task Groups, submitted with direct REST calls
rather than built from a specification: the Work Requirement and its Task
Groups first, then each Task Group's Tasks in batches (task_batches.py). A
Work Requirement left with only some of its Tasks is cancelled. Nothing is
inherited between levels, and there is no schema to check it against.
"""

from collections.abc import Callable
from gzip import compress
from json import dumps as json_dumps
from json import loads as json_loads
from typing import cast

import requests

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import ET_WORK_REQUIREMENTS
from yellowdog_cli.utils.limits import RAW_REQUEST_TIMEOUT
from yellowdog_cli.utils.misc_utils import format_yd_name
from yellowdog_cli.utils.printing import (
    print_dry_run,
    print_error,
    print_info,
    print_json,
    print_quiet_result,
    print_warning,
)
from yellowdog_cli.utils.property_names import NAME, TASK_GROUPS, TASKS
from yellowdog_cli.utils.results import record_document, record_entity
from yellowdog_cli.utils.specs.loading import load_specification
from yellowdog_cli.utils.submit_utils import formatted_number_str
from yellowdog_cli.utils.task_batches import (
    raise_for_response,
    run_batches,
    submit_with_retries,
)
from yellowdog_cli.utils.type_check import check_list, check_str
from yellowdog_cli.utils.variable_substitution import (
    add_substitutions_without_overwriting,
    resolve_variables_insitu,
)
from yellowdog_cli.utils.variable_syntax import L_WR_NAME


def submit_json_raw(
    ctx: RunContext,
    wr_file: str,
    *,
    batch_size: int,
    parallel_batches: int,
    follow: Callable[[str], None],
) -> None:
    """
    Submit a 'raw' JSON Work Requirement, consisting of a combined Work
    Requirement definition and the constituent Tasks, in batches of
    'batch_size' on up to 'parallel_batches' threads. 'follow' is given the
    new Work Requirement's ID, to follow it if '--follow' or '--progress'
    asks; it is a callback so that this module imports nothing from
    submit.py, the command module.
    """
    # Platform JSON, not a specification, so there is no schema to check
    wr_data = load_specification(
        wr_file,
        "Work Requirement",
        family=None,
        jsonnet_dry_run=bool(ctx.args.jsonnet_dry_run),
    )

    if not isinstance(wr_data, dict):
        raise ValueError(f"Work Requirement file '{wr_file}' must be a JSON object")
    if "name" not in wr_data:
        raise ValueError(f"Property '{NAME}' is not defined in '{wr_file}'")

    # Lazy substitution of Work Requirement name
    wr_data["name"] = format_yd_name(check_str(wr_data["name"], NAME))
    wr_name = wr_data["name"]
    add_substitutions_without_overwriting(subs={L_WR_NAME: wr_name})
    resolve_variables_insitu(wr_data)

    if ctx.args.dry_run:
        # This will show the results of any variable substitutions
        if ctx.args.json_output:
            record_document(wr_data)
            return
        print_dry_run("Printing JSON Work Requirement specification:")
        print_json(wr_data)
        print_dry_run("Complete")
        return

    # Extract Tasks from Task Groups
    task_lists = {}
    if TASK_GROUPS not in wr_data:
        raise ValueError(f"Property '{TASK_GROUPS}' is not defined")
    task_groups = check_list(wr_data[TASK_GROUPS], TASK_GROUPS)
    if not task_groups:
        raise ValueError("There must be at least one Task Group")
    for tg_number, task_group in enumerate(task_groups):
        if not isinstance(task_group, dict) or "name" not in task_group:
            raise ValueError(
                f"Task Group {tg_number + 1} of {len(task_groups)} has no"
                f" '{NAME}' property"
            )
        task_lists[task_group["name"]] = task_group.get(TASKS, [])
        task_group.pop(TASKS, None)

    # Submit the Work Requirement and its Task Groups
    response = requests.post(
        url=f"{ctx.config.url}/work/requirements",
        headers={"Authorization": f"yd-key {ctx.config.key}:{ctx.config.secret}"},
        json=wr_data,
        timeout=RAW_REQUEST_TIMEOUT,
    )

    if response.status_code != 200:
        print_error(f"Failed to create Work Requirement '{wr_name}'")
        raise_for_response(response)

    wr_id = json_loads(response.text)["id"]
    namespace = cast(str, wr_data.get("namespace"))
    print_info(f"Created Work Requirement '{namespace}/{wr_name}' ({wr_id})")
    record_entity(wr_id, wr_name, namespace, ET_WORK_REQUIREMENTS)
    print_quiet_result(wr_id)

    try:
        _submit_json_raw_tasks(
            ctx, wr_id, wr_name, namespace, task_lists, batch_size, parallel_batches
        )
    except (Exception, KeyboardInterrupt):
        # As for a Work Requirement built from a specification: one left
        # with only some of its Tasks is cancelled, and a failure to cancel
        # it is reported without masking the failure that is re-raised
        try:
            ctx.client.work_client.cancel_work_requirement_by_id(wr_id)
            print_warning(f"Cancelled Work Requirement '{wr_name}'")
        except Exception as e:
            print_error(f"Unable to cancel Work Requirement '{wr_name}': {e}")
        raise

    follow(wr_id)


def _submit_json_raw_tasks(
    ctx: RunContext,
    wr_id: str,
    wr_name: str,
    namespace: str,
    task_lists: dict[str, list],
    batch_size: int,
    parallel_batches: int,
) -> None:
    """
    Hold the newly created raw Work Requirement if asked, then submit each
    Task Group's Tasks in batches. A batch that fails raises, once the
    batches already under way have finished; those not yet started are not.
    """
    if ctx.args.hold:
        ctx.client.work_client.hold_work_requirement_by_id(wr_id)
        print_info("Work Requirement status set to 'HELD'")

    # Submit Tasks in batches
    for task_group_name, task_list in task_lists.items():
        if not task_list:
            print_info(f"No Tasks to add to Task Group '{task_group_name}'")
            continue
        num_submitted_tasks = run_batches(
            ctx,
            len(task_list),
            batch_size,
            parallel_batches,
            make_batch=lambda start, end, task_list=task_list: task_list[start:end],
            send_batch=lambda task_batch, batch_number, num_batches, name=task_group_name: (
                submit_json_task_batch(
                    ctx,
                    task_batch,
                    batch_number,
                    num_batches,
                    name,
                    wr_name,
                    namespace,
                )
            ),
        )
        print_info(
            f"Added a total of {num_submitted_tasks} Task(s) to Task Group '{task_group_name}'"
        )


def submit_json_task_batch(
    ctx: RunContext,
    task_batch: list[dict],
    batch_number: int,
    num_batches: int,
    task_group_name: str,
    wr_name: str,
    namespace: str,
) -> int:
    """
    Submit a batch of tasks using the REST API, retrying it as the main path
    does. Return the number of tasks submitted.
    """
    task_batch_compressed = compress(json_dumps(task_batch).encode("utf-8"))
    batch_number_str = formatted_number_str(batch_number, num_batches)

    def attempt() -> None:
        response = requests.post(
            url=(
                f"{ctx.config.url}/work/namespaces/{namespace}"
                f"/requirements/{wr_name}/taskGroups/{task_group_name}/tasks"
            ),
            headers={
                "Authorization": f"yd-key {ctx.config.key}:{ctx.config.secret}",
                "Content-Encoding": "gzip",
                "Content-Type": "application/json",
            },
            data=task_batch_compressed,
            timeout=RAW_REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            raise_for_response(response)

    def report_success() -> None:
        print_info(
            f"Added {len(task_batch)} Task(s) to Task Group "
            f"'{task_group_name}' (Batch {batch_number_str} of {num_batches})"
        )

    batch = (
        f"batch {batch_number_str} of {num_batches} to Task Group '{task_group_name}'"
    )
    submit_with_retries(attempt, report_success, batch=batch, batch_in_full=batch)
    return len(task_batch)
