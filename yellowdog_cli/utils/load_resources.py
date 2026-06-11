"""
Load data for resource creation/update/removal requests.
"""

from os.path import abspath, dirname
from sys import exit

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.printing import print_info, print_warning
from yellowdog_cli.utils.settings import (
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
from yellowdog_cli.utils.variables import (
    load_json_file_with_variable_substitutions,
    load_jsonnet_file_with_variable_substitutions,
    load_toml_file_with_variable_substitutions,
    process_variable_substitutions_insitu,
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
        if isinstance(resources_loaded, dict):
            resources_loaded = [resources_loaded]

        spec_dir = dirname(abspath(resource_spec))

        # Secondary variable processing pass + source-dir stamp
        for resource in resources_loaded:
            process_variable_substitutions_insitu(resource)
            resource[RESOURCE_SOURCE_DIR] = spec_dir

        print_info(
            f"Including {len(resources_loaded)} resource(s) from '{resource_spec}'"
        )
        resources += resources_loaded

    if ARGS_PARSER.jsonnet_dry_run:
        exit(0)

    if len(ARGS_PARSER.resource_specifications) > 1:
        print_info(f"Including {len(resources)} resources in total")

    return _resequence_resources(resources, creation_or_update=creation_or_update)


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

    for r in resources:
        if "resource" not in r:
            raise KeyError(
                "Property 'resource' is not specified for one or more resource specifications"
            )

    # Don't fail the whole batch for unknown resource types here: they're
    # reported (and counted as failures) during per-resource processing
    unknown_types = {
        r["resource"] for r in resources if r["resource"] not in resource_creation_order
    }
    if unknown_types:
        print_warning(
            "Unknown resource type(s) in resource list: "
            f"{', '.join(sorted(unknown_types))}"
        )

    def _sequence(resource: dict) -> int:
        try:
            return resource_creation_order.index(resource["resource"])
        except ValueError:
            return len(resource_creation_order)  # Unknown types sequence last

    resources.sort(key=_sequence, reverse=not creation_or_update)

    return resources
