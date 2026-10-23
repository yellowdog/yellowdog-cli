"""
Load data for resource creation/update/removal requests.
"""

import sys
from os import getcwd
from os.path import abspath, dirname
from sys import exit
from typing import Any

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
from yellowdog_cli.utils.file_substitution import (
    load_json_file_with_variable_substitutions,
    load_json_text_with_variable_substitutions,
    load_jsonnet_file_with_variable_substitutions,
    load_toml_file_with_variable_substitutions,
)
from yellowdog_cli.utils.load_config import parse_property_value
from yellowdog_cli.utils.printing import print_info, print_warning
from yellowdog_cli.utils.property_names import (
    PROP_CREDENTIAL,
    PROP_DESCRIPTION,
    PROP_ID,
    PROP_NAME,
    PROP_NAMESPACE,
    PROP_RESOURCE,
    PROP_SOURCE,
    PROP_USERNAME,
)
from yellowdog_cli.utils.settings import NAMESPACE_PREFIX_SEPARATOR
from yellowdog_cli.utils.specs.schema import Family
from yellowdog_cli.utils.specs.validation import (
    strip_schema_key,
    validate_all_and_exit,
    warn_of_violations,
)
from yellowdog_cli.utils.variable_substitution import resolve_variables_insitu
from yellowdog_cli.utils.ydid_utils import get_ydid_type

# A resource specification read from standard input, as given on the command
# line, and how a message names it
STDIN_SPECIFICATION = "-"
_STDIN_SOURCE = "standard input"
# How a message names a resource given with '--type' and '--set'
_COMMAND_LINE_SOURCE = "the command line"

# Internal key stamped onto each resource dict to record the directory of the
# spec file it came from. Consumed by create.py; never reaches _get_model_object.
RESOURCE_SOURCE_DIR = "_sourceDir"


# The order resources are created in, so that what one refers to exists
# first (removal is the reverse): every type yd-create accepts, which
# tests/test_load_resources.py holds to sdk_models.RESOURCE_TYPES
RESOURCE_CREATION_ORDER: tuple[str, ...] = (
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
)


def load_resource_specifications(
    args: Any,
    creation_or_update: bool = True,
    files: list[str] | None = None,
    per_source: list[list[dict]] | None = None,
) -> list[dict]:
    """
    Load and return a list of resource specifications assembled from the
    resources described in a set of resource description files: those the
    command line 'args' names ('-' standard input's), or 'files' in their
    place (yd-remove's arguments less its IDs), and the resource it gives
    with '--type' and '--set', with its '--jsonnet-dry-run', '--validate'
    and '--no-resequence'. 'per_source', when given, is appended with each
    source's resources in turn, for yd-remove to put them among its IDs in
    the order given.
    """
    resources = []
    to_validate: list[tuple[object, str]] = []  # Under '--validate'
    named = args.resource_specifications if files is None else files
    sources = [
        *named,
        *([_COMMAND_LINE_SOURCE] if getattr(args, "resource_type", None) else []),
    ]
    for position, resource_spec in enumerate(sources):
        shown = resource_spec
        if position == len(named):
            # The resource '--type' and '--set' give
            resources_loaded = _inline_resource(
                args.resource_type, getattr(args, "resource_properties", None) or []
            )
            shown = _COMMAND_LINE_SOURCE
        elif resource_spec == STDIN_SPECIFICATION:
            resources_loaded = load_json_text_with_variable_substitutions(
                sys.stdin.read(), _STDIN_SOURCE
            )
            shown = _STDIN_SOURCE
        elif resource_spec.lower().endswith(".jsonnet"):
            resources_loaded = load_jsonnet_file_with_variable_substitutions(
                resource_spec,
                exit_on_dry_run=False,
                dry_run=bool(args.jsonnet_dry_run),
            )
        elif args.jsonnet_dry_run:
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
                exception_message += (
                    "; a YellowDog ID is removed with 'yd resource remove'"
                )
            raise ValueError(exception_message)

        # Transform single resource items into lists
        document = resources_loaded
        if isinstance(resources_loaded, dict):
            resources_loaded = [resources_loaded]
        _check_specifications(resources_loaded, shown)

        # A file a specification names is found from its directory; from the
        # current one for standard input and the command line
        spec_dir = (
            dirname(abspath(resource_spec)) if shown == resource_spec else getcwd()
        )

        # Secondary variable processing pass
        for resource in resources_loaded:
            resolve_variables_insitu(resource)

        # Every branch above -- JSON, Jsonnet, TOML -- arrives here with the
        # loaded document. Checked for creation only: the schema is what
        # yd-create accepts, and yd-remove reads no more than the names
        if creation_or_update:
            strip_schema_key(resources_loaded)
            if args.validate:
                to_validate.append((document, shown))
                continue
            warn_of_violations(Family.RESOURCES, document, shown)

        # Source-dir stamp
        for resource in resources_loaded:
            resource[RESOURCE_SOURCE_DIR] = spec_dir

        print_info(
            f"Including {len(resources_loaded)} resource(s) from "
            + (f"'{shown}'" if shown == resource_spec else shown)
        )
        resources += resources_loaded
        if per_source is not None:
            per_source.append(resources_loaded)

    if creation_or_update and args.validate:
        validate_all_and_exit(Family.RESOURCES, to_validate)

    if args.jsonnet_dry_run:
        exit(0)

    if len(sources) > 1:
        print_info(f"Including {len(resources)} resources in total")

    return _resequence_resources(
        resources,
        creation_or_update=creation_or_update,
        resequence=not args.no_resequence,
    )


def _inline_resource(resource_type: str, properties: list[str]) -> dict:
    """
    The resource '--type' and '--set' give: each 'property=value' read as a
    '--property' value is, JSON where it parses (a string property keeping
    its text), and its values' variables substituted as a file's are.
    """
    resource: dict = {PROP_RESOURCE: resource_type}
    for given in properties:
        name, _, value = given.partition("=")
        resource[name] = parse_property_value(value, name)
    resolve_variables_insitu(resource)
    return resource


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
    resources: list[dict], creation_or_update: bool = True, resequence: bool = True
) -> list[dict]:
    """
    Re-sequence resources so that possible dependencies are evaluated in the
    correct order. If 'creation_or_update' is True this is a creation/update
    action, otherwise it's a removal action -- the sequencing differs for each.
    Without 'resequence' ('--no-resequence'), they are left as they are.
    """

    if not resequence:
        print_info("Not re-sequencing the resource list")
        return resources

    if len(resources) == 1:
        return resources

    # Don't fail the whole batch for a missing or unknown resource type here:
    # each is reported (and counted as a failure) during per-resource
    # processing, sequenced last (first on removal)
    unknown_types = {
        str(r[PROP_RESOURCE])
        for r in resources
        if r.get(PROP_RESOURCE) is not None
        and r[PROP_RESOURCE] not in RESOURCE_CREATION_ORDER
    }
    if unknown_types:
        print_warning(
            "Unknown resource type(s) in resource list: "
            f"{', '.join(sorted(unknown_types))}"
        )

    def _sequence(resource: dict) -> int:
        try:
            return RESOURCE_CREATION_ORDER.index(str(resource.get(PROP_RESOURCE)))
        except ValueError:
            # Unknown or missing types sequence last
            return len(RESOURCE_CREATION_ORDER)

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
