"""
Load data for resource creation/update/removal requests.
"""

from os.path import abspath, dirname
from sys import exit

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.printing import print_info, print_warning
from yellowdog_cli.utils.settings import (
    NAMESPACE_PREFIX_SEPARATOR,
    PROP_CREDENTIAL,
    PROP_DESCRIPTION,
    PROP_ID,
    PROP_NAME,
    PROP_NAMESPACE,
    PROP_RESOURCE,
    PROP_SOURCE,
    PROP_USERNAME,
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
from yellowdog_cli.utils.spec_schema import Family
from yellowdog_cli.utils.spec_validation import (
    strip_schema_key,
    validate_all_and_exit,
    warn_of_violations,
)
from yellowdog_cli.utils.variable_substitution import (
    load_json_file_with_variable_substitutions,
    load_jsonnet_file_with_variable_substitutions,
    load_toml_file_with_variable_substitutions,
    resolve_variables_insitu,
)
from yellowdog_cli.utils.ydid_utils import get_ydid_type

# Internal key stamped onto each resource dict to record the directory of the
# spec file it came from. Consumed by create.py; never reaches _get_model_object.
RESOURCE_SOURCE_DIR = "_sourceDir"


def load_resource_specifications(creation_or_update: bool = True) -> list[dict]:
    """
    Load and return a list of resource specifications assembled from the
    resources described in a set of resource description files.
    """
    resources = []
    to_validate: list[tuple[object, str]] = []  # Under '--validate'
    for resource_spec in ARGS_PARSER.resource_specifications:
        if resource_spec.lower().endswith(".jsonnet"):
            resources_loaded = load_jsonnet_file_with_variable_substitutions(
                resource_spec, exit_on_dry_run=False
            )
        elif ARGS_PARSER.jsonnet_dry_run:
            print_warning(
                f"['{resource_spec}'] Option '--jsonnet-dry-run' can only be applied"
                f" to files ending in '.jsonnet'"
            )
            continue
        elif resource_spec.lower().endswith(".toml"):
            resources_loaded = load_toml_file_with_variable_substitutions(resource_spec)
        elif resource_spec.lower().endswith(".json"):
            resources_loaded = load_json_file_with_variable_substitutions(resource_spec)
        else:
            exception_message = (
                f"['{resource_spec}'] Resource specifications must end in '.toml', "
                "'.json' or '.jsonnet'"
            )
            if get_ydid_type(resource_spec) is not None:
                exception_message += "; did you mean to use the '--ids' option?"
            raise ValueError(exception_message)

        # Transform single resource items into lists
        document = resources_loaded
        if isinstance(resources_loaded, dict):
            resources_loaded = [resources_loaded]
        _check_specifications(resources_loaded, resource_spec)

        spec_dir = dirname(abspath(resource_spec))

        # Secondary variable processing pass
        for resource in resources_loaded:
            resolve_variables_insitu(resource)

        # Every branch above -- JSON, Jsonnet, TOML -- arrives here with the
        # loaded document. Checked for creation only: the schema is what
        # yd-create accepts, and yd-remove reads no more than the names
        if creation_or_update:
            strip_schema_key(resources_loaded)
            if ARGS_PARSER.validate:
                to_validate.append((document, resource_spec))
                continue
            warn_of_violations(Family.RESOURCES, document, resource_spec)

        # Source-dir stamp
        for resource in resources_loaded:
            resource[RESOURCE_SOURCE_DIR] = spec_dir

        print_info(
            f"Including {len(resources_loaded)} resource(s) from '{resource_spec}'"
        )
        resources += resources_loaded

    if creation_or_update and ARGS_PARSER.validate:
        validate_all_and_exit(Family.RESOURCES, to_validate)

    if ARGS_PARSER.jsonnet_dry_run:
        exit(0)

    if len(ARGS_PARSER.resource_specifications) > 1:
        print_info(f"Including {len(resources)} resources in total")

    return _resequence_resources(resources, creation_or_update=creation_or_update)


_JSON_TYPE_NAMES = {
    str: "a string",
    int: "a number",
    float: "a number",
    bool: "a boolean",
    list: "a list",
    type(None): "null",
}


def _check_specifications(resources: object, resource_spec: str) -> None:
    """
    Refuse a file that is not a resource specification object or a list of
    them, naming the file and the item, before anything indexes into it.
    """
    if not isinstance(resources, list):
        raise ValueError(
            f"'{resource_spec}' holds"
            f" {_JSON_TYPE_NAMES.get(type(resources), type(resources).__name__)},"
            " not a resource specification or a list of them"
        )
    for position, resource in enumerate(resources, start=1):
        if not isinstance(resource, dict):
            raise ValueError(
                f"Item {position} in '{resource_spec}' is"
                f" {_JSON_TYPE_NAMES.get(type(resource), type(resource).__name__)},"
                " not a resource specification"
            )


def _resequence_resources(
    resources: list[dict], creation_or_update: bool = True
) -> list[dict]:
    """
    Re-sequence resources so that possible dependencies are evaluated in the
    correct order. If 'creation_or_update' is True this is a creation/update
    action, otherwise it's a removal action -- the sequencing differs for each.
    """

    if ARGS_PARSER.no_resequence:
        print_info("Not re-sequencing the resource list")
        return resources

    if len(resources) == 1:
        return resources

    resource_creation_order = [
        RN_NAMESPACE,
        RN_KEYRING,
        RN_CREDENTIAL,
        RN_IMAGE_FAMILY,
        RN_STRING_ATTRIBUTE_DEFINITION,
        RN_NUMERIC_ATTRIBUTE_DEFINITION,
        RN_SOURCE_TEMPLATE,
        RN_REQUIREMENT_TEMPLATE,
        RN_ALLOWANCE,
        RN_NAMESPACE_POLICY,
        RN_CONFIGURED_POOL,
        RN_GROUP,
        RN_APPLICATION,
        RN_INTERNAL_USER,
        RN_EXTERNAL_USER,
    ]

    # Don't fail the whole batch for a missing or unknown resource type here:
    # each is reported (and counted as a failure) during per-resource
    # processing, sequenced last (first on removal)
    unknown_types = {
        str(r[PROP_RESOURCE])
        for r in resources
        if r.get(PROP_RESOURCE) is not None
        and r[PROP_RESOURCE] not in resource_creation_order
    }
    if unknown_types:
        print_warning(
            "Unknown resource type(s) in resource list: "
            f"{', '.join(sorted(unknown_types))}"
        )

    def _sequence(resource: dict) -> int:
        try:
            return resource_creation_order.index(str(resource.get(PROP_RESOURCE)))
        except ValueError:
            # Unknown or missing types sequence last
            return len(resource_creation_order)

    resources.sort(key=_sequence, reverse=not creation_or_update)

    return resources


def resource_display_name(resource_type: str | None, resource: dict) -> str | None:
    """
    The name yd-create and yd-remove report a resource by, read from its
    specification before anything is popped from it: namespace-qualified
    for the resources whose names are ('namespace/name'), the namespace for
    a Namespace Policy, the description for an Allowance. None if the
    specification lacks it.
    """

    def _get(container: object, key: str) -> str | None:
        value = container.get(key) if isinstance(container, dict) else None
        return value if isinstance(value, str) else None

    def _qualified(name: str | None) -> str | None:
        namespace = _get(resource, PROP_NAMESPACE)
        if name is None or namespace is None:
            return name
        return f"{namespace}{NAMESPACE_PREFIX_SEPARATOR}{name}"

    if resource_type == RN_SOURCE_TEMPLATE:
        return _qualified(_get(resource.get(PROP_SOURCE), PROP_NAME))
    if resource_type in (RN_REQUIREMENT_TEMPLATE, RN_IMAGE_FAMILY, RN_CONFIGURED_POOL):
        return _qualified(_get(resource, PROP_NAME))
    if resource_type == RN_CREDENTIAL:
        return _get(resource.get(PROP_CREDENTIAL), PROP_NAME)
    if resource_type == RN_NAMESPACE_POLICY:
        return _get(resource, PROP_NAMESPACE)
    if resource_type == RN_ALLOWANCE:
        return _get(resource, PROP_DESCRIPTION)
    if resource_type in (RN_INTERNAL_USER, RN_EXTERNAL_USER):
        return (
            _get(resource, PROP_NAME)
            or _get(resource, PROP_USERNAME)
            or _get(resource, PROP_ID)
        )
    return _get(resource, PROP_NAME)
