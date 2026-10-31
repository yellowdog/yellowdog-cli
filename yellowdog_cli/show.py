#!/usr/bin/env python3

"""
Command to show the JSON details of YellowDog entities via their IDs.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from sys import exit as sys_exit
from typing import Any, cast

from yellowdog_client.model import (
    ComputeRequirement,
    ConfiguredWorkerPool,
    NamespaceSearch,
    ProvisionedWorkerPool,
)

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    RESOURCE_PROPERTY_NAME,
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
    RN_ROLE,
    RN_SOURCE_TEMPLATE,
    RN_STRING_ATTRIBUTE_DEFINITION,
)
from yellowdog_cli.utils.entity_utils import (
    get_application_group_summaries,
    get_application_id_by_name,
    get_compute_requirement_template_id_by_name,
    get_compute_source_template_id_by_name,
    get_group_applications,
    get_group_id_by_name,
    get_group_users,
    get_instance_by_id,
    get_keyring_summary_by_name,
    get_role_groups,
    get_user_attribute_definitions,
    get_user_by_name_or_id,
    get_user_groups,
    get_worker_pool_id_by_name,
    split_namespace_and_name,
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
from yellowdog_cli.utils.failure_advice import advise
from yellowdog_cli.utils.misc_utils import is_http_not_found
from yellowdog_cli.utils.named_targets import is_pattern, resolve_targets
from yellowdog_cli.utils.printing import (
    counted,
    print_error,
    print_info,
    print_to_file,
    print_warning,
    print_yd_object,
)
from yellowdog_cli.utils.property_names import PROP_GROUPS, PROP_KEYRING_NAME
from yellowdog_cli.utils.resource_targets import SHOWN_WITHOUT_ID
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

_LOG = logging.getLogger(__name__)

# An object to be shown, paired with any additional fields to add to its JSON
# representation. A single YellowDog ID can yield more than one: a Configured
# Worker Pool shown with '--show-token' yields the pool and its token, and a
# Compute Requirement (or a Provisioned Worker Pool) shown with
# '--show-source-report' or '--show-exhaustion' yields those reports after it,
# and a Group or Role with '--show-members' its members.
ShowItem = tuple[Any, dict | None]


@main_wrapper
def main(ctx: RunContext):
    # At least one ID is required, and '--substitute-ids' refused where no ID
    # can use it, as the command line is parsed
    # A noun verb's names are looked up first, every one before any is shown,
    # and its name patterns matched
    targets = resolve_targets(ctx, ctx.args.yellowdog_ids, ctx.args.named_target_type)
    # A pattern asks for many, so is shown as an array however many it matched
    many = ctx.args.named_target_type is not None and any(
        is_pattern(target) for target in ctx.args.yellowdog_ids
    )
    if exit_code := show_ydids(ctx, targets, many=many):
        sys_exit(exit_code)


@dataclass
class _Tally:
    """
    The exit code of each ID not shown: why it was not.
    """

    codes: list[ExitCode] = field(default_factory=list)


_TALLY = _Tally()


def _report_failure(message: str, code: ExitCode) -> None:
    print_error(message)
    _TALLY.codes.append(code)


def _report_not_found(message: str) -> None:
    _report_failure(message, ExitCode.NOT_FOUND)


def show_ydids(ctx: RunContext, ydids: list[str], many: bool = False) -> int:
    """
    Resolve and print the details of each of the supplied YellowDog IDs, and
    return the exit code: 0 if all were shown; the one cause's code if
    those that were not all failed for the same reason (6 NOT_FOUND, 5
    PERMISSION); 1 otherwise. The IDs that were resolved are
    printed whatever the code. A failure every later lookup would repeat
    (authentication, connection) stops the run: what was resolved is printed
    and the failure raised with its own exit code.
    """
    if ctx.args.strip_ids:
        _LOG.debug("Stripping YellowDog IDs (etc.) from detailed JSON objects")

    _TALLY.codes.clear()
    items: list[ShowItem] = []
    failures = 0
    # Whenever more than one object is to be printed, it's printed as a JSON
    # array. More than one ID asked for is enough on its own, so that the shape
    # of the output follows the request rather than how much of it succeeded;
    # a single ID can also yield more than one object: a Configured Worker
    # Pool with '--show-token', or a Compute Requirement or Provisioned Worker
    # Pool with '--show-source-report' or '--show-exhaustion'. 'many' says the
    # request was for any number (a name pattern), whatever it found.
    as_json_array = many or len(ydids) > 1
    resource_type = ctx.args.resource_type
    for index, ydid in enumerate(ydids):
        try:
            if resource_type in SHOWN_WITHOUT_ID:
                # A name of a type with no ID: fetched by it
                shown = _without_id(ctx, cast(str, resource_type), ydid)
                if shown is None:  # The reason has already been reported
                    failures += 1
                else:
                    items += shown
                continue
            if resource_type is not None and get_ydid_type(ydid) is None:
                # A name, with '--type': shown as its ID is
                found = _named_id(ctx, resource_type, ydid)
                if found is None:  # The reason has already been reported
                    failures += 1
                    continue
                ydid = found
            resolved = resolve_details(ctx, ydid)
        except Exception as e:  # Re-raised by the resolvers only if SESSION_FAILURES
            print_error(f"Unable to show details for '{ydid}': {e}")
            advise(e)
            if remaining := len(ydids) - index - 1:
                print_warning(
                    f"Not attempting the remaining {counted(remaining, 'ID')}, which would"
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
    codes = set(_TALLY.codes)
    # Each failure's cause recorded, and every one the same
    if len(_TALLY.codes) == failures and len(codes) == 1:
        return codes.pop()
    return ExitCode.FAILURE


def _named_id(ctx: RunContext, resource_type: str, name: str) -> str | None:
    """
    The ID a name of the type stands for, or None having reported why there
    is none: nothing has the name (not found), or the lookup failed for this
    name alone (an ambiguous name, a refused search). A session failure is
    raised, as it is for an ID, to stop the run.
    """
    try:
        found = _id_for_name(ctx, resource_type, name)
    except Exception as e:
        code = classify(e)
        if code in SESSION_FAILURES:
            raise
        _report_failure(f"Unable to find {resource_type} '{name}': {e}", code)
        advise(e)
        return None
    if found is None:
        _report_not_found(f"Cannot find {resource_type} '{name}'")
    return found


def _without_id(
    ctx: RunContext, resource_type: str, name: str
) -> list[ShowItem] | None:
    """
    A resource of a type with no ID, found by its name, or None having
    reported why not, as _named_id() reports it.
    """
    try:
        found = _shown_without_id(ctx, resource_type, name)
    except Exception as e:
        code = classify(e)
        if code in SESSION_FAILURES:
            raise
        _report_failure(f"Unable to find {resource_type} '{name}': {e}", code)
        advise(e)
        return None
    if found is None:
        _report_not_found(f"Cannot find {resource_type} '{name}'")
        return None
    return [found]


def _shown_without_id(
    ctx: RunContext, resource_type: str, name: str
) -> ShowItem | None:
    """
    The resource of a type with no ID that has the name, as 'yd resource
    list --details' shows it, with 'resource' added, or None: a Namespace by
    its name, a Namespace Policy by its namespace, an Attribute Definition of
    the type by its name, a Credential as 'keyring/credential' (shown as its
    Keyring holds it, with 'keyringName' added). The types are
    resource_targets.SHOWN_WITHOUT_ID's.
    """
    client = ctx.client
    added = {RESOURCE_PROPERTY_NAME: resource_type}
    if resource_type == RN_NAMESPACE:
        namespaces = client.namespaces_client.get_namespaces(
            NamespaceSearch(namespaceContains=name)
        ).list_all()
        found = next((ns for ns in namespaces if ns.namespace == name), None)
        return None if found is None else (found, added)
    if resource_type == RN_NAMESPACE_POLICY:
        try:
            return (
                client.namespaces_client.get_namespace_policy(namespace=name),
                added,
            )
        except Exception as e:
            if is_http_not_found(e):
                return None
            raise
    if resource_type in (
        RN_STRING_ATTRIBUTE_DEFINITION,
        RN_NUMERIC_ATTRIBUTE_DEFINITION,
    ):
        for definition in get_user_attribute_definitions(ctx.config):
            numeric = "Numeric" in str(definition.get("type", ""))
            definition_type = (
                RN_NUMERIC_ATTRIBUTE_DEFINITION
                if numeric
                else RN_STRING_ATTRIBUTE_DEFINITION
            )
            if definition.get("name") == name and definition_type == resource_type:
                return (definition, added)
        return None
    if resource_type == RN_CREDENTIAL:
        keyring_name, _, credential_name = name.partition("/")
        summary = get_keyring_summary_by_name(client, keyring_name)
        if summary is None:
            return None
        keyring = client.keyring_client.get_keyring(cast(str, summary.id))
        credential = next(
            (c for c in keyring.credentials or [] if c.name == credential_name), None
        )
        if credential is None:
            return None
        return (credential, {**added, PROP_KEYRING_NAME: keyring_name})
    raise ValueError(f"a {resource_type} cannot be shown without an ID")


def _id_for_name(ctx: RunContext, resource_type: str, name: str) -> str | None:
    """
    The ID of the resource of the type with the name, found as the commands
    acting on one find it, or None: 'namespace/name' for a namespaced type,
    the configured namespace without one; a User by its name or username.
    The types are resource_targets.SHOWN_BY_NAME's.
    """
    client, namespace = ctx.client, ctx.config.namespace
    match resource_type:
        case _ if resource_type == RN_KEYRING:
            summary = get_keyring_summary_by_name(client, name)
            return None if summary is None else summary.id
        case _ if resource_type == RN_SOURCE_TEMPLATE:
            return get_compute_source_template_id_by_name(client, name, namespace)
        case _ if resource_type == RN_REQUIREMENT_TEMPLATE:
            return get_compute_requirement_template_id_by_name(client, name, namespace)
        case _ if resource_type == RN_CONFIGURED_POOL:
            return get_worker_pool_id_by_name(client, name, namespace)
        case _ if resource_type == RN_GROUP:
            return get_group_id_by_name(client, name)
        case _ if resource_type == RN_APPLICATION:
            return get_application_id_by_name(client, name)
        case _ if resource_type == RN_IMAGE_FAMILY:
            family_namespace, family_name = split_namespace_and_name(name)
            try:
                return client.images_client.get_image_family_by_name(
                    namespace=family_namespace or namespace,
                    family_name=family_name or name,
                ).id
            except Exception as e:
                if is_http_not_found(e):
                    return None
                raise
        case _ if resource_type in (RN_INTERNAL_USER, RN_EXTERNAL_USER):
            user = get_user_by_name_or_id(client, name)
            return None if user is None else user.id
    raise ValueError(f"a {resource_type} cannot be shown by name")


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

    Resolution is deliberately separated from printing: threaded through each
    entity type's branch, the JSON array's indentation and commas would be
    applied to some of them and forgotten on the rest, leaving the array
    unparseable. Each type's resolution is an entry in _RESOLVERS.
    """
    # Instances have no YDID of their own: they're identified by their Compute
    # Requirement plus an instance ID, in 'cr_id.instance_id' form
    if (cr_id_instance_id := split_instance_specification(ydid)) is not None:
        return _resolve_instance_details(
            ctx, cr_id_instance_id[0], cr_id_instance_id[1]
        )

    if (ydid_type := get_ydid_type(ydid)) is None:
        _report_failure(f"Invalid YellowDog ID '{ydid}'", ExitCode.FAILURE)
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
            _report_failure(f"Unable to show details for '{ydid}': {e}", classify(e))
            advise(e)
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
        _LOG.debug("Substituting Image Family ID with name")
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
        _LOG.debug(
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
        _LOG.debug("Checking Allowance exhaustion for '%s'", cr_id)
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
        _LOG.debug("Substituting ID with name")
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
    # Its groups by name, as for an Application and 'yd-list users
    # --details': a User specification takes them, so the JSON can still be
    # given to yd-create
    user = ctx.client.account_client.get_user(ydid)
    group_names = [group.name for group in get_user_groups(ctx.client, ydid)]
    return [
        (
            user,
            {PROP_GROUPS: group_names, RESOURCE_PROPERTY_NAME: user.__class__.__name__},
        )
    ]


def _group(ctx: RunContext, ydid: str) -> list[ShowItem]:
    items: list[ShowItem] = [
        (ctx.client.account_client.get_group(ydid), {RESOURCE_PROPERTY_NAME: RN_GROUP})
    ]
    if ctx.args.show_members:
        print_info(f"Showing members of Group '{ydid}'")
        items.append(
            (
                {
                    "groupId": ydid,
                    "users": [
                        {
                            "id": user.id,
                            # An external User has no username
                            "username": getattr(user, "username", None),
                            "name": user.name,
                        }
                        for user in get_group_users(ctx.client, ydid)
                    ],
                    "applications": [
                        _named(application.id, application.name)
                        for application in get_group_applications(ctx.client, ydid)
                    ],
                },
                None,
            )
        )
    return items


def _role(ctx: RunContext, ydid: str) -> list[ShowItem]:
    items: list[ShowItem] = [
        (ctx.client.account_client.get_role(ydid), {RESOURCE_PROPERTY_NAME: RN_ROLE})
    ]
    if ctx.args.show_members:
        print_info(f"Showing Groups holding Role '{ydid}'")
        items.append(
            (
                {
                    "roleId": ydid,
                    "groups": [
                        _named(group.id, group.name)
                        for group in get_role_groups(ctx.client, ydid)
                    ],
                },
                None,
            )
        )
    return items


def _named(id_: str | None, name: str | None) -> dict:
    return {"id": id_, "name": name}


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
    YDIDType.GROUP: _Resolver("Group", _group),
    YDIDType.ROLE: _Resolver("Role", _role),
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
            _report_failure(
                f"Unable to find Compute Requirement ID '{cr_id}': {e}", classify(e)
            )
            advise(e)
        return None

    try:
        instance = get_instance_by_id(ctx.client, cr_id, instance_id)
    except Exception as e:
        if classify(e) in SESSION_FAILURES:
            raise  # For show_ydids(), which stops
        _report_failure(
            f"Unable to show details for '{cr_id}.{instance_id}': {e}", classify(e)
        )
        advise(e)
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
