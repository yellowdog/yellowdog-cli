# Work Requirements

<!--ts-->
   * [Work Requirement JSON File Structure](#work-requirement-json-file-structure)
   * [Property Inheritance](#property-inheritance)
   * [Work Requirement Property Dictionary](#work-requirement-property-dictionary)
   * [Automatic taskTypes Population](#automatic-tasktypes-population)
   * [Task Retries and Failure Policies](#task-retries-and-failure-policies)
      * [Selecting errors (Selection&lt;TaskErrorSelector&gt;)](#selecting-errors-selectiontaskerrorselector)
      * [retryPolicy](#retrypolicy)
      * [failurePolicy](#failurepolicy)
      * [Deprecated: maximumTaskRetries / retryableErrors](#deprecated-maximumtaskretries--retryableerrors)
         * [Migration](#migration)
      * [Caveat — agent version](#caveat--agent-version)
   * [Merging Additional Environment Variables into Tasks](#merging-additional-environment-variables-into-tasks)
      * [Example — TOML](#example--toml)
      * [Example — JSON](#example--json)
   * [Argument Prefix and Postfix](#argument-prefix-and-postfix)
      * [Example — TOML](#example--toml-1)
      * [Example — JSON](#example--json-1)
   * [Task Templates](#task-templates)
      * [Example — TOML](#example--toml-2)
      * [Example — JSON](#example--json-2)
   * [Automatic Properties](#automatic-properties)
      * [Work Requirement, Task Group and Task Naming](#work-requirement-task-group-and-task-naming)
         * [Obtaining Names/Context from Environment Variables at Task Run Time](#obtaining-namescontext-from-environment-variables-at-task-run-time)
      * [Task and Task Group Counts](#task-and-task-group-counts)
   * [Examples](#examples)
      * [TOML Properties in the workRequirement Section](#toml-properties-in-the-workrequirement-section)
      * [JSON Properties at the Work Requirement Level](#json-properties-at-the-work-requirement-level)
      * [JSON Properties at the Task Group Level](#json-properties-at-the-task-group-level)
      * [JSON Properties at the Task Level](#json-properties-at-the-task-level)
   * [Variable Substitutions in Work Requirement Properties](#variable-substitutions-in-work-requirement-properties)
      * [Work Requirement Name Substitution](#work-requirement-name-substitution)
      * [Task and Task Group Name Substitutions](#task-and-task-group-name-substitutions)
   * [Dry-Running Work Requirement Submissions](#dry-running-work-requirement-submissions)
      * [Adding Task Groups and Tasks to an Existing Work Requirement](#adding-task-groups-and-tasks-to-an-existing-work-requirement)
      * [Submitting 'Raw' JSON Work Requirement Specifications](#submitting-raw-json-work-requirement-specifications)
   * [Using the YellowDog Data Client](#using-the-yellowdog-data-client)
      * [Specifying Data Client Inputs](#specifying-data-client-inputs)
      * [Automatic Upload of Local Files](#automatic-upload-of-local-files)
      * [Rclone Authentication](#rclone-authentication)
      * [Specifying Data Client Outputs](#specifying-data-client-outputs)
   * [Task Execution Context](#task-execution-context)
      * [Task Execution Steps](#task-execution-steps)
      * [The User and Group used for Tasks](#the-user-and-group-used-for-tasks)
      * [Home Directory for yd-agent](#home-directory-for-yd-agent)
      * [Task Execution Directory](#task-execution-directory)
   * [Specifying Work Requirements using CSV Data](#specifying-work-requirements-using-csv-data)
      * [Work Requirement CSV Data Example](#work-requirement-csv-data-example)
      * [CSV Variable Substitutions](#csv-variable-substitutions)
      * [Property Inheritance](#property-inheritance-1)
      * [Multiple Task Groups using Multiple CSV Files](#multiple-task-groups-using-multiple-csv-files)
      * [Using CSV Data with Simple, TOML-Only Work Requirement Specifications](#using-csv-data-with-simple-toml-only-work-requirement-specifications)
      * [Inspecting the Results of CSV Variable Substitution](#inspecting-the-results-of-csv-variable-substitution)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Fri Oct  9 09:37:24 BST 2026 -->

<!--te-->


A **Work Requirement** is the top-level unit of work submitted to the YellowDog platform. It contains one or more **Task Groups**, each of which contains one or more **Tasks**. Work Requirements are created and submitted using the **`yd-submit`** command, and can be updated after submission — adding Task Groups or Tasks — using the `--add-to` option.

The `workRequirement` section of the configuration file is optional. It's used only by the `yd-submit` command, and controls the Work Requirement that is submitted to the Platform.

**Jump to:** [Property Dictionary](property-dictionary.md#work-requirement-property-dictionary) · [Task Templates](#task-templates) · [Automatic Properties](#automatic-properties) · [Examples](#examples) · [Variable Substitutions](#variable-substitutions-in-work-requirement-properties) · [Dry-Running](#dry-running-work-requirement-submissions) · [Data Client](#using-the-yellowdog-data-client) · [Task Execution Context](#task-execution-context) · [CSV Data](#specifying-work-requirements-using-csv-data)

The details of a Work Requirement to be submitted can be captured entirely within the TOML configuration file for simple (single Task Group) examples. More complex examples capture the Work Requirement in a combination of the TOML file plus a JSON document, or in a JSON document only.

## Work Requirement JSON File Structure

Work Requirements are represented in JSON documents using a containment hierarchy of a **Work Requirement** containing a **list of Task Groups**, containing a **list of Tasks**.

A very simple example document is shown below with a top-level Work Requirement containing two Task Groups each containing two Tasks, each with a different set of arguments to be passed to the Task.

```json
{
  "taskGroups": [
    {
      "tasks": [
        {
          "arguments": [1, 2, 3]
        },
        {
          "arguments": [4, 5, 6]
        }
      ]
    },
    {
      "tasks": [
        {
          "arguments": [7, 8, 9]
        },
        {
          "arguments": [10, 11, 12]
        }
      ]
    }
  ]
}

```

To specify the file containing the JSON document, either populate the `workRequirementData` property in the `workRequirement` section of the TOML configuration file with the JSON filename, or specify it on the command line as a positional argument (which will override the property in the TOML file), e.g.:

`yd-submit --config myconfig.toml my_workreq.json`

## Property Inheritance

Work Requirement specifications can be simplified substantially by the property inheritance features in `yd-submit`. In general, properties that are set at a higher level in the hierarchy are inherited at lower levels, unless explicitly overridden.

This means that a property set in the `workRequirement` section of the TOML file can be inherited successively by the Work Requirement, Task Groups, and Tasks in the JSON document (assuming the property is available at each level). Hence, Tasks inherit from Task Groups, which inherit from the Work Requirement in the JSON document, which inherits from the `workRequirement` properties in the TOML file.

Overridden properties are also inherited at lower levels in the hierarchy. E.g. if a property is set at the Task Group level, it will be inherited by the Tasks in that Task Group unless explicitly overridden.

## Work Requirement Property Dictionary

Every property available for defining Work Requirements, and the levels at which each can be set, is listed in the **[Work Requirement Property Dictionary](property-dictionary.md)**.

## Automatic `taskTypes` Population

A Task Group's `taskTypes` list (which determines which Workers can pick up Tasks in the group) can be omitted: it will be populated from the `taskType` of the constituent Tasks. When both are supplied, the resulting list is the **union** of the explicit `taskTypes` and every `taskType` set on the Tasks in the group.

For example, this Task Group has no explicit `taskTypes` — the group's allowlist becomes `["bash"]` automatically:

```json
{
  "name": "my-tasks",
  "tasks": [
    {"name": "task-1", "taskType": "bash", "arguments": ["echo", "hello"]},
    {"name": "task-2", "taskType": "bash", "arguments": ["echo", "world"]}
  ]
}
```

And in this example, the group's allowlist becomes `["bash", "docker"]` (the union):

```json
{
  "name": "mixed-tasks",
  "taskTypes": ["bash"],
  "tasks": [
    {"name": "shell-task", "taskType": "bash", "arguments": ["echo", "hi"]},
    {"name": "container-task", "taskType": "docker", "taskData": "..."}
  ]
}
```

If `taskTypes` is still empty after this union, the CLI falls back (in order) to the `[workRequirement] taskType` config property and to `taskTemplate.taskType`. If none of these provide a value and the Task Group contains Tasks, submission fails with a clear error. The resulting `taskTypes` keeps the declared types in their order, followed by the Tasks' own types in the order they first appear.

A Task with no `taskType` of its own takes its Task Group's, if the group has only one. If the group allows several, the Task takes the `[workRequirement] taskType` config property where the group allows that type, or otherwise the type of the group's `taskTemplate`; if neither applies, submission fails with an error naming the Task, rather than sending a Task the platform would refuse.

When using `yd-submit --add-to <wr>` to add Tasks to an **existing** Task Group, the existing group's `taskTypes` allowlist cannot be modified (the platform does not support mutating `taskTypes` after the Task Group is created). The CLI detects this case before submitting anything and fails with a clear error if the incoming Tasks introduce a `taskType` that the existing group does not already allow. The remedy is to use a different Task Group name (so a new Task Group is created with the union of `taskTypes`) or change the offending Tasks to use a supported `taskType`.

## Task Retries and Failure Policies

A Task Group's `runSpecification` can carry one **`retryPolicy`** and one **`failurePolicy`**. The retry policy is evaluated after each errored attempt; if retries are exhausted (or excluded by the policy), the failure policy can re-issue the Task in a different Task Group rather than letting it terminate as `FAILED`.

### Selecting errors (`Selection<TaskErrorSelector>`)

Both policies select Tasks by their most-recent `TaskError` using a **`Selection`** of one or more `TaskErrorSelector` entries. Every `Selection` in the spec is a dict of the form:

```json
{
  "includes": [ ... ],
  "excludes": [ ... ]
}
```

Either `includes` or `excludes` (or both) must be present. A Task matches the selection if at least one entry under `includes` matches **and** no entry under `excludes` matches. Bare lists are rejected — wrap them as `{"includes": [...]}` to be explicit.

Each `TaskErrorSelector` has three optional fields, each itself a Selection of primitive values; an entry matches a Task error when **every** specified field's Selection matches (AND logic across the fields):

| Field               | Selection of      | Description                                                                                                |
|:--------------------|:------------------|:-----------------------------------------------------------------------------------------------------------|
| `errorTypes`        | strings           | Task error types — e.g. `"ALLOCATION_LOST"`, `"PROCESS_NON_ZERO_EXIT"`, `"TIMED_OUT"`.                     |
| `statusesAtFailure` | TaskStatus names  | Task status at the time of the error — e.g. `"FAILED"`.                                                    |
| `processExitCodes`  | integers          | The Task process exit code — e.g. `137` (OOM), `143` (SIGTERM). Implies `errorType = PROCESS_NON_ZERO_EXIT`. |

### `retryPolicy`

```json
{
  "retryPolicy": {
    "maxRetries": 3,
    "retryErrors": {
      "includes": [
        {"errorTypes": {"includes": ["ALLOCATION_LOST"]}},
        {"processExitCodes": {"includes": [143]}}
      ]
    }
  }
}
```

`maxRetries` is required and must be `>= 0` (set it to `0` to define the policy but disable retries). `retryErrors` is optional — when omitted, all Task errors are eligible for retry.

### `failurePolicy`

When retries are exhausted (or the error didn't match `retryPolicy.retryErrors`), a `failurePolicy` can resubmit the Task in another Task Group within the same Work Requirement:

```json
{
  "failurePolicy": {
    "resubmissionDestinations": [
      {
        "destinationTaskGroup": "on-demand-tg",
        "resubmitErrors": {
          "includes": [{"errorTypes": {"includes": ["ALLOCATION_LOST"]}}]
        }
      },
      {
        "destinationTaskGroup": "high-memory-tg",
        "resubmitErrors": {
          "includes": [{"processExitCodes": {"includes": [137]}}]
        }
      }
    ]
  }
}
```

Destinations are evaluated **in order**; the first matching entry wins. A resubmitted Task becomes `RESUBMITTED` (a terminal status), and a copy is added to the destination Task Group with its `resubmittedFromTaskId` linking back to the original. The original Task carries `resubmittedToTaskId` pointing forward.

Common use cases:

- **Spot → on-demand fallback**: retry preemptions a few times in a spot-priced Task Group, then resubmit to an on-demand Task Group.
- **Out-of-memory → larger instance**: exit code 137 in a default-sized group resubmits to a Task Group with more `ram` or `vcpus`.

### Deprecated: `maximumTaskRetries` / `retryableErrors`

The legacy retry mechanism is still accepted but **cannot be combined with `retryPolicy`** on the same Task Group — `yd-submit` will reject the spec with a clear error, because both control how many times and on which errors a Task is retried. Using the legacy fields emits a one-time deprecation warning per invocation.

`failurePolicy` *can* be used alongside `maximumTaskRetries` / `retryableErrors`: the legacy retry mechanism runs first, and if retries are exhausted, the `failurePolicy` is consulted for resubmission. This lets you adopt failure-based resubmission without simultaneously migrating your existing retry configuration.

#### Migration

The minimal replacement for `maximumTaskRetries = N` (with no error filtering) is a `retryPolicy` with only `maxRetries` set — every error is eligible for retry, matching the legacy behaviour.

**TOML** — under `[workRequirement]`:

```toml
# Before (deprecated)
[workRequirement]
    maximumTaskRetries = 3

# After (equivalent — retries on any error)
[workRequirement]
    retryPolicy.maxRetries = 3

# After (with error filtering)
[workRequirement.retryPolicy]
    maxRetries = 3
    retryErrors.includes = [
        { errorTypes = { includes = ["ALLOCATION_LOST"] } },
        { processExitCodes = { includes = [143] } },
    ]
```

**JSON / Jsonnet** — inside a Task Group:

```json
{
  "retryPolicy": {
    "maxRetries": 3,
    "retryErrors": {
      "includes": [
        {"errorTypes": {"includes": ["ALLOCATION_LOST"]}},
        {"processExitCodes": {"includes": [143]}}
      ]
    }
  }
}
```

A legacy `retryableErrors` entry's three fields (`errorTypes`, `statusesAtFailure`, `processExitCodes`) all migrate to the corresponding fields on a `TaskErrorSelector`, with each wrapped in a `{"includes": [...]}` Selection. Legacy semantics — a Task retried if **any** entry matched — translate to a single `includes` list of `TaskErrorSelector` entries.

### Caveat — agent version

The retry/failure selection by `errorTypes`/`processExitCodes` depends on the YellowDog Agent recording which error caused the Task to fail. Older Agent versions don't populate that field, so Selection precision is reduced when running against older Workers — `maxRetries` and unconditional resubmission still work, but error-typed selectors won't match precisely. Upgrade Workers to the current Agent release for full behaviour.

## Merging Additional Environment Variables into Tasks

The `addEnvironment` property allows a fixed set of environment variable key-value pairs to be merged into the `environment` of every Task, without replacing the entire `environment` property. Any key in `addEnvironment` that also exists in the Task's `environment` is **overridden** by the value from `addEnvironment`.

`addEnvironment` follows the same inheritance hierarchy as `argumentsPrefix` and `argumentsPostfix`: it can be set in the TOML `[workRequirement]` section, at the Work Requirement JSON level, or at the Task Group JSON level (not at the per-Task level), with lower levels taking precedence.

### Example — TOML

```toml
[workRequirement]
    environment = {MY_VAR = "original", KEEP = "kept"}
    addEnvironment = {MY_VAR = "overridden", EXTRA = "new"}
    # Effective environment for each task: {MY_VAR = "overridden", KEEP = "kept", EXTRA = "new"}
```

### Example — JSON

```json
{
  "taskGroups": [
    {
      "environment": {"MY_VAR": "original", "KEEP": "kept"},
      "addEnvironment": {"MY_VAR": "overridden", "EXTRA": "new"},
      "tasks": [{}]
    }
  ]
}
```

## Argument Prefix and Postfix

The `argumentsPrefix` and `argumentsPostfix` properties allow a fixed list of arguments to be prepended and/or appended to every Task's `arguments`. The final argument list passed to each Task is:

```
argumentsPrefix + arguments + argumentsPostfix
```

This is useful when many Tasks share a common command structure but differ only in their per-task arguments — the shared parts can be set once at the Work Requirement or Task Group level rather than repeated in every Task definition. Variable substitutions are supported in all three lists.

`argumentsPrefix` and `argumentsPostfix` follow the same inheritance hierarchy as `addEnvironment`: they can be set in the TOML `[workRequirement]` section, at the Work Requirement JSON level, or at the Task Group JSON level (not at the per-Task level), with lower levels taking precedence.

### Example — TOML

```toml
[workRequirement]
    argumentsPrefix = ["--input", "data/"]
    argumentsPostfix = ["--output", "results/"]
    arguments = ["file1.txt"]
    # Effective arguments for each task: ["--input", "data/", "file1.txt", "--output", "results/"]
```

### Example — JSON

In this example, the repeated `python process.py` is set once at the Task Group level; each Task only specifies the part that varies:

```json
{
  "taskGroups": [
    {
      "argumentsPrefix": ["python", "process.py"],
      "tasks": [
        {"arguments": ["--input", "file1.txt"]},
        {"arguments": ["--input", "file2.txt"]},
        {"arguments": ["--input", "file3.txt"]}
      ]
    }
  ]
}
```

Each Task is invoked as `python process.py --input <file>`.

## Task Templates

The `taskTemplate` property on a Task Group optionally sets default values for `taskType`, `taskData`, and `environment` for all Tasks in that group. These defaults are applied by the YellowDog platform, allowing individual Task specifications to be more compact — Tasks that share the same type and data don't need to repeat them.

Any combination of the three fields can be specified; omitted fields are simply not defaulted. Values specified directly on an individual Task take precedence over the template.

`taskDataFile` or `taskDataFiles` can be used inside `taskTemplate` as an alternative to `taskData`, exactly as they can at the Task level — the file contents are read client-side and used as the `taskData` value. `taskDataFiles` concatenates multiple files in order.

`taskTemplate` can be set in the TOML config (applying globally as a default), at the Work Requirement level, or at the Task Group level. More specific levels take precedence.

### Example — TOML

```toml
[workRequirement]
    taskTemplate = {taskType = "docker", taskData = "default-data", environment = {BATCH_SIZE = "100"}}
```

### Example — JSON

```json
{
  "taskGroups": [
    {
      "taskTemplate": {
        "taskType": "docker",
        "taskData": "default-data",
        "environment": {"BATCH_SIZE": "100"}
      },
      "taskTypes": ["docker"],
      "tasks": [
        {},
        {"environment": {"BATCH_SIZE": "200"}},
        {}
      ]
    }
  ]
}
```

All three Tasks use the `docker` task type from the template. The second Task overrides `BATCH_SIZE` to `"200"`; the others inherit `"100"` from the template.

## Automatic Properties

In addition to the property inheritance mechanism, some properties are set automatically by the `yd-submit` command, as a usage convenience if they're not explicitly specified.

### Work Requirement, Task Group and Task Naming

- The **Work Requirement** name is automatically set using a concatenation of the `tag` property, a UTC timestamp and a process discriminator (see [Naming Rules](configuration.md#naming-rules)): e.g. `mytag_221024-1555241-4f`.
- **Task Group** names are automatically created for any Task Group that is not explicitly named, using names of the form `task_group_1` (or `task_group_01`, etc., for larger numbers of Task Groups). Task Group numbers can also be included in user-defined Task Group names using the `{{task_group_number}}` variable substitution discussed below.
- **Task** names are automatically created for any Task that is not explicitly named, using names of the form `task_1` (or `task_01`, etc., for larger numbers of Tasks). The Task counter resets for each different Task Group. Task numbers can also be included in user-defined Task names using the `{{task_number}}` variable substitution discussed below. Automatic Task name generation can be suppressed by setting the `setTaskNames` property to `false`, in which case the `task_name` variable will be set to `none`.

#### Obtaining Names/Context from Environment Variables at Task Run Time

When a Task executes, its Task name and number, Task Group name and number, Work Requirement name, Namespace, and Tag can be made automatically available to the Task in the following environment variables, if the `addYDEnvironment` property is set to `true`:

- `YD_TASK_NAME`
- `YD_TASK_NUMBER`
- `YD_NUM_TASKS` (Number of Tasks in this Task Group)
- `YD_TASK_GROUP_NAME`
- `YD_TASK_GROUP_NUMBER`
- `YD_NUM_TASK_GROUPS` (Number of Task Groups in the Work Requirement)
- `YD_WORK_REQUIREMENT_NAME`
- `YD_NAMESPACE`
- `YD_TAG` (if set at the Task level)

This applies whether the names were set automatically by `yd-submit` or explicitly by the user.

In addition to the environment variables above, when a Task is executed by a Worker, the YellowDog Agent will set the following for use by the Task, based on the instance details and Task identification:

- `YD_PROVIDER`
- `YD_REGION`
- `YD_INSTANCE_TYPE`
- `YD_INSTANCE_ID`
- `YD_TASK_GROUP_ID`
- `YD_TASK_ID`
- `YD_AGENT_DATA`
- `YD_AGENT_HOME`
- `YD_WORKER_SLOT`

### Task and Task Group Counts

The `taskCount` property can be used to expand the number of Tasks within a Task Group, by creating duplicates of a single Task; this can be handy for testing and demos. In JSON specifications, there must be zero or one Task(s) listed within each Task Group or `taskCount` is ignored. This property can also be set on the command line using the `--task-count`/`-C` option of `yd-submit` followed by the required number of Tasks.

Also useful for testing, the `taskGroupCount` property or the command-line option `--task-group-count`/`-G` can be set to expand the number of Task Groups in the Work Requirement, by creating duplicates of a single Task Group. If used, the `taskCount` property will apply to every Task Group, i.e. the total number of Tasks is the product of `taskGroupCount` and `taskCount`.

## Examples

### TOML Properties in the `workRequirement` Section

Here's an example of the `workRequirement` section of a TOML configuration file, showing all the possible properties that can be set:

```toml
[workRequirement]
    addEnvironment = {EXTRA_VAR = "extra_value", MY_VAR = "override"}
    addYDEnvironment = true
    arguments = ["1", "TWO"]
    argumentsPostfix = ["--postfix-arg"]
    argumentsPrefix = ["--prefix-arg"]
    completedTaskTtl = 10
    csvFile = "file1.csv"
    csvFiles = ["file1.csv", "file3.csv:3"]
    environment = {MY_VAR = "100"}
    finishIfAllTasksFinished = true
    finishIfAnyTaskFailed = false
    instancePricingPreference = "SPOT_THEN_ON_DEMAND"
    instanceTypes = ["t3a.micro", "t3.micro"]
    namespaces = ["namespace_1", "namespace_2"]
    maxWorkers = 1
    maximumTaskRetries = 0
    minWorkers = 1
    name = "my-work-requirement"
    parallelBatches = 5
    priority = 0.0
    providers = ["AWS"]
    ram = [0.5, 2.0]
    regions = ["eu-west-2"]
    retryableErrors = [
      {processExitCodes = [143], statusesAtFailure = ["FAILED"], errorTypes = ["ALLOCATION_LOST"]},
    ]
    setTaskNames = false
    tag = "my_tag"
    taskBatchSize = 1000
    taskCount = 100
    taskData = "my_data_string"
    taskDataFile = "my_data_file.txt"
    taskDataFiles = ["header.txt", "body.txt"]
    taskDataInputs = [
      {source = "in_src_path_1", destination = "dest_path_1"},
      {localPath = "local_file", uploadPath = "in_src_path_2", source = "in_src_path_2", destination = "dest_path_2"},
    ]
    taskDataOutputs = [
        {source = "out_src_path_1", destination = "dest_path_1", alwaysUpload = true},
        {source = "out_src_path_2", destination = "dest_path_2", alwaysUpload = false},
    ]
    taskName = "my_task_number_{{task_number}}"
    taskGroupCount = 5
    taskGroupName = "my_task_group_number_{{task_group_number}}"
    taskTemplate = {taskType = "docker", taskData = "my_data_string", environment = {MY_VAR = "value"}}
    taskTimeout = 120.0
    taskType = "docker"
    tasksPerWorker = 1
    vcpus = [1, 4]
    workerTags = ["tag-{{username}}"]
    workRequirementData = "work_requirement.json"
```

### JSON Properties at the Work Requirement Level

Showing all possible properties at the Work Requirement level:

```json
{
  "addEnvironment": {"EXTRA_VAR": "extra_value", "MY_VAR": "override"},
  "addYDEnvironment": true,
  "arguments": [1, "TWO"],
  "argumentsPostfix": ["--postfix-arg"],
  "argumentsPrefix": ["--prefix-arg"],
  "completedTaskTtl": 10,
  "environment": {"MY_VAR": "100"},
  "finishIfAllTasksFinished": true,
  "finishIfAnyTaskFailed": false,
  "instancePricingPreference": "SPOT_THEN_ON_DEMAND",
  "instanceTypes": ["t3a.micro", "t3.micro"],
  "maxWorkers": 1,
  "maximumTaskRetries": 0,
  "minWorkers": 1,
  "name": "my-work-requirement",
  "namespaces": ["namespace_1", "namespace_2"],
  "priority": 0.0,
  "providers": ["AWS"],
  "ram": [0.5, 2],
  "regions": ["eu-west-2"],
  "retryableErrors": [
    {
      "processExitCodes": [143],
      "statusesAtFailure" : ["FAILED"],
      "errorTypes": ["ALLOCATION_LOST"]
    }
  ],
  "setTaskNames": false,
  "tag": "my_tag",
  "taskCount": 100,
  "taskData": "my_task_data_string",
  "taskDataFile": "my_data_file.txt",
  "taskDataFiles": ["header.txt", "body.txt"],
  "taskDataInputs": [
    {"destination": "dest_path_1", "source": "in_src_path_1"},
    {"localPath": "local_file", "uploadPath": "in_src_path_2", "destination": "dest_path_2", "source": "in_src_path_2"}
  ],
  "taskDataOutputs": [
    {"alwaysUpload": true, "destination": "dest_path_1", "source": "out_src_path_1"},
    {"alwaysUpload": false, "destination": "dest_path_2", "source": "out_src_path_2"}
  ],
  "taskGroupCount": 5,
  "taskTemplate": {"taskType": "docker", "taskData": "my_task_data_string", "environment": {"MY_VAR": "value"}},
  "taskTimeout": 120.0,
  "taskTypes": ["docker"],
  "tasksPerWorker": 1,
  "vcpus": [1, 4],
  "workerTags": [],
  "taskGroups": [
    {
      "tasks": [
        {}
      ]
    }
  ]
}

```

### JSON Properties at the Task Group Level

Showing all possible properties at the Task Group level:

```json
{
  "taskGroups": [
    {
      "addEnvironment": {"EXTRA_VAR": "extra_value", "MY_VAR": "override"},
      "addYDEnvironment": true,
      "arguments": [1, "TWO"],
      "argumentsPostfix": ["--postfix-arg"],
      "argumentsPrefix": ["--prefix-arg"],
      "completedTaskTtl": 10,
      "environment": {"MY_VAR": "100"},
      "finishIfAllTasksFinished": true,
      "finishIfAnyTaskFailed": false,
      "instancePricingPreference": "SPOT_THEN_ON_DEMAND",
      "instanceTypes": ["t3a.micro", "t3.micro"],
      "maximumTaskRetries": 0,
      "maxWorkers": 1,
      "minWorkers": 1,
      "name": "first-task-group",
      "namespaces": ["namespace_1", "namespace_2"],
      "priority": 0.0,
      "providers": ["AWS"],
      "ram": [0.5, 2],
      "regions": ["eu-west-2"],
      "retryableErrors": [
        {
          "processExitCodes": [143],
          "statusesAtFailure" : ["FAILED"],
          "errorTypes": ["ALLOCATION_LOST"]
        }
      ],
      "setTaskNames": false,
      "tag": "my_tag",
      "taskCount": 5,
      "taskData": "my_task_data_string",
      "taskDataFile": "my_data_file.txt",
      "taskDataFiles": ["header.txt", "body.txt"],
      "taskDataInputs": [
        {"destination": "dest_path_1", "source": "in_src_path_1"},
        {"localPath": "local_file", "uploadPath": "in_src_path_2", "destination": "dest_path_2", "source": "in_src_path_2"}
      ],
      "taskDataOutputs": [
        {"alwaysUpload": true, "destination": "dest_path_1", "source": "out_src_path_1"},
        {"alwaysUpload": false, "destination": "dest_path_2", "source": "out_src_path_2"}
      ],
      "taskTemplate": {"taskType": "docker", "taskData": "default-data", "environment": {"VAR": "value"}},
      "taskTimeout": 120.0,
      "taskTypes": ["docker"],
      "tasksPerWorker": 1,
      "vcpus": [1, 4],
      "workerTags": [],
      "tasks": [
        {}
      ]
    },
    {
      "name": "second-task-group",
      "dependencies": ["first-task-group"],
      "tasks": [
        {}
      ]
    }
  ]
}
```

### JSON Properties at the Task Level

Showing all possible properties at the Task level:

```json
{
  "taskGroups": [
    {
      "tasks": [
        {
          "addYDEnvironment": true,
          "arguments": [1, 2],
          "environment": {"MY_VAR": "100"},
          "name": "my-task",
          "setTaskNames": false,
          "tag": "my_tag",
          "taskData": "my_task_data_string",
          "taskDataFile": "my_data_file.txt",
          "taskDataFiles": ["header.txt", "body.txt"],
          "taskDataInputs": [
            {"destination": "dest_path_1", "source": "in_src_path_1"},
            {"localPath": "local_file", "uploadPath": "in_src_path_2", "destination": "dest_path_2", "source": "in_src_path_2"}
          ],
          "taskDataOutputs": [
            {"alwaysUpload": true, "destination": "dest_path_1", "source": "out_src_path_1"},
            {"alwaysUpload": false, "destination": "dest_path_2", "source": "out_src_path_2"}
          ],
          "timeout": 120.0,
          "taskType": "docker"
        }
      ]
    }
  ]
}
```

## Variable Substitutions in Work Requirement Properties

Variable substitutions can be used within any property value in TOML configuration files or Work Requirement JSON files. See the description [above](variables.md#variable-substitutions) for more details on variable substitutions. This is a powerful feature that allows Work Requirements to be parameterised by supplying values on the command line, via environment variables, or via the TOML file.

### Work Requirement Name Substitution

The name of the Work Requirement itself can be used via the variable substitution `{{wr_name}}`. This can be used anywhere in the `workRequirement` section of the TOML configuration file, or in JSON Work Requirement definitions.

### Task and Task Group Name Substitutions

The following naming and numbering substitutions are available for use in TOML and JSON Work Requirement specifications, along with the context(s) in which each variable can be used. The variables can be used within the value of any property.

| Directive               | Description                                       | Task | Task Group |
|:------------------------|:--------------------------------------------------|:-----|:-----------|
| `{{task_number}}`       | The current Task number                           | Yes  |            |
| `{{task_name}}`         | The current Task name                             | Yes  |            |
| `{{task_group_name}}`   | The current Task Group name                       | Yes  | Yes        |
| `{{task_count}}`        | The number of Tasks in the current Task Group     | Yes  | Yes        |
| `{{task_group_number}}` | The current Task Group number                     | Yes  | Yes        |
| `{{task_group_count}}`  | The number of Task Groups in the Work Requirement | Yes  | Yes        |

The Task variables are available in any property a Task takes, wherever it is set: a property such as `arguments`, `environment`, `taskData`, `taskDataFile` or `taskDataInputs` set on a Task Group or the Work Requirement, or in the `[workRequirement]` section of the configuration file, is inherited by each of its Tasks and substituted for each one, so `"arguments": ["--frame", "{{task_number}}"]` on a Task Group gives each Task its own number, and `"taskDataFile": "data-{{task_name}}.txt"` its own file.

As an example, the following JSON Work Requirement:

```json
{
  "taskGroups": [
    {
      "name": "my_task_group_{{task_group_number}}_a1",
      "taskCount": 2,
      "tasks": [
        {
          "name": "my_task_{{task_number}}-of-{{task_count}}"
        }
      ]
    },
    {
      "name": "my_task_group_{{task_group_number}}_b1",
      "taskCount": 2,
      "tasks": [
        {
          "name": "my_task_{{task_number}}-of-{{task_count}}"
        }
      ]
    }
  ]
}
```

... would create Task Groups named `my_task_group_1_a1` and `my_task_group_2_b1`, each containing Tasks named `my_task_1-of-2`, `my_task_2-of-2`.

## Dry-Running Work Requirement Submissions

To examine the JSON that will actually be sent to the YellowDog API after all processing, use the `--dry-run` (`-D`) command-line option when running `yd-submit`. This will print the fully processed JSON for the Work Requirement. Nothing will be submitted to the Platform.

A dry-run is useful for inspecting the results of all the processing that's been performed. To suppress all output except for the JSON itself, add the `--quiet` (`-q`) command-line option.

Note that the generated JSON is a **consolidated form** of what would be submitted to the YellowDog API, and Tasks are incorporated directly within their Task Group data structures for ease of comprehension. In actual API submissions, the Work Requirement with zero or more Task Groups is submitted first, and Tasks are then added to their Task Groups separately, in subsequent API calls. Task Groups and Tasks can also later be added to the Work Requirement.

A simple example of the JSON output is shown below, showing a Work Requirement with a single Task Group, containing a single Task.

`% yd-submit --dry-run --quiet`

> **Note:** When used outside of `--dry-run`, `--quiet` on `yd-submit` prints only the Work Requirement YDID to stdout — see [yd-submit](commands.md#yd-submit) for scripting examples.

```json
{
  "name": "pyex-docker-pwt_240424-1205116-4f",
  "namespace": "pyexamples-pwt",
  "priority": 0,
  "tag": "pyex-docker-pwt",
  "taskGroups": [
    {
      "finishIfAllTasksFinished": true,
      "finishIfAnyTaskFailed": false,
      "name": "task_group_1",
      "priority": 0,
      "runSpecification": {
        "maximumTaskRetries": 0,
        "taskTypes": ["docker"],
        "workerTags": ["pyex-docker-pwt-worker"]
      },
      "starved": false,
      "waitingOnDependency": false,
      "tasks": [
        {
          "arguments": ["my_dockerhub_repo/my_container_image", "1", "2", "3"],
          "environment": {
            "YD_TASK_NAME": "task_1",
            "YD_TASK_NUMBER": "1",
            "YD_TASK_GROUP_NAME": "task_group_1",
            "YD_TASK_GROUP_NUMBER": "1",
            "YD_WORK_REQUIREMENT_NAME": "pyex-docker-pwt_240424-1205116-4f",
            "YD_NAMESPACE": "pyexamples-pwt"
          },
          "name": "task_1",
          "taskType": "docker"
        }
      ]
    }
  ]
}
```

### Adding Task Groups and Tasks to an Existing Work Requirement

The `--empty` (`-e`) option submits a new Work Requirement with no Task Groups or Tasks (using TOML configuration only, without a JSON spec file), providing a named shell that can be populated later using `--add-to`:

```bash
WR_ID=$(yd-submit --empty --quiet)
yd-submit --add-to "$WR_ID" my-spec.json
```

When a JSON spec file is supplied, empty arrays are honoured directly — `--empty` is not required:

```json
{ "taskGroups": [] }
```

or a Task Group with no Tasks:

```json
{
  "taskGroups": [
    { "name": "my-task-group", "tasks": [] }
  ]
}
```

The `--add-to` (`-A`) option allows Task Groups and/or Tasks to be added to a Work Requirement that has already been submitted, as long as it is `RUNNING` or `HELD`: a `FINISHING` one takes no new Tasks, and the rest have finished or are being cancelled. It cannot be combined with `--hold` or `--empty`, which apply only to a new Work Requirement.

The argument to `--add-to` is the name or YellowDog ID of the target Work Requirement. A YDID is found in whatever namespace it belongs to; a name is looked up in the configured `namespace` unless it is given as `namespace/name`, and since a name can be reused, the `RUNNING` or `HELD` Work Requirement of that name is chosen (if there are two, its YDID must be given instead). A target that does not exist exits with code 6:

```bash
yd-submit --add-to my-work-requirement my-spec.json
```

The Work Requirement specification supplied is processed in the same way as for a normal submission. The resulting Task Groups are then matched against the Task Groups already present in the target Work Requirement, by name:

- **Matching Task Group name**: the new Tasks are appended to the existing Task Group. Task and Task Group numbers continue from where the existing Tasks left off, ensuring consistent naming.
- **New Task Group name**: the Task Group is added to the Work Requirement, and its Tasks are submitted in the normal way.

A single `yd-submit --add-to` invocation can add a mix of new Task Groups and Tasks to existing Task Groups simultaneously.

As with a normal `yd-submit`, `--follow` (or `-f`) can be used to follow the Work Requirement to completion after additions have been submitted.

If adding Tasks fails part-way, the target Work Requirement is not cancelled, as a newly submitted one would be: any Tasks already added remain in it, and any files uploaded for them are left in place, since those Tasks may need them. A warning says so, and `yd-submit` exits with a non-zero status.

If the spec contains `taskDataInputs` with `localFile` entries, those files will be uploaded to the remote destination as usual. If a file was already uploaded during the original submission and has not changed, it will be skipped by default. Use `--overwrite` (`-O`) to force re-uploading:

```bash
yd-submit --add-to my-work-requirement --overwrite my-spec.json
```

By default, `yd-submit` checks whether a file already exists at the remote destination before uploading, and skips it if so. With `--overwrite`, any file present in the spec is uploaded unconditionally, replacing any existing remote copy.

`--dry-run` (`-D`) can be used with `--add-to` to report what would be added, without adding it. Unlike a normal dry run, which contacts the platform not at all, this one reads the target Work Requirement — the names, numbering and Task counts of its existing Task Groups are what determine the names and offsets of everything that would be added — so credentials and connectivity are required. The checks that depend on the target are therefore made as well: that it exists, that it is `RUNNING` or `HELD`, and that no Task's type falls outside an existing Task Group's `taskTypes` allowlist. Nothing is created, updated or uploaded.

The specification printed shows the Work Requirement as it would be: the existing Task Groups as well as the new ones, with the Tasks that would be added attached to whichever Task Group takes them. A `DRY-RUN` line above it names the Task Groups that are already present, because the platform reports only a summary of their Tasks, so those Task Groups appear in the specification without any Tasks of their own.

### Submitting 'Raw' JSON Work Requirement Specifications

It's possible to use the JSON output of `yd-submit --dry-run` (such as the example above) as a self-contained, fully specified Work Requirement specification, using the `--json-raw` (or `-j`) command-line option, i.e. `yd-submit --json-raw <filename.json>`.

This will submit the Work Requirement, then add all the specified Tasks, using `--parallel-batches` (or the `parallelBatches` configuration property) and following with `--follow` or `--progress` as for any other submission. A batch that fails in a way a retry could cure is retried, as any other submission's are; if the Platform refuses a batch of Tasks, the Work Requirement is cancelled and `yd-submit` exits with a non-zero status naming the kind of failure.

Note that variable substitutions **can** be used in the raw JSON file, just as in the other Work Requirement JSON examples, but there is no property inheritance, including from the `[workRequirement]` section of the TOML configuration or from Work Requirement properties supplied on the command line.

## Using the YellowDog Data Client

The YellowDog Data Client is described at https://docs.yellowdog.ai/#/the-platform/the-data-client.

The CLI provides full support for expressing Data Client inputs and outputs as part of Task specifications. In addition, it can provide automatic upload of objects on the local filesystem to Data Client targets. It does this using a local `rclone` binary that will be downloaded to your system the first time the Data Client upload capability is used, if `rclone` is not already present. An `rclone` already on your `$PATH` is used in preference and is never modified; the downloaded copy is stored in `rclone_api`'s own per-user cache directory (`~/Library/Caches/rclone_api` on macOS, `~/.cache/rclone_api` on Linux, and under `%LOCALAPPDATA%` on Windows), not inside the Python package, so it survives reinstallation of the CLI. To see which binary is in use, run `yd-submit --which-rclone` or `yd-version --debug`; to force an upgrade of the downloaded copy to the latest version, run `yd-submit --upgrade-rclone`. Both options are accepted by the Data Client commands as well as by `yd-submit`, i.e. by `yd-upload`, `yd-download`, `yd-delete`, `yd-ls`, and `yd-copy`.

Currently, Data Client only supports **individual files**, not directories or wildcards. If multiple, unspecified files are required, we recommend you compress/decompress them into a single file. The compression/decompression can be handled as part of the execution of the Task at its start and/or conclusion.

### Specifying Data Client Inputs

Data Client inputs for Tasks are specified as follows:

TOML, in the `workRequirement` section:

```toml
taskDataInputs = [
  {source = "in_src_path_1", destination = "dest_path_1"},
  {source = "in_src_path_2", destination = "dest_path_2"},
]
```

JSON:

```json
"taskDataInputs": [
  {"destination": "dest_path_1", "source": "in_src_path_1"},
  {"destination": "dest_path_2", "source": "in_src_path_2"}
],
```

- The `source` property must be an rclone-compliant path starting with `rclone:`, e.g. `rclone:S3,type=s3,provider=AWS,env_auth=true,region=eu-west-2,location_constraint=eu-west-2:my_bucket_name/directory_name/filename`.
- The `destination` property must specify a local pathname and be prefixed with `local:`, e.g. `local:my_output.txt`

### Automatic Upload of Local Files

The `yd-submit` command can automatically upload files in the `taskDataInputs` list. This is enabled by adding the `localFile` property, and optionally the `uploadPath` property, to the relevant input specification, e.g.:

TOML, in the `workRequirement` section:

```toml
taskDataInputs = [
  {localFile = "my_local_file", uploadPath = "in_upload_path_1", source = "in_src_path_1", destination = "dest_path_1"},
]
```

JSON:

```json
"taskDataInputs": [
  {
    "localFile": "my_local_file",
    "uploadPath": "in_upload_path_1",
    "source": "in_src_path_1",
    "destination": "dest_path_1"
  }
]
```

If `uploadPath` is not specified, the local file will be uploaded to the rclone target specified by the `source` property. The local file can be specified using an absolute or relative pathname, and the base files directory can be adjusted using the `--content-path <directory>`/`-F` option supplied to `yd-submit`.

If `yd-submit` fails for any reason, the uploaded objects will be deleted automatically.

### Rclone Authentication

Use of rclone to upload to targets depends on the presence of the required authentication, and this is handled outside the YellowDog CLI.

As an example, if the requirement is to upload to an S3 bucket then appropriate AWS credentials must be present to perform the task, such as `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` being set as environment variables. Example rclone paths could then be:

1. Specifying that the environment should be used for authentication: `rclone:S3,type=s3,provider=AWS,env_auth=true,region=eu-west-2,location_constraint=eu-west-2:<bucket-name>/<pathname>`

2. Explicitly using environment variables for authentication: `rclone:S3,type=s3,provider=AWS,access_key_id={{env:AWS_ACCESS_KEY_ID}},secret_access_key={{env:AWS_SECRET_ACCESS_KEY}},region=eu-west-2,location_constraint=eu-west-2:<bucket-name>/<pathname>`. Note that this will include the key ID and secret in plain text in the task specification.

3. Using an rclone configuration file, e.g. referencing a `[mys3]` section in `rclone.conf`: `rclone:mys3:<bucket-name>/<pathname>`.

### Specifying Data Client Outputs

Data Client outputs for Tasks are specified as follows:

TOML, in the `workRequirement` section:
```toml
taskDataOutputs = [
  {source = "out_src_path_1", destination = "dest_path_1"},
  {source = "out_src_path_2", destination = "dest_path_2", alwaysUpload = true},
]
```

JSON:
```json
"taskDataOutputs": [
  {"destination": "dest_path_1", "source": "out_src_path_1"},
  {"destination": "dest_path_2", "source": "out_src_path_2", "alwaysUpload": true}
],
```

- The `source` property must specify a local pathname and be prefixed with `local:`, e.g. `local:my_output.txt`
- The `destination` property must be an rclone-compliant path, e.g. `rclone:S3,type=s3,provider=AWS,env_auth=true,region=eu-west-2,location_constraint=eu-west-2:my_bucket_name/directory_name/filename`.

## Task Execution Context

This section discusses the context within which a Task operates when it's executed by a Worker on a node. It applies specifically to the YellowDog Agent running on a Linux node, and configured using the default username, directories, etc. Configurations can vary.

### Task Execution Steps

When a Task is allocated to a Worker on a node by the YellowDog Scheduler, the following steps are followed:

1. The Agent running on the node gets the Task's properties: its `taskType`, `arguments`, `environment`, `taskdata`. A number of `YD_` environment variables are also automatically set by a combination (optionally) of `yd-submit` and the Agent itself — see above for details.
2. An ephemeral working directory is created. Data Client input objects are downloaded to this directory, and the contents of the `taskData` property (if set) are written to the file `taskdata.txt`.
3. The Agent runs the command specified for the `taskType` in the Agent's `application.yaml` configuration file. This is done as a simple `exec` of a subprocess to run the Task.
4. When the Task concludes, the Agent uses the exit code of the subprocess to report success (zero) or failure (non-zero).
5. The Agent uploads any Data Client outputs specified in `taskDataOutputs` to their destinations. The ephemeral Task directory is then deleted.

Note that if a Task is aborted during execution, the Task's subprocess is sent a `SIGTERM`, allowing the Task an opportunity to terminate any child processes or other resources (e.g. containers) that may have been started as part of Task execution. In addition, there is the option to set an `abort` clause as part of the Task Type specification in the Agent's `application.yaml` file, in which case the script specified in the `abort` clause takes over complete responsibility for any abort handling.

Once the steps above have been completed, the Worker is ready to process its next Task.

Note that if the Agent on a node advertises multiple Workers, then Tasks are executed in parallel on the node and can start and stop independently.

### The User and Group used for Tasks

By default, in the standard YellowDog Agent VM images and in images/instances created using the [YellowDog Agent Installer Script](https://github.com/yellowdog/resources/blob/main/agent-install/linux/README.md), the Agent runs as user and group `yd-agent`, and hence Tasks also execute under this user.

`yd-agent` does not have `sudo` privileges as standard, but this can be added if required (e.g.) at instance boot time via the `userData` property of a provisioning request. E.g. (for Ubuntu):

```shell
usermod -aG wheel yd-agent
echo -e "yd-agent\tALL=(ALL)\tNOPASSWD: ALL" > /etc/sudoers.d/020-yd-agent
```

### Home Directory for `yd-agent`

By default, the home directory of the `yd-agent` user is `/opt/yellowdog/agent`. This directory typically contains the `application.yaml` file used to configure the Agent, as well as any scripts that are used to execute the Task Types that the node supports.

If one wants to SSH to an instance as user `yd-agent`, perhaps for debugging purposes, SSH keys can be inserted via instance `userData`, e.g.:

```shell
YDA_HOME=/opt/yellowdog/agent
mkdir -p $YDA_HOME/.ssh
chmod og-rwx $YDA_HOME/.ssh
cat >> $YDA_HOME/.ssh/authorized_keys << EOF
<<Insert_Public_key_Here>>
EOF
chmod og-rw $YDA_HOME/.ssh/authorized_keys
chown -R yd-agent:yd-agent $YDA_HOME/.ssh
```

### Task Execution Directory

Ephemeral Task working directories are by default created under `/var/opt/yellowdog/agent/data/workers`, named using their YellowDog Task IDs with colons substituted by underscores.

(On Windows hosts, the Task directories are found under `%AppData%\yellowdog\agent\data\workers`.)

When a Task is started by a worker, an ephemeral directory is created, e.g.:

`/var/opt/yellowdog/agent/data/workers/ydid_task_559EBE_74949336-ac2b-4811-a7d5-f3ecd9739908_1_1`

This is the directory into which downloaded objects are placed, and in which output files are created by default. The console output file, `taskoutput.txt`, containing combined `stderr` and `stdout` output will also be created in this directory.

Note that the Task directory — including `taskoutput.txt` — is **ephemeral**: it is deleted once the Task completes and its outputs have been uploaded. To preserve console output beyond Task execution, add `taskoutput.txt` as a `taskDataOutputs` entry.

## Specifying Work Requirements using CSV Data

CSV data files can be used to drive the generation of lists of Tasks, as follows:

- A **prototype** Task specification is created within a JSON Work Requirement specification or in the `workRequirement` section of the TOML configuration file
- The prototype Task includes one or more variable substitutions using the CSV delimiter syntax `<<variable_name>>`
- A CSV file is created, with the **headers** (first row) matching the names of the variable substitutions in the Task prototype
- Each subsequent row of the CSV file represents a new Task to be built using the prototype, with the variables substituted by the values in the row
- A Task will be created for each row of data

Note that CSV substitutions use `<<` and `>>` as delimiters, which is distinct from the `{{` and `}}` delimiters used for general variable substitutions. This means that regular variable substitutions (e.g. `{{namespace}}`) can coexist with CSV substitutions in the same Task prototype without ambiguity.

### Work Requirement CSV Data Example

As an example, consider the following JSON Work Requirement `wr.json`:

```json
{
  "taskGroups": [
    {
      "tasks": [
        {
          "arguments": ["<<arg_1>>", "<<arg_2>>", "<<arg_3>>"],
          "environment": {"ENV_VAR_1": "<<env_1>>"}
        }
      ]
    }
  ]
}
```

Note that the Task Group must contain only a single Task, acting as the prototype.

Now consider a CSV file `wr_data.csv` with the following contents:

```text
arg_1, arg_2, arg_3, env_1
A,     B,     C,     E-1
D,     E,     F,     E-2
G,     H,     I,     E-3
```

Note that the (optional) leading spaces after each comma are ignored, but trailing spaces are not and will form part of the imported data.

If these files are processed using `yd-submit wr.json -V wr_data.csv`, the following expanded list of three Tasks will be created prior to further processing by the `yd-submit` script:

```json
{
  "taskGroups": [
    {
      "tasks": [
        {
          "arguments": ["A", "B", "C"],
          "environment": {"ENV_VAR_1": "E-1"}
        },
        {
          "arguments": ["D", "E", "F"],
          "environment": {"ENV_VAR_1": "E-2"}
        },
        {
          "arguments": ["G", "H", "I"],
          "environment": {"ENV_VAR_1": "E-3"}
        }
      ]
    }
  ]
}
```

### CSV Variable Substitutions

When the CSV file data is processed, the only substitutions made are those which match the variable substitutions in the prototype Task. The CSV file is the **only** source of substitutions used for this processing phase; all other variable substitutions (supplied on the command line, in the TOML configuration file, or from environment variables) are ignored — i.e. they do not override the contents of the CSV file.

All variable substitutions unrelated to the CSV file data are left unchanged, for subsequent processing by `yd-submit`.

If the value to be inserted is a number, a Boolean, an array or a table, the `<<num:my_number_var>>`, `<<bool:my_boolean_var>>`, `<<array:my_array_var>>` and `<<table:my_table_var>>` forms can be used in the JSON file, and `<<format_name:my_var>>` for a name. The value is converted exactly as in a `{{...}}` [substitution](variables.md#variable-substitutions), so the same spellings are accepted: a substitution that is a whole string assumes the nominated type rather than being a string, and one inside a longer string is checked as its type and written as text. A value that is not of its type is an error naming the CSV file, the line in it and the column, e.g. `'tasks.csv' line 7, column 'count': 'abc' is not a number`.

A CSV value is substituted as it is, whatever it contains: an apostrophe, a quotation mark, a backslash in a Windows path, or text that looks like a CSV substitution. A `{{...}}` [variable substitution](variables.md#variable-substitutions) in a CSV value is made afterwards like any other, so a cell can refer to a variable (e.g. `{{namespace}}`), and `{{::}}` in a cell removes its property. Substitutions are also made in property names, e.g. `"environment": {"<<var_name>>": "<<var_value>>"}`. The CSV file is read as UTF-8, a byte order mark (which Excel's *CSV UTF-8* format writes) is ignored, and blank lines are skipped. Every column needs a heading of its own, so an empty or repeated heading is an error, as is a file with headings but no data rows, which would make a Task Group with no Tasks.

### Property Inheritance

All the usual property inheritance features operate as normal. Properties are inherited from the `config.toml` file, and from the relevant sections of the JSON Work Requirement file. Any properties set within a Task prototype are copied to all the generated Tasks.

### Multiple Task Groups using Multiple CSV Files

The use of multiple Task Groups is also supported, by using one CSV file per Task Group. Each Task Group must contain only a single prototype Task.

The CSV files are supplied on the command line in the order of the Task Groups to which they apply. For example, if `wr.json` contains two Task Groups, as follows:

```json
{
  "taskGroups": [
    {
      "tasks": [
        {
          "arguments": ["<<arg_1>>", "<<arg_2>>", "<<arg_3>>"],
          "environment": {"ENV_VAR_1": "<<env_1>>"}
        }
      ]
    },
    {
      "tasks": [
        {
          "arguments": ["<<arg_1>>", "<<arg_2>>"],
          "environment": {"ENV_VAR_1": "<<env_1>>", "ENV_VAR_2": "<<env_2>>"}
        }
      ]
    }
  ]
}
```

The `yd-submit` command would then be invoked with a separate CSV file for each Task Group, e.g.:

```shell
yd-submit wr.json -V wr_data_task_group_1.csv -V wr_data_task_group_2.csv
```

If there are **fewer** CSV files than Task Groups, a warning will be printed and, if there are 'n' CSV files, CSV data processing will be applied to the first 'n' Task Groups in the Work Requirement by default, in the order in which the CSV files were supplied. If there are **more** CSV files than Task Groups, an error will be raised and processing will stop.

It is possible to apply CSV files explicitly to specific Task Groups, by using an optional **index postfix** (e.g. `:2`) at the end of each CSV filename. For example, if there are two CSV files to be applied to the second and fourth Task Groups in a JSON Work Requirement, use the following syntax:

```shell
yd-submit wr.json -V wr_data_task_group_2.csv:2 -V wr_data_task_group_4.csv:4
```

Alternatively, the **Task Group name** (if supplied in the JSON file) can be used as the postfix. For example, if the Task Groups above are named `tg_two` and `tg_four`, the `yd-submit` command would become:

```shell
yd-submit wr.json -V wr_data_task_group_2.csv:tg_two -V wr_data_task_group_4.csv:tg_four
```

Note that only one CSV file can be applied to any given Task Group, however it is chosen (by position, number or name): two for the same Task Group are an error naming both. A single CSV file can, however, be reused for multiple Task Groups.

### Using CSV Data with Simple, TOML-Only Work Requirement Specifications

It's possible to use TOML exclusively to derive a list of Tasks from CSV data — i.e. a JSON Work Requirement specification is not required.

To make use of this:

1. Ensure that no JSON Work Requirement document is specified (no `workRequirementData` in the TOML file, or no positional argument on the command line)
2. Insert the required CSV-supplied variable substitutions directly into the TOML properties, e.g. `arguments = ["<<arg_1>>", "<<arg_2>>"]`
3. Specify a single CSV file in the `csvFiles` TOML property, e.g. `csvFiles = ["wr_data.csv"]`, or provide the CSV file on the command line `-V wr_data.csv`; naming more than one is an error, since there is only one Task Group to apply them to

When `yd-submit` is run, it will expand the Task list to match the number of data rows in the CSV file.

### Inspecting the Results of CSV Variable Substitution

The `--process-csv-only` (or `-p`) option can be used with `yd-submit` to output the JSON Work Requirement after CSV variable substitutions only, prior to all other substitutions and property inheritance applied by `yd-submit`.
