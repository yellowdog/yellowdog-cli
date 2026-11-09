"""
The per-type planners of 'yd resource plan', registered in
resource_plan.PLANNERS as this module is imported (resource_plan.plan_one()
imports it). Each prepares the specification as 'yd resource create' would
(resource_creation.py's prepare_*() functions, so the two resolve names
identically), finds the existing resource with the creator's own lookup,
fetches it, and compares the two, changing nothing.
"""

from typing import Any, cast

from requests import get
from requests.exceptions import HTTPError
from yellowdog_client.model import InternalUser, NamespaceSearch

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
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
from yellowdog_cli.utils.entity_utils import (
    allowances_matching_description,
    get_application_group_summaries,
    get_application_id_by_name,
    get_compute_requirement_template_id_by_name,
    get_compute_source_template_id_by_name,
    get_group_id_by_name,
    get_group_name_by_id,
    get_keyring_summary_by_name,
    get_user_groups,
    get_worker_pool_summaries,
    keyring_credential_names,
)
from yellowdog_cli.utils.exit_codes import NotFoundError
from yellowdog_cli.utils.misc_utils import is_http_not_found
from yellowdog_cli.utils.property_names import (
    PROP_AUTOSCALING_MAX_NODES,
    PROP_CST_ID,
    PROP_DESCRIPTION,
    PROP_GROUPS,
    PROP_IMAGE_GROUPS,
    PROP_IMAGES,
    PROP_KEYRINGS,
    PROP_NAME,
    PROP_NAMESPACE,
    PROP_ROLES,
    PROP_SOURCE,
    PROP_SOURCES,
    PROP_TYPE,
)
from yellowdog_cli.utils.resource_creation import (
    RoleSpecification,
    _get_model_object,
    _raise_for_response,
    attribute_definition_endpoint,
    check_keyring_grants,
    prepare_allowance,
    prepare_application,
    prepare_attribute_definition,
    prepare_compute_requirement_template,
    prepare_compute_source_template,
    prepare_credential,
    prepare_group,
    prepare_image_family,
    prepare_keyring,
    prepare_user,
    run_options,
)
from yellowdog_cli.utils.resource_plan import (
    API_KEY,
    API_KEY_REGENERATED,
    PLANNERS,
    Change,
    PlanEntry,
    ToBeCreated,
    comparable,
    path_pattern,
    resource_differences,
)
from yellowdog_cli.utils.resource_processing import missing_property
from yellowdog_cli.utils.settings import NAMESPACE_PREFIX_SEPARATOR


def _compared(
    resource_type: str, name: str, ydid: str | None, before: Any, after: Any
) -> PlanEntry:
    """
    The plan for an existing resource: 'update' with the changes that would
    make 'before' 'after' (comparable() data), else 'unchanged'.
    """
    changes = tuple(resource_differences(resource_type, before, after))
    return PlanEntry(
        resource_type, name, ydid, "update" if changes else "unchanged", changes
    )


def plan_compute_source_template(
    ctx: RunContext,
    resource: dict,
    source_dir: str | None,
    planned: set[tuple[str, str]],
) -> PlanEntry:
    """
    A Compute Source Template, found by its namespace and name. A change of
    Source type is the one change at 'source.type', the Source's other
    properties belonging to a different kind of Source.
    """
    name, template = prepare_compute_source_template(ctx, resource, source_dir)
    template_id = get_compute_source_template_id_by_name(
        ctx.client, name, resource[PROP_NAMESPACE]
    )
    if template_id is None:
        return PlanEntry(RN_SOURCE_TEMPLATE, name, None, "create")

    existing = ctx.client.compute_client.get_compute_source_template(template_id)
    before, after = comparable(existing), comparable(template)
    was = before.get(PROP_SOURCE, {}).get(PROP_TYPE)
    now = after.get(PROP_SOURCE, {}).get(PROP_TYPE)
    if was != now:
        after = {**after, PROP_SOURCE: {**before[PROP_SOURCE], PROP_TYPE: now}}
    return _compared(RN_SOURCE_TEMPLATE, name, template_id, before, after)


def plan_compute_requirement_template(
    ctx: RunContext,
    resource: dict,
    source_dir: str | None,
    planned: set[tuple[str, str]],
) -> PlanEntry:
    """
    A Compute Requirement Template, found by its namespace and name, its
    Sources compared by position. A Source Template an earlier
    specification would create is shown as '(to be created)'.
    """
    name, template, unresolved = prepare_compute_requirement_template(
        ctx, resource, source_dir, planned
    )
    template_id = get_compute_requirement_template_id_by_name(ctx.client, name)
    if template_id is None:
        return PlanEntry(RN_REQUIREMENT_TEMPLATE, name, None, "create")

    existing = ctx.client.compute_client.get_compute_requirement_template_by_id(
        template_id
    )
    after = comparable(template)
    for source in after.get(PROP_SOURCES, []):
        if source.get(PROP_CST_ID) in unresolved:
            source[PROP_CST_ID] = ToBeCreated(source[PROP_CST_ID])
    return _compared(
        RN_REQUIREMENT_TEMPLATE, name, template_id, comparable(existing), after
    )


PLANNERS[RN_SOURCE_TEMPLATE] = plan_compute_source_template
PLANNERS[RN_REQUIREMENT_TEMPLATE] = plan_compute_requirement_template

# The lists of an Image Family 'yd resource create' matches by name
_IMAGE_MEMBERS = frozenset({PROP_IMAGE_GROUPS, f"{PROP_IMAGE_GROUPS}[].{PROP_IMAGES}"})


def _with_member_lists(family: dict) -> dict:
    """
    A comparable() Image Family with its Image Groups, and each group's
    Images, as a list even where it has none, so a group or image on one
    side alone is a member added or removed, never the whole list.
    """
    groups = [
        {**group, PROP_IMAGES: group.get(PROP_IMAGES) or []}
        for group in family.get(PROP_IMAGE_GROUPS) or []
    ]
    return {**family, PROP_IMAGE_GROUPS: groups}


def _member_by_name(change: Change) -> Change:
    """
    An Image Group or Image added or removed, as its name alone: the
    member is created or removed whole, so its name says which. Any other
    change is left as it is.
    """
    if change.kind not in ("added", "removed") or (
        path_pattern(change.path) not in _IMAGE_MEMBERS
    ):
        return change
    before, after = (
        member[PROP_NAME] if isinstance(member, dict) else member
        for member in (change.before, change.after)
    )
    return Change(change.path, before, after, change.kind)


def plan_image_family(
    ctx: RunContext,
    resource: dict,
    source_dir: str | None,
    planned: set[tuple[str, str]],
) -> PlanEntry:
    """
    A Machine Image Family, found by its namespace and name, compared whole:
    its own properties, its Image Groups matched by name and, within each,
    its Images matched by name, as 'yd resource create' matches them. A
    group or image added or removed is shown by its name.
    """
    name, family = prepare_image_family(ctx, resource)
    try:
        existing = ctx.client.images_client.get_image_family_by_name(
            namespace=family.namespace, family_name=family.name
        )
    except HTTPError as e:
        if not is_http_not_found(e):
            raise
        return PlanEntry(RN_IMAGE_FAMILY, name, None, "create")
    changes = tuple(
        _member_by_name(change)
        for change in resource_differences(
            RN_IMAGE_FAMILY,
            _with_member_lists(comparable(existing)),
            _with_member_lists(comparable(family)),
            by_name=_IMAGE_MEMBERS,
        )
    )
    return PlanEntry(
        RN_IMAGE_FAMILY,
        name,
        existing.id,
        "update" if changes else "unchanged",
        changes,
    )


PLANNERS[RN_IMAGE_FAMILY] = plan_image_family


def plan_keyring(
    ctx: RunContext,
    resource: dict,
    source_dir: str | None,
    planned: set[tuple[str, str]],
) -> PlanEntry:
    """
    A Keyring, found by its name; only its description can change.
    """
    name, description = prepare_keyring(resource)
    existing = get_keyring_summary_by_name(ctx.client, name)
    if existing is None:
        return PlanEntry(RN_KEYRING, name, None, "create")
    return _compared(
        RN_KEYRING,
        name,
        cast(str, existing.id),
        {PROP_DESCRIPTION: existing.description},
        {PROP_DESCRIPTION: description},
    )


def plan_credential(
    ctx: RunContext,
    resource: dict,
    source_dir: str | None,
    planned: set[tuple[str, str]],
) -> PlanEntry:
    """
    A Credential, in a Keyring that exists or an earlier specification
    creates, prepared as the real run prepares it (its type and required
    properties checked) and the model discarded. One that exists is
    replaced, its secrets unreadable, so its outcome is unknown; nothing of
    the specification's credential is kept in the plan but its name and its
    Keyring's.
    """
    keyring_name, name, _ = prepare_credential(resource)
    summary = get_keyring_summary_by_name(ctx.client, keyring_name)
    if summary is None:
        if (RN_KEYRING, keyring_name) in planned:
            return PlanEntry(RN_CREDENTIAL, name, None, "create", keyring=keyring_name)
        raise NotFoundError(f"Keyring '{keyring_name}' not found")
    keyring = ctx.client.keyring_client.get_keyring(cast(str, summary.id))
    if name not in keyring_credential_names(keyring):
        return PlanEntry(RN_CREDENTIAL, name, None, "create", keyring=keyring_name)
    return PlanEntry(
        RN_CREDENTIAL,
        name,
        None,
        "unknown",
        reason="its secrets can't be read back, so it would be replaced",
        keyring=keyring_name,
    )


def plan_namespace(
    ctx: RunContext,
    resource: dict,
    source_dir: str | None,
    planned: set[tuple[str, str]],
) -> PlanEntry:
    """
    A Namespace: there already, or to be created.
    """
    try:
        name = resource[PROP_NAME]
    except KeyError as e:
        raise missing_property(e) from e
    found = ctx.client.namespaces_client.get_namespaces(
        NamespaceSearch(namespaceContains=name)
    ).list_all()
    if any(namespace.namespace == name for namespace in found):
        return PlanEntry(RN_NAMESPACE, name, None, "unchanged")
    return PlanEntry(RN_NAMESPACE, name, None, "create")


def plan_namespace_policy(
    ctx: RunContext,
    resource: dict,
    source_dir: str | None,
    planned: set[tuple[str, str]],
) -> PlanEntry:
    """
    A Namespace Policy, found by its namespace; 'autoscalingMaxNodes' is
    what it can change.
    """
    try:
        namespace = resource[PROP_NAMESPACE]
    except KeyError as e:
        raise missing_property(e) from e
    try:
        existing = ctx.client.namespaces_client.get_namespace_policy(
            namespace=namespace
        )
    except Exception as e:
        if not is_http_not_found(e):
            raise
        return PlanEntry(RN_NAMESPACE_POLICY, namespace, None, "create")
    return _compared(
        RN_NAMESPACE_POLICY,
        namespace,
        None,
        comparable(existing),
        {
            PROP_NAMESPACE: namespace,
            PROP_AUTOSCALING_MAX_NODES: resource.get(PROP_AUTOSCALING_MAX_NODES),
        },
    )


# How the Platform lists an Attribute Definition's unset description and
# options (live run ydst-2611091206-mxng)
_LISTED_UNSET: tuple[Any, ...] = ("", [])


def _attribute_properties(definition: dict, payload: dict) -> dict:
    """
    An Attribute Definition's properties that are set, less its 'type' and
    any property not in 'payload' (what the Platform adds to a definition
    is no difference). A value listed as unset ("", []) where the payload
    leaves the property unset is left out like None: the two agree.
    """
    return {
        key: value
        for key, value in definition.items()
        if key != PROP_TYPE
        and key in payload
        and value is not None
        and not (value in _LISTED_UNSET and payload[key] is None)
    }


def plan_attribute_definition(
    ctx: RunContext,
    resource: dict,
    source_dir: str | None,
    planned: set[tuple[str, str]],
    *,
    resource_type: str,
) -> PlanEntry:
    """
    A user Attribute Definition, found by name among those the Platform
    lists, compared with the payload 'yd resource create' would send.
    """
    payload = prepare_attribute_definition(ctx, resource, resource_type)
    name = payload[PROP_NAME]
    url, headers = attribute_definition_endpoint(ctx)
    response = get(url=url, headers=headers, timeout=ctx.config.request_timeout)
    if not response.ok:
        _raise_for_response(response)
    existing = next(
        (
            definition
            for definition in response.json()
            if definition.get(PROP_NAME) == name
        ),
        None,
    )
    if existing is None:
        return PlanEntry(resource_type, name, None, "create")
    # The payload names every property the definition can have, each sent,
    # null where the specification leaves it out, and the Platform clears a
    # property sent as null (a live check: a String Attribute Definition's
    # description and options, PUT as null, read back null): one the
    # existing definition holds and the payload does not is cleared
    return _compared(
        resource_type,
        name,
        None,
        _attribute_properties(existing, payload),
        _attribute_properties(payload, payload),
    )


def _attribute_planner(resource_type: str):
    def planner(
        ctx: RunContext,
        resource: dict,
        source_dir: str | None,
        planned: set[tuple[str, str]],
    ) -> PlanEntry:
        return plan_attribute_definition(
            ctx, resource, source_dir, planned, resource_type=resource_type
        )

    return planner


PLANNERS[RN_KEYRING] = plan_keyring
PLANNERS[RN_CREDENTIAL] = plan_credential
PLANNERS[RN_NAMESPACE] = plan_namespace
PLANNERS[RN_NAMESPACE_POLICY] = plan_namespace_policy
PLANNERS[RN_STRING_ATTRIBUTE_DEFINITION] = _attribute_planner(
    RN_STRING_ATTRIBUTE_DEFINITION
)
PLANNERS[RN_NUMERIC_ATTRIBUTE_DEFINITION] = _attribute_planner(
    RN_NUMERIC_ATTRIBUTE_DEFINITION
)


# ---------------------------------------------------------------------------
# Groups, Applications and Users
# ---------------------------------------------------------------------------

# A role as a Group holds it: its ID, whether global, and its namespaces
_HeldRole = tuple[str, bool, frozenset[str]]


def _role_shown(name: str, held: _HeldRole) -> str:
    """
    A role and its scope as a plan line names it.
    """
    _, global_, namespaces = held
    scope = "all namespaces" if global_ else ", ".join(sorted(namespaces))
    return f"{name} in {scope}"


def plan_group(
    ctx: RunContext,
    resource: dict,
    source_dir: str | None,
    planned: set[tuple[str, str]],
) -> PlanEntry:
    """
    A Group, found by its name: its description and, with 'roles' given,
    its roles added and removed, each a role in a scope, as the real run
    makes them match; without 'roles' they are left as they are.
    """
    name, description, role_specifications = prepare_group(ctx, resource)
    group_id = get_group_id_by_name(ctx.client, name)
    if group_id is None:
        return PlanEntry(RN_GROUP, name, None, "create")

    existing = ctx.client.account_client.get_group(group_id)
    changes = resource_differences(
        RN_GROUP,
        {PROP_DESCRIPTION: existing.description},
        {PROP_DESCRIPTION: description},
    )
    if role_specifications is not None:
        changes += _role_changes(existing.roles or [], role_specifications)
    return PlanEntry(
        RN_GROUP, name, group_id, "update" if changes else "unchanged", tuple(changes)
    )


def _role_changes(existing: list[Any], wanted: list[RoleSpecification]) -> list[Change]:
    """
    The roles a Group would gain and lose, compared as (role, scope) pairs.
    """
    held: dict[_HeldRole, str] = {
        (
            cast(str, role.role.id),
            bool(role.scope.global_),
            frozenset(ns.namespace for ns in role.scope.namespaces or []),
        ): cast(str, role.role.name)
        for role in existing
    }
    specified: dict[_HeldRole, str] = {
        (spec.id, bool(spec.global_), frozenset(spec.namespaces or [])): spec.name
        for spec in wanted
    }
    return [
        Change(PROP_ROLES, None, _role_shown(name, key), "added")
        for key, name in specified.items()
        if key not in held
    ] + [
        Change(PROP_ROLES, _role_shown(name, key), None, "removed")
        for key, name in held.items()
        if key not in specified
    ]


def _group_changes(
    ctx: RunContext,
    current: dict[str, str | None],
    wanted: set[str],
    planned: set[tuple[str, str]],
) -> list[Change]:
    """
    The Groups an Application or User would join and leave: 'current' its
    Groups' IDs and names, 'wanted' the IDs its specification gives, or the
    names of Groups an earlier specification creates, shown '(to be
    created)'. A Group is shown by its name.
    """

    def shown(group: str) -> object:
        if (RN_GROUP, group) in planned:
            return ToBeCreated(group)
        return get_group_name_by_id(ctx.client, group) or group

    added = [
        Change(PROP_GROUPS, None, shown(group), "added")
        for group in wanted
        if group not in current
    ]
    removed = [
        Change(PROP_GROUPS, name or group_id, None, "removed")
        for group_id, name in current.items()
        if group_id not in wanted
    ]
    return sorted(added, key=lambda c: _group_name(c.after)) + sorted(
        removed, key=lambda c: _group_name(c.before)
    )


def _group_name(group: object) -> str:
    return group.name if isinstance(group, ToBeCreated) else str(group)


def plan_application(
    ctx: RunContext,
    resource: dict,
    source_dir: str | None,
    planned: set[tuple[str, str]],
) -> PlanEntry:
    """
    An Application, found by its name: its description, with 'groups'
    given its Groups joined and left, the Keyrings it would be granted, and,
    with '--regenerate-app-keys', its key regenerated, shown as that alone,
    never a value. Keyrings for an existing Application without
    '--regenerate-app-keys' fail it, as the real run does.
    """
    name, resource, new_group_ids, keyrings = prepare_application(
        ctx, resource, planned
    )
    app_id = get_application_id_by_name(ctx.client, name)
    if app_id is None:
        return PlanEntry(RN_APPLICATION, name, None, "create")
    check_keyring_grants(name, keyrings)

    existing = ctx.client.account_client.get_application(app_id)
    changes = resource_differences(
        RN_APPLICATION,
        {PROP_DESCRIPTION: existing.description},
        {PROP_DESCRIPTION: resource.get(PROP_DESCRIPTION)},
    )
    if new_group_ids is not None:
        current = {
            cast(str, group.id): group.name
            for group in get_application_group_summaries(ctx.client, app_id)
        }
        changes += _group_changes(ctx, current, new_group_ids, planned)
    changes += [Change(PROP_KEYRINGS, None, keyring, "added") for keyring in keyrings]
    if run_options().regenerate_app_keys:
        changes.append(Change(API_KEY, None, API_KEY_REGENERATED, "changed"))
    return PlanEntry(
        RN_APPLICATION,
        name,
        app_id,
        "update" if changes else "unchanged",
        tuple(changes),
    )


def plan_user(
    ctx: RunContext,
    resource: dict,
    source_dir: str | None,
    planned: set[tuple[str, str]],
    *,
    internal_user: bool,
) -> PlanEntry:
    """
    An Internal or External User, found by its name, username or ID as the
    real run finds it (one not found fails, Users not being created by the
    CLI): with 'groups' given, its Groups joined and left; without, it is
    left as it is.
    """
    resource_type = RN_INTERNAL_USER if internal_user else RN_EXTERNAL_USER
    user, new_group_ids = prepare_user(ctx, resource, internal_user, planned)
    username = user.username if isinstance(user, InternalUser) else user.name
    user_id = cast(str, user.id)
    if new_group_ids is None:
        return PlanEntry(
            resource_type,
            username,
            user_id,
            "unchanged",
            reason="no groups given: left as they are",
        )
    current = {
        cast(str, group.id): group.name
        for group in get_user_groups(ctx.client, user_id)
    }
    changes = tuple(_group_changes(ctx, current, new_group_ids, planned))
    return PlanEntry(
        resource_type, username, user_id, "update" if changes else "unchanged", changes
    )


def _user_planner(internal_user: bool):
    def planner(
        ctx: RunContext,
        resource: dict,
        source_dir: str | None,
        planned: set[tuple[str, str]],
    ) -> PlanEntry:
        return plan_user(
            ctx, resource, source_dir, planned, internal_user=internal_user
        )

    return planner


PLANNERS[RN_GROUP] = plan_group
PLANNERS[RN_APPLICATION] = plan_application
PLANNERS[RN_INTERNAL_USER] = _user_planner(True)
PLANNERS[RN_EXTERNAL_USER] = _user_planner(False)


# Why a Configured Worker Pool whose name is taken fails its plan: there is no
# update, and the Platform refuses a new pool of a name any Worker Pool in the
# namespace holds ('Worker pool already exists with the same name in this
# namespace', live run ydst-2611091206-mxng), a SHUTDOWN one included (live
# run ydst-2611091218-3ux5), so every pool of the name counts, whatever its
# status
CONFIGURED_POOL_EXISTS = (
    "a Worker Pool of this name already exists in its namespace, and the"
    " Platform refuses another of the same name"
)


def plan_configured_worker_pool(
    ctx: RunContext,
    resource: dict,
    source_dir: str | None,
    planned: set[tuple[str, str]],
) -> PlanEntry:
    """
    A Configured Worker Pool, always created (there is no update), by its
    namespaced name. One whose name a Worker Pool in its namespace already
    holds fails, as the real run does.
    """
    try:
        name = resource[PROP_NAME]
        namespace = resource[PROP_NAMESPACE]
    except KeyError as e:
        raise missing_property(e) from e
    name = f"{namespace}{NAMESPACE_PREFIX_SEPARATOR}{name}"
    _get_model_object("AddConfiguredWorkerPoolRequest", resource)  # Report faults
    if get_worker_pool_summaries(
        ctx.client, namespace, resource[PROP_NAME], partial_name_matches=False
    ):
        raise ValueError(CONFIGURED_POOL_EXISTS)
    return PlanEntry(RN_CONFIGURED_POOL, name, None, "create")


def plan_allowance(
    ctx: RunContext,
    resource: dict,
    source_dir: str | None,
    planned: set[tuple[str, str]],
) -> PlanEntry:
    """
    An Allowance, always created, its template resolved as the real run
    resolves it (one an earlier specification creates being left as its
    name). With '--match-allowances-by-description' and a description, each
    Allowance of that description is replaced, listed without a prompt.
    """
    description, _ = prepare_allowance(ctx, resource, planned)
    changes: tuple[Change, ...] = ()
    if run_options().match_allowances_by_description and description is not None:
        changes = tuple(
            Change("replaces", allowance.id, None, "removed")
            for allowance in allowances_matching_description(ctx.client, description)
        )
    return PlanEntry(RN_ALLOWANCE, description, None, "create", changes)


PLANNERS[RN_CONFIGURED_POOL] = plan_configured_worker_pool
PLANNERS[RN_ALLOWANCE] = plan_allowance
