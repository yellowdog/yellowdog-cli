"""
The registry of yd-* commands and their options.

Every command's options are defined here once, as data: argparse is built
from it (build_parser()), yd-help lists from it, and the README's Command
List is checked against it (tests/test_readme_command_list.py). It imports
nothing from args.py; args.py imports it.
"""

from __future__ import annotations

import os
import re
from argparse import (
    Action,
    ArgumentParser,
    ArgumentTypeError,
    Namespace,
    _ArgumentGroup,
)
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from yellowdog_cli.utils.glob_utils import contains_glob_chars
from yellowdog_cli.utils.settings import (
    DEFAULT_PARALLEL_TASK_BATCH_UPLOAD_THREADS,
    DEFAULT_URL,
    DOCTOR_DEFAULT_TIMEOUT,
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
    SCHEMA_FAMILIES,
    SECRET_VARIABLE_NAME_PATTERN,
)

Validator = Callable[[Namespace, ArgumentParser], None]

DESCRIPTION_PREFIX = "YellowDog command-line utility for "


@dataclass(frozen=True, eq=False)
class Option:
    """
    One argparse argument: its flags (or a positional's name) and the
    keyword arguments handed to add_argument() verbatim. Identity, for
    'is this the same option on another command', is the first long flag.
    """

    flags: tuple[str, ...]
    kwargs: dict[str, Any]

    @property
    def positional(self) -> bool:
        return not self.flags[0].startswith("-")

    @property
    def name(self) -> str:
        if self.positional:
            return self.flags[0]
        for flag in self.flags:
            if flag.startswith("--"):
                return flag
        raise ValueError(f"no long flag among {self.flags!r}")

    @property
    def aliases(self) -> tuple[str, ...]:
        return tuple(flag for flag in self.flags if flag != self.name)

    def variant(self, **overrides: Any) -> Option:
        """The same option with some keyword arguments replaced."""
        return Option(self.flags, {**self.kwargs, **overrides})

    def register(self, target: ArgumentParser | _ArgumentGroup) -> Action:
        return target.add_argument(*self.flags, **self.kwargs)


def option(*flags: str, **kwargs: Any) -> Option:
    return Option(flags, kwargs)


@dataclass(frozen=True, eq=False)
class Exclusive:
    """A mutually exclusive group."""

    options: tuple[Option, ...]


class CommandKind(Enum):
    API = auto()  # builds a PlatformClient; takes the full universal set
    DATA_CLIENT = auto()  # rclone only; no --key, --secret, --url or --pac
    STANDALONE = auto()  # no configuration and no credentials


class ToolKind(Enum):
    """
    What the command is as an MCP tool (yellowdog_cli/mcp/): the annotation
    the client is given, so that it can ask the user before a destructive
    one. NONE for a command that is not a tool at all. There is no default:
    a new command says what it is.
    """

    READ_ONLY = auto()  # reads the platform or the installation
    ACTING = auto()  # creates, transfers or waits; destroys nothing
    DESTRUCTIVE = auto()  # cancels, removes, shuts down, changes what is running
    NONE = auto()  # interactive, or a file formatter, or the tool list itself


@dataclass(frozen=True, eq=False)
class Command:
    name: str  # "yd-submit"
    purpose: str  # "submitting a Work Requirement": the description's tail
    summary: str  # "Submit a Work Requirement": the yd-help line
    kind: CommandKind
    options: tuple[Option | Exclusive, ...] = ()  # its own, in registration order
    validators: tuple[Validator, ...] = ()
    # True for the commands that default a missing namespace and tag with a
    # debug message (load_config.py); yd-list has --namespace but is not one.
    requires_namespace_and_tag: bool = False
    # The MCP tool kind (see ToolKind), stated by every command
    tool: ToolKind = field(kw_only=True)
    # A hand-written description for a tool whose workflow needs explaining;
    # None means the summary and purpose are used
    tool_description: str | None = None

    def all_options(self) -> tuple[Option | Exclusive, ...]:
        return COMMON_OPTIONS[self.kind] + self.options

    def flat_options(self) -> tuple[Option, ...]:
        flat: list[Option] = []
        for item in self.all_options():
            flat.extend(item.options if isinstance(item, Exclusive) else (item,))
        return tuple(flat)

    def has(self, option: Option) -> bool:
        return self.option_named(option.name) is not None

    def option_named(self, name: str) -> Option | None:
        return next((o for o in self.flat_options() if o.name == name), None)


# Filled in below, once the options are defined.
COMMON_OPTIONS: dict[CommandKind, tuple[Option, ...]] = {
    CommandKind.API: (),
    CommandKind.DATA_CLIENT: (),
    CommandKind.STANDALONE: (),
}
COMMANDS: dict[str, Command] = {}

_ARGV0_SUFFIX = re.compile(r"(-script)?\.(py|exe)$")


def command_from_argv0(argv0: str) -> str:
    """
    The entry point name sys.argv[0] stands for. Basename only: a command
    name in the install path must not select that command. 'submit.py'
    (python -m) and 'yd-submit.exe' (Windows) both resolve to 'yd-submit'.
    """
    name = os.path.basename(argv0.replace("\\", "/"))
    name = _ARGV0_SUFFIX.sub("", name).replace("_", "-")
    return name if name.startswith("yd-") else f"yd-{name}"


def build_parser(command: Command | None, prog: str | None = None) -> ArgumentParser:
    """
    The argparse parser for a command. An unknown command (None) gets the
    API common set and nothing else, which is what pytest's own executable
    name gets when args.py is imported under test.
    """
    parser = ArgumentParser(
        prog=prog,
        description=None if command is None else DESCRIPTION_PREFIX + command.purpose,
    )
    items = (
        COMMON_OPTIONS[CommandKind.API] if command is None else command.all_options()
    )
    for item in items:
        if isinstance(item, Exclusive):
            group = parser.add_mutually_exclusive_group()
            for member in item.options:
                member.register(group)
        else:
            item.register(parser)
    return parser


# --- Entity types (yd-list's positional) ---------------------------------

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

# The entity types each of yd-list's filtering options applies to; the option
# is refused for any other (check_list_options), rather than ignored
LIST_NAME_TYPES = frozenset(
    {
        ET_WORK_REQUIREMENTS,
        ET_WORKER_POOLS,
        ET_COMPUTE_REQUIREMENTS,
        ET_COMPUTE_REQUIREMENT_TEMPLATES,
        ET_COMPUTE_SOURCE_TEMPLATES,
        ET_IMAGE_FAMILIES,
        ET_USERS,
        ET_APPLICATIONS,
        ET_GROUPS,
        ET_ROLES,
        ET_KEYRINGS,
        ET_PERMISSIONS,
    }
)
# Those with a status to filter on
LIST_STATUS_TYPES = frozenset(
    {
        ET_WORK_REQUIREMENTS,
        ET_TASK_GROUPS,
        ET_TASKS,
        ET_WORKER_POOLS,
        ET_NODES,
        ET_WORKERS,
        ET_COMPUTE_REQUIREMENTS,
        ET_INSTANCES,
    }
)
# Those listed from active Work Requirements, Worker Pools or Compute
# Requirements, or themselves active or not
LIST_ACTIVE_TYPES = LIST_STATUS_TYPES
# Those with YellowDog IDs: attribute definitions, namespace policies and
# permissions have none
LIST_ID_TYPES = frozenset(ENTITY_TYPES) - {
    ET_ATTRIBUTE_DEFINITIONS,
    ET_NAMESPACE_POLICIES,
    ET_PERMISSIONS,
}
# Those whose details carry IDs that --substitute-ids replaces with names
LIST_SUBSTITUTE_TYPES = frozenset(
    {ET_COMPUTE_REQUIREMENT_TEMPLATES, ET_COMPUTE_SOURCE_TEMPLATES, ET_ALLOWANCES}
)

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


def positive_int(value: str) -> int:
    """
    An argparse type for a count or a budget that must be at least 1:
    anything else is a usage error rather than a value that misleads later.
    """
    try:
        number = int(value)
    except ValueError:
        raise ArgumentTypeError(f"invalid int value: '{value}'") from None
    if number < 1:
        raise ArgumentTypeError(f"must be a positive integer, not {number}")
    return number


def non_negative_int(value: str) -> int:
    """
    An argparse type for a size that may be zero, as a Worker Pool or
    Compute Requirement can be scaled to nothing, but not less.
    """
    try:
        number = int(value)
    except ValueError:
        raise ArgumentTypeError(f"invalid int value: '{value}'") from None
    if number < 0:
        raise ArgumentTypeError(f"must be zero or more, not {number}")
    return number


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
        raise ArgumentTypeError(
            f"'{value}' is ambiguous — matches: {', '.join(matches)}"
        )
    raise ArgumentTypeError(
        f"unknown entity type '{value}'; valid types: {_ENTITY_TYPE_HELP}"
    )


# --- Universal options: API and data client commands ---------------------

DOCS = option(
    "--docs",
    action="store_true",
    required=False,
    help="provide a link to the documentation for this version",
)
CONFIG = option(
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
KEY = option(
    "--key",
    "-k",
    type=str,
    required=False,
    help="the application key ID",
    metavar="<app-key-id>",
)
SECRET = option(
    "--secret",
    "-s",
    required=False,
    type=str,
    help="the application key secret",
    metavar="<app-key-secret>",
)
URL = option(
    "--url",
    "-u",
    type=str,
    required=False,
    help=f"the YellowDog Platform API URL (defaults to '{DEFAULT_URL}')",
    metavar="<url>",
)
DEBUG = option(
    "--debug",
    action="store_true",
    required=False,
    help=("display the Python stack trace on error, and the configuration preamble"),
)
PAC = option(
    "--pac",
    action="store_true",
    required=False,
    help="enable PAC (proxy auto-configuration) support",
)
NO_FORMAT = option(
    "--no-format",
    "--nf",
    action="store_true",
    required=False,
    help="disable colouring and text wrapping in command output",
)
QUIET = option(
    "--quiet",
    "-q",
    action="store_true",
    required=False,
    help="suppress (non-error, non-interactive) status and progress messages",
)
ENV_OVERRIDE = option(
    "--env-override",
    action="store_true",
    required=False,
    help="values in '.env' file override values in the environment (also set via YD_ENV_OVERRIDE)",
)
PRINT_PID = option(
    "--print-pid",
    "--pp",
    action="store_true",
    required=False,
    help="include the process ID of this CLI invocation alongside timestamp in logging messages",
)
NO_CONFIG = option(
    "--no-config",
    "--nc",
    action="store_true",
    required=False,
    help="ignore the contents of any TOML configuration file (even if specified on the command line)",
)
PROPERTY = option(
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

COMMON_OPTIONS[CommandKind.API] = (
    DOCS,
    CONFIG,
    KEY,
    SECRET,
    URL,
    DEBUG,
    PAC,
    NO_FORMAT,
    QUIET,
    ENV_OVERRIDE,
    PRINT_PID,
    NO_CONFIG,
    PROPERTY,
)
COMMON_OPTIONS[CommandKind.DATA_CLIENT] = (
    DOCS,
    CONFIG,
    DEBUG,
    NO_FORMAT,
    QUIET,
    ENV_OVERRIDE,
    PRINT_PID,
    NO_CONFIG,
    PROPERTY,
)
COMMON_OPTIONS[CommandKind.STANDALONE] = ()

# The options no MCP tool exposes, by option name (Option.name: the first
# long flag, or a positional's name), compared as Command.has() compares.
# tests/test_mcp_tools.py holds every option of every tool command to being
# either in a schema or here, so a new option is placed on purpose.
MCP_EXCLUDED_OPTIONS: frozenset[str] = frozenset(
    {
        # The common set: the server owns the configuration, the credentials
        # and the output form
        "--docs",
        "--config",
        "--key",
        "--secret",
        "--url",
        "--debug",
        "--pac",
        "--no-format",
        "--quiet",
        "--env-override",
        "--print-pid",
        "--no-config",
        "--property",
        # Supplied by the server, or meaningless without a terminal, or
        # refused with '--json'
        "--json",
        "--yes",
        "--interactive",
        "--progress",
        "--report",
        "--ids-only",
        # Machine maintenance, not platform work
        "--upgrade-rclone",
        "--which-rclone",
        # A credential in a tool result is a credential in the conversation
        "--show-keyring-passwords",
        "--show-secrets",
        # The specification files, replaced by the tools' 'specification(s)'
        # argument (yellowdog_cli/mcp/tools.py)
        "--work-requirement",
        "--worker-pool",
        "--compute-requirement",
        "work_requirement_file_positional",
        "worker_pool_file_positional",
        "compute_requirement_file_positional",
        "resource_specifications",
    }
)


# --- Shared options ------------------------------------------------------
# Each is shared by several commands; a command registering the same flag
# with different keyword arguments uses a variant.

SORT = option(
    "--sort",
    type=str,
    required=False,
    choices=["name", "created", "status", "namespace"],
    default="name",
    help=(
        "order in which listed and interactively-selected entities "
        "are sorted: 'name' (default), 'created' (creation time, "
        "earliest first), 'status' (status name, then name), or "
        "'namespace' (namespace, then name); combine with --reverse "
        "to invert the order"
    ),
    metavar="<name|created|status|namespace>",
)
REVERSE = option(
    "--reverse",
    action="store_true",
    required=False,
    help="reverse (descending) order of the active --sort key",
)
VARIABLE = option(
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
NAMESPACE = option(
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
TAG = option(
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
JSON = option(
    "--json",
    "-J",
    action="store_true",
    required=False,
    help="emit results as a plain JSON array (suppresses table formatting)",
)
OFFLINE = option(
    "--offline",
    action="store_true",
    required=False,
    help="skip every check that reaches the network (PyPI, the Platform API, the data store)",
)
TIMEOUT = option(
    "--timeout",
    type=positive_int,
    required=False,
    default=DOCTOR_DEFAULT_TIMEOUT,
    help=f"seconds allowed for each network call (default {DOCTOR_DEFAULT_TIMEOUT})",
    metavar="<seconds>",
)
FOLLOW = option(
    "--follow",
    "-f",
    action="store_true",
    required=False,
    help="follow the work requirement's progress to completion",
)
WORKER_POOL = option(
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
DRY_RUN = option(
    "--dry-run",
    "-D",
    action="store_true",
    required=False,
    help="list the entities that would be affected, without acting",
)
# Not a variant of JSON: this '--json' has no '-J' alias.
DRY_RUN_JSON = option(
    "--json",
    action="store_true",
    required=False,
    help=(
        "emit the actions taken, or with --dry-run what would be taken, as a JSON array"
    ),
)
# The action commands' '--json': the '--json' of JSON without its '-J',
# which the specification commands use for '--jsonnet-dry-run'
ACTIONS_JSON = option(
    "--json",
    action="store_true",
    required=False,
    help="emit the actions taken as a JSON array",
)
TRANSFERS_JSON = ACTIONS_JSON.variant(help="emit the files uploaded as a JSON array")
RESOURCES_JSON = ACTIONS_JSON.variant(
    help="emit the resources created, updated, removed or skipped as a JSON array"
)
CREATE_JSON = ACTIONS_JSON.variant(
    help=(
        "emit the resources created, updated, removed or skipped as a JSON"
        " array; with --dry-run, the processed specifications"
    )
)
ENTITY_JSON = ACTIONS_JSON.variant(
    help=(
        "emit the created entity as JSON; with --dry-run, the processed"
        " specification; not with --progress or --report"
    )
)
FOLLOW_WORK_REQUIREMENT_EVENTS = FOLLOW.variant(
    help="follow work requirement events after applying action"
)
INTERACTIVE = option(
    "--interactive",
    "-i",
    action="store_true",
    required=False,
    help="list, and interactively select, the items to act on",
)
YES = option(
    "--yes",
    "-y",
    action="store_true",
    required=False,
    help=("perform modifying/destructive actions without requiring user confirmation"),
)
DETAILS = option(
    "--details",
    "-d",
    action="store_true",
    required=False,
    help="show the full JSON representation of objects",
)
DRY_RUN_ACTION = DRY_RUN.variant(help="dry-run the action without applying any changes")
JSONNET_DRY_RUN = option(
    "--jsonnet-dry-run",
    "-J",
    action="store_true",
    required=False,
    help="dry-run Jsonnet processing into JSON",
)
VALIDATE = option(
    "--validate",
    action="store_true",
    required=False,
    help=(
        "check the specification against its JSON Schema and stop, reporting"
        " every violation"
    ),
)
COMPUTE_REQS_INSTANCES_OR_NODES = option(
    "compute_reqs_instances_or_nodes",
    nargs="*",
    default="",
    metavar="<name-or-ID>",
    type=str,
    help=(
        "the name(s) or YellowDog ID(s) of the compute "
        "requirement(s), ID(s) of nodes, or instances in "
        "'cr_id.instance_id' format; a name may be a glob pattern"
        " (e.g. 'cr-*')"
    ),
)
FOLLOW_COMPUTE_REQUIREMENT_EVENTS = FOLLOW.variant(
    help="follow compute requirement events after applying action"
)
WORK_REQUIREMENTS = option(
    "work_requirements",
    nargs="*",
    default="",
    metavar="<work-requirement-name-or-ID>",
    type=str,
    help=(
        "the name(s) or YellowDog ID(s) of the work requirement(s) to be"
        " cancelled; can also supply task IDs; a name may be a glob"
        " pattern (e.g. 'proj-*')"
    ),
)
RESOURCE_SPECIFICATIONS = option(
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
YES_ALLOW_UPDATES = YES.variant(help="allow updates without user confirmation")
MATCH_ALLOWANCES_BY_DESCRIPTION = option(
    "--match-allowances-by-description",
    "-M",
    action="store_true",
    required=False,
    help=(
        "match using the 'description' property when updating "
        "(using yd-create) or removing allowances"
    ),
)
YELLOWDOG_IDS = option(
    "yellowdog_ids",
    nargs="*",
    default=[],
    metavar="<yellowdog-id>",
    type=str,
    help="the YellowDog ID(s) of the item(s) to follow",
)
PROGRESS = option(
    "--progress",
    action="store_true",
    required=False,
    help=(
        "display a live progress bar for Work Requirement IDs; "
        "ignored for Worker Pool and Compute Requirement IDs"
    ),
)
CONTENT_PATH = option(
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
FOLLOW_PROVISIONING = FOLLOW.variant(help="follow progress after provisioning")
TARGET = option(
    "--target",
    "-T",
    type=int,
    required=False,
    help="override targetInstanceCount from the spec or config",
    metavar="<n>",
)
AUTO_FOLLOW_COMPUTE_REQUIREMENTS = option(
    "--auto-follow-compute-requirements",
    "-a",
    action="store_true",
    required=False,
    help=(
        "automatically follow the associated compute requirements when"
        " following worker pools"
    ),
)
SHOW_SECRETS = option(
    "--show-secrets",
    action="store_true",
    required=False,
    help="print AWS secret key during setup",
)
SUBSTITUTE_IDS = option(
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
STRIP_IDS = option(
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
OUTPUT_FILE = option(
    "--output-file",
    type=str,
    required=False,
    help=(
        "if specified, the detailed JSON resource listing will also be written "
        "to the nominated output file"
    ),
    metavar="<output-file>",
)
UPGRADE_RCLONE = option(
    "--upgrade-rclone",
    action="store_true",
    required=False,
    help="download the latest rclone binary, then exit",
)
WHICH_RCLONE = option(
    "--which-rclone",
    action="store_true",
    required=False,
    help="report the path and version of the rclone binary in use, then exit",
)

# The data client set, shared by every data client command.
REMOTE = option(
    "--remote",
    "-r",
    type=str,
    required=False,
    help="rclone remote name or inline config string; overrides [dataClient] config",
    metavar="<remote>",
)
BUCKET = option(
    "--bucket",
    "-b",
    type=str,
    required=False,
    help="bucket or container name; overrides [dataClient] config",
    metavar="<bucket>",
)
PREFIX = option(
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
NO_PREFIX = option(
    "--no-prefix",
    action="store_true",
    required=False,
    help="suppress the default path prefix; place files at the bucket root",
)
DATA_CLIENT_PROFILE = option(
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
DRY_RUN_TRANSFERS = DRY_RUN.variant(
    help="show what would happen without performing any transfers"
)
DATA_CLIENT_OPTIONS: tuple[Option, ...] = (
    REMOTE,
    BUCKET,
    PREFIX,
    NO_PREFIX,
    UPGRADE_RCLONE,
    WHICH_RCLONE,
    DATA_CLIENT_PROFILE,
    DRY_RUN_TRANSFERS,
)

DESTINATION = option(
    "--destination",
    "-d",
    type=str,
    required=False,
    help="explicit remote destination path, overriding the assembled default",
    metavar="<remote-path>",
)
RECURSIVE = option(
    "--recursive",
    "-R",
    action="store_true",
    required=False,
    help="upload directories recursively",
)
FLATTEN = option(
    "--flatten",
    action="store_true",
    required=False,
    help="strip directory structure; upload all files flat under the destination",
)
SYNC = option(
    "--sync",
    action="store_true",
    required=False,
    help=(
        "mirror the local source to the remote destination, deleting remote "
        "files not present locally; implies --recursive"
    ),
)
REMOTE_PATHS = option(
    "remote_paths",
    metavar="<remote-path>",
    type=str,
    nargs="+",
    help="remote file(s) or pattern(s) to download",
)


# --- Validators: run after parsing ---------------------------------------


def check_glob_and_literal_names(args: Namespace, parser: ArgumentParser) -> None:
    """
    Positional names/IDs on the destructive commands. A name may be a glob
    pattern; globs route through the summary-based dry-run and are allowed
    with --dry-run, but must not be mixed with literal names/IDs.
    """
    explicit_names: list[str] = []
    for attr in (
        "work_requirements",
        "worker_pool_nodes_list",
        "compute_reqs_instances_or_nodes",
    ):
        value = getattr(args, attr, None)
        if isinstance(value, list):
            explicit_names.extend(value)
    globs = [n for n in explicit_names if contains_glob_chars(n)]
    literals = [n for n in explicit_names if not contains_glob_chars(n)]
    if globs and literals:
        parser.error("cannot mix name glob patterns with explicit names/IDs")
    if getattr(args, "dry_run", False) and literals:
        parser.error("--dry-run is not supported with explicit names/IDs")


# The options that write their own output to stdout, which '--json' cannot
# share with its document
_STREAMING_OPTIONS = (
    ("progress", "--progress"),
    ("report", "--report"),
)


def check_json_excludes_streaming(args: Namespace, parser: ArgumentParser) -> None:
    """
    On the single-object creators, refuse '--json' with an option that
    writes its own output to stdout: a progress bar or a report table
    would share stdout with the document. '--follow' alone reports through
    messages '--json' silences, so it is allowed.
    """
    if not getattr(args, "json", False):
        return
    for dest, flag in _STREAMING_OPTIONS:
        if getattr(args, dest, False):
            parser.error(
                f"--json cannot be combined with {flag}: --progress and --report"
                " write their own output"
            )


def check_follow_json_excludes_progress(
    args: Namespace, parser: ArgumentParser
) -> None:
    """
    On yd-follow, '--json' prints the events themselves, so the one option it
    cannot share stdout with is the progress bar, which consumes the events
    rather than printing them.
    """
    if getattr(args, "json", False) and getattr(args, "progress", False):
        parser.error(
            "--json cannot be combined with --progress: --json prints the raw"
            " events, which --progress replaces with a progress bar"
        )


def check_schema_mode_is_exclusive(args: Namespace, parser: ArgumentParser) -> None:
    """
    yd-schema takes exactly one of a family, --write, --check or --list: each
    names a different thing to do, and none is a sensible default for the
    others.
    """
    given = [
        name
        for name, value in (
            ("family", getattr(args, "family", None)),
            ("--write", getattr(args, "write", None)),
            ("--check", getattr(args, "check", None)),
            ("--list", getattr(args, "list", False)),
        )
        if value
    ]
    if len(given) == 0:
        parser.error("give a family, or one of --write, --check or --list")
    if len(given) > 1:
        parser.error(f"cannot combine {' and '.join(given)}")


# --- Commands ------------------------------------------------------------
# Each command's options are listed in the order the pre-registry
# CLIParser.__init__ registered them, which is the order argparse prints
# them in; reordering changes --help.

# --- yd-abort ------------------------------------------------------------

TASK_ID_LIST = option(
    "task_id_list",
    nargs="*",
    default="",
    metavar="<target>",
    type=str,
    help=(
        "items to target: executing task YDID(s) to abort directly; Work"
        " Requirement name(s), 'namespace/wr-name' or YDID(s) to abort all"
        " executing tasks within; Task Group YDID(s), 'wr-name/tg-name' or"
        " 'namespace/wr-name/tg-name' to abort executing tasks in a specific"
        " group. Without arguments, selects interactively by namespace and"
        " tag."
    ),
)

COMMANDS["yd-abort"] = Command(
    name="yd-abort",
    purpose="aborting Tasks individually, or in Work Requirements or Task Groups",
    summary="Abort running Tasks",
    kind=CommandKind.API,
    options=(SORT, REVERSE, VARIABLE, NAMESPACE, TAG, YES, ACTIONS_JSON, TASK_ID_LIST),
    requires_namespace_and_tag=True,
    tool=ToolKind.DESTRUCTIVE,
)

# --- yd-application ------------------------------------------------------

COMMANDS["yd-application"] = Command(
    name="yd-application",
    purpose="reporting the details of the current Application",
    summary="Report details of the current Application",
    kind=CommandKind.API,
    options=(
        VARIABLE,
        JSON.variant(help="emit the Application's details as JSON"),
    ),
    tool=ToolKind.READ_ONLY,
)

# --- yd-boost ------------------------------------------------------------

BOOST_HOURS = option(
    "boost_hours",
    metavar="<boost hours>",
    type=positive_int,
    help="the number of hours to boost the allowance by (at least 1)",
)
ALLOWANCES = option(
    "allowances",
    metavar="<allowance-ID>",
    nargs="+",
    type=str,
    help="the YellowDog ID(s) of the allowance(s) to boost",
)


def check_allowance_ids(args: Namespace, parser: ArgumentParser) -> None:
    """
    yd-boost's Allowance IDs, before anything is fetched or boosted. The
    YDID parser is imported here, so this module still imports nothing at
    load beyond settings.py and glob_utils.py.
    """
    from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

    for allowance_id in args.allowances:
        if get_ydid_type(allowance_id) != YDIDType.ALLOWANCE:
            parser.error(f"not a YellowDog Allowance ID: '{allowance_id}'")


COMMANDS["yd-boost"] = Command(
    name="yd-boost",
    purpose="boosting Allowances",
    summary="Boost Allowances",
    kind=CommandKind.API,
    options=(VARIABLE, YES, ACTIONS_JSON, BOOST_HOURS, ALLOWANCES),
    validators=(check_allowance_ids,),
    tool=ToolKind.DESTRUCTIVE,
)

# --- yd-cancel -----------------------------------------------------------

ABORT = option(
    "--abort",
    "-a",
    action="store_true",
    required=False,
    help="abort running tasks with immediate effect",
)

COMMANDS["yd-cancel"] = Command(
    name="yd-cancel",
    purpose="cancelling Work Requirements",
    summary="Cancel Work Requirements",
    kind=CommandKind.API,
    options=(
        SORT,
        REVERSE,
        VARIABLE,
        NAMESPACE,
        TAG,
        ABORT,
        FOLLOW.variant(help="follow progress after cancelling the work requirement(s)"),
        DRY_RUN,
        DRY_RUN_JSON,
        INTERACTIVE,
        YES,
        WORK_REQUIREMENTS,
    ),
    validators=(check_glob_and_literal_names,),
    requires_namespace_and_tag=True,
    tool=ToolKind.DESTRUCTIVE,
)

# --- yd-cloudwizard ------------------------------------------------------

OPERATION = option(
    "operation",
    metavar="'setup', 'teardown', 'add-ssh' or 'remove-ssh'",
    type=str,
    choices=["setup", "teardown", "add-ssh", "remove-ssh"],
    help=(
        "the cloud wizard operation to perform: 'setup', 'teardown',"
        " 'add-ssh' or 'remove-ssh'"
    ),
)
CLOUD_PROVIDER = option(
    "--cloud-provider",
    required=True,
    metavar="<name of cloud provider>",
    type=str,
    help=(
        "the name of the cloud provider (AWS, GCP, and Azure are currently supported)"
    ),
)
CREDENTIALS_FILE = option(
    "--credentials-file",
    required=False,
    metavar="<file-containing-google-credentials>",
    type=str,
    help=(
        "the name of the file containing the cloud GCP credentials when"
        " using Cloud Wizard with GCP"
    ),
)
REGION_NAME = option(
    "--region-name",
    "-R",
    required=False,
    metavar="<cloud-provider-region-name>",
    type=str,
    help="specify the cloud provider region name for certain operations",
)
INSTANCE_TYPE = option(
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

COMMANDS["yd-cloudwizard"] = Command(
    name="yd-cloudwizard",
    purpose="setting up cloud accounts and YellowDog resources",
    summary="Set up cloud accounts and YellowDog resources (needs the cloudwizard extra)",
    kind=CommandKind.API,
    options=(
        VARIABLE,
        YES,
        OPERATION,
        CLOUD_PROVIDER,
        CREDENTIALS_FILE,
        REGION_NAME,
        INSTANCE_TYPE,
        SHOW_SECRETS,
    ),
    tool=ToolKind.NONE,
)

# --- yd-compare ----------------------------------------------------------

WR_OR_TG_ID = option(
    "wr_or_tg_id",
    metavar="<work-requirement-or-task-group-ID>",
    type=str,
    help=("the YellowDog ID of the work requirement or task group to be compared"),
)
WORKER_POOL_IDS = option(
    "worker_pool_ids",
    metavar="<provisioned-worker-pool-ID>",
    type=str,
    nargs="+",
    help="the YellowDog ID(s) of the provisioned worker pool(s) to compare",
)
RUNNING_NODES_ONLY = option(
    "--running-nodes-only",
    action="store_true",
    required=False,
    help="only compare against nodes in the RUNNING state",
)


def check_compare_ids(args: Namespace, parser: ArgumentParser) -> None:
    """
    yd-compare's positional IDs, by type, before anything is fetched: a Work
    Requirement or Task Group ID, then Worker Pool IDs. The YDID parser is
    imported here, so this module still imports nothing at load beyond
    settings.py and glob_utils.py.
    """
    from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

    if get_ydid_type(args.wr_or_tg_id) not in (
        YDIDType.WORK_REQUIREMENT,
        YDIDType.TASK_GROUP,
    ):
        parser.error(
            f"not a YellowDog Work Requirement or Task Group ID: '{args.wr_or_tg_id}'"
        )
    for worker_pool_id in args.worker_pool_ids:
        if get_ydid_type(worker_pool_id) != YDIDType.WORKER_POOL:
            parser.error(f"not a YellowDog Worker Pool ID: '{worker_pool_id}'")


COMMANDS["yd-compare"] = Command(
    name="yd-compare",
    purpose=(
        "comparing whether a work requirement or task group is matched by "
        "workers in the specified provisioned worker pools"
    ),
    summary="Compare a Work Requirement or Task Group against Worker Pool(s)",
    kind=CommandKind.API,
    options=(
        WR_OR_TG_ID,
        WORKER_POOL_IDS,
        RUNNING_NODES_ONLY,
        ACTIONS_JSON.variant(
            help=(
                "emit the comparison as a JSON array, one object per Worker Pool"
                " compared with each Task Group"
            )
        ),
    ),
    validators=(check_compare_ids,),
    tool=ToolKind.READ_ONLY,
)

# --- yd-compute-restart / yd-compute-start / yd-compute-stop --------------


def _compute_action_options(
    targets: Option,
) -> tuple[Option | Exclusive, ...]:
    return (
        SORT,
        REVERSE,
        VARIABLE,
        NAMESPACE,
        TAG,
        INTERACTIVE,
        YES,
        ACTIONS_JSON,
        targets,
        FOLLOW_COMPUTE_REQUIREMENT_EVENTS,
    )


COMMANDS["yd-compute-restart"] = Command(
    name="yd-compute-restart",
    purpose="restarting Instances",
    summary="Restart Instances",
    kind=CommandKind.API,
    # Restart is instance-level only: no Compute Requirement names, IDs or
    # listing, so none of the options that select or sort them
    options=(
        VARIABLE,
        YES,
        ACTIONS_JSON,
        COMPUTE_REQS_INSTANCES_OR_NODES.variant(
            nargs="+",
            metavar="<instance-or-node-ID>",
            help="the ID(s) of nodes, or instances in 'cr_id.instance_id' format",
        ),
        FOLLOW_COMPUTE_REQUIREMENT_EVENTS,
    ),
    tool=ToolKind.DESTRUCTIVE,
)
COMMANDS["yd-compute-start"] = Command(
    name="yd-compute-start",
    purpose="starting stopped Compute Requirements and Instances",
    summary="Start stopped Compute Requirements and Instances",
    kind=CommandKind.API,
    options=_compute_action_options(COMPUTE_REQS_INSTANCES_OR_NODES),
    validators=(check_glob_and_literal_names,),
    requires_namespace_and_tag=True,
    tool=ToolKind.DESTRUCTIVE,
)
COMMANDS["yd-compute-stop"] = Command(
    name="yd-compute-stop",
    purpose="stopping Compute Requirements and Instances",
    summary="Stop Compute Requirements and Instances",
    kind=CommandKind.API,
    options=_compute_action_options(COMPUTE_REQS_INSTANCES_OR_NODES),
    validators=(check_glob_and_literal_names,),
    requires_namespace_and_tag=True,
    tool=ToolKind.DESTRUCTIVE,
)

# --- yd-copy -------------------------------------------------------------

SRC_PATH = option(
    "src_path",
    metavar="<src-path>",
    type=str,
    nargs="?",
    help="source path relative to the configured source remote/bucket/prefix",
)
DST_PATH = option(
    "dst_path",
    metavar="<dst-path>",
    type=str,
    nargs="?",
    help="destination path relative to the configured destination remote/bucket/prefix",
)
DST_PROFILE = option(
    "--dst-profile",
    type=str,
    required=False,
    help=(
        "select a named [dataClient.<name>] profile for the destination; "
        "inherits unset fields from [dataClient]"
    ),
    metavar="<name>",
)
DST_PREFIX = option(
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

COMMANDS["yd-copy"] = Command(
    name="yd-copy",
    purpose="copying files between remote data client locations",
    summary="Copy files between remote data client locations",
    kind=CommandKind.DATA_CLIENT,
    options=(
        VARIABLE,
        NAMESPACE,
        TAG,
        *DATA_CLIENT_OPTIONS,
        SRC_PATH,
        DST_PATH,
        DST_PROFILE,
        DST_PREFIX,
        RECURSIVE.variant(
            help="copy directories recursively (rclone copies recursively by default)"
        ),
        SYNC.variant(
            help=(
                "make the destination a mirror of the source, "
                "deleting destination files not present in the source"
            )
        ),
        TRANSFERS_JSON.variant(help="emit the files copied as a JSON array"),
    ),
    requires_namespace_and_tag=True,
    tool=ToolKind.ACTING,
)

# --- yd-create / yd-remove -----------------------------------------------

SHOW_KEYRING_PASSWORDS = option(
    "--show-keyring-passwords",
    action="store_true",
    required=False,
    help="display YellowDog-generated password when creating a Keyring",
)
REGENERATE_APP_KEYS = option(
    "--regenerate-app-keys",
    action="store_true",
    required=False,
    help="regenerate the application key & secret when updating an application",
)
NO_RESEQUENCE = option(
    "--no-resequence",
    action="store_true",
    required=False,
    help=(
        "don't re-sequence resources prior to creation (e.g., "
        "putting source templates before requirement templates)"
    ),
)

COMMANDS["yd-create"] = Command(
    name="yd-create",
    purpose="creating and updating resources",
    summary="Create and update resources",
    kind=CommandKind.API,
    options=(
        VARIABLE,
        NAMESPACE,
        TAG,
        DRY_RUN_ACTION,
        JSONNET_DRY_RUN,
        VALIDATE,
        CREATE_JSON,
        RESOURCE_SPECIFICATIONS,
        YES_ALLOW_UPDATES,
        MATCH_ALLOWANCES_BY_DESCRIPTION,
        SHOW_KEYRING_PASSWORDS,
        REGENERATE_APP_KEYS,
        NO_RESEQUENCE,
    ),
    requires_namespace_and_tag=True,
    tool=ToolKind.ACTING,
    tool_description=(
        "Create or update resources from specifications (each a file path,"
        " or the specification itself). Returns {resource, name, id, action}"
        " per resource created, updated or skipped; yd_schema resources"
        " gives the schema to compose against."
    ),
)

IDS = option(
    "--ids",
    action="store_true",
    required=False,
    help="remove resources using their YellowDog IDs (YDIDs)",
)

COMMANDS["yd-remove"] = Command(
    name="yd-remove",
    purpose="removing resources",
    summary="Remove resources",
    kind=CommandKind.API,
    options=(
        VARIABLE,
        NAMESPACE,
        TAG,
        JSONNET_DRY_RUN,
        RESOURCES_JSON,
        RESOURCE_SPECIFICATIONS,
        YES_ALLOW_UPDATES,
        MATCH_ALLOWANCES_BY_DESCRIPTION,
        IDS,
    ),
    requires_namespace_and_tag=True,
    tool=ToolKind.DESTRUCTIVE,
)

# --- yd-delete / yd-rm ---------------------------------------------------

COMMANDS["yd-delete"] = Command(
    name="yd-delete",
    purpose="deleting remote data client files and directories",
    summary="Delete remote data client files and directories (synonym: yd-rm)",
    kind=CommandKind.DATA_CLIENT,
    options=(
        VARIABLE,
        NAMESPACE,
        TAG,
        YES,
        *DATA_CLIENT_OPTIONS,
        REMOTE_PATHS.variant(
            nargs="*",
            help=(
                "remote file(s) or directory(ies) to delete; "
                "if omitted with --recursive, deletes the entire default prefix"
            ),
        ),
        RECURSIVE.variant(help="delete directories recursively"),
        DRY_RUN_JSON.variant(
            help=(
                "emit the deletions, or with --dry-run the matched items, as a"
                " JSON array"
            )
        ),
    ),
    requires_namespace_and_tag=True,
    tool=ToolKind.DESTRUCTIVE,
)
# The prog is set by the caller, so one object serves both names.
COMMANDS["yd-rm"] = COMMANDS["yd-delete"]

# --- yd-doctor -----------------------------------------------------------

COMMANDS["yd-doctor"] = Command(
    name="yd-doctor",
    purpose="checking the installation, configuration and platform connection",
    summary="Check the installation, configuration and platform connection",
    kind=CommandKind.API,
    options=(
        VARIABLE,
        NAMESPACE,
        TAG,
        OFFLINE,
        JSON.variant(help="emit the check results as a JSON array"),
        TIMEOUT,
    ),
    requires_namespace_and_tag=True,
    tool=ToolKind.READ_ONLY,
)

# --- yd-download ---------------------------------------------------------

INTO = option(
    "--into",
    type=str,
    required=False,
    default=None,
    help=(
        "local directory to download each remote item into, under its "
        "own name; unlike --destination, which names the local path "
        "corresponding to a single remote item"
    ),
    metavar="<local-dir>",
)

COMMANDS["yd-download"] = Command(
    name="yd-download",
    purpose="downloading files from a remote data client",
    summary="Download files from a remote data client",
    kind=CommandKind.DATA_CLIENT,
    options=(
        VARIABLE,
        NAMESPACE,
        TAG,
        *DATA_CLIENT_OPTIONS,
        REMOTE_PATHS,
        # '--destination' names the local path corresponding to one remote
        # item; '--into' names a container directory that several items keep
        # their own names inside. Honouring both is meaningless, so let
        # argparse refuse the combination rather than picking one.
        Exclusive(
            (
                DESTINATION.variant(
                    default=None,
                    help="local directory or file path to write to (default: mirrors remote name)",
                    metavar="<local-path>",
                ),
                INTO,
            )
        ),
        SYNC.variant(
            help=(
                "mirror the remote source to the local destination, deleting local "
                "files not present remotely"
            )
        ),
        FLATTEN.variant(
            help="strip remote directory structure; download all files flat"
        ),
        DRY_RUN_JSON.variant(
            help=(
                "emit the downloads, or with --dry-run the matched items, as a"
                " JSON array"
            )
        ),
    ),
    requires_namespace_and_tag=True,
    tool=ToolKind.ACTING,
    tool_description=(
        "Download objects (task outputs, results) from the namespace's object"
        " store to the local machine. remote_paths are object paths relative"
        " to the configured prefix, which defaults to '<namespace>/<tag>' (set"
        " no_prefix to give paths relative to the bucket root instead);"
        " wildcards are allowed. Returns one record per file: {source, destination, size,"
        " action, match}. Use dry_run first to see what would be fetched."
    ),
)

# --- yd-finish / yd-hold / yd-start --------------------------------------


def _work_requirement_action_options(
    targets: Option,
) -> tuple[Option | Exclusive, ...]:
    return (
        SORT,
        REVERSE,
        VARIABLE,
        NAMESPACE,
        TAG,
        FOLLOW_WORK_REQUIREMENT_EVENTS,
        INTERACTIVE,
        YES,
        ACTIONS_JSON,
        targets,
    )


COMMANDS["yd-finish"] = Command(
    name="yd-finish",
    purpose="finishing Work Requirements",
    summary="Finish Work Requirements",
    kind=CommandKind.API,
    options=_work_requirement_action_options(
        WORK_REQUIREMENTS.variant(
            help=(
                "the name(s) or YellowDog ID(s) of the work requirement(s) to be"
                " finished; a name may be a glob pattern (e.g. 'proj-*')"
            )
        )
    ),
    validators=(check_glob_and_literal_names,),
    requires_namespace_and_tag=True,
    tool=ToolKind.DESTRUCTIVE,
)
COMMANDS["yd-hold"] = Command(
    name="yd-hold",
    purpose="holding (pausing) running Work Requirements",
    summary="Hold (pause) running Work Requirements",
    kind=CommandKind.API,
    options=_work_requirement_action_options(
        WORK_REQUIREMENTS.variant(
            help=(
                "the name(s) or YellowDog ID(s) of the work requirement(s) to be"
                " held (paused); a name may be a glob pattern (e.g. 'proj-*')"
            )
        )
    ),
    validators=(check_glob_and_literal_names,),
    requires_namespace_and_tag=True,
    tool=ToolKind.DESTRUCTIVE,
)
COMMANDS["yd-start"] = Command(
    name="yd-start",
    purpose="starting held (paused) Work Requirements",
    summary="Start held (paused) Work Requirements",
    kind=CommandKind.API,
    options=_work_requirement_action_options(
        WORK_REQUIREMENTS.variant(
            help=(
                "the name(s) or YellowDog ID(s) of the held (paused) work"
                " requirement(s) to be started; a name may be a glob pattern"
                " (e.g. 'proj-*')"
            )
        )
    ),
    validators=(check_glob_and_literal_names,),
    requires_namespace_and_tag=True,
    tool=ToolKind.DESTRUCTIVE,
)

# --- yd-follow / yd-show / yd-wait ---------------------------------------

COMMANDS["yd-follow"] = Command(
    name="yd-follow",
    purpose="following event streams",
    summary="Follow event streams",
    kind=CommandKind.API,
    options=(
        VARIABLE,
        YELLOWDOG_IDS,
        PROGRESS,
        AUTO_FOLLOW_COMPUTE_REQUIREMENTS,
        ACTIONS_JSON.variant(
            help=(
                "print each event as a JSON document as it arrives"
                " (not with --progress)"
            )
        ),
    ),
    validators=(check_follow_json_excludes_progress,),
    tool=ToolKind.ACTING,
    tool_description=(
        "Collect the events of Work Requirements, Worker Pools or Compute"
        " Requirements (by YDID) for up to timeout_seconds, then return them"
        " as an array; the call ends early when every entity reaches a"
        " terminal state. Each event is the entity's current state, so the"
        " last one per entity is its latest status."
    ),
)

SHOW_TOKEN = option(
    "--show-token",
    action="store_true",
    required=False,
    help=(
        "display the worker pool token when showing the details of a "
        "configured worker pool"
    ),
)


def check_show_ids(args: Namespace, parser: ArgumentParser) -> None:
    """
    yd-show's '--substitute-ids', refused when none of the IDs is of a kind
    whose details it substitutes names into (Compute Source and Requirement
    Templates, Allowances), rather than ignored. '--show-token' is left
    alone: whether a Worker Pool is a Configured one is known only once it
    has been fetched.
    """
    from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

    substitutable = (
        YDIDType.COMPUTE_SOURCE_TEMPLATE,
        YDIDType.COMPUTE_REQUIREMENT_TEMPLATE,
        YDIDType.ALLOWANCE,
    )
    if args.substitute_ids and not any(
        get_ydid_type(ydid) in substitutable for ydid in args.yellowdog_ids
    ):
        parser.error(
            "--substitute-ids applies only to Compute Source Template, Compute"
            " Requirement Template and Allowance IDs, and none was given"
        )


COMMANDS["yd-show"] = Command(
    name="yd-show",
    purpose="showing the JSON details of entities referenced by their YDIDs",
    summary="Show the JSON details of entities referenced by their YDIDs",
    kind=CommandKind.API,
    # A YDID names its entity in whatever namespace it is in: no namespace
    # or tag is used
    options=(
        VARIABLE,
        YELLOWDOG_IDS.variant(
            nargs="+",
            help=(
                "the YellowDog ID(s) of the item(s) to show"
                "; Instances have no ID of their own and are specified "
                "in 'cr_id.instance_id' format"
            ),
        ),
        SHOW_TOKEN,
        SUBSTITUTE_IDS,
        STRIP_IDS,
        OUTPUT_FILE,
    ),
    validators=(check_show_ids,),
    tool=ToolKind.READ_ONLY,
)

COMMANDS["yd-wait"] = Command(
    name="yd-wait",
    purpose=(
        "waiting for Work Requirements, Worker Pools, or Compute Requirements"
        " to reach a terminal state"
    ),
    summary="Wait for entities to reach a terminal state",
    kind=CommandKind.API,
    options=(
        VARIABLE,
        YELLOWDOG_IDS.variant(help="the YellowDog ID(s) of the item(s) to wait"),
        ACTIONS_JSON.variant(help="emit each item's final status as a JSON array"),
    ),
    tool=ToolKind.ACTING,
)

# --- yd-instantiate / yd-provision ---------------------------------------

COMPUTE_REQUIREMENT = option(
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
REPORT = option(
    "--report",
    "-r",
    action="store_true",
    required=False,
    help="report on a dynamic template test run",
)
COMPUTE_REQUIREMENT_FILE_POSITIONAL = option(
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

COMMANDS["yd-instantiate"] = Command(
    name="yd-instantiate",
    purpose="instantiating a Compute Requirement",
    summary="Instantiate a Compute Requirement",
    kind=CommandKind.API,
    options=(
        VARIABLE,
        NAMESPACE,
        TAG,
        WORKER_POOL,
        DRY_RUN_ACTION,
        COMPUTE_REQUIREMENT,
        REPORT,
        JSONNET_DRY_RUN,
        VALIDATE,
        ENTITY_JSON,
        CONTENT_PATH,
        FOLLOW_PROVISIONING,
        TARGET,
        COMPUTE_REQUIREMENT_FILE_POSITIONAL,
    ),
    requires_namespace_and_tag=True,
    validators=(check_json_excludes_streaming,),
    tool=ToolKind.ACTING,
)

WORKER_POOL_FILE_POSITIONAL = option(
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

COMMANDS["yd-provision"] = Command(
    name="yd-provision",
    purpose="provisioning a Worker Pool",
    summary="Provision a Worker Pool",
    kind=CommandKind.API,
    options=(
        VARIABLE,
        NAMESPACE,
        TAG,
        WORKER_POOL,
        DRY_RUN_ACTION,
        JSONNET_DRY_RUN,
        VALIDATE,
        ENTITY_JSON,
        CONTENT_PATH,
        FOLLOW_PROVISIONING,
        TARGET,
        AUTO_FOLLOW_COMPUTE_REQUIREMENTS,
        WORKER_POOL_FILE_POSITIONAL,
    ),
    requires_namespace_and_tag=True,
    validators=(check_json_excludes_streaming,),
    tool=ToolKind.ACTING,
    tool_description=(
        "Provision a Worker Pool from a specification (a file path, or the"
        " specification itself). Returns {id, name, namespace, type}. With"
        " dry_run, the processed specification. Shut it"
        " down afterwards with yd_shutdown; yd_schema worker-pool gives the"
        " schema to compose against."
    ),
)

# --- yd-list -------------------------------------------------------------

LIST_NAMESPACE = NAMESPACE.variant(help="the namespace to use when listing entities")
# Tag attribute is defaulted to "" when using 'yd-list'
LIST_TAG = TAG.variant(default="", help="the tag to search when listing entities")
IDS_ONLY = option(
    "--ids-only",
    "-D",
    action="store_true",
    required=False,
    help="list the YellowDog IDs only",
)
COUNT = option(
    "--count",
    "-C",
    action="store_true",
    required=False,
    help=(
        "print only the number of matching items (implies '--quiet';"
        " overrides '--details', '--json' and '--ids-only')"
    ),
)
ENTITY_TYPE = option(
    "entity_type",
    type=resolve_entity_type,
    metavar="ENTITY_TYPE",
    help=(
        "type of entity to list; accepts a full name, an unambiguous "
        "prefix (e.g. 'work-r'), or a single uppercase synonym "
        "(e.g. 'W'). Valid types: " + _ENTITY_TYPE_HELP
    ),
)
ACTIVE_ONLY = option(
    "--active-only",
    "-l",
    action="store_true",
    required=False,
    help=("list only active compute requirements / worker pools / work requirements"),
)
NAME = option(
    "--name",
    dest="name_glob",
    metavar="<glob>",
    required=False,
    help=(
        "list only entities whose name matches the given glob "
        "pattern (e.g. 'proj-*'); applies to work requirements, "
        "worker pools, compute requirements, compute requirement/source "
        "templates, image families, users, applications, groups, "
        "roles, keyrings and permissions; not supported for other "
        "entity types; a value without "
        "wildcards matches the name exactly, so use '*' for partial "
        "matches (e.g. 'linux*' or '*linux*')"
    ),
)
STATUS = option(
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
PUBLIC_IPS_ONLY = option(
    "--public-ips-only",
    action="store_true",
    required=False,
    help="when used with 'instances', lists public IP addresses only",
)
AUTO_SELECT_ALL = option(
    "--auto-select-all",
    action="store_true",
    required=False,
    help="automatically select all listed objects (implies '--details')",
)


def check_list_options(args: Namespace, parser: ArgumentParser) -> None:
    """
    yd-list's filtering options, refused for an entity type they do not
    apply to rather than ignored: a script would otherwise take an
    unfiltered listing for a filtered one.
    """
    entity_type = args.entity_type
    for dest, flag, types in (
        ("name_glob", "--name", LIST_NAME_TYPES),
        ("status_filter", "--status", LIST_STATUS_TYPES),
        ("active_only", "--active-only", LIST_ACTIVE_TYPES),
        ("ids_only", "--ids-only", LIST_ID_TYPES),
        ("substitute_ids", "--substitute-ids", LIST_SUBSTITUTE_TYPES),
        ("public_ips_only", "--public-ips-only", frozenset({ET_INSTANCES})),
    ):
        if getattr(args, dest, None) and entity_type not in types:
            parser.error(
                f"{flag} does not apply to {entity_type}; it applies to "
                + ", ".join(sorted(types))
            )
    if args.public_ips_only:
        for dest, flag in (
            ("json", "--json"),
            ("ids_only", "--ids-only"),
            ("details", "--details"),
        ):
            if getattr(args, dest, False):
                parser.error(f"--public-ips-only cannot be used with {flag}")


COMMANDS["yd-list"] = Command(
    name="yd-list",
    purpose="listing all kinds of YellowDog items",
    summary="List YellowDog items",
    kind=CommandKind.API,
    options=(
        SORT,
        REVERSE,
        VARIABLE,
        LIST_NAMESPACE,
        LIST_TAG,
        Exclusive((IDS_ONLY, JSON)),
        COUNT,
        YES,
        ENTITY_TYPE,
        ACTIVE_ONLY,
        NAME,
        STATUS,
        PUBLIC_IPS_ONLY,
        DETAILS,
        AUTO_SELECT_ALL,
        SUBSTITUTE_IDS,
        STRIP_IDS,
        OUTPUT_FILE,
    ),
    validators=(check_list_options,),
    tool=ToolKind.READ_ONLY,
    tool_description=(
        "List entities of one type in the namespace, optionally filtered by"
        " name pattern and status. entity_type is the full type name"
        " (work-requirements, worker-pools, compute-requirements, tasks,"
        " task-groups, nodes, workers, images, ...). Returns an array of"
        " summary objects; details adds each entity's full object."
    ),
)

# --- yd-ls ---------------------------------------------------------------

LONG = option(
    "--long",
    "-l",
    action="store_true",
    required=False,
    help="long listing: show file sizes and modification timestamps",
)

COMMANDS["yd-ls"] = Command(
    name="yd-ls",
    purpose="listing remote data client files and directories",
    summary="List remote data client files and directories",
    kind=CommandKind.DATA_CLIENT,
    options=(
        VARIABLE,
        NAMESPACE,
        TAG,
        *DATA_CLIENT_OPTIONS,
        REMOTE_PATHS.variant(
            nargs="*",
            help="remote path(s) to list; defaults to the configured prefix if omitted",
        ),
        RECURSIVE.variant(help="list directories recursively"),
        LONG,
        ACTIONS_JSON.variant(
            help="emit the listing as a JSON array of rclone 'lsjson' entries"
        ),
    ),
    requires_namespace_and_tag=True,
    tool=ToolKind.READ_ONLY,
)

# --- yd-nodeaction -------------------------------------------------------

ACTIONS = option(
    "--actions",
    "-S",
    type=str,
    required=False,
    help="node action spec file in JSON or Jsonnet format",
    metavar="<node_actions.json>",
)
NODE = option(
    "--node",
    "-N",
    type=str,
    required=False,
    action="append",
    help=("target a specific node by ID; can be specified multiple times"),
    metavar="<node-id>",
)
ALL_NODES = option(
    "--all-nodes",
    action="store_true",
    required=False,
    help=(
        "target all current nodes in the worker pool "
        "(filtered by nodeTypes if present in the spec)"
    ),
)
# Not a variant of yd-list's STATUS: this one is a flag, with no dest.
NODE_ACTION_STATUS = option(
    "--status",
    action="store_true",
    required=False,
    help="show the node action queue for the selected node(s)",
)


def check_node_action_args(args: Namespace, parser: ArgumentParser) -> None:
    """
    yd-nodeaction's options, as they combine: --actions unless --status,
    which takes neither it nor --validate; node and Worker Pool IDs of the
    right kind; and --timeout only with --follow. The YDID parser is
    imported here, so this module still imports nothing at load beyond
    settings.py and glob_utils.py.
    """
    from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

    if args.status:
        if getattr(args, "validate", False):
            parser.error("--validate cannot be used with --status")
        if args.actions is not None:
            parser.error("--actions cannot be used with --status")
    elif args.actions is None:
        parser.error("--actions is required, unless --status is given")
    for node_id in args.node or []:
        if get_ydid_type(node_id) != YDIDType.NODE:
            parser.error(f"not a YellowDog Node ID: '{node_id}'")
    worker_pool = args.worker_pool
    if (
        worker_pool is not None
        and worker_pool.startswith("ydid:")
        and get_ydid_type(worker_pool) != YDIDType.WORKER_POOL
    ):
        parser.error(f"not a YellowDog Worker Pool ID: '{worker_pool}'")
    if args.timeout is not None and not args.follow:
        parser.error("--timeout needs --follow")


COMMANDS["yd-nodeaction"] = Command(
    name="yd-nodeaction",
    purpose="submitting Node Actions to Worker Pool nodes",
    summary="Submit Node Actions to Worker Pool nodes",
    kind=CommandKind.API,
    options=(
        SORT,
        REVERSE,
        VARIABLE,
        NAMESPACE,
        TAG,
        YES,
        CONTENT_PATH,
        FOLLOW.variant(
            help=(
                "poll node action queues after submission, "
                "reporting progress until all actions complete or fail"
            )
        ),
        ACTIONS,
        VALIDATE,
        WORKER_POOL.variant(
            help="name of the target worker pool", metavar="<worker-pool-name>"
        ),
        Exclusive((NODE, ALL_NODES)),
        NODE_ACTION_STATUS,
        TIMEOUT.variant(
            default=None,
            help=(
                "with --follow, stop following after this many seconds, and fail"
                " if any node action queue has not finished (default: no limit)"
            ),
        ),
        DETAILS.variant(help="show the full JSON details for --status output"),
        ACTIONS_JSON.variant(
            help=(
                "emit the submissions, or with --status the node action queues,"
                " as a JSON array"
            )
        ),
    ),
    validators=(check_node_action_args,),
    requires_namespace_and_tag=True,
    tool=ToolKind.DESTRUCTIVE,
)

# --- yd-resize -----------------------------------------------------------

WORKER_POOL_POSITIONAL = option(
    "worker_pool",
    metavar="<worker-pool-or-compute-requirement-name-or-ID>",
    type=str,
    help=(
        "the name or YellowDog ID of the worker pool or compute requirement to resize"
    ),
)
WORKER_POOL_SIZE = option(
    "worker_pool_size",
    metavar="<new-node/instance-count>",
    type=non_negative_int,
    help="the desired number of (total) nodes in the worker pool",
)
# Not a variant of COMPUTE_REQUIREMENT: this one is a flag, with no type.
RESIZE_COMPUTE_REQUIREMENT = option(
    "--compute-requirement",
    "-C",
    action="store_true",
    required=False,
    help="resize a compute requirement instead of a worker pool",
)

COMMANDS["yd-resize"] = Command(
    name="yd-resize",
    purpose="resizing Worker Pools and Compute Requirements",
    summary="Resize Worker Pools and Compute Requirements",
    kind=CommandKind.API,
    options=(
        VARIABLE,
        NAMESPACE,
        TAG,
        YES,
        DRY_RUN_ACTION,
        ACTIONS_JSON,
        WORKER_POOL_POSITIONAL,
        WORKER_POOL_SIZE,
        RESIZE_COMPUTE_REQUIREMENT,
        FOLLOW.variant(help="follow progress after resizing"),
        AUTO_FOLLOW_COMPUTE_REQUIREMENTS,
    ),
    requires_namespace_and_tag=True,
    tool=ToolKind.DESTRUCTIVE,
)

# --- yd-schema -------------------------------------------------------------

SCHEMA_FAMILY = option(
    "family",
    nargs="?",
    choices=list(SCHEMA_FAMILIES),
    metavar="<family>",
    type=str,
    help=(
        "the specification family to print: work-requirement, worker-pool,"
        " compute-requirement, resources or node-actions"
    ),
)
SCHEMA_WRITE = option(
    "--write",
    type=str,
    metavar="<dir>",
    help="write every family's schema to <dir>, and index.json naming the CLI and SDK versions",
)
SCHEMA_CHECK = option(
    "--check",
    type=str,
    metavar="<dir>",
    help="exit 0 if the schemas in <dir> were written by the installed CLI and SDK, else 1 saying which changed",
)
SCHEMA_LIST = option(
    "--list",
    action="store_true",
    help="list the families",
)

COMMANDS["yd-schema"] = Command(
    name="yd-schema",
    purpose="printing, writing and checking the specification schemas",
    summary="Print, write or check the specification schemas",
    kind=CommandKind.STANDALONE,
    options=(
        SCHEMA_FAMILY,
        SCHEMA_WRITE,
        SCHEMA_CHECK,
        SCHEMA_LIST,
    ),
    validators=(check_schema_mode_is_exclusive,),
    tool=ToolKind.READ_ONLY,
    tool_description=(
        "Print the JSON Schema a specification family must follow —"
        " work-requirement (yd_submit), worker-pool (yd_provision),"
        " compute-requirement (yd_instantiate), resources (yd_create),"
        " node-actions (yd_nodeaction) — generated from the installed CLI"
        " and SDK. Ask for it before composing an inline specification."
    ),
)

# --- yd-shutdown ---------------------------------------------------------

WORKER_POOL_NODES_LIST = option(
    "worker_pool_nodes_list",
    nargs="*",
    default="",
    metavar="<worker-pool-name-or-ID/node-id>",
    type=str,
    help="the name(s) or YellowDog ID(s) of the worker pool(s) and/or ID(s) of"
    " nodes; a name may be a glob pattern (e.g. 'wp-*')",
)
TERMINATE = option(
    "--terminate",
    "-T",
    action="store_true",
    required=False,
    help="also immediately terminate associated compute requirement(s)",
)

COMMANDS["yd-shutdown"] = Command(
    name="yd-shutdown",
    purpose="shutting down Worker Pools and Nodes",
    summary="Shut down Worker Pools and Nodes",
    kind=CommandKind.API,
    options=(
        SORT,
        REVERSE,
        VARIABLE,
        NAMESPACE,
        TAG,
        DRY_RUN,
        DRY_RUN_JSON,
        INTERACTIVE,
        YES,
        WORKER_POOL_NODES_LIST,
        FOLLOW.variant(help="follow worker pool shutdown to completion"),
        TERMINATE,
        AUTO_FOLLOW_COMPUTE_REQUIREMENTS,
    ),
    validators=(check_glob_and_literal_names,),
    requires_namespace_and_tag=True,
    tool=ToolKind.DESTRUCTIVE,
)

# --- yd-submit -----------------------------------------------------------

WORK_REQUIREMENT = option(
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
JSON_RAW = option(
    "--json-raw",
    "-j",
    type=str,
    required=False,
    help="submit a 'raw' JSON work requirement file",
    metavar="<raw_work_requirement.json>",
)
EXIT_ON_FAILURE = option(
    "--exit-on-failure",
    "-E",
    action="store_true",
    required=False,
    help=(
        "when following (--follow/--progress), exit with a non-zero"
        " code if the work requirement ends in a FAILED or CANCELLED"
        " state"
    ),
)
TASK_TYPE = option(
    "--task-type",
    "-T",
    type=str,
    required=False,
    help="the task type to use",
    metavar="<task_type>",
)
TASK_COUNT = option(
    "--task-count",
    "-C",
    type=int,
    required=False,
    help="the number of tasks to submit (copies of a single task)",
    metavar="<task_count>",
)
TASK_GROUP_COUNT = option(
    "--task-group-count",
    "-G",
    type=int,
    required=False,
    help="the number of task groups to submit (copies of a single task group)",
    metavar="<task_group_count>",
)
TASK_BATCH_SIZE = option(
    "--task-batch-size",
    "-b",
    type=int,
    required=False,
    help="the batch size for task submission; must be between 1 and 10,000",
    metavar="<batch_size>",
)
PAUSE_BETWEEN_BATCHES = option(
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
CSV_FILE = option(
    "--csv-file",
    "-V",
    type=str,
    required=False,
    action="append",
    help="the CSV file(s) from which to read Task data",
    metavar="<data.csv>",
)
PROCESS_CSV_ONLY = option(
    "--process-csv-only",
    "-p",
    action="store_true",
    required=False,
    help=(
        "process CSV variable substitutions only and output the"
        " intermediate JSON Work Requirement specification"
    ),
)
HOLD = option(
    "--hold",
    "-H",
    action="store_true",
    required=False,
    help="set the work requirement status to 'HELD' on submission",
)
PARALLEL_BATCHES = option(
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
EMPTY = option(
    "--empty",
    "-e",
    action="store_true",
    required=False,
    help=(
        "submit a new Work Requirement with no Task Groups or Tasks;"
        " use with '--add-to' to populate it later"
    ),
)
OVERWRITE = option(
    "--overwrite",
    "-O",
    action="store_true",
    required=False,
    help=(
        "overwrite a file if it already exists at the"
        " remote destination; by default existing files are skipped"
    ),
)
ADD_TO = option(
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
# Note: removes the need for the '-r' option
WORK_REQUIREMENT_FILE_POSITIONAL = option(
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


def check_submit_combinations(args: Namespace, parser: ArgumentParser) -> None:
    """
    yd-submit's options that cannot apply together, refused rather than
    ignored: '--json-raw' is a complete Platform document, so the options
    that build or extend a specification do not apply to it; '--add-to'
    adds to a Work Requirement that already has its own state and Task
    Groups; and '--exit-on-failure' needs something to wait on.
    """
    if args.json_raw is not None:
        for dest, flag in (
            ("work_requirement", "--work-requirement"),
            ("work_requirement_file_positional", "a Work Requirement file"),
            ("add_to", "--add-to"),
            ("csv_file", "--csv-file"),
            ("process_csv_only", "--process-csv-only"),
            ("task_count", "--task-count"),
            ("task_group_count", "--task-group-count"),
            ("empty", "--empty"),
            ("validate", "--validate"),
        ):
            if getattr(args, dest, None) not in (None, False):
                parser.error(f"--json-raw cannot be used with {flag}")
    if args.add_to is not None:
        for dest, flag in (("hold", "--hold"), ("empty", "--empty")):
            if getattr(args, dest, False):
                parser.error(f"--add-to cannot be used with {flag}")
    if args.exit_on_failure and not (args.follow or args.progress):
        parser.error("--exit-on-failure needs --follow or --progress")


COMMANDS["yd-submit"] = Command(
    name="yd-submit",
    purpose="submitting a Work Requirement",
    summary="Submit a Work Requirement",
    kind=CommandKind.API,
    options=(
        VARIABLE,
        NAMESPACE,
        TAG,
        WORK_REQUIREMENT,
        JSON_RAW,
        FOLLOW,
        EXIT_ON_FAILURE,
        TASK_TYPE,
        TASK_COUNT,
        TASK_GROUP_COUNT,
        TASK_BATCH_SIZE,
        PAUSE_BETWEEN_BATCHES,
        CSV_FILE,
        PROCESS_CSV_ONLY,
        HOLD,
        PARALLEL_BATCHES,
        EMPTY,
        OVERWRITE,
        ADD_TO,
        DRY_RUN_ACTION,
        JSONNET_DRY_RUN,
        VALIDATE,
        ENTITY_JSON,
        CONTENT_PATH,
        WORK_REQUIREMENT_FILE_POSITIONAL,
        UPGRADE_RCLONE,
        WHICH_RCLONE,
        PROGRESS.variant(
            help=(
                "display a live progress bar showing task completion; "
                "implies following the Work Requirement to completion"
            )
        ),
    ),
    requires_namespace_and_tag=True,
    validators=(check_json_excludes_streaming, check_submit_combinations),
    tool=ToolKind.ACTING,
    tool_description=(
        "Submit a Work Requirement from a specification (a file path, or the"
        " specification itself as an object). Returns {id, name, namespace,"
        " type} of the created Work Requirement; with dry_run, the processed"
        " specification instead. Follow it afterwards with yd_follow, or"
        " poll with yd_list and yd_show, then fetch its outputs with"
        " yd_download; yd_schema work-requirement gives the schema to"
        " compose against."
    ),
)

# --- yd-terminate --------------------------------------------------------

COMMANDS["yd-terminate"] = Command(
    name="yd-terminate",
    purpose="terminating Compute Requirements, Instances or Nodes",
    summary="Terminate Compute Requirements, Instances or Nodes",
    kind=CommandKind.API,
    options=(
        SORT,
        REVERSE,
        VARIABLE,
        NAMESPACE,
        TAG,
        DRY_RUN,
        DRY_RUN_JSON,
        INTERACTIVE,
        YES,
        COMPUTE_REQS_INSTANCES_OR_NODES,
        FOLLOW_COMPUTE_REQUIREMENT_EVENTS,
    ),
    validators=(check_glob_and_literal_names,),
    requires_namespace_and_tag=True,
    tool=ToolKind.DESTRUCTIVE,
)

# --- yd-upload -----------------------------------------------------------

LOCAL_PATHS = option(
    "local_paths",
    metavar="<local-path>",
    type=str,
    nargs="+",
    help="local file(s) or directory(ies) to upload",
)

COMMANDS["yd-upload"] = Command(
    name="yd-upload",
    purpose="uploading files to a remote data client",
    summary="Upload files to a remote data client",
    kind=CommandKind.DATA_CLIENT,
    options=(
        VARIABLE,
        NAMESPACE,
        TAG,
        *DATA_CLIENT_OPTIONS,
        LOCAL_PATHS,
        DESTINATION,
        RECURSIVE,
        FLATTEN,
        SYNC,
        TRANSFERS_JSON,
    ),
    requires_namespace_and_tag=True,
    tool=ToolKind.ACTING,
)

# --- yd-variables --------------------------------------------------------

VARIABLE_NAMES = option(
    "variable_names",
    nargs="*",
    default=[],
    type=str,
    metavar="<var>",
    help=(
        "the variable substitution(s) whose processed values are to be"
        " reported; all variables are reported if none is supplied"
    ),
)

COMMANDS["yd-variables"] = Command(
    name="yd-variables",
    purpose="reporting the processed values of variable substitutions",
    summary="Report the processed values of variable substitutions",
    kind=CommandKind.API,
    options=(
        VARIABLE,
        NAMESPACE,
        TAG,
        VARIABLE_NAMES,
        SHOW_SECRETS.variant(
            help=(
                "include the values of the 'key' and 'secret' variables, of"
                " variables whose names match"
                f" '{SECRET_VARIABLE_NAME_PATTERN.pattern}'"
                " (case-insensitive), and the parameters of any value that is an inline"
                " rclone connection string, when reporting all variables; they are always reported"
                " when named explicitly. Any other variable is reported in full,"
                " even one holding a credential"
            )
        ),
    ),
    requires_namespace_and_tag=True,
    tool=ToolKind.READ_ONLY,
)

# --- Standalone commands -------------------------------------------------
# Each keeps a parser of its own (or none); only their purpose and summary
# are held here.

COMMANDS["yd-format-json"] = Command(
    name="yd-format-json",
    purpose="formatting JSON files using a compact encoder",
    summary="Format JSON files using a compact encoder",
    kind=CommandKind.STANDALONE,
    tool=ToolKind.NONE,
)
COMMANDS["yd-help"] = Command(
    name="yd-help",
    purpose="listing available yd-* commands and their purposes",
    summary="List available yd-* commands and their purposes",
    kind=CommandKind.STANDALONE,
    tool=ToolKind.NONE,
)
COMMANDS["yd-jsonnet2json"] = Command(
    name="yd-jsonnet2json",
    purpose="converting a Jsonnet file to JSON",
    summary="Convert a Jsonnet file to JSON",
    kind=CommandKind.STANDALONE,
    tool=ToolKind.NONE,
)
COMMANDS["yd-version"] = Command(
    name="yd-version",
    purpose="reporting version information",
    summary="Report version information",
    kind=CommandKind.STANDALONE,
    tool=ToolKind.READ_ONLY,
)
