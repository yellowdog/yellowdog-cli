#!/usr/bin/env python3

"""
A script to submit Node Actions to Worker Pool nodes.
"""

import time
from os.path import abspath, dirname
from os.path import join as path_join
from typing import Any, cast

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
    NodeWorkerTarget,
    NodeWriteFileAction,
    WorkerPool,
    WorkerPoolSummary,
)

from yellowdog_cli.utils.entity_utils import (
    get_worker_pool_id_by_name,
    get_worker_pool_summaries,
)
from yellowdog_cli.utils.interactive import confirmed, select
from yellowdog_cli.utils.load_config import CONFIG_FILE_DIR
from yellowdog_cli.utils.printing import (
    print_error,
    print_info,
    print_node_action_queue_table,
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
from yellowdog_cli.utils.settings import (
    NODE_ACTION_QUEUE_POLL_INTERVAL,
    WP_VARIABLES_POSTFIX,
    WP_VARIABLES_PREFIX,
)
from yellowdog_cli.utils.variables import (
    load_json_file_with_variable_substitutions,
    load_jsonnet_file_with_variable_substitutions,
    process_variable_substitutions_in_file_contents,
    warn_of_undefined_variables,
)
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, CONFIG_COMMON, main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

# Action type strings used in spec files
_RUN_COMMAND = "runCommand"
_WRITE_FILE = "writeFile"
_CREATE_WORKERS = "createWorkers"


@main_wrapper
def main():
    if ARGS_PARSER.status:
        _show_status()
    else:
        _submit_actions()


def _get_worker_pool_id_for_node(node_id: str) -> str | None:
    """
    Look up the worker pool ID that owns the given node.
    """
    try:
        node = CLIENT.worker_pool_client.get_node_by_id(node_id)
    except Exception as e:
        print_error(f"Node '{node_id}' not found: {e}")
        return None
    return node.workerPoolId


def _resolve_worker_pool_id() -> str | None:
    """
    Resolve the worker pool ID. Uses --worker-pool if given, otherwise
    falls back to interactive selection.
    """
    wp_name = ARGS_PARSER.worker_pool_name

    if wp_name is not None:
        if get_ydid_type(wp_name) == YDIDType.WORKER_POOL:
            return wp_name
        if wp_name.startswith("ydid:"):
            print_error(f"'{wp_name}' is not a valid Worker Pool ID")
            return None
        wp_id = get_worker_pool_id_by_name(CLIENT, wp_name, CONFIG_COMMON.namespace)
        if wp_id is None:
            print_warning(f"Worker Pool '{wp_name}' not found")
        return wp_id

    # Interactive selection
    summaries: list[WorkerPoolSummary] = get_worker_pool_summaries(
        CLIENT,
        namespace=CONFIG_COMMON.namespace,
        name=CONFIG_COMMON.name_tag if CONFIG_COMMON.name_tag else None,
    )

    if not summaries:
        print_warning(f"No Worker Pools found in namespace '{CONFIG_COMMON.namespace}'")
        return None

    summaries = cast(
        list[WorkerPoolSummary],
        select(
            CLIENT,
            cast(list[Any], summaries),
            single_result=True,
            force_interactive=True,
            override_quiet=True,
        ),
    )
    if not summaries:
        return None

    if len(summaries) > 1:
        print_warning("Multiple Worker Pools selected; using the first")

    wp_id = summaries[0].id
    if wp_id is None:
        print_warning("Selected Worker Pool has no ID")
        return None
    wp: WorkerPool = CLIENT.worker_pool_client.get_worker_pool_by_id(
        worker_pool_id=wp_id
    )
    return wp.id


def _get_nodes_for_pool(wp_id: str) -> list[Node]:
    """
    Return all nodes registered to the given worker pool.
    """
    return CLIENT.worker_pool_client.get_nodes(
        NodeSearch(workerPoolId=wp_id)
    ).list_all()


def _resolve_node_ids(wp_id: str) -> list[str] | None:
    """
    Resolve target node IDs. Uses --node if given; otherwise prompts
    interactively from the pool's current nodes.
    Returns None if no nodes are selected or an error occurs.
    """
    node_ids = ARGS_PARSER.node_ids
    if node_ids:
        return node_ids

    # Interactive selection from the pool's current nodes
    nodes = _get_nodes_for_pool(wp_id)

    if not nodes:
        print_warning(f"No nodes found in Worker Pool '{wp_id}'")
        return None

    selected: list[Node] = cast(
        list[Node],
        select(
            CLIENT,
            cast(list[Any], nodes),
            force_interactive=True,
            sort_objects=False,
            override_quiet=True,
        ),
    )
    if not selected:
        return None

    return [n.id for n in selected if n.id is not None]


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
                    with open(path_join(source_dir, cast(str, content_file))) as f:
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
                        with open(path_join(source_dir, file_path)) as f:
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


def _load_spec(spec_file: str) -> dict | None:
    """
    Load and parse a node action spec file (JSON or Jsonnet),
    applying variable substitutions with the worker-pool prefix/postfix.
    """
    if spec_file.lower().endswith(".jsonnet"):
        spec = load_jsonnet_file_with_variable_substitutions(
            spec_file,
            prefix=WP_VARIABLES_PREFIX,
            postfix=WP_VARIABLES_POSTFIX,
        )
    else:
        spec = load_json_file_with_variable_substitutions(
            spec_file,
            prefix=WP_VARIABLES_PREFIX,
            postfix=WP_VARIABLES_POSTFIX,
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


def _submit_actions():
    """
    Load a node action spec and submit actions to the target worker pool/nodes.
    """
    spec_file = ARGS_PARSER.node_action_spec
    if spec_file is None:
        print_error("A spec file is required (use --actions)")
        return

    spec = _load_spec(spec_file)
    if spec is None:
        return

    # Resolve the directory to use when opening contentFile(s).
    # Priority: --content-path > spec file's directory > config file directory.
    source_dir = (
        ARGS_PARSER.content_path
        or (dirname(abspath(spec_file)) if spec_file else None)
        or CONFIG_FILE_DIR
        or "."
    )

    # If explicit node YDIDs are given without --worker-pool, derive the pool
    # from the first node rather than prompting interactively.
    node_ids_arg = ARGS_PARSER.node_ids
    if (
        node_ids_arg
        and all(get_ydid_type(n) == YDIDType.NODE for n in node_ids_arg)
        and ARGS_PARSER.worker_pool_name is None
    ):
        wp_id = _get_worker_pool_id_for_node(node_ids_arg[0])
    else:
        wp_id = _resolve_worker_pool_id()
    if wp_id is None:
        return

    # Grouped actions
    if ACTION_GROUPS in spec:
        group_specs = spec[ACTION_GROUPS]
        if not isinstance(group_specs, list):
            print_error(f"'{ACTION_GROUPS}' must be a list")
            return

        action_groups = _parse_action_groups(group_specs, source_dir)
        if action_groups is None:
            return

        if ARGS_PARSER.all_nodes:
            node_id_filter_list = None
            target_desc = "all nodes"
        else:
            node_id_filter_list = _resolve_node_ids(wp_id)
            if not node_id_filter_list:
                return
            target_desc = f"{len(node_id_filter_list)} node(s)"

        # The platform requires NodeIdFilter.LIST on every action when
        # node_id_filter_list is provided.
        if node_id_filter_list:
            for group in action_groups:
                for action in group.actions or []:
                    action.nodeIdFilter = NodeIdFilter.LIST

        if not confirmed(
            f"Submit {len(action_groups)} action group(s) to "
            f"Worker Pool '{wp_id}' targeting {target_desc}?"
        ):
            return

        try:
            CLIENT.worker_pool_client.add_node_actions_grouped_by_id(
                wp_id,
                action_groups=action_groups,
                node_id_filter_list=node_id_filter_list,
            )
            print_info(
                f"Submitted {len(action_groups)} action group(s) to "
                f"Worker Pool '{wp_id}'"
            )
        except Exception as e:
            print_error(_submission_error(e, specific_nodes=bool(node_id_filter_list)))
            return

        if ARGS_PARSER.follow:
            follow_ids = node_id_filter_list or [
                n.id for n in _get_nodes_for_pool(wp_id) if n.id is not None
            ]
            if follow_ids:
                _follow_node_actions(follow_ids, initial_delay=True)
        return

    # Actions
    if ACTIONS in spec:
        action_specs = spec[ACTIONS]
        if not isinstance(action_specs, list):
            print_error(f"'{ACTIONS}' must be a list")
            return

        actions = _parse_actions(action_specs, source_dir)
        if actions is None:
            return

        if ARGS_PARSER.all_nodes:
            if not confirmed(
                f"Submit {len(actions)} action(s) to all nodes in "
                f"Worker Pool '{wp_id}'?"
            ):
                return
            try:
                CLIENT.worker_pool_client.add_node_actions_by_id(wp_id, *actions)
                print_info(
                    f"Submitted {len(actions)} action(s) to all nodes in "
                    f"Worker Pool '{wp_id}'"
                )
            except Exception as e:
                print_error(_submission_error(e))
                return

            if ARGS_PARSER.follow:
                all_node_ids = [
                    n.id for n in _get_nodes_for_pool(wp_id) if n.id is not None
                ]
                if all_node_ids:
                    _follow_node_actions(all_node_ids, initial_delay=True)
        else:
            # Specific nodes: --node IDs or interactive selection
            node_ids = _resolve_node_ids(wp_id)
            if not node_ids:
                return

            if not confirmed(
                f"Submit {len(actions)} action(s) to "
                f"{len(node_ids)} node(s) in Worker Pool '{wp_id}'?"
            ):
                return

            submitted_node_ids = []
            for node_id in node_ids:
                try:
                    CLIENT.worker_pool_client.add_node_actions_for_node_by_id(
                        wp_id, node_id, *actions
                    )
                    print_info(
                        f"Submitted {len(actions)} action(s) to node '{node_id}'"
                    )
                    submitted_node_ids.append(node_id)
                except Exception as e:
                    print_error(_submission_error(e, node_id=node_id))

            if ARGS_PARSER.follow and submitted_node_ids:
                _follow_node_actions(submitted_node_ids, initial_delay=True)
        return

    print_error(f"Spec must contain either '{ACTIONS}' or '{ACTION_GROUPS}'")


def _follow_node_actions(node_ids: list[str], initial_delay: bool = False) -> None:
    """
    Poll the node action queue for each node until all reach EMPTY or FAILED status.
    """
    pending = set(node_ids)
    done: dict[str, NodeActionQueueSnapshot] = {}
    print_info(f"Following node action queue(s) for {len(pending)} node(s)...")
    if initial_delay:
        time.sleep(0.5)  # Allow submission to stabilize

    while pending:
        completed = set()
        live_rows: list[tuple[str, NodeActionQueueSnapshot]] = []
        for node_id in sorted(pending):
            try:
                snapshot: NodeActionQueueSnapshot = (
                    CLIENT.worker_pool_client.get_node_actions_by_id(node_id)
                )
            except Exception as e:
                print_error(f"Failed to get status for node '{node_id}': {e}")
                completed.add(node_id)
                continue

            live_rows.append((node_id, snapshot))
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
        if all_rows:
            print_node_action_queue_table(all_rows)
        pending -= completed
        if pending:
            time.sleep(NODE_ACTION_QUEUE_POLL_INTERVAL)

    print_info("All node action queues have finished.")


def _show_status():
    """
    Show the node action queue status for selected node(s).
    """
    node_ids = ARGS_PARSER.node_ids
    if not node_ids:
        wp_id = _resolve_worker_pool_id()
        if wp_id is None:
            return
        if ARGS_PARSER.all_nodes:
            node_ids = [n.id for n in _get_nodes_for_pool(wp_id) if n.id is not None]
            if not node_ids:
                print_warning(f"No nodes found in Worker Pool '{wp_id}'")
                return
        else:
            node_ids = _resolve_node_ids(wp_id)
            if not node_ids:
                return

    if ARGS_PARSER.follow:
        _follow_node_actions(node_ids)
        return

    rows: list[tuple[str, NodeActionQueueSnapshot]] = []
    for node_id in node_ids:
        try:
            snapshot: NodeActionQueueSnapshot = (
                CLIENT.worker_pool_client.get_node_actions_by_id(node_id)
            )
        except Exception as e:
            print_error(f"Failed to get node action status for '{node_id}': {e}")
            continue

        if ARGS_PARSER.details:
            print_info(f"Node action queue for node '{node_id}':")
            print_yd_object(snapshot)
        else:
            rows.append((node_id, snapshot))

    if rows:
        print_node_action_queue_table(rows)


# Entry point
if __name__ == "__main__":
    main()
