"""
Utility functions for provisioning and instantiating.
"""

from json import dumps as json_dumps
from os.path import join
from typing import Any

from yellowdog_client import PlatformClient

from yellowdog_cli.utils.config_types import ConfigWorkerPool
from yellowdog_cli.utils.entity_utils import (
    get_compute_requirement_template_id_by_name,
    get_image_name_or_id,
)
from yellowdog_cli.utils.exit_codes import NotFoundError
from yellowdog_cli.utils.file_substitution import (
    process_variable_substitutions_in_file_contents,
)
from yellowdog_cli.utils.load_config import config_file_dir
from yellowdog_cli.utils.misc_utils import generate_id
from yellowdog_cli.utils.printing import print_info
from yellowdog_cli.utils.property_names import USERDATA, USERDATAFILE, USERDATAFILES
from yellowdog_cli.utils.type_check import check_list, check_str
from yellowdog_cli.utils.variable_substitution import warn_of_undefined_variables
from yellowdog_cli.utils.variable_syntax import (
    WP_VARIABLES_POSTFIX,
    WP_VARIABLES_PREFIX,
)
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

_MUTEX_ERROR = (
    f"Only one of '{USERDATA}', '{USERDATAFILE}' or '{USERDATAFILES}' should be set"
)


def _read_user_data(
    user_data: str | None,
    user_data_file: str | None,
    user_data_files: list[str] | None,
    source_dir: str,
) -> str | None:
    """
    Core implementation shared by get_user_data_property and
    resolve_user_data_in_spec.  Reads and returns user-data content from one
    of three sources, applying variable substitutions.  Mutual exclusivity is
    assumed to have been validated by the caller.

    A relative file is opened from 'source_dir' (an absolute one as it is),
    never by changing the working directory, which is the whole process's.
    """
    check_str(user_data, USERDATA)
    check_str(user_data_file, USERDATAFILE)
    check_list(user_data_files, USERDATAFILES)

    # Each part keeps its source, so that a file is substituted, and named
    # in an error or a warning, by itself rather than with the others
    if user_data is not None:
        parts = [(USERDATA, user_data)]
    elif user_data_file is not None:
        parts = [(user_data_file, _read(user_data_file, source_dir))]
    elif user_data_files is not None:
        parts = []
        for path in user_data_files:
            check_str(path, USERDATAFILES)
            parts.append((path, _read(path, source_dir) + "\n"))
    else:
        return None

    return "".join(_substituted_user_data(source, text) for source, text in parts)


def _read(path: str, source_dir: str) -> str:
    """
    A User Data file's text, found from 'source_dir'; a missing one is
    reported by the path it was looked for at.
    """
    full_path = join(source_dir, path) if source_dir else path
    try:
        with open(full_path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError as e:
        raise FileNotFoundError(
            f"User Data file '{path}' not found (looked for at '{full_path}')"
        ) from e


def _substituted_user_data(source: str, text: str) -> str:
    """
    One part of the User Data with variables substituted. Substituted as text,
    so no substitution pass walks it: an undefined variable left in it is
    reported here, by 'source'.
    """
    try:
        content = process_variable_substitutions_in_file_contents(
            text,
            prefix=WP_VARIABLES_PREFIX,
            postfix=WP_VARIABLES_POSTFIX,
            source=source,
        )
    except Exception as e:
        raise RuntimeError(
            f"Error processing variable substitutions in '{source}': {e}"
        ) from e

    warn_of_undefined_variables(
        {source: content},
        prefix=WP_VARIABLES_PREFIX,
        postfix=WP_VARIABLES_POSTFIX,
        per_source=True,
    )
    return content


def get_user_data_property(
    config: ConfigWorkerPool, content_path: str | None = None
) -> str | None:
    """
    Get the 'userData' property from a worker pool config, reading from
    'userDataFile' or concatenating 'userDataFiles' as needed.
    Raises ValueError if more than one of the three properties is set.
    """
    if [config.user_data, config.user_data_file, config.user_data_files].count(
        None
    ) < 2:
        raise ValueError(_MUTEX_ERROR)

    source_dir = (
        config_file_dir()
        if content_path is None or content_path == ""
        else content_path
    )
    return _read_user_data(
        config.user_data, config.user_data_file, config.user_data_files, source_dir
    )


def resolve_user_data_in_spec(spec: dict, base_dir: str | None = None) -> None:
    """
    Resolve 'userDataFile' / 'userDataFiles' in a resource specification dict
    in-place, reading the file(s) and collapsing them into a single 'userData'
    string.  Mutually exclusive with an inline 'userData' value.  No-op when
    none of the three keys are present in the spec.

    Relative file paths are resolved from base_dir when provided, otherwise
    from CONFIG_FILE_DIR (the directory containing the active config.toml).
    """
    user_data = spec.get(USERDATA)
    user_data_file = spec.get(USERDATAFILE)
    user_data_files = spec.get(USERDATAFILES)

    if [user_data, user_data_file, user_data_files].count(None) < 2:
        raise ValueError(_MUTEX_ERROR)

    if user_data_file is None and user_data_files is None:
        return

    source_dir = base_dir if base_dir else config_file_dir()
    content = _read_user_data(None, user_data_file, user_data_files, source_dir)

    spec.pop(USERDATAFILE, None)
    spec.pop(USERDATAFILES, None)
    if content is not None:
        spec[USERDATA] = content


def user_data_source(config: ConfigWorkerPool) -> str:
    """
    Where the configuration's User Data comes from, for a message that
    reports it without printing it: a boot script can be long, and can
    carry credentials.
    """
    if config.user_data_file is not None:
        return f"'{config.user_data_file}'"
    if config.user_data_files is not None:
        return ", ".join(f"'{path}'" for path in config.user_data_files)
    return f"the configuration's '{USERDATA}'"


def requirement_name(config: ConfigWorkerPool, name_tag: str) -> str:
    """
    The name the configuration gives the Compute Requirement (or Worker Pool),
    else one generated from the name tag. Generated whether or not it is used,
    so that a name tag too long for it is always reported.
    """
    generated = generate_id(name_tag)
    return config.name if config.name is not None else generated


def requirement_tag(config: ConfigWorkerPool, name_tag: str) -> str:
    """
    The Compute Requirement's tag: the configuration's, else the name tag.
    """
    return name_tag if config.cr_tag is None else config.cr_tag


def shown_value(value: object) -> str:
    """
    A value set in a specification, as a message shows it: a string as it
    is, anything else as JSON, the form the specification is written in
    (so 'true' and '{"enabled": true}', never Python's 'True').
    """
    return value if isinstance(value, str) else json_dumps(value)


def get_template_id(client: PlatformClient, template_id_or_name: str) -> str:
    """
    Check if 'template_id_or_name' looks like a valid CRT ID; if not,
    assume it's a CRT name and perform a lookup.
    """
    if get_ydid_type(template_id_or_name) == YDIDType.COMPUTE_REQUIREMENT_TEMPLATE:
        return template_id_or_name

    template_id = get_compute_requirement_template_id_by_name(
        client=client, name=template_id_or_name
    )
    if template_id is None:
        raise NotFoundError(
            f"Compute Requirement Template '{template_id_or_name}' not found"
        )

    print_info(f"Compute Requirement Template '{template_id_or_name}' -> {template_id}")
    return template_id


def get_image_id(client: PlatformClient, image_name_or_id: str) -> str | None:
    """
    An Images ID as yd-provision and yd-instantiate pass it on: an image
    family, group or image name resolved to its YellowDog ID, anything else
    (a provider's own image ID) unchanged.
    """
    return get_image_name_or_id(
        client=client, image_name_or_id=image_name_or_id, always_return_ydid=True
    )


def specification_model(class_name: str, data: dict) -> Any:
    """
    A JSON specification's part as the SDK model it describes (a
    ComputeRequirementTemplateUsage or ProvisionedWorkerPoolProperties), so
    that yd-provision and yd-instantiate send it through the SDK, as the
    TOML path does. Built as yd-create builds its resources: a property the
    model lacks is warned of and left out, and the specification itself is
    not changed.
    """
    from yellowdog_cli.utils.resource_creation import _get_model_object

    return _get_model_object(class_name, dict(data))
