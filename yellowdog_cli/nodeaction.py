#!/usr/bin/env python3

"""
A script to submit Node Actions to Worker Pool nodes.
"""

import time
from dataclasses import dataclass
from os.path import abspath, dirname
from os.path import join as path_join
from typing import Any, TypeAlias, cast

from yellowdog_client.model import (
    Node,
    NodeAction,
    NodeActionGroup,
    NodeActionQueueSnapshot,
    NodeActionQueueStatus,
    NodeCreateWorkersAction,
    NodeIdFilter,
    NodeRunCommandAction,
    NodeSearch,
    NodeStatus,
    NodeWorkerTarget,
    NodeWriteFileAction,
    WorkerPool,
    WorkerPoolSummary,
)

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_utils import (
    get_worker_pool_id_by_name,
    get_worker_pool_summaries,
)
from yellowdog_cli.utils.exit_codes import (
    SESSION_FAILURES,
    NotFoundError,
    ReportedFailure,
    classify,
)
from yellowdog_cli.utils.file_substitution import (
    process_variable_substitutions_in_file_contents,
)
from yellowdog_cli.utils.interactive import confirmed, select
from yellowdog_cli.utils.limits import NODE_ACTION_QUEUE_POLL_INTERVAL
from yellowdog_cli.utils.load_config import config_file_dir
from yellowdog_cli.utils.misc_utils import is_http_not_found
from yellowdog_cli.utils.printing import (
    print_error,
    print_info,
    print_warning,
    print_yd_object,
)
from yellowdog_cli.utils.property_names import (
    ACTION_CONTENT,
    ACTION_CONTENT_FILE,
    ACTION_CONTENT_FILES,
    ACTION_GROUPS,
    ACTION_PATH,
    ACTION_TYPE,
    ACTIONS,
    ARGS,
    ENV,
    NODE_TARGET_COUNT,
    NODE_TARGET_CUSTOM_CMD,
    NODE_TARGET_TYPE,
    NODE_TOTAL_WORKERS,
    NODE_TYPES,
    NODE_WORKERS,
)
from yellowdog_cli.utils.results import json_requested, record, rows_as_objects
from yellowdog_cli.utils.specs.loading import load_specification
from yellowdog_cli.utils.specs.schema import Family
from yellowdog_cli.utils.tables import (
    NODE_ACTION_QUEUE_HEADINGS,
    node_action_queue_table,
    print_node_action_queue_table,
)
from yellowdog_cli.utils.variable_substitution import warn_of_undefined_variables
from yellowdog_cli.utils.variable_syntax import (
    WP_VARIABLES_POSTFIX,
    WP_VARIABLES_PREFIX,
)
from yellowdog_cli.utils.wrapper import main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

# Action type strings used in spec files
_RUN_COMMAND = "runCommand"
_WRITE_FILE = "writeFile"
_CREATE_WORKERS = "createWorkers"

# The columns of a submission's '--json' record, one per submission target:
# a node, or the whole Worker Pool (a null node ID)
SUBMISSION_HEADINGS = [
    "Worker Pool ID",
    "Node ID",
    "Action Groups",
    "Actions",
    "Outcome",
]


def _record_submission(
    wp_id: str,
    node_ids: list[str] | None,
    action_groups: int | None,
    actions: int,
    outcome: str,
    error: str | None = None,
) -> None:
    """
    Record a submission for '--json': one row per node in 'node_ids', or one
    for the whole Worker Pool when it is None. 'outcome' is 'submitted',
    'skipped' (declined) or 'failed', with the error text in "error".
    """
    for node_id in node_ids if node_ids is not None else [None]:
        (row,) = rows_as_objects(
            SUBMISSION_HEADINGS, [[wp_id, node_id, action_groups, actions, outcome]]
        )
        if error is not None:
            row["error"] = error
        record(row)


def _record_queues(rows: list[tuple[str, NodeActionQueueSnapshot]]) -> None:
    """
    Record the node action queue table for '--json', a row object per node.
    """
    for row in rows_as_objects(
        NODE_ACTION_QUEUE_HEADINGS, node_action_queue_table(rows)
    ):
        record(row)


@main_wrapper
def main(ctx: RunContext):
    # '--validate' with '--status', and a missing '--actions', are refused as
    # the command line is parsed ('check_node_action_args' in the registry)
    if ctx.args.status:
        _show_status(ctx)
    else:
        _submit_actions(ctx)


# The states of a node that can take Node Actions, offered for selection and
# targeted by '--all-nodes'; a TERMINATED or DEREGISTERED one is skipped
_LIVE_NODE_STATUSES = (NodeStatus.RUNNING, NodeStatus.LATE)
_FINISHED_NODE_STATUSES = (NodeStatus.TERMINATED, NodeStatus.DEREGISTERED)

# A Worker Pool to act on: fetched, or chosen from a listing
_Pool: TypeAlias = WorkerPool | WorkerPoolSummary

# A submission's Worker Pool, nodes (None for all), action groups and actions,
# as _record_submission() records them
_SubmissionRecord: TypeAlias = tuple[str, list[str] | None, int | None, int]


def _pool_label(pool: _Pool) -> str:
    return f"'{pool.namespace}/{pool.name}'" if pool.name else str(pool.id)


def _get_worker_pool(ctx: RunContext, worker_pool_id: str) -> WorkerPool:
    try:
        return ctx.client.worker_pool_client.get_worker_pool_by_id(
            worker_pool_id=worker_pool_id
        )
    except Exception as e:
        if is_http_not_found(e):
            raise NotFoundError(f"Cannot find Worker Pool {worker_pool_id}") from e
        raise


def _get_node(ctx: RunContext, node_id: str) -> Node:
    try:
        return ctx.client.worker_pool_client.get_node_by_id(node_id)
    except Exception as e:
        if is_http_not_found(e):
            raise NotFoundError(f"Cannot find Node {node_id}") from e
        raise


def _without_duplicates(node_ids: list[str]) -> list[str]:
    """
    The node IDs in the order given, each once: a repeated node would
    otherwise be sent the actions again.
    """
    unique = list(dict.fromkeys(node_ids))
    if len(unique) < len(node_ids):
        print_warning(f"Ignoring {len(node_ids) - len(unique)} duplicate node ID(s)")
    return unique


def _resolve_worker_pool(ctx: RunContext) -> _Pool:
    """
    The Worker Pool named by --worker-pool (a name, or a YDID, checked as
    the command line is parsed), else one chosen interactively from the
    unfinished pools in the namespace whose names include the tag. Raises
    NotFoundError for one that does not exist, and ValueError for one that
    has finished or when none can be chosen.
    """
    wp_name = ctx.args.worker_pool_name

    if wp_name is not None:
        if get_ydid_type(wp_name) == YDIDType.WORKER_POOL:
            pool: _Pool = _get_worker_pool(ctx, wp_name)
        else:
            wp_id = get_worker_pool_id_by_name(
                ctx.client, wp_name, ctx.config.namespace
            )
            if wp_id is None:
                raise NotFoundError(f"Cannot find Worker Pool '{wp_name}'")
            pool = _get_worker_pool(ctx, wp_id)
        if pool.status is not None and pool.status.finished:
            raise ValueError(f"Worker Pool {_pool_label(pool)} is {pool.status}")
        return pool

    summaries: list[WorkerPoolSummary] = [
        summary
        for summary in get_worker_pool_summaries(
            ctx.client,
            namespace=ctx.config.namespace,
            name=ctx.config.name_tag if ctx.config.name_tag else None,
        )
        if summary.status is None or not summary.status.finished
    ]
    if not summaries:
        raise ValueError(
            f"No active Worker Pools found in namespace '{ctx.config.namespace}'"
        )
    selected = cast(
        list[WorkerPoolSummary],
        select(
            ctx.client,
            cast(list[Any], summaries),
            single_result=True,
            force_interactive=True,
            override_quiet=True,
            result_required=True,
        ),
    )
    return selected[0]


def _get_nodes_for_pool(
    ctx: RunContext, wp_id: str, live_only: bool = True
) -> list[Node]:
    """
    The nodes registered to the Worker Pool: those that can take Node
    Actions, unless 'live_only' is False.
    """
    nodes = ctx.client.worker_pool_client.get_nodes(
        NodeSearch(workerPoolId=wp_id)
    ).list_all()
    if not live_only:
        return nodes
    return [node for node in nodes if node.status in _LIVE_NODE_STATUSES]


def _choose_nodes(ctx: RunContext, pool: _Pool) -> list[str]:
    """
    The IDs of the nodes chosen interactively from the pool's live ones.
    """
    live = _get_nodes_for_pool(ctx, cast(str, pool.id))
    if not live:
        raise ValueError(f"No running nodes in Worker Pool {_pool_label(pool)}")
    selected = cast(
        list[Node],
        select(
            ctx.client,
            cast(list[Any], live),
            force_interactive=True,
            sort_objects=False,
            override_quiet=True,
            result_required=True,
        ),
    )
    return [cast(str, node.id) for node in selected]


def _resolve_targets(ctx: RunContext) -> tuple[_Pool, list[str] | None, list[str]]:
    """
    The Worker Pool, the nodes to target (None for all of them, with
    --all-nodes) and the nodes given that are skipped, having finished.

    Nodes given with --node are fetched, each once: one that does not exist
    raises NotFoundError, and they must all be in the one Worker Pool, which
    is theirs unless --worker-pool names it (and must then be theirs too).
    Without --node, the nodes are chosen interactively from the pool's live
    ones.
    """
    node_ids = _without_duplicates(ctx.args.node_ids or [])

    if not node_ids:
        pool = _resolve_worker_pool(ctx)
        if ctx.args.all_nodes:
            return pool, None, []
        return pool, _choose_nodes(ctx, pool), []

    nodes = [_get_node(ctx, node_id) for node_id in node_ids]
    pool_ids = list(dict.fromkeys(cast(str, node.workerPoolId) for node in nodes))
    if ctx.args.worker_pool_name is not None:
        pool = _resolve_worker_pool(ctx)
        strangers = [node.id for node in nodes if node.workerPoolId != pool.id]
        if strangers:
            raise ValueError(
                f"Node(s) {', '.join(cast(list[str], strangers))} are not in"
                f" Worker Pool {_pool_label(pool)}"
            )
    elif len(pool_ids) > 1:
        raise ValueError(
            f"The nodes given are in {len(pool_ids)} Worker Pools"
            f" ({', '.join(pool_ids)}); give the nodes of one pool at a time"
        )
    else:
        pool = _get_worker_pool(ctx, pool_ids[0])

    targets: list[str] = []
    skipped: list[str] = []
    for node in nodes:
        if node.status in _FINISHED_NODE_STATUSES:
            print_warning(f"Node {node.id} is {node.status}, and is skipped")
            skipped.append(cast(str, node.id))
        else:
            targets.append(cast(str, node.id))
    return pool, targets, skipped


def _parse_node_worker_target(workers_spec: dict) -> NodeWorkerTarget | None:
    """
    Parse a nodeWorkers dict to a NodeWorkerTarget.
    """
    target_type_str = workers_spec.get(NODE_TARGET_TYPE)
    if target_type_str is None:
        print_error(f"'nodeWorkers' must specify '{NODE_TARGET_TYPE}'")
        return None

    match target_type_str.upper():
        case "PER_NODE":
            count = workers_spec.get(NODE_TARGET_COUNT)
            if count is None:
                print_error("'PER_NODE' nodeWorkers requires a 'targetCount'")
                return None
            return NodeWorkerTarget.per_node(int(cast(str, count)))
        case "PER_VCPU":
            count = workers_spec.get(NODE_TARGET_COUNT)
            if count is None:
                print_error("'PER_VCPU' nodeWorkers requires a 'targetCount'")
                return None
            return NodeWorkerTarget.per_vcpus(float(cast(str, count)))
        case "CUSTOM":
            cmd = workers_spec.get(NODE_TARGET_CUSTOM_CMD)
            if cmd is None:
                print_error("'CUSTOM' nodeWorkers requires a 'customTargetCommand'")
                return None
            return NodeWorkerTarget.per_custom_command(cast(str, cmd))
        case _:
            print_error(f"Unknown nodeWorkers targetType '{target_type_str}'")
            return None


def _parse_action(action_spec: dict, source_dir: str) -> NodeAction | None:
    """
    Parse a single action dict into the appropriate SDK NodeAction subclass.
    contentFile/contentFiles paths are resolved relative to source_dir.
    """
    action_type = action_spec.get(ACTION_TYPE)
    node_types = action_spec.get(NODE_TYPES)

    match action_type:
        case None:
            print_error(f"Action missing required '{ACTION_TYPE}' field")
            return None

        case "runCommand":
            path = action_spec.get(ACTION_PATH)
            if path is None:
                print_error(f"'{_RUN_COMMAND}' action missing required '{ACTION_PATH}'")
                return None
            return NodeRunCommandAction(
                path=cast(str, path),
                arguments=action_spec.get(ARGS),
                environment=action_spec.get(ENV),
                nodeTypes=node_types,
            )

        case "writeFile":
            path = action_spec.get(ACTION_PATH)
            if path is None:
                print_error(f"'{_WRITE_FILE}' action missing required '{ACTION_PATH}'")
                return None
            content_val = action_spec.get(ACTION_CONTENT)
            content_file = action_spec.get(ACTION_CONTENT_FILE)
            content_files = action_spec.get(ACTION_CONTENT_FILES)
            sources = sum(
                x is not None for x in (content_val, content_file, content_files)
            )
            if sources > 1:
                print_error(
                    f"'{_WRITE_FILE}' action: only one of '{ACTION_CONTENT}', "
                    f"'{ACTION_CONTENT_FILE}', '{ACTION_CONTENT_FILES}' may be specified"
                )
                return None
            if content_file is not None:
                try:
                    with open(
                        path_join(source_dir, cast(str, content_file)), encoding="utf-8"
                    ) as f:
                        raw = f.read()
                    content_val = process_variable_substitutions_in_file_contents(
                        raw,
                        prefix=WP_VARIABLES_PREFIX,
                        postfix=WP_VARIABLES_POSTFIX,
                        source=str(content_file),
                    )
                    warn_of_undefined_variables(
                        {str(content_file): content_val},
                        prefix=WP_VARIABLES_PREFIX,
                        postfix=WP_VARIABLES_POSTFIX,
                        per_source=True,
                    )
                except OSError as e:
                    print_error(f"Cannot read '{ACTION_CONTENT_FILE}' file: {e}")
                    return None
            elif content_files is not None:
                if not isinstance(content_files, list):
                    print_error(f"'{ACTION_CONTENT_FILES}' must be a list")
                    return None
                parts = []
                for file_path in content_files:
                    try:
                        with open(
                            path_join(source_dir, file_path), encoding="utf-8"
                        ) as f:
                            raw = f.read()
                        part = process_variable_substitutions_in_file_contents(
                            raw,
                            prefix=WP_VARIABLES_PREFIX,
                            postfix=WP_VARIABLES_POSTFIX,
                            source=str(file_path),
                        )
                        warn_of_undefined_variables(
                            {str(file_path): part},
                            prefix=WP_VARIABLES_PREFIX,
                            postfix=WP_VARIABLES_POSTFIX,
                            per_source=True,
                        )
                        parts.append(part)
                    except OSError as e:
                        print_error(f"Cannot read '{ACTION_CONTENT_FILES}' file: {e}")
                        return None
                content_val = "".join(parts)
            return NodeWriteFileAction(
                path=cast(str, path),
                content=content_val,
                nodeTypes=node_types,
            )

        case "createWorkers":
            workers_spec = action_spec.get(NODE_WORKERS)
            node_worker_target = None
            if workers_spec is not None:
                node_worker_target = _parse_node_worker_target(workers_spec)
                if node_worker_target is None:
                    return None
            return NodeCreateWorkersAction(
                nodeWorkers=node_worker_target,
                totalWorkers=action_spec.get(NODE_TOTAL_WORKERS),
                nodeTypes=node_types,
            )

        case _:
            print_error(
                f"Unknown action type '{action_type}'; "
                f"expected '{_RUN_COMMAND}', '{_WRITE_FILE}', or '{_CREATE_WORKERS}'"
            )
            return None


def _parse_actions(
    action_specs: list[dict], source_dir: str
) -> list[NodeAction] | None:
    """
    Parse a list of action dicts. Returns None if any action fails to parse.
    """
    actions = []
    for spec in action_specs:
        action = _parse_action(spec, source_dir)
        if action is None:
            return None
        actions.append(action)
    return actions


def _parse_action_groups(
    group_specs: list[dict],
    source_dir: str,
) -> list[NodeActionGroup] | None:
    """
    Parse a list of action group dicts into SDK NodeActionGroup objects.
    """
    groups = []
    for group_spec in group_specs:
        action_specs = group_spec.get(ACTIONS, [])
        actions = _parse_actions(action_specs, source_dir)
        if actions is None:
            return None
        groups.append(NodeActionGroup(actions=actions))
    return groups


def _load_spec(ctx: RunContext, spec_file: str) -> dict | None:
    """
    Load and parse a node action spec file (JSON or Jsonnet),
    applying variable substitutions with the worker-pool prefix/postfix.
    """
    spec = load_specification(
        spec_file,
        "Node Action",
        family=Family.NODE_ACTIONS,
        jsonnet_dry_run=bool(ctx.args.jsonnet_dry_run),
        validate=bool(ctx.args.validate),
        prefix=WP_VARIABLES_PREFIX,
        postfix=WP_VARIABLES_POSTFIX,
        other_extensions_as_json=True,
    )

    if not isinstance(spec, dict):
        print_error(f"Spec file '{spec_file}' must be a JSON object")
        return None

    return spec


def _submission_error(
    e: Exception,
    node_id: str | None = None,
    specific_nodes: bool = False,
) -> str:
    """
    Return a human-friendly message for a node action submission error.
    """
    msg = str(e)
    if "No available nodes" in msg:
        if node_id:
            return f"Node '{node_id}' is not available (is it running?)"
        if specific_nodes:
            return "None of the selected nodes are available (are they running?)"
        return (
            "No nodes matched the 'nodeTypes' filter; "
            "check that node types are correctly defined in the Worker Pool specification"
        )
    return f"Failed to submit: {e}"


def _invalid(spec_file: str) -> ReportedFailure:
    """
    The failure for a specification whose faults have been reported: the
    command exits 1 without submitting anything.
    """
    return ReportedFailure(
        ValueError(f"Node Action specification '{spec_file}' is not valid")
    )


def _after_failure(
    e: Exception, not_attempted: list[str], submission: _SubmissionRecord
) -> None:
    """
    Having recorded a failed submission: if the failure is the session's,
    record the nodes not yet attempted as skipped and raise ReportedFailure,
    which exits with the failure's own code.
    """
    if classify(e) not in SESSION_FAILURES:
        return
    wp_id, _, groups, actions = submission
    if not_attempted:
        print_warning(
            f"Not attempting the remaining {len(not_attempted)} node(s),"
            " which would fail in the same way"
        )
        _record_submission(
            wp_id, not_attempted, groups, actions, "skipped", f"not attempted: {e}"
        )
    raise ReportedFailure(e)


@dataclass(frozen=True)
class _ParsedActions:
    """
    A specification's actions: grouped, or a flat list.
    """

    action_groups: list[NodeActionGroup] | None
    actions: list[NodeAction]
    group_count: int | None
    action_count: int

    @property
    def what(self) -> str:
        if self.action_groups is not None:
            return f"{self.group_count} action group(s)"
        return f"{self.action_count} action(s)"


def _submit_actions(ctx: RunContext):
    """
    Load a node action spec and submit actions to the target worker pool/nodes.
    """
    spec_file = cast(str, ctx.args.node_action_spec)
    spec = _load_spec(ctx, spec_file)
    if spec is None:
        raise _invalid(spec_file)

    # Resolve the directory to use when opening contentFile(s).
    # Priority: --content-path > spec file's directory > config file directory.
    source_dir = (
        ctx.args.content_path or dirname(abspath(spec_file)) or config_file_dir() or "."
    )

    # The actions are parsed before anything is looked up, so that a faulty
    # specification fails first
    parsed = _parse_spec_actions(spec, spec_file, source_dir)

    pool, node_ids, skipped = _resolve_targets(ctx)
    wp_id = cast(str, pool.id)
    submission: _SubmissionRecord = (
        wp_id,
        node_ids,
        parsed.group_count,
        parsed.action_count,
    )
    if skipped:
        _record_submission(
            wp_id,
            skipped,
            parsed.group_count,
            parsed.action_count,
            "skipped",
            "node finished",
        )
    if node_ids is not None and not node_ids:
        print_info("No nodes to submit Node Actions to")
        return

    target_desc = "all nodes" if node_ids is None else f"{len(node_ids)} node(s)"
    if not confirmed(
        f"Submit {parsed.what} to {target_desc} in Worker Pool {_pool_label(pool)}?"
    ):
        _record_submission(*submission, "skipped")
        return

    submitted: list[str] | None
    if parsed.action_groups is not None:
        if not _submit_grouped(ctx, pool, node_ids, parsed, submission, target_desc):
            return
        submitted = node_ids
    elif node_ids is None:
        if not _submit_to_all_nodes(ctx, pool, parsed, submission):
            return
        submitted = None
    else:
        submitted = _submit_to_each_node(ctx, wp_id, node_ids, parsed, submission)

    if ctx.args.follow:
        _follow_submitted(ctx, wp_id, submitted)


def _parse_spec_actions(spec: dict, spec_file: str, source_dir: str) -> _ParsedActions:
    """
    The specification's actions, or its faults reported and the failure raised.
    """
    if ACTION_GROUPS in spec:
        group_specs = spec[ACTION_GROUPS]
        if not isinstance(group_specs, list):
            print_error(f"'{ACTION_GROUPS}' must be a list")
            raise _invalid(spec_file)
        action_groups = _parse_action_groups(group_specs, source_dir)
        if action_groups is None:
            raise _invalid(spec_file)
        return _ParsedActions(
            action_groups=action_groups,
            actions=[],
            group_count=len(action_groups),
            action_count=sum(len(group.actions or []) for group in action_groups),
        )
    if ACTIONS in spec:
        action_specs = spec[ACTIONS]
        if not isinstance(action_specs, list):
            print_error(f"'{ACTIONS}' must be a list")
            raise _invalid(spec_file)
        actions = _parse_actions(action_specs, source_dir)
        if actions is None:
            raise _invalid(spec_file)
        return _ParsedActions(
            action_groups=None,
            actions=actions,
            group_count=None,
            action_count=len(actions),
        )
    print_error(f"Spec must contain either '{ACTIONS}' or '{ACTION_GROUPS}'")
    raise _invalid(spec_file)


def _submit_grouped(
    ctx: RunContext,
    pool: _Pool,
    node_ids: list[str] | None,
    parsed: _ParsedActions,
    submission: _SubmissionRecord,
    target_desc: str,
) -> bool:
    """
    Submit the action groups in one call; False if it failed, having
    reported and recorded the failure.
    """
    action_groups = cast(list[NodeActionGroup], parsed.action_groups)
    # The platform requires NodeIdFilter.LIST on every action when
    # node_id_filter_list is provided.
    if node_ids:
        for group in action_groups:
            for action in group.actions or []:
                action.nodeIdFilter = NodeIdFilter.LIST
    try:
        ctx.client.worker_pool_client.add_node_actions_grouped_by_id(
            cast(str, pool.id),
            action_groups=action_groups,
            node_id_filter_list=node_ids,
        )
    except Exception as e:
        error = _submission_error(e, specific_nodes=bool(node_ids))
        print_error(error)
        _record_submission(*submission, "failed", error=error)
        _after_failure(e, [], submission)
        return False
    print_info(
        f"Submitted {parsed.what} to {target_desc} in Worker Pool {_pool_label(pool)}"
    )
    _record_submission(*submission, "submitted")
    return True


def _submit_to_all_nodes(
    ctx: RunContext,
    pool: _Pool,
    parsed: _ParsedActions,
    submission: _SubmissionRecord,
) -> bool:
    """
    Submit the actions to every node in the pool in one call; False if it
    failed, having reported and recorded the failure.
    """
    try:
        ctx.client.worker_pool_client.add_node_actions_by_id(
            cast(str, pool.id), *parsed.actions
        )
    except Exception as e:
        error = _submission_error(e)
        print_error(error)
        _record_submission(*submission, "failed", error)
        _after_failure(e, [], submission)
        return False
    print_info(
        f"Submitted {parsed.what} to all nodes in Worker Pool {_pool_label(pool)}"
    )
    _record_submission(*submission, "submitted")
    return True


def _submit_to_each_node(
    ctx: RunContext,
    wp_id: str,
    node_ids: list[str],
    parsed: _ParsedActions,
    submission: _SubmissionRecord,
) -> list[str]:
    """
    Submit the actions to each node in turn, returning the nodes they were
    submitted to; a node that fails is reported and recorded, and the rest
    are still tried unless the failure is the session's.
    """
    submitted = []
    for index, node_id in enumerate(node_ids):
        try:
            ctx.client.worker_pool_client.add_node_actions_for_node_by_id(
                wp_id, node_id, *parsed.actions
            )
        except Exception as e:
            error = _submission_error(e, node_id=node_id)
            print_error(error)
            _record_submission(
                wp_id, [node_id], None, parsed.action_count, "failed", error
            )
            _after_failure(e, node_ids[index + 1 :], submission)
            continue
        print_info(f"Submitted {parsed.what} to node {node_id}")
        _record_submission(wp_id, [node_id], None, parsed.action_count, "submitted")
        submitted.append(node_id)
    return submitted


def _follow_submitted(ctx: RunContext, wp_id: str, submitted: list[str] | None) -> None:
    """
    Follow the queues of the nodes the actions were submitted to; None is
    every node in the pool.
    """
    follow_ids = (
        submitted
        if submitted is not None
        else [cast(str, n.id) for n in _get_nodes_for_pool(ctx, wp_id)]
    )
    if follow_ids:
        try:
            _follow_node_actions(ctx, follow_ids, initial_delay=True)
        except _FollowTimedOut as e:
            raise ReportedFailure(TimeoutError(str(e)))
        except _QueuesNotFetched as e:
            raise ReportedFailure(RuntimeError(str(e)))


def _follow_node_actions(
    ctx: RunContext, node_ids: list[str], initial_delay: bool = False
) -> list[tuple[str, NodeActionQueueSnapshot]]:
    """
    Poll the node action queue for each node until all reach EMPTY or FAILED
    status, printing the table at each poll (not under '--json'), and return
    the final rows. With --timeout, stop polling after that many seconds:
    the rows are then each node's latest, and the caller raises
    _FollowTimedOut once it has recorded them. A node whose queue cannot be
    fetched is reported and no longer polled, and once the rest have
    finished _QueuesNotFetched is raised, carrying the final rows, as for a
    timeout.
    """
    pending = set(node_ids)
    done: dict[str, NodeActionQueueSnapshot] = {}
    latest: dict[str, NodeActionQueueSnapshot] = {}
    not_fetched: list[str] = []
    timeout = ctx.args.timeout
    deadline = None if timeout is None else time.monotonic() + timeout
    print_info(f"Following node action queue(s) for {len(pending)} node(s)...")
    if initial_delay:
        time.sleep(0.5)  # Allow submission to stabilize

    while pending:
        completed = set()
        live_rows: list[tuple[str, NodeActionQueueSnapshot]] = []
        for node_id in sorted(pending):
            try:
                snapshot: NodeActionQueueSnapshot = (
                    ctx.client.worker_pool_client.get_node_actions_by_id(node_id)
                )
            except Exception as e:
                if classify(e) in SESSION_FAILURES:
                    raise
                error = "not found" if is_http_not_found(e) else str(e)
                print_error(f"Failed to get status for node '{node_id}': {error}")
                completed.add(node_id)
                not_fetched.append(node_id)
                continue

            live_rows.append((node_id, snapshot))
            latest[node_id] = snapshot
            if snapshot.status in (
                NodeActionQueueStatus.EMPTY,
                NodeActionQueueStatus.FAILED,
            ):
                completed.add(node_id)
                done[node_id] = snapshot

        live_node_ids = {r[0] for r in live_rows}
        done_rows = [
            (nid, snap) for nid, snap in done.items() if nid not in live_node_ids
        ]
        all_rows = done_rows + live_rows
        if all_rows and not json_requested():
            print_node_action_queue_table(all_rows)
        pending -= completed
        if pending and deadline is not None and time.monotonic() >= deadline:
            print_warning(
                f"Stopped following after {timeout:,d} second(s): the queue(s) of"
                f" {len(pending)} node(s) had not finished"
            )
            rows = {**latest, **done}
            raise _FollowTimedOut(sorted(rows.items(), key=lambda row: row[0]))
        if pending:
            time.sleep(NODE_ACTION_QUEUE_POLL_INTERVAL)

    final_rows = sorted(done.items(), key=lambda row: row[0])
    if not_fetched:
        raise _QueuesNotFetched(final_rows, len(not_fetched))
    print_info("All node action queues have finished.")
    return final_rows


class _FollowTimedOut(Exception):
    """
    --timeout ran out before every queue finished: 'rows' are each node's
    latest queue, for the caller to record before the failure is raised.
    """

    def __init__(self, rows: list[tuple[str, NodeActionQueueSnapshot]]):
        super().__init__("Node action queue(s) had not finished when --timeout ran out")
        self.rows = rows


class _QueuesNotFetched(Exception):
    """
    The queues of some nodes could not be fetched while following, each
    reported as it failed: 'rows' are the others' final queues, for the
    caller to record before the failure is raised.
    """

    def __init__(self, rows: list[tuple[str, NodeActionQueueSnapshot]], count: int):
        super().__init__(
            f"The node action queue(s) of {count} node(s) could not be fetched"
        )
        self.rows = rows


def _show_status(ctx: RunContext):
    """
    Show the node action queue status for selected node(s).
    """
    node_ids = _without_duplicates(ctx.args.node_ids or [])
    if not node_ids:
        pool = _resolve_worker_pool(ctx)
        wp_id = cast(str, pool.id)
        if ctx.args.all_nodes:
            node_ids = [cast(str, n.id) for n in _get_nodes_for_pool(ctx, wp_id)]
            if not node_ids:
                print_warning(f"No running nodes in Worker Pool {_pool_label(pool)}")
                return
        else:
            node_ids = _choose_nodes(ctx, pool)

    if ctx.args.follow:
        try:
            final_rows = _follow_node_actions(ctx, node_ids)
        except _FollowTimedOut as e:
            if json_requested():
                _record_queues(e.rows)
            raise ReportedFailure(TimeoutError(str(e)))
        except _QueuesNotFetched as e:
            if json_requested():
                _record_queues(e.rows)
            raise ReportedFailure(RuntimeError(str(e)))
        if json_requested():
            _record_queues(final_rows)
        return

    rows: list[tuple[str, NodeActionQueueSnapshot]] = []
    failures: list[Exception] = []
    for node_id in node_ids:
        try:
            snapshot: NodeActionQueueSnapshot = (
                ctx.client.worker_pool_client.get_node_actions_by_id(node_id)
            )
        except Exception as e:
            if classify(e) in SESSION_FAILURES:
                raise
            error = "not found" if is_http_not_found(e) else str(e)
            print_error(f"Failed to get the node action queue for '{node_id}': {error}")
            failures.append(e)
            continue

        # Under '--json' the table's rows, '--details' or not
        if ctx.args.details and not json_requested():
            print_info(f"Node action queue for node '{node_id}':")
            print_yd_object(snapshot)
        else:
            rows.append((node_id, snapshot))

    if json_requested():
        _record_queues(rows)
    elif rows:
        print_node_action_queue_table(rows)
    if failures:
        raise ReportedFailure(
            RuntimeError(
                f"The node action queue(s) of {len(failures)} node(s) could not be"
                " fetched"
            )
        )


# Entry point
if __name__ == "__main__":
    main()
