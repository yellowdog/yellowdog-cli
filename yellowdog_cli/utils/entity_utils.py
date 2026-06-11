"""
Various utility functions for finding objects, etc.
"""

from functools import lru_cache

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
    MachineImageFamily,
    MachineImageFamilySearch,
    MachineImageFamilySummary,
    MachineImageGroup,
    NamespaceSearch,
    ProvisionedWorkerPool,
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
    WorkRequirementSearch,
    WorkRequirementStatus,
    WorkRequirementSummary,
)

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.interactive import confirmed, select
from yellowdog_cli.utils.misc_utils import is_http_not_found
from yellowdog_cli.utils.printing import print_error, print_info
from yellowdog_cli.utils.settings import NAMESPACE_PREFIX_SEPARATOR
from yellowdog_cli.utils.ydid_utils import (
    TYPE_IMGFAM,
    TYPE_IMGGRP,
    TYPE_TASKGRP,
    TYPE_WORKREQ,
    YDIDType,
    get_ydid_type,
)


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


def get_task_group_name(
    client: PlatformClient, wr_summary: WorkRequirementSummary, task: Task
) -> str:
    """
    Function to find the Task Group Name for a given Task
    within a Work Requirement.
    """
    for task_group in get_task_groups_from_wr_by_id(client, wr_summary.id):
        if task.taskGroupId == task_group.id:
            return task_group.name

    raise RuntimeError(f"Task group name not found for Task ID {task.id}")


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
        namespaces=None if namespace is None else [namespace],
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
    overrides the 'namespace' argument.
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
        if not is_http_not_found(e):
            print_error(f"Unable to look up Worker Pool '{worker_pool_name}': {e}")
        return None


def get_compute_requirement_id_by_name(
    client: PlatformClient,
    compute_requirement_name: str,
    namespace: str,
    statuses: list[ComputeRequirementStatus] | None = None,
) -> str | None:
    """
    Find a Compute Requirement ID by its name and namespace.
    Restrict search by status. A 'namespace' prefix for the
    name will override the 'namespace' argument.
    """
    namespace_, name = split_namespace_and_name(compute_requirement_name)
    namespace_ = namespace if namespace_ is None else namespace_

    crs_search = ComputeRequirementSummarySearch(
        name=name,
        statuses=statuses,
        namespaces=None if namespace_ is None else [namespace_],
    )
    search_client: SearchClient = (
        client.compute_client.get_compute_requirement_summaries(crs_search)
    )
    if (fq_name := f"{namespace_}/{name}") != compute_requirement_name:
        print_info(f"Finding Compute Requirement ID for '{fq_name}'")
    try:
        # The CR must be unique for any given namespace/name
        # Ensure exact name match
        return next(cr for cr in search_client.list_all() if cr.name == name).id
    except StopIteration:
        return None


def get_work_requirement_summary_by_name_or_id(
    client: PlatformClient,
    work_requirement_name_or_id: str,
    namespace: str | None = None,
) -> WorkRequirementSummary | None:
    """
    Get a Work Requirement Summary by its name or ID.
    Scoped by namespace.
    """
    namespace_, name = split_namespace_and_name(work_requirement_name_or_id)
    namespace_ = namespace if namespace_ is None else namespace_

    # Don't include name in the search, to allow for name or ID
    work_requirement_summaries = get_work_requirement_summaries(
        client, namespace=namespace_, partial_name_matches=True
    )

    for work_requirement_summary in work_requirement_summaries:
        if (
            work_requirement_summary.name == name
            or work_requirement_summary.id == work_requirement_name_or_id
        ):
            return work_requirement_summary

    return None


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
        name=name, namespaces=None if namespace_ is None else [namespace_]
    )
    cst_search_client: SearchClient = (
        client.compute_client.get_compute_source_templates(cst_search)
    )

    csts = cst_search_client.list_all()
    if partial_name_matches or name is None:
        return csts

    return [cst for cst in csts if cst.name == name]


@lru_cache
def get_work_requirement_summaries(
    client: PlatformClient,
    namespace: str | None = None,
    name: str | None = None,
    partial_name_matches: bool = True,
) -> list[WorkRequirementSummary]:
    """
    Get the list of Work Requirement summaries, optionally
    scoped by namespace and name. Optionally allow partial
    name matches.
    """
    wr_search = WorkRequirementSearch(
        name=name, namespaces=None if namespace is None else [namespace]
    )
    wr_search_client: SearchClient = client.work_client.get_work_requirements(wr_search)
    wr_summaries = wr_search_client.list_all()

    if partial_name_matches or name is None:
        return wr_summaries

    return [wr for wr in wr_summaries if wr.name == name]


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
    overrides namespace arg.
    """
    namespace_, name = split_namespace_and_name(name)  # type: ignore[assignment]
    namespace_ = namespace if namespace_ is None else namespace_

    crts = get_compute_requirement_templates(
        client, namespace_, name, partial_name_matches=False
    )
    if not crts:
        return None

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
        name=name, namespaces=None if namespace is None else [namespace]
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


def get_compute_requirement_id_by_worker_pool_id(
    client: PlatformClient, worker_pool_id: str
) -> str | None:
    """
    Get a Compute Requirement ID from a Provisioned Worker Pool ID.
    """
    try:
        worker_pool: WorkerPool = client.worker_pool_client.get_worker_pool_by_id(
            worker_pool_id
        )
    except Exception as e:
        if not is_http_not_found(e):
            print_error(f"Unable to look up Worker Pool '{worker_pool_id}': {e}")
        return None

    if isinstance(worker_pool, ProvisionedWorkerPool):
        return worker_pool.computeRequirementId

    return None


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
        name=name, namespaces=None if namespace is None else [namespace]
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
    report_substitutions: bool = True,
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

    original_image_name_or_id = image_name_or_id

    # Remove a leading 'yd/' prefix; will be reinstated later if required
    image_name_or_id = (
        image_name_or_id[3:] if image_name_or_id.startswith("yd/") else image_name_or_id
    )

    # Remove "/latest"; this is redundant/implied for YD image groups
    image_name_or_id = (
        image_name_or_id[:-7]
        if image_name_or_id.endswith("/latest")
        else image_name_or_id
    )

    def _replaced(return_val: str, is_ydid: bool = False):
        """
        Helper function to report the replacement.
        """
        if report_substitutions and return_val != original_image_name_or_id:
            msg = f"{return_val}" if is_ydid else f"'{return_val}'"
            print_info(f"Images ID '{original_image_name_or_id}' -> {msg}")
        return return_val

    split_name = image_name_or_id.split("/")
    image_family_summaries = get_image_family_summaries(client)  # All namespaces

    # Search for image name (only) matches
    if len(split_name) == 1:
        matching_image_families = [
            ifs for ifs in image_family_summaries if ifs.name == split_name[0]
        ]
        if len(matching_image_families) > 1:
            namespaces = [ifs.namespace or "" for ifs in matching_image_families]
            raise ValueError(
                f"Ambiguous Images ID '{original_image_name_or_id}': please "
                f"specify a namespace from: {', '.join(namespaces)}"
            )
        elif len(matching_image_families) == 1:
            if (
                matching_image_families[0].access == ImageAccess.PUBLIC
                or always_return_ydid
            ):
                return _replaced(matching_image_families[0].id, True)  # type: ignore[arg-type]
            else:
                return _replaced(
                    f"yd/{matching_image_families[0].namespace}/"
                    f"{matching_image_families[0].name}"
                )

    # Search for namespace/family_name matches, *or* family_name/group_name matches
    if len(split_name) == 2:
        # namespace/family-name match

        # This will be tidied up when the Application can
        # query its properties
        if not image_family_summaries:  # Global search didn't work
            image_family_summaries = get_image_family_summaries(client, split_name[0])

        matching_image_families = [
            ifs
            for ifs in image_family_summaries
            if ifs.namespace == split_name[0] and ifs.name == split_name[1]
        ]
        if len(matching_image_families) == 1:
            if (
                matching_image_families[0].access == ImageAccess.PUBLIC
                or always_return_ydid
            ):
                return _replaced(matching_image_families[0].id, True)  # type: ignore[arg-type]
            return _replaced(
                f"yd/{matching_image_families[0].namespace}/"
                f"{matching_image_families[0].name}"
            )

        # family-name/group-name match
        matching_image_families = [
            ifs for ifs in image_family_summaries if ifs.name == split_name[0]
        ]
        if_group_matches: list[tuple[MachineImageFamilySummary, MachineImageGroup]] = []
        for ifs in matching_image_families:
            for if_group in get_image_family_groups(client, ifs.id):
                if if_group.name == split_name[1]:
                    if_group_matches.append((ifs, if_group))
                    break
        if len(if_group_matches) == 1:
            if (
                if_group_matches[0][0].access == ImageAccess.PUBLIC
                or always_return_ydid
            ):
                return _replaced(if_group_matches[0][1].id, True)  # type: ignore[arg-type]
            else:
                return _replaced(
                    f"yd/{if_group_matches[0][0].namespace}/"
                    f"{if_group_matches[0][0].name}/"
                    f"{if_group_matches[0][1].name}"
                )
        if len(if_group_matches) > 1:
            namespaces = [match[0].namespace or "" for match in if_group_matches]
            raise ValueError(
                f"Ambiguous image-family/image-group '{original_image_name_or_id}': "
                f"please specify a namespace from: {', '.join(namespaces)}"
            )

    # Search for names of form 'namespace/image-family-name/image-group-name'
    # (the platform prevents duplicates)
    if len(split_name) == 3:
        # This will be tidied up when the Application can
        # query its properties
        if not image_family_summaries:  # Global search didn't work
            image_family_summaries = get_image_family_summaries(client, split_name[0])

        for ifs in image_family_summaries:
            if ifs.namespace == split_name[0] and ifs.name == split_name[1]:
                for ig in get_image_family_groups(client, ifs.id):
                    if ig.name == split_name[2]:
                        if ifs.access == ImageAccess.PUBLIC or always_return_ydid:
                            return _replaced(ig.id, True)  # type: ignore[arg-type]
                        else:
                            return _replaced(f"yd/{image_name_or_id}")
                else:
                    raise ValueError(
                        "Image family found, but no matching image "
                        f"group for '{original_image_name_or_id}'"
                    )

    # Finally, fall through and return the unchanged, original ID string
    print_info(f"No Images ID substitution possible for '{original_image_name_or_id}'")
    return original_image_name_or_id


def remove_allowances_matching_description(
    client: PlatformClient, description: str
) -> int:
    """
    Remove Allowances that match on the description property.
    Return the number of allowances removed.
    """
    allowances = client.allowances_client.get_allowances(
        AllowanceSearch(description=description)
    ).list_all()  # Note: partial matches on 'name'

    # Ensure exact match
    allowances = [
        allowance for allowance in allowances if description == allowance.description
    ]

    if not allowances:
        print_info(f"Cannot find Allowance matching description '{description}'")
        return 0

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

    for allowance in allowances:
        if confirmed(f"Remove Allowance with YellowDog ID {allowance.id}?"):
            client.allowances_client.delete_allowance_by_id(allowance.id)  # type: ignore[arg-type]
            print_info(f"Removed Allowance with YellowDog ID {allowance.id}")

    return len(allowances)


@lru_cache
def get_all_tasks_in_task_group(
    client: PlatformClient, task_group_id: str
) -> list[Task]:
    """
    Return all the tasks in a task group, with caching.
    """
    return client.work_client.find_tasks(
        TaskSearch(
            taskGroupId=task_group_id,
        )
    )


def split_namespace_and_name(
    namespace_and_name: str | None,
) -> tuple[str | None, str | None]:
    """
    Split a name into an (optional) namespace and a name.
    """
    if namespace_and_name is None:
        return None, None

    parts = namespace_and_name.strip().split(NAMESPACE_PREFIX_SEPARATOR)
    if len(parts) == 1:
        return None, namespace_and_name
    if len(parts) == 2:
        if parts[0] == "":  # Handle the case of a leading slash
            return None, parts[1]
        return parts[0], parts[1]

    raise ValueError(f"Malformed name or namespace/name '{namespace_and_name}'")


def substitute_ids_for_names_in_crt(
    client: PlatformClient, crt: ComputeRequirementTemplate
) -> ComputeRequirementTemplate:
    """
    Substitute CST and Image Family IDs for namespace/name,
    if option is selected.
    """
    if not ARGS_PARSER.substitute_ids:
        return crt

    # Image family
    try:
        crt.imagesId = _get_image_family_or_group_name_from_id(client, crt.imagesId)
    except Exception:
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
    except Exception:
        pass

    return crt


def substitute_image_family_id_for_name_in_cst(
    client: PlatformClient, cst: ComputeSourceTemplate
) -> ComputeSourceTemplate:
    """
    Substitute Image Family IDs for namespace/name,
    if option is selected.
    """
    if not ARGS_PARSER.substitute_ids:
        return cst

    try:
        cst.source.imageId = _get_image_family_or_group_name_from_id(
            client, cst.source.imageId
        )
        return cst
    except Exception:
        pass

    try:
        # Google uses a different property name
        cst.source.image = _get_image_family_or_group_name_from_id(  # type: ignore[attr-defined]
            client,
            cst.source.image,  # type: ignore[attr-defined]
        )
        return cst
    except Exception:
        pass

    return cst


def substitute_id_for_name_in_allowance(
    client: PlatformClient,
    allowance: (
        AccountAllowance | RequirementsAllowance | SourcesAllowance | SourceAllowance
    ),
) -> AccountAllowance | RequirementsAllowance | SourcesAllowance | SourceAllowance:
    """
    Substitute IDs in Allowance objects.
    """
    if not ARGS_PARSER.substitute_ids:
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
    except Exception:
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
    except Exception:
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
        except Exception:
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
        except Exception:
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
    Get a group's name by its ID.
    """
    try:
        return client.account_client.get_group(group_id).name
    except Exception:
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
) -> list[ComputeRequirementSummary]:
    """
    Get compute requirement summaries for a namespace, tag.
    Optionally filter on statuses.
    """
    crs_search = ComputeRequirementSummarySearch(
        namespaces=(None if namespace in [None, ""] else [namespace]),  # type: ignore[list-item]
        tag=tag,
        statuses=statuses,
    )
    search_client: SearchClient = (
        client.compute_client.get_compute_requirement_summaries(crs_search)
    )
    # Note: partial matches on 'tag'
    return search_client.list_all()


@lru_cache
def get_image_family_summaries(
    client: PlatformClient,
    namespace: str | None = None,
) -> list[MachineImageFamilySummary]:
    """
    Obtain and cache the list of image families.
    """
    # Determine namespace(s) to search
    if namespace is None:
        # Attempt to use the namespace(s) that are 'readable' by
        # this application; does not guarantee IMAGE_READ
        application_details = get_application_details(client)
        if application_details.allNamespacesReadable:
            namespaces = None  # Search all namespaces
        elif application_details.readableNamespaces is not None:
            namespaces = application_details.readableNamespaces
        else:
            namespaces = []
    else:
        # Use the supplied namespace
        namespaces = [namespace]

    try:
        if_search = MachineImageFamilySearch(
            familyName=None,
            namespaces=namespaces,
            includePublic=True,
        )
        search_client: SearchClient = client.images_client.get_image_families(if_search)
        return search_client.list_all()
    except Exception as e:
        if namespace is not None and "MissingPermissionException" in str(e):
            # Caching will prevent this warning appearing multiple times
            print_info(
                "Warning: Possible 'IMAGE_READ' permission missing if "
                f"'{namespace}' is meant as an Image namespace?"
            )
        else:
            print_error(f"Unable to list Image Families: {e}")

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
def get_instance_id_by_id(
    client: PlatformClient, cr_id: str, instance_id: str
) -> Instance | None:
    """
    Given a compute requirement ID and an instance ID string,
    find the Instance ID object.
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
    work_requirement_id = task_group_id.rsplit(":", 1)[0].replace(
        TYPE_TASKGRP, TYPE_WORKREQ
    )

    try:
        task_groups = get_task_groups_from_wr_by_id(client, work_requirement_id)
    except Exception as e:
        if is_http_not_found(e):
            raise KeyError(f"Task Group ID '{task_group_id}' not found")
        raise RuntimeError(
            f"Unable to obtain Task Group details for '{task_group_id}': {e}"
        )

    for task_group in task_groups:
        if task_group.id == task_group_id:
            return task_group

    raise KeyError(f"Task Group ID '{task_group_id}' not found")
