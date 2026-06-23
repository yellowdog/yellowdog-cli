"""
Property names.
"""

ACTION_CONTENT = "content"  # String - file content for writeFile action
ACTION_CONTENT_FILE = "contentFile"  # String - path to file whose content to use
ACTION_CONTENT_FILES = "contentFiles"  # List - paths to files to concatenate
ACTION_GROUPS = "actionGroups"  # List - grouped node actions
ACTION_PATH = "path"  # String - command/file path
ACTION_TYPE = "type"  # String - "runCommand", "writeFile", "createWorkers"
ACTIONS = "actions"  # List - flat node actions
ADD_ENVIRONMENT = "addEnvironment"  # Dict
ADD_YD_ENV_VARS = "addYDEnvironment"
ARGS = "arguments"  # List
ARGS_PREFIX = "argumentsPrefix"  # List
ARGS_POSTFIX = "argumentsPostfix"  # List
CERTIFICATES = "certificates"
COMMON_SECTION = "common"  # No value
COMPLETED_TASK_TTL = "completedTaskTtl"  # Float
COMPUTE_REQUIREMENT_BATCH_SIZE = "computeRequirementBatchSize"  # Integer
COMPUTE_REQUIREMENT_DATA_FILE = "computeRequirementData"  # String
COMPUTE_REQUIREMENT_SECTION = "computeRequirement"  # No value
CR_TAG = "requirementTag"  # String
CSV_FILE = "csvFile"  # String
CSV_FILES = "csvFiles"  # List of Strings
DATA_CLIENT_BUCKET = "bucket"  # String
DATA_CLIENT_LOCAL_PATH = "localPath"  # String
DATA_CLIENT_PREFIX = "prefix"  # String
DATA_CLIENT_REMOTE = "remote"  # String
DATA_CLIENT_SECTION = "dataClient"  # No value
DATA_CLIENT_UPLOAD_PATH = "uploadPath"  # String
DEPENDENCIES = "dependencies"  # List of Strings
DEPENDENT_ON = "dependentOn"  # String (Deprecated)
DESTINATION_TASK_GROUP = "destinationTaskGroup"  # String (for ResubmissionDestination)
DIRECTORY_NAME = "directoryName"  # String
DISABLE_PREALLOCATION = "disablePreallocation"
ENV = "environment"  # Dictionary
ERROR_TYPES = "errorTypes"  # List of Strings
FAILURE_POLICY = "failurePolicy"  # Dict
FINISH_IF_ALL_TASKS_FINISHED = "finishIfAllTasksFinished"  # Boolean
FINISH_IF_ANY_TASK_FAILED = "finishIfAnyTaskFailed"  # Boolean
IDLE_NODE_TIMEOUT = "idleNodeTimeout"  # Float
IDLE_POOL_TIMEOUT = "idlePoolTimeout"  # Float
IMAGES_ID = "imagesId"  # String
IMPORT_COMMON = "importCommon"  # String
INSTANCE_PRICING_PREFERENCE = "instancePricingPreference"  # String (enum)
INSTANCE_TAGS = "instanceTags"  # Dictionary
INSTANCE_TYPES = "instanceTypes"  # List of Strings
KEY = "key"  # String
MAINTAIN_INSTANCE_COUNT = "maintainInstanceCount"  # Bool
MAX_NODES = "maxNodes"  # Integer
MAX_RETRIES = "maximumTaskRetries"  # Integer (Deprecated: use RETRY_POLICY)
MAX_WORKERS = "maxWorkers"  # Integer
METRICS_ENABLED = "metricsEnabled"  # Boolean
MIN_NODES = "minNodes"  # Integer
MIN_WORKERS = "minWorkers"  # Integer
NAME = "name"  # String
NAMESPACE = "namespace"  # String
NAMESPACES = "namespaces"  # List of Strings
NAME_TAG = "tag"  # String
NODE_BOOT_TIMEOUT = "nodeBootTimeout"  # Float
NODE_TARGET_COUNT = "targetCount"  # Float - worker count
NODE_TARGET_CUSTOM_CMD = (
    "customTargetCommand"  # String - custom command for worker target
)
NODE_TARGET_TYPE = "targetType"  # String - "PER_NODE", "PER_VCPU", "CUSTOM"
NODE_TOTAL_WORKERS = "totalWorkers"  # Integer
NODE_TYPES = "nodeTypes"  # List of Strings - node type filter
NODE_WORKERS = "nodeWorkers"  # Dict - NodeWorkerTarget spec
PARALLEL_BATCHES = "parallelBatches"  # Integer
PRIORITY = "priority"  # Float
PROCESS_EXIT_CODES = "processExitCodes"  # List of Ints
PROVIDERS = "providers"  # List of Strings
RAM = "ram"  # List of two Floats
REGIONS = "regions"  # List of Strings
REQUIRED = "required"  # Boolean
RESUBMISSION_DESTINATIONS = "resubmissionDestinations"  # List of Dicts
RESUBMIT_ERRORS = "resubmitErrors"  # Dict (Selection<TaskErrorSelector>)
RETRY_ERRORS = "retryErrors"  # Dict (Selection<TaskErrorSelector>)
RETRY_MAX_RETRIES = "maxRetries"  # Integer (RetryPolicy field)
RETRY_POLICY = "retryPolicy"  # Dict
RETRYABLE_ERRORS = "retryableErrors"  # List of Dicts (Deprecated: use RETRY_POLICY)
SECRET = "secret"  # String
SELECTION_EXCLUDES = "excludes"  # List (within a Selection<T>)
SELECTION_INCLUDES = "includes"  # List (within a Selection<T>)
SET_TASK_NAMES = "setTaskNames"  # Set to False to suppress task naming
STATUSES_AT_FAILURE = "statusesAtFailure"  # List of Strings
TARGET_INSTANCE_COUNT = "targetInstanceCount"  # Integer
TASKS = "tasks"  # List of Tasks
TASKS_PER_WORKER = "tasksPerWorker"  # Integer
TASK_BATCH_SIZE = "taskBatchSize"  # Integer
TASK_COUNT = "taskCount"  # Integer
TASK_DATA = "taskData"  # String
TASK_DATA_DESTINATION = "destination"  # String
TASK_DATA_FILE = "taskDataFile"  # String
TASK_DATA_FILES = "taskDataFiles"  # List of Strings
TASK_DATA_INPUTS = "taskDataInputs"  # List of dictionaries
TASK_DATA_OUTPUTS = "taskDataOutputs"  # List of dictionaries
TASK_DATA_SOURCE = "source"  # String
TASK_GROUPS = "taskGroups"  # List of Task Groups
TASK_GROUP_COUNT = "taskGroupCount"  # Integer
TASK_GROUP_NAME = "taskGroupName"  # String
TASK_GROUP_TAG = "tag"  # String
TASK_LEVEL_TIMEOUT = "timeout"  # Float
TASK_NAME = "taskName"  # String
TASK_TAG = "tag"  # String
TASK_TEMPLATE = "taskTemplate"  # Dict
TASK_TIMEOUT = "taskTimeout"  # Float
TASK_TYPE = "taskType"  # String
TASK_TYPES = "taskTypes"  # List of Strings
TEMPLATE_ID = "templateId"  # String
URL = "url"  # String
USERDATA = "userData"  # String
USERDATAFILE = "userDataFile"  # String
USERDATAFILES = "userDataFiles"  # List of Strings
USE_PAC = "usePAC"  # Boolean
VARIABLES = "variables"  # Dictionary
VCPUS = "vcpus"  # List of two Floats
WORKERS_CUSTOM_COMMAND = "workersCustomCommand"  # String
WORKERS_PER_NODE = "workersPerNode"  # Integer
WORKERS_PER_VCPU = "workersPerVCPU"  # Integer
WORKER_POOL_DATA_FILE = "workerPoolData"  # String
WORKER_POOL_SECTION = "workerPool"  # No value
WORKER_TAG = "workerTag"  # String
WORKER_TAGS = "workerTags"  # List of Strings
WORK_REQUIREMENT_SECTION = "workRequirement"  # No value
WP_NAME = "name"  # String
WR_DATA = "workRequirementData"  # String
WR_NAME = "name"  # String
WR_TAG = "tag"  # String


ALL_KEYS = [
    ACTION_CONTENT,
    ACTION_CONTENT_FILE,
    ACTION_CONTENT_FILES,
    ACTION_GROUPS,
    ACTION_PATH,
    ACTION_TYPE,
    ACTIONS,
    ADD_ENVIRONMENT,
    ADD_YD_ENV_VARS,
    ARGS,
    ARGS_POSTFIX,
    ARGS_PREFIX,
    CERTIFICATES,
    COMMON_SECTION,
    COMPLETED_TASK_TTL,
    COMPUTE_REQUIREMENT_BATCH_SIZE,
    COMPUTE_REQUIREMENT_DATA_FILE,
    COMPUTE_REQUIREMENT_SECTION,
    CR_TAG,
    CSV_FILE,
    CSV_FILES,
    DATA_CLIENT_BUCKET,
    DATA_CLIENT_LOCAL_PATH,
    DATA_CLIENT_PREFIX,
    DATA_CLIENT_REMOTE,
    DATA_CLIENT_SECTION,
    DATA_CLIENT_UPLOAD_PATH,
    DISABLE_PREALLOCATION,
    DEPENDENCIES,
    DEPENDENT_ON,
    DESTINATION_TASK_GROUP,
    DIRECTORY_NAME,
    ENV,
    ERROR_TYPES,
    FAILURE_POLICY,
    FINISH_IF_ALL_TASKS_FINISHED,
    FINISH_IF_ANY_TASK_FAILED,
    IDLE_NODE_TIMEOUT,
    IDLE_POOL_TIMEOUT,
    IMAGES_ID,
    IMPORT_COMMON,
    INSTANCE_PRICING_PREFERENCE,
    INSTANCE_TAGS,
    INSTANCE_TYPES,
    KEY,
    MAINTAIN_INSTANCE_COUNT,
    MAX_NODES,
    MAX_RETRIES,
    MAX_WORKERS,
    METRICS_ENABLED,
    MIN_NODES,
    MIN_WORKERS,
    NAMESPACE,
    NAMESPACES,
    NAME_TAG,
    NODE_BOOT_TIMEOUT,
    NODE_TARGET_COUNT,
    NODE_TARGET_CUSTOM_CMD,
    NODE_TARGET_TYPE,
    NODE_TOTAL_WORKERS,
    NODE_TYPES,
    NODE_WORKERS,
    PARALLEL_BATCHES,
    PRIORITY,
    PROCESS_EXIT_CODES,
    PROVIDERS,
    RAM,
    REGIONS,
    REQUIRED,
    RESUBMISSION_DESTINATIONS,
    RESUBMIT_ERRORS,
    RETRY_ERRORS,
    RETRY_MAX_RETRIES,
    RETRY_POLICY,
    RETRYABLE_ERRORS,
    SECRET,
    SELECTION_EXCLUDES,
    SELECTION_INCLUDES,
    SET_TASK_NAMES,
    STATUSES_AT_FAILURE,
    TARGET_INSTANCE_COUNT,
    TASKS,
    TASKS_PER_WORKER,
    TASK_BATCH_SIZE,
    TASK_COUNT,
    TASK_DATA,
    TASK_DATA_DESTINATION,
    TASK_DATA_FILE,
    TASK_DATA_FILES,
    TASK_DATA_INPUTS,
    TASK_DATA_OUTPUTS,
    TASK_DATA_SOURCE,
    TASK_GROUPS,
    TASK_GROUP_COUNT,
    TASK_GROUP_NAME,
    TASK_GROUP_TAG,
    TASK_LEVEL_TIMEOUT,
    TASK_NAME,
    TASK_TAG,
    TASK_TEMPLATE,
    TASK_TIMEOUT,
    TASK_TYPE,
    TASK_TYPES,
    TEMPLATE_ID,
    URL,
    USERDATA,
    USERDATAFILE,
    USERDATAFILES,
    USE_PAC,
    VARIABLES,
    VCPUS,
    WORKERS_CUSTOM_COMMAND,
    WORKERS_PER_NODE,
    WORKERS_PER_VCPU,
    WORKER_POOL_DATA_FILE,
    WORKER_POOL_SECTION,
    WORKER_TAG,
    WORKER_TAGS,
    WORK_REQUIREMENT_SECTION,
    WP_NAME,
    WR_DATA,
    WR_NAME,
    WR_TAG,
]
