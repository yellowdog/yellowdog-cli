"""
Common utility functions, mostly related to loading configuration data.
"""

import json
import os
from os import getenv
from os.path import abspath, dirname, join, relpath
from pathlib import Path
from sys import exit
from typing import cast

from tomli import TOMLDecodeError

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.config_types import (
    ConfigCommon,
    ConfigDataClient,
    ConfigWorkerPool,
    ConfigWorkRequirement,
)
from yellowdog_cli.utils.misc_utils import (
    config_file_explicitly_selected as _config_file_explicitly_selected,
)
from yellowdog_cli.utils.misc_utils import (
    pathname_relative_to_config_file,
)
from yellowdog_cli.utils.printing import (
    print_error,
    print_info,
    print_warning,
)
from yellowdog_cli.utils.property_names import *
from yellowdog_cli.utils.settings import (
    CR_MAX_INSTANCES,
    DEFAULT_URL,
    TASK_BATCH_SIZE_DEFAULT,
    TOML_VAR_NESTED_DEPTH,
    YD_CONF,
    YD_DATA_CLIENT,
    YD_DATA_CLIENT_BUCKET,
    YD_DATA_CLIENT_PREFIX,
    YD_DATA_CLIENT_REMOTE,
    YD_KEY,
    YD_KEY_ALT,
    YD_NAMESPACE,
    YD_SECRET,
    YD_SECRET_ALT,
    YD_TAG,
    YD_URL,
    YD_URL_ALT,
)
from yellowdog_cli.utils.type_check import check_list, check_str
from yellowdog_cli.utils.validate_properties import validate_properties
from yellowdog_cli.utils.variables import (
    CLI_DEFINED_VARIABLES,
    VARIABLE_SUBSTITUTIONS,
    add_or_update_substitution,
    add_substitutions_without_overwriting,
    load_toml_file_with_variable_substitutions,
    process_variable_substitutions,
    process_variable_substitutions_insitu,
)


def config_file_explicitly_selected() -> bool:
    """
    True if the configuration file was explicitly selected using the
    '--config'/'-c' option. An explicitly selected config file takes
    precedence over environment variables (but not over the command line).
    """
    return _config_file_explicitly_selected(ARGS_PARSER)


def _parse_property_value(value_str: str):
    """
    Parse a property value string into a Python object.
    Tries JSON first (handles bool, int, float, list, dict), falls back to str.
    """
    try:
        return json.loads(value_str)
    except (json.JSONDecodeError, ValueError):
        return value_str


def _apply_property_overrides(config: dict, overrides: list[str]) -> None:
    """
    Apply '--property section.key=value' overrides to CONFIG_TOML in-place.

    Each override must be in 'section.key=value' format.  The value is parsed
    via JSON first (handles bool, int, float, list, dict); if that fails it is
    treated as a plain string.  Unknown section names are rejected; unknown
    property names produce a warning.
    """
    valid_sections = {
        COMMON_SECTION,
        DATA_CLIENT_SECTION,
        WORK_REQUIREMENT_SECTION,
        WORKER_POOL_SECTION,
        COMPUTE_REQUIREMENT_SECTION,
    }
    for override in overrides:
        if "=" not in override:
            print_error(
                f"Invalid --property format '{override}': expected 'section.key=value'"
            )
            exit(1)
        lhs, _, value_str = override.partition("=")
        if "." not in lhs:
            print_error(
                f"Invalid --property format '{override}': "
                f"expected 'section.key=value' (missing section)"
            )
            exit(1)
        section, _, rest = lhs.partition(".")
        if section not in valid_sections:
            print_error(
                f"Unknown section '{section}' in --property '{override}'. "
                f"Valid sections: {', '.join(sorted(valid_sections))}"
            )
            exit(1)
        path = rest.split(".")
        value = _parse_property_value(value_str)
        if section not in config:
            config[section] = {}
        target = config[section]
        for part in path[:-1]:
            target = target.setdefault(part, {})
        target[path[-1]] = value
        display_section = ".".join([section, *path[:-1]])
        print_info(f"Property override: [{display_section}] {path[-1]} = {value!r}")
        if section == COMMON_SECTION and path[0] == VARIABLES and len(path) == 2:
            add_or_update_substitution(path[1], str(value))
            # Command-line-defined variables always take precedence,
            # including over an explicitly selected config file
            CLI_DEFINED_VARIABLES.add(path[1])


# Support for alternative common env. vars; written into the normal vars.
for norm, alt in [
    (YD_KEY, YD_KEY_ALT),
    (YD_SECRET, YD_SECRET_ALT),
    (YD_URL, YD_URL_ALT),
]:
    alt_value = os.getenv(alt)
    if os.getenv(norm) is None and alt_value is not None:
        os.environ[norm] = alt_value

# The YD_CONF environment variable is no longer supported; error out (rather
# than silently ignoring it) so that any remaining usage fails loudly instead
# of quietly loading a different configuration file
if getenv(YD_CONF) is not None:
    print_error(
        f"The '{YD_CONF}' environment variable is no longer supported; "
        "please use the '--config'/'-c' option to select a configuration file"
    )
    exit(1)

# CLI > 'config.toml'
CONFIG_FILE = relpath(
    "config.toml" if ARGS_PARSER.config_file is None else ARGS_PARSER.config_file
)

if ARGS_PARSER.no_config:
    # Suppress use of any TOML config file
    print_info(f"Configuration file ('{CONFIG_FILE}') ignored")
    CONFIG_TOML = {COMMON_SECTION: {}}
    CONFIG_FILE_DIR = os.getcwd()
    if ARGS_PARSER.property_overrides:
        _apply_property_overrides(CONFIG_TOML, ARGS_PARSER.property_overrides)

else:
    # Attempt to load configuration data from TOML file
    try:
        CONFIG_FILE_DIR = dirname(CONFIG_FILE)
        config_dir_abs = abspath(CONFIG_FILE_DIR)
        config_dir_short = Path(config_dir_abs).parts[-1]
        VARIABLE_SUBSTITUTIONS.update(
            {"config_dir_abs": config_dir_abs, "config_dir_name": config_dir_short}
        )
        print_info(f"Loading configuration data from: '{CONFIG_FILE}'")
        CONFIG_TOML: dict = load_toml_file_with_variable_substitutions(CONFIG_FILE)
        try:
            # Strip profile sub-tables from [dataClient] before validation;
            # profile names are user-defined and not in ALL_KEYS.
            toml_for_validation = dict(CONFIG_TOML)
            if DATA_CLIENT_SECTION in toml_for_validation:
                toml_for_validation[DATA_CLIENT_SECTION] = {
                    k: v
                    for k, v in toml_for_validation[DATA_CLIENT_SECTION].items()
                    if not isinstance(v, dict)
                }
            validate_properties(toml_for_validation, f"'{CONFIG_FILE}'")
        except Exception as e:
            print_error(e)
            exit(1)
        if ARGS_PARSER.property_overrides:
            _apply_property_overrides(CONFIG_TOML, ARGS_PARSER.property_overrides)

    except FileNotFoundError as e:
        # An explicitly selected config file ('--config'/'-c') must exist
        if ARGS_PARSER.config_file is not None:
            print_error(e)
            exit(1)
        # No config file, so create a stub config dictionary
        print_info(
            "No configuration file; expecting configuration data on command line "
            "or in environment variables"
        )
        CONFIG_TOML = {COMMON_SECTION: {}}
        CONFIG_FILE_DIR = os.getcwd()

    except (PermissionError, TOMLDecodeError) as e:
        print_error(
            f"Unable to load configuration data from '{CONFIG_FILE}': {e}",
        )
        exit(1)

    except Exception as e:
        print_error(e)
        exit(1)


def load_config_common() -> ConfigCommon:
    """
    Load the configuration values for the 'common' section.
    """
    try:
        common_section = CONFIG_TOML.get(COMMON_SECTION, {})

        # Check for IMPORT directive ('common' section in a separate file)
        common_section_import_file = common_section.pop(IMPORT_COMMON, None)
        if common_section_import_file is not None:
            common_section_imported = import_toml(common_section_import_file)
            # Local properties supersede imported properties
            common_section_imported.update(common_section)
            common_section = common_section_imported

        # Replace common section properties with command line or
        # environment variable overrides. Precedence is:
        # command line > environment variable > config file
        # ... unless the config file was explicitly selected using
        # '--config'/'-c', in which case its contents take precedence
        # over the environment:
        # command line > config file > environment variable
        for key_name, args_parser_value, env_var_name in [
            (KEY, ARGS_PARSER.key, YD_KEY),
            (SECRET, ARGS_PARSER.secret, YD_SECRET),
            (NAMESPACE, ARGS_PARSER.namespace, YD_NAMESPACE),
            (NAME_TAG, ARGS_PARSER.tag, YD_TAG),
            (URL, ARGS_PARSER.url, YD_URL),
        ]:
            if args_parser_value is not None:
                common_section[key_name] = args_parser_value
                print_info(
                    f"Using '{key_name}' provided on command line "
                    "(or automatically set)"
                )
            elif config_file_explicitly_selected() and (
                common_section.get(key_name) is not None
            ):
                pass  # Retain the value from the explicitly selected config file
            elif os.environ.get(env_var_name) is not None:
                common_section[key_name] = os.environ[env_var_name]
                print_info(f"Using '{key_name}' provided via the environment")

        # Provide default values for namespace and tag
        if common_section.get(NAMESPACE) is None:
            common_section[NAMESPACE] = "default"
            if ARGS_PARSER.namespace_required:
                print_info(
                    "Using default value for 'namespace': "
                    f"'{common_section[NAMESPACE]}'"
                )
        if common_section.get(NAME_TAG) is None:
            common_section[NAME_TAG] = "{{username}}"
            if ARGS_PARSER.tag_required:
                print_info(
                    "Using default value for 'tag/prefix/name' = "
                    f"'{VARIABLE_SUBSTITUTIONS['username']}'"
                )

        url = cast(
            str, process_variable_substitutions(common_section.get(URL, DEFAULT_URL))
        )
        if url != DEFAULT_URL:
            print_info(f"Using the YellowDog API at: {url}")

        # Exhaustive variable processing for common section variables
        # Note that add_substitutions() will perform all possible
        # substitutions for the items in its dictionary each time it's
        # called
        add_substitutions_without_overwriting(subs={URL: url})
        key = cast(str, process_variable_substitutions(common_section[KEY]))
        add_substitutions_without_overwriting(subs={KEY: key})
        secret = cast(str, process_variable_substitutions(common_section[SECRET]))
        add_substitutions_without_overwriting(subs={SECRET: secret})
        namespace = cast(str, process_variable_substitutions(common_section[NAMESPACE]))
        add_substitutions_without_overwriting(subs={NAMESPACE: namespace})
        name_tag = cast(str, process_variable_substitutions(common_section[NAME_TAG]))
        add_substitutions_without_overwriting(subs={NAME_TAG: name_tag})

        # Specify a certificates bundle directly by setting the requests
        # environment variable; this will override the default certificates
        certificates = cast(
            str | None,
            process_variable_substitutions(common_section.get(CERTIFICATES)),
        )
        if certificates is not None:
            certificates = abspath(certificates)
            requests_ca_bundle = "REQUESTS_CA_BUNDLE"
            print_info(
                f"Setting environment variable '{requests_ca_bundle}' to '{certificates}'"
            )
            os.environ[requests_ca_bundle] = certificates

        register_dc_substitutions()

        return ConfigCommon(
            # Required
            key=key,
            secret=secret,
            namespace=namespace,
            name_tag=name_tag,
            # Optional
            url=url,
            use_pac=(
                True if ARGS_PARSER.use_pac else common_section.get(USE_PAC, False)
            ),
        )

    except KeyError as e:
        print_error(f"Missing configuration data: {e}")
        exit(1)


def import_toml(filename: str) -> dict:
    filename = relpath(
        join(CONFIG_FILE_DIR, cast(str, process_variable_substitutions(filename)))
    )
    print_info(f"Loading imported common configuration data from: '{filename}'")
    try:
        common_config: dict = load_toml_file_with_variable_substitutions(filename)
        return common_config[COMMON_SECTION]
    except (FileNotFoundError, PermissionError, TOMLDecodeError) as e:
        print_error(f"Unable to load imported common configuration data: {e}")
        exit(1)


def _load_namespace_and_tag() -> None:
    """
    Populate VARIABLE_SUBSTITUTIONS with 'namespace' and 'tag' without
    requiring a full common config load (no key/secret needed).
    Priority: CLI flags > environment variables > [common] section in config.toml > defaults.
    Safe to call before load_config_common(); won't overwrite values it sets.
    """
    common_section = dict(CONFIG_TOML.get(COMMON_SECTION, {}))

    # Handle importCommon: merge namespace/tag from the imported file.
    # Use .get() (not .pop()) so CONFIG_TOML is left intact for load_config_common().
    import_file = common_section.get(IMPORT_COMMON)
    if import_file is not None:
        imported = import_toml(str(import_file))
        # Imported values are baseline; local section takes precedence
        common_section = {**imported, **common_section}

    explicit_config = config_file_explicitly_selected()

    if ARGS_PARSER.namespace is not None:
        namespace = ARGS_PARSER.namespace
    elif explicit_config and common_section.get(NAMESPACE) is not None:
        namespace = str(common_section[NAMESPACE])
    elif os.environ.get(YD_NAMESPACE) is not None:
        namespace = os.environ[YD_NAMESPACE]
    elif common_section.get(NAMESPACE) is not None:
        namespace = str(common_section[NAMESPACE])
    else:
        namespace = "default"
    namespace = process_variable_substitutions(namespace)

    if ARGS_PARSER.tag is not None:
        name_tag = ARGS_PARSER.tag
    elif explicit_config and common_section.get(NAME_TAG) is not None:
        name_tag = str(common_section[NAME_TAG])
    elif os.environ.get(YD_TAG) is not None:
        name_tag = os.environ[YD_TAG]
    elif common_section.get(NAME_TAG) is not None:
        name_tag = str(common_section[NAME_TAG])
    else:
        name_tag = "{{username}}"
    name_tag = process_variable_substitutions(name_tag)

    add_substitutions_without_overwriting(
        subs={NAMESPACE: namespace, NAME_TAG: name_tag}
    )


def _build_dc_substitutions(base: dict) -> dict:
    """
    Build the {{dataClient.*}} substitution dict from the raw [dataClient] TOML section.

    Returns raw (pre-substitution) string values; variable resolution is applied
    by the caller via add_substitutions_without_overwriting.

    Produces:
    - {{dataClient.remote/bucket/prefix}} from the base scalar fields
    - {{dataClient.<name>.remote/bucket/prefix}} for each named profile sub-table,
      with unset profile fields inherited from the base
    """
    scalars = {k: v for k, v in base.items() if not isinstance(v, dict)}
    subs: dict = {}

    for field in (DATA_CLIENT_REMOTE, DATA_CLIENT_BUCKET, DATA_CLIENT_PREFIX):
        value = scalars.get(field)
        if value is not None:
            subs[f"{DATA_CLIENT_SECTION}.{field}"] = str(value)

    for name, profile in base.items():
        if not isinstance(profile, dict):
            continue
        merged = {**scalars, **profile}
        for field in (DATA_CLIENT_REMOTE, DATA_CLIENT_BUCKET, DATA_CLIENT_PREFIX):
            value = merged.get(field)
            if value is not None:
                subs[f"{DATA_CLIENT_SECTION}.{name}.{field}"] = str(value)

    return subs


def register_dc_substitutions() -> None:
    """
    Register {{dataClient.*}} variable substitutions from the [dataClient] TOML section.

    Must be called after namespace and tag are registered (i.e. after
    load_config_common or _load_namespace_and_tag) so that prefix values
    containing {{namespace}}/{{tag}} resolve correctly.

    Called from load_config_common() for all @main_wrapper commands, and from
    load_config_data_client() for data client commands (which bypass main_wrapper).
    """
    base = CONFIG_TOML.get(DATA_CLIENT_SECTION, {})
    if not base:
        return
    subs = _build_dc_substitutions(base)
    if subs:
        add_substitutions_without_overwriting(subs)


def _select_dc_section(base: dict, profile_name: str | None) -> dict:
    """
    From the raw [dataClient] TOML dict (which may contain named profile sub-tables),
    return the merged scalar section to use.

    If profile_name is None: return only scalar (non-dict) entries from base.
    If profile_name is given: merge scalar base entries with the named profile's
    entries, with the profile taking precedence. Raises ValueError if not found.
    """
    scalars = {k: v for k, v in base.items() if not isinstance(v, dict)}
    if profile_name is None:
        return scalars
    profile = base.get(profile_name)
    if not isinstance(profile, dict):
        raise ValueError(
            f"Data client profile '[{DATA_CLIENT_SECTION}.{profile_name}]' not found in config"
        )
    return {**scalars, **profile}


def load_config_data_client() -> ConfigDataClient:
    """
    Load the configuration data for the data client (rclone-backed commands).
    Priority: CLI flags > environment variables > TOML config.
    Named profiles ([dataClient.<name>]) inherit unset fields from [dataClient].
    Resolved values are registered in VARIABLE_SUBSTITUTIONS for use in specs.
    """
    _load_namespace_and_tag()
    # Register all {{dataClient.*}} vars for data client commands, which bypass
    # load_config_common() and therefore don't get this called automatically.
    register_dc_substitutions()
    base_section = CONFIG_TOML.get(DATA_CLIENT_SECTION, {})

    profile_name = getattr(ARGS_PARSER, "data_client_profile", None) or os.environ.get(
        YD_DATA_CLIENT
    )
    if profile_name is not None:
        try:
            dc_section = _select_dc_section(base_section, profile_name)
        except ValueError as e:
            print_error(e)
            exit(1)
        print_info(f"Using data client profile: '{profile_name}'")
    else:
        dc_section = _select_dc_section(base_section, None)

    for _ in range(TOML_VAR_NESTED_DEPTH):
        process_variable_substitutions_insitu(dc_section)

    def _resolve(cli_value: str | None, env_var: str, toml_key: str) -> str | None:
        if cli_value is not None:
            return cast(str | None, process_variable_substitutions(cli_value))
        toml_value = dc_section.get(toml_key)
        if config_file_explicitly_selected() and toml_value is not None:
            return cast(str | None, process_variable_substitutions(str(toml_value)))
        env_value = os.environ.get(env_var)
        if env_value is not None:
            return cast(str | None, process_variable_substitutions(env_value))
        if toml_value is not None:
            return cast(str | None, process_variable_substitutions(str(toml_value)))
        return None

    remote = _resolve(
        getattr(ARGS_PARSER, "remote", None), YD_DATA_CLIENT_REMOTE, DATA_CLIENT_REMOTE
    )
    bucket = _resolve(
        getattr(ARGS_PARSER, "bucket", None), YD_DATA_CLIENT_BUCKET, DATA_CLIENT_BUCKET
    )

    if getattr(ARGS_PARSER, "no_prefix", False):
        prefix = None
    else:
        prefix = _resolve(
            getattr(ARGS_PARSER, "prefix", None),
            YD_DATA_CLIENT_PREFIX,
            DATA_CLIENT_PREFIX,
        )
        if prefix is None:
            prefix = cast(
                str | None, process_variable_substitutions("{{namespace}}/{{tag}}")
            )

    # Register legacy {{remote/bucket/prefix}} names (backward compat).
    add_substitutions_without_overwriting(
        subs={
            k: v
            for k, v in {
                DATA_CLIENT_REMOTE: remote,
                DATA_CLIENT_BUCKET: bucket,
                DATA_CLIENT_PREFIX: prefix,
            }.items()
            if v is not None
        }
    )

    # Register {{dataClient.remote/bucket/prefix}} with the fully-resolved active
    # profile values, overwriting whatever register_dc_substitutions() set from the
    # base section (active profile takes precedence).
    for key, value in {
        f"{DATA_CLIENT_SECTION}.{DATA_CLIENT_REMOTE}": remote,
        f"{DATA_CLIENT_SECTION}.{DATA_CLIENT_BUCKET}": bucket,
        f"{DATA_CLIENT_SECTION}.{DATA_CLIENT_PREFIX}": prefix,
    }.items():
        if value is not None:
            add_or_update_substitution(key, value)

    return ConfigDataClient(remote=remote, bucket=bucket, prefix=prefix)


def load_config_data_client_for_profile(
    profile_name: str | None,
    dst_prefix_override: str | None = None,
) -> ConfigDataClient:
    """
    Load a destination data client config for yd-copy.

    CLI source-side flags (--remote, --bucket, --prefix, --no-prefix,
    --data-client-profile) are NOT applied; only TOML + env vars are used.
    dst_prefix_override (from --dst-prefix) takes highest priority.
    Pass an empty string to suppress the default prefix entirely.
    """
    _load_namespace_and_tag()
    base_section = CONFIG_TOML.get(DATA_CLIENT_SECTION, {})

    try:
        dc_section = _select_dc_section(base_section, profile_name)
    except ValueError as e:
        print_error(e)
        exit(1)

    if profile_name is not None:
        print_info(f"Using destination data client profile: '{profile_name}'")

    for _ in range(TOML_VAR_NESTED_DEPTH):
        process_variable_substitutions_insitu(dc_section)

    def _resolve(env_var: str, toml_key: str) -> str | None:
        toml_value = dc_section.get(toml_key)
        if config_file_explicitly_selected() and toml_value is not None:
            return cast(str | None, process_variable_substitutions(str(toml_value)))
        env_value = os.environ.get(env_var)
        if env_value is not None:
            return cast(str | None, process_variable_substitutions(env_value))
        if toml_value is not None:
            return cast(str | None, process_variable_substitutions(str(toml_value)))
        return None

    remote = _resolve(YD_DATA_CLIENT_REMOTE, DATA_CLIENT_REMOTE)
    bucket = _resolve(YD_DATA_CLIENT_BUCKET, DATA_CLIENT_BUCKET)

    if dst_prefix_override is not None:
        prefix = cast(str | None, process_variable_substitutions(dst_prefix_override))
    else:
        prefix = _resolve(YD_DATA_CLIENT_PREFIX, DATA_CLIENT_PREFIX)
        if prefix is None:
            prefix = cast(
                str | None, process_variable_substitutions("{{namespace}}/{{tag}}")
            )

    return ConfigDataClient(remote=remote, bucket=bucket, prefix=prefix)


def load_config_work_requirement() -> ConfigWorkRequirement:
    """
    Load the configuration data for a Work Requirement
    """
    try:
        wr_section = CONFIG_TOML[WORK_REQUIREMENT_SECTION]
    except KeyError:
        return ConfigWorkRequirement()

    # Process any new substitutions after the common config
    # has been processed
    for _ in range(TOML_VAR_NESTED_DEPTH):
        process_variable_substitutions_insitu(wr_section)

    try:
        # Allow WORKER_TAG if WORKER_TAGS is empty
        worker_tags = wr_section.get(WORKER_TAGS)
        if worker_tags is None:
            try:
                worker_tags = [wr_section[WORKER_TAG]]
            except KeyError:
                pass
        if worker_tags is not None:
            check_list(worker_tags)
            for index, worker_tag in enumerate(worker_tags):
                worker_tags[index] = cast(
                    str, process_variable_substitutions(worker_tag)
                )

        wr_data_file = wr_section.get(WR_DATA)
        if wr_data_file is not None:
            check_str(wr_data_file)
            wr_data_file = cast(str, process_variable_substitutions(wr_data_file))
            wr_data_file = pathname_relative_to_config_file(
                CONFIG_FILE_DIR, wr_data_file
            )

        # Check for properties set on the command line
        task_type = (
            wr_section.get(TASK_TYPE)
            if ARGS_PARSER.task_type is None
            else ARGS_PARSER.task_type
        )
        if task_type is not None:
            check_str(task_type)
            task_type = cast(str | None, process_variable_substitutions(task_type))

        csv_file = wr_section.get(CSV_FILE)
        csv_files = wr_section.get(CSV_FILES)
        if csv_file and csv_files:
            print_error("Only one of 'csvFile' and 'csvFiles' should be set")
            exit(1)
        if csv_file:
            csv_files = [csv_file]

        task_batch_size = (
            wr_section.get(TASK_BATCH_SIZE, TASK_BATCH_SIZE_DEFAULT)
            if ARGS_PARSER.task_batch_size is None
            else ARGS_PARSER.task_batch_size
        )

        task_count = (
            ARGS_PARSER.task_count
            if ARGS_PARSER.task_count is not None
            else wr_section.get(TASK_COUNT, 1)
        )

        task_group_count = (
            ARGS_PARSER.task_group_count
            if ARGS_PARSER.task_group_count is not None
            else wr_section.get(TASK_GROUP_COUNT, 1)
        )

        return ConfigWorkRequirement(
            add_environment=wr_section.get(ADD_ENVIRONMENT),
            add_yd_env_vars=wr_section.get(ADD_YD_ENV_VARS, False),
            args=wr_section.get(ARGS, []),
            args_postfix=wr_section.get(ARGS_POSTFIX),
            args_prefix=wr_section.get(ARGS_PREFIX),
            completed_task_ttl=wr_section.get(COMPLETED_TASK_TTL),
            csv_files=cast(list[str] | None, csv_files),
            disable_preallocation=wr_section.get(DISABLE_PREALLOCATION),
            env=wr_section.get(ENV, {}),
            finish_if_all_tasks_finished=wr_section.get(
                FINISH_IF_ALL_TASKS_FINISHED, True
            ),
            finish_if_any_task_failed=wr_section.get(FINISH_IF_ANY_TASK_FAILED, False),
            instance_pricing_preference=wr_section.get(INSTANCE_PRICING_PREFERENCE),
            instance_types=wr_section.get(INSTANCE_TYPES),
            max_retries=wr_section.get(MAX_RETRIES),
            max_workers=wr_section.get(MAX_WORKERS),
            min_workers=wr_section.get(MIN_WORKERS),
            namespaces=wr_section.get(NAMESPACES),
            parallel_batches=wr_section.get(PARALLEL_BATCHES),
            priority=wr_section.get(PRIORITY),
            providers=wr_section.get(PROVIDERS),
            ram=wr_section.get(RAM),
            regions=wr_section.get(REGIONS),
            retry_policy=wr_section.get(RETRY_POLICY),
            retryable_errors=wr_section.get(RETRYABLE_ERRORS),
            failure_policy=wr_section.get(FAILURE_POLICY),
            set_task_names=wr_section.get(SET_TASK_NAMES, True),
            task_batch_size=task_batch_size,
            task_count=task_count,
            task_data=wr_section.get(TASK_DATA),
            task_data_file=wr_section.get(TASK_DATA_FILE),
            task_data_files=wr_section.get(TASK_DATA_FILES),
            task_data_inputs=wr_section.get(TASK_DATA_INPUTS),
            task_data_outputs=wr_section.get(TASK_DATA_OUTPUTS),
            task_group_count=task_group_count,
            task_group_name=wr_section.get(TASK_GROUP_NAME),
            task_name=wr_section.get(TASK_NAME),
            task_template=wr_section.get(TASK_TEMPLATE),
            task_timeout=wr_section.get(TASK_TIMEOUT),
            task_type=task_type,
            tasks_per_worker=wr_section.get(TASKS_PER_WORKER),
            task_level_timeout=wr_section.get(TASK_LEVEL_TIMEOUT),
            vcpus=wr_section.get(VCPUS),
            worker_tags=worker_tags,
            wr_data_file=wr_data_file,
            wr_name=wr_section.get(WR_NAME),
            wr_tag=wr_section.get(WR_TAG),
        )

    except KeyError as e:
        print_error(f"Missing configuration data: {e}")
        exit(1)

    except Exception as e:
        print_error(f"{e}")
        exit(1)


def load_config_worker_pool() -> ConfigWorkerPool:
    """
    Load the configuration data for a Worker Pool or a Compute Requirement.
    """

    # Allow the use of values in a 'computeRequirement' section, which acts
    # as a configuration synonym for 'workerPool'. Check for duplicates.
    wp_section = CONFIG_TOML.get(WORKER_POOL_SECTION, {})
    cr_section = CONFIG_TOML.get(COMPUTE_REQUIREMENT_SECTION, {})

    # Process any new substitutions after the common config
    # has been processed
    for _ in range(TOML_VAR_NESTED_DEPTH):
        process_variable_substitutions_insitu(wp_section)
        process_variable_substitutions_insitu(cr_section)

    duplicate_keys = set(wp_section.keys()).intersection(set(cr_section.keys()))
    if duplicate_keys:
        print_error(
            f"Duplicate keys in '{WORKER_POOL_SECTION}' and"
            f" '{COMPUTE_REQUIREMENT_SECTION}': {duplicate_keys}"
        )
        exit(1)
    wp_section.update(cr_section)

    if not wp_section:
        return ConfigWorkerPool()

    try:
        worker_tag = cast(
            str | None, process_variable_substitutions(wp_section.get(WORKER_TAG))
        )
        worker_pool_data_file = cast(
            str | None,
            process_variable_substitutions(wp_section.get(WORKER_POOL_DATA_FILE)),
        )
        compute_requirement_data_file = cast(
            str | None,
            process_variable_substitutions(
                wp_section.get(COMPUTE_REQUIREMENT_DATA_FILE)
            ),
        )
        if (
            worker_pool_data_file is not None
            and compute_requirement_data_file is not None
        ):
            print_error(
                f"Only one of '{WORKER_POOL_DATA_FILE}' or"
                f" '{COMPUTE_REQUIREMENT_DATA_FILE}' should be set"
            )
            exit(1)
        if worker_pool_data_file is not None:
            worker_pool_data_file = pathname_relative_to_config_file(
                CONFIG_FILE_DIR, worker_pool_data_file
            )
        if compute_requirement_data_file is not None:
            compute_requirement_data_file = pathname_relative_to_config_file(
                CONFIG_FILE_DIR, compute_requirement_data_file
            )
        workers_per_vcpu = (
            None
            if wp_section.get(WORKERS_PER_VCPU) is None
            else int(wp_section[WORKERS_PER_VCPU])
        )

        cr_batch_size = wp_section.get(COMPUTE_REQUIREMENT_BATCH_SIZE, CR_MAX_INSTANCES)
        if cr_batch_size > CR_MAX_INSTANCES:
            print_warning(
                f"'computeRequirementBatchSize' ({cr_batch_size:,d}) exceeds the"
                f" platform maximum ({CR_MAX_INSTANCES:,d}); clamping to"
                f" {CR_MAX_INSTANCES:,d}"
            )
            cr_batch_size = CR_MAX_INSTANCES

        return ConfigWorkerPool(
            compute_requirement_batch_size=cr_batch_size,
            compute_requirement_data_file=compute_requirement_data_file,
            cr_tag=wp_section.get(CR_TAG),
            idle_node_timeout=float(wp_section.get(IDLE_NODE_TIMEOUT, 5.0)),
            idle_pool_timeout=float(wp_section.get(IDLE_POOL_TIMEOUT, 30.0)),
            images_id=wp_section.get(IMAGES_ID),
            instance_tags=wp_section.get(INSTANCE_TAGS),
            maintainInstanceCount=wp_section.get(MAINTAIN_INSTANCE_COUNT, False),
            max_nodes=wp_section.get(
                MAX_NODES, max(1, int(wp_section.get(TARGET_INSTANCE_COUNT, 1)))
            ),
            max_nodes_set=(False if wp_section.get(MAX_NODES) is None else True),
            metrics_enabled=wp_section.get(METRICS_ENABLED, False),
            min_nodes=int(wp_section.get(MIN_NODES, 0)),
            min_nodes_set=(False if wp_section.get(MIN_NODES) is None else True),
            name=cast(
                str | None,
                process_variable_substitutions(wp_section.get(WP_NAME)),
            ),
            node_boot_timeout=float(wp_section.get(NODE_BOOT_TIMEOUT, 10.0)),
            target_instance_count=int(wp_section.get(TARGET_INSTANCE_COUNT, 1)),
            target_instance_count_set=(
                False if wp_section.get(TARGET_INSTANCE_COUNT) is None else True
            ),
            template_id=wp_section.get(TEMPLATE_ID),
            user_data=wp_section.get(USERDATA),
            user_data_file=wp_section.get(USERDATAFILE),
            user_data_files=wp_section.get(USERDATAFILES),
            worker_pool_data_file=worker_pool_data_file,
            worker_tag=worker_tag,
            workers_custom_command=wp_section.get(WORKERS_CUSTOM_COMMAND),
            workers_per_vcpu=workers_per_vcpu,
            workers_per_node=int(wp_section.get(WORKERS_PER_NODE, 1)),
        )

    except KeyError as e:
        print_error(f"Missing configuration data: {e}")
        exit(1)

    except ValueError as e:
        print_error(f"Invalid type for configuration: {e}")
        exit(1)
