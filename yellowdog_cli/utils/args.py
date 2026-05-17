"""
Class to parse command line arguments for all commands.
"""

import argparse
import sys

from yellowdog_cli._version import __version__
from yellowdog_cli.utils.settings import (
    DEFAULT_PARALLEL_TASK_BATCH_UPLOAD_THREADS,
    DEFAULT_URL,
    ET_ALLOWANCES,
    ET_APPLICATIONS,
    ET_ATTRIBUTE_DEFINITIONS,
    ET_COMPUTE_REQUIREMENT_TEMPLATES,
    ET_COMPUTE_REQUIREMENTS,
    ET_COMPUTE_SOURCE_TEMPLATES,
    ET_GROUPS,
    ET_IMAGE_FAMILIES,
    ET_INSTANCES,
    ET_KEYRINGS,
    ET_NAMESPACE_POLICIES,
    ET_NAMESPACES,
    ET_NODES,
    ET_PERMISSIONS,
    ET_ROLES,
    ET_TASK_GROUPS,
    ET_TASKS,
    ET_USERS,
    ET_WORK_REQUIREMENTS,
    ET_WORKER_POOLS,
    ET_WORKERS,
)
from yellowdog_cli.version import DOCS_URL


def docs():
    print(
        f"Online documentation for Python Examples v{__version__}: {DOCS_URL}",
        flush=True,
    )


def allow_missing_attribute(func):
    """
    Wrapper function to return None if an option isn't enabled.
    """

    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except AttributeError:
            return None

    return wrapper


ENTITY_TYPES = [
    ET_ALLOWANCES,
    ET_APPLICATIONS,
    ET_ATTRIBUTE_DEFINITIONS,
    ET_COMPUTE_REQUIREMENT_TEMPLATES,
    ET_COMPUTE_REQUIREMENTS,
    ET_COMPUTE_SOURCE_TEMPLATES,
    ET_GROUPS,
    ET_IMAGE_FAMILIES,
    ET_INSTANCES,
    ET_KEYRINGS,
    ET_NAMESPACE_POLICIES,
    ET_NAMESPACES,
    ET_NODES,
    ET_PERMISSIONS,
    ET_ROLES,
    ET_TASK_GROUPS,
    ET_TASKS,
    ET_USERS,
    ET_WORK_REQUIREMENTS,
    ET_WORKER_POOLS,
    ET_WORKERS,
]

# Single uppercase letter synonyms for each entity type.
SYNONYMS: dict[str, str] = {
    "A": ET_ALLOWANCES,
    "B": ET_APPLICATIONS,
    "D": ET_ATTRIBUTE_DEFINITIONS,
    "C": ET_COMPUTE_REQUIREMENT_TEMPLATES,
    "R": ET_COMPUTE_REQUIREMENTS,
    "S": ET_COMPUTE_SOURCE_TEMPLATES,
    "G": ET_GROUPS,
    "I": ET_IMAGE_FAMILIES,
    "E": ET_INSTANCES,
    "K": ET_KEYRINGS,
    "L": ET_NAMESPACE_POLICIES,
    "M": ET_NAMESPACES,
    "N": ET_NODES,
    "X": ET_PERMISSIONS,
    "O": ET_ROLES,
    "H": ET_TASK_GROUPS,
    "T": ET_TASKS,
    "U": ET_USERS,
    "W": ET_WORK_REQUIREMENTS,
    "P": ET_WORKER_POOLS,
    "F": ET_WORKERS,
}

# For help text: "allowances (A)", "applications (B)", ...
_SYNONYM_REVERSE: dict[str, str] = {v: k for k, v in SYNONYMS.items()}
_ENTITY_TYPE_HELP = ", ".join(f"{t} ({_SYNONYM_REVERSE[t]})" for t in ENTITY_TYPES)


def resolve_entity_type(value: str) -> str:
    """
    Resolve an entity type string to its canonical form.

    Checks single-letter uppercase synonyms first, then falls back to
    unambiguous prefix matching. Raises argparse.ArgumentTypeError if the
    value is ambiguous or unrecognised.
    """
    if value in SYNONYMS:
        return SYNONYMS[value]
    matches = [e for e in ENTITY_TYPES if e.startswith(value)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise argparse.ArgumentTypeError(
            f"'{value}' is ambiguous — matches: {', '.join(matches)}"
        )
    raise argparse.ArgumentTypeError(
        f"unknown entity type '{value}'; valid types: {_ENTITY_TYPE_HELP}"
    )


class CLIParser:
    def __init__(self, description: str | None = None):
        """
        Create the argument parser, and parse the command
        line arguments. Argument availability depends on module.
        """
        self.tag_required = False
        self.namespace_required = False

        parser = argparse.ArgumentParser(description=description)

        # Common arguments across all commands
        parser.add_argument(
            "--docs",
            action="store_true",
            required=False,
            help="provide a link to the documentation for this version",
        )
        parser.add_argument(
            "--config",
            "-c",
            required=False,
            type=str,
            help=(
                "configuration file in TOML format; "
                "the default to use is 'config.toml' in the current directory"
            ),
            metavar="<config_file.toml>",
        )
        parser.add_argument(
            "--key",
            "-k",
            type=str,
            required=False,
            help="the application key ID",
            metavar="<app-key-id>",
        )
        parser.add_argument(
            "--secret",
            "-s",
            required=False,
            type=str,
            help="the application key secret",
            metavar="<app-key-secret>",
        )
        parser.add_argument(
            "--url",
            "-u",
            type=str,
            required=False,
            help=f"the YellowDog Platform API URL (defaults to '{DEFAULT_URL}')",
            metavar="<url>",
        )
        parser.add_argument(
            "--debug",
            action="store_true",
            required=False,
            help="display the Python stack trace on error",
        )
        parser.add_argument(
            "--pac",
            action="store_true",
            required=False,
            help="enable PAC (proxy auto-configuration) support",
        )
        parser.add_argument(
            "--no-format",
            "--nf",
            action="store_true",
            required=False,
            help="disable colouring and text wrapping in command output",
        )
        parser.add_argument(
            "--quiet",
            "-q",
            action="store_true",
            required=False,
            help="suppress (non-error, non-interactive) status and progress messages",
        )
        parser.add_argument(
            "--env-override",
            action="store_true",
            required=False,
            help="values in '.env' file override values in the environment",
        )
        parser.add_argument(
            "--print-pid",
            "--pp",
            action="store_true",
            required=False,
            help="include the process ID of this CLI invocation alongside timestamp in logging messages",
        )
        parser.add_argument(
            "--no-config",
            "--nc",
            action="store_true",
            required=False,
            help="ignore the contents of any TOML configuration file (even if specified on the command line)",
        )
        parser.add_argument(
            "--property",
            type=str,
            required=False,
            action="append",
            help=(
                "override a TOML configuration property; "
                "format: 'section.key=value', e.g. "
                "'workRequirement.workerTags=[\"mytag\"]'; "
                "can be supplied multiple times"
            ),
            metavar="<section.key=value>",
        )

        # Module-specific arguments

        # yd-* (all except yd-compare)
        if not any(module in sys.argv[0] for module in ["compare"]):
            parser.add_argument(
                "--variable",
                "-v",
                type=str,
                required=False,
                action="append",
                help=(
                    "user-defined variable substitution; the option can be supplied"
                    " multiple times, one per variable"
                ),
                metavar="<var1=v1>",
            )

        # yd-* (all except yd-boost, yd-cloudwizard, yd-follow, yd-list, yd-compare, yd-wait)
        if not any(
            module in sys.argv[0]
            for module in [
                "boost",
                "cloudwizard",
                "follow",
                "list",
                "compare",
                "wait",
            ]
        ):
            self.namespace_required = True
            parser.add_argument(
                "--namespace",
                "-n",
                type=str,
                required=False,
                nargs="?",
                const="",
                help=(
                    "the namespace to use when specifying entities;"
                    " this is set to '' if the option is provided without a value"
                ),
                metavar="<namespace>",
            )
            self.tag_required = True
            parser.add_argument(
                "--tag",
                "-t",
                type=str,
                required=False,
                nargs="?",
                const="",
                help=(
                    "the tag to use when naming, tagging, or selecting entities;"
                    " this is set to '' if the option is provided without a value"
                ),
                metavar="<tag>",
            )

        # yd-list
        if any(module in sys.argv[0] for module in ["list"]):
            parser.add_argument(
                "--namespace",
                "-n",
                type=str,
                required=False,
                nargs="?",
                const="",
                # default="",
                help="the namespace to use when listing entities",
                metavar="<namespace>",
            )
            # Tag attribute is defaulted to "" when using 'yd-list'
            parser.add_argument(
                "--tag",
                "-t",
                type=str,
                required=False,
                nargs="?",
                const="",
                default="",
                help="the tag to search when listing entities",
                metavar="<tag>",
            )
            _list_output = parser.add_mutually_exclusive_group()
            _list_output.add_argument(
                "--ids-only",
                "-D",
                action="store_true",
                required=False,
                help="list the YellowDog IDs only",
            )
            _list_output.add_argument(
                "--json",
                "-J",
                action="store_true",
                required=False,
                help="emit results as a plain JSON array (suppresses table formatting)",
            )

        # yd-submit
        if any(module in sys.argv[0] for module in ["submit"]):
            parser.add_argument(
                "--work-requirement",
                "-r",
                type=str,
                required=False,
                help=(
                    "work requirement definition file in JSON or Jsonnet format"
                    " (deprecated: please use positional argument instead)"
                ),
                metavar="<work_requirement.json>",
            )
            parser.add_argument(
                "--json-raw",
                "-j",
                type=str,
                required=False,
                help="submit a 'raw' JSON work requirement file",
                metavar="<raw_work_requirement.json>",
            )
            parser.add_argument(
                "--follow",
                "-f",
                action="store_true",
                required=False,
                help="follow the work requirement's progress to completion",
            )
            parser.add_argument(
                "--task-type",
                "-T",
                type=str,
                required=False,
                help="the task type to use",
                metavar="<task_type>",
            )
            parser.add_argument(
                "--task-count",
                "-C",
                type=int,
                required=False,
                help="the number of tasks to submit (copies of a single task)",
                metavar="<task_count>",
            )
            parser.add_argument(
                "--task-group-count",
                "-G",
                type=int,
                required=False,
                help="the number of task groups to submit (copies of a single task group)",
                metavar="<task_group_count>",
            )
            parser.add_argument(
                "--task-batch-size",
                "-b",
                type=int,
                required=False,
                help="the batch size for task submission; must be between 1 and 10,000",
                metavar="<batch_size>",
            )
            parser.add_argument(
                "--pause-between-batches",
                "-P",
                nargs="?",
                type=int,
                const=0,
                required=False,
                metavar="<interval_between_batches_in_seconds>",
                help=(
                    "pause for user input between task batch submissions; if no"
                    " pause interval is provided, user input is required to advance; "
                    "only valid when 'parallel-batches=1'"
                ),
            )
            parser.add_argument(
                "--csv-file",
                "-V",
                type=str,
                required=False,
                action="append",
                help="the CSV file(s) from which to read Task data",
                metavar="<data.csv>",
            )
            parser.add_argument(
                "--process-csv-only",
                "-p",
                action="store_true",
                required=False,
                help=(
                    "process CSV variable substitutions only and output the"
                    " intermediate JSON Work Requirement specification"
                ),
            )
            parser.add_argument(
                "--hold",
                "-H",
                action="store_true",
                required=False,
                help="set the work requirement status to 'HELD' on submission",
            )
            parser.add_argument(
                "--parallel-batches",
                "-l",
                type=int,
                required=False,
                help=(
                    "the maximum number of parallel task batch "
                    f"uploads (default={DEFAULT_PARALLEL_TASK_BATCH_UPLOAD_THREADS})"
                    "; set this to '1' for sequential batch upload"
                ),
                metavar="<max_number_of_parallel_batches>",
            )
            parser.add_argument(
                "--empty",
                "-e",
                action="store_true",
                required=False,
                help=(
                    "submit a new Work Requirement with no Task Groups or Tasks;"
                    " use with '--add-to' to populate it later"
                ),
            )
            parser.add_argument(
                "--overwrite",
                "-O",
                action="store_true",
                required=False,
                help=(
                    "overwrite a file if it already exists at the"
                    " remote destination; by default existing files are skipped"
                ),
            )
            parser.add_argument(
                "--add-to",
                "-A",
                type=str,
                required=False,
                help=(
                    "add task groups and/or tasks to an existing work requirement"
                    " specified by name or YellowDog ID"
                ),
                metavar="<work_requirement_name_or_id>",
            )

        # yd-provision / yd-instantiate
        if any(module in sys.argv[0] for module in ["provision", "instantiate"]):
            parser.add_argument(
                "--worker-pool",
                "-p",
                type=str,
                required=False,
                help=(
                    "worker pool definition file in JSON or Jsonnet format"
                    " (deprecated: please use positional argument instead)"
                ),
                metavar="<worker_pool.json>",
            )

        # yd-cancel
        if any(module in sys.argv[0] for module in ["cancel"]):
            parser.add_argument(
                "--abort",
                "-a",
                action="store_true",
                required=False,
                help="abort running tasks with immediate effect",
            )
            parser.add_argument(
                "--follow",
                "-f",
                action="store_true",
                required=False,
                help="follow progress after cancelling the work requirement(s)",
            )

        # yd-start / yd-hold / yd-finish
        if any(
            module in sys.argv[0]
            for module in [
                "start",
                "hold",
                "finish",
            ]
        ):
            parser.add_argument(
                "--follow",
                "-f",
                action="store_true",
                required=False,
                help="follow work requirement events after applying action",
            )

        # yd-cancel / yd-shutdown / yd-terminate / yd-start / yd-hold / yd-finish
        if any(
            module in sys.argv[0]
            for module in [
                "cancel",
                "shutdown",
                "terminate",
                "start",
                "hold",
                "finish",
            ]
        ):
            parser.add_argument(
                "--interactive",
                "-i",
                action="store_true",
                required=False,
                help="list, and interactively select, the items to act on",
            )

        # yd-abort / yd-cancel / yd-shutdown / yd-terminate /
        # yd-resize / yd-cloudwizard / yd-boost / yd-hold / yd-start / yd-list /
        # yd-finish / yd-delete (data client) / yd-nodeaction
        if any(
            module in sys.argv[0]
            for module in [
                "abort",
                "cancel",
                "delete",
                "nodeaction",
                "shutdown",
                "terminate",
                "resize",
                "cloudwizard",
                "boost",
                "hold",
                "start",
                "list",
                "finish",
            ]
        ):
            parser.add_argument(
                "--yes",
                "-y",
                action="store_true",
                required=False,
                help=(
                    "perform modifying/destructive actions without "
                    "requiring user confirmation"
                ),
            )

        # yd-list
        if "list" in sys.argv[0]:
            parser.add_argument(
                "entity_type",
                type=resolve_entity_type,
                metavar="ENTITY_TYPE",
                help=(
                    "type of entity to list; accepts a full name, an unambiguous "
                    "prefix (e.g. 'work-r'), or a single uppercase synonym "
                    "(e.g. 'W'). Valid types: " + _ENTITY_TYPE_HELP
                ),
            )
            parser.add_argument(
                "--reverse",
                action="store_true",
                required=False,
                help="list items in reverse-sorted name order",
            )
            parser.add_argument(
                "--active-only",
                "-l",
                action="store_true",
                required=False,
                help=(
                    "list only active compute requirements / worker pools / work"
                    " requirements"
                ),
            )
            parser.add_argument(
                "--status",
                dest="status_filter",
                action="append",
                required=False,
                help=(
                    "include only entities whose status matches the given value "
                    "(case-insensitive); may be repeated to allow multiple statuses"
                ),
                metavar="<status>",
            )
            parser.add_argument(
                "--public-ips-only",
                action="store_true",
                required=False,
                help="when used with 'instances', lists public IP addresses only",
            )
            parser.add_argument(
                "--details",
                "-d",
                action="store_true",
                required=False,
                help="show the full JSON representation of objects",
            )
            parser.add_argument(
                "--auto-select-all",
                action="store_true",
                required=False,
                help="automatically select all listed objects (implies '--details')",
            )

        # yd-submit / yd-provision / yd-instantiate / yd-create
        if any(
            module in sys.argv[0]
            for module in ["submit", "provision", "instantiate", "create"]
        ):
            parser.add_argument(
                "--dry-run",
                "-D",
                action="store_true",
                required=False,
                help="dry-run the action and print the JSON that would be submitted",
            )

        # yd-instantiate
        if any(module in sys.argv[0] for module in ["instantiate"]):
            parser.add_argument(
                "--compute-requirement",
                "-C",
                type=str,
                required=False,
                help=(
                    "compute requirement definition file in JSON or Jsonnet format"
                    " (deprecated: please use positional argument instead)"
                ),
                metavar="<compute_requirement.json>",
            )
            parser.add_argument(
                "--report",
                "-r",
                action="store_true",
                required=False,
                help="report on a dynamic template test run",
            )

        # yd-admin
        if "admin" in sys.argv[0]:
            parser.add_argument(
                "work_requirement_id",
                metavar="<work_requirement_id>",
                type=str,
                nargs="*",
                help="work requirement to be refreshed",
            )

        # yd-submit / yd-provision / yd-instantiate / yd-create / yd-remove
        if any(
            module in sys.argv[0]
            for module in ["submit", "provision", "instantiate", "create", "remove"]
        ):
            parser.add_argument(
                "--jsonnet-dry-run",
                "-J",
                action="store_true",
                required=False,
                help="dry-run Jsonnet processing into JSON",
            )

        # yd-resize
        if "resize" in sys.argv[0]:
            parser.add_argument(
                "worker_pool",
                metavar="<worker-pool-or-compute-requirement-name-or-ID>",
                type=str,
                help=(
                    "the name or YellowDog ID of the worker pool or compute requirement"
                    " to resize"
                ),
            )
            parser.add_argument(
                "worker_pool_size",
                metavar="<new-node/instance-count>",
                type=int,
                help="the desired number of (total) nodes in the worker pool",
            )
            parser.add_argument(
                "--compute-requirement",
                "-C",
                action="store_true",
                required=False,
                help="resize a compute requirement instead of a worker pool",
            )

        # yd-boost
        if "boost" in sys.argv[0]:
            parser.add_argument(
                "boost_hours",
                metavar="<boost hours>",
                type=int,
                help="the number of hours to boost the allowance by",
            )
            parser.add_argument(
                "allowances",
                metavar="<allowance-ID> [<allowance-ID>]",
                nargs="+",
                type=str,
                help="the YellowDog ID(s) of the allowance(s) to boost",
            )

        # yd-shutdown
        if "shutdown" in sys.argv[0]:
            parser.add_argument(
                "worker_pool_nodes_list",
                nargs="*",
                default="",
                metavar="<worker-pool-name-or-ID/node-id>",
                type=str,
                help="the name(s) or YellowDog ID(s) of the worker pool(s) and/or ID(s) of nodes",
            )
            parser.add_argument(
                "--follow",
                "-f",
                action="store_true",
                required=False,
                help="follow worker pool shutdown to completion",
            )
            parser.add_argument(
                "--terminate",
                "-T",
                action="store_true",
                required=False,
                help="also immediately terminate associated compute requirement(s)",
            )

        # yd-terminate
        if "terminate" in sys.argv[0]:
            parser.add_argument(
                "compute_reqs_instances_or_nodes",
                nargs="*",
                default="",
                metavar="<name-or-ID>",
                type=str,
                help=(
                    "the name(s) or YellowDog ID(s) of the compute requirement(s), "
                    "ID(s) of nodes, or instances in 'cr_id.instance_id' format"
                ),
            )
            parser.add_argument(
                "--follow",
                "-f",
                action="store_true",
                required=False,
                help="follow termination to completion",
            )

        # yd-cancel
        if "cancel" in sys.argv[0]:
            parser.add_argument(
                "work_requirements",
                nargs="*",
                default="",
                metavar="<work-requirement-name-or-ID>",
                type=str,
                help=(
                    "the name(s) or YellowDog ID(s) of the work requirement(s) to be"
                    " cancelled; can also supply task IDs"
                ),
            )

        # yd-start
        if "start" in sys.argv[0]:
            parser.add_argument(
                "work_requirements",
                nargs="*",
                default="",
                metavar="<work-requirement-name-or-ID>",
                type=str,
                help=(
                    "the name(s) or YellowDog ID(s) of the held (paused) work requirement(s) to be"
                    " started"
                ),
            )

        # yd-hold
        if "hold" in sys.argv[0]:
            parser.add_argument(
                "work_requirements",
                nargs="*",
                default="",
                metavar="<work-requirement-name-or-ID>",
                type=str,
                help=(
                    "the name(s) or YellowDog ID(s) of the work requirement(s) to be"
                    " held (paused)"
                ),
            )

        # yd-finish
        if "finish" in sys.argv[0]:
            parser.add_argument(
                "work_requirements",
                nargs="*",
                default="",
                metavar="<work-requirement-name-or-ID>",
                type=str,
                help=(
                    "the name(s) or YellowDog ID(s) of the work requirement(s) to be"
                    " finished"
                ),
            )

        # yd-create / yd-remove
        if any(module in sys.argv[0] for module in ["create", "remove"]):
            parser.add_argument(
                "resource_specifications",
                nargs="+",
                default=[],
                metavar="<resource-specification>",
                type=str,
                help=(
                    "the resource specifications to process (or resource IDs if used"
                    " with 'yd-remove --ids')"
                ),
            )
            parser.add_argument(
                "--yes",
                "-y",
                action="store_true",
                required=False,
                help="allow updates without user confirmation",
            )
            parser.add_argument(
                "--match-allowances-by-description",
                "-M",
                action="store_true",
                required=False,
                help=(
                    "match using the 'description' property when updating "
                    "(using yd-create) or removing allowances"
                ),
            )

        # yd-create
        if "create" in sys.argv[0]:
            parser.add_argument(
                "--show-keyring-passwords",
                action="store_true",
                required=False,
                help="display YellowDog-generated password when creating a Keyring",
            )
            parser.add_argument(
                "--regenerate-app-keys",
                action="store_true",
                required=False,
                help="regenerate the application key & secret when updating an application",
            )

        # yd-remove
        if "remove" in sys.argv[0]:
            parser.add_argument(
                "--ids",
                action="store_true",
                required=False,
                help="remove resources using their YellowDog IDs (YDIDs)",
            )

        # yd-follow / yd-show / yd-wait
        if any(module in sys.argv[0] for module in ["follow", "show", "wait"]):
            verb = (
                "follow"
                if "follow" in sys.argv[0]
                else "wait"
                if "wait" in sys.argv[0]
                else "show"
            )
            parser.add_argument(
                "yellowdog_ids",
                nargs="*",
                default=[],
                metavar="<yellowdog-id>",
                type=str,
                help=f"the YellowDog ID(s) of the item(s) to {verb}",
            )

        # yd-follow
        if "follow" in sys.argv[0]:
            parser.add_argument(
                "--progress",
                action="store_true",
                required=False,
                help=(
                    "display a live progress bar for Work Requirement IDs; "
                    "ignored for Worker Pool and Compute Requirement IDs"
                ),
            )

        # yd-submit / yd-provision / yd-instantiate / yd-nodeaction
        if any(
            module in sys.argv[0]
            for module in ["submit", "provision", "instantiate", "nodeaction"]
        ):
            parser.add_argument(
                "--content-path",
                "-F",
                type=str,
                required=False,
                help=(
                    "the directory in which files for upload (or for user data "
                    "or CSV data) are found"
                ),
                metavar="<directory>",
            )

        # yd-provision / yd-instantiate
        if any(module in sys.argv[0] for module in ["provision", "instantiate"]):
            parser.add_argument(
                "--follow",
                "-f",
                action="store_true",
                required=False,
                help="follow progress after provisioning",
            )
            parser.add_argument(
                "--target",
                "-T",
                type=int,
                required=False,
                help="override targetInstanceCount from the spec or config",
                metavar="<n>",
            )

        # yd-resize
        if any(module in sys.argv[0] for module in ["resize"]):
            parser.add_argument(
                "--follow",
                "-f",
                action="store_true",
                required=False,
                help="follow progress after resizing",
            )

        # yd-follow / yd-shutdown / yd-provision / yd-resize
        if any(
            module in sys.argv[0]
            for module in ["follow", "shutdown", "provision", "resize"]
        ):
            parser.add_argument(
                "--auto-follow-compute-requirements",
                "-a",
                action="store_true",
                required=False,
                help=(
                    "automatically follow the associated compute requirements when"
                    " following worker pools"
                ),
            )

        # yd-follow / yd-provision / yd-instantiate / yd-resize / yd-shutdown /
        # yd-terminate / yd-submit / yd-cancel / yd-start / yd-hold / yd-finish
        if any(
            module in sys.argv[0]
            for module in [
                "follow",
                "provision",
                "instantiate",
                "resize",
                "shutdown",
                "terminate",
                "submit",
                "cancel",
                "start",
                "hold",
                "finish",
            ]
        ):
            parser.add_argument(
                "--raw-events",
                action="store_true",
                required=False,
                help="print the raw JSON event stream when following events",
            )

        # yd-cloudwizard
        if "cloudwizard" in sys.argv[0]:
            parser.add_argument(
                "operation",
                metavar="'setup', 'teardown', 'add-ssh' or 'remove-ssh'",
                type=str,
                choices=["setup", "teardown", "add-ssh", "remove-ssh"],
                help=(
                    "the cloud wizard operation to perform: 'setup', 'teardown',"
                    " 'add-ssh' or 'remove-ssh'"
                ),
            )
            parser.add_argument(
                "--cloud-provider",
                required=True,
                metavar="<name of cloud provider>",
                type=str,
                help=(
                    "the name of the cloud provider (AWS, GCP, and Azure are currently"
                    " supported)"
                ),
            )
            parser.add_argument(
                "--credentials-file",
                required=False,
                metavar="<file-containing-google-credentials>",
                type=str,
                help=(
                    "the name of the file containing the cloud GCP credentials when"
                    " using Cloud Wizard with GCP"
                ),
            )
            parser.add_argument(
                "--region-name",
                "-R",
                required=False,
                metavar="<cloud-provider-region-name>",
                type=str,
                help="specify the cloud provider region name for certain operations",
            )
            parser.add_argument(
                "--instance-type",
                "-I",
                required=False,
                metavar="<instance-type>",
                type=str,
                help=(
                    "the instance type to use in the automatically generated YellowDog"
                    " compute requirement templates"
                ),
            )
            parser.add_argument(
                "--show-secrets",
                action="store_true",
                required=False,
                help="print AWS secret key during setup",
            )

        # yd-nodeaction
        if "nodeaction" in sys.argv[0]:
            parser.add_argument(
                "--follow",
                "-f",
                action="store_true",
                required=False,
                help=(
                    "poll node action queues after submission, "
                    "reporting progress until all actions complete or fail"
                ),
            )
            parser.add_argument(
                "--actions",
                "-S",
                type=str,
                required=False,
                help="node action spec file in JSON or Jsonnet format",
                metavar="<node_actions.json>",
            )
            parser.add_argument(
                "--worker-pool",
                "-p",
                type=str,
                required=False,
                help="name of the target worker pool",
                metavar="<worker-pool-name>",
            )
            parser.add_argument(
                "--node",
                "-N",
                type=str,
                required=False,
                action="append",
                help=("target a specific node by ID; can be specified multiple times"),
                metavar="<node-id>",
            )
            parser.add_argument(
                "--all-nodes",
                action="store_true",
                required=False,
                help=(
                    "target all current nodes in the worker pool "
                    "(filtered by nodeTypes if present in the spec)"
                ),
            )
            parser.add_argument(
                "--status",
                action="store_true",
                required=False,
                help="show the node action queue for the selected node(s)",
            )
            parser.add_argument(
                "--details",
                "-d",
                action="store_true",
                required=False,
                help="show the full JSON details for --status output",
            )

        # yd-abort
        if "abort" in sys.argv[0]:
            parser.add_argument(
                "task_id_list",
                nargs="*",
                default="",
                metavar="<task-id>",
                type=str,
                help="the YellowDog ID(s) of the task(s) to abort",
            )

        # yd-submit (positional arg)
        if any(module in sys.argv[0] for module in ["submit"]):
            # Note: removes the need for the '-r' option
            parser.add_argument(
                "work_requirement_file_positional",
                metavar="<work-requirement-specification-file>",
                type=str,
                nargs="?",
                help=(
                    "the JSON or Jsonnet specification of the work requirement"
                    " to submit; alternative to using the '--work-requirement/-r'"
                    " option"
                ),
            )

        # yd-provision (positional arg)
        if any(module in sys.argv[0] for module in ["provision"]):
            # Note: removes the need for the '-p' option
            parser.add_argument(
                "worker_pool_file_positional",
                metavar="<worker-pool-specification-file>",
                type=str,
                nargs="?",
                help=(
                    "the JSON or Jsonnet specification of the worker pool"
                    " to provision; alternative to using the '--worker-pool/-p'"
                    " option"
                ),
            )

        # yd-instantiate (positional arg)
        if any(module in sys.argv[0] for module in ["instantiate"]):
            # Note: removes the need for the '-C' option
            parser.add_argument(
                "compute_requirement_file_positional",
                metavar="<compute-requirement-specification-file>",
                type=str,
                nargs="?",
                help=(
                    "the JSON or Jsonnet specification of the compute requirement"
                    " to provision; alternative to using the"
                    "'--compute-requirement/-C' option"
                ),
            )

        # yd-create
        if any(module in sys.argv[0] for module in ["create"]):
            parser.add_argument(
                "--no-resequence",
                action="store_true",
                required=False,
                help=(
                    "don't re-sequence resources prior  to creation (e.g., "
                    "putting source templates before requirement templates)"
                ),
            )

        # yd-show
        if any(module in sys.argv[0] for module in ["show"]):
            parser.add_argument(
                "--show-token",
                action="store_true",
                required=False,
                help=(
                    "display the worker pool token when showing the details of a "
                    "configured worker pool"
                ),
            )
            parser.add_argument(
                "--report-variable",
                "-r",
                type=str,
                required=False,
                action="append",
                help=(
                    "report the processed value of the specified variable and exit; "
                    "the option can be supplied multiple times, one per variable, "
                    "or use 'all' to report all variables; use with '--quiet' for "
                    "output in JSON"
                ),
                metavar="<var>",
            )

        # yd-list / yd-show
        if any(module in sys.argv[0] for module in ["list", "show"]):
            parser.add_argument(
                "--substitute-ids",
                "-U",
                action="store_true",
                required=False,
                help=(
                    "substitute compute source template IDs and image family IDs "
                    "for names in detailed compute requirement templates, "
                    "and image family IDs in compute source templates "
                    "(implies '--details')"
                ),
            )
            parser.add_argument(
                "--strip-ids",
                action="store_true",
                required=False,
                help=(
                    "omit the YellowDog IDs of objects from their JSON "
                    "representations, as well as other properties not "
                    "required when capturing JSON for use with yd-create and yd-remove "
                    "(implies '--details')"
                ),
            )
            parser.add_argument(
                "--output-file",
                type=str,
                required=False,
                help=(
                    "if specified, the detailed JSON resource listing will also be written "
                    "to the nominated output file"
                ),
                metavar="<output-file>",
            )

        # yd-compare
        if "compare" in sys.argv[0]:
            parser.add_argument(
                "wr_or_tg_id",
                metavar="<work-requirement-or-task-group-ID>",
                type=str,
                help=(
                    "the YellowDog ID of the work requirement or task group to be compared"
                ),
            )
            parser.add_argument(
                "worker_pool_ids",
                metavar="<provisioned-worker-pool-ID>",
                type=str,
                nargs="+",
                help="the YellowDog ID(s) of the provisioned worker pool(s) to compare",
            )

        # yd-submit
        if any(module in sys.argv[0] for module in ["submit"]):
            parser.add_argument(
                "--upgrade-rclone",
                action="store_true",
                required=False,
                help="download the latest rclone binary, then exit",
            )
            parser.add_argument(
                "--which-rclone",
                action="store_true",
                required=False,
                help="report the path and version of the rclone binary in use, then exit",
            )
            parser.add_argument(
                "--progress",
                action="store_true",
                required=False,
                help=(
                    "display a live progress bar showing task completion; "
                    "implies following the Work Requirement to completion"
                ),
            )

        # yd-upload / yd-download / yd-delete / yd-ls / yd-copy (data client commands)
        if any(
            module in sys.argv[0]
            for module in ["upload", "download", "delete", "ls", "copy"]
        ):
            parser.add_argument(
                "--remote",
                "-r",
                type=str,
                required=False,
                help="rclone remote name or inline config string; overrides [dataClient] config",
                metavar="<remote>",
            )
            parser.add_argument(
                "--bucket",
                "-b",
                type=str,
                required=False,
                help="bucket or container name; overrides [dataClient] config",
                metavar="<bucket>",
            )
            parser.add_argument(
                "--prefix",
                "-p",
                type=str,
                required=False,
                help=(
                    "remote path prefix; supports {{variable}} substitution; "
                    "overrides [dataClient] config"
                ),
                metavar="<prefix>",
            )
            parser.add_argument(
                "--no-prefix",
                action="store_true",
                required=False,
                help="suppress the default path prefix; place files at the bucket root",
            )
            parser.add_argument(
                "--upgrade-rclone",
                action="store_true",
                required=False,
                help="download the latest rclone binary, then exit",
            )
            parser.add_argument(
                "--which-rclone",
                action="store_true",
                required=False,
                help="report the path and version of the rclone binary in use, then exit",
            )
            parser.add_argument(
                "--data-client-profile",
                "--profile",
                type=str,
                required=False,
                help=(
                    "select a named [dataClient.<name>] profile from the config; "
                    "inherits unset fields from [dataClient]"
                ),
                metavar="<name>",
            )
            parser.add_argument(
                "--dry-run",
                "-D",
                action="store_true",
                required=False,
                help="show what would happen without performing any transfers",
            )

        # yd-upload
        if "upload" in sys.argv[0]:
            parser.add_argument(
                "local_paths",
                metavar="<local-path>",
                type=str,
                nargs="+",
                help="local file(s) or directory(ies) to upload",
            )
            parser.add_argument(
                "--destination",
                "-d",
                type=str,
                required=False,
                help="explicit remote destination path, overriding the assembled default",
                metavar="<remote-path>",
            )
            parser.add_argument(
                "--recursive",
                "-R",
                action="store_true",
                required=False,
                help="upload directories recursively",
            )
            parser.add_argument(
                "--flatten",
                action="store_true",
                required=False,
                help="strip directory structure; upload all files flat under the destination",
            )
            parser.add_argument(
                "--sync",
                action="store_true",
                required=False,
                help=(
                    "mirror the local source to the remote destination, deleting remote "
                    "files not present locally; implies --recursive"
                ),
            )

        # yd-download
        if "download" in sys.argv[0]:
            parser.add_argument(
                "remote_paths",
                metavar="<remote-path>",
                type=str,
                nargs="+",
                help="remote file(s) or pattern(s) to download",
            )
            parser.add_argument(
                "--destination",
                "-d",
                type=str,
                required=False,
                default=None,
                help="local directory or file path to write to (default: mirrors remote name)",
                metavar="<local-path>",
            )
            parser.add_argument(
                "--sync",
                action="store_true",
                required=False,
                help=(
                    "mirror the remote source to the local destination, deleting local "
                    "files not present remotely"
                ),
            )
            parser.add_argument(
                "--flatten",
                action="store_true",
                required=False,
                help="strip remote directory structure; download all files flat",
            )

        # yd-delete (data client)
        if "delete" in sys.argv[0]:
            parser.add_argument(
                "remote_paths",
                metavar="<remote-path>",
                type=str,
                nargs="*",
                help=(
                    "remote file(s) or directory(ies) to delete; "
                    "if omitted with --recursive, deletes the entire default prefix"
                ),
            )
            parser.add_argument(
                "--recursive",
                "-R",
                action="store_true",
                required=False,
                help="delete directories recursively",
            )

        # yd-ls
        if "ls" in sys.argv[0]:
            parser.add_argument(
                "remote_paths",
                metavar="<remote-path>",
                type=str,
                nargs="*",
                help="remote path(s) to list; defaults to the configured prefix if omitted",
            )
            parser.add_argument(
                "--recursive",
                "-R",
                action="store_true",
                required=False,
                help="list directories recursively",
            )

        # yd-copy
        if "copy" in sys.argv[0]:
            parser.add_argument(
                "src_path",
                metavar="<src-path>",
                type=str,
                nargs="?",
                help="source path relative to the configured source remote/bucket/prefix",
            )
            parser.add_argument(
                "dst_path",
                metavar="<dst-path>",
                type=str,
                nargs="?",
                help="destination path relative to the configured destination remote/bucket/prefix",
            )
            parser.add_argument(
                "--dst-profile",
                type=str,
                required=False,
                help=(
                    "select a named [dataClient.<name>] profile for the destination; "
                    "inherits unset fields from [dataClient]"
                ),
                metavar="<name>",
            )
            parser.add_argument(
                "--dst-prefix",
                type=str,
                required=False,
                help=(
                    "override the destination path prefix; "
                    "supports {{variable}} substitution; "
                    "pass '' to place files at the bucket root"
                ),
                metavar="<prefix>",
            )
            parser.add_argument(
                "--recursive",
                "-R",
                action="store_true",
                required=False,
                help="copy directories recursively (rclone copies recursively by default)",
            )
            parser.add_argument(
                "--sync",
                action="store_true",
                required=False,
                help=(
                    "make the destination a mirror of the source, "
                    "deleting destination files not present in the source"
                ),
            )

        self.args = parser.parse_args()

        if self.args.docs:
            docs()
            exit(0)

    # -----------------------------------------------------------------------
    # Common args
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def config_file(self) -> str | None:
        return self.args.config

    @property
    @allow_missing_attribute
    def key(self) -> str | None:
        return self.args.key

    @property
    @allow_missing_attribute
    def secret(self) -> str | None:
        return self.args.secret

    @property
    @allow_missing_attribute
    def url(self) -> str | None:
        return self.args.url

    @property
    @allow_missing_attribute
    def debug(self) -> bool | None:
        return self.args.debug

    @property
    @allow_missing_attribute
    def use_pac(self) -> bool | None:
        return self.args.pac

    @property
    @allow_missing_attribute
    def no_format(self) -> bool | None:
        return self.args.no_format

    @property
    @allow_missing_attribute
    def quiet(self) -> bool | None:
        return self.args.quiet

    @quiet.setter
    def quiet(self, value: bool) -> None:
        self.args.quiet = value

    @property
    @allow_missing_attribute
    def env_override(self) -> bool | None:
        return self.args.env_override

    @property
    @allow_missing_attribute
    def print_pid(self) -> bool | None:
        return self.args.print_pid

    @property
    @allow_missing_attribute
    def no_config(self) -> bool | None:
        return self.args.no_config

    @property
    @allow_missing_attribute
    def property_overrides(self) -> list[str] | None:
        return self.args.property

    # -----------------------------------------------------------------------
    # yd-* (all except yd-compare)
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def variables(self) -> list[str] | None:
        return self.args.variable

    # -----------------------------------------------------------------------
    # yd-* (all except yd-boost, yd-cloudwizard, yd-follow, yd-list, yd-compare)
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def namespace(self) -> str | None:
        return self.args.namespace

    @property
    @allow_missing_attribute
    def tag(self) -> str | None:
        return self.args.tag

    # -----------------------------------------------------------------------
    # yd-list
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def ids_only(self) -> bool | None:
        return self.args.ids_only

    @property
    @allow_missing_attribute
    def json_output(self) -> bool | None:
        return self.args.json

    # -----------------------------------------------------------------------
    # yd-submit
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def work_req_file(self) -> str | None:
        return self.args.work_requirement

    @property
    @allow_missing_attribute
    def json_raw(self) -> str | None:
        return self.args.json_raw

    # Also used by yd-cancel, yd-provision, yd-instantiate, yd-start, yd-hold,
    # yd-finish, yd-shutdown, yd-terminate, yd-resize
    @property
    @allow_missing_attribute
    def follow(self) -> bool:
        return self.args.follow

    @property
    @allow_missing_attribute
    def task_type(self) -> str | None:
        return self.args.task_type

    @property
    @allow_missing_attribute
    def task_count(self) -> int | None:
        return self.args.task_count

    @property
    @allow_missing_attribute
    def task_group_count(self) -> int | None:
        return self.args.task_group_count

    @property
    @allow_missing_attribute
    def task_batch_size(self) -> int | None:
        return self.args.task_batch_size

    @property
    @allow_missing_attribute
    def pause_between_batches(self) -> int | None:
        return self.args.pause_between_batches

    @property
    @allow_missing_attribute
    def csv_files(self) -> list[str] | None:
        return self.args.csv_file

    @property
    @allow_missing_attribute
    def process_csv_only(self) -> bool | None:
        return self.args.process_csv_only

    @property
    @allow_missing_attribute
    def hold(self) -> bool | None:
        return self.args.hold

    @property
    @allow_missing_attribute
    def parallel_batches(self) -> int | None:
        return self.args.parallel_batches

    @property
    @allow_missing_attribute
    def empty(self) -> bool | None:
        return self.args.empty

    @property
    @allow_missing_attribute
    def overwrite(self) -> bool | None:
        return self.args.overwrite

    @property
    @allow_missing_attribute
    def add_to(self) -> str | None:
        return self.args.add_to

    # -----------------------------------------------------------------------
    # yd-provision / yd-instantiate
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def worker_pool_file(self) -> str | None:
        return self.args.worker_pool

    @property
    @allow_missing_attribute
    def target(self) -> int | None:
        return self.args.target

    # -----------------------------------------------------------------------
    # yd-cancel
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def abort(self) -> bool:
        return self.args.abort

    # -----------------------------------------------------------------------
    # yd-cancel / yd-shutdown / yd-terminate / yd-start / yd-hold / yd-finish
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def interactive(self) -> bool | None:
        return self.args.interactive

    @interactive.setter
    def interactive(self, interactive: bool):
        self.args.interactive = interactive

    # -----------------------------------------------------------------------
    # yd-abort / yd-cancel / yd-shutdown / yd-terminate /
    # yd-resize / yd-cloudwizard / yd-boost / yd-hold / yd-start / yd-list /
    # yd-finish  (also yd-create / yd-remove)
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def yes(self) -> bool | None:
        return self.args.yes

    # -----------------------------------------------------------------------
    # yd-list
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def reverse(self) -> bool | None:
        return self.args.reverse

    @property
    @allow_missing_attribute
    def entity_type(self) -> str | None:
        return self.args.entity_type

    @property
    @allow_missing_attribute
    def active_only(self) -> bool | None:
        return self.args.active_only

    @property
    @allow_missing_attribute
    def status_filter(self) -> list[str] | None:
        return self.args.status_filter

    @property
    @allow_missing_attribute
    def public_ips_only(self) -> bool | None:
        return self.args.public_ips_only

    @property
    @allow_missing_attribute
    def details(self) -> bool | None:
        return self.args.details

    @details.setter
    def details(self, interactive: bool):
        self.args.details = interactive

    @property
    @allow_missing_attribute
    def auto_select_all(self) -> bool | None:
        return self.args.auto_select_all

    # -----------------------------------------------------------------------
    # yd-submit / yd-provision / yd-instantiate / yd-create
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def dry_run(self) -> bool | None:
        return self.args.dry_run

    # -----------------------------------------------------------------------
    # yd-instantiate
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def compute_requirement(self) -> str | None:
        return self.args.compute_requirement

    @property
    @allow_missing_attribute
    def report(self) -> bool | None:
        return self.args.report

    # -----------------------------------------------------------------------
    # yd-admin
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def wr_ids(self) -> list[str] | None:
        return self.args.work_requirement_id

    # -----------------------------------------------------------------------
    # yd-submit / yd-provision / yd-instantiate / yd-create / yd-remove
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def jsonnet_dry_run(self) -> bool | None:
        return self.args.jsonnet_dry_run

    # -----------------------------------------------------------------------
    # yd-resize
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def worker_pool_name(self) -> str | None:
        return self.args.worker_pool

    @property
    @allow_missing_attribute
    def worker_pool_size(self) -> int | None:
        return self.args.worker_pool_size

    @property
    @allow_missing_attribute
    def compute_req_resize(self) -> bool | None:
        return self.args.compute_requirement

    # -----------------------------------------------------------------------
    # yd-boost
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def boost_hours(self) -> int:
        return self.args.boost_hours

    @property
    @allow_missing_attribute
    def allowance_list(self) -> list[str]:
        return self.args.allowances

    # -----------------------------------------------------------------------
    # yd-shutdown
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def worker_pool_nodes_list(self) -> list[str] | None:
        return self.args.worker_pool_nodes_list

    @property
    @allow_missing_attribute
    def terminate(self) -> bool | None:
        return self.args.terminate

    # -----------------------------------------------------------------------
    # yd-terminate
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def compute_requirements_instances_or_nodes(self) -> list[str]:
        return self.args.compute_reqs_instances_or_nodes

    # -----------------------------------------------------------------------
    # yd-cancel / yd-start / yd-hold / yd-finish  (positional args)
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def work_requirement_names(self) -> list[str]:
        return self.args.work_requirements

    # -----------------------------------------------------------------------
    # yd-create / yd-remove
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def resource_specifications(self) -> list[str]:
        return self.args.resource_specifications

    @property
    @allow_missing_attribute
    def match_allowances_by_description(self) -> bool | None:
        return self.args.match_allowances_by_description

    # -----------------------------------------------------------------------
    # yd-create
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def show_keyring_passwords(self) -> bool | None:
        return self.args.show_keyring_passwords

    @property
    @allow_missing_attribute
    def regenerate_app_keys(self) -> bool | None:
        return self.args.regenerate_app_keys

    # -----------------------------------------------------------------------
    # yd-remove
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def ids(self) -> bool | None:
        return self.args.ids

    # -----------------------------------------------------------------------
    # yd-follow / yd-show
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def yellowdog_ids(self) -> list[str]:
        return self.args.yellowdog_ids

    # -----------------------------------------------------------------------
    # yd-submit / yd-provision / yd-instantiate
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def content_path(self) -> str | None:
        return self.args.content_path

    # -----------------------------------------------------------------------
    # yd-follow / yd-shutdown / yd-provision / yd-resize
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def auto_cr(self) -> bool:
        return self.args.auto_follow_compute_requirements

    # -----------------------------------------------------------------------
    # yd-follow / yd-provision / yd-instantiate / yd-resize / yd-shutdown /
    # yd-terminate / yd-submit / yd-cancel / yd-start / yd-hold / yd-finish
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def raw_events(self) -> bool | None:
        return self.args.raw_events

    # -----------------------------------------------------------------------
    # yd-cloudwizard
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def operation(self) -> str | None:
        return self.args.operation

    @property
    @allow_missing_attribute
    def cloud_provider(self) -> str | None:
        return self.args.cloud_provider

    @property
    @allow_missing_attribute
    def credentials_file(self) -> str | None:
        return self.args.credentials_file

    @property
    @allow_missing_attribute
    def region_name(self) -> str | None:
        return self.args.region_name

    @property
    @allow_missing_attribute
    def instance_type(self) -> str | None:
        return self.args.instance_type

    @property
    @allow_missing_attribute
    def show_secrets(self) -> bool:
        return self.args.show_secrets

    # -----------------------------------------------------------------------
    # yd-nodeaction
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def node_action_spec(self) -> str | None:
        return self.args.actions

    @property
    @allow_missing_attribute
    def node_ids(self) -> list[str] | None:
        return self.args.node

    @property
    @allow_missing_attribute
    def all_nodes(self) -> bool | None:
        return self.args.all_nodes

    @property
    @allow_missing_attribute
    def status(self) -> bool | None:
        return self.args.status

    # -----------------------------------------------------------------------
    # yd-abort
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def task_id_list(self) -> list[str] | None:
        return self.args.task_id_list

    # -----------------------------------------------------------------------
    # yd-submit / yd-provision / yd-instantiate  (positional args)
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def work_requirement_file_positional(self) -> str | None:
        return self.args.work_requirement_file_positional

    @property
    @allow_missing_attribute
    def worker_pool_file_positional(self) -> str | None:
        return self.args.worker_pool_file_positional

    @property
    @allow_missing_attribute
    def compute_requirement_file_positional(self) -> str | None:
        return self.args.compute_requirement_file_positional

    # -----------------------------------------------------------------------
    # yd-create
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def no_resequence(self) -> bool | None:
        return self.args.no_resequence

    # -----------------------------------------------------------------------
    # yd-show
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def show_token(self) -> bool | None:
        return self.args.show_token

    @property
    @allow_missing_attribute
    def report_variables(self) -> list[str]:
        return self.args.report_variable

    # -----------------------------------------------------------------------
    # yd-list / yd-show
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def substitute_ids(self) -> bool | None:
        return self.args.substitute_ids

    @property
    @allow_missing_attribute
    def strip_ids(self) -> bool | None:
        return self.args.strip_ids

    @property
    @allow_missing_attribute
    def output_file(self) -> str | None:
        return self.args.output_file

    # -----------------------------------------------------------------------
    # yd-compare
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def wr_or_tg_id(self) -> str | None:
        return self.args.wr_or_tg_id

    @property
    @allow_missing_attribute
    def worker_pool_ids(self) -> list[str] | None:
        return self.args.worker_pool_ids

    @property
    @allow_missing_attribute
    def running_nodes_only(self) -> bool | None:
        return self.args.running_nodes_only

    # -----------------------------------------------------------------------
    # yd-submit
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def upgrade_rclone(self) -> bool | None:
        return self.args.upgrade_rclone

    @property
    @allow_missing_attribute
    def which_rclone(self) -> bool | None:
        return self.args.which_rclone

    @property
    @allow_missing_attribute
    def progress(self) -> bool | None:
        return self.args.progress

    # -----------------------------------------------------------------------
    # yd-upload / yd-download / yd-delete / yd-ls (data client commands)
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def remote(self) -> str | None:
        return self.args.remote

    @property
    @allow_missing_attribute
    def bucket(self) -> str | None:
        return self.args.bucket

    @property
    @allow_missing_attribute
    def prefix(self) -> str | None:
        return self.args.prefix

    @property
    @allow_missing_attribute
    def no_prefix(self) -> bool | None:
        return self.args.no_prefix

    @property
    @allow_missing_attribute
    def data_client_profile(self) -> str | None:
        return self.args.data_client_profile

    # -----------------------------------------------------------------------
    # yd-upload
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def local_paths(self) -> list[str]:
        return self.args.local_paths

    @property
    @allow_missing_attribute
    def destination(self) -> str | None:
        return self.args.destination

    @property
    @allow_missing_attribute
    def recursive(self) -> bool | None:
        return self.args.recursive

    @property
    @allow_missing_attribute
    def flatten(self) -> bool | None:
        return self.args.flatten

    @property
    @allow_missing_attribute
    def sync(self) -> bool | None:
        return self.args.sync

    # -----------------------------------------------------------------------
    # yd-download / yd-delete / yd-ls
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def remote_paths(self) -> list[str]:
        return self.args.remote_paths

    # -----------------------------------------------------------------------
    # yd-copy
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def src_path(self) -> str | None:
        return self.args.src_path

    @property
    @allow_missing_attribute
    def dst_path(self) -> str | None:
        return self.args.dst_path

    @property
    @allow_missing_attribute
    def dst_profile(self) -> str | None:
        return self.args.dst_profile

    @property
    @allow_missing_attribute
    def dst_prefix(self) -> str | None:
        return self.args.dst_prefix


def lookup_module_description(module_name: str) -> str | None:
    """
    Descriptive string for the module's purpose.
    """
    prefix = "YellowDog command line utility for "
    suffix = None

    if "abort" in module_name:
        suffix = "aborting Tasks"
    elif "delete" in module_name:
        suffix = "deleting remote data client files and directories"
    elif "download" in module_name:
        suffix = "downloading files from a remote data client"
    elif "application" in module_name:
        suffix = "reporting the details of the current Application"
    elif "boost" in module_name:
        suffix = "boosting Allowances"
    elif "cancel" in module_name:
        suffix = "cancelling Work Requirements"
    elif "cloudwizard" in module_name:
        suffix = "setting up cloud accounts and YellowDog resources"
    elif "copy" in module_name:
        suffix = "copying files between remote data client locations"
    elif "compare" in module_name:
        suffix = (
            "comparing whether a work requirement or task group is matched by "
            "workers in the specified provisioned worker pools"
        )
    elif "create" in module_name:
        suffix = "creating and updating resources"
    elif "finish" in module_name:
        suffix = "finishing Work Requirements"
    elif "follow" in module_name:
        suffix = "following event streams"
    elif "hold" in module_name:
        suffix = "holding (pausing) running Work Requirements"
    elif "instantiate" in module_name:
        suffix = "instantiating a Compute Requirement"
    elif "ls" in module_name:
        suffix = "listing remote data client files and directories"
    elif "list" in module_name:
        suffix = "listing all kinds of YellowDog items"
    elif "nodeaction" in module_name:
        suffix = "submitting Node Actions to Worker Pool nodes"
    elif "provision" in module_name:
        suffix = "provisioning a Worker Pool"
    elif "remove" in module_name:
        suffix = "removing resources"
    elif "resize" in module_name:
        suffix = "resizing Worker Pools and Compute Requirements"
    elif "show" in module_name:
        suffix = "showing the JSON details of entities referenced by their YDIDs"
    elif "shutdown" in module_name:
        suffix = "shutting down Worker Pools and Nodes"
    elif "start" in module_name:
        suffix = "starting held (paused) Work Requirements"
    elif "submit" in module_name:
        suffix = "submitting a Work Requirement"
    elif "terminate" in module_name:
        suffix = "terminating Compute Requirements, Instances or Nodes"
    elif "upload" in module_name:
        suffix = "uploading files to a remote data client"
    elif "format" in module_name:
        suffix = "formatting JSON files using a compact encoder"
    elif "jsonnet" in module_name:
        suffix = "converting a Jsonnet file to JSON"
    elif "wait" in module_name:
        suffix = (
            "waiting for Work Requirements, Worker Pools, or Compute Requirements"
            " to reach a terminal state"
        )
    elif "version" in module_name:
        suffix = "reporting version information"
    elif "help" in module_name:
        suffix = "listing available yd-* commands and their purposes"

    return None if suffix is None else prefix + suffix


ARGS_PARSER = CLIParser(description=lookup_module_description(sys.argv[0]))
