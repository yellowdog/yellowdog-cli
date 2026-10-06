"""
Configuration and environment constants: the default URL, the YD_*
environment variable names, name prefixes and separators, supported Python
versions, and the schema families. Other constants live by concern:
exit_codes.py (ExitCode), limits.py, variable_syntax.py, output_style.py,
entity_names.py and property_names.py (the PROP_* names).
"""

DEFAULT_URL = "https://api.yellowdog.ai"

# Reported when a required configuration property is absent from every
# source, by each of load_config.py's section loaders.
MISSING_CONFIG_DATA = "Missing configuration data"

# Environment variables
YD_KEY = "YD_KEY"
YD_SECRET = "YD_SECRET"
YD_NAMESPACE = "YD_NAMESPACE"
YD_TAG = "YD_TAG"
YD_URL = "YD_URL"
YD_DATA_CLIENT = "YD_DATA_CLIENT"
YD_DATA_CLIENT_BUCKET = "YD_DATA_CLIENT_BUCKET"
YD_DATA_CLIENT_PREFIX = "YD_DATA_CLIENT_PREFIX"
YD_DATA_CLIENT_REMOTE = "YD_DATA_CLIENT_REMOTE"
YD_ENV_VAR_PREFIX = "YD_VAR_"
YD_ENV_OVERRIDE = "YD_ENV_OVERRIDE"
# Alternative env.var names
YD_KEY_ALT = "YD_API_KEY_ID"
YD_SECRET_ALT = "YD_API_KEY_SECRET"
YD_URL_ALT = "YD_API_URL"

# The MCP server's name to its clients (yellowdog_cli/mcp/)
MCP_SERVER_NAME = "yellowdog-cli"

# yd-doctor
PYTHON_MIN_VERSION = (
    3,
    10,
)  # must match pyproject.toml's requires-python; a test holds them together
PYTHON_MAX_TESTED_VERSION = (3, 14)
PYPI_PROJECT_URL = "https://pypi.org/pypi/yellowdog-cli/json"

# Prepended by format_yd_name() to a name that doesn't start with a letter.
# The underscore is what makes the prefix visible as a prefix: bare 'yd' merges
# into the name it is fixing, so 'yd2024-run' reads as a name the user chose.
NAME_START_PREFIX = "yd_"
NAMESPACE_PREFIX_SEPARATOR = "/"
RCLONE_PREFIX = "rclone:"

# The specification families yd-schema knows, in utils/specs/schema.py's
# Family order. Carried here, as a plain tuple, rather than imported from
# specs/schema.py: that module reaches into the installed SDK and compiles
# fastjsonschema at class-definition time, and command_registry.py (which
# needs these values for --list's choices) is imported by every command's
# parse and by yellowdog_cli/mcp/tools.py, which must stay SDK-free.
# tests/test_spec_schema.py holds this to Family.
SCHEMA_FAMILIES: tuple[str, ...] = (
    "work-requirement",
    "worker-pool",
    "compute-requirement",
    "resources",
    "node-actions",
    "config",
)
