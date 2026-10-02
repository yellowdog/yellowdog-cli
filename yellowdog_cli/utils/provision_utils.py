"""
Utility functions for provisioning and instantiating.
"""

from json import dumps as json_dumps
from os import chdir, getcwd

from yellowdog_client import PlatformClient

from yellowdog_cli.utils.config_types import ConfigWorkerPool
from yellowdog_cli.utils.entity_utils import (
    get_compute_requirement_template_id_by_name,
    get_image_name_or_id,
)
from yellowdog_cli.utils.load_config import CONFIG_FILE_DIR
from yellowdog_cli.utils.printing import print_info
from yellowdog_cli.utils.property_names import USERDATA, USERDATAFILE, USERDATAFILES
from yellowdog_cli.utils.settings import WP_VARIABLES_POSTFIX, WP_VARIABLES_PREFIX
from yellowdog_cli.utils.variable_substitution import (
    process_variable_substitutions_in_file_contents,
    warn_of_undefined_variables,
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
    """
    original_directory = getcwd()
    try:
        if source_dir:
            try:
                chdir(source_dir)
            except Exception as e:
                raise RuntimeError(
                    f"Unable to switch to content directory '{source_dir}': {e}"
                )

        # Each part keeps its source, so that a file is substituted, and named
        # in an error or a warning, by itself rather than with the others
        if user_data is not None:
            parts = [(USERDATA, user_data)]
        elif user_data_file is not None:
            with open(user_data_file) as f:
                parts = [(user_data_file, f.read())]
        elif user_data_files is not None:
            parts = []
            for path in user_data_files:
                with open(path) as f:
                    parts.append((path, f.read() + "\n"))
        else:
            return None
    finally:
        chdir(original_directory)

    return "".join(_substituted_user_data(source, text) for source, text in parts)


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
        raise RuntimeError(f"Error processing variable substitutions: {e}")

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
        CONFIG_FILE_DIR if content_path is None or content_path == "" else content_path
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

    source_dir = base_dir if base_dir else CONFIG_FILE_DIR
    content = _read_user_data(None, user_data_file, user_data_files, source_dir)

    spec.pop(USERDATAFILE, None)
    spec.pop(USERDATAFILES, None)
    if content is not None:
        spec[USERDATA] = content


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
        raise KeyError(
            f"Compute Requirement Template '{template_id_or_name}' not found"
        )

    print_info(
        f"Compute Requirement Template '{template_id_or_name}' --> {template_id}"
    )
    return template_id


def get_image_id(client: PlatformClient, image_name_or_id: str) -> str | None:
    """
    This function was simplified, hence the pass-through call for now.
    """
    return get_image_name_or_id(
        client=client, image_name_or_id=image_name_or_id, always_return_ydid=True
    )
