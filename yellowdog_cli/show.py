#!/usr/bin/env python3

"""
Command to show the JSON details of YellowDog entities via their IDs.
"""

from collections.abc import Callable
from dataclasses import dataclass
from sys import exit as sys_exit
from typing import Any, cast

from yellowdog_client.model import (
    ComputeRequirement,
    ConfiguredWorkerPool,
    ProvisionedWorkerPool,
)

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    RESOURCE_PROPERTY_NAME,
    RN_ALLOWANCE,
    RN_APPLICATION,
    RN_CONFIGURED_POOL,
    RN_GROUP,
    RN_IMAGE_FAMILY,
    RN_KEYRING,
    RN_REQUIREMENT_TEMPLATE,
    RN_ROLE,
    RN_SOURCE_TEMPLATE,
)
from yellowdog_cli.utils.entity_utils import (
    get_application_group_summaries,
    get_instance_by_id,
    substitute_id_for_name_in_allowance,
    substitute_ids_for_names_in_crt,
    substitute_image_family_id_for_name_in_cst,
)
from yellowdog_cli.utils.exit_codes import (
    SESSION_FAILURES,
    ExitCode,
    NotFoundError,
    ReportedFailure,
    classify,
)
from yellowdog_cli.utils.misc_utils import is_http_not_found
from yellowdog_cli.utils.printing import (
    print_error,
    print_info,
    print_to_file,
    print_warning,
    print_yd_object,
)
from yellowdog_cli.utils.property_names import PROP_GROUPS
from yellowdog_cli.utils.wrapper import main_wrapper
from yellowdog_cli.utils.ydid_utils import (
    TYPE_COMPREQ,
    TYPE_COMPSRC,
    TYPE_NODE,
    TYPE_WRKR,
    YDIDType,
    get_ydid_type,
    split_instance_specification,
    work_requirement_id_of_task_group,
)

# An object to be shown, paired with any additional fields to add to its JSON
# representation. A single YellowDog ID can yield more than one: a Configured
# Worker Pool shown with '--show-token' yields the pool and its token, and a
# Compute Requirement (or a Provisioned Worker Pool) shown with
# '--show-source-report' or '--show-exhaustion' yields those reports after it.
ShowItem = tuple[Any, dict | None]


@main_wrapper
def main(ctx: RunContext):
    # At least one ID is required, and '--substitute-ids' refused where no ID
    # can use it, as the command line is parsed
    if exit_code := show_ydids(ctx, ctx.args.yellowdog_ids):
        sys_exit(exit_code)


@dataclass
class _Tally:
    """
    The IDs not shown because their entity does not exist.
    """

    not_found: int = 0


_TALLY = _Tally()


def _report_not_found(message: str) -> None:
    print_error(message)
    _TALLY.not_found += 1


def show_ydids(ctx: RunContext, ydids: list[str]) -> int:
    """
    Resolve and print the details of each of the supplied YellowDog IDs, and
    return the exit code: 0 if all were shown; 6 (NOT_FOUND) if those that
    were not all named nothing; 1 otherwise. The IDs that were resolved are
    printed whatever the code. A failure every later lookup would repeat
    (authentication, connection) stops the run: what was resolved is printed
    and the failure raised with its own exit code.
    """
    if ctx.args.strip_ids:
        print_info("Stripping YellowDog IDs (etc.) from detailed JSON objects")

    _TALLY.not_found = 0
    items: list[ShowItem] = []
    failures = 0
    # Whenever more than one object is to be printed, it's printed as a JSON
    # array. More than one ID asked for is enough on its own, so that the shape
    # of the output follows the request rather than how much of it succeeded;
    # a single ID can also yield more than one object: a Configured Worker
    # Pool with '--show-token', or a Compute Requirement or Provisioned Worker
    # Pool with '--show-source-report' or '--show-exhaustion'.
    as_json_array = len(ydids) > 1
    for index, ydid in enumerate(ydids):
        try:
            resolved = resolve_details(ctx, ydid)
        except Exception as e:  # Re-raised by the resolvers only if SESSION_FAILURES
            print_error(f"Unable to show details for '{ydid}': {e}")
            if remaining := len(ydids) - index - 1:
                print_warning(
                    f"Not attempting the remaining {remaining} ID(s), which would"
                    " fail in the same way"
                )
            _print_items(ctx, items, as_json_array=as_json_array or len(items) > 1)
            raise ReportedFailure(e)
        if resolved is None:  # The reason has already been reported
            failures += 1
            continue
        items += resolved

    _print_items(ctx, items, as_json_array=as_json_array or len(items) > 1)

    if not failures:
        return ExitCode.SUCCESS
    return ExitCode.NOT_FOUND if _TALLY.not_found == failures else ExitCode.FAILURE


def _print_items(ctx: RunContext, items: list[ShowItem], as_json_array: bool):
    """
    Print the resolved objects, framing them as a JSON array if required.
    This is the only place the array's indentation and its separating commas
    are applied.
    """
    if as_json_array:
        print("[")
        if ctx.args.output_file is not None:
            print_to_file("[", ctx.args.output_file)

    for index, (yd_object, add_fields) in enumerate(items):
        print_yd_object(
            yd_object,
            initial_indent=2 if as_json_array else 0,
            with_final_comma=as_json_array and index < len(items) - 1,
            add_fields=add_fields,
        )

    if as_json_array:
        print("]")
        if ctx.args.output_file is not None:
            print_to_file("]", ctx.args.output_file)


def resolve_details(ctx: RunContext, ydid: str) -> list[ShowItem] | None:
    """
    Resolve a YellowDog ID to the object(s) to be shown. Returns None if the ID
    could not be resolved, having already reported why.

    Resolution is deliberately separated from printing: the JSON array's
    indentation and commas were previously threaded through each entity type's
    branch, applied to some of them and forgotten on the rest, which left the
    array unparseable for most entity types. Each type's resolution is now an
    entry in _RESOLVERS.
    """
    # Instances have no YDID of their own: they're identified by their Compute
    # Requirement plus an instance ID, in 'cr_id.instance_id' form
    if (cr_id_instance_id := split_instance_specification(ydid)) is not None:
        return _resolve_instance_details(
            ctx, cr_id_instance_id[0], cr_id_instance_id[1]
        )

    if (ydid_type := get_ydid_type(ydid)) is None:
        print_error(f"Invalid YellowDog ID '{ydid}'")
        return None

    resolver = _RESOLVERS[ydid_type]
    print_info(f"Showing details of {resolver.noun} ID '{ydid}'")
    try:
        return resolver.resolve(ctx, ydid)
    except Exception as e:
        if classify(e) in SESSION_FAILURES:
            raise  # For show_ydids(), which stops
        if is_http_not_found(e) or isinstance(e, NotFoundError):
            _report_not_found(f"{ydid_type.value} ID '{ydid}' not found")
        else:
            print_error(f"Unable to show details for '{ydid}': {e}")
        return None


# A resolver returns the object(s) a YellowDog ID names, raising if there are
# none
_Resolve = Callable[[RunContext, str], list[ShowItem]]


@dataclass(frozen=True)
class _Resolver:
    """
    How one YellowDog ID type is resolved, and what its progress message calls
    the entity.
    """

    noun: str
    resolve: _Resolve


def _fetched(get: Callable[[Any, str], Any], resource: str | None = None) -> _Resolve:
    """
    A resolver for an entity fetched by its own ID, with the 'resource'
    property added to its JSON where it can be created from that.
    """

    def resolve(ctx: RunContext, ydid: str) -> list[ShowItem]:
        return [
            (
                get(ctx.client, ydid),
                {RESOURCE_PROPERTY_NAME: resource} if resource is not None else None,
            )
        ]

    return resolve


def _member_of(
    get_parent: Callable[[Any, str], Any], members: Callable[[Any], list | None]
) -> _Resolve:
    """
    A resolver for an entity with no lookup of its own, found by ID among the
    members of the parent it belongs to.
    """

    def resolve(ctx: RunContext, ydid: str) -> list[ShowItem]:
        for member in members(get_parent(ctx.client, ydid)) or []:
            if member.id == ydid:
                return [(member, None)]
        raise NotFoundError(ydid)

    return resolve


def _compute_source_template(ctx: RunContext, ydid: str) -> list[ShowItem]:
    if ctx.args.substitute_ids:
        print_info("Substituting Image Family ID with name")
    return [
        (
            substitute_image_family_id_for_name_in_cst(
                ctx.client,
                ctx.client.compute_client.get_compute_source_template(ydid),
                substitute=bool(ctx.args.substitute_ids),
            ),
            {RESOURCE_PROPERTY_NAME: RN_SOURCE_TEMPLATE},
        )
    ]


def _compute_requirement_template(ctx: RunContext, ydid: str) -> list[ShowItem]:
    if ctx.args.substitute_ids:
        print_info(
            "Substituting Compute Source Template IDs and Image Family IDs with names"
        )
    return [
        (
            substitute_ids_for_names_in_crt(
                ctx.client,
                ctx.client.compute_client.get_compute_requirement_template(ydid),
                substitute=bool(ctx.args.substitute_ids),
            ),
            {RESOURCE_PROPERTY_NAME: RN_REQUIREMENT_TEMPLATE},
        )
    ]


def _worker_pool(ctx: RunContext, ydid: str) -> list[ShowItem]:
    worker_pool = ctx.client.worker_pool_client.get_worker_pool_by_id(ydid)
    configured = isinstance(worker_pool, ConfiguredWorkerPool)
    items: list[ShowItem] = [
        (
            worker_pool,
            {RESOURCE_PROPERTY_NAME: RN_CONFIGURED_POOL} if configured else {},
        )
    ]
    if ctx.args.show_token and configured:
        print_info("Showing Configured Worker Pool token data")
        items.append(
            (
                ctx.client.worker_pool_client.get_configured_worker_pool_token_by_id(
                    ydid
                ),
                None,
            )
        )
    if _diagnostics_requested(ctx):
        if isinstance(worker_pool, ProvisionedWorkerPool):
            items += _diagnostics(
                ctx,
                ctx.client.compute_client.get_compute_requirement_by_id(
                    cast(str, worker_pool.computeRequirementId)
                ),
            )
        else:
            print_warning(
                f"Worker Pool '{ydid}' is not a Provisioned Worker Pool, so has"
                " no Compute Requirement to report on"
            )
    return items


def _compute_requirement(ctx: RunContext, ydid: str) -> list[ShowItem]:
    compute_requirement = ctx.client.compute_client.get_compute_requirement_by_id(ydid)
    return [(compute_requirement, None), *_diagnostics(ctx, compute_requirement)]


def _diagnostics_requested(ctx: RunContext) -> bool:
    return bool(ctx.args.show_source_report or ctx.args.show_exhaustion)


def _diagnostics(
    ctx: RunContext, compute_requirement: ComputeRequirement
) -> list[ShowItem]:
    """
    The reports asked for on a Compute Requirement: how its sources were
    chosen ('--show-source-report'), and the Allowances exhausted for it
    ('--show-exhaustion'). A report the Platform does not have is warned of
    and left out, so that the Compute Requirement is still shown; any other
    failure is raised, failing the ID.
    """
    items: list[ShowItem] = []
    cr_id = cast(str, compute_requirement.id)
    if ctx.args.show_source_report:
        print_info(f"Showing source report for '{cr_id}'")
        try:
            items.append(
                (
                    ctx.client.compute_client.get_best_compute_source_report_by_compute_requirement(
                        cr_id
                    ),
                    None,
                )
            )
        except Exception as e:
            if not is_http_not_found(e):
                raise
            print_warning(
                f"No source report for '{cr_id}': only a Compute"
                " Requirement provisioned from a dynamic template has one"
            )
    if ctx.args.show_exhaustion:
        print_info(f"Checking Allowance exhaustion for '{cr_id}'")
        notifications = (
            ctx.client.allowances_client.check_compute_requirement_exhaustion(
                compute_requirement
            )
        )
        items.append(
            (
                {
                    "computeRequirementId": cr_id,
                    "exhaustedAllowances": notifications or [],
                },
                None,
            )
        )
    return items


def _allowance(ctx: RunContext, ydid: str) -> list[ShowItem]:
    allowance = ctx.client.allowances_client.get_allowance_by_id(ydid)
    if ctx.args.substitute_ids:
        print_info("Substituting ID with name")
        allowance = substitute_id_for_name_in_allowance(
            ctx.client,
            allowance,  # type: ignore[arg-type]
            substitute=bool(ctx.args.substitute_ids),
        )
    return [(allowance, {RESOURCE_PROPERTY_NAME: RN_ALLOWANCE})]


def _application(ctx: RunContext, ydid: str) -> list[ShowItem]:
    # The Application first, so that one that does not exist is reported as
    # such rather than by its groups' lookup
    application = ctx.client.account_client.get_application(ydid)
    group_names = [
        group.name for group in get_application_group_summaries(ctx.client, ydid)
    ]
    return [
        (
            application,
            {PROP_GROUPS: group_names, RESOURCE_PROPERTY_NAME: RN_APPLICATION},
        )
    ]


def _user(ctx: RunContext, ydid: str) -> list[ShowItem]:
    user = ctx.client.account_client.get_user(ydid)
    return [(user, {RESOURCE_PROPERTY_NAME: user.__class__.__name__})]


# Every YDIDType, held to that by tests/test_show_output.py
_RESOLVERS: dict[YDIDType, _Resolver] = {
    YDIDType.COMPUTE_SOURCE_TEMPLATE: _Resolver(
        "Compute Source Template", _compute_source_template
    ),
    YDIDType.COMPUTE_REQUIREMENT_TEMPLATE: _Resolver(
        "Compute Requirement Template", _compute_requirement_template
    ),
    YDIDType.COMPUTE_REQUIREMENT: _Resolver(
        "Compute Requirement", _compute_requirement
    ),
    YDIDType.COMPUTE_SOURCE: _Resolver(
        "Compute Source",
        _member_of(
            lambda c, ydid: c.compute_client.get_compute_requirement_by_id(
                ydid.rsplit(":", 1)[0].replace(TYPE_COMPSRC, TYPE_COMPREQ)
            ),
            lambda compute_requirement: compute_requirement.provisionStrategy.sources,
        ),
    ),
    YDIDType.WORKER_POOL: _Resolver("Worker Pool", _worker_pool),
    YDIDType.NODE: _Resolver(
        "Node", _fetched(lambda c, ydid: c.worker_pool_client.get_node_by_id(ydid))
    ),
    YDIDType.WORKER: _Resolver(
        "Worker",
        _member_of(
            lambda c, ydid: c.worker_pool_client.get_node_by_id(
                ydid.rsplit(":", 1)[0].replace(TYPE_WRKR, TYPE_NODE)
            ),
            lambda node: node.workers,
        ),
    ),
    YDIDType.WORK_REQUIREMENT: _Resolver(
        "Work Requirement",
        _fetched(lambda c, ydid: c.work_client.get_work_requirement_by_id(ydid)),
    ),
    YDIDType.TASK_GROUP: _Resolver(
        "Task Group",
        _member_of(
            lambda c, ydid: c.work_client.get_work_requirement_by_id(
                work_requirement_id_of_task_group(ydid)
            ),
            lambda work_requirement: work_requirement.taskGroups,
        ),
    ),
    YDIDType.TASK: _Resolver(
        "Task", _fetched(lambda c, ydid: c.work_client.get_task_by_id(ydid))
    ),
    YDIDType.IMAGE_FAMILY: _Resolver(
        "Image Family",
        _fetched(
            lambda c, ydid: c.images_client.get_image_family_by_id(ydid),
            RN_IMAGE_FAMILY,
        ),
    ),
    YDIDType.IMAGE_GROUP: _Resolver(
        "Image Group",
        _fetched(lambda c, ydid: c.images_client.get_image_group_by_id(ydid)),
    ),
    YDIDType.IMAGE: _Resolver(
        "Image", _fetched(lambda c, ydid: c.images_client.get_image(ydid))
    ),
    # The Keyring with its credentials and accessors, in one call
    YDIDType.KEYRING: _Resolver(
        "Keyring",
        _fetched(lambda c, ydid: c.keyring_client.get_keyring(ydid), RN_KEYRING),
    ),
    YDIDType.ALLOWANCE: _Resolver("Allowance", _allowance),
    YDIDType.APPLICATION: _Resolver("Application", _application),
    YDIDType.USER: _Resolver("User", _user),
    YDIDType.GROUP: _Resolver(
        "Group", _fetched(lambda c, ydid: c.account_client.get_group(ydid), RN_GROUP)
    ),
    YDIDType.ROLE: _Resolver(
        "Role", _fetched(lambda c, ydid: c.account_client.get_role(ydid), RN_ROLE)
    ),
}


def _resolve_instance_details(
    ctx: RunContext, cr_id: str, instance_id: str
) -> list[ShowItem] | None:
    """
    Resolve the details of an Instance within a Compute Requirement, supplied
    in 'cr_id.instance_id' form.
    """
    print_info(
        f"Showing details of Instance ID '{instance_id}' in "
        f"Compute Requirement ID '{cr_id}'"
    )

    # Check the Compute Requirement exists first: the Instance search below
    # returns an empty list for a non-existent Compute Requirement, which is
    # indistinguishable from a Compute Requirement without this Instance
    try:
        ctx.client.compute_client.get_compute_requirement_by_id(cr_id)
    except Exception as e:
        if classify(e) in SESSION_FAILURES:
            raise  # For show_ydids(), which stops
        if is_http_not_found(e):
            _report_not_found(f"Compute Requirement ID '{cr_id}' not found")
        else:
            print_error(f"Unable to find Compute Requirement ID '{cr_id}': {e}")
        return None

    try:
        instance = get_instance_by_id(ctx.client, cr_id, instance_id)
    except Exception as e:
        if classify(e) in SESSION_FAILURES:
            raise  # For show_ydids(), which stops
        print_error(f"Unable to show details for '{cr_id}.{instance_id}': {e}")
        return None

    if instance is None:
        _report_not_found(
            f"Instance ID '{instance_id}' not found in Compute Requirement ID '{cr_id}'"
        )
        return None

    return [(instance, None)]


# Entry point
if __name__ == "__main__":
    main()
