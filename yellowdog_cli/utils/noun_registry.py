"""
The noun commands: 'yd workrequirement submit', 'yd instance terminate', and
the rest, each a noun naming the object operated on and a verb naming what
is done to it.

A verb is not a command of its own: it runs one of the registry's commands
(command_registry.COMMANDS), which stay the units the CLI is built from, with
its options narrowed to the object. NOUN_COMMANDS holds a Command derived for
each noun and verb: named for the noun form, it runs ('runs') the registry
command, with the options that do not apply to the object hidden from its
help and refused if given, any arguments the verb fixes (yd-list's entity
type, yd-cloud-info's type) supplied by the dispatcher (noun_dispatch.py),
and the targets it is given held to the object's kind. The registry commands
the noun verbs replace are kept for a release as deprecated aliases
(REPLACED_BY_VERBS); yd-list, yd-show, yd-follow and yd-wait are not replaced, but
offered under each noun as well, restricted to its objects.
"""

from __future__ import annotations

from argparse import SUPPRESS, ArgumentParser, Namespace
from dataclasses import dataclass, field, replace
from typing import Any

from yellowdog_cli.utils.command_registry import (
    COMMANDS,
    LIST_ACTIVE_TYPES,
    LIST_DELETABLE_TYPES,
    LIST_DESCRIPTION_TYPES,
    LIST_ID_TYPES,
    LIST_NAME_TYPES,
    LIST_PROVIDER_TYPES,
    LIST_STATUS_TYPES,
    LIST_SUBSTITUTE_TYPES,
    LIST_UNHEALTHY_TYPES,
    LIST_WITH_ERRORS_TYPES,
    LIST_WITHIN_TYPES,
    Command,
    Exclusive,
    Option,
    Validator,
    command_module,
)
from yellowdog_cli.utils.entity_names import (
    CI_INSTANCE_TYPES,
    CI_PRICES,
    CI_REGIONS,
    CI_SUB_REGIONS,
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
from yellowdog_cli.utils.ydid_utils import (
    YDIDType,
    get_ydid_type,
    split_instance_specification,
)

# The kinds of target a verb can take, beyond the YDID types: an Instance
# ('cr_id.instance_id', which is no YDID) and a name (anything else)
INSTANCE = "instance"
NAME = "name"
TargetKind = YDIDType | str

# The registry commands every noun offers, restricted to its objects, and
# which stay commands in their own right: no noun replaces them
GENERIC_COMMANDS = frozenset({"yd-list", "yd-show", "yd-follow", "yd-wait"})

# The options that select Compute Requirements, Worker Pools or Work
# Requirements by namespace, tag or interactive listing: meaningless for a
# verb that takes Instance or Node IDs alone
_SELECTION_OPTIONS = (
    "--sort",
    "--reverse",
    "--namespace",
    "--tag",
    "--interactive",
)

# The configuration types 'yd resource list' lists: those yd-create makes,
# and the Platform's own (namespaces, permissions) beside them
RESOURCE_LIST_TYPES = frozenset(
    {
        ET_ALLOWANCES,
        ET_APPLICATIONS,
        ET_ATTRIBUTE_DEFINITIONS,
        ET_COMPUTE_REQUIREMENT_TEMPLATES,
        ET_COMPUTE_SOURCE_TEMPLATES,
        ET_GROUPS,
        ET_IMAGE_FAMILIES,
        ET_KEYRINGS,
        ET_NAMESPACE_POLICIES,
        ET_NAMESPACES,
        ET_PERMISSIONS,
        ET_ROLES,
        ET_USERS,
    }
)

# The YDID types 'yd resource show' shows
RESOURCE_YDID_TYPES = frozenset(
    {
        YDIDType.ALLOWANCE,
        YDIDType.APPLICATION,
        YDIDType.COMPUTE_REQUIREMENT_TEMPLATE,
        YDIDType.COMPUTE_SOURCE_TEMPLATE,
        YDIDType.GROUP,
        YDIDType.IMAGE,
        YDIDType.IMAGE_FAMILY,
        YDIDType.IMAGE_GROUP,
        YDIDType.KEYRING,
        YDIDType.ROLE,
        YDIDType.USER,
    }
)


@dataclass(frozen=True)
class Targets:
    """
    The targets a verb accepts: the positional ('dest') whose values are
    held to 'kinds', described as 'described' in a refusal.
    """

    dest: str
    kinds: frozenset[TargetKind]
    described: str


@dataclass(frozen=True)
class Verb:
    name: str  # "submit"
    command: str  # the registry command it runs: "yd-submit"
    summary: str  # "Submit a Work Requirement": the noun help's line
    purpose: str  # "submitting a Work Requirement": the description's tail
    # Arguments placed ahead of the user's, and the options they set, which
    # are hidden from help (and not refused, being given by the verb)
    fixed: tuple[str, ...] = ()
    fixed_options: tuple[str, ...] = ()
    # Options (by name) that do not apply: hidden from help, refused if given
    hidden: tuple[str, ...] = ()
    # Keyword arguments replaced on an option (by name), keeping its identity
    overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    targets: Targets | None = None
    # A check of the parsed arguments of the verb's own
    validators: tuple[Validator, ...] = ()


@dataclass(frozen=True)
class Noun:
    name: str  # "workrequirement"
    summary: str  # what the noun's commands do, for its help and yd-help
    verbs: tuple[Verb, ...]
    alias: str | None = None  # "wr"

    def verb(self, name: str) -> Verb | None:
        return next((verb for verb in self.verbs if verb.name == name), None)

    def invoked_names(self) -> tuple[str, ...]:
        return (self.name,) if self.alias is None else (self.name, self.alias)


def target_kind(target: str) -> TargetKind:
    """
    The kind of a target as given: an Instance specification, a YDID's
    type, or else a name.
    """
    if split_instance_specification(target) is not None:
        return INSTANCE
    ydid_type = get_ydid_type(target)
    return NAME if ydid_type is None else ydid_type


def kind_description(kind: TargetKind) -> str:
    if kind == INSTANCE:
        return "an Instance"
    if kind == NAME:
        return "a name"
    assert isinstance(kind, YDIDType)
    article = "an" if kind.value[0] in "AEIOU" else "a"
    return f"{article} {kind.value} ID"


# --- Verb builders ---------------------------------------------------------


def _ids(*types: YDIDType) -> frozenset[TargetKind]:
    return frozenset(types)


def _named(*types: YDIDType) -> frozenset[TargetKind]:
    return frozenset({*types, NAME})


def _list(entity_type: str, noun_plural: str) -> Verb:
    """
    yd-list for one entity type, its filters that do not apply to the type
    hidden (check_list_options refuses them all the same).
    """
    hidden = [
        flag
        for flag, types in (
            ("--name", LIST_NAME_TYPES),
            ("--status", LIST_STATUS_TYPES),
            ("--active-only", LIST_ACTIVE_TYPES),
            ("--ids-only", LIST_ID_TYPES),
            ("--substitute-ids", LIST_SUBSTITUTE_TYPES),
            ("--public-ips-only", frozenset({ET_INSTANCES})),
            ("--deletable", LIST_DELETABLE_TYPES),
            ("--unhealthy", LIST_UNHEALTHY_TYPES),
            ("--provider", LIST_PROVIDER_TYPES),
            ("--description", LIST_DESCRIPTION_TYPES),
            ("--with-errors", LIST_WITH_ERRORS_TYPES),
            ("--within", LIST_WITHIN_TYPES),
        )
        if entity_type not in types
    ]
    return Verb(
        "list",
        "yd-list",
        f"List {noun_plural}",
        f"listing {noun_plural}",
        fixed=(entity_type,),
        fixed_options=("entity_type",),
        hidden=tuple(hidden),
    )


def _show(
    noun_plural: str,
    kinds: frozenset[TargetKind],
    described: str,
    keep: tuple[str, ...] = (),
) -> Verb:
    """
    yd-show for one kind of object, the options for other kinds hidden.
    """
    specific = (
        "--show-token",
        "--show-source-report",
        "--show-exhaustion",
        "--show-members",
    )
    return Verb(
        "show",
        "yd-show",
        f"Show the details of {noun_plural}",
        f"showing the JSON details of {noun_plural}",
        hidden=tuple(flag for flag in specific if flag not in keep),
        overrides={
            "yellowdog_ids": {
                "metavar": f"<{described}>",
                "help": f"the {described.replace('-', ' ')}(s) to show",
            }
        },
        targets=Targets("yellowdog_ids", kinds, described),
    )


def _follow(
    noun_plural: str, ydid_type: YDIDType, described: str, keep: tuple[str, ...] = ()
) -> Verb:
    specific = ("--progress", "--auto-follow-compute-requirements")
    return Verb(
        "follow",
        "yd-follow",
        f"Follow the event streams of {noun_plural}",
        f"following the event streams of {noun_plural}",
        hidden=tuple(flag for flag in specific if flag not in keep),
        overrides={
            "yellowdog_ids": {
                "metavar": f"<{described}>",
                "help": f"the {described.replace('-', ' ')}(s) to follow",
            }
        },
        targets=Targets("yellowdog_ids", _ids(ydid_type), described),
    )


def _wait(noun_plural: str, ydid_type: YDIDType, described: str) -> Verb:
    return Verb(
        "wait",
        "yd-wait",
        f"Wait for {noun_plural} to reach a terminal state",
        f"waiting for {noun_plural} to reach a terminal state",
        overrides={
            "yellowdog_ids": {
                "metavar": f"<{described}>",
                "help": f"the {described.replace('-', ' ')}(s) to wait for",
            }
        },
        targets=Targets("yellowdog_ids", _ids(ydid_type), described),
    )


def _compute_action(
    name: str,
    command: str,
    summary: str,
    purpose: str,
    kinds: frozenset[TargetKind],
    described: str,
    help_text: str,
) -> Verb:
    """
    A compute action (or yd-terminate, or yd-shutdown) on one kind of
    target. One that takes IDs alone needs at least one, and has none of the
    options that select Compute Requirements by namespace, tag or listing.
    """
    by_id_only = NAME not in kinds
    overrides: dict[str, Any] = {"metavar": f"<{described}>", "help": help_text}
    if by_id_only:
        overrides["nargs"] = "+"
    return Verb(
        name,
        command,
        summary,
        purpose,
        hidden=_SELECTION_OPTIONS if by_id_only else (),
        overrides={"compute_reqs_instances_or_nodes": overrides},
        targets=Targets("compute_reqs_instances_or_nodes", kinds, described),
    )


_CR_TARGETS = _named(YDIDType.COMPUTE_REQUIREMENT)
_CR_DESCRIBED = "compute-requirement-name-or-ID"
_CR_HELP = (
    "the name(s) or YellowDog ID(s) of the compute requirement(s); a name"
    " may be a glob pattern (e.g. 'cr-*')"
)
_INSTANCE_TARGETS = frozenset({INSTANCE})
_INSTANCE_DESCRIBED = "cr-id.instance-id"
_INSTANCE_HELP = "the instance(s), each as 'cr_id.instance_id'"
_NODE_TARGETS = _ids(YDIDType.NODE)
_NODE_DESCRIBED = "node-ID"
_NODE_HELP = "the YellowDog ID(s) of the node(s)"


def _cr_action(name: str, command: str, summary: str, purpose: str) -> Verb:
    return _compute_action(
        name, command, summary, purpose, _CR_TARGETS, _CR_DESCRIBED, _CR_HELP
    )


def _instance_action(name: str, command: str, summary: str, purpose: str) -> Verb:
    return _compute_action(
        name,
        command,
        summary,
        purpose,
        _INSTANCE_TARGETS,
        _INSTANCE_DESCRIBED,
        _INSTANCE_HELP,
    )


def _node_action(name: str, command: str, summary: str, purpose: str) -> Verb:
    return _compute_action(
        name, command, summary, purpose, _NODE_TARGETS, _NODE_DESCRIBED, _NODE_HELP
    )


def _compare(noun_singular: str, ydid_type: YDIDType, described: str) -> Verb:
    return Verb(
        "compare",
        "yd-compare",
        f"Compare a {noun_singular} against Worker Pool(s)",
        f"comparing whether a {noun_singular.lower()} is matched by workers in"
        " the specified provisioned worker pools",
        overrides={
            "wr_or_tg_id": {
                "metavar": f"<{described}>",
                "help": f"the YellowDog ID of the {noun_singular.lower()} to compare",
            }
        },
        targets=Targets("wr_or_tg_id", _ids(ydid_type), described),
    )


def _priority(noun_plural: str) -> Verb:
    return Verb(
        "priority",
        "yd-priority",
        f"Change the priority of {noun_plural}",
        f"changing the priority of {noun_plural}",
    )


def _cloud_info(name: str, info_type: str, summary: str) -> Verb:
    return Verb(
        name,
        "yd-cloud-info",
        summary,
        "listing " + summary.removeprefix("List "),
        fixed=(info_type,),
        fixed_options=("cloud_info_type",),
    )


def _check_resource_type(args: Namespace, parser: ArgumentParser) -> None:
    if args.entity_type not in RESOURCE_LIST_TYPES:
        parser.error(
            f"'{args.entity_type}' is not a resource type; choose from:"
            f" {', '.join(sorted(RESOURCE_LIST_TYPES))}"
        )


# --- The nouns -------------------------------------------------------------

_WR_DESCRIBED = "work-requirement-ID"
_TG_DESCRIBED = "task-group-ID"
_WP_DESCRIBED = "worker-pool-ID"
_CR_ID_DESCRIBED = "compute-requirement-ID"

NOUNS: tuple[Noun, ...] = (
    Noun(
        "workrequirement",
        "Submit, control and inspect Work Requirements",
        (
            Verb(
                "submit",
                "yd-submit",
                "Submit a Work Requirement",
                "submitting a Work Requirement",
            ),
            Verb(
                "cancel",
                "yd-cancel",
                "Cancel Work Requirements",
                "cancelling Work Requirements",
            ),
            Verb(
                "hold",
                "yd-hold",
                "Hold (pause) running Work Requirements",
                "holding (pausing) running Work Requirements",
            ),
            Verb(
                "start",
                "yd-start",
                "Start held (paused) Work Requirements",
                "starting held (paused) Work Requirements",
            ),
            Verb(
                "finish",
                "yd-finish",
                "Finish Work Requirements",
                "finishing Work Requirements",
            ),
            _priority("Work Requirements and Task Groups"),
            _compare("Work Requirement", YDIDType.WORK_REQUIREMENT, _WR_DESCRIBED),
            _list(ET_WORK_REQUIREMENTS, "Work Requirements"),
            _show("Work Requirements", _ids(YDIDType.WORK_REQUIREMENT), _WR_DESCRIBED),
            _follow(
                "Work Requirements",
                YDIDType.WORK_REQUIREMENT,
                _WR_DESCRIBED,
                keep=("--progress",),
            ),
            _wait("Work Requirements", YDIDType.WORK_REQUIREMENT, _WR_DESCRIBED),
        ),
        alias="wr",
    ),
    Noun(
        "taskgroup",
        "Inspect Task Groups and change their priority",
        (
            _priority("Task Groups and Work Requirements"),
            _compare("Task Group", YDIDType.TASK_GROUP, _TG_DESCRIBED),
            _list(ET_TASK_GROUPS, "Task Groups"),
            _show("Task Groups", _ids(YDIDType.TASK_GROUP), _TG_DESCRIBED),
        ),
        alias="tg",
    ),
    Noun(
        "task",
        "Abort and inspect Tasks",
        (
            Verb(
                "abort",
                "yd-abort",
                "Abort running Tasks",
                "aborting Tasks individually, or in Work Requirements or Task Groups",
            ),
            _list(ET_TASKS, "Tasks"),
            _show("Tasks", _ids(YDIDType.TASK), "task-ID"),
        ),
    ),
    Noun(
        "workerpool",
        "Provision, resize, shut down and inspect Worker Pools",
        (
            Verb(
                "provision",
                "yd-provision",
                "Provision a Worker Pool",
                "provisioning a Worker Pool",
            ),
            Verb(
                "resize",
                "yd-resize",
                "Resize a Worker Pool",
                "resizing a Worker Pool",
                hidden=("--compute-requirement",),
                overrides={
                    "worker_pool": {
                        "metavar": "<worker-pool-name-or-ID>",
                        "help": "the name or YellowDog ID of the worker pool to resize",
                    }
                },
                targets=Targets(
                    "worker_pool",
                    _named(YDIDType.WORKER_POOL),
                    "worker-pool-name-or-ID",
                ),
            ),
            Verb(
                "shutdown",
                "yd-shutdown",
                "Shut down Worker Pools",
                "shutting down Worker Pools",
                overrides={
                    "worker_pool_nodes_list": {
                        "metavar": "<worker-pool-name-or-ID>",
                        "help": (
                            "the name(s) or YellowDog ID(s) of the worker"
                            " pool(s); a name may be a glob pattern (e.g. 'wp-*')"
                        ),
                    }
                },
                targets=Targets(
                    "worker_pool_nodes_list",
                    _named(YDIDType.WORKER_POOL),
                    "worker-pool-name-or-ID",
                ),
            ),
            Verb(
                "token",
                "yd-token",
                "Refresh or regenerate the tokens of Configured Worker Pools",
                "refreshing or regenerating the tokens of Configured Worker Pools",
            ),
            _list(ET_WORKER_POOLS, "Worker Pools"),
            _show(
                "Worker Pools",
                _ids(YDIDType.WORKER_POOL),
                _WP_DESCRIBED,
                keep=("--show-token", "--show-source-report", "--show-exhaustion"),
            ),
            _follow(
                "Worker Pools",
                YDIDType.WORKER_POOL,
                _WP_DESCRIBED,
                keep=("--auto-follow-compute-requirements",),
            ),
            _wait("Worker Pools", YDIDType.WORKER_POOL, _WP_DESCRIBED),
        ),
        alias="wp",
    ),
    Noun(
        "computerequirement",
        "Instantiate, control and inspect Compute Requirements",
        (
            Verb(
                "instantiate",
                "yd-instantiate",
                "Instantiate a Compute Requirement",
                "instantiating a Compute Requirement",
            ),
            Verb(
                "resize",
                "yd-resize",
                "Resize a Compute Requirement",
                "resizing a Compute Requirement",
                fixed=("--compute-requirement",),
                fixed_options=("--compute-requirement",),
                hidden=("--auto-follow-compute-requirements",),
                overrides={
                    "worker_pool": {
                        "metavar": f"<{_CR_DESCRIBED}>",
                        "help": (
                            "the name or YellowDog ID of the compute"
                            " requirement to resize"
                        ),
                    },
                    "worker_pool_size": {
                        "help": "the desired number of (total) instances",
                    },
                },
                targets=Targets("worker_pool", _CR_TARGETS, _CR_DESCRIBED),
            ),
            _cr_action(
                "stop",
                "yd-compute-stop",
                "Stop Compute Requirements",
                "stopping Compute Requirements",
            ),
            _cr_action(
                "start",
                "yd-compute-start",
                "Start stopped Compute Requirements",
                "starting stopped Compute Requirements",
            ),
            _cr_action(
                "reprovision",
                "yd-compute-reprovision",
                "Reprovision Compute Requirements, restoring their target"
                " instance counts",
                "reprovisioning Compute Requirements: provisioning Instances"
                " until their target counts are met",
            ),
            _cr_action(
                "terminate",
                "yd-terminate",
                "Terminate Compute Requirements",
                "terminating Compute Requirements",
            ),
            _list(ET_COMPUTE_REQUIREMENTS, "Compute Requirements"),
            _show(
                "Compute Requirements",
                _ids(YDIDType.COMPUTE_REQUIREMENT, YDIDType.COMPUTE_SOURCE),
                _CR_ID_DESCRIBED,
                keep=("--show-source-report", "--show-exhaustion"),
            ),
            _follow(
                "Compute Requirements", YDIDType.COMPUTE_REQUIREMENT, _CR_ID_DESCRIBED
            ),
            _wait(
                "Compute Requirements", YDIDType.COMPUTE_REQUIREMENT, _CR_ID_DESCRIBED
            ),
        ),
        alias="cr",
    ),
    Noun(
        "instance",
        "Control and inspect the Instances of Compute Requirements",
        (
            _instance_action(
                "stop", "yd-compute-stop", "Stop Instances", "stopping Instances"
            ),
            _instance_action(
                "start",
                "yd-compute-start",
                "Start stopped Instances",
                "starting stopped Instances",
            ),
            _instance_action(
                "restart",
                "yd-compute-restart",
                "Restart Instances",
                "restarting Instances",
            ),
            _instance_action(
                "deprovision",
                "yd-compute-deprovision",
                "Deprovision Instances, reducing their Compute Requirements'"
                " target counts",
                "deprovisioning Instances: terminating them and reducing their"
                " Compute Requirements' target counts to match",
            ),
            _instance_action(
                "terminate",
                "yd-terminate",
                "Terminate Instances",
                "terminating Instances",
            ),
            _list(ET_INSTANCES, "Instances"),
            _show("Instances", _INSTANCE_TARGETS, _INSTANCE_DESCRIBED),
        ),
    ),
    Noun(
        "node",
        "Act on and inspect Worker Pool Nodes",
        (
            Verb(
                "action",
                "yd-nodeaction",
                "Submit Node Actions to Worker Pool nodes",
                "submitting Node Actions to Worker Pool nodes",
            ),
            Verb(
                "shutdown",
                "yd-shutdown",
                "Shut down Nodes",
                "shutting down Nodes",
                hidden=(
                    *_SELECTION_OPTIONS,
                    "--terminate",
                    "--auto-follow-compute-requirements",
                ),
                overrides={
                    "worker_pool_nodes_list": {
                        "nargs": "+",
                        "metavar": f"<{_NODE_DESCRIBED}>",
                        "help": _NODE_HELP,
                    }
                },
                targets=Targets(
                    "worker_pool_nodes_list", _NODE_TARGETS, _NODE_DESCRIBED
                ),
            ),
            _node_action(
                "stop",
                "yd-compute-stop",
                "Stop the Instances of Nodes",
                "stopping the Instances of Nodes",
            ),
            _node_action(
                "start",
                "yd-compute-start",
                "Start the stopped Instances of Nodes",
                "starting the stopped Instances of Nodes",
            ),
            _node_action(
                "terminate",
                "yd-terminate",
                "Terminate the Instances of Nodes",
                "terminating the Instances of Nodes",
            ),
            _node_action(
                "restart",
                "yd-compute-restart",
                "Restart the Instances of Nodes",
                "restarting the Instances of Nodes",
            ),
            _node_action(
                "deprovision",
                "yd-compute-deprovision",
                "Deprovision the Instances of Nodes, reducing their Compute"
                " Requirements' target counts",
                "deprovisioning the Instances of Nodes: terminating them and"
                " reducing their Compute Requirements' target counts to match",
            ),
            _list(ET_NODES, "Nodes"),
            _show("Nodes", _NODE_TARGETS, _NODE_DESCRIBED),
        ),
    ),
    Noun(
        "worker",
        "Inspect Workers",
        (
            _list(ET_WORKERS, "Workers"),
            _show("Workers", _ids(YDIDType.WORKER), "worker-ID"),
        ),
    ),
    Noun(
        "resource",
        "Create, remove and inspect resources: templates, keyrings, users and the rest",
        (
            Verb(
                "create",
                "yd-create",
                "Create and update resources",
                "creating and updating resources",
            ),
            Verb("remove", "yd-remove", "Remove resources", "removing resources"),
            Verb(
                "list",
                "yd-list",
                "List resources of a type",
                "listing resources",
                hidden=("--active-only", "--status", "--public-ips-only"),
                overrides={
                    "entity_type": {
                        "help": "the type of resource to list: "
                        + ", ".join(sorted(RESOURCE_LIST_TYPES))
                        + "; an unambiguous prefix (e.g. 'key') is accepted"
                    }
                },
                validators=(_check_resource_type,),
            ),
            _show(
                "resources",
                frozenset(RESOURCE_YDID_TYPES),
                "resource-ID",
                keep=("--show-members",),
            ),
        ),
    ),
    Noun(
        "allowance",
        "Boost and inspect Allowances",
        (
            Verb("boost", "yd-boost", "Boost Allowances", "boosting Allowances"),
            _list(ET_ALLOWANCES, "Allowances"),
            _show("Allowances", _ids(YDIDType.ALLOWANCE), "allowance-ID"),
        ),
    ),
    Noun(
        "data",
        "Transfer, list and delete files in a remote data client location",
        (
            Verb(
                "upload",
                "yd-upload",
                "Upload files to a remote data client",
                "uploading files to a remote data client",
            ),
            Verb(
                "download",
                "yd-download",
                "Download files from a remote data client",
                "downloading files from a remote data client",
            ),
            Verb(
                "ls",
                "yd-ls",
                "List remote data client files and directories",
                "listing remote data client files and directories",
            ),
            Verb(
                "delete",
                "yd-delete",
                "Delete remote data client files and directories",
                "deleting remote data client files and directories",
            ),
            Verb(
                "copy",
                "yd-copy",
                "Copy files between remote data client locations",
                "copying files between remote data client locations",
            ),
        ),
    ),
    Noun(
        "cloudinfo",
        "List cloud regions, instance types and prices",
        (
            _cloud_info("regions", CI_REGIONS, "List cloud regions"),
            _cloud_info("sub-regions", CI_SUB_REGIONS, "List cloud sub-regions"),
            _cloud_info("instance-types", CI_INSTANCE_TYPES, "List instance types"),
            _cloud_info("prices", CI_PRICES, "List instance prices"),
        ),
    ),
)


# --- The derived commands --------------------------------------------------


def _check_targets(targets: Targets) -> Validator:
    """
    A validator holding a verb's targets to its kinds, naming what each
    refused one is.
    """

    def check(args: Namespace, parser: ArgumentParser) -> None:
        values = getattr(args, targets.dest, None)
        if values is None:
            return
        for value in [values] if isinstance(values, str) else values:
            kind = target_kind(value)
            if kind not in targets.kinds:
                parser.error(
                    f"'{value}' is {kind_description(kind)}; {parser.prog} takes"
                    f" <{targets.described}>"
                )

    return check


def _check_hidden(dests: dict[str, str]) -> Validator:
    """
    A validator refusing a hidden option given a value: a script must not
    take an option that does not apply to the object for one that did.
    """

    def check(args: Namespace, parser: ArgumentParser) -> None:
        for dest, flag in dests.items():
            if getattr(args, dest, None) != _parsed_default(parser, dest):
                parser.error(f"{flag} does not apply to {parser.prog}")

    return check


def _parsed_default(parser: ArgumentParser, dest: str) -> Any:
    """
    An option's default as parsing leaves it: argparse converts a string
    default with the option's type, so the raw default would never match.
    """
    default = parser.get_default(dest)
    for action in parser._actions:
        if action.dest == dest and isinstance(default, str) and action.type:
            return action.type(default)  # type: ignore[operator]
    return default


def _dest(option: Option) -> str:
    if "dest" in option.kwargs:
        return option.kwargs["dest"]
    if option.positional:
        return option.flags[0]
    return option.name[2:].replace("-", "_")


def _derived_option(option: Option, verb: Verb) -> Option:
    overrides = dict(verb.overrides.get(option.name, {}))
    if option.name in verb.hidden or option.name in verb.fixed_options:
        overrides["help"] = SUPPRESS
    return option.variant(**overrides) if overrides else option


def derive_command(noun: Noun, verb: Verb) -> Command:
    """
    The Command a noun and verb stand for: the registry command it runs,
    renamed, its options narrowed to the object.
    """
    base = COMMANDS[verb.command]
    name = f"yd {noun.name} {verb.name}"
    for option_name in (*verb.hidden, *verb.fixed_options, *verb.overrides):
        # The selection options are hidden from every by-ID compute action,
        # whether or not its command has them all
        if option_name in _SELECTION_OPTIONS:
            continue
        if base.option_named(option_name) is None:
            raise ValueError(f"{name}: {verb.command} has no option {option_name}")
    options: list[Option | Exclusive] = []
    for item in base.options:
        if isinstance(item, Exclusive):
            options.append(
                Exclusive(tuple(_derived_option(o, verb) for o in item.options))
            )
        else:
            options.append(_derived_option(item, verb))
    # The verb's own checks come first, before a registry validator acts on
    # (or changes) a value the verb does not offer
    validators: list[Validator] = []
    hidden = {
        _dest(option): option.name
        for option in base.flat_options()
        if option.name in verb.hidden
    }
    if hidden:
        validators.append(_check_hidden(hidden))
    if verb.targets is not None:
        validators.append(_check_targets(verb.targets))
    validators.extend(verb.validators)
    validators.extend(base.validators)
    return replace(
        base,
        name=name,
        purpose=verb.purpose,
        summary=verb.summary,
        options=tuple(options),
        validators=tuple(validators),
        runs=verb.command,
    )


NOUNS_BY_NAME: dict[str, Noun] = {
    invoked: noun for noun in NOUNS for invoked in noun.invoked_names()
}

NOUN_COMMANDS: dict[str, Command] = {
    f"yd {noun.name} {verb.name}": derive_command(noun, verb)
    for noun in NOUNS
    for verb in noun.verbs
}


def noun_forms(command_name: str) -> list[str]:
    """
    The noun forms that run a registry command: 'yd-terminate' is
    'yd computerequirement terminate', 'yd instance terminate' and
    'yd node terminate'.
    """
    return [
        f"yd {noun.name} {verb.name}"
        for noun in NOUNS
        for verb in noun.verbs
        if verb.command == command_name
    ]


# The registry commands the noun verbs replace, each with its noun forms
# (every deprecated script, these included, is top_level.SCRIPT_FORMS)
REPLACED_BY_VERBS: dict[str, list[str]] = {
    name: noun_forms(name)
    for name in COMMANDS
    if name not in GENERIC_COMMANDS and noun_forms(name)
}


def noun_module(noun: Noun) -> str:
    """
    The module that runs a noun's verbs: 'python -m' it with the verb first.
    """
    return f"yellowdog_cli.nouns.{noun.name}"


def command_named(name: str) -> Command | None:
    """
    A registry command, or a noun verb's derived command, by any name it is
    given: 'yd-submit', 'yd workrequirement submit', 'yd wr submit', or the
    'yd' form of a registry command no verb replaces ('yd list' is yd-list;
    'yd submit' is nothing, as 'yd' refuses it).
    """
    words = name.split(" ")
    if words[0] != "yd" or len(words) < 2:
        return COMMANDS.get(name) or NOUN_COMMANDS.get(name)
    noun = NOUNS_BY_NAME.get(words[1])
    if noun is not None:
        if len(words) != 3:
            return None
        return NOUN_COMMANDS.get(f"yd {noun.name} {words[2]}")
    registry_name = f"yd-{words[1]}"
    if len(words) != 2 or registry_name in REPLACED_BY_VERBS:
        return None
    return COMMANDS.get(registry_name)


def module_invocation(command: str) -> tuple[str, list[str]] | None:
    """
    The module 'python -m' runs for a command, and the arguments that come
    first. A 'yd' command ('yd wr submit', 'yd list') runs the 'yd'
    dispatcher with its words, so it is shown as typed and refused as 'yd'
    refuses it; a 'yd-*' name runs its own module, as its script would, or
    the dispatcher, which reports it, when this installation has no such
    command. None for anything else.
    """
    words = command.split(" ")
    if words[0] == "yd":
        return "yellowdog_cli.yd", words[1:]
    if len(words) != 1 or not command.startswith("yd-"):
        return None
    module = command_module(command)
    return ("yellowdog_cli.yd", [command]) if module is None else (module, [])


def typed_command(words: list[str]) -> list[str] | None:
    """
    A typed command line with its command as one word, its arguments after:
    'yd wr submit -y' is ['yd wr submit', '-y'] and 'yd list wr' ['yd list',
    'wr']. A 'yd' word not known is kept as a command, for the CLI to
    report; a 'yd-*' name is as typed; None for a line that is not the
    CLI's.
    """
    if not words:
        return None
    if words[0].startswith("yd-"):
        return list(words)
    if words[0] != "yd":
        return None
    if len(words) == 1:
        return ["yd"]
    noun = NOUNS_BY_NAME.get(words[1])
    if noun is not None and len(words) > 2 and noun.verb(words[2]) is not None:
        return [" ".join(words[:3]), *words[3:]]
    return [" ".join(words[:2]), *words[2:]]
