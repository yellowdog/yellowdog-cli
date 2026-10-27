# Work Requirements

<!--ts-->
   * [Work Requirement JSON File Structure](#work-requirement-json-file-structure)
   * [Property Inheritance](#property-inheritance)
      * [Stopping Inheritance with null](#stopping-inheritance-with-null)
   * [Work Requirement Property Dictionary](#work-requirement-property-dictionary)
   * [Automatic taskTypes Population](#automatic-tasktypes-population)
   * [Task Retries and Failure Policies](#task-retries-and-failure-policies)
      * [Selecting errors (Selection&lt;TaskErrorSelector&gt;)](#selecting-errors-selectiontaskerrorselector)
      * [Task Error Types](#task-error-types)
      * [Finding the Errors Your Tasks Hit](#finding-the-errors-your-tasks-hit)
      * [retryPolicy](#retrypolicy)
      * [failurePolicy](#failurepolicy)
      * [Deprecated: maximumTaskRetries / retryableErrors](#deprecated-maximumtaskretries--retryableerrors)
         * [Migration](#migration)
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
   * [Submitting Large Numbers of Tasks](#submitting-large-numbers-of-tasks)
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
      * [Windows Nodes](#windows-nodes)
   * [Specifying Work Requirements using CSV Data](#specifying-work-requirements-using-csv-data)
      * [Work Requirement CSV Data Example](#work-requirement-csv-data-example)
      * [CSV Variable Substitutions](#csv-variable-substitutions)
      * [Property Inheritance](#property-inheritance-1)
      * [Multiple Task Groups using Multiple CSV Files](#multiple-task-groups-using-multiple-csv-files)
      * [Using CSV Data with Simple, TOML-Only Work Requirement Specifications](#using-csv-data-with-simple-toml-only-work-requirement-specifications)
      * [Inspecting the Results of CSV Variable Substitution](#inspecting-the-results-of-csv-variable-substitution)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Tue Oct 27 12:45:53 GMT 2026 -->

<!--te-->


A **Work Requirement** is the top-level unit of work submitted to the YellowDog platform. It contains one or more **Task Groups**, each of which contains one or more **Tasks**. Work Requirements are created and submitted using the **`yd workrequirement submit`** command, and can be updated after submission — adding Task Groups or Tasks — using the `--add-to` option.

The `workRequirement` section of the configuration file is optional. It's used only by the `yd workrequirement submit` command, and controls the Work Requirement that is submitted to the Platform.

**Jump to:** [Property Dictionary](work-requirement-property-dictionary.md#work-requirement-property-dictionary) · [Task Templates](#task-templates) · [Automatic Properties](#automatic-properties) · [Examples](#examples) · [Variable Substitutions](#variable-substitutions-in-work-requirement-properties) · [Dry-Running](#dry-running-work-requirement-submissions) · [Data Client](#using-the-yellowdog-data-client) · [Task Execution Context](#task-execution-context) · [CSV Data](#specifying-work-requirements-using-csv-data)

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

`yd workrequirement submit --config myconfig.toml my_workreq.json`

The document may also be written in [Jsonnet](jsonnet.md), or in TOML.

## Property Inheritance

Work Requirement specifications can be simplified substantially by the property inheritance features in `yd workrequirement submit`. In general, properties that are set at a higher level in the hierarchy are inherited at lower levels, unless explicitly overridden.

This means that a property set in the `workRequirement` section of the TOML file can be inherited successively by the Work Requirement, Task Groups, and Tasks in the JSON document (assuming the property is available at each level). Hence, Tasks inherit from Task Groups, which inherit from the Work Requirement in the JSON document, which inherits from the `workRequirement` properties in the TOML file.

Overridden properties are also inherited at lower levels in the hierarchy. E.g. if a property is set at the Task Group level, it will be inherited by the Tasks in that Task Group unless explicitly overridden.

A `--property workRequirement.<key>=<value>` override is the exception to lower levels winning: it replaces the property wherever the JSON document sets it, at every level, as a command-line value beats a file's (see [Which Value Wins](configuration.md#which-value-wins)).

### Stopping Inheritance with `null`

To stop a property being inherited, set it to `null` at the level that should not receive it. The property then has its default at that level and every level below it, exactly as if it had been set nowhere: no `priority`, no `arguments`, no Task Data, `setTaskNames` true, and so on, as the [Property Dictionary](work-requirement-property-dictionary.md) gives them. For example, with `arguments = ["--verbose"]` and `priority = 5.0` in the `[workRequirement]` section of the TOML file:

```json
{
  "taskGroups": [
    {"name": "plain", "arguments": null, "priority": null, "tasks": [{"name": "task-1"}]},
    {"name": "verbose", "tasks": [{"name": "task-2"}, {"name": "task-3", "arguments": null}]}
  ]
}
```

`task-1` runs with no arguments, in a Task Group with no priority. `task-2` inherits `["--verbose"]` and its Task Group a priority of `5.0`, while `task-3` stops the inheritance for itself alone.

`null` can be used for any property that is inherited, at any level with a level above it to inherit from (the TOML file counts, so `null` at the Work Requirement level stops a TOML value). The TOML file is the top of the hierarchy, with nothing above it to stop, so it has no need of `null`, which TOML cannot express. Two properties are exceptions:

- `name` and `tag` are not inherited, so there is nothing for `null` to stop.
- A Task must have a Task Type, so a `null` `taskType` is treated as though the Task set none (though the schema check warns of it, and `--validate` reports it, so leaving the property out is the better way): it takes its Task Group's, as described in [Automatic `taskTypes` Population](#automatic-tasktypes-population). `"taskTypes": null` on a Task Group means it declares no Task Types of its own, and takes them from its Tasks.

For a list or a table, an empty value (`[]` or `{}`) also stops the inheritance, with the same result. An inherited `taskData`, `taskDataFile` or `taskDataFiles` is stopped by setting any one of the three, to `null` or to an empty value: the three are one setting, and the first level to set any of them supplies the Task Data.

`null` is not the same as removing the property with the [unset syntax](variables.md#removing-properties-using-the-unset-suffix): a property removed by `{{::}}` (or by `{{variable::}}` with the variable undefined) is treated as never written at that level, so it is still inherited from the level above. See [Unset Properties and Property Inheritance](variables.md#unset-properties-and-property-inheritance).

## Work Requirement Property Dictionary

Every property available for defining Work Requirements, and the levels at which each can be set, is listed in the **[Work Requirement Property Dictionary](work-requirement-property-dictionary.md)**.

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

When using `yd workrequirement submit --add-to <wr>` to add Tasks to an **existing** Task Group, the existing group's `taskTypes` allowlist cannot be modified (the platform does not support mutating `taskTypes` after the Task Group is created). The CLI detects this case before submitting anything and fails with a clear error if the incoming Tasks introduce a `taskType` that the existing group does not already allow. The remedy is to use a different Task Group name (so a new Task Group is created with the union of `taskTypes`) or change the offending Tasks to use a supported `taskType`.

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
| `statusesAtFailure` | TaskStatus names  | The status the Task was in when the error happened — e.g. `"EXECUTING"`, `"DOWNLOADING"`, `"UPLOADING"`. |
| `processExitCodes`  | integers          | The Task process exit code — e.g. `137` (OOM), `143` (SIGTERM). Implies `errorType = PROCESS_NON_ZERO_EXIT`. |

### Task Error Types

The values an `errorTypes` Selection matches:

| Error type                | When it is recorded                                                                                     |
|:--------------------------|:--------------------------------------------------------------------------------------------------------|
| `ALLOCATION_LOST`         | The Task lost the Worker it was allocated to, as when its instance goes away (a spot instance reclaimed, say). |
| `RESOURCE_REQUEST_FAILED` | A request for the resources the Task needed failed.                                                     |
| `TIMED_OUT`               | The Task ran past its timeout (`timeout`, or its Task Group's `taskTimeout`), while `EXECUTING`. Its process, stopped, then records a second error, `PROCESS_NON_ZERO_EXIT` with exit code 143, which did not cause the failure. |
| `UNABLE_START_PROCESS`    | The Agent could not start the Task's process.                                                           |
| `PROCESS_NON_ZERO_EXIT`   | The Task was `EXECUTING`, and its process exited with a non-zero code (which `processExitCodes` selects on). |
| `DATA_CLIENT_DISABLED`    | The Task could not use the data client, which was disabled, while `DOWNLOADING` or `UPLOADING`.        |
| `INPUT_NOT_FOUND`         | An input was not found. A Task data input (`taskDataInputs`) missing from the data store is recorded as `UNKNOWN_ERROR` at `DOWNLOADING` instead. |
| `OUTPUT_NOT_FOUND`        | An output was not found. A Task data output (`taskDataOutputs`) the Task did not write is recorded as `UNKNOWN_ERROR` at `UPLOADING` instead. |
| `UNABLE_WRITE_TASK_DATA`  | The Agent could not write the Task's `taskData` to its file.                                            |
| `UNKNOWN_ERROR`           | Any other error.                                                                                        |

`PROCESS_NON_ZERO_EXIT`, `TIMED_OUT` and the `UNKNOWN_ERROR` of a missing Task data input or output are as observed on the Platform; the SDK describes `DATA_CLIENT_DISABLED`, and the others are described by what their names record. Because a Task can record more than one error for one failure, as a timeout does, select on the one that caused it: the errors your own Tasks have recorded (below) show which that is.

### Finding the Errors Your Tasks Hit

A Task keeps every error it has recorded, retried or not, in its `errors` list, so a policy is best written from the errors your Tasks actually hit. `--with-errors` lists the Tasks that recorded one, whatever their status (a Task that completed on a retry included), and `--auto-select-all` shows each in full (as `--details` does for the Tasks you choose from the list), or `--json` gives them all as one array:

```shell
yd task list --within my-work-requirement --with-errors --auto-select-all
```

Each entry in a Task's `errors` carries the three things a `TaskErrorSelector` selects on, beside a description, when it happened, and the node and Worker it happened on:

```jsonc
{
  "timestamp": "<when it happened>",
  "error": "<the Agent's description of the error>",
  "nodeId": "ydid:node:000000:...",
  "workerId": "ydid:wrkr:000000:...",
  "errorType": "PROCESS_NON_ZERO_EXIT",
  "statusAtFailure": "EXECUTING",
  "processExitCode": 137,
  "causedFailure": true
}
```

`causedFailure` says whether the error was the one that failed the Task, which is not always the last: a timed-out Task's `TIMED_OUT` is followed by its stopped process's exit code 143. A Task's `retryCount` says how many times it has been retried, and its `resubmittedToTaskId`/`resubmittedFromTaskId` link it to the copy a failure policy made.

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

`maxRetries` must be `>= 0`, and defaults to `0` when omitted, which defines the policy but retries nothing. `retryErrors` is optional — when omitted, all Task errors are eligible for retry.

A Task can tell which attempt it is from the `YD_RETRY_NUMBER` environment variable, which the YellowDog Agent sets: `0` for its first run, `1` for its first retry, and so on — for example, to resume from a checkpoint rather than start again.

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

A destination Task Group must not finish once all its Tasks have finished: the Platform refuses the Work Requirement unless each one sets `"finishIfAllTasksFinished": false` (`task group failure policy destinations ... will finish if all tasks finished`). It therefore stays `RUNNING` after its last Task has finished, and so does the Work Requirement, which ends only when it is finished or cancelled: `yd workrequirement finish` once the work is done (a `--follow` of it does not return until then).

Destinations are evaluated **in order**; the first matching entry wins. An entry without `resubmitErrors` matches every error, so only the last should leave it out, or those after it can never be reached; an empty `resubmissionDestinations` list is refused. A resubmitted Task becomes `RESUBMITTED` (a terminal status), and a copy is added to the destination Task Group with its `resubmittedFromTaskId` linking back to the original. The original Task carries `resubmittedToTaskId` pointing forward.

A Task resubmitted counts as finished in its own Task Group, which completes as usual; the copy follows its destination Task Group's policies, not the original's, so it is retried only if that Task Group has a `retryPolicy` of its own.

A complete example, retrying a Task once on exit code 3 and then resubmitting it to a fallback Task Group (on other Workers, say):

```json
{
  "taskType": "bash",
  "taskGroups": [
    {
      "name": "first",
      "workerTags": ["spot"],
      "retryPolicy": {
        "maxRetries": 1,
        "retryErrors": {
          "includes": [
            {"errorTypes": {"includes": ["PROCESS_NON_ZERO_EXIT"]}, "processExitCodes": {"includes": [3]}}
          ]
        }
      },
      "failurePolicy": {
        "resubmissionDestinations": [{"destinationTaskGroup": "fallback"}]
      },
      "tasks": [{"arguments": ["-c", "./run.sh"]}]
    },
    {
      "name": "fallback",
      "workerTags": ["on-demand"],
      "finishIfAllTasksFinished": false,
      "tasks": []
    }
  ]
}
```

Here the only destination omits `resubmitErrors`, so every error the retries did not clear is resubmitted. Once every Task has finished, wherever it ran, `yd workrequirement finish` ends the Work Requirement.

Common use cases:

- **Spot → on-demand fallback**: retry preemptions a few times in a spot-priced Task Group, then resubmit to an on-demand Task Group.
- **Out-of-memory → larger instance**: exit code 137 in a default-sized group resubmits to a Task Group with more `ram` or `vcpus`.

### Deprecated: `maximumTaskRetries` / `retryableErrors`

The legacy retry mechanism is still accepted but **cannot be combined with `retryPolicy`** on the same Task Group — `yd workrequirement submit` will reject the spec with a clear error, because both control how many times and on which errors a Task is retried. Using the legacy fields emits a one-time deprecation warning per invocation.

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

## Merging Additional Environment Variables into Tasks

The `addEnvironment` property allows a fixed set of environment variable key-value pairs to be merged into the `environment` of every Task, without replacing the entire `environment` property. The Task's `environment` is inherited as usual; then a key in both keeps the value from the `environment`, so `addEnvironment` only adds the keys the `environment` lacks.

`addEnvironment` can be set in the TOML `[workRequirement]` section, at the Work Requirement JSON level, or at the Task Group JSON level (not at the per-Task level), and it **accumulates** down those levels rather than being replaced: each level's table is added to those above it, and a key set at more than one level takes its value from the lowest. Setting it to `null` at a level clears what came from above, as `null` stops inheritance elsewhere.

### Example — TOML

```toml
[workRequirement]
    environment = {MY_VAR = "original", KEEP = "kept"}
    addEnvironment = {MY_VAR = "ignored", EXTRA = "new"}
    # Effective environment for each task: {MY_VAR = "original", KEEP = "kept", EXTRA = "new"}
```

### Example — JSON

```json
{
  "taskGroups": [
    {
      "environment": {"MY_VAR": "original", "KEEP": "kept"},
      "addEnvironment": {"MY_VAR": "ignored", "EXTRA": "new"},
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

`argumentsPrefix` and `argumentsPostfix` can be set at the same levels as `addEnvironment`: in the TOML `[workRequirement]` section, at the Work Requirement JSON level, or at the Task Group JSON level (not at the per-Task level). Unlike `addEnvironment`, which is merged down the levels, each is taken whole from the lowest level that sets it, as `arguments` is.

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

`taskDataFile` or `taskDataFiles` can be used inside `taskTemplate` as an alternative to `taskData`, exactly as they can at the Task level — the file contents are read client-side and used as the `taskData` value. `taskDataFiles` concatenates multiple files in order, a newline after each. Every Task Data file is substituted as it is read, `{{variable}}` by `{{variable}}`, as a User Data file is.

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

In addition to the property inheritance mechanism, some properties are set automatically by the `yd workrequirement submit` command, as a usage convenience if they're not explicitly specified.

### Work Requirement, Task Group and Task Naming

- The **Work Requirement** name is automatically set using a concatenation of the `[common]` `tag` (not `[workRequirement]`'s), a UTC timestamp and a process discriminator (see [Naming Rules](configuration.md#naming-rules)): e.g. `mytag_221024-1555241-4f`.
- **Task Group** names are automatically created for any Task Group that is not explicitly named, using names of the form `task_group_1` (or `task_group_01`, etc., for larger numbers of Task Groups). Task Group numbers can also be included in user-defined Task Group names using the `{{task_group_number}}` variable substitution discussed below.
- **Task** names are automatically created for any Task that is not explicitly named, using names of the form `task_1` (or `task_01`, etc., for larger numbers of Tasks). The Task counter resets for each different Task Group. Task numbers can also be included in user-defined Task names using the `{{task_number}}` variable substitution discussed below. Automatic Task name generation can be suppressed by setting the `setTaskNames` property to `false`, in which case the `task_name` variable will be set to `none`.

#### Obtaining Names/Context from Environment Variables at Task Run Time

When a Task executes, its Task name and number, Task Group name and number, Work Requirement name, Namespace, and Tag can be made automatically available to the Task in the following environment variables, if the `addYDEnvironment` property is set to `true` (which adds about 250 to 300 bytes to every Task; see [Submitting Large Numbers of Tasks](#submitting-large-numbers-of-tasks)):

- `YD_TASK_NAME`
- `YD_TASK_NUMBER`
- `YD_NUM_TASKS` (Number of Tasks in this Task Group)
- `YD_TASK_GROUP_NAME`
- `YD_TASK_GROUP_NUMBER`
- `YD_NUM_TASK_GROUPS` (Number of Task Groups in the Work Requirement)
- `YD_WORK_REQUIREMENT_NAME`
- `YD_NAMESPACE`
- `YD_TAG` (if set at the Task level)

This applies whether the names were set automatically by `yd workrequirement submit` or explicitly by the user.

In addition to the environment variables above, when a Task is executed by a Worker, the YellowDog Agent will set the following for use by the Task, based on the instance details and Task identification:

- `YD_PROVIDER`
- `YD_REGION`
- `YD_INSTANCE_TYPE`
- `YD_INSTANCE_ID`
- `YD_TASK_GROUP_ID`
- `YD_TASK_ID`
- `YD_RETRY_NUMBER` (`0` for a Task's first run, `1` for its first retry, and so on; see [Task Retries and Failure Policies](#task-retries-and-failure-policies))
- `YD_AGENT_DATA`
- `YD_AGENT_HOME`
- `YD_WORKER_SLOT`

### Task and Task Group Counts

The `taskCount` property can be used to expand the number of Tasks within a Task Group, by creating duplicates of a single Task; this can be handy for testing and demos. In JSON specifications, there must be exactly one Task listed within the Task Group, or `taskCount` is ignored with a warning. The `--task-count`/`-C` option of `yd workrequirement submit` sets it on the command line, overriding a `taskCount` set anywhere in the specification or the configuration file.

Also useful for testing, the `taskGroupCount` property or the command-line option `--task-group-count`/`-G` (which overrides the property) can be set to expand the number of Task Groups in the Work Requirement, by creating duplicates of a single Task Group; with more than one Task Group listed, it is ignored with a warning. The duplicates must be named apart, so a named Task Group expanded this way includes `{{task_group_number}}` in its name, or the submission is refused. If used, the `taskCount` property will apply to every Task Group, i.e. the total number of Tasks is the product of `taskGroupCount` and `taskCount`.

## Examples

### TOML Properties in the `workRequirement` Section

Here's an example of the `workRequirement` section of a TOML configuration file, showing all the possible properties that can be set. `taskData`, `taskDataFile` and `taskDataFiles` are alternatives, of which only one may be set at a given level, so the example uses `taskData`; likewise `csvFile` and `csvFiles`, and `workerTag` and `workerTags`. The deprecated `maximumTaskRetries` and `retryableErrors` (see [above](#deprecated-maximumtaskretries--retryableerrors)) cannot be combined with `retryPolicy` and are left out.

```toml
[workRequirement]
    addEnvironment = {EXTRA_VAR = "extra_value", MY_VAR = "override"}
    addYDEnvironment = true
    arguments = ["1", "TWO"]
    argumentsPostfix = ["--postfix-arg"]
    argumentsPrefix = ["--prefix-arg"]
    completedTaskTtl = 10
    disablePreallocation = false
    csvFiles = ["file1.csv", "file3.csv:3"]
    environment = {MY_VAR = "100"}
    failurePolicy = {resubmissionDestinations = [
      {destinationTaskGroup = "on-demand-tg", resubmitErrors = {includes = [{errorTypes = {includes = ["ALLOCATION_LOST"]}}]}},
    ]}
    finishIfAllTasksFinished = true
    finishIfAnyTaskFailed = false
    instancePricingPreference = "SPOT_THEN_ON_DEMAND"
    instanceTypes = ["t3a.micro", "t3.micro"]
    namespaces = ["namespace_1", "namespace_2"]
    maxWorkers = 1
    minWorkers = 1
    name = "my-work-requirement"
    parallelBatches = 5
    priority = 0.0
    providers = ["AWS"]
    ram = [0.5, 2.0]
    regions = ["eu-west-2"]
    retryPolicy = {maxRetries = 3, retryErrors = {includes = [
      {errorTypes = {includes = ["ALLOCATION_LOST"]}},
      {errorTypes = {includes = ["PROCESS_NON_ZERO_EXIT"]}, processExitCodes = {includes = [143]}},
    ]}}
    setTaskNames = false
    tag = "my_tag"
    taskBatchSize = 1000
    taskCount = 100
    taskData = "my_data_string"
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

Showing all possible properties at the Work Requirement level. `taskData`, `taskDataFile` and `taskDataFiles` are alternatives, of which only one may be set, so the example uses `taskData`; the deprecated `maximumTaskRetries` and `retryableErrors` are replaced by `retryPolicy`.

```json
{
  "addEnvironment": {"EXTRA_VAR": "extra_value", "MY_VAR": "override"},
  "addYDEnvironment": true,
  "arguments": [1, "TWO"],
  "argumentsPostfix": ["--postfix-arg"],
  "argumentsPrefix": ["--prefix-arg"],
  "completedTaskTtl": 10,
  "disablePreallocation": false,
  "environment": {"MY_VAR": "100"},
  "finishIfAllTasksFinished": true,
  "finishIfAnyTaskFailed": false,
  "instancePricingPreference": "SPOT_THEN_ON_DEMAND",
  "instanceTypes": ["t3a.micro", "t3.micro"],
  "maxWorkers": 1,
  "minWorkers": 1,
  "name": "my-work-requirement",
  "namespaces": ["namespace_1", "namespace_2"],
  "priority": 0.0,
  "providers": ["AWS"],
  "ram": [0.5, 2],
  "regions": ["eu-west-2"],
  "retryPolicy": {
    "maxRetries": 3,
    "retryErrors": {
      "includes": [
        {"errorTypes": {"includes": ["ALLOCATION_LOST"]}},
        {
          "errorTypes": {"includes": ["PROCESS_NON_ZERO_EXIT"]},
          "processExitCodes": {"includes": [143]}
        }
      ]
    }
  },
  "setTaskNames": false,
  "tag": "my_tag",
  "taskCount": 100,
  "taskData": "my_task_data_string",
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

Showing all possible properties at the Task Group level. `taskData`, `taskDataFile` and `taskDataFiles` are alternatives, of which only one may be set, so the example uses `taskData`; the deprecated `maximumTaskRetries` and `retryableErrors` are replaced by `retryPolicy`.

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
      "disablePreallocation": false,
      "environment": {"MY_VAR": "100"},
      "finishIfAllTasksFinished": true,
      "finishIfAnyTaskFailed": false,
      "instancePricingPreference": "SPOT_THEN_ON_DEMAND",
      "instanceTypes": ["t3a.micro", "t3.micro"],
      "maxWorkers": 1,
      "minWorkers": 1,
      "name": "first-task-group",
      "namespaces": ["namespace_1", "namespace_2"],
      "priority": 0.0,
      "providers": ["AWS"],
      "ram": [0.5, 2],
      "regions": ["eu-west-2"],
      "failurePolicy": {
        "resubmissionDestinations": [
          {
            "destinationTaskGroup": "second-task-group",
            "resubmitErrors": {"includes": [{"errorTypes": {"includes": ["ALLOCATION_LOST"]}}]}
          }
        ]
      },
      "retryPolicy": {
        "maxRetries": 3,
        "retryErrors": {
          "includes": [
            {"errorTypes": {"includes": ["ALLOCATION_LOST"]}},
            {
              "errorTypes": {"includes": ["PROCESS_NON_ZERO_EXIT"]},
              "processExitCodes": {"includes": [143]}
            }
          ]
        }
      },
      "setTaskNames": false,
      "tag": "my_tag",
      "taskCount": 5,
      "taskData": "my_task_data_string",
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
      "taskType": "docker",
      "tasks": [
        {}
      ]
    }
  ]
}
```

### JSON Properties at the Task Level

Showing all possible properties at the Task level. `taskData`, `taskDataFile` and `taskDataFiles` are alternatives, of which only one may be set, so the example uses `taskData`.

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

Variable substitutions can be used within any property value in TOML configuration files or Work Requirement JSON files. See [Variable Substitutions](variables.md) for more details. This is a powerful feature that allows Work Requirements to be parameterised by supplying values on the command line, via environment variables, or via the TOML file.

### Work Requirement Name Substitution

The name of the Work Requirement itself can be used via the variable substitution `{{wr_name}}`. This can be used anywhere in the `workRequirement` section of the TOML configuration file, or in JSON Work Requirement definitions.

### Task and Task Group Name Substitutions

The following naming and numbering substitutions are available for use in TOML and JSON Work Requirement specifications, along with the context(s) in which each variable can be used. The variables can be used within the value of any property.

| Directive               | Description                                       | Task | Task Group |
|:------------------------|:--------------------------------------------------|:-----|:-----------|
| `{{task_number}}`       | The current Task number, zero-padded              | Yes  |            |
| `{{task_name}}`         | The current Task name                             | Yes  |            |
| `{{task_group_name}}`   | The current Task Group name                       | Yes  | Yes        |
| `{{task_count}}`        | The number of Tasks in the current Task Group     | Yes  | Yes        |
| `{{task_group_number}}` | The current Task Group number, zero-padded        | Yes  | Yes        |
| `{{task_group_count}}`  | The number of Task Groups in the Work Requirement | Yes  | Yes        |

`{{task_number}}` and `{{task_group_number}}` are zero-padded to the width of the count they belong to: Task 7 is `7` in a Task Group of 9 Tasks, `07` in one of 50 and `007` in one of 100, and likewise Task Groups by the number of Task Groups. The automatically generated names (`task_007`, `task_group_02`) are padded the same way.

Padding makes anything named from the numbers sort in Task order — Task names in `yd task list` and the Portal, and output files such as `out-{{task_number}}.txt` in `yd data list` — where unpadded `task_10` would sort before `task_2`.

A padded number is still text with leading zeros, so take care where those mean something: in bash arithmetic, for example, `$((008))` fails because a leading zero means octal, and `10#` reads a padded number in base 10 instead: `n={{task_number}}; echo $((10#$n + 1))`. The `YD_TASK_NUMBER` and `YD_TASK_GROUP_NUMBER` environment variables (see [Obtaining Names/Context from Environment Variables at Task Run Time](#obtaining-namescontext-from-environment-variables-at-task-run-time)) hold the same numbers unpadded.

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

To examine the JSON that will actually be sent to the YellowDog API after all processing, use the `--dry-run` (`-D`) command-line option when running `yd workrequirement submit`. This will print the fully processed JSON for the Work Requirement. Nothing will be submitted to the Platform.

A dry-run is useful for inspecting the results of all the processing that's been performed. To suppress all output except for the JSON itself, add the `--quiet` (`-q`) command-line option.

Note that the generated JSON is a **consolidated form** of what would be submitted to the YellowDog API, and Tasks are incorporated directly within their Task Group data structures for ease of comprehension. In actual API submissions, the Work Requirement with zero or more Task Groups is submitted first, and Tasks are then added to their Task Groups separately, in subsequent API calls. Task Groups and Tasks can also later be added to the Work Requirement.

A simple example of the JSON output is shown below, showing a Work Requirement with a single Task Group, containing a single Task.

`% yd workrequirement submit --dry-run --quiet`

> **Note:** When used outside of `--dry-run`, `--quiet` on `yd workrequirement submit` prints only the Work Requirement YDID to stdout — see [yd workrequirement submit](commands.md#yd-workrequirement-submit) for scripting examples.

```json
{
  "namespace": "pyexamples-pwt",
  "name": "pyex-docker-pwt_240424-1205116-4f",
  "taskGroups": [
    {
      "name": "task_group_1",
      "runSpecification": {
        "taskTypes": ["docker"],
        "maximumTaskRetries": 0,
        "workerTags": ["pyex-docker-pwt-worker"]
      },
      "priority": 0,
      "starved": false,
      "waitingOnDependency": false,
      "finishIfAllTasksFinished": true,
      "finishIfAnyTaskFailed": false,
      "tasks": [
        {
          "name": "task_1",
          "taskType": "docker",
          "arguments": ["my_dockerhub_repo/my_container_image", "1", "2", "3"],
          "environment": {
            "YD_TASK_NAME": "task_1",
            "YD_TASK_NUMBER": "1",
            "YD_NUM_TASKS": "1",
            "YD_TASK_GROUP_NAME": "task_group_1",
            "YD_TASK_GROUP_NUMBER": "1",
            "YD_NUM_TASK_GROUPS": "1",
            "YD_WORK_REQUIREMENT_NAME": "pyex-docker-pwt_240424-1205116-4f",
            "YD_NAMESPACE": "pyexamples-pwt"
          }
        }
      ]
    }
  ],
  "tag": "pyex-docker-pwt"
}
```

### Adding Task Groups and Tasks to an Existing Work Requirement

The `--empty` (`-e`) option submits a new Work Requirement with no Task Groups or Tasks (using TOML configuration only: a specification or CSV file, given or configured, is refused with it), providing a named shell that can be populated later using `--add-to`:

```bash
WR_ID=$(yd workrequirement submit --empty --quiet)
yd workrequirement submit --add-to "$WR_ID" my-spec.json
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
yd workrequirement submit --add-to my-work-requirement my-spec.json
```

The Work Requirement specification supplied is processed in the same way as for a normal submission. The resulting Task Groups are then matched against the Task Groups already present in the target Work Requirement, by name:

- **Matching Task Group name**: the new Tasks are appended to the existing Task Group; the specification's own settings for that Task Group (`priority`, `workerTags`, `dependencies` and the rest) are not applied, the existing Task Group keeping its own, though the properties its Tasks inherit are taken from it, as below. Their numbers continue from where the existing Tasks left off, and `{{task_count}}` (in their names and other properties alike, and `YD_NUM_TASKS`) is the Task Group's whole count, the existing Tasks and the new. The Platform updates a Task Group's count of Tasks a few seconds after Tasks are added to it, so `--add-to` first looks in the Task Group for the name its first new Task would be given: when that name is already there, because Tasks were added moments before, it says so and waits for the count to catch up, up to 10 seconds at a time, before numbering the new Tasks; a name still there once the count has stood still for 10 seconds is one already in use, and the submission is refused. Tasks without names (`setTaskNames = false`) have no name to look for, so the existing Tasks are counted instead, which for a large Task Group takes a moment.
- **New Task Group name**: the Task Group is added to the Work Requirement, and its Tasks are submitted in the normal way, numbered from 1. Its own number continues from the Work Requirement's existing Task Groups, the new ones numbered in the order given, and `{{task_group_count}}` is the Work Requirement's count once they are added, in the Task Group's own properties as in its Tasks'.

Which Task Groups already exist is decided by their names, so a Task Group named by its own number (`tg_{{task_group_number}}`) that would come to name another Task Group once numbered is refused: give it a name of its own.

A single `yd workrequirement submit --add-to` invocation can add a mix of new Task Groups and Tasks to existing Task Groups simultaneously.

What is taken from each part of the specification:

| Part of the specification | For a new Task Group | For an existing Task Group (matched by name) |
|:---|:---|:---|
| The Work Requirement's own settings (its name and tag, and its `priority` as the Work Requirement's) | not applied: the target Work Requirement keeps its own | not applied |
| What the Work Requirement level passes down (`priority`, `workerTags`, `arguments`, `environment` and the other inherited properties) | inherited by the Task Group and its Tasks | the Task properties (`arguments`, `environment` and the like) inherited by the new Tasks; the Task Group's (`priority`, `workerTags` and the like) not applied |
| The Task Group's own settings (`priority`, the run specification: `taskTypes`, `workerTags`, `dependencies` and the rest) | applied, as the Task Group is created | not applied: the existing Task Group keeps its own |
| What the Task Group level passes down to its Tasks (`arguments`, `environment`, `taskType`, `timeout`, `taskData` and the rest) | inherited by its Tasks | inherited by the new Tasks |
| The Tasks | added, numbered from 1 | added, numbered on from the existing Tasks, each `taskType` in the Task Group's `taskTypes` (or the submission is refused) |

So a specification written to add Tasks to an existing Task Group can carry the Task-level defaults those Tasks need at its Task Group level, as a new submission would, while the Task Group's scheduling stays as it was submitted.

As with a normal `yd workrequirement submit`, `--follow` (or `-f`) can be used to follow the Work Requirement to completion after additions have been submitted.

If adding Tasks fails part-way, the target Work Requirement is not cancelled, as a newly submitted one would be: any Tasks already added remain in it, and any files uploaded for them are left in place, since those Tasks may need them. A warning says so, and `yd workrequirement submit` exits with a non-zero status.

If the spec contains `taskDataInputs` with `localPath` entries, those files will be uploaded to the remote destination as usual. A file already at its upload path, from the original submission or otherwise, is skipped by default, whether or not the local file has changed since. Use `--overwrite` (`-O`) to upload it again:

```bash
yd workrequirement submit --add-to my-work-requirement --overwrite my-spec.json
```

By default, `yd workrequirement submit` checks whether a file already exists at the remote destination before uploading, and skips it if so. With `--overwrite`, any file present in the spec is uploaded unconditionally, replacing any existing remote copy.

`--dry-run` (`-D`) can be used with `--add-to` to report what would be added, without adding it. Unlike a normal dry run, which contacts the platform not at all, this one reads the target Work Requirement — the names, numbering and Task counts of its existing Task Groups are what determine the names and offsets of everything that would be added — so credentials and connectivity are required. The checks that depend on the target are therefore made as well: that it exists, that it is `RUNNING` or `HELD`, and that no Task's type falls outside an existing Task Group's `taskTypes` allowlist. Nothing is created, updated or uploaded.

The specification printed shows the Work Requirement as it would be: the existing Task Groups as well as the new ones, with the Tasks that would be added attached to whichever Task Group takes them. A `DRY-RUN` line above it names the Task Groups that are already present, because the platform reports only a summary of their Tasks, so those Task Groups appear in the specification without any Tasks of their own.

### Submitting 'Raw' JSON Work Requirement Specifications

It's possible to use the JSON output of `yd workrequirement submit --dry-run` (such as the example above) as a self-contained, fully specified Work Requirement specification, using the `--json-raw` (or `-j`) command-line option, i.e. `yd workrequirement submit --json-raw <filename.json>`.

This will submit the Work Requirement, then add all the specified Tasks, using `--parallel-batches` (or the `parallelBatches` configuration property) and following with `--follow` or `--progress` as for any other submission. A batch that fails in a way a retry could cure is retried, as any other submission's are; if the Platform refuses a batch of Tasks, the Work Requirement is cancelled and `yd workrequirement submit` exits with a non-zero status naming the kind of failure.

Note that variable substitutions **can** be used in the raw JSON file, just as in the other Work Requirement JSON examples, but there is no property inheritance, including from the `[workRequirement]` section of the TOML configuration or from Work Requirement properties supplied on the command line.

## Submitting Large Numbers of Tasks

With tens of thousands of Tasks or more, how the Tasks are sent decides how long a submission takes, and what each Task carries decides how much is sent and stored.

**Sending the Tasks.** Tasks are added to their Task Groups in batches of `taskBatchSize` (1,000 by default, up to 10,000), one batch at a time unless `parallelBatches` (or `--parallel-batches`) sends several at once. A batch that fails in a way a retry could cure is resubmitted.

**Keeping each Task small.** Every byte on a Task is sent and stored once per Task, so:

- Put what the Tasks of a Task Group share — their `taskType`, `taskData` and `environment` — in a [`taskTemplate`](#task-templates), which the Platform applies, rather than on every Task.
- Leave `addYDEnvironment` off. Its variables ([Obtaining Names/Context from Environment Variables at Task Run Time](#obtaining-namescontext-from-environment-variables-at-task-run-time)) add about 250 to 300 bytes to every Task, more with long Work Requirement, Task Group or namespace names. Pass a Task what it needs in its arguments instead, with the [Task and Task Group name substitutions](#task-and-task-group-name-substitutions): `"arguments": ["--frame", "{{task_number}}"]` on the Task Group gives each Task its own number at the cost of a few bytes.
- Consider `setTaskNames: false`, which leaves Tasks without names, saving each Task its name. Two things are lost with the names: a batch whose response times out is then not resubmitted, since the Platform might already have added it and nothing would tell a duplicate (the submission fails instead, saying to check the Work Requirement's Tasks); and a Task can no longer be found by its name (`yd task show wr/tg/task`).
- Keep `taskData` small: a large input is better fetched by each Task as it runs, with [`taskDataInputs`](#specifying-data-client-inputs), than carried in every Task.

## Using the YellowDog Data Client

The YellowDog Data Client is described at https://docs.yellowdog.ai/#/the-platform/the-data-client.

The CLI provides full support for expressing Data Client inputs and outputs as part of Task specifications. In addition, it can provide automatic upload of objects on the local filesystem to Data Client targets. It does this using a local `rclone` binary that will be downloaded to your system the first time the Data Client upload capability is used, if `rclone` is not already present.

An `rclone` already on your `$PATH` is used in preference and is never modified; the downloaded copy is stored in `rclone_api`'s own per-user cache directory (`~/Library/Caches/rclone_api` on macOS, `~/.cache/rclone_api` on Linux, and under `%LOCALAPPDATA%` on Windows), not inside the Python package, so it survives reinstallation of the CLI.

To see which binary is in use, run `yd workrequirement submit --which-rclone` or `yd version --debug`; to force an upgrade of the downloaded copy to the latest version, run `yd workrequirement submit --upgrade-rclone`. Both options are accepted by the Data Client commands as well as by `yd workrequirement submit`, i.e. by `yd data upload`, `yd data download`, `yd data delete`, `yd data list`, and `yd data copy`.

Task data inputs and outputs support only **individual files**, not directories or wildcards. If multiple, unspecified files are required, we recommend you compress/decompress them into a single file. The compression/decompression can be handled as part of the execution of the Task at its start and/or conclusion.

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

The `yd workrequirement submit` command can automatically upload files in the `taskDataInputs` list. This is enabled by adding the `localPath` property, and optionally the `uploadPath` property, to the relevant input specification, e.g.:

TOML, in the `workRequirement` section:

```toml
taskDataInputs = [
  {localPath = "my_local_file", uploadPath = "in_upload_path_1", source = "in_src_path_1", destination = "dest_path_1"},
]
```

JSON:

```json
"taskDataInputs": [
  {
    "localPath": "my_local_file",
    "uploadPath": "in_upload_path_1",
    "source": "in_src_path_1",
    "destination": "dest_path_1"
  }
]
```

If `uploadPath` is not specified, the local file will be uploaded to the rclone target specified by the `source` property. The local file can be specified using an absolute or relative pathname. A relative one is found from the files directory: the `--content-path <directory>`/`-F` option supplied to `yd workrequirement submit`, else the specification file's directory, else the configuration file's (as Task Data files and CSV files are). Two different local files given the same upload path are refused.

If `yd workrequirement submit` fails for any reason while submitting a new Work Requirement, the Work Requirement is cancelled and the objects it uploaded are deleted automatically; with `--add-to`, the Tasks already added and the files uploaded for them are left in place, with a warning. An object that was already at its upload path is left in place, whether it was skipped or replaced with `--overwrite`, since another Work Requirement may be using it.

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

This section discusses the context within which a Task operates when it's executed by a Worker on a node. It describes the YellowDog Agent running on a Linux node, configured using the default username, directories, etc.; [Windows Nodes](#windows-nodes) gives the differences on Windows. Configurations can vary.

### Task Execution Steps

When a Task is allocated to a Worker on a node by the YellowDog Scheduler, the following steps are followed:

1. The Agent running on the node gets the Task's properties: its `taskType`, `arguments`, `environment`, `taskData`. A number of `YD_` environment variables are also automatically set by a combination (optionally) of `yd workrequirement submit` and the Agent itself — see above for details.
2. An ephemeral working directory is created. Data Client input objects are downloaded to this directory, and the contents of the `taskData` property (if set) are written to the file `taskdata.txt`.
3. The Agent runs the command specified for the `taskType` in the Agent's `application.yaml` configuration file. This is done as a simple `exec` of a subprocess to run the Task.
4. When the Task concludes, the Agent uses the exit code of the subprocess to report success (zero) or failure (non-zero).
5. The Agent uploads any Data Client outputs specified in `taskDataOutputs` to their destinations. The ephemeral Task directory is then deleted.

Note that if a Task is aborted during execution, the Task's subprocess is sent a `SIGTERM` (on Linux), allowing the Task an opportunity to terminate any child processes or other resources (e.g. containers) that may have been started as part of Task execution. In addition, there is the option to set an `abort` clause as part of the Task Type specification in the Agent's `application.yaml` file, in which case the script specified in the `abort` clause takes over complete responsibility for any abort handling.

Once the steps above have been completed, the Worker is ready to process its next Task.

Note that if the Agent on a node advertises multiple Workers, then Tasks are executed in parallel on the node and can start and stop independently.

### The User and Group used for Tasks

By default, in the standard YellowDog Agent VM images and in images/instances created using the [YellowDog Agent Installer Script](https://github.com/yellowdog/resources/blob/main/agent-install/linux/README.md), the Agent runs as user and group `yd-agent`, and hence Tasks also execute under this user.

`yd-agent` does not have `sudo` privileges as standard, but this can be added if required (e.g.) at instance boot time via the `userData` property of a provisioning request, e.g.:

```shell
echo "yd-agent ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/020-yd-agent
chmod 440 /etc/sudoers.d/020-yd-agent
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

Ephemeral Task working directories are by default created under `/var/opt/yellowdog/agent/data/workers`, named using their YellowDog Task IDs with colons substituted by underscores (on Windows, see [Windows Nodes](#windows-nodes)).

When a Task is started by a worker, an ephemeral directory is created, e.g.:

`/var/opt/yellowdog/agent/data/workers/ydid_task_559EBE_74949336-ac2b-4811-a7d5-f3ecd9739908_1_1`

This is the directory into which downloaded objects are placed, and in which output files are created by default. The console output file, `taskoutput.txt`, containing combined `stderr` and `stdout` output will also be created in this directory.

Note that the Task directory — including `taskoutput.txt` — is **ephemeral**: it is deleted once the Task completes and its outputs have been uploaded. To preserve console output beyond Task execution, add `taskoutput.txt` as a `taskDataOutputs` entry.

### Windows Nodes

On a Windows node, with the Agent installed by its MSI installer or the [YellowDog Agent Installer Script for Windows](https://github.com/yellowdog/resources/blob/main/agent-install/windows/README-INSTALLER.md), the Task Execution Steps above are the same, but the user, the directories and abort handling differ:

| | Linux | Windows |
|---|---|---|
| The Agent | User and group `yd-agent` | The Windows service `yd-agent`, running as `LocalSystem` by default |
| Installation directory (`YD_AGENT_HOME`) | `/opt/yellowdog/agent` | `C:\Program Files\YellowDog\Agent` |
| Configuration file | `/opt/yellowdog/agent/application.yaml` | `C:\Program Files\YellowDog\Agent\config\application.yaml` |
| Data directory (`YD_AGENT_DATA`) | `/var/opt/yellowdog/agent/data` | `C:\ProgramData\YellowDog\Agent` |
| Task directories | `/var/opt/yellowdog/agent/data/workers` | `C:\ProgramData\YellowDog\Agent\workers` |
| Task abort, with no `abort` clause | The Task's process is sent a `SIGTERM` | The Task's process is terminated |

**The user.** Tasks run as the Agent's service account, `LocalSystem` unless the MSI was installed with its `SERVICE_ACCOUNT` property naming another, so by default they have full administrative rights on the node: nothing like the `sudo` set-up above is needed, and a Task can change anything on the node. A `LocalSystem` Task's user profile is the system profile, `C:\Windows\System32\config\systemprofile`, so `%USERPROFILE%`, `%AppData%` and `%LocalAppData%` all point inside it, and a tool that keeps its configuration or cache in the user's profile keeps it there. `YD_AGENT_HOME` and `YD_AGENT_DATA` are system environment variables, and `C:\ProgramData\YellowDog\Agent\scripts` is on the system `PATH`, so Tasks see them too.

**Task Types.** The installer script defines two general-purpose Task Types, `cmd` (running `cmd.exe`) and `powershell` (running `powershell.exe`), and a Task's `arguments` are passed to that command, so a `cmd` Task's arguments start with `/c` (e.g. `["/c", "my_script.bat"]`) and a `powershell` Task's with `-File` or `-Command`. These Task Types can run arbitrary commands on the node; for production use, Task Types running specific scripts are recommended.

**Aborting a Task.** Without an `abort` clause, an aborted Task's process is terminated, with no chance to clean up after itself, and any child processes it started are left running. The installer script's Task Types therefore name the abort handler supplied with the Agent, `yd_abort.bat` (in `C:\ProgramData\YellowDog\Agent\scripts`, which is on the `PATH`), which is passed the Task's process ID and ends the Task's whole process tree (`taskkill /F /T /PID <pid>`).

**The Task directory.** Task directories are created under `C:\ProgramData\YellowDog\Agent\workers`, named as on Linux, and hold the same `taskdata.txt` and `taskoutput.txt`; they are just as ephemeral.

**Logging in.** To inspect a node, e.g. for debugging, connect over RDP as an administrator rather than as the Agent's user, which is not an account that can log in. The Agent's own output is in `C:\Program Files\YellowDog\Agent\output.log` and `error.log`, holding the current run of the service only.

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

Note that the Task Group must contain only a single Task, acting as the prototype. A prototype holding no `<<variable>>` that names a heading of its CSV file is not expanded, with a warning.

Now consider a CSV file `wr_data.csv` with the following contents:

```text
arg_1, arg_2, arg_3, env_1
A,     B,     C,     E-1
D,     E,     F,     E-2
G,     H,     I,     E-3
```

Note that the (optional) leading spaces after each comma are ignored, but trailing spaces are not and will form part of the imported data.

If these files are processed using `yd workrequirement submit wr.json -V wr_data.csv`, the following expanded list of three Tasks will be created prior to further processing by the `yd workrequirement submit` command:

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

All variable substitutions unrelated to the CSV file data are left unchanged, for subsequent processing by `yd workrequirement submit`.

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

The `yd workrequirement submit` command would then be invoked with a separate CSV file for each Task Group, e.g.:

```shell
yd workrequirement submit wr.json -V wr_data_task_group_1.csv -V wr_data_task_group_2.csv
```

If there are **fewer** CSV files than Task Groups, a note is printed and, if there are 'n' CSV files, CSV data processing will be applied to the first 'n' Task Groups in the Work Requirement by default, in the order in which the CSV files were supplied. If there are **more** CSV files than Task Groups, an error will be raised and processing will stop.

It is possible to apply CSV files explicitly to specific Task Groups, by using an optional **index postfix** (e.g. `:2`) at the end of each CSV filename. For example, if there are two CSV files to be applied to the second and fourth Task Groups in a JSON Work Requirement, use the following syntax:

```shell
yd workrequirement submit wr.json -V wr_data_task_group_2.csv:2 -V wr_data_task_group_4.csv:4
```

Alternatively, the **Task Group name** (if supplied in the JSON file) can be used as the postfix. For example, if the Task Groups above are named `tg_two` and `tg_four`, the `yd workrequirement submit` command would become:

```shell
yd workrequirement submit wr.json -V wr_data_task_group_2.csv:tg_two -V wr_data_task_group_4.csv:tg_four
```

Note that only one CSV file can be applied to any given Task Group, however it is chosen (by position, number or name): two for the same Task Group are an error naming both. A single CSV file can, however, be reused for multiple Task Groups.

### Using CSV Data with Simple, TOML-Only Work Requirement Specifications

It's possible to use TOML exclusively to derive a list of Tasks from CSV data — i.e. a JSON Work Requirement specification is not required.

To make use of this:

1. Ensure that no JSON Work Requirement document is specified (no `workRequirementData` in the TOML file, or no positional argument on the command line)
2. Insert the required CSV-supplied variable substitutions directly into the TOML properties, e.g. `arguments = ["<<arg_1>>", "<<arg_2>>"]`
3. Specify a single CSV file in the `csvFiles` TOML property, e.g. `csvFiles = ["wr_data.csv"]`, or provide the CSV file on the command line `-V wr_data.csv`; naming more than one is an error, since there is only one Task Group to apply them to

When `yd workrequirement submit` is run, it will expand the Task list to match the number of data rows in the CSV file.

In this form the CSV substitutions are made only in the properties a Task takes: `addYDEnvironment`, `arguments`, `environment`, `setTaskNames`, `taskData`, `taskDataFile`, `taskDataFiles`, `taskDataInputs`, `taskDataOutputs`, `taskGroupName`, `taskName`, `taskTimeout`, `taskType` and `timeout`. A `<<variable>>` anywhere else in the `[workRequirement]` section, such as `argumentsPrefix`, `addEnvironment` or `taskTemplate`, is left as written.

### Inspecting the Results of CSV Variable Substitution

The `--process-csv-only` (or `-p`) option can be used with `yd workrequirement submit` to output the JSON Work Requirement after CSV variable substitutions only, prior to all other substitutions and property inheritance applied by `yd workrequirement submit`.
