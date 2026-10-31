# Work Requirements

<!--ts-->
   * [Examples](#examples)
      * [A Work Requirement from the Configuration File](#a-work-requirement-from-the-configuration-file)
      * [Several Task Groups in a JSON Specification](#several-task-groups-in-a-json-specification)
      * [Sending Files to Tasks and Collecting Their Results](#sending-files-to-tasks-and-collecting-their-results)
   * [Work Requirement JSON File Structure](#work-requirement-json-file-structure)
   * [Property Inheritance](#property-inheritance)
      * [Stopping Inheritance with null](#stopping-inheritance-with-null)
         * [Details](#details)
      * [Overriding Inherited Properties on the Command Line](#overriding-inherited-properties-on-the-command-line)
   * [Work Requirement Property Dictionary](#work-requirement-property-dictionary)
   * [Automatic taskTypes Population](#automatic-tasktypes-population)
         * [Details](#details-1)
   * [Task Retries and Failure Policies](#task-retries-and-failure-policies)
      * [Selecting errors (Selection&lt;TaskErrorSelector&gt;)](#selecting-errors-selectiontaskerrorselector)
      * [Task Error Types](#task-error-types)
      * [Finding the Errors Your Tasks Hit](#finding-the-errors-your-tasks-hit)
      * [retryPolicy](#retrypolicy)
      * [failurePolicy](#failurepolicy)
         * [Details](#details-2)
      * [Deprecated: maximumTaskRetries / retryableErrors](#deprecated-maximumtaskretries--retryableerrors)
         * [Migration](#migration)
   * [Merging Additional Environment Variables into Tasks](#merging-additional-environment-variables-into-tasks)
      * [Example — TOML](#example--toml)
      * [Example — JSON](#example--json)
         * [Details](#details-3)
   * [Argument Prefix and Postfix](#argument-prefix-and-postfix)
      * [Example — TOML](#example--toml-1)
      * [Example — JSON](#example--json-1)
         * [Details](#details-4)
   * [Task Templates](#task-templates)
      * [Example — TOML](#example--toml-2)
      * [Example — JSON](#example--json-2)
         * [Details](#details-5)
   * [Automatic Properties](#automatic-properties)
      * [Work Requirement, Task Group and Task Naming](#work-requirement-task-group-and-task-naming)
         * [Obtaining Names/Context from Environment Variables at Task Run Time](#obtaining-namescontext-from-environment-variables-at-task-run-time)
      * [Task and Task Group Counts](#task-and-task-group-counts)
         * [Details](#details-6)
   * [All Properties](#all-properties)
      * [Properties in the workRequirement Section](#properties-in-the-workrequirement-section)
      * [Properties at the Work Requirement Level](#properties-at-the-work-requirement-level)
      * [Properties at the Task Group Level](#properties-at-the-task-group-level)
      * [Properties at the Task Level](#properties-at-the-task-level)
   * [Variable Substitutions in Work Requirement Properties](#variable-substitutions-in-work-requirement-properties)
      * [Work Requirement Name Substitution](#work-requirement-name-substitution)
      * [Task and Task Group Name Substitutions](#task-and-task-group-name-substitutions)
         * [Details](#details-7)
   * [Task Group Statuses](#task-group-statuses)
         * [Details](#details-8)
   * [Dry-Running Work Requirement Submissions](#dry-running-work-requirement-submissions)
      * [Adding Task Groups and Tasks to an Existing Work Requirement](#adding-task-groups-and-tasks-to-an-existing-work-requirement)
         * [Details](#details-9)
      * [Submitting 'Raw' JSON Work Requirement Specifications](#submitting-raw-json-work-requirement-specifications)
         * [Details](#details-10)
   * [Submitting Large Numbers of Tasks](#submitting-large-numbers-of-tasks)
   * [Using the YellowDog Data Client](#using-the-yellowdog-data-client)
      * [Specifying Data Client Inputs](#specifying-data-client-inputs)
      * [Using Files Uploaded with yd data](#using-files-uploaded-with-yd-data)
      * [Automatic Upload of Local Files](#automatic-upload-of-local-files)
         * [Details](#details-11)
      * [Rclone Authentication](#rclone-authentication)
      * [Specifying Data Client Outputs](#specifying-data-client-outputs)
      * [The rclone Binary](#the-rclone-binary)
   * [Task Execution Context](#task-execution-context)
      * [Task Execution Steps](#task-execution-steps)
      * [Where Task Types Come From](#where-task-types-come-from)
      * [The docker Task Type](#the-docker-task-type)
         * [Details](#details-12)
      * [The User and Group used for Tasks](#the-user-and-group-used-for-tasks)
      * [Home Directory for yd-agent](#home-directory-for-yd-agent)
      * [Task Execution Directory](#task-execution-directory)
      * [Windows Nodes](#windows-nodes)
   * [Specifying Work Requirements using CSV Data](#specifying-work-requirements-using-csv-data)
      * [Work Requirement CSV Data Example](#work-requirement-csv-data-example)
         * [Details](#details-13)
      * [CSV Variable Substitutions](#csv-variable-substitutions)
         * [Details](#details-14)
      * [Property Inheritance](#property-inheritance-1)
      * [Multiple Task Groups using Multiple CSV Files](#multiple-task-groups-using-multiple-csv-files)
         * [Details](#details-15)
      * [Using CSV Data with Simple, TOML-Only Work Requirement Specifications](#using-csv-data-with-simple-toml-only-work-requirement-specifications)
         * [Details](#details-16)
      * [Inspecting the Results of CSV Variable Substitution](#inspecting-the-results-of-csv-variable-substitution)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Wed Oct 28 09:22:01 GMT 2026 -->

<!--te-->


A **Work Requirement** is the top-level unit of work submitted to the YellowDog platform. It contains one or more **Task Groups**, each of which contains one or more **Tasks**. Work Requirements are created and submitted using the **`yd workrequirement submit`** command, and can be updated after submission — adding Task Groups or Tasks — using the `--add-to` option.

The `workRequirement` section of the configuration file is optional. It's used only by the `yd workrequirement submit` command, and controls the Work Requirement that is submitted to the Platform.

**Jump to:** [Property Dictionary](work-requirement-property-dictionary.md#work-requirement-property-dictionary) · [Task Templates](#task-templates) · [Automatic Properties](#automatic-properties) · [Examples](#examples) · [All Properties](#all-properties) · [Variable Substitutions](#variable-substitutions-in-work-requirement-properties) · [Dry-Running](#dry-running-work-requirement-submissions) · [Data Client](#using-the-yellowdog-data-client) · [Task Execution Context](#task-execution-context) · [CSV Data](#specifying-work-requirements-using-csv-data)

The details of a Work Requirement to be submitted can be captured entirely within the TOML configuration file for simple (single Task Group) examples. More complex examples capture the Work Requirement in a combination of the TOML file plus a JSON document, or in a JSON document only.

## Examples

Each example runs in a directory whose `config.toml` holds your Application key and secret, namespace and tag in its `[common]` section, as `yd init` writes them. Its Tasks need a Worker Pool whose Workers carry the same Worker Tag, such as the one in the [Worker Pool examples](worker-pools.md#examples). The `bash` Task Type, in the YellowDog Agent's default configuration, runs `/bin/bash` with the Task's arguments.

### A Work Requirement from the Configuration File

For a single Task Group, the `[workRequirement]` section of `config.toml` is enough. This one submits 20 Tasks, each processing one frame:

```toml
[workRequirement]
    taskType = "bash"
    arguments = ["-c", "echo Processing frame {{task_number}}"]
    taskCount = 20
    workerTag = "render"
```

```bash
yd workrequirement submit --follow
```

`{{task_number}}` gives each Task its own number, `01` to `20`, padded to the same width (see [Task and Task Group Name Substitutions](#task-and-task-group-name-substitutions)). Add `--dry-run` to print the Work Requirement without submitting it.

### Several Task Groups in a JSON Specification

For more than one Task Group, write the Work Requirement as a JSON specification. In this `trailer.json`, the `encode` Task Group starts only when every Task in `render` has succeeded:

```json
{
  "taskGroups": [
    {
      "name": "render",
      "taskCount": 20,
      "tasks": [{"arguments": ["-c", "echo Rendering frame {{task_number}}"]}]
    },
    {
      "name": "encode",
      "dependencies": ["render"],
      "taskCount": 1,
      "tasks": [{"arguments": ["-c", "echo Encoding the trailer"]}]
    }
  ]
}
```

```bash
yd workrequirement submit --follow trailer.json
```

Both Task Groups take their `taskType` and `workerTag` from the `[workRequirement]` section above (see [Property Inheritance](#property-inheritance)).

### Sending Files to Tasks and Collecting Their Results

Tasks can download their input files from a remote data store, such as an S3 bucket, and upload their results to it. Here each of four Tasks fetches the script `make-thumbnails.sh` and its own batch of photos, runs the script, and uploads the `thumbnails.zip` it makes:

```toml
[common.variables]
    bucket = "rclone:S3,type=s3,provider=AWS,env_auth=true,region=eu-west-2,location_constraint=eu-west-2:my-photos"

[workRequirement]
    taskType = "bash"
    arguments = ["make-thumbnails.sh", "{{task_number}}"]
    taskCount = 4
    workerTag = "render"
    taskDataInputs = [
        {localPath = "make-thumbnails.sh", source = "{{bucket}}/scripts/make-thumbnails.sh", destination = "local:make-thumbnails.sh"},
        {source = "{{bucket}}/originals/batch_{{task_number}}.zip", destination = "local:originals.zip"},
    ]
    taskDataOutputs = [
        {source = "local:thumbnails.zip", destination = "{{bucket}}/thumbnails/batch_{{task_number}}.zip"},
    ]
```

`localPath` uploads `make-thumbnails.sh` from the current directory to the bucket as the Work Requirement is submitted, so each Task can download it. `env_auth=true` takes the AWS credentials from the environment: yours when the script is uploaded, and the node's, such as an instance role, when Tasks download and upload. See [Using the YellowDog Data Client](#using-the-yellowdog-data-client).

## Work Requirement JSON File Structure

A JSON specification holds a Work Requirement, which contains a list of Task Groups, each of which contains a list of Tasks. This `photos.json` has two Task Groups of two Tasks, each Task with its own arguments:

```json
{
  "taskGroups": [
    {
      "name": "resize",
      "tasks": [
        {"arguments": ["resize.sh", "holiday.jpg"]},
        {"arguments": ["resize.sh", "wedding.jpg"]}
      ]
    },
    {
      "name": "watermark",
      "tasks": [
        {"arguments": ["watermark.sh", "holiday.jpg"]},
        {"arguments": ["watermark.sh", "wedding.jpg"]}
      ]
    }
  ]
}
```

Name the file on the command line:

```bash
yd workrequirement submit photos.json
```

Or name it in the `workRequirementData` property of the `[workRequirement]` section, and leave it off the command line. A file named on the command line overrides the property.

The document may also be written in [Jsonnet](jsonnet.md), or in TOML.

## Property Inheritance

A property set at a higher level is inherited by the levels below it, unless a lower level sets it too. So a property needed by every Task can be set once rather than on every Task.

The levels, from the top, are the `[workRequirement]` section of the TOML file, then the Work Requirement, its Task Groups and their Tasks in the JSON document. A property is inherited only by the levels that take it. A value set part-way down is inherited from there: a property set on a Task Group is inherited by that Task Group's Tasks unless a Task sets its own.

For example, with `taskType = "bash"` in the `[workRequirement]` section, every Task in this specification is a `bash` Task, and the Tasks of `resize` all take its `arguments`:

```json
{
  "taskGroups": [
    {
      "name": "resize",
      "arguments": ["resize.sh"],
      "taskCount": 3,
      "tasks": [{}]
    }
  ]
}
```

### Stopping Inheritance with `null`

To stop a property being inherited, set it to `null` at the level that should not receive it. The property then has its default at that level and every level below it, as if it had been set nowhere. For example, with `arguments = ["--verbose"]` and `priority = 5.0` in the `[workRequirement]` section of the TOML file:

```json
{
  "taskGroups": [
    {"name": "plain", "arguments": null, "priority": null, "tasks": [{"name": "task-1"}]},
    {"name": "verbose", "tasks": [{"name": "task-2"}, {"name": "task-3", "arguments": null}]}
  ]
}
```

`task-1` runs with no arguments, in a Task Group with no priority. `task-2` inherits `["--verbose"]` and its Task Group a priority of `5.0`, while `task-3` stops the inheritance for itself alone.

For a list or a table, an empty value (`[]` or `{}`) also stops the inheritance, with the same result.

#### Details

**The defaults.** A property stopped with `null` takes the default the [Property Dictionary](work-requirement-property-dictionary.md) gives it: no `priority`, no `arguments`, no Task Data, `setTaskNames` true, and so on.

**Where `null` can be used.** `null` can be used for any inherited property, at any level with a level above it to inherit from. The TOML file counts as a level, so `null` at the Work Requirement level stops a TOML value. The TOML file is the top of the hierarchy, so it has nothing to stop; TOML cannot express `null` in any case.

**`name` and `tag`.** These are not inherited, so there is nothing for `null` to stop.

**`taskType` and `taskTypes`.** A Task must have a Task Type, so a `null` `taskType` is treated as though the Task set none: it takes its Task Group's, as described in [Automatic `taskTypes` Population](#automatic-tasktypes-population). The schema check warns of a `null` `taskType`, and `--validate` reports it, so leaving the property out is the better way. `"taskTypes": null` on a Task Group means it declares no Task Types of its own, and takes them from its Tasks.

**Task Data.** `taskData`, `taskDataFile` and `taskDataFiles` are one setting: the first level to set any of them supplies the Task Data. So an inherited one is stopped by setting any one of the three, to `null` or to an empty value.

**`null` is not unset.** Removing a property with the [unset syntax](variables.md#removing-properties-using-the-unset-suffix) is different. A property removed by `{{::}}` (or by `{{variable::}}` with the variable undefined) is treated as never written at that level, so it is still inherited from the level above. See [Unset Properties and Property Inheritance](variables.md#unset-properties-and-property-inheritance).

### Overriding Inherited Properties on the Command Line

A `--property workRequirement.<key>=<value>` override is the exception to lower levels winning. It replaces the property wherever the JSON document sets it, at every level, as a command-line value beats a file's (see [Which Value Wins](configuration.md#which-value-wins)):

```bash
yd workrequirement submit --property workRequirement.priority=10 photos.json
```

## Work Requirement Property Dictionary

Every property available for defining Work Requirements, and the levels at which each can be set, is listed in the **[Work Requirement Property Dictionary](work-requirement-property-dictionary.md)**.

## Automatic `taskTypes` Population

A Task Group's `taskTypes` list says which Workers can pick up its Tasks. It can be left out: it is filled in from the `taskType` of the Task Group's Tasks.

This Task Group has no `taskTypes`, so its list becomes `["bash"]`:

```json
{
  "name": "greetings",
  "tasks": [
    {"name": "hello", "taskType": "bash", "arguments": ["-c", "echo hello"]},
    {"name": "world", "taskType": "bash", "arguments": ["-c", "echo world"]}
  ]
}
```

When a Task Group sets `taskTypes` and its Tasks set `taskType` too, the list is the **union** of the two. (The `docker` Task Type here is one a node has only once it is added: see [The `docker` Task Type](#the-docker-task-type).) Here it becomes `["bash", "docker"]`:

```json
{
  "name": "mixed-tasks",
  "taskTypes": ["bash"],
  "tasks": [
    {"name": "shell-task", "taskType": "bash", "arguments": ["-c", "echo hi"]},
    {"name": "container-task", "taskType": "docker", "arguments": ["alpine:3.20", "echo", "hi"]}
  ]
}
```

#### Details

**Order.** The resulting `taskTypes` keeps the declared types in their order, followed by the Tasks' own types in the order they first appear.

**When nothing gives a type.** If `taskTypes` is still empty after the union, the CLI falls back, in order, to the `[workRequirement]` `taskType` configuration property and to `taskTemplate.taskType`. If none of these gives a value and the Task Group contains Tasks, the submission fails with an error.

**A Task with no `taskType`.** It takes its Task Group's type, if the group has only one. If the group allows several, the Task takes the `[workRequirement]` `taskType` configuration property where the group allows that type, or otherwise the type of the group's `taskTemplate`. If neither applies, the submission fails with an error naming the Task, rather than sending a Task the Platform would refuse.

**Adding Tasks with `--add-to`.** When `yd workrequirement submit --add-to` adds Tasks to an **existing** Task Group, that group's `taskTypes` cannot be changed, because the Platform does not allow `taskTypes` to change after a Task Group is created. If the new Tasks bring a `taskType` the existing group does not allow, the CLI fails with an error before submitting anything. Either give the Tasks a different Task Group name, so that a new Task Group is created with the union of `taskTypes`, or change them to a `taskType` the group allows.

## Task Retries and Failure Policies

A Task Group's `runSpecification` can carry one **`retryPolicy`** and one **`failurePolicy`**. The retry policy runs a failed Task again, on the errors it selects. When the retries are used up, or the error is not one the retry policy selects, the failure policy can resubmit the Task to a different Task Group rather than letting it end as `FAILED`.

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

A Task can record more than one error for one failure, as a timeout does, so select on the one that caused it. The errors your own Tasks have recorded (below) show which that is.

`PROCESS_NON_ZERO_EXIT`, `TIMED_OUT` and the `UNKNOWN_ERROR` of a missing Task data input or output are described as observed on the Platform. The SDK describes `DATA_CLIENT_DISABLED`, and the others are described by what their names record.

### Finding the Errors Your Tasks Hit

A policy is best written from the errors your Tasks actually hit. A Task keeps every error it has recorded, retried or not, in its `errors` list. This command lists the Tasks that recorded one and shows each in full:

```shell
yd task list --within my-work-requirement --with-errors --auto-select-all
```

`--with-errors` lists the Tasks with errors whatever their status, a Task that completed on a retry included. `--auto-select-all` shows each in full, as `--details` does for the Tasks you choose from the list. `--json` instead gives them all as one array.

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

A retry policy says how many times a failed Task is retried, and on which errors. This one retries a Task up to three times when it lost its Worker or was stopped with exit code 143:

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

`retryErrors` is optional: without it, every Task error is retried. `maxRetries` must be `0` or more. It defaults to `0`, which defines the policy but retries nothing.

A Task can tell which attempt it is from the `YD_RETRY_NUMBER` environment variable, which the YellowDog Agent sets: `0` for its first run, `1` for its first retry, and so on. A Task can use it, for example, to resume from a checkpoint rather than start again.

### `failurePolicy`

When a Task's retries are used up, or its error is not one `retryPolicy.retryErrors` selects, a `failurePolicy` can resubmit the Task to another Task Group in the same Work Requirement. This one sends Tasks that lost their Worker to `on-demand-tg`, and Tasks that ran out of memory (exit code 137) to `high-memory-tg`:

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

Destinations are evaluated **in order**, and the first matching entry wins. An entry without `resubmitErrors` matches every error.

Each destination Task Group must set `"finishIfAllTasksFinished": false`, or the Platform refuses the Work Requirement. Such a Work Requirement does not end by itself: run `yd workrequirement finish` once the work is done.

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

#### Details

**Why the Work Requirement stays running.** The Platform refuses a destination Task Group that would finish once all its Tasks have finished, with the error `task group failure policy destinations ... will finish if all tasks finished`. A destination therefore stays `RUNNING` after its last Task has finished, and so does the Work Requirement. It ends only when it is finished or cancelled, and a `--follow` of it does not return until then.

**Ordering the destinations.** Since an entry without `resubmitErrors` matches every error, only the last entry should leave it out; any entries after it can never be reached. An empty `resubmissionDestinations` list is refused.

**The resubmitted Task.** A resubmitted Task becomes `RESUBMITTED`, a terminal status. A copy is added to the destination Task Group, with its `resubmittedFromTaskId` linking back to the original. The original Task carries `resubmittedToTaskId` pointing forward.

**Policies after resubmission.** A resubmitted Task counts as finished in its own Task Group, which completes as usual. The copy follows its destination Task Group's policies, not the original's, so it is retried only if that Task Group has a `retryPolicy` of its own.

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

`addEnvironment` adds environment variables to every Task's `environment`, without replacing it. A variable the `environment` already has keeps its value: `addEnvironment` only adds the variables the `environment` lacks.

### Example — TOML

```toml
[workRequirement]
    environment = {IMAGE_SIZE = "800", OUTPUT_FORMAT = "png"}
    addEnvironment = {IMAGE_SIZE = "1024", LOG_LEVEL = "info"}
    # Each Task's environment: {IMAGE_SIZE = "800", OUTPUT_FORMAT = "png", LOG_LEVEL = "info"}
```

### Example — JSON

```json
{
  "taskGroups": [
    {
      "environment": {"IMAGE_SIZE": "800", "OUTPUT_FORMAT": "png"},
      "addEnvironment": {"IMAGE_SIZE": "1024", "LOG_LEVEL": "info"},
      "tasks": [{}]
    }
  ]
}
```

#### Details

**Where it can be set.** `addEnvironment` can be set in the TOML `[workRequirement]` section, at the Work Requirement JSON level, or at the Task Group JSON level, but not on a Task.

**How the levels combine.** Unlike other properties, `addEnvironment` **accumulates** down the levels rather than being replaced: each level's table is added to those above it. A variable set at more than one level takes its value from the lowest. Setting `addEnvironment` to `null` at a level clears what came from above, as `null` stops inheritance elsewhere.

**With the Task's `environment`.** The Task's `environment` is inherited as usual, then `addEnvironment` is merged into it.

## Argument Prefix and Postfix

`argumentsPrefix` and `argumentsPostfix` put a fixed list of arguments before and after every Task's `arguments`. The shared part of a command is then set once, on the Work Requirement or a Task Group, and each Task gives only the part that varies. Each Task runs with:

```
argumentsPrefix + arguments + argumentsPostfix
```

### Example — TOML

```toml
[workRequirement]
    argumentsPrefix = ["resize.sh", "--width", "800"]
    arguments = ["holiday.jpg"]
    argumentsPostfix = ["--format", "png"]
    # Each Task's arguments: ["resize.sh", "--width", "800", "holiday.jpg", "--format", "png"]
```

### Example — JSON

Here `resize.sh --width 800` is set once on the Task Group, and each Task names only its photo:

```json
{
  "taskGroups": [
    {
      "argumentsPrefix": ["resize.sh", "--width", "800"],
      "tasks": [
        {"arguments": ["holiday.jpg"]},
        {"arguments": ["wedding.jpg"]},
        {"arguments": ["birthday.jpg"]}
      ]
    }
  ]
}
```

Each Task runs as `resize.sh --width 800 <photo>`.

#### Details

**Where they can be set.** `argumentsPrefix` and `argumentsPostfix` can be set at the same levels as `addEnvironment`: the TOML `[workRequirement]` section, the Work Requirement JSON level, or the Task Group JSON level, but not on a Task.

**How the levels combine.** Each is taken whole from the lowest level that sets it, as `arguments` is. They are not merged down the levels as `addEnvironment` is.

**Substitutions.** Variable substitutions are supported in all three lists.

## Task Templates

A Task Group's `taskTemplate` gives its Tasks default values for `taskType`, `taskData` and `environment`. The Platform applies the defaults, so Tasks that share them need not each repeat them.

### Example — TOML

```toml
[workRequirement]
    taskTemplate = {taskType = "bash", taskData = "quality=90", environment = {IMAGE_SIZE = "800"}}
```

### Example — JSON

```json
{
  "taskGroups": [
    {
      "taskTemplate": {
        "taskType": "bash",
        "taskData": "quality=90",
        "environment": {"IMAGE_SIZE": "800"}
      },
      "taskTypes": ["bash"],
      "tasks": [
        {"arguments": ["resize.sh", "holiday.jpg"]},
        {"arguments": ["resize.sh", "poster.jpg"], "environment": {"IMAGE_SIZE": "2400"}},
        {"arguments": ["resize.sh", "wedding.jpg"]}
      ]
    }
  ]
}
```

All three Tasks use the `bash` Task Type and the Task Data from the template. The second Task sets `IMAGE_SIZE` to `"2400"`; the others take `"800"` from the template.

#### Details

**Which fields.** Any combination of the three fields can be given. A field left out is not defaulted.

**Precedence.** A value set on a Task takes precedence over the template.

**Task Data files.** `taskDataFile` or `taskDataFiles` can be used inside `taskTemplate` in place of `taskData`, exactly as on a Task. The file contents are read by the CLI and used as the `taskData` value. `taskDataFiles` joins several files in order, with a newline after each. Every Task Data file is substituted as it is read, `{{variable}}` by `{{variable}}`, as a User Data file is.

**Where it can be set.** `taskTemplate` can be set in the TOML configuration (a default for every Task Group), at the Work Requirement level, or at the Task Group level. The more specific level takes precedence.

## Automatic Properties

`yd workrequirement submit` sets some properties itself when the specification leaves them out.

### Work Requirement, Task Group and Task Naming

- An unnamed **Work Requirement** is named from the `[common]` `tag`, a UTC timestamp and a process discriminator, e.g. `thumbnails_261027-1605404-tz` (see [Naming Rules](configuration.md#naming-rules)).
- An unnamed **Task Group** is named `task_group_1`, `task_group_2` and so on.
- An unnamed **Task** is named `task_1`, `task_2` and so on, counting from 1 again in each Task Group.

Your own names can include the numbers with the `{{task_group_number}}` and `{{task_number}}` [substitutions](#task-and-task-group-name-substitutions).

The Work Requirement's name uses the `[common]` `tag`, not the `[workRequirement]` section's. The numbers in the generated names are zero-padded to the width of the count, e.g. `task_01` in a Task Group of 10 to 99 Tasks, and `task_group_01` likewise.

Setting `setTaskNames` to `false` stops Tasks being named. The `task_name` variable is then `none`.

#### Obtaining Names/Context from Environment Variables at Task Run Time

Set `addYDEnvironment` to `true` to give each Task its names, numbers, namespace and tag in these environment variables:

- `YD_TASK_NAME`
- `YD_TASK_NUMBER`
- `YD_NUM_TASKS` (Number of Tasks in this Task Group)
- `YD_TASK_GROUP_NAME`
- `YD_TASK_GROUP_NUMBER`
- `YD_NUM_TASK_GROUPS` (Number of Task Groups in the Work Requirement)
- `YD_WORK_REQUIREMENT_NAME`
- `YD_NAMESPACE`
- `YD_TAG` (if set at the Task level)

This applies whether the names were set automatically by `yd workrequirement submit` or by you. The variables add about 250 to 300 bytes to every Task (see [Submitting Large Numbers of Tasks](#submitting-large-numbers-of-tasks)).

The YellowDog Agent also sets these, from the instance and the Task, for every Task it runs:

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

`taskCount` makes a Task Group of copies of a single Task, and `taskGroupCount` makes a Work Requirement of copies of a single Task Group. They are handy for testing and demos. On the command line, `--task-count` (`-C`) and `--task-group-count` (`-G`) set them, overriding the specification and the configuration file:

```bash
yd workrequirement submit --task-group-count 3 --task-count 10 --dry-run
```

`taskCount` applies to every Task Group, so this makes 3 Task Groups of 10 Tasks each, 30 Tasks in all.

#### Details

**One Task, one Task Group.** In a JSON specification, `taskCount` needs exactly one Task in its Task Group, and `taskGroupCount` exactly one Task Group in the Work Requirement. With more than one listed, the count is ignored with a warning.

**Naming the copies.** The copies of a Task Group must have different names. So a named Task Group expanded with `taskGroupCount` must include `{{task_group_number}}` in its name, or the submission is refused.

## All Properties

Each listing below sets every property that can be set at its level, for reference: none is meant to be submitted as it stands. The [Property Dictionary](work-requirement-property-dictionary.md) describes each property, and the [Examples](#examples) show typical use.

### Properties in the `workRequirement` Section

Every property the `workRequirement` section of a TOML configuration file can set. `taskData`, `taskDataFile` and `taskDataFiles` are alternatives, of which only one may be set at a given level, so the listing uses `taskData`; likewise `csvFile` and `csvFiles`, and `workerTag` and `workerTags`. The deprecated `maximumTaskRetries` and `retryableErrors` (see [above](#deprecated-maximumtaskretries--retryableerrors)) cannot be combined with `retryPolicy` and are left out.

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

### Properties at the Work Requirement Level

Every property a JSON specification can set at the Work Requirement level. `taskData`, `taskDataFile` and `taskDataFiles` are alternatives, of which only one may be set, so the listing uses `taskData`; the deprecated `maximumTaskRetries` and `retryableErrors` are replaced by `retryPolicy`.

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

### Properties at the Task Group Level

Every property a JSON specification can set at the Task Group level. `taskData`, `taskDataFile` and `taskDataFiles` are alternatives, of which only one may be set, so the listing uses `taskData`; the deprecated `maximumTaskRetries` and `retryableErrors` are replaced by `retryPolicy`.

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

### Properties at the Task Level

Every property a JSON specification can set at the Task level. `taskData`, `taskDataFile` and `taskDataFiles` are alternatives, of which only one may be set, so the listing uses `taskData`.

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

These substitutions give each Task Group and Task its own name, number and counts. They can be used in the value of any property, in TOML and JSON specifications, in the contexts the table shows:

| Directive               | Description                                       | Task | Task Group |
|:------------------------|:--------------------------------------------------|:-----|:-----------|
| `{{task_number}}`       | The current Task number, zero-padded              | Yes  |            |
| `{{task_name}}`         | The current Task name                             | Yes  |            |
| `{{task_group_name}}`   | The current Task Group name                       | Yes  | Yes        |
| `{{task_count}}`        | The number of Tasks in the current Task Group     | Yes  | Yes        |
| `{{task_group_number}}` | The current Task Group number, zero-padded        | Yes  | Yes        |
| `{{task_group_count}}`  | The number of Task Groups in the Work Requirement | Yes  | Yes        |

For example, this JSON Work Requirement:

```json
{
  "taskGroups": [
    {
      "name": "render_{{task_group_number}}_preview",
      "taskCount": 2,
      "tasks": [
        {
          "name": "frame_{{task_number}}-of-{{task_count}}",
          "arguments": ["render.sh", "--preview", "{{task_number}}"]
        }
      ]
    },
    {
      "name": "render_{{task_group_number}}_final",
      "taskCount": 2,
      "tasks": [
        {
          "name": "frame_{{task_number}}-of-{{task_count}}",
          "arguments": ["render.sh", "{{task_number}}"]
        }
      ]
    }
  ]
}
```

... creates Task Groups named `render_1_preview` and `render_2_final`, each containing Tasks named `frame_1-of-2` and `frame_2-of-2`.

The Task variables work wherever a property a Task takes is set. A property such as `arguments`, `environment`, `taskData`, `taskDataFile` or `taskDataInputs` set on a Task Group, on the Work Requirement or in the `[workRequirement]` section is inherited by each Task and substituted for each one. So `"arguments": ["--frame", "{{task_number}}"]` on a Task Group gives each Task its own number, and `"taskDataFile": "data-{{task_name}}.txt"` its own file.

#### Details

**Padding.** `{{task_number}}` and `{{task_group_number}}` are zero-padded to the width of the count they belong to. Task 7 is `7` in a Task Group of 9 Tasks, `07` in one of 50 and `007` in one of 100; Task Groups are padded likewise by the number of Task Groups. The automatically generated names (`task_007`, `task_group_02`) are padded the same way.

**Why the numbers are padded.** Padding makes anything named from the numbers sort in Task order: Task names in `yd task list` and the Portal, and output files such as `out-{{task_number}}.txt` in `yd data list`. Unpadded, `task_10` would sort before `task_2`.

**Arithmetic on padded numbers.** A padded number is still text with leading zeros, so take care where those mean something. In bash arithmetic, for example, `$((008))` fails because a leading zero means octal; `10#` reads a padded number in base 10 instead: `n={{task_number}}; echo $((10#$n + 1))`. The `YD_TASK_NUMBER` and `YD_TASK_GROUP_NUMBER` environment variables (see [Obtaining Names/Context from Environment Variables at Task Run Time](#obtaining-namescontext-from-environment-variables-at-task-run-time)) hold the same numbers unpadded.

## Task Group Statuses

`yd taskgroup list` and `yd workrequirement follow` show each Task Group's status, followed by `/STARVED` or `/WAITING` when either holds it up. For example, `yd workrequirement follow` prints:

```text
Work Requirement 'nightly-render' is RUNNING
--> [RUNNING] Task Group 'render': 20 Tasks
    16 READY, 4 EXECUTING
--> [PENDING/STARVED] Task Group 'encode': 1 Task
    1 READY
--> [PENDING/WAITING] Task Group 'publish': 1 Task
    1 PENDING
```

- **`/STARVED`**: the Task Group can't claim any Workers. The Platform reports this as the Task Group's `starved` flag.
- **`/WAITING`**: the Task Group is waiting for a Task Group named in its `dependencies` to complete. The Platform reports this as its `waitingOnDependency` flag.

A Task Group that is `PENDING` with neither is waiting for the Workers it needs, for example while a matching Worker Pool starts up. One submitted moments ago may show plain `PENDING` before it is flagged `/STARVED`. A `RUNNING` one has them. [Why Isn't My Work Running?](troubleshooting.md) works through what to do about a Task Group that stays starved.

#### Details

**Not statuses of their own.** `/STARVED` and `/WAITING` are the CLI's display of the two flags beside the status, not statuses: `--status` matches the status alone, so `yd list task-groups --status pending` lists starved and waiting Task Groups too, and `--status starved` matches nothing. `--json` gives the flags as `starved` and `waitingOnDependency`, and the status without them.

**The statuses.** A Task Group is `PENDING` until it has Workers, then `RUNNING`. It is `HELD` while its Work Requirement is held, and `FINISHING` once no more Tasks can be added and the rest are running to the end. It ends `COMPLETED`, or `FAILED` if a Task failed (passing through `FAILING` while its outstanding Tasks are discarded), or `CANCELLED` (through `CANCELLING`).

## Dry-Running Work Requirement Submissions

To see the Work Requirement that would be submitted, after all processing, add `--dry-run` (`-D`) to `yd workrequirement submit`. It prints the Work Requirement as JSON and submits nothing. `--quiet` (`-q`) prints the JSON alone. With this configuration:

```toml
[workRequirement]
    taskType = "bash"
    arguments = ["make-thumbnails.sh", "{{task_number}}"]
    taskCount = 2
    workerTag = "render"
```

```bash
yd workrequirement submit --dry-run --quiet
```

prints:

```json
{
  "namespace": "image-processing",
  "name": "thumbnails_261027-1608530-fd",
  "taskGroups": [
    {
      "name": "task_group_1",
      "runSpecification": {
        "taskTypes": ["bash"],
        "workerTags": ["render"]
      },
      "priority": 0,
      "starved": false,
      "waitingOnDependency": false,
      "finishIfAllTasksFinished": true,
      "finishIfAnyTaskFailed": false,
      "tasks": [
        {
          "name": "task_1",
          "taskType": "bash",
          "arguments": ["make-thumbnails.sh", "1"]
        },
        {
          "name": "task_2",
          "taskType": "bash",
          "arguments": ["make-thumbnails.sh", "2"]
        }
      ]
    }
  ],
  "tag": "thumbnails"
}
```

> **Note:** Without `--dry-run`, `--quiet` on `yd workrequirement submit` prints only the Work Requirement's YellowDog ID — see [yd workrequirement submit](commands.md#yd-workrequirement-submit) for scripting examples.

The JSON printed is a **consolidated form** of what would be sent to the YellowDog API: the Tasks are shown inside their Task Groups, for ease of reading. In the actual submission, the Work Requirement and its zero or more Task Groups are submitted first, and the Tasks are then added to their Task Groups in separate API calls. Task Groups and Tasks can also be added to the Work Requirement later (below).

### Adding Task Groups and Tasks to an Existing Work Requirement

To add Tasks to a Work Requirement that is already running, submit a specification with `--add-to` (`-A`), naming the Work Requirement by its name or YellowDog ID:

```bash
yd workrequirement submit --add-to my-work-requirement more-frames.json
```

Each Task Group in the specification is matched by name against the Task Groups the Work Requirement already has. Tasks for an existing Task Group are added to it, numbered on from its existing Tasks. A Task Group the Work Requirement doesn't have yet is added to it, with its Tasks. One submission can do both. For example, if `my-work-requirement` has a Task Group `render` holding 100 Tasks, this `more-frames.json` adds Tasks 101 and 102 to `render` and adds a new Task Group, `encode`, with one Task:

```json
{
  "taskGroups": [
    {
      "name": "render",
      "taskCount": 2,
      "tasks": [{"taskType": "bash", "arguments": ["render.sh", "{{task_number}}"]}]
    },
    {
      "name": "encode",
      "taskCount": 1,
      "tasks": [{"taskType": "bash", "arguments": ["encode.sh"]}]
    }
  ]
}
```

The Work Requirement must be `RUNNING` or `HELD`. Add `--dry-run` (`-D`) to see what would be added without adding it, and `--follow` (`-f`) to follow the Work Requirement once the Tasks are added.

To create a Work Requirement now and add its Tasks later, submit it with `--empty` (`-e`), which gives it no Task Groups or Tasks:

```bash
WR_ID=$(yd workrequirement submit --empty --quiet)
yd workrequirement submit --add-to "$WR_ID" my-spec.json
```

#### Details

**Choosing the Work Requirement.** A YellowDog ID is found in whatever namespace it belongs to. A name is looked up in the configured `namespace`, unless it is given as `namespace/name`. A name can be reused, so the `RUNNING` or `HELD` Work Requirement of that name is chosen; if there are two, give its YellowDog ID instead. A target that does not exist exits with code 6. A `FINISHING` Work Requirement takes no new Tasks, and the other states have finished or are being cancelled. `--add-to` cannot be combined with `--hold` or `--empty`, which apply only to a new Work Requirement.

**Adding to an existing Task Group.** The specification's own settings for the Task Group (`priority`, `workerTags`, `dependencies` and the rest) are not applied: the existing Task Group keeps its own. The properties its new Tasks inherit are taken from the specification, as the table below shows. `{{task_count}}` (in the Tasks' names and other properties alike, and `YD_NUM_TASKS`) is the Task Group's whole count, the existing Tasks and the new.

**Waiting for the Task count.** The Platform updates a Task Group's count of Tasks a few seconds after Tasks are added to it. So `--add-to` first looks in the Task Group for the name its first new Task would be given. If that name is already there, because Tasks were added moments before, it says so and waits for the count to catch up, up to 10 seconds at a time, before numbering the new Tasks. A name still there once the count has stood still for 10 seconds is one already in use, and the submission is refused. Tasks without names (`setTaskNames = false`) have no name to look for, so the existing Tasks are counted instead, which for a large Task Group takes a moment.

**Adding a new Task Group.** Its Tasks are numbered from 1. Its own number continues from the Work Requirement's existing Task Groups, the new ones numbered in the order given, and `{{task_group_count}}` is the Work Requirement's count once they are added, in the Task Group's own properties as in its Tasks'. Which Task Groups already exist is decided by their names, so a Task Group named by its own number (`tg_{{task_group_number}}`) that would come to name another Task Group once numbered is refused: give it a name of its own.

**What is taken from each part of the specification:**

| Part of the specification | For a new Task Group | For an existing Task Group (matched by name) |
|:---|:---|:---|
| The Work Requirement's own settings (its name and tag, and its `priority` as the Work Requirement's) | not applied: the target Work Requirement keeps its own | not applied |
| What the Work Requirement level passes down (`priority`, `workerTags`, `arguments`, `environment` and the other inherited properties) | inherited by the Task Group and its Tasks | the Task properties (`arguments`, `environment` and the like) inherited by the new Tasks; the Task Group's (`priority`, `workerTags` and the like) not applied |
| The Task Group's own settings (`priority`, the run specification: `taskTypes`, `workerTags`, `dependencies` and the rest) | applied, as the Task Group is created | not applied: the existing Task Group keeps its own |
| What the Task Group level passes down to its Tasks (`arguments`, `environment`, `taskType`, `timeout`, `taskData` and the rest) | inherited by its Tasks | inherited by the new Tasks |
| The Tasks | added, numbered from 1 | added, numbered on from the existing Tasks, each `taskType` in the Task Group's `taskTypes` (or the submission is refused) |

So a specification written to add Tasks to an existing Task Group can carry the Task-level defaults those Tasks need at its Task Group level, as a new submission would, while the Task Group's scheduling stays as it was submitted.

**Uploaded files.** If the specification contains `taskDataInputs` with `localPath` entries, those files are uploaded to the remote destination as usual. A file already at its upload path, from the original submission or otherwise, is skipped, whether or not the local file has changed since. Use `--overwrite` (`-O`) to upload every file again, replacing the remote copy:

```bash
yd workrequirement submit --add-to my-work-requirement --overwrite my-spec.json
```

**A failure part-way.** If adding Tasks fails part-way, the target Work Requirement is not cancelled, as a newly submitted one would be: any Tasks already added remain in it, and any files uploaded for them are left in place, since those Tasks may need them. A warning says so, and `yd workrequirement submit` exits with a non-zero status.

**Dry runs.** Unlike a normal dry run, which does not contact the Platform, a dry run with `--add-to` reads the target Work Requirement, since the names, numbering and Task counts of its existing Task Groups determine the names and offsets of everything that would be added. Credentials and connectivity are therefore required, and the checks that depend on the target are made as well: that it exists, that it is `RUNNING` or `HELD`, and that no Task's type falls outside an existing Task Group's `taskTypes` allowlist. Nothing is created, updated or uploaded. The specification printed shows the Work Requirement as it would be: the existing Task Groups as well as the new ones, with the Tasks that would be added attached to whichever Task Group takes them. A `DRY-RUN` line above it names the Task Groups that are already present, because the Platform reports only a summary of their Tasks, so those Task Groups appear in the specification without any Tasks of their own.

**Empty Work Requirements.** `--empty` uses the TOML configuration only: a specification or CSV file, given or configured, is refused with it. A JSON specification can also create an empty Work Requirement without `--empty`, since empty arrays are honoured as written, either with no Task Groups:

```json
{ "taskGroups": [] }
```

or with a Task Group that has no Tasks:

```json
{
  "taskGroups": [
    { "name": "my-task-group", "tasks": [] }
  ]
}
```

### Submitting 'Raw' JSON Work Requirement Specifications

The JSON a dry run prints is a complete Work Requirement specification in itself, which `--json-raw` (`-j`) submits as it is:

```bash
yd workrequirement submit --dry-run --quiet > thumbnails.json
yd workrequirement submit --json-raw thumbnails.json
```

The Work Requirement is submitted, then its Tasks are added. `--parallel-batches` (or the `parallelBatches` configuration property), `--follow` and `--progress` work as for any other submission.

#### Details

**Substitutions but no inheritance.** Variable substitutions can be used in the raw JSON file, as in any other Work Requirement JSON file. There is no property inheritance, though, neither from the `[workRequirement]` section of the TOML configuration nor from Work Requirement properties given on the command line.

**Failures.** A batch of Tasks that fails in a way a retry could cure is retried, as any other submission's are. If the Platform refuses a batch of Tasks, the Work Requirement is cancelled and `yd workrequirement submit` exits with a non-zero status naming the kind of failure.

## Submitting Large Numbers of Tasks

With tens of thousands of Tasks or more, how the Tasks are sent decides how long a submission takes, and what each Task carries decides how much is sent and stored.

**Sending the Tasks.** Tasks are added to their Task Groups in batches of `taskBatchSize` (1,000 by default, up to 10,000), one batch at a time unless `parallelBatches` (or `--parallel-batches`) sends several at once. A batch that fails in a way a retry could cure is resubmitted.

**Keeping each Task small.** Every byte on a Task is sent and stored once per Task, so:

- Put what the Tasks of a Task Group share — their `taskType`, `taskData` and `environment` — in a [`taskTemplate`](#task-templates), which the Platform applies, rather than on every Task.
- Leave `addYDEnvironment` off. Its variables ([Obtaining Names/Context from Environment Variables at Task Run Time](#obtaining-namescontext-from-environment-variables-at-task-run-time)) add about 250 to 300 bytes to every Task, more with long Work Requirement, Task Group or namespace names. Pass a Task what it needs in its arguments instead, with the [Task and Task Group name substitutions](#task-and-task-group-name-substitutions): `"arguments": ["--frame", "{{task_number}}"]` on the Task Group gives each Task its own number at the cost of a few bytes.
- Consider `setTaskNames: false`, which leaves Tasks without names, saving each Task its name. See below for what is lost.
- Keep `taskData` small: a large input is better fetched by each Task as it runs, with [`taskDataInputs`](#specifying-data-client-inputs), than carried in every Task.

**Tasks without names.** Two things are lost with `setTaskNames: false`. First, a Task can no longer be found by its name (`yd task show wr/tg/task`). Second, a batch whose response times out is not resubmitted, because the Platform might already have added it and nothing would tell a duplicate apart. The submission fails instead, saying to check the Work Requirement's Tasks.

## Using the YellowDog Data Client

A Task can download its input files from remote storage, such as an S3 bucket, before it runs, and upload its output files after it has run. The YellowDog Agent's Data Client does the transfers, which are given in each Task's `taskDataInputs` and `taskDataOutputs`. `yd workrequirement submit` can also upload local files to the remote storage as the Work Requirement is submitted, for the Tasks to download. [Sending Files to Tasks and Collecting Their Results](#sending-files-to-tasks-and-collecting-their-results) shows all three together.

The YellowDog Data Client is described at https://docs.yellowdog.ai/#/the-platform/the-data-client.

The examples below name the bucket `my-photos` through a remote called `s3`, which the node defines: [`add-rclone-s3.sh`](https://github.com/yellowdog/resources/blob/main/agent-install/linux/userdata/add-rclone-s3.sh), run as User Data after the Agent installer, adds it to the Agent's rclone configuration, using the instance's IAM role (see [The rclone S3 Remote](https://github.com/yellowdog/resources/blob/main/agent-install/linux/README.md#the-rclone-s3-remote); set `YD_S3_REGION` to the bucket's region). The remote exists on the node only. A file uploaded from your own machine needs credentials of its own (see [Automatic Upload of Local Files](#automatic-upload-of-local-files)).

Task data inputs and outputs are **individual files**, not directories or wildcards. If a Task needs many files, or files whose names are not known in advance, put them in a single archive, and have the Task unpack it as it starts or pack its results as it ends.

### Specifying Data Client Inputs

Each input names a remote `source` and a local `destination`. In the `[workRequirement]` section of the TOML file:

```toml
taskDataInputs = [
  {source = "rclone:s3:my-photos/originals/batch_{{task_number}}.zip", destination = "local:originals.zip"},
  {source = "rclone:s3:my-photos/watermarks/logo.png", destination = "local:logo.png"},
]
```

Or in JSON:

```json
"taskDataInputs": [
  {"source": "rclone:s3:my-photos/originals/batch_{{task_number}}.zip", "destination": "local:originals.zip"},
  {"source": "rclone:s3:my-photos/watermarks/logo.png", "destination": "local:logo.png"}
],
```

- The `source` property is an rclone path starting with `rclone:`.
- The `destination` property is a local pathname, in the Task's directory, prefixed with `local:`.

### Using Files Uploaded with `yd data`

A Task can download a file that `yd data upload` put in the data store. The `{{dataClient.remote}}`, `{{dataClient.bucket}}` and `{{dataClient.prefix}}` variables give the `[dataClient]` section's values, so the input names the same place the upload did:

```bash
yd data upload originals.zip
```

```toml
taskDataInputs = [
  {source = "rclone:{{dataClient.remote}}:{{dataClient.bucket}}/{{dataClient.prefix}}/originals.zip", destination = "local:originals.zip"},
]
```

Leave out the `rclone:` if the configured `remote` already starts with it. A named profile's values are `{{dataClient.<profile>.remote}}` and so on: see [Variable Substitutions for Data Client Properties](data-client.md#variable-substitutions-for-data-client-properties).

### Automatic Upload of Local Files

`yd workrequirement submit` uploads a local file for an input that names it in `localPath`. The Task's `source` names the node's remote, which your own machine does not have, so `uploadPath` names where to upload the file with credentials your machine does have: here, the AWS credentials in your environment (see [Rclone Authentication](#rclone-authentication)):

```toml
taskDataInputs = [
  {localPath = "make-thumbnails.sh", uploadPath = "rclone:S3,type=s3,provider=AWS,env_auth=true,region=eu-west-2,location_constraint=eu-west-2:my-photos/scripts/make-thumbnails.sh", source = "rclone:s3:my-photos/scripts/make-thumbnails.sh", destination = "local:make-thumbnails.sh"},
]
```

Without `uploadPath`, the file is uploaded to the `source` itself. That works when your machine can reach the `source` as written: a remote of the same name in your own `rclone.conf`, or an inline connection string such as the one in `uploadPath` above.

#### Details

**Finding the local file.** `localPath` can be an absolute or a relative pathname. A relative one is found from the files directory, as Task Data files and CSV files are: the `--content-path <directory>` (`-F`) option of `yd workrequirement submit`, else the specification file's directory, else the configuration file's.

**One file per upload path.** Two different local files given the same upload path are refused.

**Clean-up on failure.** If `yd workrequirement submit` fails while submitting a new Work Requirement, the Work Requirement is cancelled and the files it uploaded are deleted. With `--add-to`, the Tasks already added and the files uploaded for them are left in place, with a warning. A file that was already at its upload path is always left in place, whether it was skipped or replaced with `--overwrite`, because another Work Requirement may be using it.

### Rclone Authentication

Uploading a local file from your own machine with rclone needs credentials for the remote storage, which are set up outside the YellowDog CLI. (A node's credentials come from its own rclone configuration, as above.) For an S3 bucket, for example, AWS credentials such as `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` can be set as environment variables. An rclone path can then reach them in any of three ways:

1. Taking the credentials from the environment: `rclone:S3,type=s3,provider=AWS,env_auth=true,region=eu-west-2,location_constraint=eu-west-2:my-photos/originals/batch_01.zip`

2. Substituting the environment variables into the path: `rclone:S3,type=s3,provider=AWS,access_key_id={{env:AWS_ACCESS_KEY_ID}},secret_access_key={{env:AWS_SECRET_ACCESS_KEY}},region=eu-west-2,location_constraint=eu-west-2:my-photos/originals/batch_01.zip`. This puts the key ID and secret in plain text in the Task specification.

3. Using an rclone configuration file, e.g. referencing a `[mys3]` section in `rclone.conf`: `rclone:mys3:my-photos/originals/batch_01.zip`.

### Specifying Data Client Outputs

Each output names a local `source` and a remote `destination`. In the `[workRequirement]` section of the TOML file:

```toml
taskDataOutputs = [
  {source = "local:thumbnails.zip", destination = "rclone:s3:my-photos/thumbnails/batch_{{task_number}}.zip"},
  {source = "local:taskoutput.txt", destination = "rclone:s3:my-photos/logs/task_{{task_number}}.txt", alwaysUpload = true},
]
```

Or in JSON:

```json
"taskDataOutputs": [
  {"source": "local:thumbnails.zip", "destination": "rclone:s3:my-photos/thumbnails/batch_{{task_number}}.zip"},
  {"source": "local:taskoutput.txt", "destination": "rclone:s3:my-photos/logs/task_{{task_number}}.txt", "alwaysUpload": true}
],
```

- The `source` property is a local pathname, in the Task's directory, prefixed with `local:`.
- The `destination` property is an rclone path starting with `rclone:`.

### The `rclone` Binary

`yd workrequirement submit` uploads local files with an `rclone` binary on your own machine: one on your `PATH`, or else one it downloads the first time it is needed. It is the binary the `yd data` commands use, described under [Configuration](data-client.md#configuration) in the Data Client page's Details. `yd workrequirement submit --which-rclone` reports the binary in use, and `--upgrade-rclone` upgrades the downloaded copy.

## Task Execution Context

This section describes how a Worker on a node runs a Task: the steps it takes, the user the Task runs as, and the directories it uses. It describes the YellowDog Agent on a Linux node, with the default username, directories and so on; configurations can vary. [Windows Nodes](#windows-nodes) gives the differences on Windows.

### Task Execution Steps

When a Task is allocated to a Worker on a node by the YellowDog Scheduler, the following steps are followed:

1. The Agent running on the node gets the Task's properties: its `taskType`, `arguments`, `environment`, `taskData`. `YD_` environment variables are also set, by the Agent and optionally by `yd workrequirement submit` (see [Obtaining Names/Context from Environment Variables at Task Run Time](#obtaining-namescontext-from-environment-variables-at-task-run-time)).
2. An ephemeral working directory is created. Data Client input objects are downloaded to this directory, and the contents of the `taskData` property (if set) are written to the file `taskdata.txt`.
3. The Agent runs the command specified for the `taskType` in the Agent's `application.yaml` configuration file. This is done as a simple `exec` of a subprocess to run the Task.
4. When the Task concludes, the Agent uses the exit code of the subprocess to report success (zero) or failure (non-zero).
5. The Agent uploads any Data Client outputs specified in `taskDataOutputs` to their destinations. The ephemeral Task directory is then deleted.

Once the steps above have been completed, the Worker is ready to process its next Task. If the Agent on a node advertises several Workers, Tasks run in parallel on the node and start and stop independently.

**Aborting a Task.** If a Task is aborted while it runs, its subprocess is sent a `SIGTERM` (on Linux). This gives the Task a chance to stop any child processes or other resources, such as containers, that it started. Alternatively, a Task Type in the Agent's `application.yaml` file can set an `abort` clause. The script the `abort` clause names then takes over all abort handling.

### Where Task Types Come From

A Task's `taskType` names one of the Task Types the Agent on the node defines in its `application.yaml`, each with the command that runs a Task of that type. A Task Group's Tasks go only to Workers whose Agent has every Task Type in its `taskTypes`.

The [Agent installer](https://github.com/yellowdog/resources/blob/main/agent-install/linux/README.md) defines one Task Type, `bash`, which runs `/bin/bash` with the Task's arguments: `"arguments": ["-c", "echo hello"]` runs a command, and `"arguments": ["process.sh", "{{task_number}}"]` runs a script the Task downloaded. Any other Task Type is one you define, by editing the installer's settings (see [YellowDog Task Types](https://github.com/yellowdog/resources/blob/main/agent-install/linux/README.md#yellowdog-task-types)) or with [`add-task-type.sh`](https://github.com/yellowdog/resources/blob/main/agent-install/linux/userdata/add-task-type.sh) in the instances' User Data.

### The `docker` Task Type

A node has a `docker` Task Type once [`install-docker.sh`](https://github.com/yellowdog/resources/blob/main/agent-install/linux/userdata/install-docker.sh) and [`add-docker-task-type.sh`](https://github.com/yellowdog/resources/blob/main/agent-install/linux/userdata/add-docker-task-type.sh) have run on it, as User Data after the Agent installer (see [The docker Task Type](https://github.com/yellowdog/resources/blob/main/agent-install/linux/README.md#the-docker-task-type)). A `docker` Task runs `docker run` with the Task's arguments, so they are any `docker run` options, then the image and, optionally, the command to run in the container:

```json
{"taskType": "docker", "arguments": ["-e", "BATCH_SIZE", "my-org/thumbnailer:2.1", "--input", "/yd_working/originals.zip"], "environment": {"BATCH_SIZE": "50"}}
```

The Task's working directory, where its inputs are downloaded and from where its outputs are uploaded, is mounted in the container at `/yd_working`.

#### Details

**The Task's environment.** The container does not see the Task's environment variables unless the arguments pass them in, as `-e BATCH_SIZE` does above. The variables that control the container itself (`DOCKER_USERNAME`, `DOCKER_PASSWORD`, `DOCKER_REGISTRY`, `DOCKER_IMAGE`, `YD_STOP_SIGNAL`, `YD_STOP_TIMEOUT` and `YD_WORKING`) are read from the Task's environment; the [`docker` Task Type's README](https://github.com/yellowdog/resources/blob/main/agent-install/linux/README.md#the-docker-task-type) describes each.

**Registry credentials.** A `DOCKER_PASSWORD` in the Task's environment is visible to anyone who can read the Task's specification. A Docker credential helper on the image, or the instance's role where the registry accepts one, keeps the password out of the specification.

### The User and Group used for Tasks

By default, in the standard YellowDog Agent VM images and in images/instances created using the [YellowDog Agent Installer Script](https://github.com/yellowdog/resources/blob/main/agent-install/linux/README.md), the Agent runs as user and group `yd-agent`, and hence Tasks also execute under this user.

`yd-agent` does not have `sudo` privileges as standard. They can be added where needed, for example at instance boot time through the `userData` property of a provisioning request:

```shell
echo "yd-agent ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/020-yd-agent
chmod 440 /etc/sudoers.d/020-yd-agent
```

### Home Directory for `yd-agent`

By default, the home directory of the `yd-agent` user is `/opt/yellowdog/agent`. This directory typically contains the `application.yaml` file used to configure the Agent, as well as any scripts that are used to execute the Task Types that the node supports.

To SSH to an instance as user `yd-agent`, for debugging say, add your public key through the instance's `userData`:

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

Each Task runs in a working directory of its own, created when the Task starts and deleted when it ends. The directories are created under `/var/opt/yellowdog/agent/data/workers` (on Windows, see [Windows Nodes](#windows-nodes)), named from the Task's YellowDog ID with its colons replaced by underscores, e.g.:

`/var/opt/yellowdog/agent/data/workers/ydid_task_559EBE_74949336-ac2b-4811-a7d5-f3ecd9739908_1_1`

Downloaded files are placed in this directory, and output files are created in it by default. The Task's console output, `stderr` and `stdout` combined, is written to `taskoutput.txt` in it too.

The Task directory, `taskoutput.txt` included, is **ephemeral**: it is deleted once the Task completes and its outputs have been uploaded. To keep the console output, add `taskoutput.txt` as a `taskDataOutputs` entry (see [Specifying Data Client Outputs](#specifying-data-client-outputs)).

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

A CSV file can make one Task per row from a single prototype Task. The prototype's properties hold `<<column>>` substitutions, named by the CSV file's headings, and each row of the file fills them in for one Task.

CSV substitutions use `<<` and `>>` as delimiters, distinct from the `{{` and `}}` of general variable substitutions, so the two (e.g. `<<photo>>` and `{{namespace}}`) can be used together in the same prototype.

### Work Requirement CSV Data Example

This `wr.json` has a prototype Task that resizes one photo:

```json
{
  "taskGroups": [
    {
      "tasks": [
        {
          "arguments": ["resize.sh", "<<photo>>", "<<width>>"],
          "environment": {"OUTPUT_FORMAT": "<<format>>"}
        }
      ]
    }
  ]
}
```

This `photos.csv` gives three photos, one per row:

```text
photo,       width, format
holiday.jpg, 800,   png
wedding.jpg, 1200,  jpg
poster.jpg,  2400,  png
```

Submitting them together with `--csv-file` (`-V`):

```bash
yd workrequirement submit wr.json -V photos.csv
```

expands the prototype into three Tasks before the rest of the processing:

```json
{
  "taskGroups": [
    {
      "tasks": [
        {
          "arguments": ["resize.sh", "holiday.jpg", "800"],
          "environment": {"OUTPUT_FORMAT": "png"}
        },
        {
          "arguments": ["resize.sh", "wedding.jpg", "1200"],
          "environment": {"OUTPUT_FORMAT": "jpg"}
        },
        {
          "arguments": ["resize.sh", "poster.jpg", "2400"],
          "environment": {"OUTPUT_FORMAT": "png"}
        }
      ]
    }
  ]
}
```

#### Details

**One prototype.** The Task Group must contain a single Task, the prototype. A prototype holding no `<<variable>>` that names a heading of its CSV file is not expanded, with a warning.

**Spaces.** Spaces after each comma are optional and ignored. Spaces at the end of a value are not ignored, and form part of it.

**Where the file is found.** A CSV file named with `-V` is looked for in the specification's directory, not the current one, as the specification's other files are. So `yd workrequirement submit work/wr.json -V photos.csv` reads `work/photos.csv`. `--content-path` names another directory to look in, and an absolute path is used as it is. `--debug` shows the path each CSV file was read from.

### CSV Variable Substitutions

A `<<...>>` substitution takes its value from the CSV file alone. Variables supplied on the command line, in the TOML configuration file or from environment variables do not override the file's values. Every substitution that is not a `<<...>>` one is left unchanged, for `yd workrequirement submit` to make afterwards.

A value is substituted as a string. For a number, a Boolean, an array or a table, use the `<<num:...>>`, `<<bool:...>>`, `<<array:...>>` and `<<table:...>>` forms, and `<<format_name:...>>` for a name. With the `photos.csv` above, `"timeout": "<<num:width>>"` gives each Task a numeric `timeout` (`800`, `1200`, `2400`).

#### Details

**Typed values.** A typed value is converted exactly as in a `{{...}}` [substitution](variables.md#variable-substitutions), so the same spellings are accepted. A substitution that is a whole string takes the nominated type rather than being a string. One inside a longer string is checked as its type and written as text. A value that is not of its type is an error naming the CSV file, the line in it and the column, e.g. `'tasks.csv' line 7, column 'count': 'abc' is not a number`.

**Values are substituted as they are.** A CSV value is substituted whatever it contains: an apostrophe, a quotation mark, a backslash in a Windows path, or text that looks like a CSV substitution.

**`{{...}}` in a value.** A `{{...}}` [variable substitution](variables.md#variable-substitutions) in a CSV value is made afterwards like any other. So a cell can refer to a variable (e.g. `{{namespace}}`), and `{{::}}` in a cell removes its property.

**Property names.** Substitutions are also made in property names, e.g. `"environment": {"<<var_name>>": "<<var_value>>"}`.

**Reading the file.** The CSV file is read as UTF-8, and a byte order mark (which Excel's *CSV UTF-8* format writes) is ignored. Blank lines are skipped.

**Headings and rows.** Every column needs a heading of its own, so an empty or repeated heading is an error. A file with headings but no data rows is an error too, since it would make a Task Group with no Tasks.

### Property Inheritance

All the usual property inheritance features operate as normal. Properties are inherited from the `config.toml` file, and from the relevant sections of the JSON Work Requirement file. Any properties set within a Task prototype are copied to all the generated Tasks.

### Multiple Task Groups using Multiple CSV Files

For several Task Groups, give one CSV file per Task Group, each Task Group holding a single prototype Task. The CSV files are applied to the Task Groups in the order given. For example, if `wr.json` contains two Task Groups:

```json
{
  "taskGroups": [
    {
      "name": "resize",
      "tasks": [
        {
          "arguments": ["resize.sh", "<<photo>>", "<<width>>"],
          "environment": {"OUTPUT_FORMAT": "<<format>>"}
        }
      ]
    },
    {
      "name": "watermark",
      "tasks": [
        {
          "arguments": ["watermark.sh", "<<photo>>"],
          "environment": {"LOGO": "<<logo>>", "POSITION": "<<position>>"}
        }
      ]
    }
  ]
}
```

then each gets its own CSV file:

```shell
yd workrequirement submit wr.json -V photos.csv -V watermarks.csv
```

To apply CSV files to particular Task Groups, add an **index postfix** (e.g. `:2`) to each filename. For example, to apply two CSV files to the second and fourth Task Groups:

```shell
yd workrequirement submit wr.json -V photos.csv:2 -V watermarks.csv:4
```

The postfix can also be a Task Group's **name**, where the JSON file names it:

```shell
yd workrequirement submit wr.json -V photos.csv:resize -V watermarks.csv:watermark
```

#### Details

**Fewer or more CSV files than Task Groups.** With fewer CSV files than Task Groups, a note is printed, and the 'n' CSV files are applied to the first 'n' Task Groups, in the order given. With more CSV files than Task Groups, an error is raised and processing stops.

**One CSV file per Task Group.** Only one CSV file can be applied to any Task Group, however it is chosen (by position, number or name): two for the same Task Group are an error naming both. A single CSV file can, however, be reused for several Task Groups.

### Using CSV Data with Simple, TOML-Only Work Requirement Specifications

A CSV file can also expand a Work Requirement given in the TOML file alone, with no JSON specification. Put the `<<...>>` substitutions in the `[workRequirement]` properties and name the CSV file in `csvFiles`:

```toml
[workRequirement]
    taskType = "bash"
    arguments = ["resize.sh", "<<photo>>", "<<width>>"]
    environment = {OUTPUT_FORMAT = "<<format>>"}
    workerTag = "render"
    csvFiles = ["photos.csv"]
```

`yd workrequirement submit` then makes one Task for each data row of the CSV file.

#### Details

**No JSON specification.** This form applies only when no JSON Work Requirement is given: no `workRequirementData` in the TOML file, and no specification on the command line.

**One CSV file.** The CSV file can be given with `-V photos.csv` on the command line in place of `csvFiles`. Naming more than one is an error, since there is only one Task Group to apply them to.

**Where substitutions are made.** In this form the CSV substitutions are made only in the properties a Task takes: `addYDEnvironment`, `arguments`, `environment`, `setTaskNames`, `taskData`, `taskDataFile`, `taskDataFiles`, `taskDataInputs`, `taskDataOutputs`, `taskGroupName`, `taskName`, `taskTimeout`, `taskType` and `timeout`. A `<<variable>>` anywhere else in the `[workRequirement]` section, such as `argumentsPrefix`, `addEnvironment` or `taskTemplate`, is left as written.

### Inspecting the Results of CSV Variable Substitution

To see the Work Requirement after the CSV substitutions alone, before any other substitution or property inheritance, add `--process-csv-only` (`-p`):

```bash
yd workrequirement submit wr.json -V photos.csv --process-csv-only
```
