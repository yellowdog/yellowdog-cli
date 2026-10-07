"""
Various utility functions for finding objects, etc.
"""

import fnmatch
from collections.abc import Callable, Collection
from dataclasses import dataclass
from functools import lru_cache
from typing import cast

from yellowdog_client import PlatformClient
from yellowdog_client.common import SearchClient
from yellowdog_client.model import (
    AccountAllowance,
    AllowanceSearch,
    Application,
    ApplicationDetails,
    ApplicationSearch,
    ComputeRequirementStatus,
    ComputeRequirementSummary,
    ComputeRequirementSummarySearch,
    ComputeRequirementTemplate,
    ComputeRequirementTemplateSearch,
    ComputeRequirementTemplateSummary,
    ComputeSourceTemplate,
    ComputeSourceTemplateSearch,
    ComputeSourceTemplateSummary,
    ExternalUser,
    Group,
    GroupSearch,
    GroupSummary,
    ImageAccess,
    Instance,
    InstanceSearch,
    InternalUser,
    KeyringSearch,
    KeyringSummary,
    MachineImageFamily,
    MachineImageFamilySearch,
    MachineImageFamilySummary,
    MachineImageGroup,
    NamespaceSearch,
    RequirementsAllowance,
    RoleSearch,
    RoleSummary,
    SourceAllowance,
    SourcesAllowance,
    Task,
    TaskGroup,
    TaskSearch,
    User,
    UserSearch,
    WorkerPool,
    WorkerPoolSearch,
    WorkerPoolSummary,
    WorkRequirement,
    WorkRequirementSearch,
    WorkRequirementStatus,
    WorkRequirementSummary,
)

from yellowdog_cli.utils.exit_codes import (
    SESSION_FAILURES,
    ExitCode,
    NotFoundError,
    classify,
)
from yellowdog_cli.utils.glob_utils import GLOB_CHARS, glob_search_prefix
from yellowdog_cli.utils.interactive import confirmed, select
from yellowdog_cli.utils.misc_utils import is_http_not_found
from yellowdog_cli.utils.printing import print_info, print_warning
from yellowdog_cli.utils.settings import NAMESPACE_PREFIX_SEPARATOR
from yellowdog_cli.utils.ydid_utils import (
    TYPE_IMGFAM,
    TYPE_IMGGRP,
    YDIDType,
    get_ydid_type,
    work_requirement_id_of_task_group,
)


def search_namespaces(
    client: PlatformClient, namespace: str | None
) -> list[str] | None:
    """
    The 'namespaces' a namespaced search is scoped to: the one given, else
    every namespace the Application can read -- None (every namespace) when
    it can read them all, or the list of those it can. The Platform refuses
    an unscoped search, with a 403, from an Application without global read
    access, even for a name in a namespace it can read ('Specify namespaces
    where possible to prevent global access being required'), so a search
    with no namespace is never left unscoped for one. With no readable
    namespace at all, the search is left unscoped, and the Platform's 403
    says which permission is missing. '' is no namespace, as yd-list takes it.
    """
    if namespace:
        return [namespace]
    details = get_application_details(client)
    if details.allNamespacesReadable or not details.readableNamespaces:
        return None
    return list(details.readableNamespaces)


@lru_cache
def get_task_groups_from_wr_by_id(
    client: PlatformClient, wr_id: str
) -> list[TaskGroup]:
    """
    Get the list of the Work Requirement's Task Groups.
    Cache results.
    """
    work_requirement = client.work_client.get_work_requirement_by_id(wr_id)
    return [] if work_requirement.taskGroups is None else work_requirement.taskGroups


def get_filtered_work_requirement_summaries(
    client: PlatformClient,
    name: str | None = None,
    namespace: str | None = None,
    tag: str | None = None,
    include_filter: list[WorkRequirementStatus] | None = None,
    exclude_filter: list[WorkRequirementStatus] | None = None,
) -> list[WorkRequirementSummary]:
    """
    Get a list of Work Requirements optionally filtered by name,
    namespace, tag and statuses. Also support an exclusion
    filter.
    """
    wr_search = WorkRequirementSearch(
        name=name,
        namespaces=search_namespaces(client, namespace),
        tag=tag,
        statuses=include_filter,
    )

    # Note: partial matches on 'name'
    wr_search_client = client.work_client.get_work_requirements(wr_search)
    work_requirement_summaries: list[WorkRequirementSummary] = (
        wr_search_client.list_all()
    )

    if exclude_filter is None:
        return work_requirement_summaries

    return [
        work_requirement_summary
        for work_requirement_summary in work_requirement_summaries
        if work_requirement_summary.status not in exclude_filter
    ]


@lru_cache
def get_worker_pool_by_id(client: PlatformClient, worker_pool_id: str) -> WorkerPool:
    """
    Pass-through function to cache results.
    """
    return client.worker_pool_client.get_worker_pool_by_id(
        worker_pool_id=worker_pool_id
    )


def get_worker_pool_id_by_name(
    client: PlatformClient, worker_pool_name: str, namespace: str | None = None
) -> str | None:
    """
    Find a Worker Pool ID by its name. A 'namespace' in the worker pool name
    overrides the 'namespace' argument. None means not found (an HTTP 404);
    any other failure, such as a 401, is raised for the wrapper to report and
    classify, rather than being mistaken for not found.
    """
    namespace_, name = split_namespace_and_name(worker_pool_name)
    namespace_ = namespace if namespace_ is None else namespace_

    if namespace_ is None:
        return None

    try:
        if (fq_name := f"{namespace_}/{name}") != worker_pool_name:
            print_info(f"Finding Worker Pool ID for '{fq_name}'")
        worker_pool: WorkerPool = client.worker_pool_client.get_worker_pool_by_name(
            namespace_,
            name,  # type: ignore[arg-type]
        )
        return worker_pool.id
    except Exception as e:
        if is_http_not_found(e):
            return None
        raise


class AmbiguousNameError(LookupError):
    """
    A name that two or more entities the command could act on share, so that
    only an ID can say which is meant.
    """


# The Work Requirement states no action applies to
FINISHED_WORK_REQUIREMENT_STATUSES = (
    WorkRequirementStatus.COMPLETED,
    WorkRequirementStatus.CANCELLED,
    WorkRequirementStatus.FAILED,
)


def find_work_requirement_by_name(
    client: PlatformClient,
    name_or_namespaced_name: str,
    default_namespace: str | None,
    statuses: Collection[WorkRequirementStatus],
) -> WorkRequirementSummary:
    """
    The Work Requirement with a name, in 'default_namespace' unless the name
    has a 'namespace/' prefix, found by a search for the name (which the
    Platform matches partially, so the results are filtered for equality),
    never by listing the namespace. A name can be reused once a Work
    Requirement has finished, so the one whose status is in 'statuses' is
    preferred; with none, one in another state is returned, for the caller
    to report as such. Raises NotFoundError when nothing has the name, and
    AmbiguousNameError when two or more in 'statuses' do.
    """
    namespace, name = split_namespace_and_name(name_or_namespaced_name)
    namespace = default_namespace if namespace is None else namespace
    candidates = [
        summary
        for summary in get_filtered_work_requirement_summaries(
            client, name=name, namespace=namespace
        )
        if summary.name == name
    ]
    if not candidates:
        raise NotFoundError(
            f"Cannot find Work Requirement '{name}' in namespace '{namespace}'"
        )
    preferred = [summary for summary in candidates if summary.status in statuses]
    if len(preferred) > 1:
        raise AmbiguousNameError(
            f"{len(preferred)} Work Requirements in namespace '{namespace}' are"
            f" named '{name}' ({', '.join(str(s.status) for s in preferred)});"
            " please supply the ID of the one meant"
        )
    return (preferred or candidates)[0]


def find_compute_requirement_by_name(
    client: PlatformClient,
    name_or_namespaced_name: str,
    default_namespace: str | None,
    statuses: Collection[ComputeRequirementStatus],
) -> ComputeRequirementSummary:
    """
    The Compute Requirement with a name, found as
    find_work_requirement_by_name() finds a Work Requirement: in
    'default_namespace' unless the name has a 'namespace/' prefix, by a name
    search filtered for equality, preferring the one whose status is in
    'statuses' (a name can be reused once a Compute Requirement has
    terminated), else one in another state for the caller to report. Raises
    NotFoundError when nothing has the name, and AmbiguousNameError when two
    or more in 'statuses' do.
    """
    namespace, name = split_namespace_and_name(name_or_namespaced_name)
    namespace = default_namespace if namespace is None else namespace
    candidates = [
        summary
        for summary in get_compute_requirement_summaries(
            client, namespace, tag=None, statuses=None, name=name
        )
        if summary.name == name
    ]
    if not candidates:
        raise NotFoundError(
            f"Cannot find Compute Requirement '{name}' in namespace '{namespace}'"
        )
    preferred = [summary for summary in candidates if summary.status in statuses]
    if len(preferred) > 1:
        raise AmbiguousNameError(
            f"{len(preferred)} Compute Requirements in namespace '{namespace}' are"
            f" named '{name}' ({', '.join(str(s.status) for s in preferred)});"
            " please supply the ID of the one meant"
        )
    return (preferred or candidates)[0]


def work_requirement_summary_of(
    work_requirement: WorkRequirement,
) -> WorkRequirementSummary:
    """
    A fetched Work Requirement as the summary a search would have returned,
    less the Task counts and health, which only a search reports.
    """
    return WorkRequirementSummary(
        id=work_requirement.id,
        namespace=work_requirement.namespace,
        name=work_requirement.name,
        tag=work_requirement.tag,
        createdTime=work_requirement.createdTime,
        statusChangedTime=work_requirement.statusChangedTime,
        priority=work_requirement.priority,
        status=work_requirement.status,
    )


def get_work_requirement_summary_by_name_or_id(
    client: PlatformClient,
    work_requirement_name_or_id: str,
    namespace: str | None = None,
) -> WorkRequirementSummary | None:
    """
    A Work Requirement's summary by its ID, fetched whatever its namespace, or by its
    name, in 'namespace' unless the name has a 'namespace/' prefix, preferring
    one that has not finished where the name has been reused. None means not
    found; two unfinished Work Requirements of the name raise
    AmbiguousNameError rather than one being guessed at.
    """
    if get_ydid_type(work_requirement_name_or_id) == YDIDType.WORK_REQUIREMENT:
        try:
            work_requirement = client.work_client.get_work_requirement_by_id(
                work_requirement_name_or_id
            )
        except Exception as e:
            if is_http_not_found(e):
                return None
            raise
        return work_requirement_summary_of(work_requirement)
    try:
        return find_work_requirement_by_name(
            client,
            work_requirement_name_or_id,
            namespace,
            [
                status
                for status in WorkRequirementStatus
                if status not in FINISHED_WORK_REQUIREMENT_STATUSES
            ],
        )
    except NotFoundError:
        return None


@lru_cache
def get_keyring_summary_by_name(
    client: PlatformClient, name: str
) -> KeyringSummary | None:
    """
    Find a Keyring's summary by its exact name, or None. The search's 'name'
    is a partial match, so the results are filtered for equality here.
    Keyring names are unique within an account. Cached.
    """
    summaries = client.keyring_client.get_keyrings(KeyringSearch(name=name)).list_all()
    return next((s for s in summaries if s.name == name), None)


def clear_keyring_cache():
    """
    Forget the Keyring name lookups: a Keyring created or removed in this run
    must be found, or not, by the specifications that follow it.
    """
    get_keyring_summary_by_name.cache_clear()


@lru_cache
def get_compute_source_template_id_by_name(
    client: PlatformClient, name: str, namespace: str | None = None
) -> str | None:
    """
    Find a Compute Source Template id by name.
    Compute Source Template names are unique within a namespace.
    Namespace included as part of a name overrides argument.
    """
    namespace_, name = split_namespace_and_name(name)  # type: ignore[assignment]
    namespace_ = namespace if namespace_ is None else namespace_

    # Ensure exact name match
    csts = get_compute_source_templates(
        client, namespace_, name, partial_name_matches=False
    )
    if not csts:
        return None

    # Names are unique within namespaces
    # This will be printed only once per name, due to caching
    print_info(f"Compute Source Template name '{name}' -> ID {(cst_id := csts[0].id)}")
    return cst_id


@lru_cache
def get_compute_source_templates(
    client: PlatformClient,
    namespace: str | None = None,
    name: str | None = None,
    partial_name_matches: bool = True,
) -> list[ComputeSourceTemplateSummary]:
    """
    Cache the list of Compute Source Templates, scoped by namespace and name.
    """
    namespace_, name = split_namespace_and_name(name)
    namespace_ = namespace if namespace_ is None else namespace_

    cst_search = ComputeSourceTemplateSearch(
        name=name, namespaces=search_namespaces(client, namespace_)
    )
    cst_search_client: SearchClient = (
        client.compute_client.get_compute_source_templates(cst_search)
    )

    csts = cst_search_client.list_all()
    if partial_name_matches or name is None:
        return csts

    return [cst for cst in csts if cst.name == name]


def clear_compute_source_template_cache():
    """
    Clear the cache of Compute Source Templates.
    Clear name -> CST lookups.
    """
    get_compute_source_templates.cache_clear()
    get_compute_source_template_id_by_name.cache_clear()


def get_compute_requirement_template_id_by_name(
    client: PlatformClient, name: str, namespace: str | None = None
) -> str | None:
    """
    Find the Compute Requirement Template ID that matches the
    provided name and namespace. Namespace as a name prefix
    overrides namespace arg. With neither, the name is looked for in
    every namespace, and found in two or more raises AmbiguousNameError
    rather than one of them being picked.
    """
    namespace_, name = split_namespace_and_name(name)  # type: ignore[assignment]
    namespace_ = namespace if namespace_ is None else namespace_

    crts = get_compute_requirement_templates(
        client, namespace_, name, partial_name_matches=False
    )
    if not crts:
        return None
    if len(crts) > 1:
        namespaces = ", ".join(sorted(str(crt.namespace) for crt in crts))
        raise AmbiguousNameError(
            f"Compute Requirement Templates named '{name}' are in namespaces"
            f" {namespaces}; please supply 'namespace/{name}' or the ID"
        )

    return crts[0].id


@lru_cache
def get_compute_requirement_templates(
    client: PlatformClient,
    namespace: str | None = None,
    name: str | None = None,
    partial_name_matches: bool = True,
) -> list[ComputeRequirementTemplateSummary]:
    """
    Cache the list of Compute Requirement Templates, scoped by namespace
    and name.
    """
    crt_search = ComputeRequirementTemplateSearch(
        name=name, namespaces=search_namespaces(client, namespace)
    )
    crt_search_client: SearchClient = (
        client.compute_client.get_compute_requirement_templates(crt_search)
    )
    crts = crt_search_client.list_all()

    if partial_name_matches or name is None:
        return crts

    return [crt for crt in crts if crt.name == name]


def clear_compute_requirement_template_cache():
    """
    Clear the cache of Compute Requirement Templates.
    """
    get_compute_requirement_templates.cache_clear()


def get_worker_pool_summaries(
    client: PlatformClient,
    namespace: str | None = None,
    name: str | None = None,
    partial_name_matches: bool = True,
) -> list[WorkerPoolSummary]:
    """
    Return all Worker Pool summaries for a namespace, name.
    """
    wp_search = WorkerPoolSearch(
        name=name, namespaces=search_namespaces(client, namespace)
    )
    wp_search_client: SearchClient = client.worker_pool_client.get_worker_pools(
        wp_search
    )
    wps = wp_search_client.list_all()

    if partial_name_matches or name is None:
        return wps

    return [wp for wp in wps if wp.name == name]


@lru_cache
def get_image_name_or_id(
    client: PlatformClient,
    image_name_or_id: str | None,
    always_return_ydid: bool = True,
) -> str | None:
    """
    Attempts to resolve to a well-formed YD image name or ID, if it can.

    Argument 'image_name_or_id' can take one of the following forms:
     - Any image family or group YDID (returned unchanged)
     - Strings prefixed or not prefixed with 'yd/' (will be added if required)
     - Strings post-fixed or not post-fixed with '/latest' (will be removed)
     - Any standalone image-family-name
     - Any namespace/image-family-name combination
     - Any image-family-name/image-group-name combination
     - Any namespace/image-family-name/image-group-name combination

     The call will attempt to resolve the image into its fully qualified
     name if 'always_return_id' is false:
      - yd/namespace/image-family-name or
      - yd/namespace/image-family-name/image-group-name

    If the resolved image is PUBLIC or 'always_return_ydid' is True,
    the relevant YDID will always be returned; this is enforced for
    PUBLIC images.

    Finally, if nothing matches, the original ID is returned. This is
    likely to be a provider-specific string.
    """
    if image_name_or_id is None:
        return None

    # Already a matching YDID?
    if get_ydid_type(image_name_or_id) in [
        YDIDType.IMAGE_FAMILY,
        YDIDType.IMAGE_GROUP,
        YDIDType.IMAGE,
    ]:
        return image_name_or_id

    original = image_name_or_id
    # A leading 'yd/' is reinstated in a name returned, and '/latest' is
    # redundant (implied) for YD image groups
    name = image_name_or_id.removeprefix("yd/").removesuffix("/latest")
    parts = name.split("/")

    image_family_summaries = get_image_family_summaries(client)  # All namespaces
    # This will be tidied up when the Application can query its properties
    if len(parts) in (2, 3) and not image_family_summaries:  # Global search didn't work
        image_family_summaries = get_image_family_summaries(client, parts[0])

    match = _image_match(client, image_family_summaries, parts, original)
    if match is None:
        # Probably a provider-specific image ID
        print_info(f"No Images ID substitution possible for '{original}'")
        return original

    if match.family.access == ImageAccess.PUBLIC or always_return_ydid:
        if match.ydid != original:
            print_info(f"Images ID '{original}' -> {match.ydid}")
        return match.ydid
    if match.name != original:
        print_info(f"Images ID '{original}' -> '{match.name}'")
    return match.name


@dataclass(frozen=True)
class _ImageMatch:
    """
    The Image Family or Group an Images ID names: its YDID, and its full name,
    'yd/namespace/family-name[/group-name]'.
    """

    family: MachineImageFamilySummary
    ydid: str
    name: str


def _image_match(
    client: PlatformClient,
    families: list[MachineImageFamilySummary],
    parts: list[str],
    original: str,
) -> _ImageMatch | None:
    """
    The Image Family or Group a name's parts name, in the forms 'family',
    'namespace/family' (tried before 'family/group') and
    'namespace/family/group', or None if they name none.
    """
    match parts:
        case [family_name]:
            return _family_match(families, family_name, original)
        case [first, second]:
            return _namespace_family_match(families, first, second) or (
                _family_group_match(client, families, first, second, original)
            )
        case [namespace, family_name, group_name]:
            return _namespace_family_group_match(
                client, families, namespace, family_name, group_name, original
            )
    return None


def _family_name(family: MachineImageFamilySummary) -> str:
    return f"yd/{family.namespace}/{family.name}"


def _family_match(
    families: list[MachineImageFamilySummary], family_name: str, original: str
) -> _ImageMatch | None:
    matches = [family for family in families if family.name == family_name]
    if len(matches) > 1:
        namespaces = [family.namespace or "" for family in matches]
        raise ValueError(
            f"Ambiguous Images ID '{original}': please "
            f"specify a namespace from: {', '.join(namespaces)}"
        )
    if not matches:
        return None
    return _ImageMatch(matches[0], cast(str, matches[0].id), _family_name(matches[0]))


def _namespace_family_match(
    families: list[MachineImageFamilySummary], namespace: str, family_name: str
) -> _ImageMatch | None:
    matches = [
        family
        for family in families
        if family.namespace == namespace and family.name == family_name
    ]
    if len(matches) != 1:
        return None
    return _ImageMatch(matches[0], cast(str, matches[0].id), _family_name(matches[0]))


def _family_group_match(
    client: PlatformClient,
    families: list[MachineImageFamilySummary],
    family_name: str,
    group_name: str,
    original: str,
) -> _ImageMatch | None:
    matches: list[_ImageMatch] = []
    for family in families:
        if family.name != family_name:
            continue
        for group in get_image_family_groups(client, cast(str, family.id)):
            if group.name == group_name:
                matches.append(
                    _ImageMatch(
                        family,
                        cast(str, group.id),
                        f"{_family_name(family)}/{group.name}",
                    )
                )
                break  # The first in each family
    if len(matches) > 1:
        namespaces = [match.family.namespace or "" for match in matches]
        raise ValueError(
            f"Ambiguous image-family/image-group '{original}': "
            f"please specify a namespace from: {', '.join(namespaces)}"
        )
    return matches[0] if matches else None


def _namespace_family_group_match(
    client: PlatformClient,
    families: list[MachineImageFamilySummary],
    namespace: str,
    family_name: str,
    group_name: str,
    original: str,
) -> _ImageMatch | None:
    """
    The platform prevents duplicates, so the first match is the only one.
    """
    for family in families:
        if family.namespace == namespace and family.name == family_name:
            for group in get_image_family_groups(client, cast(str, family.id)):
                if group.name == group_name:
                    return _ImageMatch(
                        family,
                        cast(str, group.id),
                        f"yd/{namespace}/{family_name}/{group_name}",
                    )
            raise ValueError(
                f"Image family found, but no matching image group for '{original}'"
            )
    return None


def allowances_to_remove(client: PlatformClient, description: str) -> list:
    """
    The Allowances whose description is exactly 'description' that the user
    chooses to remove: selected from, when there are several, and each one
    confirmed. All the asking and none of the removing, so that yd-create
    asks before it creates the replacement, and an unanswerable prompt fails
    the run before anything has changed.
    """
    allowances = client.allowances_client.get_allowances(
        AllowanceSearch(description=description)
    ).list_all()  # Note: partial matches on 'description'

    # Ensure exact match
    allowances = [
        allowance for allowance in allowances if description == allowance.description
    ]

    if not allowances:
        print_info(f"Cannot find Allowance matching description '{description}'")
        return []

    if len(allowances) > 1:
        print_info(f"Multiple Allowances match the description '{description}'")
        print_info("Please select which Allowance(s) to remove")
        allowances = select(
            client=client,
            objects=allowances,
            object_type_name="Allowance",
            single_result=False,
            force_interactive=True,
        )

    return [
        allowance
        for allowance in allowances
        if confirmed(f"Remove Allowance with YellowDog ID {allowance.id}?")
    ]


def remove_allowances(client: PlatformClient, allowances: list) -> list[str]:
    """
    Remove the Allowances allowances_to_remove() chose, returning their IDs.
    """
    removed = []
    for allowance in allowances:
        client.allowances_client.delete_allowance_by_id(allowance.id)
        print_info(f"Removed Allowance with YellowDog ID {allowance.id}")
        removed.append(cast(str, allowance.id))
    return removed


def remove_allowances_matching_description(
    client: PlatformClient, description: str
) -> list[str]:
    """
    Remove the Allowances matching on the description property that the
    user chooses (see allowances_to_remove()), returning their IDs.
    """
    return remove_allowances(client, allowances_to_remove(client, description))


@lru_cache
def get_all_tasks_in_task_group(
    client: PlatformClient, task_group_id: str
) -> list[Task]:
    """
    Return all the tasks in a task group, with caching.
    """
    return client.work_client.get_tasks(
        TaskSearch(taskGroupId=task_group_id)
    ).list_all()


def split_namespace_and_name(
    namespace_and_name: str | None,
) -> tuple[str | None, str | None]:
    """
    Split a name into an (optional) namespace and a name.
    """
    if namespace_and_name is None:
        return None, None

    namespace_and_name = namespace_and_name.strip()
    parts = namespace_and_name.split(NAMESPACE_PREFIX_SEPARATOR)
    if len(parts) == 1:
        return None, namespace_and_name
    if len(parts) == 2:
        if parts[0] == "":  # Handle the case of a leading slash
            return None, parts[1]
        return parts[0], parts[1]

    raise ValueError(f"Malformed name or namespace/name '{namespace_and_name}'")


def resolve_name_glob(
    pattern: str, default_namespace: str | None
) -> tuple[str | None, str]:
    """
    Split an optional 'namespace/pattern' into (namespace, pattern), applying
    'default_namespace' when no namespace prefix is present. Raises ValueError
    if the namespace part itself contains glob metacharacters (wildcards are
    only allowed in the name).
    """
    namespace, name = split_namespace_and_name(pattern)
    namespace = default_namespace if namespace is None else namespace
    if GLOB_CHARS.intersection(namespace or ""):
        raise ValueError(
            f"Wildcards are not allowed in the namespace part of '{pattern}'"
        )
    return namespace, cast(str, name)


def describe_glob_scope(patterns: list[str], default_namespace: str | None) -> str:
    """
    Human-readable scope phrase for a set of name-glob patterns, resolving each
    pattern's namespace. Collapses to "in namespace 'X' matching 'a', 'b'" when
    all patterns resolve to the same namespace; otherwise qualifies each pattern
    with its namespace: "matching 'ns1/a', 'ns2/b'".
    """
    resolved = [resolve_name_glob(pattern, default_namespace) for pattern in patterns]
    namespaces = {namespace for namespace, _ in resolved}
    if len(namespaces) == 1:
        namespace = resolved[0][0]
        names = ", ".join(repr(name) for _, name in resolved)
        return f"in namespace '{namespace}' matching {names}"
    qualified = ", ".join(repr(f"{namespace}/{name}") for namespace, name in resolved)
    return f"matching {qualified}"


def filter_summaries_by_name_glob(summaries: list, pattern: str) -> list:
    """
    Return summaries whose '.name' matches the glob 'pattern' (case-sensitive,
    fnmatch semantics). Summaries with a None name are skipped.
    """
    return [
        summary
        for summary in summaries
        if summary.name is not None and fnmatch.fnmatchcase(summary.name, pattern)
    ]


def expand_name_globs(
    patterns: list[str],
    default_namespace: str | None,
    fetch: Callable[[str | None, str], list],
) -> list:
    """
    Expand name-glob 'patterns' to a deduplicated list of entity summaries.

    'fetch(namespace, name_prefix)' returns candidate summaries for a namespace,
    optionally server-side filtered by a partial name; 'name_prefix' is '' when
    the pattern begins with a wildcard. Each candidate is kept only if its name
    matches the full glob. Results are deduplicated by '.id', preserving order.
    Raises ValueError (via resolve_name_glob) for a wildcard in a namespace part.
    """
    result: list = []
    seen: set[str] = set()
    for pattern in patterns:
        namespace, name = resolve_name_glob(pattern, default_namespace)
        candidates = fetch(namespace, glob_search_prefix(name))
        for summary in filter_summaries_by_name_glob(candidates, name):
            if summary.id not in seen:
                seen.add(summary.id)
                result.append(summary)
    return result


def substitute_ids_for_names_in_crt(
    client: PlatformClient, crt: ComputeRequirementTemplate, substitute: bool
) -> ComputeRequirementTemplate:
    """
    Substitute CST and Image Family IDs for namespace/name, if 'substitute'
    ('--substitute-ids').
    """
    if not substitute:
        return crt

    # Image family
    try:
        crt.imagesId = _get_image_family_or_group_name_from_id(client, crt.imagesId)
    except (AttributeError, TypeError):  # No such property, or no sources
        pass

    # Source templates
    try:
        for source in crt.sources:  # type: ignore[attr-defined]
            source.sourceTemplateId = _get_source_template_name_from_id(
                client, source.sourceTemplateId
            )
            source.imageId = _get_image_family_or_group_name_from_id(
                client, source.imageId
            )
    except (AttributeError, TypeError):  # No such property, or no sources
        pass

    return crt


def substitute_image_family_id_for_name_in_cst(
    client: PlatformClient, cst: ComputeSourceTemplate, substitute: bool
) -> ComputeSourceTemplate:
    """
    Substitute Image Family IDs for namespace/name, if 'substitute'
    ('--substitute-ids').
    """
    if not substitute:
        return cst

    try:
        cst.source.imageId = _get_image_family_or_group_name_from_id(
            client, cst.source.imageId
        )
        return cst
    except (AttributeError, TypeError):  # No such property, or no sources
        pass

    try:
        # Google uses a different property name
        cst.source.image = _get_image_family_or_group_name_from_id(  # type: ignore[attr-defined]
            client,
            cst.source.image,  # type: ignore[attr-defined]
        )
        return cst
    except (AttributeError, TypeError):  # No such property, or no sources
        pass

    return cst


def substitute_id_for_name_in_allowance(
    client: PlatformClient,
    allowance: (
        AccountAllowance | RequirementsAllowance | SourcesAllowance | SourceAllowance
    ),
    substitute: bool,
) -> AccountAllowance | RequirementsAllowance | SourcesAllowance | SourceAllowance:
    """
    Substitute IDs in Allowance objects, if 'substitute' ('--substitute-ids').
    """
    if not substitute:
        return allowance

    if isinstance(allowance, RequirementsAllowance):
        allowance.requirementCreatedFromId = _get_requirement_template_name_from_id(
            client, allowance.requirementCreatedFromId
        )

    elif isinstance(allowance, SourcesAllowance):
        allowance.sourceCreatedFromId = _get_source_template_name_from_id(
            client, allowance.sourceCreatedFromId
        )

    # No processing for other allowance types
    return allowance


def _raise_session_failure(error: Exception) -> None:
    """
    Re-raise an authentication or connection failure, which a lookup that
    otherwise tolerates failure (shows an ID it could not name) must not
    hide: the command cannot go on as if nothing were wrong.
    """
    if classify(error) in SESSION_FAILURES:
        raise error


@lru_cache
def _get_source_template_name_from_id(
    client: PlatformClient, cst_id: str | None
) -> str | None:
    """
    Obtain the namespace/name of a source template.
    Otherwise, return the original value.
    """
    if get_ydid_type(cst_id) != YDIDType.COMPUTE_SOURCE_TEMPLATE:
        return cst_id
    try:
        cst: ComputeSourceTemplate = client.compute_client.get_compute_source_template(
            cst_id  # type: ignore[arg-type]
        )
        return f"{cst.namespace}/{cst.source.name}"
    except Exception as e:
        _raise_session_failure(e)
        return cst_id


@lru_cache
def _get_requirement_template_name_from_id(
    client: PlatformClient, crt_id: str | None
) -> str | None:
    """
    Obtain the namespace/name of a requirement template.
    Otherwise, return the original value.
    """
    if get_ydid_type(crt_id) != YDIDType.COMPUTE_REQUIREMENT_TEMPLATE:
        return crt_id
    try:
        crt: ComputeRequirementTemplate = (
            client.compute_client.get_compute_requirement_template(crt_id)  # type: ignore[arg-type]
        )
        return f"{crt.namespace}/{crt.name}"
    except Exception as e:
        _raise_session_failure(e)
        return crt_id


@lru_cache
def _get_image_family_or_group_name_from_id(
    client: PlatformClient, image_family_or_group_id: str | None
) -> str | None:
    """
    Obtain the namespace/name of an image family or image group.
    Otherwise, return the original value.
    """
    if (ydid_type := get_ydid_type(image_family_or_group_id)) == YDIDType.IMAGE_FAMILY:
        try:
            image_family: MachineImageFamily = (
                client.images_client.get_image_family_by_id(image_family_or_group_id)  # type: ignore[arg-type]
            )
            return f"yd/{image_family.namespace}/{image_family.name}"
        except Exception as e:
            _raise_session_failure(e)
            return image_family_or_group_id

    elif ydid_type == YDIDType.IMAGE_GROUP:
        try:
            image_group: MachineImageGroup = client.images_client.get_image_group_by_id(
                image_family_or_group_id  # type: ignore[arg-type]
            )
            image_family: MachineImageFamily = (
                client.images_client.get_image_family_by_id(
                    # The image family ID can be derived from the group ID
                    image_family_or_group_id.replace(TYPE_IMGGRP, TYPE_IMGFAM).rsplit(  # type: ignore[union-attr]
                        ":", 1
                    )[0]
                )
            )
            return f"yd/{image_family.namespace}/{image_family.name}/{image_group.name}"
        except Exception as e:
            _raise_session_failure(e)
            return image_family_or_group_id

    return image_family_or_group_id


@lru_cache
def get_role_id_by_name(client: PlatformClient, role_name: str) -> str | None:
    """
    Find the ID of a role by its name. Accept IDs and return unchanged.
    """
    if get_ydid_type(role_name) == YDIDType.ROLE:
        return role_name

    role_search = RoleSearch(name=role_name)
    search_client: SearchClient = client.account_client.get_roles(role_search)

    for role in search_client.list_all():  # Note: partial matches on 'name'
        if role.name == role_name:
            return role.id

    return None


@lru_cache
def get_role_name_by_id(client: PlatformClient, role_id: str) -> str | None:
    """
    Get the name of a role by its ID.
    """
    for role in get_all_roles(client):
        if role.id == role_id:
            return role.name

    return None


@lru_cache
def get_all_roles(client: PlatformClient) -> list[RoleSummary]:
    """
    Cache all roles.
    """
    search_client: SearchClient = client.account_client.get_roles(RoleSearch())
    return search_client.list_all()


@lru_cache
def get_group_id_by_name(client: PlatformClient, group_name: str) -> str | None:
    """
    Get a group's ID by its name. Accept IDs and return unchanged.
    """
    if get_ydid_type(group_name) == YDIDType.GROUP:
        return group_name

    search_client: SearchClient = client.account_client.get_groups(
        GroupSearch(name=group_name)
    )
    # Note: partial matches on 'name'
    group_summaries: list[GroupSummary] = search_client.list_all()

    for group_summary in group_summaries:
        if group_summary.name == group_name:
            return group_summary.id

    return None


@lru_cache
def get_group_name_by_id(client: PlatformClient, group_id: str) -> str | None:
    """
    Get a group's name by its ID, or None when it cannot be fetched (an
    authentication or connection failure is raised).
    """
    try:
        return client.account_client.get_group(group_id).name
    except Exception as e:
        _raise_session_failure(e)
        return None


@lru_cache
def get_all_groups(client: PlatformClient) -> list[GroupSummary]:
    """
    Return a list of all the groups.
    """
    search_client: SearchClient = client.account_client.get_groups(GroupSearch())
    return search_client.list_all()


def clear_group_caches():
    """
    Clear the group caches.
    """
    get_all_groups.cache_clear()
    get_group_name_by_id.cache_clear()
    get_group_id_by_name.cache_clear()


@lru_cache
def get_all_applications(client: PlatformClient) -> list[Application]:
    """
    Return a list of all the applications.
    """
    application_search = ApplicationSearch()
    search_client: SearchClient = client.account_client.get_applications(
        application_search
    )
    return search_client.list_all()


@lru_cache
def get_application_id_by_name(client: PlatformClient, app_name: str) -> str | None:
    """
    Get an application ID by its name. Accept IDs and return unchanged.
    """
    if get_ydid_type(app_name) == YDIDType.APPLICATION:
        return app_name

    for app in get_all_applications(client):
        if app.name == app_name:
            return app.id

    return None


@lru_cache
def get_application_details(client: PlatformClient) -> ApplicationDetails:
    """
    Load and cache the Application's details.
    """
    return client.application_client.get_application_details()


@lru_cache
def get_application_group_summaries(
    client: PlatformClient, app_id: str
) -> list[GroupSummary]:
    """
    Get the summaries of the groups to which an application belongs.
    """
    return client.account_client.get_application_groups(app_id).list_all()


@lru_cache
def get_application_groups(client: PlatformClient, app_id: str) -> list[Group]:
    """
    Get the groups to which an application belongs.
    """
    return [
        client.account_client.get_group(group_summary.id)  # type: ignore[arg-type]
        for group_summary in get_application_group_summaries(client, app_id)
    ]


@lru_cache
def get_all_roles_and_namespaces_for_application(
    client: PlatformClient, application_id: str
) -> dict:
    """
    Get a list of roles and the namespaces to which they apply, for a given
    application.

    Returns {role_name: [namespace, ...]}, sorted by role name.
    """
    # Iterate through groups, roles, accumulate unique namespaces
    roles = dict()
    for group in get_application_groups(client, application_id):
        for role in group.roles:  # type: ignore[union-attr]
            if roles.get(role.role.name) is None:
                # Set of namespaces to suppress duplicates
                roles[role.role.name] = set()
            if role.scope.global_:
                roles[role.role.name].update(["GLOBAL"])
            else:
                roles[role.role.name].update(
                    [namespace.namespace for namespace in role.scope.namespaces or []]
                )

    return {
        role: sorted(list(namespaces)) for role, namespaces in sorted(roles.items())
    }


def clear_application_caches():
    """
    Clear the application caches.
    """
    get_all_applications.cache_clear()
    get_application_id_by_name.cache_clear()
    get_application_details.cache_clear()
    get_application_group_summaries.cache_clear()
    get_application_groups.cache_clear()
    get_all_roles_and_namespaces_for_application.cache_clear()


def get_user_groups(client: PlatformClient, user_id: str) -> list[GroupSummary]:
    """
    Get the groups to which a user belongs.
    """
    return client.account_client.get_user_groups(user_id).list_all()


@lru_cache
def get_user_by_name_or_id(client: PlatformClient, user_name_or_id: str) -> User | None:
    """
    Get a user ID by name, username or ID.
    """
    for user in get_all_users(client):
        if user.id == user_name_or_id:
            return user

        if (
            isinstance(user, InternalUser)
            and (user.username == user_name_or_id or user.name == user_name_or_id)
        ) or (isinstance(user, ExternalUser) and user.name == user_name_or_id):
            return user

    return None


@lru_cache
def get_all_users(client: PlatformClient) -> list[User]:
    """
    Return a list of all users.
    """
    user_search = UserSearch()
    search_client: SearchClient = client.account_client.get_users(user_search)
    return search_client.list_all()


def get_namespace_id_by_name(client: PlatformClient, namespace_name: str) -> str | None:
    """
    Get a namespace's ID by its name.
    """
    search_client: SearchClient = client.namespaces_client.get_namespaces(
        NamespaceSearch(namespace_name)
    )
    for namespace in search_client.list_all():
        if namespace.namespace == namespace_name:
            return namespace.id

    return None


def get_compute_requirement_summaries(
    client: PlatformClient,
    namespace: str | None = None,
    tag: str | None = None,
    statuses: list[ComputeRequirementStatus] | None = None,
    name: str | None = None,
) -> list[ComputeRequirementSummary]:
    """
    Get compute requirement summaries for a namespace, tag.
    Optionally filter on statuses and a partial name.
    """
    crs_search = ComputeRequirementSummarySearch(
        namespaces=search_namespaces(client, namespace),
        tag=tag,
        statuses=statuses,
        name=name,
    )
    search_client: SearchClient = (
        client.compute_client.get_compute_requirement_summaries(crs_search)
    )
    # Note: partial matches on 'tag' and 'name'
    return search_client.list_all()


@lru_cache
def get_image_family_summaries(
    client: PlatformClient,
    namespace: str | None = None,
) -> list[MachineImageFamilySummary]:
    """
    Obtain and cache the list of image families.
    """
    # The readable namespaces, without one: does not guarantee IMAGE_READ
    namespaces = search_namespaces(client, namespace)

    try:
        if_search = MachineImageFamilySearch(
            familyName=None,
            namespaces=namespaces,
            includePublic=True,
        )
        search_client: SearchClient = client.images_client.get_image_families(if_search)
        return search_client.list_all()
    except Exception as e:
        # Only a missing permission means 'none to be seen here': a search
        # of every namespace is followed by one of the name's own, and a
        # namespaced one is warned of. Anything else is raised, never
        # cached as an empty list and a name passed on unresolved.
        if classify(e) != ExitCode.PERMISSION:
            raise
        if namespace is not None:
            # Caching will prevent this warning appearing multiple times
            print_warning(
                "Possible 'IMAGE_READ' permission missing if "
                f"'{namespace}' is meant as an Image namespace?"
            )

    return []


@lru_cache
def get_image_family_groups(
    client: PlatformClient, image_family_id: str
) -> list[MachineImageGroup]:
    """
    Obtain and cache the list of image groups for an image family.
    """
    return (
        client.images_client.get_image_family_by_id(image_family_id).imageGroups or []
    )


def clear_image_caches():
    """
    Clear the image caches.
    """
    get_image_name_or_id.cache_clear()
    get_image_family_summaries.cache_clear()
    get_image_family_groups.cache_clear()


@lru_cache
def get_instance_by_id(
    client: PlatformClient, cr_id: str, instance_id: str
) -> Instance | None:
    """
    Given a compute requirement ID and an instance ID string,
    find the Instance object.
    """
    for instance in _get_instances(client, cr_id):
        if instance.id.instanceId == instance_id:  # type: ignore[union-attr]
            return instance

    return None


@lru_cache
def _get_instances(client: PlatformClient, cr_id: str) -> list[Instance]:
    """
    Get and cache all the instances in a compute requirement.
    """
    instance_search = InstanceSearch(computeRequirementId=cr_id)
    return client.compute_client.get_instances(instance_search).list_all()


def get_task_group_by_id(client: PlatformClient, task_group_id: str) -> TaskGroup:
    """
    Get a task group by its ID.
    """
    work_requirement_id = work_requirement_id_of_task_group(task_group_id)

    try:
        task_groups = get_task_groups_from_wr_by_id(client, work_requirement_id)
    except Exception as e:
        if is_http_not_found(e):
            raise NotFoundError(f"Task Group ID '{task_group_id}' not found") from e
        raise RuntimeError(
            f"Unable to obtain Task Group details for '{task_group_id}': {e}"
        ) from e

    for task_group in task_groups:
        if task_group.id == task_group_id:
            return task_group

    raise NotFoundError(f"Task Group ID '{task_group_id}' not found")
