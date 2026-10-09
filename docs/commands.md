# Command List

<!--ts-->
   * [Universal Options](#universal-options)
   * [Shared Options](#shared-options)
   * [Work Requirement Commands](#work-requirement-commands)
      * [yd-submit](#yd-submit)
      * [yd-cancel](#yd-cancel)
      * [yd-abort](#yd-abort)
      * [yd-start](#yd-start)
      * [yd-hold](#yd-hold)
      * [yd-finish](#yd-finish)
      * [yd-priority](#yd-priority)
   * [Worker Pool and Compute Commands](#worker-pool-and-compute-commands)
      * [yd-provision](#yd-provision)
      * [yd-shutdown](#yd-shutdown)
      * [yd-token](#yd-token)
      * [yd-resize](#yd-resize)
      * [yd-nodeaction](#yd-nodeaction)
      * [yd-instantiate](#yd-instantiate)
         * [Test-Running a Dynamic Template](#test-running-a-dynamic-template)
      * [yd-terminate](#yd-terminate)
      * [yd-compute-stop](#yd-compute-stop)
      * [yd-compute-start](#yd-compute-start)
      * [yd-compute-restart](#yd-compute-restart)
      * [yd-compute-deprovision](#yd-compute-deprovision)
      * [yd-compute-reprovision](#yd-compute-reprovision)
   * [Monitoring and Inspection Commands](#monitoring-and-inspection-commands)
      * [yd-list](#yd-list)
      * [yd-show](#yd-show)
      * [yd-follow](#yd-follow)
      * [yd-wait](#yd-wait)
      * [yd-compare](#yd-compare)
      * [yd-application](#yd-application)
      * [yd-variables](#yd-variables)
      * [yd-cloud-info](#yd-cloud-info)
   * [Resource Commands](#resource-commands)
      * [yd-create](#yd-create)
      * [yd-remove](#yd-remove)
      * [yd-boost](#yd-boost)
   * [Data Client Commands](#data-client-commands)
      * [yd-upload](#yd-upload)
      * [yd-download](#yd-download)
      * [yd-delete](#yd-delete)
      * [yd-ls](#yd-ls)
      * [yd-copy](#yd-copy)
   * [Utility Commands](#utility-commands)
      * [yd-doctor](#yd-doctor)
      * [yd-help](#yd-help)
      * [yd-version](#yd-version)
      * [yd-format-json](#yd-format-json)
      * [yd-jsonnet2json](#yd-jsonnet2json)
      * [yd-schema](#yd-schema)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Fri Oct  9 14:40:48 BST 2026 -->

<!--te-->


Help is available for all commands by invoking a command with the `--help` or `-h` option. The two tables below describe the options shared across commands; the sections that follow describe each command individually, along with its own command-specific options.

## Universal Options

These options are accepted by every `yd-*` command except `yd-commander`, `yd-mcp`, `yd-help`, `yd-version`, `yd-format-json`, `yd-jsonnet2json` and `yd-schema`, none of which requires a configuration file or YellowDog credentials; of those, `yd-help`, `yd-schema`, `yd-version` and `yd-jsonnet2json` accept `--no-format`. They are not repeated in the individual command sections below.

The five [Data Client Commands](#data-client-commands) are a partial exception: they accept all of these except `--key`, `--secret`, `--url` and `--pac`, because they talk only to the remote data store and never to the YellowDog Platform API.

| Option | Effect |
|---|---|
| `--config <config_file.toml>`, `-c` | Configuration file in TOML format; the default is `config.toml` in the current directory |
| `--no-config`, `--nc` | Ignore the contents of any TOML configuration file, even one named using `--config` |
| `--key <app-key-id>`, `-k` | The Application key ID |
| `--secret <app-key-secret>`, `-s` | The Application key secret |
| `--url <url>`, `-u` | The YellowDog Platform API URL (defaults to `https://api.yellowdog.ai`) |
| `--property <section.key=value>` | Override a single TOML configuration property; can be supplied multiple times — see [Overriding Arbitrary TOML Properties on the Command Line](configuration.md#overriding-arbitrary-toml-properties-on-the-command-line) |
| `--env-override` | Values in a `.env` file override values in the environment — see [Support for .env Files](configuration.md#support-for-env-files) |
| `--quiet`, `-q` | Suppress (non-error, non-interactive) status and progress messages |
| `--no-format`, `--nf` | Disable colouring and text wrapping in command output |
| `--print-pid`, `--pp` | Include the process ID of the CLI invocation alongside the timestamp in log messages; useful for disambiguating interleaved output when running multiple commands in parallel |
| `--debug` | Display the Python stack trace on error, which can be useful for support purposes. Also shows the startup preamble, each line marked `DEBUG`: where the configuration, the variable substitutions and the `.env` variables were loaded from, the Platform API URL when it is not the default, the HTTPS proxy in use, and the certificates bundle when one is set. The whole preamble is suppressed by default |
| `--pac` | Enable PAC (proxy auto-configuration) support — see [HTTPS Proxy Support](configuration.md#https-proxy-support) |
| `--docs` | Provide a link to the documentation for this version of the CLI |

Note that `yd-version` also accepts `--debug`, but reports the Python path and executable details rather than a stack trace.

A table longer than 2,000 lines, or JSON longer than 5,000 lines, is printed without colour, whether or not `--no-format` is used, since colouring output that long takes a noticeable time.

For `yd-submit`, `yd-provision`, and `yd-instantiate`, `--quiet` prints **only the YDID** of the created entity to stdout, making those commands directly composable in shell scripts:

```bash
WR_ID=$(yd-submit --quiet)
yd-follow "$WR_ID"
```

## Shared Options

These options are accepted by many commands, but not by all. The command sections below mention them only where a command does something particular with one; use `--help` to confirm exactly what any given command accepts.

| Option | Effect |
|---|---|
| `--variable <var1=v1>`, `-v` | Set a user-defined variable substitution; can be supplied multiple times, one per variable — see [User-Defined Variables](variables.md#user-defined-variables) |
| `--namespace [<namespace>]`, `-n` | The namespace to use when naming or selecting entities; this is set to `''` if the option is supplied without a value. Since its value is optional, `-n wr.json` would take a file name as the namespace: a namespace (or tag) ending `.json`, `.jsonnet`, `.toml`, `.yaml`, `.yml` or `.csv` is refused, so give the option after the file |
| `--tag [<tag>]`, `-t` | The tag to use when naming, tagging, or selecting entities; this is set to `''` if the option is supplied without a value |
| `--yes`, `-y` | Perform modifying or destructive actions without requiring user confirmation |
| `--dry-run`, `-D` | Report what the command would do, without acting |
| `--interactive`, `-i` | List, and interactively select, the items to act on; e.g. to select which object paths to delete |
| `--follow`, `-f` | Follow the relevant event stream after the command has acted: until the entity finishes, or, after an action that leaves it alive, until it has done what was asked of it — `yd-hold` until the Work Requirement is `HELD`; `yd-compute-stop` until nothing is changing, having stopped; `yd-compute-start`, `yd-compute-deprovision`, `yd-compute-reprovision` and `yd-resize -C` until the Compute Requirement is `RUNNING` at its target with no Instance starting, stopping or terminating; `yd-compute-restart` and `yd-resize` of a Provisioned Worker Pool until it is so again, having left it. A Configured Worker Pool resized is followed until Ctrl-C |
| `--sort <name\|created\|status\|namespace>[,...]` | Order in which listed and interactively-selected entities are sorted: `name` (default), `created` (creation time, earliest first), `status` (status name), or `namespace`. Give several keys, separated by commas, to sort by each in turn, e.g. `--sort status,created`; the name always breaks any tie that remains |
| `--reverse` | Reverse (descending) the whole order `--sort` gives |
| `--jsonnet-dry-run`, `-J` | Dry-run Jsonnet processing into JSON — see [Checking Jsonnet Processing](jsonnet.md#checking-jsonnet-processing) |

All destructive commands require user confirmation before taking effect, unless the `--yes` option is supplied.

The data client commands share a further set of options (`--remote`, `--bucket`, `--prefix`, `--no-prefix` and `--data-client-profile`), which are described under [Data Client](data-client.md).

## Work Requirement Commands

### yd-submit

The `yd-submit` command submits a new Work Requirement, according to the Work Requirement definition found in the `workRequirement` section of the TOML configuration file and/or the specification found in a Work Requirement JSON (or Jsonnet) document.

```shell
yd-submit [options] [<work-requirement-specification-file>]
```

Once submitted, the Work Requirement will appear in the **Work** tab in the YellowDog Portal.

Key options:
- `--follow`/`-f` — report on Tasks as they conclude, and don't return until the Work Requirement has finished
- `--progress` — as `--follow`, but showing a single updating progress bar of completed and failed Tasks against the total, rather than per-task event messages
- `--exit-on-failure`/`-E` — when following, exit with a non-zero code if the Work Requirement ends in a `FAILED` or `CANCELLED` state, or, if it could not be followed to its end (its event stream lost, say) and has not finished, with the code of that failure, since its outcome is not known; needs `--follow` or `--progress`
- `--hold`/`-H` — submit the Work Requirement in the `HELD` (paused) state; it can later be started with `yd-start`. It is held before any Task is added, and if holding it fails it is cancelled, as for any failure part-way through a submission
- `--empty`/`-e` — submit a Work Requirement with no Task Groups, to be populated later
- `--add-to`/`-A <name-or-id>` — add Task Groups and/or Tasks to an existing Work Requirement
- `--task-type`/`-T <type>` — the Task Type to use
- `--task-count`/`-C <n>`, `--task-group-count`/`-G <n>` — submit `n` copies of a single Task or Task Group
- `--csv-file`/`-V <data.csv>` — read Task data from one or more CSV files; `--process-csv-only`/`-p` outputs the intermediate JSON specification without submitting
- `--task-batch-size`/`-b <n>` — the batch size for Task submission, between 1 and 10,000
- `--parallel-batches`/`-l <n>` — the maximum number of Task batches uploaded in parallel (default `1`, i.e. sequential); once a batch fails, those not yet started are not submitted
- `--pause-between-batches`/`-P [<seconds>]` — pause between batch submissions; with no interval, user input is required to advance. Only valid when `--parallel-batches` is `1`
- `--overwrite`/`-O` — overwrite a file that already exists at the remote destination; by default, existing files are skipped
- `--json-raw`/`-j <file>` — submit a 'raw' JSON Work Requirement file; it cannot be combined with a specification file, `--add-to`, `--csv-file`, `--process-csv-only`, `--task-count`, `--task-group-count`, `--empty` or `--validate`, none of which applies to it
- `--content-path`/`-F <directory>` — the directory in which files for upload, user data, or CSV data are found; a relative path in the specification (a `taskDataFile`, a CSV file) is found there, while the specification file itself is always named from the current directory
- `--dry-run`/`-D` — inspect the Work Requirement, Task Groups and Tasks that would be submitted, in JSON format
- `--validate` — check the specification file against its schema and stop, reporting every violation, rather than submitting it (see [Specification Schemas](../README.md#specification-schemas))
- `--json` — emit the created Work Requirement as a JSON object; with `--dry-run`, the processed specification; refused with `--progress`, which writes its own output (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-submit my_work_requirement.json --follow
```

When `--quiet` (`-q`) is used, only the YDID of the submitted Work Requirement is printed to stdout, with all other output suppressed. This is convenient for scripting:

```bash
WR_ID=$(yd-submit --quiet)
yd-follow "$WR_ID"
```

To force a download or upgrade of the rclone binary used by the Data Client, run `yd-submit --upgrade-rclone`. To report the path and version of the binary that would be used, without downloading anything, run `yd-submit --which-rclone`. Both options are also accepted by the Data Client commands themselves.

The specification file may also be supplied using the deprecated `--work-requirement`/`-r` option; the positional argument is preferred.

See [Work Requirements](work-requirements.md) for the full specification reference, [Specifying Work Requirements using CSV Data](work-requirements.md#specifying-work-requirements-using-csv-data) for the CSV options, and [Adding Task Groups and Tasks to an Existing Work Requirement](work-requirements.md#adding-task-groups-and-tasks-to-an-existing-work-requirement) for `--add-to`.

### yd-cancel

The `yd-cancel` command cancels any active Work Requirements, including any pending Task Groups and the Tasks they contain.

```shell
yd-cancel [options] [<work-requirement-name-or-ID> ...]
```

The `namespace` and `tag` values in the `config.toml` file are used to identify which Work Requirements to cancel. Alternatively, specific Work Requirement names or YDIDs (or individual Task YDIDs) can be supplied as positional arguments.

A YDID names its Work Requirement or Task in whatever namespace it is in. A name is looked up in the configured `namespace` unless it is given as `namespace/name`; since a name can be reused, the Work Requirement of that name that can still be cancelled is chosen, and if there are two or more, the name is ambiguous and its YDID must be given instead.

Explicit names and IDs are handled in the order given, and are confirmed together; one that has already finished, or a Task that has, is skipped with a warning. If a request fails because the Application's credentials are not accepted, or the platform cannot be reached, nothing further is attempted, the remaining items are reported as skipped, and the command exits with that failure's code (see [Machine-readable Output and Exit Codes](json-output.md)).

A name argument can also be a glob pattern (`*`, `?`, `[...]`), matched client-side against Work Requirement names within the namespace (a name without wildcards matches exactly, so use `*` for partial matches); glob patterns cannot be mixed with literal names or YDIDs in the same command. Use `yd-list work-requirements --name 'myproject-*'` to preview the matches first.

By default, any Tasks that are currently running on Workers will continue to run to completion or until they fail. A Work Requirement that is already `CANCELLING` is left alone unless `--abort` is given, in which case it is cancelled again to abort its executing Tasks.

Key options:
- `--abort`/`-a` — instruct running Tasks to abort immediately, rather than running to completion
- `--dry-run`/`-D` — show the Work Requirements (and Tasks) that would be cancelled, whether matched or named, without cancelling anything
- `--json` — emit the actions taken, or with `--dry-run` what would be taken, as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-cancel 'myproject-*' --dry-run
```

### yd-abort

The `yd-abort` command aborts Tasks that are currently running, without cancelling the Work Requirements that contain them.

```shell
yd-abort [options] [<target> ...]
```

With no arguments, the user interactively selects the Work Requirements to target, and then which Tasks within those Work Requirements to abort.

Aborting a Task sends `SIGTERM` to the Task's subprocess, giving it an opportunity to clean up. The Task is then reported as `FAILED`. If the Task Type has an `abort` clause configured in the Agent's `application.yaml`, that script takes over abort handling entirely.

The `namespace` and `tag` values in the `config.toml` file are used to identify which Work Requirements to list for selection. Alternatively, targets can be supplied as positional arguments, each of which can be:

- a Task YDID, to abort that Task, whatever its state
- a Work Requirement name, `<namespace>/<wr-name>` or YDID, to abort all running Tasks within it (a YDID is found in whatever namespace it belongs to)
- a Task Group YDID, `<wr-name>/<tg-name>` or `<namespace>/<wr-name>/<tg-name>`, to abort running Tasks in a specific Task Group

A running Task is one that is `DOWNLOADING`, `EXECUTING` or `UPLOADING`; a Task that has yet to start, or has finished, is left alone.

`<a>/<b>` is read as a Task Group `<b>` in Work Requirement `<a>` if there is one, and otherwise as Work Requirement `<b>` in namespace `<a>`. A Work Requirement name is looked up as for `yd-cancel`: since a name can be reused, an unfinished Work Requirement of that name is chosen, and if there are two or more, the name is ambiguous and its YDID must be given instead (for `<a>/<b>`, the namespace reading is still tried).

Targets are handled in the order given, except that the Task YDIDs are confirmed together, where the first of them appears. A repeated target is ignored, and a Task included by more than one target is aborted once. If an attempt fails because the credentials are rejected or the platform cannot be reached, nothing further is attempted, the remaining Tasks and targets are reported as skipped, and the command exits with that failure's code (see [Machine-readable Output and Exit Codes](json-output.md)).

Unless `--yes`/`-y` is given, the Tasks to be aborted are listed and confirmed before anything is aborted. With `--yes`/`-y`, all executing Tasks in all the selected Work Requirements are aborted without prompting.

Key options:
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-abort my-analysis-run/task-group-1
```

### yd-start

The `yd-start` command starts Work Requirements that are in the `HELD` (paused) state.

```shell
yd-start [options] [<work-requirement-name-or-ID> ...]
```

It can optionally be supplied with a list of the names and/or YDIDs of the specific Work Requirements to start, otherwise the `namespace` and `tag` are used to generate a list of candidate requirements.

A YDID names its Work Requirement in whatever namespace it is in. A name is looked up in the configured `namespace` unless it is given as `namespace/name`; since a name can be reused, the `HELD` Work Requirement of that name is chosen, and if there are two or more, the name is ambiguous and its YDID must be given instead. A name may also be a glob pattern (e.g. `'proj-*'`), which selects every `HELD` Work Requirement whose name it matches, to be confirmed (or chosen from, with `--interactive`) as the candidates found by `namespace` and `tag` are; glob patterns cannot be mixed with explicit names or IDs.

Explicit names and IDs are handled in the order given, and are confirmed together. One that is not `HELD` is skipped with a warning naming its state. If a request fails because the Application's credentials are not accepted, or the platform cannot be reached, nothing further is attempted, the remaining items are reported as skipped, and the command exits with that failure's code (see [Machine-readable Output and Exit Codes](json-output.md)).

Key options:
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-start my-analysis-run --follow
yd-start 'analysis-*'
```

Work Requirements are submitted in the `HELD` state using `yd-submit --hold`; `yd-hold` returns a `RUNNING` one to it.

### yd-hold

The `yd-hold` command holds (pauses) `RUNNING` Work Requirements.

```shell
yd-hold [options] [<work-requirement-name-or-ID> ...]
```

It can optionally be supplied with a list of the names and/or YDIDs of the specific Work Requirements to hold, otherwise the `namespace` and `tag` are used to generate a list of candidate requirements. Names, YDIDs and glob patterns are handled as [`yd-start`](#yd-start) handles them, with `RUNNING` in place of `HELD`.

Key options:
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-hold my-analysis-run
```

A held Work Requirement is restarted using `yd-start`.

### yd-finish

The `yd-finish` command moves Work Requirements into the `FINISHING` state, meaning that the requirements will be allowed to conclude but that no new Tasks can be added.

```shell
yd-finish [options] [<work-requirement-name-or-ID> ...]
```

As with `yd-start` and `yd-hold`, specific names and/or YDIDs can be supplied, otherwise the `namespace` and `tag` are used to generate the list of candidates. Names, YDIDs and glob patterns are handled as [`yd-start`](#yd-start) handles them, with `RUNNING` or `HELD` in place of `HELD`: a Work Requirement that is already `FINISHING` is left out of the candidates, and skipped with a warning if named. With `--follow`, only the Work Requirements this command finished are followed.

Key options:
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-finish my-analysis-run
```

### yd-priority

The `yd-priority` command changes the priority of Work Requirements and Task Groups after they have been submitted. Higher priority acquires Workers ahead of lower priority (see [`priority`](property-dictionary.md)), so raising a Task Group's priority favours that stage of a run, and lowering a Work Requirement's lets others go first.

```shell
yd-priority [options] <priority> <target> [<target> ...]
```

The new priority, any finite number (negative ones included), comes first, followed by one or more targets, read as [`yd-abort`](#yd-abort) reads them:

- a Work Requirement name, `<namespace>/<wr-name>` or YDID
- a Task Group YDID, `<wr-name>/<tg-name>` or `<namespace>/<wr-name>/<tg-name>`

Targets are handled in the order given, each once, and confirmed together, the confirmation showing each one's current and new priority. A target that does not exist, or whose name is ambiguous, is reported as failed; one in a Work Requirement that has finished (`COMPLETED`, `CANCELLED` or `FAILED`), or already at the priority, is skipped with a warning. The Platform takes a Work Requirement whole, so the targets in one Work Requirement are changed together, in one update to a copy fetched just before it is sent: a change made to the Work Requirement since the targets were found is kept. An authentication or connection failure stops the command, with that failure's [exit code](json-output.md), and the targets not yet attempted are reported as skipped.

Key options:
- `--dry-run`/`-D` — report each target's current and new priority without changing anything
- `--json` — emit the actions taken as a JSON array, each with its `previousPriority` and `priority` (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-priority 10 my-analysis-run
yd-priority 5 my-analysis-run/render my-analysis-run/encode
yd-priority -1 ydid:workreq:000000:...
```

## Worker Pool and Compute Commands

### yd-provision

The `yd-provision` command provisions a new Worker Pool according to the specifications in the `workerPool` section of the TOML configuration file and/or in a Worker Pool JSON (or Jsonnet) document.

```shell
yd-provision [options] [<worker-pool-specification-file>]
```

Once provisioned, the Worker Pool will appear in the **Workers** tab in the YellowDog Portal, and its associated Compute Requirement will appear in the **Compute** tab.

Key options:
- `--target`/`-T <n>` — override the `targetInstanceCount` from the specification or configuration; a `maxNodes` lower than it is raised to match
- `--content-path`/`-F <directory>` — the directory in which files for upload or user data are found; a relative path in the specification (a `userDataFile`) is found there, while the specification file itself is always named from the current directory
- `--auto-follow-compute-requirements`/`-a` — when following, also follow the associated Compute Requirement
- `--dry-run`/`-D` — inspect the Worker Pool specification that would be submitted, in JSON format
- `--hide-user-data` — with `--dry-run`, show the User Data as a summary of its size, e.g. `<user data: 4,812 characters, 131 lines>`, rather than the script in full; refused without `--dry-run`
- `--report`/`-r` — report on a test run of the Worker Pool's Compute Requirement Template, without provisioning (see [Test-Running a Dynamic Template](#test-running-a-dynamic-template))
- `--validate` — check the specification file against its schema and stop, reporting every violation, rather than provisioning it (see [Specification Schemas](../README.md#specification-schemas))
- `--json` — emit the created Worker Pool as a JSON object; with `--dry-run`, the processed specification; refused with `--report`, which writes its own output (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-provision my_worker_pool.json --target 10 --follow
```

When `--quiet` (`-q`) is used, only the YDID of the provisioned Worker Pool is printed to stdout.

A Worker Pool defined in the configuration whose `maxNodes` exceeds `computeRequirementBatchSize` is provisioned as several Worker Pools; if one of them fails, those already provisioned are listed, since they are still running, and `--report` reports on the first of them alone, saying so. A Worker Pool specification is always provisioned as a single Worker Pool, with a warning if its `maxNodes` exceeds the batch size, and its `maintainInstanceCount` is set to `false`, as a Worker Pool requires. User Data merged in from the configuration is reported by its source and size, never printed.

The specification file may also be supplied using the deprecated `--worker-pool`/`-p` option; the positional argument is preferred.

See [Worker Pools](worker-pools.md) for the full specification reference.

### yd-shutdown

The `yd-shutdown` command shuts down the Worker Pools in the configured `namespace` whose names include the `tag`. All remaining work will be cancelled, but currently executing Tasks will be allowed to complete, after which a Provisioned Worker Pool's Compute Requirement will be terminated. Worker Pools that are already `SHUTDOWN` or `TERMINATED` are left out.

```shell
yd-shutdown [options] [<worker-pool-name-or-ID/node-id> ...]
```

Specific Worker Pool names or YDIDs, and/or Node YDIDs (to shut down individual nodes), can optionally be supplied as positional arguments instead of using the `namespace`/`tag` selection.

They are handled in the order given and confirmed together; one that does not exist is reported as failed, and a Worker Pool or Node that has already finished is skipped with a warning. If a request fails because the Application's credentials are not accepted, or the platform cannot be reached, nothing further is attempted, the remaining items are reported as skipped, and the command exits with that failure's code (see [Machine-readable Output and Exit Codes](json-output.md)).

A Worker Pool name argument can also be a glob pattern (`*`, `?`, `[...]`), matched client-side against Worker Pool names within the namespace (a name without wildcards matches exactly, so use `*` for partial matches); glob patterns cannot be mixed with literal names or YDIDs in the same command. Use `yd-list worker-pools --name 'wp-*'` to preview the matches first.

Key options:
- `--terminate`/`-T` — immediately terminate each Provisioned Worker Pool's Compute Requirement, straight after the pool is shut down, rather than waiting for executing Tasks to complete; a Configured Worker Pool has no Compute Requirement, and Node targets are unaffected
- `--auto-follow-compute-requirements`/`-a` — when following, also follow the associated Compute Requirements
- `--dry-run`/`-D` — show the Worker Pools (and Nodes) that would be shut down, whether matched or named, and with `--terminate` the Compute Requirements that would be terminated, without acting
- `--json` — emit the actions taken, or with `--dry-run` what would be taken, as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-shutdown 'wp-*' --dry-run
```

### yd-token

The `yd-token` command refreshes or regenerates the token of one or more Configured Worker Pools: the token that the YellowDog Agents on a pool's nodes use to register with it. Refreshing keeps the current token and sets its expiry afresh: `--ttl-hours` from now, or, without it, no expiry at all. Regenerating, with `--regenerate`, issues a new token instead, and Agents still holding the old one can no longer use it to register. Either is confirmed before anything is changed, the prompt saying what the tokens' expiry will be; `--yes` skips the confirmation.

```shell
yd-token [options] <worker-pool-name-or-ID> [<worker-pool-name-or-ID> ...]
```

Each argument is a Worker Pool's YDID or name (a bare name is looked up in the configured `namespace`, or give it as `namespace/name`), or a glob pattern (`*`, `?`, `[...]`) matched against Worker Pool names in the namespace, which takes only the Configured Worker Pools it matches that have not been shut down. Arguments are handled in the order given, each pool once. A Worker Pool that does not exist, or is not a Configured Worker Pool, is reported as failed, and one that has already been shut down is skipped with a warning; the others go ahead. If a request fails because the Application's credentials are not accepted, or the platform cannot be reached, nothing further is attempted, the remaining pools are reported as skipped, and the command exits with that failure's code (see [Machine-readable Output and Exit Codes](json-output.md)).

Each pool's token and its expiry time (in UTC, or `never`) are printed; with `--quiet`, the token alone, one per pool. Under `--json`, a token that does not expire has an `expiryTime` of `null`.

Key options:
- `--regenerate`/`-R` — issue a new token, invalidating the current one, rather than setting the current token's expiry afresh
- `--ttl-hours`/`-H` — the token's time to live, in whole hours from now; **without it, the refreshed or regenerated token never expires**
- `--dry-run`/`-D` — report the pools whose tokens would be refreshed or regenerated, without changing anything
- `--json` — emit the actions taken, each with the new `token` and its `expiryTime`, as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-token my-namespace/my-configured-pool --ttl-hours 720
yd-token 'cwp-*' --regenerate
```

### yd-resize

The `yd-resize` command resizes Worker Pools and Compute Requirements. A Compute Requirement is resized when it is given by its ID, or by name with the `--compute-requirement`/`-C` option: a Worker Pool and its Compute Requirement share their name, so a name alone means the Worker Pool.

```shell
yd-resize [options] <worker-pool-or-compute-requirement-name-or-ID> <new-node/instance-count>
```

The name or ID of the Worker Pool or Compute Requirement is supplied along with the new target number of Nodes or Instances, which may be zero but not negative. A YDID is found in whatever namespace it belongs to; a name is looked up in the configured `namespace` unless it is given as `namespace/name`.

What cannot be resized is reported before anything is asked. A Worker Pool or Compute Requirement that does not exist exits with code 6. A Worker Pool fails if it is a Configured Worker Pool, is awaiting nodes, or would be taken outside its minimum or maximum number of nodes; it is skipped if it has already shut down or terminated, or already expects the number of nodes asked for.

Only a `RUNNING` Compute Requirement is resized: one in any other state is skipped, as is one whose target is already the number of instances asked for, and a name shared by two `RUNNING` Compute Requirements is ambiguous, so the YDID must be given instead. The confirmation shows the current and new sizes.

Key options:
- `--compute-requirement`/`-C` — resize the Compute Requirement of this name instead of the Worker Pool; not needed with a Compute Requirement ID, and refused with a Worker Pool ID
- `--auto-follow-compute-requirements`/`-a` — when following, also follow the associated Compute Requirement
- `--wait`/`-w` — when resizing a Compute Requirement, wait until the Compute Requirement has its new target of Instances running (see below)
- `--timeout <seconds>` — with `--wait`, stop waiting after this many seconds and exit 1 (default: no limit)
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

With `--wait`, the command returns only once the resized Compute Requirement has settled: it is `RUNNING`, as many of its Instances are `RUNNING` as its new target asks for, and none is still starting, stopping or terminating. Scaling up therefore waits for the new Instances to start, and scaling down for the surplus Instances to finish terminating, which can take a minute or more. Progress is printed whenever it changes. A Compute Requirement that cannot reach its target, because the cloud provider has no more capacity of the kind it asks for (on-demand as well as spot) or an Allowance or quota stands in the way, never settles, so give a `--timeout` when that is possible: if it passes first, the command reports what is still missing and exits 1, though the resize itself has been made and is recorded as `resized`. `--wait` cannot be combined with `--follow`, and does not apply to Worker Pools.

```shell
yd-resize pyex-slurm-pwt_230711-1243561-0d 10
yd-resize ydid:wrkrpool:D9C548:1f020696-ae9a-4786-bed2-c31b484b1d4f 10
yd-resize --compute-requirement pyex-slurm-pwt_230712-1102264-4c 5
yd-resize ydid:compreq:D9C548:600bef1f-7ccd-431c-afcc-b56208565aac 5
yd-resize -C pyex-slurm-pwt_230712-1102264-4c 5 --wait --timeout 600
```

### yd-nodeaction

The `yd-nodeaction` command submits Node Actions to running Worker Pool nodes.

```shell
yd-nodeaction [options]
```

The command takes no positional arguments: the actions are supplied with `--actions`, which is required unless `--status` is used (and is refused with it). `--worker-pool` accepts a pool name or a Worker Pool YDID; if omitted, an interactive selection of the active pools is shown. Without `--node` or `--all-nodes`, the nodes are chosen interactively from the pool's running ones.

The specification is checked first, so a faulty one fails (exit 1) before anything is looked up or submitted.

Nodes given with `--node` must be node YDIDs, and are each targeted once however often they are given; they must all be in one Worker Pool, which is then found from them (or, with `--worker-pool`, must be the one it names), and a node that has terminated or deregistered is skipped with a warning. A Worker Pool or node that does not exist exits with code 6, and one that has shut down or terminated is refused. If a submission fails because the Application's credentials are not accepted, or the platform cannot be reached, nothing further is attempted, and the command exits with that failure's code.

Key options:
- `--actions`/`-S <file>` — the Node Action spec file, in JSON or Jsonnet format
- `--worker-pool`/`-p <name>` — the target Worker Pool
- `--node`/`-N <node-id>` — target a specific node by ID; can be supplied multiple times
- `--all-nodes` — target all current nodes in the Worker Pool, filtered by `nodeTypes` if present in the spec; cannot be combined with `--node`
- `--follow`/`-f` — poll the node action queues after submission until every one is `EMPTY` or `FAILED`
- `--timeout <seconds>` — with `--follow`, stop after this many seconds, failing (exit 1) if any queue has not finished; by default there is no limit
- `--status` — show the Node Action queue for the selected node(s); `--details`/`-d` shows the full JSON
- `--content-path`/`-F <directory>` — the directory in which files for upload are found
- `--validate` — check the `--actions` file against its schema and stop, reporting every violation, rather than submitting it; refused with `--status` (see [Specification Schemas](../README.md#specification-schemas))
- `--json` — emit the submissions, or with `--status` the node action queues, as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
# Submit actions to interactively selected node(s)
yd-nodeaction --actions my_actions.json --worker-pool my-pool

# Submit to all current nodes in a pool
yd-nodeaction --actions my_actions.json --worker-pool my-pool --all-nodes

# Submit to a specific node by YDID (worker pool resolved automatically)
yd-nodeaction --actions my_actions.json --node ydid:node:D9C548:... --follow

# Check node action queue status for a specific node
yd-nodeaction --status --node ydid:node:D9C548:... --details
```

See [Node Actions](worker-pools.md#node-actions) for the spec format, action types, and field reference.

### yd-instantiate

The `yd-instantiate` command instantiates a Compute Requirement (i.e. a set of instances that are managed by their creator and do not automatically become part of a YellowDog Worker Pool).

```shell
yd-instantiate [options] [<compute-requirement-specification-file>]
```

This command uses the data from the `workerPool` configuration section (or, synonymously, the `computeRequirement` section), but only uses the `name`, `templateId`, `targetInstanceCount`, `instanceTags`, `userData`, `requirementTag`, and `imagesId` properties. In addition, the Boolean property `maintainInstanceCount` (default = `false`) is available for use with `yd-instantiate`.

Compute Requirements can be instantiated directly from JSON (or Jsonnet) specifications, supplied as the positional argument or by using the `computeRequirementData` property in the `workerPool`/`computeRequirement` section. The properties listed above will be inherited from the `config.toml` `workerPool` specification if they are not present in the JSON file.

The specification file may also be supplied using the deprecated `--compute-requirement`/`-C` or `--worker-pool`/`-p` options; the positional argument is preferred.

Variable substitutions must be prefixed and postfixed by a double underscore (`__`), e.g. `"__{{my_variable}}__"`.

Key options:
- `--target`/`-T <n>` — override `targetInstanceCount` from the specification or configuration
- `--report`/`-r` — report on a test run of a Dynamic Template, without provisioning (see below)
- `--content-path`/`-F <directory>` — the directory in which files for upload or user data are found
- `--dry-run`/`-D` — inspect the Compute Requirement specification that would be submitted, in JSON format; the JSON output can itself be used with `yd-instantiate`
- `--hide-user-data` — with `--dry-run`, show the User Data as a summary of its size rather than the script in full, as for `yd-provision`; refused without `--dry-run`
- `--validate` — check the specification against its schema and stop, reporting every violation, rather than instantiating it (see [Specification Schemas](../README.md#specification-schemas))
- `--json` — emit the created Compute Requirement as a JSON object; with `--dry-run`, the processed specification; refused with `--report`, which writes its own output (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-instantiate my_compute_requirement.json --target 4
```

An example JSON specification is shown below:

```json
{
  "imagesId": "ydid:imgfam:000000:41962592-577c-4fde-ab03-d852465e7f8b",
  "instanceTags": {"a1": "one", "a2": "two"},
  "requirementName": "cr_test___{{datetime}}__",
  "requirementNamespace": "pyexamples",
  "requirementTag": "pyexamples-test",
  "templateId": "ydid:crt:000000:230e9a42-97db-4d69-aa91-29ff309951b4",
  "userData": "#!/bin/bash\n#Other stuff...",
  "targetInstanceCount": 1,
  "maintainInstanceCount": true
}
```

Note that the `templateId` property can use either the YellowDog ID ('YDID') for the Compute Requirement Template, or its name. The same is true for the `imagesId` property.

Values missing from a JSON specification are taken from the configuration file; `targetInstanceCount` only if the configuration actually sets it, so that a specification with no count is never sent with a count of zero. User Data merged in from the configuration is reported by its source and size, never printed. A target count larger than `computeRequirementBatchSize` is split across several Compute Requirements; if one of them fails, those already provisioned are listed, since they are still running, and `--report` reports on the first of them alone, saying so.

If a Worker Pool is defined in JSON, using `workerPoolData` in the configuration file or by supplying the command-line positional argument, `yd-instantiate` will extract the Compute Requirement from the Worker Pool specification (ignoring Worker-Pool-specific data), and use that for instantiating the Compute Requirement.

When `--quiet` (`-q`) is used, only the YDID of the instantiated Compute Requirement is printed to stdout.

#### Test-Running a Dynamic Template

When the `templateId` of a Dynamic Requirement is used, the `yd-instantiate` command can be used to report on a test run of the Template, using the `--report` (or `-r`) command-line option. This can be used with both TOML-defined and JSON-defined Compute Requirement specifications. `yd-provision --report` does the same for a Worker Pool, testing the Compute Requirement it would be provisioned with.

No instances will be provisioned during the test run.

For example:

```shell
% yd-instantiate --report --quiet
┌────┬────────┬────────────┬───────────────────────────┬───────────┬────────────────┬───────────────────┐
│    │   Rank │ Provider   │ Type                      │ Region    │ InstanceType   │ Source Name       │
├────┼────────┼────────────┼───────────────────────────┼───────────┼────────────────┼───────────────────┤
│  1 │      1 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ t3a.micro      │ awsspot-eu-west-2 │
│  2 │      2 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ t3a.small      │ awsspot-eu-west-2 │
│  3 │      3 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ c5a.large      │ awsspot-eu-west-2 │
│  4 │      3 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ c6a.large      │ awsspot-eu-west-2 │
│  5 │      3 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ t3a.medium     │ awsspot-eu-west-2 │
│  6 │      4 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ m5a.large      │ awsspot-eu-west-2 │
│  7 │      4 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ m5ad.large     │ awsspot-eu-west-2 │
│  8 │      4 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ m6a.large      │ awsspot-eu-west-2 │
│  9 │      4 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ t3a.large      │ awsspot-eu-west-2 │
│ 10 │      5 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ r5a.large      │ awsspot-eu-west-2 │
└────┴────────┴────────────┴───────────────────────────┴───────────┴────────────────┴───────────────────┘
```

### yd-terminate

The `yd-terminate` command immediately terminates Compute Requirements that match the `namespace` and `tag` found in the configuration file. Any executing Tasks will be terminated immediately, and the Worker Pool will be shut down. A Compute Requirement in any state but `TERMINATING` or `TERMINATED` can be terminated, as can an Instance; to terminate Instances without their being replaced, use [`yd-compute-deprovision`](#yd-compute-deprovision).

```shell
yd-terminate [options] [<name-or-ID> ...]
```

Specific targets can optionally be supplied as positional arguments instead of using the `namespace`/`tag` selection. Each target can be:

- a Compute Requirement name or YDID (the whole requirement is terminated)
- a single instance, in `<compute-requirement-ydid>.<instance-id>` form
- a Node YDID (the node's instance is terminated)

A Compute Requirement name is looked up in the configured namespace unless it is given as `namespace/name`. A name argument can also be a glob pattern (`*`, `?`, `[...]`), matched client-side against Compute Requirement names within the namespace (a name without wildcards matches exactly, so use `*` for partial matches); glob patterns cannot be mixed with literal names or YDIDs in the same command. Use `--dry-run`, or `yd-list compute-requirements --name 'ci-*'`, to preview the matches first.

Explicit names and IDs are handled as [`yd-compute-stop`](#yd-compute-stop) handles them: in the order given, confirmed together, with the Instances in a Compute Requirement terminated in a single request. A Compute Requirement, Instance or Node that is already terminating or terminated is skipped with a warning, and a failure of the Application's credentials or of the connection stops the command, the remaining items being reported as skipped.

Key options:
- `--dry-run`/`-D` — show which Compute Requirements (and Instances or Nodes) would be terminated, whether selected by `namespace` and `tag`, by glob pattern or by name or ID, without terminating anything
- `--json` — emit the actions taken, or with `--dry-run` what would be taken, as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))
- `--follow`/`-f` — follow the affected Compute Requirements' event streams after the action is applied

```shell
yd-terminate 'ci-*' --dry-run
```

### yd-compute-stop

The `yd-compute-stop` command stops `RUNNING` Compute Requirements and Instances. Stopped Compute Requirements and Instances can subsequently be started again using `yd-compute-start`.

```shell
yd-compute-stop [options] [<name-or-ID> ...]
```

If no arguments are supplied, Compute Requirements that match the `namespace` and `tag` found in the configuration file are candidates for stopping. Alternatively, the command accepts a list of any of the following:

- Compute Requirement names or YDIDs, to stop whole Compute Requirements
- Instances in `<compute-requirement-ydid>.<instance-id>` form, to stop individual Instances
- Node YDIDs, to stop the Instances on which Worker Pool Nodes are running

A Compute Requirement name is looked up in the configured namespace unless it is given as `namespace/name`. A name may also be a glob pattern (e.g. `'cr-*'`), which selects every `RUNNING` Compute Requirement whose name it matches, to be confirmed (or chosen from, with `--interactive`) as the candidates found by `namespace` and `tag` are; glob patterns cannot be mixed with explicit names or IDs.

Explicit names and IDs are handled in the order given, and are confirmed together: Instances in the same Compute Requirement are stopped in a single request. A Compute Requirement or Instance that is not `RUNNING` is skipped with a warning. If a request fails because the Application's credentials are not accepted, or the platform cannot be reached, nothing further is attempted, the remaining items are reported as skipped, and the command exits with that failure's code (see [Machine-readable Output and Exit Codes](json-output.md)).

The `--follow`/`-f` option follows the event stream(s) of the Compute Requirement(s) acted on.

Key options:
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-compute-stop
yd-compute-stop my-compute-requirement
yd-compute-stop ydid:compreq:D9C548:98879b5a-9192-4a56-ad25-fc1330e49185
yd-compute-stop ydid:compreq:D9C548:98879b5a-9192-4a56-ad25-fc1330e49185.i-0a1b2c3d4e5f67890
yd-compute-stop ydid:node:D9C548:f9d5a10e-5b0e-4b76-b50f-d2bbac0a5cb8
```

### yd-compute-start

The `yd-compute-start` command starts `STOPPED` Compute Requirements and Instances.

```shell
yd-compute-start [options] [<name-or-ID> ...]
```

It accepts the same arguments as `yd-compute-stop`, and handles them in the same way: if no arguments are supplied, `STOPPED` Compute Requirements that match the `namespace` and `tag` are candidates for starting; otherwise, supply a list of Compute Requirement names (or glob patterns) or YDIDs, Instances in `<compute-requirement-ydid>.<instance-id>` form, or Node YDIDs.

Key options:
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-compute-start my-compute-requirement --follow
```

### yd-compute-restart

The `yd-compute-restart` command restarts (reboots) `RUNNING` Instances. Restarting applies to Instances only; whole Compute Requirements cannot be restarted.

```shell
yd-compute-restart [options] <instance-or-node-ID> ...
```

Instances to restart are supplied as a list of Instances in `<compute-requirement-ydid>.<instance-id>` form and/or Node YDIDs; at least one is required. They are handled as `yd-compute-stop` handles them: in the order given, confirmed together, one request per Compute Requirement, and an Instance that is not `RUNNING` is skipped with a warning.

Key options:
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-compute-restart ydid:compreq:D9C548:98879b5a-9192-4a56-ad25-fc1330e49185.i-0a1b2c3d4e5f67890
```

### yd-compute-deprovision

The `yd-compute-deprovision` command deprovisions Instances: it terminates them and reduces their Compute Requirement's target instance count by the same number, so that they are not replaced. Terminating an Instance with `yd-terminate` leaves the target count as it was, so a Compute Requirement that maintains its instance count replaces it. Deprovisioning applies to Instances only; to remove a whole Compute Requirement, use `yd-terminate`.

An Instance of a Provisioned Worker Pool can be deprovisioned too, by its `cr_id.instance_id` or its Node's YDID. The pool's expected node count follows its Compute Requirement's reduced target, so the pool does not ask for a replacement either. A pool left with no nodes stays up until its idle pool shutdown, if it has one, takes effect; use `yd-shutdown` to shut it down at once.

```shell
yd-compute-deprovision [options] <instance-or-node-ID> ...
```

Instances to deprovision are supplied as a list of Instances in `<compute-requirement-ydid>.<instance-id>` form and/or Node YDIDs; at least one is required, and a Compute Requirement name or ID is reported as failed. They are handled as `yd-compute-stop` handles them: in the order given, confirmed together, one request per Compute Requirement, and an Instance that is already `TERMINATING` or `TERMINATED` is skipped with a warning. The command returns once the Platform has accepted the request: the target count drops at once, and the Instances are terminated shortly afterwards, which `--follow` shows.

Key options:
- `--follow`/`-f` — follow the Compute Requirements' events as the Instances are terminated, until each is at its new target
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-compute-deprovision ydid:compreq:D9C548:98879b5a-9192-4a56-ad25-fc1330e49185.i-0a1b2c3d4e5f67890
```

### yd-compute-reprovision

The `yd-compute-reprovision` command reprovisions `RUNNING` Compute Requirements: it asks the Platform to provision Instances until as many are running as each Compute Requirement's target instance count asks for. This restores a Compute Requirement that has fewer Instances than its target, for example after Instances were terminated with `yd-terminate` or reclaimed by the cloud provider, without changing the target. It is the counterpart of `yd-compute-deprovision`, which reduces the target; to change the target itself, use `yd-resize`. Reprovisioning applies to Compute Requirements only; Instance and Node IDs are reported as failed.

```shell
yd-compute-reprovision [options] [<name-or-ID> ...]
```

It selects Compute Requirements as `yd-compute-stop` does: if no arguments are supplied, `RUNNING` Compute Requirements that match the `namespace` and `tag` are candidates for reprovisioning; otherwise, supply a list of Compute Requirement names (or glob patterns) or YDIDs. A Compute Requirement that is not `RUNNING` is skipped with a warning, including one still `PROVISIONING`, which is already provisioning towards its target. Reprovisioning a Compute Requirement that already has as many Instances running as its target count changes nothing. The command returns once the Platform has accepted the request: the Compute Requirement moves to `PROVISIONING` while the new Instances start, and `--follow` shows them being provisioned.

Key options:
- `--follow`/`-f` — follow the Compute Requirements' events as Instances are provisioned, until each is at its target
- `--wait`/`-w` — wait until each Compute Requirement reprovisioned has its target number of Instances running, as for `yd-resize --wait`
- `--timeout <seconds>` — with `--wait`, stop waiting after this many seconds and exit 1 (default: no limit)
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-compute-reprovision my-compute-requirement --follow
yd-compute-reprovision my-compute-requirement --wait --timeout 600
```

## Monitoring and Inspection Commands

### yd-list

The `yd-list` command lists various YellowDog items, using the configured `namespace`, and a `tag` given on the command line (not the configured one), to target the scope of what to list.

```shell
yd-list [options] <entity-type>
```

Valid entity types are:

| Entity Type | Synonym | Description |
|---|---|---|
| `allowances` | `A` | Allowances |
| `applications` | `B` | Applications |
| `attribute-definitions` | `D` | User compute attribute definitions |
| `compute-requirement-templates` | `C` | Compute Requirement Templates |
| `compute-requirements` | `R` | Compute Requirements |
| `compute-source-templates` | `S` | Compute Source Templates |
| `groups` | `G` | Groups |
| `image-families` | `I` | Machine Image Families, Groups, and Images |
| `instances` | `E` | Compute instances (interactive: select a Compute Requirement first) |
| `keyrings` | `K` | Keyrings |
| `namespace-policies` | `L` | Namespace Policies |
| `namespaces` | `M` | Namespaces |
| `nodes` | `N` | Worker Pool Nodes (interactive: select a Worker Pool first) |
| `permissions` | `X` | Permissions |
| `roles` | `O` | Roles |
| `task-groups` | `H` | Task Groups (interactive: select a Work Requirement first) |
| `tasks` | `T` | Tasks (interactive: select a Work Requirement and Task Group first) |
| `users` | `U` | Users |
| `work-requirements` | `W` | Work Requirements |
| `worker-pools` | `P` | Worker Pools |
| `workers` | `F` | Workers (interactive: select a Worker Pool first) |

The interactive selections noted above are made only for the readable listing: with `--json`, `--count` or `--ids-only`, every matching parent's items are listed without asking.

Unambiguous prefix matching is supported — for example `yd-list work-r` resolves to `yd-list work-requirements`, and `yd-list key` resolves to `yd-list keyrings`. Single uppercase synonyms also work, e.g. `yd-list W` and `yd-list K`.

`yd-list` has more options than are listed here; use `yd-list --help` to inspect the full set. Commonly used options are:

| Option | Description |
|---|---|
| `--details`/`-d` | Show the full JSON representation of selected objects; in some cases this drills into additional detail, e.g. `yd-list keyrings --details` allows inspection of the Credentials within the selected Keyrings |
| `--active-only`/`-l` | List only entities in a non-terminated state: Work Requirements (and their Task Groups and Tasks), Worker Pools (and their Nodes and Workers) and Compute Requirements (and their Instances); a Compute Requirement that is still provisioning counts as active |
| `--name <glob>` | List only entities whose name matches the given glob pattern (`*`, `?`, `[...]`), e.g. `yd-list work-requirements --name 'myproject-*'` (a name without wildcards matches exactly, so use `*` for partial matches, e.g. `'linux*'` or `'*linux*'`); applies to Work Requirements, Worker Pools, Compute Requirements, Compute Requirement/Source Templates, Image Families, Users, Applications, Groups, Roles, Keyrings and Permissions, and is refused for other entity types (for Groups, Roles, Keyrings and Permissions, whose names are optional, any entries without a name are excluded from matching, with a warning); it's also a non-destructive way to preview which entities a glob passed to `yd-cancel`/`yd-shutdown`/`yd-terminate` would select |
| `--status <status>` | Include only entities whose status matches (case-insensitive); repeatable to allow multiple statuses. Applies to the entity types that have a status: Work Requirements, Task Groups, Tasks, Worker Pools, Nodes, Workers, Compute Requirements and Instances |
| `--ids-only`/`-D` | Print only the YellowDog IDs of the listed entities, one per line. Like `--json`, this lists non-interactively: e.g. `yd-list tasks --ids-only` gives the IDs of all Tasks across all matching Work Requirements and Task Groups. An Instance is given as `<compute-requirement-ydid>.<instance-id>`, the form `yd-compute-stop` and the other Instance commands take. Refused for attribute definitions, namespace policies and permissions, which have no IDs |
| `--json`/`-J` | Emit the listing as a plain JSON array of summary objects (mutually exclusive with `--ids-only`) |
| `--count`/`-C` | Print only the number of matching items. Implies `--quiet`, and overrides `--details`, `--json` and `--ids-only`. Like `--json`, this aggregates non-interactively: e.g. `yd-list tasks -C` counts all Tasks across all matching Work Requirements and Task Groups |
| `--sort <name\|created\|status\|namespace>[,...]` | Order listed (and interactively selected) entities by `name` (default), `created` (creation time, earliest first), `status` (status name), or `namespace`. Give several keys, separated by commas, to sort by each in turn: `--sort namespace,status,created` groups by namespace, then by status within it, then by age; the name (for Instances the instance type, for Nodes and Workers the Worker Pool name, for Tasks the task number) breaks any tie that remains. `created`, `status` and `namespace` apply to entities exposing those fields, e.g. Work Requirements, Compute Requirements, Worker Pools; a key an entity type lacks is passed over. This is a global option, so it also affects the numbered selection lists shown by commands such as `yd-cancel`, `yd-hold` and `yd-start` |
| `--reverse` | List items in reverse (descending) order: the whole order `--sort` gives, every key's included |
| `--public-ips-only` | With `instances`, list public IP addresses only; it cannot be combined with `--json`, `--ids-only` or `--details` |
| `--hide-user-data` | With `--details` or `--json`, show each `userData` value (in Compute Source Templates, Compute Requirement Templates and Compute Requirements) as a summary of its size, e.g. `<user data: 4,812 characters, 131 lines>`, rather than the script in full. It applies to `--output-file` too, whose JSON can then no longer be used with `yd-create` as it is |

```shell
yd-list work-requirements --name 'myproject-*' --active-only
```

For convenience, `tag` is set to the empty string unless explicitly set on the command line; `namespace` falls back to the configured value as usual.

An option that does not apply to the entity type listed — `--name`, `--status`, `--active-only`, `--ids-only`, `--public-ips-only` or `--substitute-ids` — is refused (exit code 2), rather than ignored and the whole listing returned. With `--details`, Compute Requirements are shown in full, as Work Requirements and Worker Pools are.

The `--substitute-ids`/`-U`, `--strip-ids`, `--auto-select-all` and `--output-file` options are used when capturing existing resources as specifications — see [Generating Resource Specifications using `yd-list`](resources.md#generating-resource-specifications-using-yd-list).

### yd-show

The `yd-show` command shows the details (in JSON) of any YellowDog entity that has a YellowDog ID.

```shell
yd-show [options] <yellowdog-id> [<yellowdog-id> ...]
```

It supports IDs referring to:

- Compute Source Templates
- Compute Requirement Templates
- Compute Requirements
- Sources
- Worker Pools
- Nodes
- Workers
- Work Requirements
- Task Groups
- Tasks
- Image Families, Image Groups, and Images
- Keyrings
- Allowances
- Users
- Applications
- Groups
- Roles

Instances have no YellowDog ID of their own: they're identified by the combination of their Compute Requirement and their provider-assigned instance ID. An Instance is therefore supplied in `<compute-requirement-ydid>.<instance-id>` form, the same format used by `yd-terminate` and `yd-compute-stop`/`yd-compute-start`/`yd-compute-restart`. Only the first `.` separates the two parts, so instance IDs that contain dots of their own (OCI's OCIDs, for example) need no special treatment.

Key options:
- `--show-token` — include the Worker Pool token when showing the details of a Configured Worker Pool
- `--show-source-report` — follow a Compute Requirement with the Platform's report of how its sources were chosen: the Compute Source Templates considered, selected and rejected, each source's rank and score, and the constraints and preferences applied. Only a Compute Requirement provisioned from a dynamic template has one, and it is kept after the Compute Requirement has been terminated; for any other, a warning says so and the Compute Requirement is still shown
- `--show-exhaustion` — follow a Compute Requirement with `{"computeRequirementId", "exhaustedAllowances"}`, the Allowances that are exhausted for it, each with its `allowanceId`, `allowanceDescription` and `exhaustedSourceIds`; an empty list means no Allowance is holding it back (see [`yd-boost`](#yd-boost))

- `--show-members` — follow a Group with `{"groupId", "users", "applications"}`, its Users (each `{"id", "username", "name"}`, `username` being `null` for an external User) and its Applications (each `{"id", "name"}`), or a Role with `{"roleId", "groups"}`, the Groups that hold it (each `{"id", "name"}`); a Group's own roles are already in its details. It is refused unless at least one of the IDs is a Group's or a Role's

A User is always shown with `groups`, the names of the Groups it belongs to, as an Application is and as `yd-list users --details` shows them.

`--show-source-report` and `--show-exhaustion` also apply to a Provisioned Worker Pool's ID, reporting on its Compute Requirement after the pool; a Configured Worker Pool, which has no Compute Requirement, is shown with a warning and no reports. Each is refused unless at least one of the IDs is a Compute Requirement's or a Worker Pool's.

- `--hide-user-data` — show each `userData` value (in Compute Source Templates, Compute Requirement Templates, Compute Requirements and Compute Sources) as a summary of its size rather than the script in full, as for `yd-list`, `--output-file` included
- `--substitute-ids`/`-U`, `--strip-ids`, `--output-file <file>` — as for `yd-list`; see [Generating Resource Specifications using `yd-list`](resources.md#generating-resource-specifications-using-yd-list). `--substitute-ids` is refused unless at least one of the IDs is a Compute Source Template's, a Compute Requirement Template's or an Allowance's

At least one ID is required. A YDID names its entity in whatever namespace it is in, so `yd-show` takes no `--namespace` or `--tag`.

Supplying more than one ID produces a JSON array, whatever the verbosity options say, so that the shape of the output follows what was asked for rather than how much of it succeeded. A single ID produces the object on its own, except when `--show-token` yields both a Configured Worker Pool and its token, `--show-source-report` or `--show-exhaustion` add their reports after a Compute Requirement or Provisioned Worker Pool, or `--show-members` adds a Group's or a Role's members. Combine with `--quiet`/`-q` to suppress the status messages and leave only the JSON on stdout.

It exits with code 0 if every ID was shown; 6 if those that were not all name entities that do not exist; and 1 if any could not be shown for another reason (an invalid ID, or an API error). The IDs that could be shown are still emitted. If a lookup fails because the Application's credentials are not accepted, or the platform cannot be reached, the remaining IDs are not attempted, what was shown is still emitted, and the command exits with that failure's code (4 or 8).

```shell
yd-show ydid:compreq:000000:07e0a2c1-3e0a-4b40-9f5b-0b0f81a29b16 --show-source-report --show-exhaustion
yd-show ydid:compreq:000000:07e0a2c1-3e0a-4b40-9f5b-0b0f81a29b16.i-0123456789abcdef0
yd-show ydid:compreq:000000:07e0a2c1-3e0a-4b40-9f5b-0b0f81a29b16.ocid1.instance.oc1.uk-london-1.anwgiljtbfkcyvycib2ubsewuwqqffx2jzyp7dolkhxanfvdsgvjzjrytepa
```

### yd-follow

The `yd-follow` command follows the event streams for one or more Work Requirements, Worker Pools and Compute Requirements, specified by their YellowDog IDs.

```shell
yd-follow [options] <yellowdog-id> [<yellowdog-id> ...]
```

At least one ID is required, and each must be a Work Requirement's, Worker Pool's or Compute Requirement's: anything else is refused before anything is followed (exit code 2). The IDs are followed in the order given, each once.

The command will continue to run until manually stopped using `CTRL-C`, unless all the IDs to be followed are in a terminal state. A stream that drops is reconnected, waiting 5, 10, 20 and then 30 seconds between attempts, for up to five minutes of continuous outage, which ends only once a stream delivers an event, so a connection that is accepted and then drops before any, over and over, is given up on as well; a stream closed while its entity is still live (by a proxy dropping an idle connection, say) is reconnected too, the entity's status being checked when its stream closes.

It exits with code 0 if every stream could be followed. Otherwise it exits with the code of the failure — 6 for an entity that does not exist, 4 for credentials that are not accepted, 8 for a connection that could not be made or re-made — or 1 if the streams failed for different reasons. This applies to the event streams that other commands follow with `--follow` too, though only `yd-follow` takes its exit code from them.

Note that the exit code reflects only whether the event streams could be followed, not the final status of the entities themselves — use `yd-wait` (or `yd-submit --exit-on-failure`) to act on Work Requirement outcomes.

Key options:
- `--progress` — display a live progress bar for Work Requirement IDs (ignored for Worker Pool and Compute Requirement IDs)
- `--auto-follow-compute-requirements`/`-a` — automatically follow the associated Compute Requirements when following Worker Pools
- `--json` — print each event as a JSON document as it arrives, refused with `--progress` (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-follow ydid:workreq:D9C548:37d3c0cd-2651-4779-be17-89a8601b03b8 \
          ydid:wrkrpool:D9C548:c22f0d9a-4a99-460d-ae42-15653ba264c3 \
          ydid:compreq:D9C548:98879b5a-9192-4a56-ad25-fc1330e49185
```

### yd-wait

The `yd-wait` command waits for one or more Work Requirements, Worker Pools, or Compute Requirements to reach a terminal state, then exits with a status code reflecting the outcome.

```shell
yd-wait [options] <yellowdog-id> [<yellowdog-id> ...]
```

At least one ID is required, and each must be the ID of a Work Requirement, Worker Pool or Compute Requirement; anything else is refused before anything is followed (exit 2). Multiple IDs can be supplied, and `yd-wait` blocks until all of them have reached a terminal state: `COMPLETED`, `FAILED` or `CANCELLED` for a Work Requirement, `SHUTDOWN` or `TERMINATED` for a Worker Pool, and `TERMINATED` for a Compute Requirement. This makes it suitable for scripting pipelines. Use `--quiet`/`-q` to suppress all output and rely solely on the exit code. For interactive observation of event streams, use `yd-follow` instead.

- **Exit 0** — every entity reached a terminal state, and no Work Requirement ended `FAILED` or `CANCELLED`
- **Exit 1** — a Work Requirement ended `FAILED` or `CANCELLED`, `--timeout` expired with an entity not finished, or there were failures with different causes
- **Exit 4, 6 or 8** — every failure had the one cause: credentials not accepted (4), an entity that does not exist (6), or an event stream that could not be connected or reconnected (8)

An entity that is still not in a terminal state when following ends — because `--timeout` expired, or its event stream was lost — is a failure, reported with its current status, never a success.

Key options:
- `--timeout <seconds>` — stop waiting after this many seconds, and fail if anything has not finished (default: no limit)
- `--json` — emit each item's final status as a JSON array of `{"id", "name", "status", "succeeded"}` (see [Machine-readable Output and Exit Codes](json-output.md))

```bash
WR_ID=$(yd-submit mywork.json --quiet)
yd-wait "$WR_ID" && yd-download results/
```

### yd-compare

The `yd-compare` command takes a Work Requirement or Task Group ID and one or more Worker Pool IDs, and compares the selected Task Group(s) against the available Nodes/Workers in the Worker Pool(s). If a Work Requirement ID is supplied, all Task Groups in the Work Requirement will be compared.

```shell
yd-compare [options] <work-requirement-or-task-group-ID> <provisioned-worker-pool-ID> ...
```

The command checks if the **Run Specification** of a Task Group matches the properties of the Worker Pools and their registered Nodes and Workers, meaning there are Workers in the Worker Pool that could be claimed by the Task Group and that the Worker Pool would be a candidate for scaling up to meet the demands of the Task Group.

A detailed matching report showing the comparison against each specific property is created, which can be used to determine which properties are preventing a Worker Pool match.

A Worker Pool that cannot be compared — its Compute Requirement or its Nodes cannot be fetched — is reported as `FAILED` with the reason, and the other Worker Pools and Task Groups are still compared; the command then exits non-zero, with the failure's [exit code](json-output.md) when every failure had the one cause. An authentication or connection failure stops the comparison. A Task Group or Work Requirement that does not exist exits 6, and a Work Requirement with no Task Groups is reported with a warning.

By default every Node registered to a Worker Pool is included in the comparison, whatever its state. The `--running-nodes-only` option restricts the comparison to Nodes in the `RUNNING` state, which gives a more accurate picture of current capacity when a pool contains Nodes that are still provisioning or have been terminated.

Key options:
- `--running-nodes-only` — compare against Nodes in the `RUNNING` state only
- `--json` — emit the comparison as a JSON array, one object per Worker Pool compared with each Task Group (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-compare ydid:taskgrp:000000:83587010-5e26-4174-92a7-c7cc2612638d:1 ydid:wrkrpool:000000:3666e4c5-382e-4512-a2c7-33dbb839f75
```

The properties are compared as follows. A property the Task Group leaves unset, or sets to an empty list, places no constraint on the Worker Pool.

| **Property**         | **Compared with**                                                                       | **Matches when**                                                                                                 |
|----------------------|-----------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------|
| **Instance Type(s)** | The instance types of the Worker Pool's Compute Sources (an AWS Fleet's overrides included) | Every one of them is in the Task Group's list                                                                    |
| **Provider(s)**      | The providers of the Worker Pool's Compute Sources                                      | Every one of them is in the Task Group's list; a source whose provider can't be determined is shown as `UNKNOWN`, and doesn't match |
| **Region(s)**        | The regions of the Worker Pool's Compute Sources                                        | Every one of them is in the Task Group's list                                                                    |
| **Namespace(s)**     | The Worker Pool's namespace                                                             | It is in the Task Group's list                                                                                   |
| **Worker Tag(s)**    | The Worker Pool's worker tag                                                            | It is in the Task Group's list                                                                                   |
| **Task Type(s)**     | The task types reported by one Node: a `RUNNING` one where there is one                 | The Node supports all of the Task Group's task types (the scheduler, too, takes a single Node's task types)     |
| **RAM**, **vCPUs**   | The value reported by every Node                                                        | Every Node's value is within the Task Group's range                                                              |

Only Nodes that have reported their details are compared: a Node that has registered but not yet reported them is left out rather than counted as a non-match.

The match status of each property, and of the Worker Pool as a whole, is one of:

| **Match Status** | **Meaning**                                                                                                                                                 |
|------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **YES**          | The property matches; for the Worker Pool, every property does, so far as the Nodes that have reported their details show.                                |
| **NO**           | The property doesn't match (for RAM and vCPUs, any one Node failing is enough); for the Worker Pool, at least one property doesn't.                         |
| **MAYBE**        | The property depends on the Nodes (task types, RAM, vCPUs) and no Node has yet reported its details; for the Worker Pool, no property is NO but at least one is MAYBE. |

A Worker Pool ID given more than once is compared once, with a warning. An ID of the wrong kind is a usage error (exit code 2), and a Work Requirement, Task Group or Worker Pool that does not exist exits with code 6.

### yd-application

The `yd-application` command shows the details of the current Application, i.e. the Application represented by the `key` and `secret` being used.

```shell
yd-application [options]
```

It takes no arguments beyond the [Universal Options](#universal-options), and is the quickest way to confirm which Application a set of credentials belongs to.

Key options:
- `--json`/`-J` — emit the Application's details as JSON instead of the readable report

```shell
yd-application --config prod.toml
```

The JSON output contains the Application's properties, plus `portalUrl`, `groups` and `roles`, in alphabetical order. Each of these three is `null` when it can't be determined.

`portalUrl` is derived from the Platform API URL as every Portal link the commands print is: a hostname label that is exactly `api` becomes `portal` (so `https://api.yellowdog.ai` gives `https://portal.yellowdog.ai`), and any other URL, such as `https://host/api`, is used as it is; it is `null` only when the account's name is not known.

`groups` and `roles` are `null` when the Application lacks the permissions required to look them up, which is not a failure, and `groupsAndRoles` is then added, saying `"permission denied"`; an Application in no groups, or with no roles, has `[]` or `{}` (the readable report says `none`); if the lookup fails for any other reason they are `null` too, a warning naming the failure is printed (on stderr, under `--json`), and the command exits with that failure's [exit code](json-output.md) once the rest has been reported.

```shell
yd-application --json
```

```json
{
  "accountId": "000000",
  "accountName": "my-account",
  "allNamespacesReadable": true,
  "features": ["PLATFORM"],
  "groups": ["administrators"],
  "id": "ydid:app:000000:557cc657-4fca-4e00-aa7a-3f6bd59dc6f2",
  "name": "my-app",
  "portalUrl": "https://portal.yellowdog.ai/#/signin?account=my-account",
  "roles": {"administrator": ["GLOBAL"]}
}
```

### yd-variables

The `yd-variables` command reports the processed values of variable substitutions, as JSON. It shows what a specification file would actually see, once the TOML configuration file, the environment, any `YD_VAR_*` variables, any `--variable`/`-v` options and the built-in defaults have all been taken into account, which makes it the quickest way to debug a variable substitution setup.

```shell
yd-variables [options] [<var> ...]
```

Only the named variables are reported if any names are supplied; every variable is reported otherwise. The output is a JSON object keyed by variable name, in alphabetical order. As with `yd-show`, it is preceded by any warnings and followed by `Done`; pass `--quiet`/`-q` to get the JSON alone, for example to pipe it into another program.

A name that isn't the name of a variable reports `null`, with a warning that it is not defined, so the command also answers whether a variable is set at all; a name no variable could have, such as `{{tag}}` or `env:HOME`, is refused. `yd-variables` never contacts the Platform, so it needs no application key or secret: when they are not configured, `key` and `secret` are reported as `null`.

```shell
yd-variables                           # report every variable
yd-variables namespace tag             # report only these two
yd-variables -v instances=5 instances  # report a variable set on the command line
```

```json
{"namespace": "my-namespace", "tag": "my-tag"}
```

The report redacts the values of `key` and `secret`, replacing each with `<REDACTED>`, and shows an inline data client remote (`dataClient.remote`, or a profile's `dataClient.<name>.remote`) with its name, type and provider only, every other parameter's value withheld as `<N parameters redacted>`, because those parameters are where an inline remote's credentials go; a named remote such as `myremote:` is shown as it is.

This applies whether the variables are named or not, and only `--show-secrets` reports their values; naming `key` or `secret` prints a line saying they were redacted. (Naming a variable once reported it in full; it no longer does, so that a caller unable to pass `--show-secrets`, such as the [MCP server](../yellowdog_cli/mcp/README.md)'s tools, cannot ask for a credential by name.)

```shell
yd-variables                 # 'key' and 'secret' are reported as <REDACTED>
yd-variables --show-secrets  # every variable, credentials included
yd-variables key secret      # still <REDACTED>, with a line saying so
yd-variables --show-secrets key secret  # reported in full
```

A reported variable whose value still contains a reference to a variable that is not defined is reported as it stands, and a [warning](variables.md#undefined-variables) naming it is printed ahead of the JSON. The same applies to the configuration's `namespace`, `tag` and `url`; `key` and `secret` are never checked. `--quiet` suppresses the warnings along with `Done`.

```shell
yd-variables -v 'bucket=s3://{{regoin}}' bucket
```

```
WARNING : Variable '{{regoin}}' is not defined, and has been left unsubstituted in 'bucket'
```

A variable that was defined but has been removed by the [unset syntax](variables.md#removing-properties-using-the-unset-suffix) (`{{::}}`, or `{{name::}}` for a `name` that is not defined) is reported as `null` when named, and left out of the full report. So that this can be told apart from a variable that was never defined, a warning also gives the reason, following each `{{name::}}` reference to a variable that was itself unset:

```shell
yd-variables -v 'site={{::}}' -v 'pool={{site::}}-p' pool
```

```
WARNING : Variable 'pool' is unset: 'pool' refers to '{{site::}}', and 'site' is unset; 'site' is '{{::}}', which always unsets it
```

**Variables whose names look like credentials are redacted too, and the command says so.** `key`, `secret` and the inline remotes are the only variables the CLI can *know* hold credentials: it adds them to the substitution table itself when it loads the configuration, and the rclone connection string's format says which part of it is parameters. Beyond them, the report also redacts any variable of your own — defined in `[common.variables]`, via a `YD_VAR_*` environment variable, or with `--variable`/`-v` — whose name contains `secret`, `password`, `passwd`, `token`, `credential` or `private_key`, in any case, and when it does it prints one line ahead of the JSON saying so: `Redacted N variable(s) whose names match 'secret|password|passwd|token|credential|private_key' (case-insensitive); everything else is shown in full. --show-secrets reports all.` (not under `--quiet`, which leaves the JSON alone). As with the others, this applies to a variable named on the command line too, and `--show-secrets` reports them all.

**A variable of your own holding an inline rclone connection string is shown as the data client remotes are.** Whatever it is called, a variable whose value is an inline connection string — `NAME,type=...` or rclone's own `:backend,...` form, with or without a leading `rclone:` and a trailing `:path` — is shown with its prefix, name, type and provider, every other parameter's value (and a trailing path) withheld as `<N parameters redacted>`, so `remote_with_keys = "rclone:S3,type=s3,provider=AWS,access_key_id=...,secret_access_key=...,region=eu-west-2"` is reported as `rclone:S3,type=s3,provider=AWS,<3 parameters redacted>`. A value with a comma in it that has neither form, such as `a,b` or `x,y=z`, is shown in full. When this withholds anything the command says so ahead of the JSON: `Withheld the parameters of N variable(s) holding an inline rclone connection string, keeping its name, type and provider. --show-secrets reports all.` `--show-secrets` reports it in full.

This is a heuristic, and the note is there so that it is not mistaken for a guarantee. `key` on its own is deliberately not in the pattern, so `APP_KEY_DEMO`, an application key's identifier rather than its secret, is shown in full; and a credential held under a name the pattern does not match, such as `APP_CREDS`, is shown in full too. Keeping a credential like that out of a report you send somewhere it will persist is up to you: name the variables you want, or rename the one holding it so that the pattern matches it.

### yd-cloud-info

The `yd-cloud-info` command lists what the YellowDog Platform knows about the cloud providers: their regions and sub-regions (availability zones), their instance types, and the instance types' prices. It answers questions such as which instance types with 4 to 8 vCPUs and at least 16 GiB of RAM are offered in a region, and which of them is cheapest on spot.

```shell
yd-cloud-info [options] <regions|sub-regions|instance-types|prices>
```

The type may be shortened to any unambiguous prefix (e.g. `inst`). Region and sub-region names are matched exactly, so `--region eu-west-2` does not include the Wavelength Zone `eu-west-2-wl1-lon1`; `--name` takes a glob pattern, and a value without wildcards matches the name exactly. Each option applies only to the types listed against it below, and is refused with any other.

Key options:
- `--provider`/`-p <aws|azure|google|oci>` — list only this provider's items; may be repeated (every type)
- `--region <region>` — the region (sub-regions, instance-types, prices); prices need `--region` or `--name`, since every region's prices together are far too many to fetch
- `--sub-region <sub-region>` — the sub-region, which needs `--region` (instance-types, prices); prices for a sub-region include the region's on-demand prices, which apply to every sub-region
- `--name <glob>` — the item's name; for prices, the instance type's (every type)
- `--vcpus <n|n-m>`, `--ram <GiB|GiB-GiB>` — the number of vCPUs, and the RAM in GiB: `n` exactly, `n-m` inclusive, `n-` at least, `-m` at most (instance-types)
- `--arch <x86_64|arm64>` — the processor architecture (instance-types)
- `--usage <spot|on-demand>` — one kind of price only (prices)
- `--os <none|windows>` — prices for this operating system licence, `none` by default (prices, and instance-types with `--prices`)
- `--prices` — add each instance type's on-demand price and lowest spot price in the region, and the sub-region the spot price is found in; needs `--region` (instance-types)
- `--sort <name|vcpus|ram|price|spot|on-demand>[,...]` — `name` (the default) for every type, `vcpus` and `ram` for instance types, `price` for prices, `spot` and `on-demand` for instance types with `--prices`; give several keys, separated by commas, to sort by each in turn (`--sort spot,vcpus`: cheapest first, the smaller of equally priced types first); items without a value for a key come after those with one, with `--reverse` too
- `--count` — print only the number of items
- `--json` — emit the items as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-cloud-info instance-types --region eu-west-2 --vcpus 4-8 --ram 16- --prices --sort spot
yd-cloud-info prices --region eu-west-2 --name 't3.*' --usage spot
yd-cloud-info sub-regions --provider aws --region us-east-1
```

Prices are per hour, as the Platform reports them, in the currency it gives them in.

## Resource Commands

### yd-create

The `yd-create` command creates or updates YellowDog resources, specified in one or more JSON (or Jsonnet) files supplied on the command line. Each file can contain one or more resources.

```shell
yd-create [options] <resource-specification> [<resource-specification> ...]
```

Key options:
- `--match-allowances-by-description`/`-M` — match using the `description` property when updating Allowances
- `--show-keyring-passwords` — display the YellowDog-generated password when creating a Keyring
- `--regenerate-app-keys` — regenerate the application key and secret when updating an Application; required to grant an existing Application access to Keyrings
- `--no-resequence` — process the resources strictly in the order supplied, rather than in dependency order
- `--dry-run`/`-D` — report what would be created or updated, without applying any changes; a template named in an Allowance or Compute Requirement Template that does not exist yet is left as named, since an earlier specification in the same run may create it
- `--hide-user-data` — with `--dry-run`, show the User Data of Compute Source Templates and Compute Requirement Templates as a summary of its size rather than the script in full, as for `yd-provision`; refused without `--dry-run`
- `--jsonnet-dry-run`/`-J` — dry-run Jsonnet processing into JSON
- `--validate` — check every resource specification against its schema and stop, reporting every violation, rather than creating or updating anything (see [Specification Schemas](../README.md#specification-schemas))
- `--json` — emit the resources created, updated or skipped as a JSON array; with `--dry-run`, the processed specifications (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-create my_keyring.json my_compute_templates.jsonnet
```

See [Creating, Updating and Removing YellowDog Resources](resources.md) for the full resource specification reference.

### yd-remove

The `yd-remove` command removes YellowDog resources, specified in one or more JSON (or Jsonnet) files supplied on the command line. Each file can contain one or more resources.

```shell
yd-remove [options] <resource-specification> [<resource-specification> ...]
```

Key options:
- `--ids` — supply YellowDog IDs (YDIDs) as the positional arguments, instead of resource specification files; cannot be combined with `--match-allowances-by-description` or `--jsonnet-dry-run`
- `--match-allowances-by-description`/`-M` — match using the `description` property when removing Allowances
- `--jsonnet-dry-run`/`-J` — dry-run Jsonnet processing into JSON
- `--json` — emit the resources removed or skipped as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-remove my_compute_templates.jsonnet
yd-remove --ids ydid:crt:000000:230e9a42-97db-4d69-aa91-29ff309951b4
```

See [Creating, Updating and Removing YellowDog Resources](resources.md) for details.

### yd-boost

The `yd-boost` command adds hours to a YellowDog Allowance. Allowances are time-based compute budgets that limit how many CPU- or GPU-hours can be consumed by a namespace or application. Boosting is useful when a running job is approaching its limit and needs additional headroom.

```shell
yd-boost [options] <boost-hours> <allowance-ID> [<allowance-ID> ...]
```

The number of hours to add is supplied first, and must be at least 1, followed by the YDID(s) of one or more Allowances to boost. Allowance names are not accepted, and anything that is not an Allowance YDID is a usage error, before anything is boosted; an Allowance ID given more than once is boosted once, with a warning.

Each Allowance is looked up first, so one that does not exist is reported as failed before any is boosted, and the rest are confirmed together, each shown with its description (an Allowance has no name); each one's remaining hours are reported once it has been boosted. An authentication or connection failure stops the command, with that failure's [exit code](json-output.md): the Allowances not yet attempted are reported as skipped rather than each failing in the same way.

Key options:
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-boost 10 ydid:allow:D9C548:...
yd-boost 10 ydid:allow:D9C548:... ydid:allow:D9C548:...
```

See [Allowances](resources.md#allowances) for how Allowances are defined.

## Data Client Commands

These five commands provide direct access to remote data stores via rclone, and never contact the YellowDog Platform API. They accordingly do not accept the `--key`, `--secret`, `--url` or `--pac` [Universal Options](#universal-options); the remainder apply as usual, including `--config`, `--namespace`/`--tag` (which supply the default path prefix) and `--property`.

They share a further set of options — `--remote`/`-r`, `--bucket`/`-b`, `--prefix`/`-p`, `--no-prefix`, `--data-client-profile`/`--profile`, `--upgrade-rclone` and `--which-rclone` — which are described under [Data Client](data-client.md), along with the `[dataClient]` configuration section and named profiles.

A remote path given to `yd-upload` (as `--destination`), `yd-download`, `yd-delete` or `yd-copy` cannot contain a `..` segment: it would climb out of the prefix, or the bucket, past the checks that keep these commands from deleting or syncing over the remote's root or the bucket, and object stores do not resolve it as a local disk does. It is refused as the command line is read (exit 2); to reach a path outside the prefix, use `--no-prefix` or `--bucket`. A `.` segment names the directory it is in, so `.` alone is the configured prefix itself. `yd-ls`, which only reads, accepts `..`, and a local path may contain it anywhere.

A wildcard (`*`, `?`, `[…]`) is matched against the names in the last part of a remote path only. An entry whose name is exactly the path's last part is taken as itself rather than as a pattern, so a file named `data[1].csv` can be listed, downloaded and deleted by its name, and deleting `file[ab].txt` deletes that file alone, not `filea.txt` and `fileb.txt`.

An inline remote's configuration, which carries its credentials, is passed to rclone in a file only you can read, in the system's temporary directory, and removed when the command ends.

### yd-upload

The `yd-upload` command uploads local files or directories to a remote data store.

```shell
yd-upload [options] <local-path> [<local-path> ...]
```

Key options:
- `--recursive`/`-R` — upload directories recursively, preserving the directory structure
- `--flatten` — upload all files in a directory tree to a flat (single-level) remote destination
- `--sync` — synchronise the remote destination to match the local source (implies `--recursive`); files present at the destination but absent locally are deleted; cannot be combined with `--flatten`
- `--destination`/`-d <remote-path>` — override the destination path; supports `{{variable}}` substitution
- `--dry-run`/`-D` — show what would be uploaded, without uploading; with `--sync`, also each remote file that would be deleted
- `--json` — emit the files uploaded as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-upload --recursive my_input_data/
```

A file is uploaded to its own name under the configured prefix, and a directory's contents to a remote directory of the directory's own name. `--destination` names the remote path instead: for a single file, the file's own path (or, ending in `/`, the directory it goes into); for a single directory, the remote directory its contents go into. With more than one local path, `--destination` is a directory, and every file and directory keeps its own name inside it, so `yd-upload -R -d out a/ b/` produces `out/a/` and `out/b/`. A directory given without `--recursive`, `--flatten` or `--sync` is an error.

Before anything is uploaded, `yd-upload` works out where every argument will land, and refuses the whole run (exit 2) if two of them would land on the same remote path — two directories of the same name would merge, and with `--sync` the second would delete what the first uploaded; with `--flatten`, it is two files landing on one path that is refused. A `--sync` whose destination is the remote's root or the configured bucket itself, whose every other file it would delete, is refused in the same way, as `yd-copy`'s is. A failed upload is reported and recorded, and the rest are still attempted; the command then exits 1. Symbolic links are not uploaded (rclone does not follow them), and a warning says how many were left out.

### yd-download

The `yd-download` command downloads files from a remote data store to the local filesystem.

```shell
yd-download [options] <remote-path> [<remote-path> ...]
```

Remote paths support `{{variable}}` substitution (e.g. `'{{tag}}/results.csv'`) and may also contain wildcard characters (`*`, `?`, `[…]`). A wildcard path is expanded against the configured prefix and all matching files and directories are downloaded. The matched names are displayed before the download begins. When a wildcard is used, files are downloaded into the current directory (preserving the names of the matched items) unless `--destination` is specified. `--sync` is supported with wildcards.

Key options:
- `--destination`/`-d <local-path>` — local destination directory (default: mirrors the remote directory name)
- `--into <local-dir>` — local directory to download each remote item into, under its own name (mutually exclusive with `--destination`)
- `--sync` — mirror the remote source to the local destination, deleting local files not present remotely (cannot be combined with `--flatten`)
- `--flatten` — download all files in a remote directory tree to a flat (single-level) local destination, including the directories a wildcard matches; files that share a name within one remote path argument are warned about, and the later one overwrites the earlier
- `--dry-run`/`-D` — show what would be downloaded, without downloading; with `--sync`, also each local file that would be deleted
- `--json` — emit the downloads, or with `--dry-run` the matched items, as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

`--destination` and `--into` answer different questions, which matters when downloading more than one item. `--destination` names the local path that *corresponds to* the remote item, so `yd-download -d out mydir` puts the contents of `mydir` directly into `out`; giving several items one `--destination` therefore merges them. `--into` names a container, so `yd-download --into out mydir otherdir` produces `out/mydir/` and `out/otherdir/`, each keeping its own name. A single file is given its own path the same way: `yd-download --into out a.txt` writes the file `out/a.txt`, and `yd-download a.txt` writes `./a.txt`, while `yd-download -d out a.txt` puts it inside `out`, as `out/a.txt`. With a wildcard the two agree, since a wildcard is expanded into the destination by name either way.

With `--sync`, which deletes local files not in the remote, two remote paths that would be synced into the same local path are refused before anything is downloaded (exit 2), since the second would delete what the first fetched, and so is a sync into the current directory itself (a remote path naming the configured prefix, `/`) unless the current directory is named explicitly with `-d .`. A wildcard is checked by listing its matches, each of which is synced to a path of its own; a wildcard whose matches cannot be listed for the check is never synced unchecked, but reported and recorded as failed while the other remote paths still are.

With `--flatten`, each directory's files are placed directly in the destination, the directory's own name and those of its subdirectories being dropped, so `yd-download --flatten -d flat 'my*'` puts every file of every matched directory in `flat`; a file whose name another flattened file already has is reported with a warning naming both, and the later of the two is the one kept.

A remote path that does not exist, or a wildcard that matches nothing, is an error, as is a remote that cannot be reached; an empty directory downloads nothing, successfully. A failed download is reported and recorded, and the other remote paths (and the other items a wildcard matched) are still attempted; the command then exits 1.

```shell
yd-download 'results_*'
```

### yd-delete

The `yd-delete` command deletes files or directories from a remote data store.

```shell
yd-delete [options] [<remote-path> ...]
```

If no remote paths are specified, `--recursive` deletes the entire configured prefix; without `--recursive` that is refused. The remote's root and the configured bucket itself are never deleted (with `--no-prefix`, the 'prefix' is the bucket, or the root), nor is a wildcard over the remote's root: the command refuses them before deleting anything (exit 2).

Remote paths support `{{variable}}` substitution and may also contain wildcard characters (`*`, `?`, `[…]`). The wildcard is expanded first and the matched names are displayed; confirmation is then requested, and exactly the items shown are deleted — anything that starts matching in the meantime is left alone. A directory, given or matched, requires `--recursive`, and without it is an error. A path that does not exist, or a wildcard that matches nothing, is skipped with a warning, so a deletion of something already gone succeeds. A failed deletion is reported and recorded, the other paths are still attempted, and the command then exits 1.

Key options:
- `--recursive`/`-R` — recursively delete a remote directory tree
- `--dry-run`/`-D` — show what would be deleted, without deleting
- `--json` — emit the deletions, or with `--dry-run` the matched items, as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))
- `--yes`/`-y` — skip confirmation prompts

```shell
yd-delete 'results_*' --dry-run
```

### yd-ls

The `yd-ls` command lists files and directories in a remote data store.

```shell
yd-ls [options] [<remote-path> ...]
```

If no remote paths are specified, the configured prefix is listed.

Remote paths support `{{variable}}` substitution and may also contain wildcard characters (`*`, `?`, `[…]`). Only entries in the configured prefix whose names match the pattern are listed. With `--recursive`, matching directories are expanded into full trees.

A path that does not exist, or a remote that cannot be reached, is an error: it is reported, the other paths are still listed, and the command exits 1. An empty directory, and a wildcard that matches nothing in a directory that exists, are empty listings rather than errors. A path given twice is listed once.

Key options:
- `--recursive`/`-R` — list recursively; output is displayed as a directory tree
- `--long`/`-l` — long listing, showing file sizes and modification timestamps
- `--json` — emit the listing as a JSON array of rclone `lsjson` entries; not with `--long`, since the entries carry sizes and times anyway (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-ls -Rl 'results_*'
```

### yd-copy

The `yd-copy` command copies files or directories between remote data client locations. Both source and destination are remote paths; no local files are involved.

```shell
yd-copy [options] <src-path> <dst-path>
```

`<src-path>` and `<dst-path>` are paths relative to their respective configured `remote:bucket/prefix` base paths. Both support `{{variable}}` substitution. The source remote is configured via the standard data client options; the destination defaults to the same, and is overridden with `--dst-profile` and/or `--dst-prefix`. A source that does not exist is an error, reported before anything is copied, as is a directory given without `--recursive`.

Key options:
- `--dst-profile <name>` — use a named `[dataClient.<name>]` TOML profile for the destination (inherits unset fields from `[dataClient]`)
- `--dst-prefix <prefix>` — override the destination path prefix; pass `''` to place files at the bucket root
- `--sync` — mirror the source directory to the destination, deleting destination files not present in the source (implies `--recursive`); not for a single file, and not to a remote's root or the destination bucket itself
- `--recursive`/`-R` — copy a directory, recursively; a directory given without it is an error
- `--dry-run`/`-D` — show what would happen, without performing any transfers; with `--sync`, also each destination file that would be deleted
- `--json` — emit the files copied as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```bash
# Copy a file to a new location within the same prefix
yd-copy input/data.csv output/data.csv

# Rename a file while copying (destination path does not end with '/')
yd-copy results/output.csv archive/output-{{date}}.csv

# Copy a directory to a different prefix on the same remote
yd-copy -R --dst-prefix staging input/ input/

# Copy results to a named profile (e.g. a separate bucket defined in config.toml)
yd-copy -R --dst-profile production results/ results/

# Sync a directory to a backup profile (deletes destination files not in source)
yd-copy --sync --dst-profile backup data/ data/

# Copy from outside the configured prefix using --no-prefix
yd-copy --no-prefix shared/configs/base.json configs/base.json

# Dry-run to preview what would be copied without transferring anything
yd-copy -R --dry-run input/ output/
```

## Utility Commands

None of `yd-help`, `yd-version`, `yd-format-json` and `yd-jsonnet2json` requires a configuration file or YellowDog credentials, and none accepts the [Universal Options](#universal-options) other than `--no-format`, which `yd-help`, `yd-version` and `yd-jsonnet2json` accept; `yd-doctor` is the exception here, since checking a configuration or a set of credentials means accepting the options that name them, but it never exits on one that is missing or broken — that is what it exists to report.

### yd-doctor

The `yd-doctor` command checks whether this machine, this configuration and these credentials can run the CLI, and reports each check as `OK`, `WARN`, `FAIL` or `SKIP` with a remedy for anything wrong. It is the first thing to run when a command fails unexpectedly, and its output is what to include in a support request: the secret is shown redacted, and an inline data client remote with its name, type and provider only, every other parameter's value withheld.

```shell
yd-doctor [options]
```

It checks, in order:

- the Python version and how the CLI was installed
- the CLI and SDK versions, and whether the SDK imports (one that will not is reported here, and the checks that need it are skipped, rather than the doctor failing to start)
- each optional extra (Jsonnet, Cloud Wizard, Commander, the MCP Server), distinguishing "not installed" from "installed but will not load"
- the rclone version
- the proxy and certificate settings (the proxy row reports `HTTPS_PROXY` and, when PAC is on, the proxy PAC resolves for the API URL, or a `WARN` when it resolves none; the live checks, the PyPI one included, then use that proxy)
- whether a newer CLI is on PyPI
- whether the configuration file loads and follows the configuration schema (a `WARN` naming the first few problems, as every command warns of them; see [Configuration](configuration.md)), and where each of the key, secret, namespace, tag and URL came from
- undefined variable references
- the `.env` file in use
- whether the tag is a legal name

and then, live:

- whether the Platform API is reachable (a `WARN` if it answers with a server error)
- whether the credentials are accepted (naming the Application, its groups and roles, or why not: the key or secret not recognised, the Application without a role, the connection, or a server error)
- whether the configured namespace is readable by the Application
- each data client profile
- whether the data client's remote can be reached at the configured prefix, where the data client commands work (a prefix not created yet is `OK` if its bucket is there, and a bucket that is not there is a `FAIL`)

A check that cannot run says why (`SKIP`) rather than disappearing.

Unlike other commands, `yd-doctor` never exits on a missing or broken configuration: that is reported as a row.

A long detail or remedy wraps at the terminal's width, its continuation lines indented under its own column, only on a terminal; when piped or redirected, and under `--no-format`, every row and every remedy is one line, for grep and pasting.

Key options:
- `--offline` — skip every check that reaches the network (PyPI, the Platform API, the data store)
- `--json`/`-J` — emit the results as a JSON array, one object per check, for scripts
- `--timeout <seconds>` — the budget for each network call (default 10)
- `--quiet`/`-q` — print only the `WARN` and `FAIL` lines and the summary

```shell
yd-doctor                    # everything, against the current configuration
yd-doctor --offline          # no network calls
yd-doctor --json | jq '.[] | select(.status == "FAIL")'
```

The exit code is 1 if any check failed, else 0, so it can gate a script or a CI job.

### yd-help

The `yd-help` command lists all available `yd-*` commands and their purposes, `yd-commander` and `yd-mcp` included, with the extra each command that needs one requires, or `(<extra> extra installed)` where it is installed already, and closes with how to see a command's options and where the documentation is.

```shell
yd-help [--json] [--no-format]
```

The listing is coloured on a terminal, with the command names and the notes on extras picked out; `--no-format`/`--nf` prints it plain, as it is when piped. With `--json` it prints the commands as a JSON array of `{"command", "summary"}`, a command needing an extra adding `"extra"` and `"installed"`, coloured on a terminal unless `--no-format` is given (see [Machine-readable Output and Exit Codes](json-output.md)).

### yd-version

The `yd-version` command reports the versions of the CLI, the YellowDog SDK, Python, and (if installed) Jsonnet, the rclone binary and the MCP SDK used by `yd-mcp` as a table, followed by the CLI's author, licence and documentation link.

```shell
yd-version [options]
```

Key options:
- `--cli`, `--sdk`, `--python`, `--jsonnet`, `--rclone`, `--mcp` — mutually exclusive; each prints just that bare version number, for use in scripts
- `--debug` — print the Python path and executable details, as a second table (note that this differs from `--debug` on other commands, which prints a stack trace on error); with the full report or `--json` only, not with a single-version option
- `--no-format`, `--nf` — print the report, or the `--json` object, without colouring, as it is when piped or redirected
- `--json` — print the versions, author and licence as a JSON object, `null` for a component not installed or whose version could not be read; with `--debug`, the Python executable and path too (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd-version           # report all versions
yd-version --cli     # print the CLI version number only
yd-version --rclone  # print the rclone binary version only
```

The rclone version is detected using the same lookup order as `yd-submit --which-rclone` (system `PATH` first, then the `rclone_api` download cache) without triggering a download; an rclone binary that does not answer within 5 seconds is reported as `unknown`. Each single-version option prints nothing and exits 1 if its component is not installed, or its version could not be read, so a script never takes `Not installed` or `unknown` for a version number. The documentation link is the release's own README, or `main`'s for a development build.

### yd-format-json

The `yd-format-json` command reformats JSON files in place using the CLI's compact JSON encoder (small containers on a single line, larger ones indented). Non-JSON files are ignored.

```shell
yd-format-json [--check] <file.json> [<file.json> ...]
```

Only the layout changes: numbers are written back exactly as they were written (`1.10` stays `1.10`), non-ASCII text is kept rather than escaped, and a file that repeats a key is refused, and left as it is, rather than losing all but one of them. A file is replaced only once its new text is complete, keeping its permissions, so an interruption leaves the original; a file already in this layout is left untouched. `--check` writes nothing, reporting the files that would be reformatted, and exits 1 if there are any, for use in CI. A file that cannot be read, parsed or written is reported on stderr, the others are still processed, and the command exits 1.

```shell
yd-format-json my_file.json my_other_file.json
```

### yd-jsonnet2json

The `yd-jsonnet2json` command converts Jsonnet files to JSON without any additional processing by the CLI (no variable substitution, no property expansion). With a single (non-glob) argument, the resulting JSON is written to stdout, coloured on a terminal unless `--no-format`/`--nf` is given; with multiple arguments or a glob pattern, each file is converted and written to a `<name>.json` file alongside its source.

```shell
yd-jsonnet2json [--yes] [--no-format] <file.jsonnet> [<file.jsonnet> ...]
```

```shell
yd-jsonnet2json my_spec.jsonnet                 # JSON to stdout
yd-jsonnet2json spec_1.jsonnet spec_2.jsonnet   # writes spec_1.json, spec_2.json
yd-jsonnet2json 'specs/*.jsonnet'               # writes a .json file per match
```

Errors go to stderr, so a failed conversion piped to a file never leaves an error message in it, and the command exits 1.

Each `.json` file is replaced whole or not at all, keeping an existing file's permissions. Every file is converted before any is written: an existing `.json` file that already holds what the conversion produces is reported as unchanged and left alone, and the others that would be replaced are listed and confirmed with one prompt, since a `.json` file of that name may be a file of its own rather than an earlier conversion. Declining keeps them and still writes the new files; `--yes`/`-y` overwrites without asking, and without a terminal to answer from the command writes nothing and exits 1, naming `--yes`.

Non-ASCII text is kept as it is rather than escaped. A pattern that matches nothing is reported as such, and a file named twice, or matched by more than one pattern, is converted once.

This is the quickest way to verify that a Jsonnet file is syntactically correct and produces the expected JSON structure. For full variable substitution and property expansion, use `--jsonnet-dry-run` or `--dry-run` on the relevant command instead.

See [Jsonnet Support](jsonnet.md) for installation and usage.

### yd-schema

The `yd-schema` command prints the JSON Schema a specification family must follow, generated from the CLI's own registry and the installed YellowDog SDK: `work-requirement` (what `yd-submit` accepts), `worker-pool` (`yd-provision`), `compute-requirement` (`yd-instantiate`), `resources` (`yd-create`), `node-actions` (`yd-nodeaction`) and `config` (the TOML configuration file every command reads; see [Configuration](configuration.md)). It needs no configuration file and no credentials.

```shell
yd-schema <family>            # print one family's schema as JSON
yd-schema --write <dir>       # write every family's schema, and index.json, to <dir>
yd-schema --check <dir>       # exit 0 if <dir> matches the installed CLI and SDK, else 1
yd-schema --list              # list the family names
```

A schema printed to a terminal is coloured unless it is longer than 5,000 lines (the `resources` family is); `--no-format`/`--nf` prints it plain, as it is when piped or redirected.

Exactly one of a `<family>`, `--write <dir>`, `--check <dir>` or `--list` must be given. `--write` writes `<family>.schema.json` for every family into `<dir>`, plus an `index.json` naming the CLI and SDK versions that generated them, and exits 1 naming the path if `<dir>` cannot be created or written; point an editor's JSON Schema support (VS Code's `json.schemas`, JetBrains' JSON Schema mappings) at the files it writes.

After upgrading the CLI or the SDK, `yd-schema --check <dir>` says whether a written directory is still current — the versions in its index, and every family's file, which must be there and be exactly what the installed CLI and SDK build, so a file edited or missing is reported — and `yd-schema --write <dir>` again refreshes it.

A family printed with `yd-schema <family>` is exactly what `--write` writes for it (coloured when printed to a terminal, unless `--no-format` is given, so piped or redirected it is the same bytes), and each file is replaced whole or not at all. Every schema also accepts a `{{variable}}` substitution, the `{{name::}}` unset form included, wherever a plain value is otherwise expected.
