"""
String and numeric constants, etc.
"""

import re

DEFAULT_URL = "https://api.yellowdog.ai"

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
YD_CONF = "YD_CONF"
ENV_VAR_SUB_PREFIX = "env:"
RAND_VAR_SIZE = 0xFFF

# Alternative env.var names
YD_KEY_ALT = "YD_API_KEY_ID"
YD_SECRET_ALT = "YD_API_KEY_SECRET"
YD_URL_ALT = "YD_API_URL"

TASK_BATCH_SIZE_DEFAULT = 1_000
DEFAULT_PARALLEL_TASK_BATCH_UPLOAD_THREADS = 1
MAX_BATCH_SUBMIT_ATTEMPTS = 4  # Initial attempt plus retries

CR_MAX_INSTANCES = (
    10_000  # This is enforced by the platform (MAX_WORKER_POOL_NODE_COUNT)
)

EVENT_STREAM_RETRY_INTERVAL = 5.0  # Seconds
EVENT_STREAM_CONNECT_TIMEOUT = 10.0  # Seconds
# Generous read timeout: a silently dropped connection must not block the
# event stream forever; a timeout during a quiet period just reconnects
EVENT_STREAM_READ_TIMEOUT = 300.0  # Seconds
NODE_ACTION_QUEUE_POLL_INTERVAL = 5.0  # Seconds

NAMESPACE_PREFIX_SEPARATOR = "/"
WP_VARIABLES_PREFIX = "__"
WP_VARIABLES_POSTFIX = "__"
CSV_VAR_OPENING_DELIMITER = "<<"
CSV_VAR_CLOSING_DELIMITER = ">>"
VAR_OPENING_DELIMITER = "{{"
VAR_CLOSING_DELIMITER = "}}"
VAR_DEFAULT_SEPARATOR = ":="
VAR_UNSET_SUFFIX = "::"

# Lazy variable substitution names (used in submit/task naming)
L_WR_NAME = "wr_name"
L_TASK_NAME = "task_name"
L_TASK_NUMBER = "task_number"
L_TASK_GROUP_NAME = "task_group_name"
L_TASK_GROUP_NUMBER = "task_group_number"
L_TASK_COUNT = "task_count"
L_TASK_GROUP_COUNT = "task_group_count"

TYPE_TAG_TERMINATOR = ":"
# The character(s) of VAR_DEFAULT_SEPARATOR that follow TYPE_TAG_TERMINATOR.
# Used as a negative lookahead in the type-tag regex: after matching e.g. 'num:',
# if this follows, the ':' is part of ':=' (a default separator), not a type tag.
TYPE_TAG_DEFAULT_GUARD = VAR_DEFAULT_SEPARATOR[len(TYPE_TAG_TERMINATOR) :]
NUMBER_TYPE_TAG = "num" + TYPE_TAG_TERMINATOR
BOOL_TYPE_TAG = "bool" + TYPE_TAG_TERMINATOR
ARRAY_TYPE_TAG = "array" + TYPE_TAG_TERMINATOR
TABLE_TYPE_TAG = "table" + TYPE_TAG_TERMINATOR
FORMAT_NAME_TYPE_TAG = "format_name" + TYPE_TAG_TERMINATOR
TOML_VAR_NESTED_DEPTH = 3
RCLONE_PREFIX = "rclone:"

VAR_NAME_OF_UNNAMED_TASK = "none"

DEFAULT_LOG_WIDTH = 120
MAX_TABLE_DESCRIPTION = 50
MAX_LINES_COLOURED_FORMATTING = 1024
ERROR_STYLE = "bold red3"
WARNING_STYLE = "red3"
DEBUG_STYLE = "dark_orange"
JSON_INDENT = 2
HIGHLIGHTED_STATES = [
    re.compile(r"(?P<active>ALLOCATED)"),
    re.compile(r"(?P<active>DOING_TASK)"),
    re.compile(r"(?P<active>BATCH_ALLOCATION)"),
    re.compile(r"(?P<active>EXECUTING)"),
    re.compile(r"(?P<active>EXPECTED)"),
    re.compile(r"(?P<active>PENDING)"),
    re.compile(r"(?P<active>READY)"),
    re.compile(r"(?P<active>RUNNING)"),
    re.compile(r"(?P<active>TARGET)"),
    re.compile(r"(?P<active>ALIVE)"),
    re.compile(r"(?P<active>MATCHING)"),
    re.compile(r"(?P<active>MAYBE MATCHING)"),
    re.compile(r"(?P<active>FINISHING)"),
    re.compile(r"(?P<cancelled>ABORTED)"),
    re.compile(r"(?P<cancelled>CANCELLED)"),
    re.compile(r"(?P<cancelled>CANCELLING)"),
    re.compile(r"(?P<cancelled>DEREGISTERED)"),
    re.compile(r"(?P<cancelled>SHUTDOWN)"),
    re.compile(r"(?P<cancelled>STOPPED)"),
    re.compile(r"(?P<cancelled>TERMINATED)"),
    re.compile(r"(?P<completed>COMPLETED)"),
    re.compile(r"(?P<failed>FAILED)"),
    re.compile(r"(?P<failed>FAILING)"),
    re.compile(r"(?P<failed>LOST)"),
    re.compile(r"(?P<failed>NON-MATCHING)"),
    re.compile(r"(?P<idle>EMPTY)"),
    re.compile(r"(?P<idle>FOUND)"),
    re.compile(r"(?P<idle>IDLE)"),
    re.compile(r"(?P<idle>SLEEPING)"),
    re.compile(r"(?P<idle>STOPPED)"),
    re.compile(r"(?P<idle>STARTING)"),
    re.compile(r"(?P<idle>WAITING)"),
    re.compile(r"(?P<idle>HELD)"),
    re.compile(r"(?P<starved>STARVED)"),
    re.compile(r"(?P<transitioning>CONFIGURING)"),
    re.compile(r"(?P<transitioning>DOWNLOADING)"),
    # re.compile(r"(?P<transitioning>LATE$)"),
    re.compile(r"(?P<transitioning>NEW)"),
    re.compile(r"(?P<transitioning>PROVISIONING)"),
    re.compile(r"(?P<transitioning>STOPPING)"),
    re.compile(r"(?P<transitioning>TERMINATING)"),
    re.compile(r"(?P<transitioning>UNAVAILABLE)"),
    re.compile(r"(?P<transitioning>UNKNOWN)"),
    re.compile(r"(?P<transitioning>UPLOADING)"),
]
# For Rich colour options, see colour list & swatches at:
# https://rich.readthedocs.io/en/stable/appendix/colors.html
DEFAULT_THEME = {
    "pyexamples.date_time": "bold deep_sky_blue1",
    "pyexamples.quoted": "bold green4",
    "pyexamples.url": "bold green4",
    "pyexamples.ydid": "bold dark_orange",
    "pyexamples.table_outline": "bold deep_sky_blue4",
    "pyexamples.table_content": "bold green4",
    "pyexamples.transitioning": "bold dark_orange",
    "pyexamples.executing": "bold deep_sky_blue4",
    "pyexamples.failed": "bold red3",
    "pyexamples.completed": "bold green4",
    "pyexamples.cancelled": "bold grey35",
    "pyexamples.active": "bold deep_sky_blue4",
    "pyexamples.idle": "bold dark_goldenrod",
    "pyexamples.starved": "bold dark_orange",
}

# Resource type names for create/remove
RESOURCE_PROPERTY_NAME = "resource"
RN_ADD_APPLICATION_REQUEST = "AddApplicationRequest"
RN_ADD_GROUP_REQUEST = "AddGroupRequest"
RN_ALLOWANCE = "Allowance"
RN_APPLICATION = "Application"
RN_CONFIGURED_POOL = "ConfiguredWorkerPool"
RN_CREDENTIAL = "Credential"
RN_EXTERNAL_USER = "ExternalUser"
RN_GROUP = "Group"
RN_IMAGE_FAMILY = "MachineImageFamily"
RN_INTERNAL_USER = "InternalUser"
RN_KEYRING = "Keyring"
RN_NAMESPACE = "Namespace"
RN_NAMESPACE_POLICY = "NamespacePolicy"
RN_NUMERIC_ATTRIBUTE_DEFINITION = "NumericAttributeDefinition"
RN_REQUIREMENT_TEMPLATE = "ComputeRequirementTemplate"
RN_ROLE = "Role"
RN_SOURCE_TEMPLATE = "ComputeSourceTemplate"
RN_STRING_ATTRIBUTE_DEFINITION = "StringAttributeDefinition"
RN_UPDATE_APPLICATION_REQUEST = "UpdateApplicationRequest"
RN_UPDATE_GROUP_REQUEST = "UpdateGroupRequest"

# Entity type names (used as CLI arguments and for dispatch)
ET_ALLOWANCES = "allowances"
ET_APPLICATIONS = "applications"
ET_ATTRIBUTE_DEFINITIONS = "attribute-definitions"
ET_COMPUTE_REQUIREMENT_TEMPLATES = "compute-requirement-templates"
ET_COMPUTE_REQUIREMENTS = "compute-requirements"
ET_COMPUTE_SOURCE_TEMPLATES = "compute-source-templates"
ET_GROUPS = "groups"
ET_IMAGE_FAMILIES = "image-families"
ET_INSTANCES = "instances"
ET_KEYRINGS = "keyrings"
ET_NAMESPACE_POLICIES = "namespace-policies"
ET_NAMESPACES = "namespaces"
ET_NODES = "nodes"
ET_PERMISSIONS = "permissions"
ET_ROLES = "roles"
ET_TASK_GROUPS = "task-groups"
ET_TASKS = "tasks"
ET_USERS = "users"
ET_WORK_REQUIREMENTS = "work-requirements"
ET_WORKER_POOLS = "worker-pools"
ET_WORKERS = "workers"

# Property Names
PROP_ACCESS_DELEGATES = "accessDelegates"
PROP_ADMIN_GROUP = "adminGroup"
PROP_AUTOSCALING_MAX_NODES = "autoscalingMaxNodes"
PROP_CREATED_BY_ID = "createdById"
PROP_CREATED_BY_USER_ID = "createdByUserId"
PROP_CREATED_TIME = "createdTime"
PROP_CREDENTIAL = "credential"
PROP_CST_ID = "sourceTemplateId"
PROP_DEFAULT_RANK_ORDER = "defaultRankOrder"
PROP_DELETABLE = "deletable"
PROP_DESCRIPTION = "description"
PROP_EFFECTIVE_FROM = "effectiveFrom"
PROP_EFFECTIVE_UNTIL = "effectiveUntil"
PROP_GLOBAL = "global"
PROP_GROUPS = "groups"
PROP_ID = "id"
PROP_IMAGE = "image"
PROP_IMAGES_ID = "imagesId"
PROP_IMAGE_ID = "imageId"
PROP_INSTANCE_PRICING = "instancePricing"
PROP_KEYRING = "keyring"
PROP_KEYRING_NAME = "keyringName"
PROP_KEYRINGS = "keyrings"
PROP_NAME = "name"
PROP_NAMESPACE = "namespace"
PROP_NAMESPACES = "namespaces"
PROP_OPTIONS = "options"
PROP_OS_TYPE = "osType"
PROP_PROVIDER = "provider"
PROP_RANGE = "range"
PROP_REMAINING_HOURS = "remainingHours"
PROP_REQUIREMENT_CREATED_FROM = "requirementCreatedFromId"
PROP_RESOURCE = "resource"
PROP_ROLE = "role"
PROP_ROLES = "roles"
PROP_SCOPE = "scope"
PROP_SOURCE = "source"
PROP_SOURCES = "sources"
PROP_SOURCE_CREATED_FROM = "sourceCreatedFromId"
PROP_SUPPORTING_RESOURCE_CREATED = "supportingResourceCreated"
PROP_TITLE = "title"
PROP_TRAITS = "traits"
PROP_TYPE = "type"
PROP_UNITS = "units"
PROP_USERNAME = "username"
