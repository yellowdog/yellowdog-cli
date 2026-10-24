"""
The registry of yd-* commands and their options.

Every command's options are defined here once, as data: argparse is built
from it (build_parser()), yd-help lists from it, and the Command List
(docs/commands.md) is checked against it
(tests/test_docs_command_list.py). It imports nothing from args.py; args.py
imports it.
"""

from __future__ import annotations

import math
import os
import re
from argparse import (
    SUPPRESS,
    Action,
    ArgumentParser,
    ArgumentTypeError,
    Namespace,
    _ArgumentGroup,
)
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from functools import cache
from importlib.metadata import entry_points
from importlib.util import find_spec
from types import MappingProxyType
from typing import Any

from yellowdog_cli.utils.entity_names import (
    CI_INSTANCE_TYPES,
    CI_PRICES,
    CI_REGIONS,
    CI_SUB_REGIONS,
    CLOUD_INFO_TYPES,
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
    RN_ALLOWANCE,
    RN_APPLICATION,
    RN_CONFIGURED_POOL,
    RN_CREDENTIAL,
    RN_EXTERNAL_USER,
    RN_GROUP,
    RN_IMAGE_FAMILY,
    RN_INTERNAL_USER,
    RN_KEYRING,
    RN_NAMESPACE,
    RN_NAMESPACE_POLICY,
    RN_NUMERIC_ATTRIBUTE_DEFINITION,
    RN_REQUIREMENT_TEMPLATE,
    RN_SOURCE_TEMPLATE,
    RN_STRING_ATTRIBUTE_DEFINITION,
)
from yellowdog_cli.utils.glob_utils import contains_glob_chars
from yellowdog_cli.utils.limits import (
    DEFAULT_LIST_LIMIT,
    DEFAULT_PARALLEL_TASK_BATCH_UPLOAD_THREADS,
    DOCTOR_DEFAULT_TIMEOUT,
)
from yellowdog_cli.utils.property_names import PROP_RESOURCE
from yellowdog_cli.utils.settings import DEFAULT_URL, SCHEMA_FAMILIES
from yellowdog_cli.utils.variable_syntax import SECRET_VARIABLE_NAME_PATTERN

Validator = Callable[[Namespace, ArgumentParser], None]

DESCRIPTION_PREFIX = "YellowDog command-line utility for "


class Completes(Enum):
    """
    What a value-taking option's value completes to in the shell
    (utils/completion.py), beyond the choices and types the registry
    already states. tests/test_completion.py holds it to the metavar.
    """

    NONE = auto()
    FILE = auto()  # a local file (or a file or directory)
    DIR = auto()  # a local directory


@dataclass(frozen=True, eq=False)
class Option:
    """
    One argparse argument: its flags (or a positional's name) and the
    keyword arguments handed to add_argument() verbatim. Identity, for
    'is this the same option on another command', is the first long flag.
    The keyword arguments are a read-only copy: options are shared module
    constants, so a change to one would reach every command taking it;
    variant() makes a changed one.
    """

    flags: tuple[str, ...]
    kwargs: Mapping[str, Any]
    # A positional argparse takes as optional only so that --which-rclone
    # and --upgrade-rclone can run without it: required for every MCP tool,
    # which offers neither, and by the command's own check otherwise
    tool_required: bool = False
    # What its value completes to in the shell
    completes: Completes = Completes.NONE

    def __post_init__(self) -> None:
        object.__setattr__(self, "kwargs", MappingProxyType(dict(self.kwargs)))

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

    def variant(
        self, *, completes: Completes | None = None, **overrides: Any
    ) -> Option:
        """
        The same option with some keyword arguments replaced, and what its
        value completes to, if given.
        """
        return replace(
            self,
            kwargs={**self.kwargs, **overrides},
            completes=self.completes if completes is None else completes,
        )

    def register(self, target: ArgumentParser | _ArgumentGroup) -> Action:
        return target.add_argument(*self.flags, **self.kwargs)


def option(*flags: str, completes: Completes = Completes.NONE, **kwargs: Any) -> Option:
    return Option(flags, kwargs, completes=completes)


@dataclass(frozen=True, eq=False)
class Exclusive:
    """
    A mutually exclusive group.
    """

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
    # False for a command on main_wrapper that never uses the Platform
    # (yd-variables): its configuration is loaded without requiring the
    # application key and secret
    requires_credentials: bool = True
    # The MCP tool kind (see ToolKind), stated by every command
    tool: ToolKind = field(kw_only=True)
    # A hand-written description for a tool whose workflow needs explaining;
    # None means the summary and purpose are used
    tool_description: str | None = None
    # The registry command a noun verb's derived command runs
    # (noun_registry.py); None for a registry command itself
    runs: str | None = None
    # False for a command released after 'yd' (yd-completion, yd-auto-shutdown):
    # it has no 'yd-*' entry point, so nothing to deprecate, and is typed only
    # as its 'yd' word or noun verb
    script: bool = True

    @property
    def internal_name(self) -> str:
        """
        The registry command this one runs: itself, or a noun verb's.
        """
        return self.runs or self.name

    def all_options(self) -> tuple[Option | Exclusive, ...]:
        return COMMON_OPTIONS[self.kind] + self.options

    def flat_options(self) -> tuple[Option, ...]:
        flat: list[Option] = []
        for item in self.all_options():
            flat.extend(item.options if isinstance(item, Exclusive) else (item,))
        return tuple(flat)

    def has(self, option: Option) -> bool:
        return self.option_named(option.name) is not None

    def offers(self, option: Option) -> bool:
        """
        Whether the command takes 'option' from its user: has it, and does
        not hide it (a noun verb's option that does not apply to its object,
        refused if given: noun_registry.py).
        """
        found = self.option_named(option.name)
        return found is not None and found.kwargs.get("help") != SUPPRESS

    def option_named(self, name: str) -> Option | None:
        return next((o for o in self.flat_options() if o.name == name), None)


# Filled in below, once the options are defined.
COMMON_OPTIONS: dict[CommandKind, tuple[Option, ...]] = {
    CommandKind.API: (),
    CommandKind.DATA_CLIENT: (),
    CommandKind.STANDALONE: (),
}
COMMANDS: dict[str, Command] = {}

# The entry points that are not registry commands: they take none of the
# CLI's options, so the registry has nothing to say about them, but a user
# has them all the same (each prints the install hint for its extra when
# that is missing). yd-help lists them, and shell completion registers them.
# tests/test_command_registry.py holds this table to pyproject.toml's entry
# points less the registry, so a new entry point is listed by one or the
# other.
OTHER_COMMANDS: dict[str, str] = {
    "yd-commander": "Launch the Commander desktop GUI (needs the commander extra)",
    "yd-mcp": "Run the MCP server over the yd-* commands (needs the mcp extra)",
}

_ARGV0_SUFFIX = re.compile(r"(-script)?\.(py|exe)$")


@cache
def _console_script_modules() -> dict[str, str]:
    """
    This package's console scripts, each with the module it runs.
    """
    return {
        point.name: point.value.split(":")[0]
        for point in entry_points(group="console_scripts")
        if point.value.startswith("yellowdog_cli.")
    }


def command_module(command_name: str) -> str | None:
    """
    The module a 'yd-*' command runs, for 'python -m': its console script's
    entry point ('yd-commander' runs yellowdog_cli.commander.launcher, which
    no rule on the name gives), else, where the package is not installed,
    the module named for the command if there is one; None for anything else. Commander and
    the MCP server both run commands this way, under their own interpreter.
    """
    module = _console_script_modules().get(command_name)
    if module is not None:
        return module
    if not command_name.startswith("yd-"):
        return None
    candidate = "yellowdog_cli." + command_name.removeprefix("yd-").replace("-", "_")
    return candidate if find_spec(candidate) is not None else None


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
        ET_NAMESPACES,
        ET_WORK_REQUIREMENTS,
        ET_TASK_GROUPS,
        ET_TASKS,
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
# Those the Platform can say are deletable: a namespace never populated
LIST_DELETABLE_TYPES = frozenset({ET_NAMESPACES})
# Those the Platform says are healthy or not
LIST_UNHEALTHY_TYPES = frozenset(
    {ET_WORK_REQUIREMENTS, ET_WORKER_POOLS, ET_COMPUTE_REQUIREMENTS}
)
# Those with a cloud provider of their own
LIST_PROVIDER_TYPES = frozenset({ET_INSTANCES, ET_NODES, ET_COMPUTE_SOURCE_TEMPLATES})
# '--provider''s values: the Platform's CloudProvider names, lower-case and
# hyphenated
LIST_PROVIDERS = ("aws", "azure", "google", "oci", "on-premise")
# Those named by a description rather than a name
LIST_DESCRIPTION_TYPES = frozenset({ET_ALLOWANCES})
# Those that record errors of their own
LIST_WITH_ERRORS_TYPES = frozenset({ET_TASKS})
# Those listed from within one parent, with the kinds of parent '--within'
# takes for each (YDIDType values: ydid_utils.py is imported only to check)
LIST_WITHIN_KINDS: dict[str, tuple[str, ...]] = {
    ET_TASK_GROUPS: ("Work Requirement", "Task Group"),
    ET_TASKS: ("Work Requirement", "Task Group"),
    ET_INSTANCES: ("Compute Requirement",),
    ET_NODES: ("Worker Pool",),
    ET_WORKERS: ("Worker Pool", "Node"),
}
LIST_WITHIN_TYPES = frozenset(LIST_WITHIN_KINDS)
# Those whose listing is limited, since they can number in the tens of
# thousands (Instances, Nodes, Workers) or the millions (Tasks)
LIST_LIMIT_TYPES = frozenset({ET_TASKS, ET_INSTANCES, ET_NODES, ET_WORKERS})
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


def finite_float(value: str) -> float:
    """
    An argparse type for a number such as a priority: any float but NaN and
    the infinities, which Python's float() accepts and no Platform value is.
    """
    try:
        number = float(value)
    except ValueError:
        raise ArgumentTypeError(f"invalid number: '{value}'") from None
    if not math.isfinite(number):
        raise ArgumentTypeError(f"must be a finite number, not {value}")
    return number


def non_negative_float(value: str) -> float:
    """
    An argparse type for a duration in minutes, where 0 means none: a finite
    number, not less than zero.
    """
    number = finite_float(value)
    if number < 0:
        raise ArgumentTypeError(f"must be zero or more, not {value}")
    return number


def parse_sort_keys(value: str, valid: tuple[str, ...]) -> tuple[str, ...]:
    """
    A '--sort' value: one sort key, or several separated by commas, the most
    significant first, each one of 'valid' and none given twice.
    """
    keys = tuple(key.strip() for key in value.split(","))
    for key in keys:
        if not key:
            raise ArgumentTypeError(f"empty sort key in '{value}'")
        if key not in valid:
            raise ArgumentTypeError(
                f"invalid sort key '{key}' (choose from {', '.join(valid)})"
            )
    repeated = sorted({key for key in keys if keys.count(key) > 1})
    if repeated:
        raise ArgumentTypeError(f"sort key given more than once: {', '.join(repeated)}")
    return keys


# The sort keys of the entity listings and interactive selection
# (tables.sorted_objects())
ENTITY_SORT_KEYS: tuple[str, ...] = ("name", "created", "status", "namespace")


def entity_sort_keys(value: str) -> tuple[str, ...]:
    """
    An argparse type for the entity listings' '--sort'.
    """
    return parse_sort_keys(value, ENTITY_SORT_KEYS)


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
    completes=Completes.FILE,
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
# long flag, or a positional's name), compared as Command.has() compares,
# with MCP_EXCLUDED_SPECIFICATION_FILES below (see mcp_excluded()).
# tests/test_mcp_tools.py holds every option of every tool command to being
# either in a schema or excluded, so a new option is placed on purpose.
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
        # yd-version's single-version flags, exclusive with the '--json' the
        # server passes
        "--cli",
        "--sdk",
        "--python",
        "--jsonnet",
        "--rclone",
        "--mcp",
        # A credential in a tool result is a credential in the conversation
        "--show-keyring-passwords",
        "--show-secrets",
        # The specification files, replaced by the tools' 'specification(s)'
        # argument (yellowdog_cli/mcp/tools.py); the flag forms are
        # MCP_EXCLUDED_SPECIFICATION_FILES', their names being other
        # commands' options too
        "work_requirement_file_positional",
        "worker_pool_file_positional",
        "compute_requirement_file_positional",
        "resource_specifications",
        # A resource given on the command line: the tools take the
        # specification itself, which says the same
        "--type",
        "--set",
    }
)


# The specification-file options given as flags, excluded only from the
# commands they are files on: by name alone they also hid yd-resize's
# '--compute-requirement' (a flag) and yd-nodeaction's '--worker-pool' (a
# name), as their names are those options' names too
MCP_EXCLUDED_SPECIFICATION_FILES: dict[str, frozenset[str]] = {
    "yd-submit": frozenset({"--work-requirement"}),
    "yd-provision": frozenset({"--worker-pool"}),
    "yd-instantiate": frozenset({"--worker-pool", "--compute-requirement"}),
}


def mcp_excluded(command: Command, option: Option) -> bool:
    """
    Whether no MCP tool for 'command' exposes 'option': it is in
    MCP_EXCLUDED_OPTIONS, is one of the command's own specification-file
    options, or is hidden (a noun verb's option that does not apply to its
    object, or one its verb fixes: noun_registry.py).
    """
    return (
        option.name in MCP_EXCLUDED_OPTIONS
        or option.name
        in MCP_EXCLUDED_SPECIFICATION_FILES.get(command.internal_name, frozenset())
        or option.kwargs.get("help") == SUPPRESS
    )


# --- Shared options ------------------------------------------------------
# Each is shared by several commands; a command registering the same flag
# with different keyword arguments uses a variant.

SORT = option(
    "--sort",
    type=entity_sort_keys,
    required=False,
    default="name",
    help=(
        "order in which listed and interactively-selected entities "
        "are sorted: 'name' (default), 'created' (creation time, "
        "earliest first), 'status' (status name), or 'namespace'; give "
        "several, separated by commas, to sort by each in turn (e.g. "
        "'status,created'), the name always breaking any tie; combine "
        "with --reverse to invert the whole order"
    ),
    metavar="<name|created|status|namespace>[,...]",
)
REVERSE = option(
    "--reverse",
    action="store_true",
    required=False,
    help="reverse (descending) the whole order --sort gives",
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
# The namespace a target given by name is looked up in (yd-show, yd-follow,
# yd-wait, yd-compare); 'namespace/name' names another
NAME_NAMESPACE = NAMESPACE.variant(
    help=(
        "the namespace a target given by name is looked up in ('namespace/name'"
        " names another); the configured namespace if not given"
    )
)

# Where a noun verb's target check records the YDID type a name among its
# targets stands for (noun_registry.Targets.named), for the registry
# command's own checks and utils/named_targets.py: None for a verb, or a
# command, that takes IDs alone
NAMED_TARGET_TYPE_DEST = "named_target_type"


def named_target_type(args: Namespace) -> Any:
    """
    The YDID type a name among the targets stands for, or None.
    """
    return getattr(args, NAMED_TARGET_TYPE_DEST, None)


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
    completes=Completes.FILE,
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
    help="emit the resources removed or skipped as a JSON array"
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
        " specification; not with --report"
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
    metavar="<work-requirement-name-or-ID>",
    type=str,
    help=(
        "the name(s) or YellowDog ID(s) of the work requirement(s) to be"
        " cancelled; can also supply task IDs; a name may be a glob"
        " pattern (e.g. 'proj-*')"
    ),
)
# Optional to argparse, for '--type' and '--set'; an MCP tool, which takes
# the specification itself, needs one
RESOURCE_SPECIFICATIONS = replace(
    option(
        "resource_specifications",
        nargs="*",
        default=[],
        completes=Completes.FILE,
        metavar="<resource-specification>",
        type=str,
        help=(
            "the resource specifications to process, '-' reading one from"
            " standard input as JSON; for 'yd resource remove', YellowDog IDs"
            " too"
        ),
    ),
    tool_required=True,
)
# The resource types '--type' takes: those yd-create creates, which
# tests/test_resource_inline.py holds to load_resources.RESOURCE_CREATION_ORDER
RESOURCE_TYPE_CHOICES = (
    RN_ALLOWANCE,
    RN_APPLICATION,
    RN_CONFIGURED_POOL,
    RN_CREDENTIAL,
    RN_EXTERNAL_USER,
    RN_GROUP,
    RN_IMAGE_FAMILY,
    RN_INTERNAL_USER,
    RN_KEYRING,
    RN_NAMESPACE,
    RN_NAMESPACE_POLICY,
    RN_NUMERIC_ATTRIBUTE_DEFINITION,
    RN_REQUIREMENT_TEMPLATE,
    RN_SOURCE_TEMPLATE,
    RN_STRING_ATTRIBUTE_DEFINITION,
)


def resolve_resource_type(value: str) -> str:
    """
    A resource type as '--type' takes it, whatever its case.
    """
    for resource_type in RESOURCE_TYPE_CHOICES:
        if resource_type.lower() == value.lower():
            return resource_type
    raise ArgumentTypeError(
        f"invalid resource type: '{value}' (choose from"
        f" {', '.join(RESOURCE_TYPE_CHOICES)})"
    )


RESOURCE_TYPE = option(
    "--type",
    dest="resource_type",
    metavar="<resource-type>",
    type=resolve_resource_type,
    choices=RESOURCE_TYPE_CHOICES,
    required=False,
    help=(
        "the type of a resource specified on the command line with --set,"
        " in place of a specification file, e.g. 'Keyring' (any case)"
    ),
)
RESOURCE_SET = option(
    "--set",
    dest="resource_properties",
    action="append",
    metavar="<property=value>",
    required=False,
    help=(
        "a property of the resource --type specifies; the value is read as"
        " JSON where it can be (a number, a list, an object, true, null),"
        " else as text; can be supplied multiple times, e.g."
        " --type Keyring --set name=team-keys --set description='Team keys'"
    ),
)


def check_resource_inputs(args: Namespace, parser: ArgumentParser) -> None:
    """
    yd-create and yd-remove: something to act on (a specification, '-' for
    standard input, or a resource given with --type and --set), '-' at most
    once, and each --set a 'property=value' naming a property once, the
    resource type given by --type alone.
    """
    specifications = args.resource_specifications or []
    properties = args.resource_properties or []
    if properties and not args.resource_type:
        parser.error("--set needs --type, the type of the resource it specifies")
    if not specifications and not args.resource_type:
        parser.error(
            "give a resource specification, '-' to read one from standard input,"
            " or a resource's --type and --set"
        )
    if specifications.count("-") > 1:
        parser.error("'-' (standard input) can be given once")
    seen: set[str] = set()
    for given in properties:
        name, equals, _ = given.partition("=")
        if not equals or not name.strip():
            parser.error(f"--set '{given}' is not of the form 'property=value'")
        if name == PROP_RESOURCE:
            parser.error("give the resource type with --type, not --set resource=...")
        if name in seen:
            parser.error(f"--set {name} is given twice")
        seen.add(name)


YES_ALLOW_UPDATES = YES.variant(help="allow updates without user confirmation")
MATCH_ALLOWANCES_BY_DESCRIPTION = option(
    "--match-allowances-by-description",
    "-M",
    action="store_true",
    required=False,
    help=(
        "match using the 'description' property when updating "
        "(using yd resource create) or removing allowances"
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
    completes=Completes.DIR,
    metavar="<directory>",
)
FOLLOW_PROVISIONING = FOLLOW.variant(help="follow progress after provisioning")
TARGET = option(
    "--target",
    "-T",
    type=non_negative_int,
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
        "image family IDs in compute source templates, "
        "and template IDs in allowances "
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
        "required when capturing JSON for use with yd resource create and remove "
        "(implies '--details')"
    ),
)
HIDE_USER_DATA = option(
    "--hide-user-data",
    action="store_true",
    required=False,
    help=("show each User Data script as a summary of its size rather than in full"),
)
OUTPUT_FILE = option(
    "--output-file",
    type=str,
    required=False,
    help=(
        "if specified, the detailed JSON resource listing will also be written "
        "to the nominated output file"
    ),
    completes=Completes.FILE,
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


# The file extensions a namespace or tag never has, but a specification or
# configuration file does
_FILE_EXTENSIONS = (".json", ".jsonnet", ".toml", ".yaml", ".yml", ".csv")


def check_namespace_and_tag_are_no_files(
    args: Namespace, parser: ArgumentParser
) -> None:
    """
    Every command with -n or -t: neither names a file. Each takes an optional
    value, so a file named straight after one ('yd-submit -t wr.json') was
    taken as its value, and the command ran without the file.
    """
    for name, flag in (("namespace", "--namespace"), ("tag", "--tag")):
        value = getattr(args, name, None)
        if isinstance(value, str) and value.lower().endswith(_FILE_EXTENSIONS):
            parser.error(
                f"{flag} '{value}' looks like a file name: give {flag} a value,"
                f" or put it after the file (e.g. '{value} {flag} <value>')"
            )


def check_paths_given(args: Namespace, parser: ArgumentParser) -> None:
    """
    The paths a data client command needs, unless it is only asked for
    --which-rclone or --upgrade-rclone: argparse takes them as optional so
    that those two can run alone.
    """
    if args.which_rclone or args.upgrade_rclone:
        return
    for name, metavar in (
        ("local_paths", "<local-path>"),
        ("remote_paths", "<remote-path>"),
    ):
        if getattr(args, name, None) == []:
            parser.error(f"the following arguments are required: {metavar}")


def refuse_parent_segments(
    parser: ArgumentParser, remote_paths: Iterable[str | None]
) -> None:
    """
    Refuse a remote path with a '..' segment: it climbs out of the prefix,
    or the bucket, past the checks that refuse deleting or syncing over the
    remote's root or the bucket itself, and object stores do not resolve it
    as a local disk does. Both readings of the path are checked, a leading
    'remote:' and none, since a relative path may hold a ':' of its own
    ('../run-10:00').
    """
    for remote_path in remote_paths:
        if remote_path is None:
            continue
        if ".." in remote_path.split("/") or (
            ".." in remote_path.split(":", 1)[-1].split("/")
        ):
            parser.error(
                f"'{remote_path}': a remote path cannot contain '..'; name it"
                " from the remote's root with --no-prefix (or --bucket) instead"
            )


def check_transfer_args(args: Namespace, parser: ArgumentParser) -> None:
    """
    yd-upload and yd-download: their paths (see check_paths_given()), the
    remote ones without '..' (see refuse_parent_segments()); and not --sync
    with --flatten, which would transfer without the deletion --sync
    promises.
    """
    check_paths_given(args, parser)
    if hasattr(args, "remote_paths"):  # yd-download: its destination is local
        refuse_parent_segments(parser, args.remote_paths or [])
    else:  # yd-upload: its destination is remote
        refuse_parent_segments(parser, [args.destination])
    if args.sync and args.flatten:
        parser.error("--sync cannot be used with --flatten")


def check_delete_args(args: Namespace, parser: ArgumentParser) -> None:
    """
    yd-delete: a path, unless --recursive asks for the entire default
    prefix (or it is only asked for --which-rclone or --upgrade-rclone);
    none with '..' (see refuse_parent_segments()).
    """
    refuse_parent_segments(parser, args.remote_paths or [])
    if args.remote_paths or args.recursive or args.which_rclone or args.upgrade_rclone:
        return
    parser.error(
        "no remote path given: name one, or use --recursive to delete the entire"
        " default prefix"
    )


def check_ls_args(args: Namespace, parser: ArgumentParser) -> None:
    """
    yd-ls: not --long with --json, whose entries carry sizes and times
    whatever is asked for.
    """
    if args.long and args.json:
        parser.error("--long cannot be used with --json")


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
    pattern, but must not be mixed with literal names/IDs. Either may be
    given with --dry-run.
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


def check_no_glob_targets(args: Namespace, parser: ArgumentParser) -> None:
    """
    yd-compute-restart and yd-compute-deprovision act on Instances alone: a
    glob pattern would select Compute Requirements, which they cannot act on.
    """
    globs = [
        target
        for target in args.compute_reqs_instances_or_nodes or []
        if contains_glob_chars(target)
    ]
    if globs:
        parser.error(
            "glob patterns are not supported, since they select Compute"
            " Requirements: supply node IDs, or instances in"
            f" 'cr_id.instance_id' format ({', '.join(globs)})"
        )


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


def check_hide_user_data_requires_dry_run(
    args: Namespace, parser: ArgumentParser
) -> None:
    """
    On the creators, refuse '--hide-user-data' outside a dry run: the real
    run prints no User Data, so the option would do nothing.
    """
    if getattr(args, "hide_user_data", False) and not getattr(args, "dry_run", False):
        parser.error("--hide-user-data applies only to --dry-run")


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
    metavar="<target>",
    type=str,
    help=(
        "items to target: executing task YDID(s) to abort directly; Work"
        " Requirement name(s), 'namespace/wr-name' or YDID(s) to abort all"
        " executing tasks within; Task Group YDID(s), 'wr-name/tg-name' or"
        " 'namespace/wr-name/tg-name' to abort executing tasks in a specific"
        " group. Without arguments, the executing tasks of the work"
        " requirements matching the namespace and tag, selected interactively"
        " unless --yes is given."
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
    load beyond the constants modules and glob_utils.py.
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
    metavar="<operation>",
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
    completes=Completes.FILE,
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

# The providers Cloud Wizard supports, by each spelling it accepts
CLOUD_PROVIDERS: dict[str, str] = {
    "aws": "AWS",
    "amazon": "AWS",
    "gcp": "GCP",
    "gce": "GCP",
    "google": "GCP",
    "azure": "Azure",
    "microsoft": "Azure",
}


def cloud_provider_of(name: str) -> str | None:
    """
    The provider a '--cloud-provider' spelling names, or None.
    """
    return CLOUD_PROVIDERS.get(name.strip().lower())


def check_cloudwizard_args(args: Namespace, parser: ArgumentParser) -> None:
    """
    yd-cloudwizard's provider, and what each operation needs from it, refused
    as the command line is parsed rather than reported and exited 0.
    """
    provider = cloud_provider_of(args.cloud_provider)
    if provider is None:
        parser.error(
            f"unknown or unsupported cloud provider '{args.cloud_provider}'; one of"
            f" {', '.join(CLOUD_PROVIDERS)}"
        )
    if provider == "GCP" and args.credentials_file is None:
        parser.error("--credentials-file is required for GCP")
    if args.operation in ("add-ssh", "remove-ssh"):
        if provider == "GCP":
            parser.error(f"'{args.operation}' is not supported for GCP")
        if provider == "Azure" and args.region_name is None:
            parser.error(f"'{args.operation}' needs --region-name for Azure")


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
    validators=(check_cloudwizard_args,),
    tool=ToolKind.NONE,
)

# --- yd-compare ----------------------------------------------------------

WR_OR_TG_ID = option(
    "wr_or_tg_id",
    metavar="<work-requirement-or-task-group-name-or-ID>",
    type=str,
    help=(
        "the name ('wr', or 'wr/tg' for a task group) or YellowDog ID of the"
        " work requirement or task group to be compared"
    ),
)
WORKER_POOL_IDS = option(
    "worker_pool_ids",
    metavar="<provisioned-worker-pool-name-or-ID>",
    type=str,
    nargs="+",
    help="the name(s) or YellowDog ID(s) of the provisioned worker pool(s) to compare",
)
RUNNING_NODES_ONLY = option(
    "--running-nodes-only",
    action="store_true",
    required=False,
    help="only compare against nodes in the RUNNING state",
)


def check_compare_ids(args: Namespace, parser: ArgumentParser) -> None:
    """
    yd-compare's positional targets, by type, before anything is fetched: a
    Work Requirement or Task Group ID or name ('wr', 'wr/tg'), then Worker
    Pool IDs or names. The YDID parser is
    imported here, so this module still imports nothing at load beyond
    the constants modules and glob_utils.py.
    """
    from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

    def kind(target: str) -> YDIDType | str | None:
        # Anything not shaped as a YellowDog ID is a name, looked up as it
        # runs; one shaped as an ID that does not parse is neither
        ydid_type = get_ydid_type(target)
        return (
            "malformed"
            if ydid_type is None and target.startswith("ydid:")
            else ydid_type
        )

    if kind(args.wr_or_tg_id) not in (
        None,
        YDIDType.WORK_REQUIREMENT,
        YDIDType.TASK_GROUP,
    ):
        parser.error(
            "not a YellowDog Work Requirement or Task Group ID, or a name:"
            f" '{args.wr_or_tg_id}'"
        )
    for worker_pool_id in args.worker_pool_ids:
        if kind(worker_pool_id) not in (None, YDIDType.WORKER_POOL):
            parser.error(
                f"not a YellowDog Worker Pool ID, or a name: '{worker_pool_id}'"
            )


COMMANDS["yd-compare"] = Command(
    name="yd-compare",
    purpose=(
        "comparing whether a work requirement or task group is matched by "
        "workers in the specified provisioned worker pools"
    ),
    summary="Compare a Work Requirement or Task Group against Worker Pool(s)",
    kind=CommandKind.API,
    options=(
        NAME_NAMESPACE,
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

# --- '--wait' for yd-resize and yd-compute-reprovision ------------------

WAIT_FOR_CAPACITY = option(
    "--wait",
    "-w",
    action="store_true",
    required=False,
    help=(
        "wait until each compute requirement acted on has its target number of"
        " instances running, and none starting or terminating"
    ),
)
WAIT_TIMEOUT = TIMEOUT.variant(
    default=None,
    help=(
        "with --wait, stop waiting after this many seconds and fail (default: no limit)"
    ),
)


def check_wait_options(args: Namespace, parser: ArgumentParser) -> None:
    """
    '--wait' waits for Compute Requirements (on yd-resize, only when the
    target is one), and not alongside '--follow', which streams events until
    the end itself; '--timeout' limits '--wait' alone.
    """
    wait = getattr(args, "wait", False)
    if wait and getattr(args, "follow", False):
        parser.error("--wait cannot be combined with --follow")
    if (
        wait
        and hasattr(args, "compute_requirement")
        and not resize_targets_compute_requirement(args)
    ):
        parser.error(
            "--wait applies to Compute Requirements only: use it with"
            " --compute-requirement/-C, or a Compute Requirement ID"
        )
    if getattr(args, "timeout", None) is not None and not wait:
        parser.error("--timeout applies only with --wait")


# --- yd-compute-restart / -deprovision / -reprovision / -start / -stop -----


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
    validators=(check_no_glob_targets,),
    tool=ToolKind.DESTRUCTIVE,
)
COMMANDS["yd-compute-deprovision"] = Command(
    name="yd-compute-deprovision",
    purpose=(
        "deprovisioning Instances: terminating them and reducing their"
        " Compute Requirements' target counts to match"
    ),
    summary="Deprovision Instances, reducing their Compute Requirements' target counts",
    kind=CommandKind.API,
    # Instance-level only, as for yd-compute-restart
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
    validators=(check_no_glob_targets,),
    tool=ToolKind.DESTRUCTIVE,
)
COMMANDS["yd-compute-reprovision"] = Command(
    name="yd-compute-reprovision",
    purpose=(
        "reprovisioning Compute Requirements: provisioning Instances until"
        " their target counts are met"
    ),
    summary="Reprovision Compute Requirements, restoring their target instance counts",
    kind=CommandKind.API,
    # Compute Requirement-level only: no Instance or Node IDs
    options=(
        *_compute_action_options(
            COMPUTE_REQS_INSTANCES_OR_NODES.variant(
                help=(
                    "the name(s) or YellowDog ID(s) of the compute requirement(s);"
                    " a name may be a glob pattern (e.g. 'cr-*')"
                ),
            )
        ),
        WAIT_FOR_CAPACITY,
        WAIT_TIMEOUT,
    ),
    validators=(check_glob_and_literal_names, check_wait_options),
    requires_namespace_and_tag=True,
    tool=ToolKind.DESTRUCTIVE,
)
AUTO_SHUTDOWN_MINUTES = option(
    "--minutes",
    dest="auto_shutdown_minutes",
    required=True,
    type=non_negative_float,
    metavar="<minutes>",
    help=(
        "terminate the compute requirement(s) this many minutes from now,"
        " replacing any auto shutdown already set; 0 never terminates them"
        " automatically"
    ),
)
COMMANDS["yd-auto-shutdown"] = Command(
    name="yd-auto-shutdown",
    purpose=(
        "setting when Compute Requirements are automatically terminated, or"
        " that they never are"
    ),
    summary="Set when Compute Requirements are automatically terminated",
    kind=CommandKind.API,
    # Compute Requirement-level only, and nothing to follow: the requirement
    # runs on until the time set
    options=(
        SORT,
        REVERSE,
        VARIABLE,
        NAMESPACE,
        TAG,
        INTERACTIVE,
        YES,
        ACTIONS_JSON,
        COMPUTE_REQS_INSTANCES_OR_NODES.variant(
            help=(
                "the name(s) or YellowDog ID(s) of the compute requirement(s);"
                " a name may be a glob pattern (e.g. 'cr-*')"
            ),
        ),
        AUTO_SHUTDOWN_MINUTES,
    ),
    validators=(check_glob_and_literal_names,),
    requires_namespace_and_tag=True,
    tool=ToolKind.DESTRUCTIVE,
    script=False,
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

SRC_PATH = Option(
    ("src_path",),
    {
        "metavar": "<src-path>",
        "type": str,
        "nargs": "?",
        "help": "source path relative to the configured source remote/bucket/prefix",
    },
    tool_required=True,
)
DST_PATH = Option(
    ("dst_path",),
    {
        "metavar": "<dst-path>",
        "type": str,
        "nargs": "?",
        "help": (
            "destination path relative to the configured destination"
            " remote/bucket/prefix"
        ),
    },
    tool_required=True,
)


def check_copy_args(args: Namespace, parser: ArgumentParser) -> None:
    """
    yd-copy: both paths, unless it is only asked for --which-rclone or
    --upgrade-rclone, which is why argparse takes them as optional; neither
    with '..' (see refuse_parent_segments()).
    """
    refuse_parent_segments(parser, [args.src_path, args.dst_path])
    if args.which_rclone or args.upgrade_rclone:
        return
    missing = [
        metavar
        for name, metavar in (("src_path", "<src-path>"), ("dst_path", "<dst-path>"))
        if getattr(args, name) is None
    ]
    if missing:
        parser.error(f"the following arguments are required: {', '.join(missing)}")


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
        RECURSIVE.variant(help="copy a directory, recursively (--sync implies it)"),
        SYNC.variant(
            help=(
                "make the destination a mirror of the source, "
                "deleting destination files not present in the source"
            )
        ),
        TRANSFERS_JSON.variant(help="emit the files copied as a JSON array"),
    ),
    validators=(check_copy_args,),
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
        "process the resources in the order given, rather than in dependency"
        " order (e.g., source templates before requirement templates when"
        " creating, after them when removing)"
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
        HIDE_USER_DATA,
        JSONNET_DRY_RUN,
        VALIDATE,
        CREATE_JSON,
        RESOURCE_SPECIFICATIONS,
        RESOURCE_TYPE,
        RESOURCE_SET,
        YES_ALLOW_UPDATES,
        MATCH_ALLOWANCES_BY_DESCRIPTION,
        SHOW_KEYRING_PASSWORDS,
        REGENERATE_APP_KEYS,
        NO_RESEQUENCE,
    ),
    requires_namespace_and_tag=True,
    validators=(check_resource_inputs, check_hide_user_data_requires_dry_run),
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
    help=(
        "every argument is a YellowDog ID (YDID); optional, since an ID is"
        " recognised as one"
    ),
)


def _check_removal_by_name(args: Namespace, parser: ArgumentParser) -> None:
    """
    yd-remove --type with arguments: each the name or the ID of a resource
    of that type, which can be removed that way, and not with --set.
    """
    from yellowdog_cli.utils.resource_targets import ID_TYPES, name_problem
    from yellowdog_cli.utils.ydid_utils import get_ydid_type

    resource_type = args.resource_type
    if not (resource_type and args.resource_specifications):
        return
    if args.resource_properties:
        parser.error(
            "give the names or IDs of the resources to remove, or one with --set,"
            " not both"
        )
    for target in args.resource_specifications:
        if target == "-":
            parser.error(
                f"'-' (standard input) is not a name: with --type the arguments are"
                f" the names or IDs of the {resource_type} resources to remove"
            )
        ydid_type = get_ydid_type(target)
        if ydid_type is not None:
            if ID_TYPES.get(resource_type) != ydid_type:
                parser.error(f"'{target}' is not the ID of a {resource_type}")
        elif (problem := name_problem(resource_type, target)) is not None:
            parser.error(problem)


def check_remove_ids(args: Namespace, parser: ArgumentParser) -> None:
    """
    yd-remove: each argument that is a YellowDog ID the ID of a resource it
    can remove, checked before anything is removed. With --ids, every
    argument must be one, and none of the options that act only on
    specification files is taken; with --type, the arguments are names or
    IDs of that type (_check_removal_by_name()).
    """
    from yellowdog_cli.utils.ydid_utils import REMOVABLE_YDID_TYPES, get_ydid_type

    if not args.ids:
        if args.resource_type:
            _check_removal_by_name(args, parser)
            return
        arguments = args.resource_specifications or []
        for argument in arguments:
            ydid_type = get_ydid_type(argument)
            if ydid_type is not None and ydid_type not in REMOVABLE_YDID_TYPES:
                parser.error(
                    f"not the ID of a resource that can be removed: '{argument}'"
                )
        # A dry run of IDs alone would remove them: the loader's dry run,
        # which ends the command, is never reached without a file
        if (
            args.jsonnet_dry_run
            and arguments
            and all(get_ydid_type(argument) is not None for argument in arguments)
        ):
            parser.error(
                "--jsonnet-dry-run applies to specification files, and every"
                " argument is a YellowDog ID"
            )
        return
    if args.resource_type or args.resource_properties:
        parser.error("--type and --set specify a resource, not --ids")
    for option, given in (
        ("--match-allowances-by-description", args.match_allowances_by_description),
        ("--jsonnet-dry-run", args.jsonnet_dry_run),
    ):
        if given:
            parser.error(f"{option} applies to specification files, not to --ids")
    for resource_id in args.resource_specifications:
        if get_ydid_type(resource_id) not in REMOVABLE_YDID_TYPES:
            parser.error(
                f"not the ID of a resource that can be removed: '{resource_id}'"
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
        RESOURCE_TYPE,
        RESOURCE_SET,
        YES.variant(help="remove without user confirmation"),
        MATCH_ALLOWANCES_BY_DESCRIPTION,
        IDS,
        NO_RESEQUENCE,
    ),
    validators=(check_resource_inputs, check_remove_ids),
    requires_namespace_and_tag=True,
    tool=ToolKind.DESTRUCTIVE,
)

# --- yd-delete ----------------------------------------------------------

COMMANDS["yd-delete"] = Command(
    name="yd-delete",
    purpose="deleting remote data client files and directories",
    summary="Delete remote data client files and directories",
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
    validators=(check_delete_args,),
    requires_namespace_and_tag=True,
    tool=ToolKind.DESTRUCTIVE,
)

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
    completes=Completes.DIR,
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
        Option(
            REMOTE_PATHS.flags,
            {**REMOTE_PATHS.kwargs, "nargs": "*"},
            tool_required=True,
        ),
        # '--destination' names the local path corresponding to one remote
        # item; '--into' names a container directory that several items keep
        # their own names inside. Honouring both is meaningless, so let
        # argparse refuse the combination rather than picking one.
        Exclusive(
            (
                DESTINATION.variant(
                    default=None,
                    help="local directory or file path to write to (default: mirrors remote name)",
                    completes=Completes.FILE,
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
    validators=(check_transfer_args,),
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


def check_follow_ids(args: Namespace, parser: ArgumentParser) -> None:
    """
    yd-follow's IDs: each a Work Requirement's, Worker Pool's or Compute
    Requirement's, the entities with event streams, checked before anything
    is followed.
    """
    from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

    followable = (
        YDIDType.WORK_REQUIREMENT,
        YDIDType.WORKER_POOL,
        YDIDType.COMPUTE_REQUIREMENT,
    )
    named = named_target_type(args)
    for ydid in args.yellowdog_ids:
        ydid_type = get_ydid_type(ydid)
        if ydid_type is None and named is not None:
            continue  # A name of the noun verb's type, looked up as it runs
        if ydid_type not in followable:
            parser.error(
                f"not a Work Requirement, Worker Pool or Compute Requirement ID:"
                f" '{ydid}'"
            )


COMMANDS["yd-follow"] = Command(
    name="yd-follow",
    purpose="following event streams",
    summary="Follow event streams",
    kind=CommandKind.API,
    options=(
        VARIABLE,
        NAME_NAMESPACE,
        YELLOWDOG_IDS.variant(nargs="+"),
        PROGRESS,
        AUTO_FOLLOW_COMPUTE_REQUIREMENTS,
        ACTIONS_JSON.variant(
            help=(
                "print each event as a JSON document as it arrives"
                " (not with --progress)"
            )
        ),
    ),
    validators=(check_follow_json_excludes_progress, check_follow_ids),
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
SHOW_SOURCE_REPORT = option(
    "--show-source-report",
    action="store_true",
    required=False,
    help=(
        "also display the report of how a compute requirement's sources were"
        " chosen (for a compute requirement, or a provisioned worker pool's,"
        " provisioned from a dynamic template)"
    ),
)
SHOW_MEMBERS = option(
    "--show-members",
    action="store_true",
    required=False,
    help=(
        "also display a group's users and applications, or the groups that hold a role"
    ),
)
SHOW_EXHAUSTION = option(
    "--show-exhaustion",
    action="store_true",
    required=False,
    help=(
        "also display the allowances exhausted for a compute requirement (or"
        " a provisioned worker pool's)"
    ),
)


def check_show_ids(args: Namespace, parser: ArgumentParser) -> None:
    """
    yd-show's '--substitute-ids', refused when none of the IDs is of a kind
    whose details it substitutes names into (Compute Source and Requirement
    Templates, Allowances), rather than ignored; '--show-source-report' and
    '--show-exhaustion' likewise without a Compute Requirement or Worker
    Pool ID, and '--show-members' without a Group or Role ID. '--show-token' is left alone: whether a Worker Pool is a
    Configured one is known only once it has been fetched, as whether it is
    a Provisioned one is for the other two.
    """
    from yellowdog_cli.utils.resource_targets import (
        ID_TYPES,
        SHOWN_BY_NAME,
        SHOWN_WITHOUT_ID,
        name_problem,
    )
    from yellowdog_cli.utils.ydid_utils import (
        YDIDType,
        get_ydid_type,
        split_instance_specification,
    )

    # The kind of each argument: a YDID's type, or with --type the kind of
    # ID the name stands for (None for a type that has no ID)
    resource_type = getattr(args, "resource_type", None)
    id_kind = (
        SHOWN_BY_NAME.get(resource_type) or ID_TYPES.get(resource_type)
        if resource_type is not None
        else None
    )
    article = "an" if (resource_type or "x")[0] in "AEIOU" else "a"
    kinds = []
    named = named_target_type(args)
    for target in args.yellowdog_ids:
        ydid_type = get_ydid_type(target)
        if resource_type is None and ydid_type is None and named is not None:
            # A name of the noun verb's type, looked up as it runs
            ydid_type = named
        elif resource_type is None:
            # A word that is plainly a name; a malformed ID is reported as
            # the run reaches it
            if (
                not target.startswith("ydid:")
                and split_instance_specification(target) is None
            ):
                parser.error(
                    f"'{target}' is not a YellowDog ID; give --type to show a"
                    " resource by name"
                )
        elif ydid_type is not None:
            if id_kind is None:
                parser.error(f"{article} {resource_type} has no ID; give its name")
            if ydid_type != id_kind:
                parser.error(f"'{target}' is not the ID of a {resource_type}")
        elif resource_type in SHOWN_WITHOUT_ID:
            if (problem := name_problem(resource_type, target)) is not None:
                parser.error(problem)
        elif resource_type in SHOWN_BY_NAME:
            ydid_type = SHOWN_BY_NAME[resource_type]
        else:
            parser.error(f"{article} {resource_type} has no name; give its ID")
        kinds.append(ydid_type)

    with_compute_requirement = (YDIDType.COMPUTE_REQUIREMENT, YDIDType.WORKER_POOL)
    for flag, given in (
        ("--show-source-report", args.show_source_report),
        ("--show-exhaustion", args.show_exhaustion),
    ):
        if given and not any(kind in with_compute_requirement for kind in kinds):
            parser.error(
                f"{flag} applies only to Compute Requirement and Worker Pool"
                " IDs, and none was given"
            )
    if args.show_members and not any(
        kind in (YDIDType.GROUP, YDIDType.ROLE) for kind in kinds
    ):
        parser.error(
            "--show-members applies only to Group and Role IDs, and none was given"
        )

    substitutable = (
        YDIDType.COMPUTE_SOURCE_TEMPLATE,
        YDIDType.COMPUTE_REQUIREMENT_TEMPLATE,
        YDIDType.ALLOWANCE,
    )
    if args.substitute_ids and not any(kind in substitutable for kind in kinds):
        parser.error(
            "--substitute-ids applies only to Compute Source Template, Compute"
            " Requirement Template and Allowance IDs, and none was given"
        )


COMMANDS["yd-show"] = Command(
    name="yd-show",
    purpose="showing the JSON details of entities referenced by their YDIDs",
    summary="Show the JSON details of entities referenced by their YDIDs",
    kind=CommandKind.API,
    # A YDID names its entity in whatever namespace it is in; the namespace
    # is where a name is looked up (a noun verb's, or with --type)
    options=(
        VARIABLE,
        NAME_NAMESPACE,
        YELLOWDOG_IDS.variant(
            nargs="+",
            help=(
                "the YellowDog ID(s) of the item(s) to show"
                "; Instances have no ID of their own and are specified "
                "in 'cr_id.instance_id' format; with --type, the names or IDs"
                " of resources of that type"
            ),
        ),
        RESOURCE_TYPE.variant(
            help=(
                "the type of the resources to show by name, e.g. 'Keyring'"
                " (any case): 'namespace/name' for a namespaced type, the"
                " configured namespace without one"
            )
        ),
        SHOW_TOKEN,
        SHOW_SOURCE_REPORT,
        SHOW_EXHAUSTION,
        SHOW_MEMBERS,
        SUBSTITUTE_IDS,
        STRIP_IDS,
        HIDE_USER_DATA,
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
        NAME_NAMESPACE,
        YELLOWDOG_IDS.variant(
            nargs="+", help="the YellowDog ID(s) of the item(s) to wait for"
        ),
        TIMEOUT.variant(
            default=None,
            help=(
                "stop waiting after this many seconds, and fail if anything has"
                " not finished (default: no limit)"
            ),
        ),
        ACTIONS_JSON.variant(help="emit each item's final status as a JSON array"),
    ),
    validators=(check_follow_ids,),
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
    completes=Completes.FILE,
    metavar="<compute_requirement.json>",
)
REPORT = option(
    "--report",
    "-r",
    action="store_true",
    required=False,
    help=(
        "report on a test run of the compute requirement template, provisioning nothing"
    ),
)
COMPUTE_REQUIREMENT_FILE_POSITIONAL = option(
    "compute_requirement_file_positional",
    completes=Completes.FILE,
    metavar="<compute-requirement-specification-file>",
    type=str,
    nargs="?",
    help=(
        "the JSON or Jsonnet specification of the compute requirement"
        " to provision; alternative to using the"
        " '--compute-requirement/-C' option"
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
        HIDE_USER_DATA,
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
    validators=(
        check_json_excludes_streaming,
        check_hide_user_data_requires_dry_run,
    ),
    tool=ToolKind.ACTING,
)

WORKER_POOL_FILE_POSITIONAL = option(
    "worker_pool_file_positional",
    completes=Completes.FILE,
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
        HIDE_USER_DATA,
        REPORT,
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
    validators=(
        check_json_excludes_streaming,
        check_hide_user_data_requires_dry_run,
    ),
    tool=ToolKind.ACTING,
    tool_description=(
        "Provision a Worker Pool from a specification (a file path, or the"
        " specification itself). Returns {id, name, namespace, type}. With"
        " dry_run, the processed specification. Shut it"
        " down afterwards with yd_workerpool_shutdown; yd_schema worker-pool gives the"
        " schema to compose against."
    ),
)

# --- yd-list -------------------------------------------------------------

LIST_NAMESPACE = NAMESPACE.variant(help="the namespace to use when listing entities")

# Tag attribute is defaulted to "" when using 'yd-list'
LIST_TAG = TAG.variant(
    help=(
        "the tag to list by: Work Requirements, Worker Pools and Compute"
        " Requirements are listed with the configured tag, as the commands"
        " acting on them select them, unless this is given ('' for the whole"
        " namespace); templates and Image Families only by a tag given here"
    ),
)
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
    help=(
        "list only active entities: work requirements, task groups, tasks,"
        " worker pools, nodes, workers, compute requirements and instances"
    ),
)
NAME = option(
    "--name",
    dest="name_glob",
    metavar="<glob>",
    required=False,
    help=(
        "list only entities whose name matches the given glob "
        "pattern (e.g. 'proj-*'); applies to namespaces, work requirements, "
        "task groups, tasks, "
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
        "(case-insensitive); several may be given separated by commas "
        "('failed,aborted'), or by repeating the option"
    ),
    metavar="<status>[,...]",
)
DELETABLE = option(
    "--deletable",
    action="store_true",
    required=False,
    help=(
        "when used with 'namespaces', lists only those that can be deleted"
        " (never populated)"
    ),
)
UNHEALTHY = option(
    "--unhealthy",
    action="store_true",
    required=False,
    help=(
        "list only the entities the Platform marks unhealthy: work"
        " requirements, worker pools and compute requirements"
    ),
)
PROVIDER = option(
    "--provider",
    choices=LIST_PROVIDERS,
    required=False,
    help=(
        "list only those of the given cloud provider: instances, nodes and"
        " compute source templates"
    ),
)
DESCRIPTION = option(
    "--description",
    dest="description_glob",
    metavar="<glob>",
    required=False,
    help=(
        "list only allowances whose description matches the given glob"
        " pattern; a value without wildcards matches the description exactly"
    ),
)
WITH_ERRORS = option(
    "--with-errors",
    action="store_true",
    required=False,
    help=(
        "list only the tasks that recorded an error, whatever their status"
        " (a task can complete after an error, on a retry)"
    ),
)
WITHIN = option(
    "--within",
    dest="within_target",
    metavar="<target>",
    required=False,
    help=(
        "list the items of one parent without asking which: the task groups or"
        " tasks of a work requirement or task group ('wr', 'wr/tg',"
        " 'namespace/wr', 'namespace/wr/tg' or its ID), the instances of a"
        " compute requirement, the nodes of a worker pool, or the workers of a"
        " worker pool or node (its name, 'namespace/name' or its ID; a node by"
        " its ID)"
    ),
)
LIST_LIMIT = option(
    "--limit",
    dest="list_limit",
    metavar="<n>",
    type=non_negative_int,
    required=False,
    help=(
        "list at most this many tasks, instances, nodes or workers, warning"
        " when more match (default"
        f" {DEFAULT_LIST_LIMIT}; 0 lists them all)"
    ),
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
        ("deletable", "--deletable", LIST_DELETABLE_TYPES),
        ("unhealthy", "--unhealthy", LIST_UNHEALTHY_TYPES),
        ("provider", "--provider", LIST_PROVIDER_TYPES),
        ("description_glob", "--description", LIST_DESCRIPTION_TYPES),
        ("with_errors", "--with-errors", LIST_WITH_ERRORS_TYPES),
        ("within_target", "--within", LIST_WITHIN_TYPES),
        ("list_limit", "--limit", LIST_LIMIT_TYPES),
    ):
        if getattr(args, dest, None) and entity_type not in types:
            parser.error(
                f"{flag} does not apply to {entity_type}; it applies to "
                + ", ".join(sorted(types))
            )
    # '--count' is exact, read from the Task Groups' own counts where it can
    if getattr(args, "list_limit", None) is not None and getattr(args, "count", False):
        parser.error("--limit cannot be used with --count, which is never limited")
    within = getattr(args, "within_target", None)
    if within and entity_type in LIST_WITHIN_KINDS:
        from yellowdog_cli.utils.ydid_utils import get_ydid_type

        kinds = LIST_WITHIN_KINDS[entity_type]
        ydid_type = get_ydid_type(within)
        if ydid_type is not None and ydid_type.value not in kinds:
            parser.error(
                f"--within takes a {' or '.join(kinds)}, not a {ydid_type.value}"
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
        UNHEALTHY,
        PROVIDER,
        DESCRIPTION,
        WITH_ERRORS,
        WITHIN,
        LIST_LIMIT,
        PUBLIC_IPS_ONLY,
        DELETABLE,
        DETAILS,
        AUTO_SELECT_ALL,
        SUBSTITUTE_IDS,
        STRIP_IDS,
        HIDE_USER_DATA,
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

# --- yd-cloud-info -------------------------------------------------------

CLOUD_INFO_PROVIDERS = ("aws", "azure", "google", "oci")

# The sort keys each type offers, and an instance-types listing with
# '--prices'; utils/cloud_info.py's SORT_KEYS and PRICED_SORT_KEYS must match
# (tests/test_cloud_info_command.py)
CLOUD_INFO_SORT_KEYS: dict[str, tuple[str, ...]] = {
    CI_REGIONS: ("name",),
    CI_SUB_REGIONS: ("name",),
    CI_INSTANCE_TYPES: ("name", "vcpus", "ram"),
    CI_PRICES: ("name", "price"),
}
CLOUD_INFO_PRICED_SORT_KEYS: tuple[str, ...] = (
    "name",
    "vcpus",
    "ram",
    "spot",
    "on-demand",
)
_CLOUD_INFO_SORT_CHOICES = ("name", "vcpus", "ram", "price", "spot", "on-demand")


def cloud_info_sort_keys(value: str) -> tuple[str, ...]:
    """
    An argparse type for yd-cloud-info's '--sort': any of its keys, which
    check_cloud_info_options() then holds to the ones the type offers.
    """
    return parse_sort_keys(value, _CLOUD_INFO_SORT_CHOICES)


# Each '--sort' type and the keys it accepts, which the MCP catalogue offers
# as a list of them (mcp/tools.py)
SORT_KEY_TYPES: dict[Callable[[str], tuple[str, ...]], tuple[str, ...]] = {
    entity_sort_keys: ENTITY_SORT_KEYS,
    cloud_info_sort_keys: _CLOUD_INFO_SORT_CHOICES,
}

# The types each filter applies to, as (dest, flag, types); '--provider' and
# '--name' apply to all
CLOUD_INFO_OPTION_TYPES: tuple[tuple[str, str, frozenset[str]], ...] = (
    ("region", "--region", frozenset({CI_SUB_REGIONS, CI_INSTANCE_TYPES, CI_PRICES})),
    ("sub_region", "--sub-region", frozenset({CI_INSTANCE_TYPES, CI_PRICES})),
    ("vcpus", "--vcpus", frozenset({CI_INSTANCE_TYPES})),
    ("ram", "--ram", frozenset({CI_INSTANCE_TYPES})),
    ("arch", "--arch", frozenset({CI_INSTANCE_TYPES})),
    ("usage", "--usage", frozenset({CI_PRICES})),
    ("os_licence", "--os", frozenset({CI_INSTANCE_TYPES, CI_PRICES})),
    ("prices", "--prices", frozenset({CI_INSTANCE_TYPES})),
)

_RANGE = re.compile(r"(?P<low>\d+(?:\.\d+)?)?(?P<dash>-)?(?P<high>\d+(?:\.\d+)?)?")


def parse_range(text: str) -> tuple[float | None, float | None]:
    """
    A '--vcpus' or '--ram' value: 'n' (exactly n), 'n-m' (n to m inclusive),
    'n-' (at least n) or '-m' (at most m).
    """
    match = _RANGE.fullmatch(text.strip())
    if match is None or (match["low"] is None and match["high"] is None):
        raise ValueError(
            f"'{text}' is not a number or a range ('4', '4-8', '4-' or '-8')"
        )
    low = None if match["low"] is None else float(match["low"])
    high = None if match["high"] is None else float(match["high"])
    if match["dash"] is None:
        return low, low
    if low is not None and high is not None and low > high:
        raise ValueError(f"'{text}' has its lower bound above its upper bound")
    return low, high


def resolve_cloud_info_type(value: str) -> str:
    """
    A yd-cloud-info TYPE: its full name or an unambiguous prefix.
    """
    matches = [t for t in CLOUD_INFO_TYPES if value and t.startswith(value)]
    if len(matches) == 1:
        return matches[0]
    raise ArgumentTypeError(
        f"unknown type '{value}'; valid types: {', '.join(CLOUD_INFO_TYPES)}"
    )


CLOUD_INFO_TYPE = option(
    "cloud_info_type",
    type=resolve_cloud_info_type,
    metavar="TYPE",
    help=(
        "what to list: "
        + ", ".join(CLOUD_INFO_TYPES)
        + "; an unambiguous prefix (e.g. 'inst') is accepted"
    ),
)
PROVIDER = option(
    "--provider",
    "-p",
    dest="providers",
    action="append",
    choices=CLOUD_INFO_PROVIDERS,
    required=False,
    metavar="<aws|azure|google|oci>",
    help="list only this cloud provider's items; may be repeated",
)
REGION = option(
    "--region",
    type=str,
    required=False,
    metavar="<region>",
    help="the region, matched exactly (e.g. 'eu-west-2')",
)
SUB_REGION = option(
    "--sub-region",
    dest="sub_region",
    type=str,
    required=False,
    metavar="<sub-region>",
    help="the sub-region (availability zone), matched exactly; needs --region",
)
CLOUD_INFO_NAME = NAME.variant(
    help=(
        "list only items whose name matches the given glob pattern (for"
        " prices, the instance type's name); a value without wildcards"
        " matches the name exactly"
    )
)
VCPUS = option(
    "--vcpus",
    type=str,
    required=False,
    metavar="<n|n-m>",
    help=(
        "instance types with this many vCPUs: 'n', 'n-m', 'n-' (at least n)"
        " or '-m' (at most m)"
    ),
)
RAM = option(
    "--ram",
    type=str,
    required=False,
    metavar="<GiB|GiB-GiB>",
    help="instance types with this much RAM in GiB, in the forms --vcpus takes",
)
ARCH = option(
    "--arch",
    choices=("x86_64", "arm64"),
    required=False,
    metavar="<x86_64|arm64>",
    help="instance types with this processor architecture",
)
USAGE = option(
    "--usage",
    choices=("spot", "on-demand"),
    required=False,
    metavar="<spot|on-demand>",
    help="prices of this kind only; both if omitted",
)
OS_LICENCE = option(
    "--os",
    dest="os_licence",
    choices=("none", "windows"),
    required=False,
    metavar="<none|windows>",
    help="prices for this operating system licence: 'none' (the default) or 'windows'",
)
PRICES = option(
    "--prices",
    action="store_true",
    required=False,
    help=(
        "add each instance type's on-demand price and lowest spot price in"
        " the region; needs --region"
    ),
)
CLOUD_INFO_SORT = SORT.variant(
    type=cloud_info_sort_keys,
    metavar="<name|vcpus|ram|price|spot|on-demand>[,...]",
    help=(
        "order of the listing: 'name' (default), 'vcpus' and 'ram' for"
        " instance types, 'price' for prices, 'spot' and 'on-demand' for"
        " instance types with --prices; give several, separated by commas,"
        " to sort by each in turn (e.g. 'spot,vcpus'); items without a"
        " value for a key come after those with one, with --reverse too"
    ),
)


def check_cloud_info_options(args: Namespace, parser: ArgumentParser) -> None:
    """
    yd-cloud-info's filters, refused for a type they do not apply to rather
    than ignored, as yd-list's are; and its ranges checked, so that a
    malformed one is a usage error (CLIParser's 'vcpus_range' and
    'ram_range' parse them again for the command).
    """
    info_type = args.cloud_info_type
    for dest, flag, types in CLOUD_INFO_OPTION_TYPES:
        if getattr(args, dest, None) and info_type not in types:
            parser.error(
                f"{flag} does not apply to {info_type}; it applies to "
                + ", ".join(sorted(types))
            )
    if args.prices and args.region is None:
        parser.error(
            "--prices needs --region: every region's prices are far too many to fetch"
        )
    if args.sub_region is not None and args.region is None:
        parser.error("--sub-region needs --region")
    if info_type == CI_PRICES and args.region is None and args.name_glob is None:
        parser.error(
            "prices needs --region or --name: every region's prices are far too"
            " many to fetch"
        )
    if (
        args.os_licence is not None
        and info_type == CI_INSTANCE_TYPES
        and not args.prices
    ):
        parser.error("--os applies to instance-types only with --prices")
    sort_keys = (
        CLOUD_INFO_PRICED_SORT_KEYS if args.prices else CLOUD_INFO_SORT_KEYS[info_type]
    )
    for key in args.sort:
        if key not in sort_keys:
            parser.error(
                f"--sort {key} does not apply to {info_type}"
                + (" with --prices" if args.prices else "")
                + "; choose from "
                + ", ".join(sort_keys)
            )
    for dest, flag in (("vcpus", "--vcpus"), ("ram", "--ram")):
        text = getattr(args, dest)
        try:
            if text is not None:
                parse_range(text)
        except ValueError as error:
            parser.error(f"{flag}: {error}")


COMMANDS["yd-cloud-info"] = Command(
    name="yd-cloud-info",
    purpose="listing cloud regions, instance types and prices",
    summary="List cloud regions, instance types and prices",
    kind=CommandKind.API,
    options=(
        CLOUD_INFO_SORT,
        REVERSE,
        JSON,
        COUNT.variant(
            help="print only the number of matching items (overrides '--json')"
        ),
        CLOUD_INFO_TYPE,
        PROVIDER,
        REGION,
        SUB_REGION,
        CLOUD_INFO_NAME,
        VCPUS,
        RAM,
        ARCH,
        USAGE,
        OS_LICENCE,
        PRICES,
    ),
    validators=(check_cloud_info_options,),
    tool=ToolKind.READ_ONLY,
    tool_description=(
        "List what the YellowDog Platform knows of the cloud providers: its"
        " regions, sub-regions, instance types or prices, as the tool's name"
        " says. Filters: providers (aws, azure, google, oci), region and sub_region"
        " (exact names; sub_region needs region), name_glob (a glob; for"
        " prices, the instance type), and for instance-types vcpus and ram"
        " (GiB) as 'n', 'n-m', 'n-' or '-m', and arch; for prices usage"
        " (spot, on-demand) and os_licence (none, windows). prices needs"
        " region or name_glob. instance-types with prices=true"
        " and a region adds each type's onDemandPrice, its lowest spotPrice"
        " and spotSubRegion; sort by spot or on-demand to find the cheapest."
        " Returns an array of the listed items."
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
    validators=(check_ls_args,),
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
    completes=Completes.FILE,
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
    the constants modules and glob_utils.py.
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
            help="name of the target worker pool",
            metavar="<worker-pool-name>",
            completes=Completes.NONE,
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
    help=(
        "resize the compute requirement of this name instead of the worker"
        " pool; not needed with a compute requirement ID"
    ),
)


def resize_targets_compute_requirement(args: Namespace) -> bool:
    """
    Whether yd-resize resizes a Compute Requirement: asked for with
    '--compute-requirement', or given one's ID. A name needs the option,
    since a Worker Pool and its Compute Requirement share their name.
    """
    from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

    return bool(args.compute_requirement) or (
        get_ydid_type(args.worker_pool) == YDIDType.COMPUTE_REQUIREMENT
    )


def check_resize_target(args: Namespace, parser: ArgumentParser) -> None:
    """
    '--compute-requirement' with a Worker Pool's ID contradicts itself.
    """
    from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

    if args.compute_requirement and (
        get_ydid_type(args.worker_pool) == YDIDType.WORKER_POOL
    ):
        parser.error(
            f"--compute-requirement/-C cannot be used with a Worker Pool ID"
            f" ({args.worker_pool})"
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
        WAIT_FOR_CAPACITY,
        WAIT_TIMEOUT,
    ),
    validators=(check_resize_target, check_wait_options),
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
    help=f"the specification family to print: {', '.join(SCHEMA_FAMILIES)}",
)
SCHEMA_WRITE = option(
    "--write",
    type=str,
    completes=Completes.DIR,
    metavar="<dir>",
    help="write every family's schema to <dir>, and index.json naming the CLI and SDK versions",
)
SCHEMA_CHECK = option(
    "--check",
    type=str,
    completes=Completes.DIR,
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
        NO_FORMAT,
    ),
    validators=(check_schema_mode_is_exclusive,),
    tool=ToolKind.READ_ONLY,
    tool_description=(
        "Print the JSON Schema a specification family must follow —"
        " work-requirement (yd_workrequirement_submit), worker-pool"
        " (yd_workerpool_provision), compute-requirement"
        " (yd_computerequirement_instantiate), resources (yd_resource_create),"
        " node-actions (yd_node_action), or config, the TOML configuration"
        " file — generated from the installed CLI and SDK. Ask for it before"
        " composing an inline specification."
    ),
)

# --- yd-shutdown ---------------------------------------------------------

WORKER_POOL_NODES_LIST = option(
    "worker_pool_nodes_list",
    nargs="*",
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
    completes=Completes.FILE,
    metavar="<work_requirement.json>",
)
JSON_RAW = option(
    "--json-raw",
    "-j",
    type=str,
    required=False,
    help="submit a 'raw' JSON work requirement file",
    completes=Completes.FILE,
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
    type=positive_int,
    required=False,
    help="the number of tasks to submit (copies of a single task)",
    metavar="<task_count>",
)
TASK_GROUP_COUNT = option(
    "--task-group-count",
    "-G",
    type=positive_int,
    required=False,
    help="the number of task groups to submit (copies of a single task group)",
    metavar="<task_group_count>",
)
TASK_BATCH_SIZE = option(
    "--task-batch-size",
    "-b",
    type=positive_int,
    required=False,
    help="the batch size for task submission; must be between 1 and 10,000",
    metavar="<batch_size>",
)
PAUSE_BETWEEN_BATCHES = option(
    "--pause-between-batches",
    "-P",
    nargs="?",
    type=non_negative_int,
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
    completes=Completes.FILE,
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
    type=positive_int,
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
    completes=Completes.FILE,
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
        ENTITY_JSON.variant(
            help=(
                "emit the created entity as JSON; with --dry-run, the processed"
                " specification; not with --progress"
            )
        ),
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
        " yd_data_download; yd_schema work-requirement gives the schema to"
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

# --- yd-priority ---------------------------------------------------------

PRIORITY = option(
    "priority",
    metavar="<priority>",
    type=finite_float,
    help=(
        "the new priority, a number; higher priority acquires workers ahead of lower"
    ),
)
PRIORITY_TARGETS = option(
    "priority_targets",
    nargs="+",
    metavar="<work-requirement-or-task-group>",
    type=str,
    help=(
        "the work requirement(s) or task group(s): IDs, or names as 'wr',"
        " 'wr/tg', 'namespace/wr' or 'namespace/wr/tg'"
    ),
)

COMMANDS["yd-priority"] = Command(
    name="yd-priority",
    purpose="changing the priority of Work Requirements and Task Groups",
    summary="Change the priority of Work Requirements and Task Groups",
    kind=CommandKind.API,
    options=(
        VARIABLE,
        NAMESPACE,
        DRY_RUN,
        YES,
        ACTIONS_JSON,
        PRIORITY,
        PRIORITY_TARGETS,
    ),
    requires_namespace_and_tag=True,
    tool=ToolKind.DESTRUCTIVE,
)

# --- yd-token ------------------------------------------------------------

TOKEN_WORKER_POOLS = option(
    "worker_pools",
    nargs="+",
    metavar="<worker-pool-name-or-ID>",
    type=str,
    help="the name(s) or YellowDog ID(s) of the configured worker pool(s);"
    " a name may be a glob pattern (e.g. 'wp-*')",
)
REGENERATE = option(
    "--regenerate",
    "-R",
    action="store_true",
    required=False,
    help=(
        "issue a new token, invalidating the current one, rather than"
        " setting the current token's expiry afresh"
    ),
)
TTL_HOURS = option(
    "--ttl-hours",
    "-H",
    type=positive_int,
    required=False,
    help="the token's time to live in hours, from now; without it, the token does not expire",
    metavar="<hours>",
)

COMMANDS["yd-token"] = Command(
    name="yd-token",
    purpose="refreshing or regenerating the tokens of Configured Worker Pools",
    summary="Refresh or regenerate the tokens of Configured Worker Pools",
    kind=CommandKind.API,
    options=(
        VARIABLE,
        NAMESPACE,
        DRY_RUN,
        YES,
        ACTIONS_JSON,
        TOKEN_WORKER_POOLS,
        REGENERATE,
        TTL_HOURS,
    ),
    requires_namespace_and_tag=True,
    tool=ToolKind.DESTRUCTIVE,
)

# --- yd-upload -----------------------------------------------------------

LOCAL_PATHS = Option(
    ("local_paths",),
    {
        "metavar": "<local-path>",
        "type": str,
        "nargs": "*",
        "help": "local file(s) or directory(ies) to upload",
    },
    tool_required=True,
    completes=Completes.FILE,
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
    validators=(check_transfer_args,),
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


def check_variable_names(args: Namespace, parser: ArgumentParser) -> None:
    """
    yd-variables' names: each one a variable could have, since any other
    could only ever report 'null' ('{{x}}', 'env:HOME').
    """
    import re

    from yellowdog_cli.utils.variable_syntax import VARIABLE_NAME_PATTERN

    for name in args.variable_names:
        if not re.fullmatch(VARIABLE_NAME_PATTERN, name):
            parser.error(
                f"not a variable name: '{name}' (a name is a letter, digit or '_',"
                " then letters, digits, '_', '.' and '-')"
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
                " (case-insensitive), and the parameters of any value that is an"
                " inline rclone connection string, whether named or not; any"
                " other variable is reported in full, even one holding a"
                " credential"
            )
        ),
    ),
    validators=(check_variable_names,),
    requires_namespace_and_tag=True,
    requires_credentials=False,
    tool=ToolKind.READ_ONLY,
)

# --- Standalone commands -------------------------------------------------
# Each keeps a parser of its own (or none); only their purpose and summary
# are held here, bar yd-completion, whose parser is built from its options
# here (build_parser()).

COMPLETION_SHELLS = ("bash", "zsh", "fish", "powershell")
COMPLETION_SHELL = option(
    "shell",
    choices=COMPLETION_SHELLS,
    help=(
        "the shell to print the completion script for: load it with"
        " 'eval \"$(yd completion bash)\"' (or zsh) in the shell's start-up"
        " file, 'yd completion fish | source' in fish's config.fish, or"
        " 'yd completion powershell | Out-String | Invoke-Expression' in a"
        " PowerShell profile"
    ),
)

COMPLETION_NAMES = option(
    "--names",
    action="store_true",
    help=(
        "a script that completes the names and IDs of what is on the Platform"
        " too (Work Requirements, Worker Pools, ...), looking them up as the"
        " command would, within 2 seconds; load it in place of the script"
        " without, e.g. 'eval \"$(yd completion zsh --names)\"'. Setting"
        " YD_COMPLETION_LOOKUPS=off switches the lookups off again"
    ),
)

COMMANDS["yd-completion"] = Command(
    name="yd-completion",
    purpose="printing the shell completion script for the yd-* commands",
    summary="Print the shell completion script for the yd-* commands",
    kind=CommandKind.STANDALONE,
    options=(COMPLETION_SHELL, COMPLETION_NAMES),
    tool=ToolKind.NONE,
    script=False,
)
FORMAT_JSON_FILES = option(
    "files",
    nargs="+",
    metavar="<file.json>",
    help="the JSON file(s) to reformat",
    completes=Completes.FILE,
)
FORMAT_JSON_CHECK = option(
    "--check",
    action="store_true",
    required=False,
    help=(
        "report the files that would be reformatted, without writing"
        " anything, and exit 1 if there are any"
    ),
)
COMMANDS["yd-format-json"] = Command(
    name="yd-format-json",
    purpose=(
        "reformatting JSON files in place with the CLI's compact layout (small"
        " containers on one line), changing nothing but the layout"
    ),
    summary="Format JSON files using a compact encoder",
    kind=CommandKind.STANDALONE,
    options=(FORMAT_JSON_FILES, FORMAT_JSON_CHECK),
    tool=ToolKind.NONE,
)
HELP_JSON = ACTIONS_JSON.variant(
    help=(
        "print the commands as a JSON array: the nouns with their verbs,"
        " the other commands, and the deprecated ones"
    )
)
HELP_DEPRECATED = option(
    "--deprecated",
    action="store_true",
    required=False,
    help="list the deprecated yd-* commands and the yd forms that replace them",
)
COMMANDS["yd-help"] = Command(
    name="yd-help",
    purpose="listing the yd commands and their purposes",
    summary="List available yd-* commands and their purposes",
    kind=CommandKind.STANDALONE,
    options=(
        HELP_JSON,
        HELP_DEPRECATED,
        NO_FORMAT.variant(
            help="print the listing, or the --json array, without colouring"
        ),
    ),
    tool=ToolKind.NONE,
)
JSONNET2JSON_FILES = option(
    "files",
    nargs="+",
    metavar="<file.jsonnet>",
    help="the Jsonnet file(s), or quoted glob pattern(s), to convert",
    completes=Completes.FILE,
)
COMMANDS["yd-jsonnet2json"] = Command(
    name="yd-jsonnet2json",
    purpose=(
        "converting Jsonnet files to JSON: one file to stdout, or several (or"
        " a glob pattern) each to <name>.json beside it"
    ),
    summary="Convert a Jsonnet file to JSON",
    kind=CommandKind.STANDALONE,
    options=(
        JSONNET2JSON_FILES,
        NO_FORMAT.variant(help="print a single file's JSON without colouring"),
        YES.variant(help="overwrite existing .json files without asking"),
    ),
    tool=ToolKind.NONE,
)
# yd-version's single-version flags, each printing one version number alone,
# exclusive with one another and with its '--json'
VERSION_CLI = option(
    "--cli", action="store_true", required=False, help="print CLI version number only"
)
VERSION_SDK = option(
    "--sdk", action="store_true", required=False, help="print SDK version number only"
)
VERSION_PYTHON = option(
    "--python",
    action="store_true",
    required=False,
    help="print Python version number only",
)
VERSION_JSONNET = option(
    "--jsonnet",
    action="store_true",
    required=False,
    help="print Jsonnet version number only",
)
VERSION_RCLONE = option(
    "--rclone",
    action="store_true",
    required=False,
    help="print rclone version number only",
)
VERSION_MCP = option(
    "--mcp",
    action="store_true",
    required=False,
    help="print the MCP SDK version number only",
)
VERSION_JSON = ACTIONS_JSON.variant(
    help=(
        "print the version numbers, author and licence as a JSON object,"
        " null for a version not installed; with --debug, the Python"
        " executable and path too"
    )
)
COMMANDS["yd-version"] = Command(
    name="yd-version",
    purpose="reporting YellowDog CLI and related version numbers",
    summary="Report version information",
    kind=CommandKind.STANDALONE,
    options=(
        Exclusive(
            (
                VERSION_CLI,
                VERSION_SDK,
                VERSION_PYTHON,
                VERSION_JSONNET,
                VERSION_RCLONE,
                VERSION_MCP,
                VERSION_JSON,
            )
        ),
        DEBUG.variant(help="print Python path and executable details"),
        NO_FORMAT.variant(help="print the report without colouring"),
    ),
    tool=ToolKind.READ_ONLY,
)
