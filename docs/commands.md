# Command List

<!--ts-->
   * [Universal Options](#universal-options)
   * [Shared Options](#shared-options)
   * [When --follow and --wait Return](#when---follow-and---wait-return)
   * [Naming What a Command Acts On](#naming-what-a-command-acts-on)
   * [yd workrequirement](#yd-workrequirement)
      * [yd workrequirement submit](#yd-workrequirement-submit)
      * [yd workrequirement cancel](#yd-workrequirement-cancel)
      * [yd workrequirement hold](#yd-workrequirement-hold)
      * [yd workrequirement start](#yd-workrequirement-start)
      * [yd workrequirement finish](#yd-workrequirement-finish)
      * [yd workrequirement priority](#yd-workrequirement-priority)
      * [yd workrequirement compare](#yd-workrequirement-compare)
   * [yd taskgroup](#yd-taskgroup)
      * [yd taskgroup priority](#yd-taskgroup-priority)
      * [yd taskgroup compare](#yd-taskgroup-compare)
   * [yd task](#yd-task)
      * [yd task abort](#yd-task-abort)
   * [yd workerpool](#yd-workerpool)
      * [yd workerpool provision](#yd-workerpool-provision)
      * [yd workerpool resize](#yd-workerpool-resize)
      * [yd workerpool shutdown](#yd-workerpool-shutdown)
      * [yd workerpool token](#yd-workerpool-token)
   * [yd computerequirement](#yd-computerequirement)
      * [yd computerequirement instantiate](#yd-computerequirement-instantiate)
         * [Test-Running a Dynamic Template](#test-running-a-dynamic-template)
      * [yd computerequirement resize](#yd-computerequirement-resize)
      * [yd computerequirement stop](#yd-computerequirement-stop)
      * [yd computerequirement start](#yd-computerequirement-start)
      * [yd computerequirement reprovision](#yd-computerequirement-reprovision)
      * [yd computerequirement autoshutdown](#yd-computerequirement-autoshutdown)
      * [yd computerequirement terminate](#yd-computerequirement-terminate)
   * [yd instance](#yd-instance)
      * [yd instance stop](#yd-instance-stop)
      * [yd instance start](#yd-instance-start)
      * [yd instance restart](#yd-instance-restart)
      * [yd instance deprovision](#yd-instance-deprovision)
      * [yd instance terminate](#yd-instance-terminate)
   * [yd node](#yd-node)
      * [yd node action](#yd-node-action)
      * [yd node shutdown](#yd-node-shutdown)
      * [yd node stop](#yd-node-stop)
      * [yd node start](#yd-node-start)
      * [yd node terminate](#yd-node-terminate)
      * [yd node restart](#yd-node-restart)
      * [yd node deprovision](#yd-node-deprovision)
   * [yd worker](#yd-worker)
   * [yd resource](#yd-resource)
      * [yd resource create](#yd-resource-create)
      * [yd resource remove](#yd-resource-remove)
   * [yd allowance](#yd-allowance)
      * [yd allowance boost](#yd-allowance-boost)
   * [yd data](#yd-data)
      * [yd data upload](#yd-data-upload)
      * [yd data download](#yd-data-download)
      * [yd data list](#yd-data-list)
      * [yd data delete](#yd-data-delete)
      * [yd data copy](#yd-data-copy)
   * [yd cloudinfo](#yd-cloudinfo)
      * [yd cloudinfo regions](#yd-cloudinfo-regions)
      * [yd cloudinfo sub-regions](#yd-cloudinfo-sub-regions)
      * [yd cloudinfo instance-types](#yd-cloudinfo-instance-types)
      * [yd cloudinfo prices](#yd-cloudinfo-prices)
   * [Other Commands](#other-commands)
      * [yd list](#yd-list)
      * [yd show](#yd-show)
      * [yd follow](#yd-follow)
      * [yd wait](#yd-wait)
      * [yd application](#yd-application)
      * [yd variables](#yd-variables)
      * [yd init](#yd-init)
      * [yd doctor](#yd-doctor)
      * [yd help](#yd-help)
      * [yd version](#yd-version)
      * [yd format-json](#yd-format-json)
      * [yd jsonnet2json](#yd-jsonnet2json)
      * [yd schema](#yd-schema)
      * [yd completion](#yd-completion)
         * [Names and IDs from the Platform](#names-and-ids-from-the-platform)
   * [Deprecated Commands](#deprecated-commands)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Mon Oct 26 10:25:47 GMT 2026 -->

<!--te-->

The CLI is one command, `yd`. Most of what it does names the object acted on, then what to do to it:

```shell
yd <noun> <verb> [options] [arguments]
```

For example, `yd workrequirement submit wr.json` submits a Work Requirement, and `yd instance terminate <cr-id>.<instance-id>` terminates an Instance. Four nouns have short forms (`wr`, `tg`, `wp` and `cr`), so `yd wr submit wr.json` is the same command.

| Noun | Short form | Its objects | Verbs |
|---|---|---|---|
| [`yd workrequirement`](#yd-workrequirement) | `yd wr` | Work Requirements | `submit`, `cancel`, `hold`, `start`, `finish`, `priority`, `compare`, `list`, `show`, `follow`, `wait` |
| [`yd taskgroup`](#yd-taskgroup) | `yd tg` | Task Groups | `priority`, `compare`, `list`, `show` |
| [`yd task`](#yd-task) | | Tasks | `abort`, `list`, `show` |
| [`yd workerpool`](#yd-workerpool) | `yd wp` | Worker Pools | `provision`, `resize`, `shutdown`, `token`, `list`, `show`, `follow`, `wait` |
| [`yd computerequirement`](#yd-computerequirement) | `yd cr` | Compute Requirements | `instantiate`, `resize`, `stop`, `start`, `reprovision`, `autoshutdown`, `terminate`, `list`, `show`, `follow`, `wait` |
| [`yd instance`](#yd-instance) | | the Instances of Compute Requirements | `stop`, `start`, `restart`, `deprovision`, `terminate`, `list`, `show` |
| [`yd node`](#yd-node) | | Worker Pool Nodes | `action`, `shutdown`, `stop`, `start`, `terminate`, `restart`, `deprovision`, `list`, `show` |
| [`yd worker`](#yd-worker) | | Workers | `list`, `show` |
| [`yd resource`](#yd-resource) | | resources: templates, keyrings, namespaces, users and the rest | `create`, `remove`, `list`, `show` |
| [`yd allowance`](#yd-allowance) | | Allowances | `boost`, `list`, `show` |
| [`yd data`](#yd-data) | | files in a remote data client location | `upload`, `download`, `list`, `delete`, `copy` |
| [`yd cloudinfo`](#yd-cloudinfo) | | the cloud providers' regions, instance types and prices | `regions`, `sub-regions`, `instance-types`, `prices` |

`yd <noun> --help` lists a noun's verbs, and `yd <noun> <verb> --help` gives a verb's options. A verb offers only the options that apply to its object: one that does not, such as `--namespace` on `yd instance terminate`, which takes Instances by ID alone, is refused (exit code 2), as is a target of the wrong kind, such as a Compute Requirement's ID given to `yd instance terminate`.

The `list` and `show` verbs, and the `follow` and `wait` verbs of the Work Requirement, Worker Pool and Compute Requirement nouns, are [`yd list`](#yd-list), [`yd show`](#yd-show), [`yd follow`](#yd-follow) and [`yd wait`](#yd-wait) restricted to the noun's objects: `yd workrequirement list` is `yd list work-requirements`, and `yd workrequirement show` takes Work Requirement IDs.

Since the noun says what a name stands for, the `show`, `follow`, `wait` and `compare` verbs of the Work Requirement, Task Group, Task, Worker Pool and Compute Requirement nouns take names too: a Work Requirement, Worker Pool or Compute Requirement by its name, a Task Group as `wr/tg` and a Task as `wr/tg/task`, each looked up in `--namespace` or the configured namespace, or in another given ahead of it (`namespace/name`, `namespace/wr/tg`), whether the object is live or finished: a Work Requirement's or Compute Requirement's name can be reused once it has finished, so a live one is found if there is one, else the newest. Every name is looked up before anything else is done; a name that finds nothing is reported and exits 6, and a name two live objects share is ambiguous, reported and exits 1, its ID being needed instead. [Naming What a Command Acts On](#naming-what-a-command-acts-on) gives the rules the action commands share.

`yd show`, `yd follow` and `yd wait` themselves take IDs alone, not knowing the type. Those four commands remain, for any type of object, as do the [other commands](#other-commands), which act on no particular object: each is `yd <command>`, such as `yd list` or `yd doctor`. `yd` alone, or `yd help`, lists them all.

The deprecated `yd-*` commands, such as `yd-submit` and `yd-list`, still work, with a warning, until a future release: see [Deprecated Commands](#deprecated-commands) for what replaces each.

Help is available for every command with the `--help` or `-h` option. The two tables below describe the options shared across commands; the sections that follow describe each command individually, along with its own command-specific options.

## Universal Options

These options are accepted by every `yd` command except `yd commander`, `yd mcp`, `yd completion`, `yd init`, `yd help`, `yd version`, `yd format-json`, `yd jsonnet2json` and `yd schema`, none of which requires a configuration file or YellowDog credentials; of those, `yd init`, `yd help`, `yd schema`, `yd version` and `yd jsonnet2json` accept `--no-format`. They are not repeated in the individual command sections below. A command's `--help` lists them last, under `universal options`, and its usage line shows them as `[universal options]`.

The five [`yd data`](#yd-data) verbs are a partial exception: they accept all of these except `--key`, `--secret`, `--url` and `--pac`, because they talk only to the remote data store and never to the YellowDog Platform API.

| Option | Effect |
|---|---|
| `--config <config_file.toml>`, `-c` | Configuration file in TOML format; the default is `config.toml` in the current directory, else your own, `~/.config/yellowdog/config.toml` (`$XDG_CONFIG_HOME/yellowdog/config.toml` where that is set; see [Configuration](configuration.md)) |
| `--no-config`, `--nc` | Ignore the contents of any TOML configuration file, even one named using `--config` |
| `--key <app-key-id>`, `-k` | The Application key ID |
| `--secret <app-key-secret>`, `-s` | The Application key secret |
| `--url <url>`, `-u` | The YellowDog Platform API URL (defaults to `https://api.yellowdog.ai`) |
| `--property <section.key=value>` | Override a single TOML configuration property; can be supplied multiple times — see [Overriding Arbitrary TOML Properties on the Command Line](configuration.md#overriding-arbitrary-toml-properties-on-the-command-line) |
| `--env-override` | Values in a `.env` file override values in the environment, as `YD_ENV_OVERRIDE` also makes them — see [Support for .env Files](configuration.md#support-for-env-files) |
| `--quiet`, `-q` | Suppress (non-error, non-interactive) status and progress messages |
| `--no-format`, `--nf` | Disable colouring and text wrapping in command output |
| `--print-pid`, `--pp` | Include the process ID of the CLI invocation alongside the timestamp in log messages; useful for disambiguating interleaved output when running multiple commands in parallel |
| `--debug` | Display the Python stack trace on error, which can be useful for support purposes. Also shows the startup preamble, each line marked `DEBUG`: where the configuration, the variable substitutions and the `.env` variables were loaded from, the Platform API URL when it is not the default, the HTTPS proxy in use, and the certificates bundle when one is set. The whole preamble is suppressed by default |
| `--pac` | Enable PAC (proxy auto-configuration) support — see [HTTPS Proxy Support](configuration.md#https-proxy-support) |
| `--docs` | Provide a link to the documentation for this version of the CLI |

Note that `yd version` also accepts `--debug`, but reports the Python path and executable details rather than a stack trace.

A table longer than 2,000 lines, or JSON longer than 5,000 lines, is printed without colour, whether or not `--no-format` is used, since colouring output that long takes a noticeable time.

For `yd workrequirement submit`, `yd workerpool provision`, and `yd computerequirement instantiate`, `--quiet` prints **only the YDID** of the created entity to stdout, making those commands directly composable in shell scripts:

```bash
WR_ID=$(yd workrequirement submit --quiet)
yd workrequirement follow "$WR_ID"
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
| `--follow`, `-f` | Follow the relevant event stream after the command has acted: until the entity finishes, or, after an action that leaves it alive, until it has done what was asked of it. [When `--follow` and `--wait` Return](#when---follow-and---wait-return) gives the end for each command. |
| `--sort <name\|created\|status\|namespace>[,...]` | Order in which listed and interactively-selected entities are sorted: `name` (default), `created` (creation time, earliest first), `status` (status name), or `namespace`. Give several keys, separated by commas, to sort by each in turn, e.g. `--sort status,created`; the name always breaks any tie that remains |
| `--reverse` | Reverse (descending) the whole order `--sort` gives |
| `--jsonnet-dry-run`, `-J` | Dry-run Jsonnet processing into JSON — see [Checking Jsonnet Processing](jsonnet.md#checking-jsonnet-processing) |

All destructive commands require user confirmation before taking effect, unless the `--yes` option is supplied.

The `yd data` verbs share a further set of options (`--remote`, `--bucket`, `--prefix`, `--no-prefix` and `--data-client-profile`), which are described under [Data Client](data-client.md).

## When `--follow` and `--wait` Return

`--follow` prints the events of what a command acted on, and returns when the action is done. For an action that finishes its object (a Work Requirement completing, a Worker Pool shutting down, a Compute Requirement terminated) that is when the Platform closes its event stream. For an action that leaves the object alive, whose stream never closes, the command watches for the state the action asked for. `--wait`, on the two Compute Requirement verbs that take it, waits for the same state without printing the events, and with `--timeout <seconds>` gives up after that long, exiting 1.

A Compute Requirement is *settled* when it is `RUNNING`, as many of its Instances are `RUNNING` as its target asks for, and none is starting, stopping or terminating.

| Command | `--follow` returns when | `--wait` |
|:---|:---|:---|
| `yd workrequirement submit` | the Work Requirement has finished (`COMPLETED`, `FAILED` or `CANCELLED`); `--progress` shows a progress bar instead of the events, and `-E` exits 1 if it did not complete | — |
| `yd workrequirement cancel` | each Work Requirement cancelled has finished (Tasks cancelled on their own are not followed) | — |
| `yd workrequirement hold` | each Work Requirement is `HELD` | — |
| `yd workrequirement start`, `finish` | each Work Requirement has finished | — |
| `yd workerpool provision` | the Worker Pool has shut down (`SHUTDOWN` or `TERMINATED`), which its idle timeouts bring about | — |
| `yd workerpool resize` | the pool's Compute Requirement is settled again, having left it for the new size | — |
| `yd workerpool shutdown` | each Worker Pool has shut down | — |
| `yd computerequirement instantiate` | the Compute Requirement is terminated, as nothing else closes its stream (Ctrl-C to stop following) | — |
| `yd computerequirement resize`, `reprovision` | each Compute Requirement is settled | as for `--follow`, without the events |
| `yd computerequirement stop`, `yd instance stop`, `yd node stop` | nothing is changing, having changed: the Compute Requirement `RUNNING` or `STOPPED`, with no Instance starting, stopping or terminating | — |
| `yd computerequirement start`, `yd instance start`, `yd node start` | each Compute Requirement is settled | — |
| `yd instance restart`, `yd node restart` | each Compute Requirement is settled again, having left it | — |
| `yd instance deprovision`, `yd node deprovision` | each Compute Requirement is settled at its new, reduced target | — |
| `yd computerequirement terminate` | each Compute Requirement is terminated | — |
| `yd instance terminate`, `yd node terminate` | nothing is changing, having changed: the Instances gone, and any the Compute Requirement starts in their place running | — |
| `yd node action` | every node's action queue is `EMPTY` or `FAILED`, polled rather than streamed; `--timeout` stops it first, exiting 1 | — |
| `yd follow` (and the nouns' `follow`) | every stream has closed, its object finished | — |
| `yd wait` (and the nouns' `wait`) | — | every object is in a terminal state: `COMPLETED`, `FAILED` or `CANCELLED` for a Work Requirement, `SHUTDOWN` or `TERMINATED` for a Worker Pool, `TERMINATED` for a Compute Requirement; `--timeout` stops it first |

With `--auto-follow-compute-requirements`/`-a` (on `yd workerpool provision`, `resize` and `shutdown`, and `yd follow`), a Provisioned Worker Pool's Compute Requirement is followed beside the pool, its stream ending by the same rule. A stream that drops is reconnected; one that cannot be followed is reported and the command exits with that failure's code (see [Machine-readable Output and Exit Codes](json-output.md)). Ctrl-C stops following without undoing what was done.

## Naming What a Command Acts On

The commands that act on Work Requirements, Task Groups, Tasks, Worker Pools and Compute Requirements share one set of rules for the targets they are given; each command's section adds what is particular to it.

- **A YellowDog ID** (YDID) names its object in whatever namespace it is in.
- **A name** is looked up in the configured namespace (or `--namespace`), unless it is given with its own: `namespace/name`. A Task Group is named `wr/tg`, or `namespace/wr/tg`, and a Task `wr/tg/task`.
- **A reused name.** A Work Requirement's or Compute Requirement's name can be used again once the first has finished, so a name is matched to the object of that name in the state the action applies to: the `HELD` Work Requirement for `start`, the `RUNNING` one for `hold`, an unfinished one for `cancel`. If two objects of the name are in that state, the name is ambiguous, reported, and exits 1; give the ID instead. The `show`, `follow`, `wait` and `compare` verbs take the live object of the name if there is one, else the newest.
- **A glob pattern** (`*`, `?` or `[...]`) is matched against the names in the namespace, by the CLI, and selects every object it matches that is in the state the action applies to; a name without a wildcard matches exactly, so `'proj-*'` rather than `proj-`. The matches are confirmed as a selection by namespace and tag is, and `--interactive` offers them to choose from. `yd list <type> --name '<pattern>'` shows what a pattern matches before acting on it.
- **No targets** at all, on the commands that allow it, selects by the namespace and tag: Work Requirements and Compute Requirements carrying the tag, and Worker Pools whose names include it.
- **The order.** Targets are resolved in the order given, each once (an object named twice, by name and by ID, is acted on once), and confirmed together, `--yes` skipping the confirmation. Each command then acts on them in the order its section gives (`yd workrequirement cancel` the Work Requirements before the Tasks, the Compute Requirement verbs the Compute Requirements before the Instances).
- **What cannot be acted on** is reported and the rest go ahead: a target that does not exist is a failure (exit 6 if every failure is one), one in a state the action does not apply to is skipped with a warning. A failure every later request would repeat (the credentials refused, the Platform unreachable) stops the command, the targets not yet attempted being reported as skipped, and it exits with that failure's code (see [Machine-readable Output and Exit Codes](json-output.md)).

How each command takes its targets:

| Command | No targets | Glob patterns |
|:---|:---|:---|
| `yd workrequirement cancel`, `start`, `hold`, `finish` | the namespace and tag | yes, not mixed with names or IDs |
| `yd workrequirement priority`, `yd taskgroup priority` | refused | no |
| `yd task abort` | the namespace and tag | no |
| `yd workerpool shutdown` | the namespace and tag | yes, not mixed with names or IDs |
| `yd workerpool token` | refused | yes, mixed with names and IDs as wished |
| `yd workerpool resize`, `yd computerequirement resize` | refused (one target) | no |
| `yd computerequirement stop`, `start`, `reprovision`, `terminate`, `autoshutdown` | the namespace and tag | yes, not mixed with names or IDs |
| `yd instance` verbs, `yd node` verbs | refused: Instances (`cr_id.instance_id`) or Node IDs only | no |
| `yd allowance boost` | refused: Allowance IDs only | no |

## yd workrequirement

Work Requirements: `yd workrequirement`, or `yd wr` for short.

| Verb | What it does | Replaces |
|---|---|---|
| [`submit`](#yd-workrequirement-submit) | Submit a Work Requirement, or add to one | `yd-submit` |
| [`cancel`](#yd-workrequirement-cancel) | Cancel Work Requirements | `yd-cancel` |
| [`hold`](#yd-workrequirement-hold) | Hold (pause) running Work Requirements | `yd-hold` |
| [`start`](#yd-workrequirement-start) | Start held Work Requirements | `yd-start` |
| [`finish`](#yd-workrequirement-finish) | Finish Work Requirements | `yd-finish` |
| [`priority`](#yd-workrequirement-priority) | Change the priority of Work Requirements and Task Groups | `yd-priority` |
| [`compare`](#yd-workrequirement-compare) | Compare a Work Requirement against Worker Pools | `yd-compare` |
| `list` | `yd list work-requirements` |  |
| `show` | `yd show`, for Work Requirement names or IDs |  |
| `follow` | `yd follow`, for Work Requirement names or IDs |  |
| `wait` | `yd wait`, for Work Requirement names or IDs |  |

### yd workrequirement submit

The `yd workrequirement submit` command submits a new Work Requirement, according to the Work Requirement definition found in the `workRequirement` section of the TOML configuration file and/or the specification found in a Work Requirement JSON (or Jsonnet) document.

```shell
yd workrequirement submit [options] [<work-requirement-specification-file>]
```

Once submitted, the Work Requirement will appear in the **Work** tab in the YellowDog Portal.

Key options:
- `--follow`/`-f` — report on Tasks as they conclude, and don't return until the Work Requirement has finished
- `--progress` — as `--follow`, but showing a single updating progress bar of completed and failed Tasks against the total, rather than per-task event messages
- `--exit-on-failure`/`-E` — when following, exit with code 1 if the Work Requirement ends in a `FAILED` or `CANCELLED` state (or its final status cannot be fetched), or, if it could not be followed to its end (its event stream lost, say) and has not finished, with the code of that failure, since its outcome is not known; needs `--follow` or `--progress`
- `--hold`/`-H` — submit the Work Requirement in the `HELD` (paused) state; it can later be started with `yd workrequirement start`. It is held before any Task is added, and if holding it fails it is cancelled, as for any failure part-way through a submission
- `--empty`/`-e` — submit a Work Requirement with no Task Groups, to be populated later; it cannot be combined with a specification file, `--csv-file`, `--process-csv-only`, `--task-count` or `--task-group-count`, and a specification or CSV file named in the configuration (`workRequirementData`, `csvFiles`) is refused with it too
- `--add-to`/`-A <name-or-id>` — add Task Groups and/or Tasks to an existing Work Requirement, which must be `RUNNING` or `HELD`; a name is looked up in the configured namespace unless given as `namespace/name`. Refused with `--hold` and `--empty` (see [Adding Task Groups and Tasks to an Existing Work Requirement](work-requirements.md#adding-task-groups-and-tasks-to-an-existing-work-requirement))
- `--task-type`/`-T <type>` — the Task Type to use
- `--task-count`/`-C <n>`, `--task-group-count`/`-G <n>` — submit `n` copies of a single Task or Task Group, overriding `taskCount` or `taskGroupCount` in the specification
- `--csv-file`/`-V <data.csv>` — read Task data from one or more CSV files; `--process-csv-only`/`-p` outputs the intermediate JSON specification without submitting, and needs a CSV file, given or configured
- `--task-batch-size`/`-b <n>` — the batch size for Task submission, between 1 and 10,000
- `--parallel-batches`/`-l <n>` — the maximum number of Task batches uploaded in parallel (default: the configuration's `parallelBatches`, else `1`, i.e. sequential); once a batch fails, those not yet started are not submitted
- `--pause-between-batches`/`-P [<seconds>]` — pause between batch submissions; with no interval, user input is required to advance. Ignored, with a warning, when batches are uploaded in parallel
- `--overwrite`/`-O` — overwrite a file that already exists at the remote destination; by default, existing files are skipped
- `--json-raw`/`-j <file>` — submit a 'raw' JSON Work Requirement file; it cannot be combined with a specification file, `--add-to`, `--csv-file`, `--process-csv-only`, `--task-count`, `--task-group-count`, `--empty`, `--validate`, `--task-type`, `--overwrite` or `--content-path`, none of which applies to it
- `--content-path`/`-F <directory>` — the directory in which files for upload, user data, or CSV data are found; a relative path in the specification (a `taskDataFile`, a CSV file) is found there, while the specification file itself is always named from the current directory
- `--dry-run`/`-D` — inspect the Work Requirement, Task Groups and Tasks that would be submitted, in JSON format
- `--validate` — check the specification file against its schema and stop, reporting every violation, rather than submitting it (see [Checking Specifications](schemas.md#checking-a-file-before-submitting-it))
- `--json` — emit a JSON object naming the created Work Requirement (`id`, `name`, `namespace` and `type`); with `--dry-run`, the processed specification; refused with `--progress`, which writes its own output (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd workrequirement submit my_work_requirement.json --follow
```

When `--quiet` (`-q`) is used, only the YDID of the submitted Work Requirement is printed to stdout, with all other output suppressed. This is convenient for scripting:

```bash
WR_ID=$(yd workrequirement submit --quiet)
yd workrequirement follow "$WR_ID"
```

To force a download or upgrade of the rclone binary used by the Data Client, run `yd workrequirement submit --upgrade-rclone`. To report the path and version of the binary that would be used, without downloading anything, run `yd workrequirement submit --which-rclone`. Both options are also accepted by the `yd data` verbs themselves.

The specification file may also be supplied using the deprecated `--work-requirement`/`-r` option; the positional argument is preferred.

See [Work Requirements](work-requirements.md) for the full specification reference, [Specifying Work Requirements using CSV Data](work-requirements.md#specifying-work-requirements-using-csv-data) for the CSV options, and [Adding Task Groups and Tasks to an Existing Work Requirement](work-requirements.md#adding-task-groups-and-tasks-to-an-existing-work-requirement) for `--add-to`.

### yd workrequirement cancel

The `yd workrequirement cancel` command cancels any active Work Requirements, including any pending Task Groups and the Tasks they contain.

```shell
yd workrequirement cancel [options] [<work-requirement-name-or-ID> ...]
```

The namespace and tag (configured, or given with `--namespace`/`-n` and `--tag`/`-t`) are used to identify which Work Requirements to cancel. Alternatively, specific Work Requirement names or YDIDs (or individual Task YDIDs) can be supplied as positional arguments.

A YDID names its Work Requirement or Task in whatever namespace it is in. A name is looked up in the configured `namespace` unless it is given as `namespace/name`; since a name can be reused, the Work Requirement of that name that can still be cancelled is chosen, and if there are two or more, the name is ambiguous and its YDID must be given instead.

Explicit names and IDs are resolved in the order given, and are confirmed together; the Work Requirements are then cancelled before the Tasks. One that has already finished, or a Task that has, is skipped with a warning. If a request fails because the Application's credentials are not accepted, or the platform cannot be reached, nothing further is attempted, the remaining items are reported as skipped, and the command exits with that failure's code (see [Machine-readable Output and Exit Codes](json-output.md)).

A name argument can also be a glob pattern (`*`, `?`, `[...]`), matched client-side against Work Requirement names within the namespace (a name without wildcards matches exactly, so use `*` for partial matches); glob patterns cannot be mixed with literal names or YDIDs in the same command. Use `yd list work-requirements --name 'myproject-*'` to preview the matches first.

By default, any Tasks that are currently running on Workers will continue to run to completion or until they fail. A Work Requirement that is already `CANCELLING` is left alone unless `--abort` is given, in which case it is cancelled again to abort its executing Tasks.

Key options:
- `--abort`/`-a` — instruct running Tasks to abort immediately, rather than running to completion
- `--dry-run`/`-D` — show the Work Requirements (and Tasks) that would be cancelled, whether matched or named, without cancelling anything
- `--json` — emit the actions taken, or with `--dry-run` what would be taken, as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd workrequirement cancel 'myproject-*' --dry-run
```

### yd workrequirement hold

The `yd workrequirement hold` command holds (pauses) `RUNNING` Work Requirements.

```shell
yd workrequirement hold [options] [<work-requirement-name-or-ID> ...]
```

It can optionally be supplied with a list of the names and/or YDIDs of the specific Work Requirements to hold, otherwise the `namespace` and `tag` are used to generate a list of candidate requirements. Names, YDIDs and glob patterns are handled as [`yd workrequirement start`](#yd-workrequirement-start) handles them, with `RUNNING` in place of `HELD`.

Key options:
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd workrequirement hold my-analysis-run
```

A held Work Requirement is restarted using `yd workrequirement start`.

### yd workrequirement start

The `yd workrequirement start` command starts Work Requirements that are in the `HELD` (paused) state.

```shell
yd workrequirement start [options] [<work-requirement-name-or-ID> ...]
```

It can optionally be supplied with a list of the names and/or YDIDs of the specific Work Requirements to start, otherwise the `namespace` and `tag` are used to generate a list of candidate requirements.

A YDID names its Work Requirement in whatever namespace it is in. A name is looked up in the configured `namespace` unless it is given as `namespace/name`; since a name can be reused, the `HELD` Work Requirement of that name is chosen, and if there are two or more, the name is ambiguous and its YDID must be given instead. A name may also be a glob pattern (e.g. `'proj-*'`), which selects every `HELD` Work Requirement whose name it matches, to be confirmed (or chosen from, with `--interactive`) as the candidates found by `namespace` and `tag` are; glob patterns cannot be mixed with explicit names or IDs.

Explicit names and IDs are handled in the order given, and are confirmed together. One that is not `HELD` is skipped with a warning naming its state. If a request fails because the Application's credentials are not accepted, or the platform cannot be reached, nothing further is attempted, the remaining items are reported as skipped, and the command exits with that failure's code (see [Machine-readable Output and Exit Codes](json-output.md)).

Key options:
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd workrequirement start my-analysis-run --follow
yd workrequirement start 'analysis-*'
```

Work Requirements are submitted in the `HELD` state using `yd workrequirement submit --hold`; `yd workrequirement hold` returns a `RUNNING` one to it.

### yd workrequirement finish

The `yd workrequirement finish` command moves Work Requirements into the `FINISHING` state, meaning that the requirements will be allowed to conclude but that no new Tasks can be added.

```shell
yd workrequirement finish [options] [<work-requirement-name-or-ID> ...]
```

As with `yd workrequirement start` and `yd workrequirement hold`, specific names and/or YDIDs can be supplied, otherwise the `namespace` and `tag` are used to generate the list of candidates. Names, YDIDs and glob patterns are handled as [`yd workrequirement start`](#yd-workrequirement-start) handles them, with `RUNNING` or `HELD` in place of `HELD`: a Work Requirement that is already `FINISHING` is left out of the candidates, and skipped with a warning if named. With `--follow`, only the Work Requirements this command finished are followed.

Key options:
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd workrequirement finish my-analysis-run
```

### yd workrequirement priority

The `yd workrequirement priority` command changes the priority of Work Requirements and Task Groups after they have been submitted. Higher priority acquires Workers ahead of lower priority (see [`priority`](property-dictionary.md)), so raising a Task Group's priority favours that stage of a run, and lowering a Work Requirement's lets others go first.

```shell
yd workrequirement priority [options] <priority> <target> [<target> ...]
```

The new priority, any finite number (negative ones included), comes first, followed by one or more targets, read as [`yd task abort`](#yd-task-abort) reads them:

- a Work Requirement name, `<namespace>/<wr-name>` or YDID
- a Task Group YDID, `<wr-name>/<tg-name>` or `<namespace>/<wr-name>/<tg-name>`

Targets are handled in the order given, each once, and confirmed together, the confirmation showing each one's current and new priority. A target that does not exist, or whose name is ambiguous, is reported as failed; one in a Work Requirement that has finished (`COMPLETED`, `CANCELLED` or `FAILED`), or already at the priority, is skipped with a warning. The Platform takes a Work Requirement whole, so the targets in one Work Requirement are changed together, in one update to a copy fetched just before it is sent: a change made to the Work Requirement since the targets were found is kept. An authentication or connection failure stops the command, with that failure's [exit code](json-output.md), and the targets not yet attempted are reported as skipped.

Key options:
- `--dry-run`/`-D` — report each target's current and new priority without changing anything
- `--json` — emit the actions taken, or with `--dry-run` what would be taken, as a JSON array, each with its `previousPriority` and `priority` (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd workrequirement priority 10 my-analysis-run
yd workrequirement priority 5 my-analysis-run/render my-analysis-run/encode
yd workrequirement priority -1 ydid:workreq:000000:...
```

### yd workrequirement compare

The `yd workrequirement compare` command takes a Work Requirement and one or more Worker Pools, each by name or ID, and compares every Task Group in the Work Requirement against the available Nodes/Workers in the Worker Pool(s). To compare a single Task Group, use [`yd taskgroup compare`](#yd-taskgroup-compare).

```shell
yd workrequirement compare [options] <work-requirement-name-or-ID> <provisioned-worker-pool-name-or-ID> ...
```

The command checks if the **Run Specification** of a Task Group matches the properties of the Worker Pools and their registered Nodes and Workers, meaning there are Workers in the Worker Pool that could be claimed by the Task Group and that the Worker Pool would be a candidate for scaling up to meet the demands of the Task Group.

A detailed matching report showing the comparison against each specific property is created, which can be used to determine which properties are preventing a Worker Pool match.

A Worker Pool that cannot be compared — its Compute Requirement or its Nodes cannot be fetched — is reported as `FAILED` with the reason, and the other Worker Pools and Task Groups are still compared; the command then exits non-zero, with the failure's [exit code](json-output.md) when every failure had the one cause. An authentication or connection failure stops the comparison. A Task Group or Work Requirement that does not exist exits 6, and a Work Requirement with no Task Groups is reported with a warning. A Configured Worker Pool cannot be compared, and is refused before any comparison (exit 1).

By default every Node registered to a Worker Pool is included in the comparison, whatever its state. The `--running-nodes-only` option restricts the comparison to Nodes in the `RUNNING` state, which gives a more accurate picture of current capacity when a pool contains Nodes that are still provisioning or have been terminated.

Key options:
- `--namespace` — the namespace the names are looked up in; the configured one if not given
- `--running-nodes-only` — compare against Nodes in the `RUNNING` state only
- `--json` — emit the comparison as a JSON array, one object per Worker Pool compared with each Task Group (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd workrequirement compare ydid:workreq:000000:83587010-5e26-4174-92a7-c7cc2612638d ydid:wrkrpool:000000:3666e4c5-382e-4512-a2c7-33dbb839f75
yd workrequirement compare nightly-run gpu-pool
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

## yd taskgroup

Task Groups: `yd taskgroup`, or `yd tg` for short.

| Verb | What it does | Replaces |
|---|---|---|
| [`priority`](#yd-taskgroup-priority) | Change the priority of Task Groups and Work Requirements | `yd-priority` |
| [`compare`](#yd-taskgroup-compare) | Compare a Task Group against Worker Pools | `yd-compare` |
| `list` | `yd list task-groups` |  |
| `show` | `yd show`, for Task Group IDs, or names as `wr/tg` |  |

### yd taskgroup priority

The `yd taskgroup priority` command is [`yd workrequirement priority`](#yd-workrequirement-priority) by another name: it takes the same arguments, Task Groups and Work Requirements alike, and does the same.

```shell
yd taskgroup priority [options] <priority> <target> [<target> ...]
```

```shell
yd taskgroup priority 5 my-analysis-run/render
```

### yd taskgroup compare

The `yd taskgroup compare` command compares one Task Group against one or more Worker Pools, as [`yd workrequirement compare`](#yd-workrequirement-compare) compares each of a Work Requirement's Task Groups, and reports in the same way.

```shell
yd taskgroup compare [options] <wr/task-group-name-or-ID> <provisioned-worker-pool-name-or-ID> ...
```

Key options:
- `--namespace` — the namespace the names are looked up in; the configured one if not given
- `--running-nodes-only` — compare against Nodes in the `RUNNING` state only
- `--json` — emit the comparison as a JSON array, one object per Worker Pool compared (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd taskgroup compare ydid:taskgrp:000000:83587010-5e26-4174-92a7-c7cc2612638d:1 ydid:wrkrpool:000000:3666e4c5-382e-4512-a2c7-33dbb839f75
```

## yd task

Tasks.

| Verb | What it does | Replaces |
|---|---|---|
| [`abort`](#yd-task-abort) | Abort running Tasks | `yd-abort` |
| `list` | `yd list tasks` |  |
| `show` | `yd show`, for Task IDs, or names as `wr/tg/task` |  |

### yd task abort

The `yd task abort` command aborts Tasks that are currently running, without cancelling the Work Requirements that contain them.

```shell
yd task abort [options] [<target> ...]
```

With no arguments, the user interactively selects the Work Requirements to target, and then which Tasks within those Work Requirements to abort.

Aborting a Task sends `SIGTERM` to the Task's subprocess, giving it an opportunity to clean up. The Task is then reported as `FAILED`. If the Task Type has an `abort` clause configured in the Agent's `application.yaml`, that script takes over abort handling entirely.

The namespace and tag (configured, or given with `--namespace`/`-n` and `--tag`/`-t`) are used to identify which Work Requirements to list for selection. Alternatively, targets can be supplied as positional arguments, each of which can be:

- a Task YDID, to abort that Task, whatever its state
- a Work Requirement name, `<namespace>/<wr-name>` or YDID, to abort all running Tasks within it (a YDID is found in whatever namespace it belongs to)
- a Task Group YDID, `<wr-name>/<tg-name>` or `<namespace>/<wr-name>/<tg-name>`, to abort running Tasks in a specific Task Group

A running Task is one that is `DOWNLOADING`, `EXECUTING` or `UPLOADING`; a Task that has yet to start, or has finished, is left alone.

`<a>/<b>` is read as a Task Group `<b>` in Work Requirement `<a>` if there is one, and otherwise as Work Requirement `<b>` in namespace `<a>`. A Work Requirement name is looked up as for `yd workrequirement cancel`: since a name can be reused, an unfinished Work Requirement of that name is chosen, and if there are two or more, the name is ambiguous and its YDID must be given instead (for `<a>/<b>`, the namespace reading is still tried).

Targets are handled in the order given, except that the Task YDIDs are confirmed together, where the first of them appears. A repeated target is ignored, and a Task included by more than one target is aborted once. If an attempt fails because the credentials are rejected or the platform cannot be reached, nothing further is attempted, the remaining Tasks and targets are reported as skipped, and the command exits with that failure's code (see [Machine-readable Output and Exit Codes](json-output.md)).

Unless `--yes`/`-y` is given, the Tasks to be aborted are listed and confirmed before anything is aborted. With `--yes`/`-y`, the running Tasks are aborted without prompting: those of the targets given or, with none, of every unfinished Work Requirement the namespace and tag select.

Key options:
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd task abort my-analysis-run/task-group-1
```

## yd workerpool

Worker Pools: `yd workerpool`, or `yd wp` for short.

| Verb | What it does | Replaces |
|---|---|---|
| [`provision`](#yd-workerpool-provision) | Provision a Worker Pool | `yd-provision` |
| [`resize`](#yd-workerpool-resize) | Resize a Worker Pool | `yd-resize` |
| [`shutdown`](#yd-workerpool-shutdown) | Shut down Worker Pools | `yd-shutdown` |
| [`token`](#yd-workerpool-token) | Refresh or regenerate the tokens of Configured Worker Pools | `yd-token` |
| `list` | `yd list worker-pools` |  |
| `show` | `yd show`, for Worker Pool names or IDs, with `--show-token`, `--show-source-report` and `--show-exhaustion` |  |
| `follow` | `yd follow`, for Worker Pool names or IDs |  |
| `wait` | `yd wait`, for Worker Pool names or IDs |  |

### yd workerpool provision

The `yd workerpool provision` command provisions a new Worker Pool according to the specifications in the `workerPool` section of the TOML configuration file and/or in a Worker Pool JSON (or Jsonnet) document.

```shell
yd workerpool provision [options] [<worker-pool-specification-file>]
```

Once provisioned, the Worker Pool will appear in the **Workers** tab in the YellowDog Portal, and its associated Compute Requirement will appear in the **Compute** tab.

Key options:
- `--target`/`-T <n>` — override the `targetInstanceCount` from the specification or configuration; a `maxNodes` lower than it is raised to match, and a count below `minNodes` is raised to `minNodes`
- `--content-path`/`-F <directory>` — the directory in which the User Data files the configuration's `[workerPool]` section names (`userDataFile`, `userDataFiles`) are found, in place of the configuration file's directory; a Worker Pool specification takes its User Data as `userData` alone, and the specification file itself is always named from the current directory
- `--auto-follow-compute-requirements`/`-a` — when following, also follow the associated Compute Requirement; refused without `--follow`
- `--dry-run`/`-D` — inspect the Worker Pool specification that would be submitted, in JSON format
- `--hide-user-data` — with `--dry-run`, show the User Data as a summary of its size, e.g. `<user data: 4,812 characters, 131 lines>`, rather than the script in full; refused without `--dry-run`
- `--report`/`-r` — report on a test run of the Worker Pool's Compute Requirement Template, without provisioning (see [Test-Running a Dynamic Template](#test-running-a-dynamic-template))
- `--validate` — check the specification file against its schema and stop, reporting every violation, rather than provisioning it (see [Checking Specifications](schemas.md#checking-a-file-before-submitting-it))
- `--json` — emit a JSON object naming the created Worker Pool (`id`, `name`, `namespace` and `type`), or an array of them if batching created several; with `--dry-run`, the processed specification; refused with `--report`, which writes its own output (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd workerpool provision my_worker_pool.json --target 10 --follow
```

When `--quiet` (`-q`) is used, only the YDID of the provisioned Worker Pool is printed to stdout.

A Worker Pool defined in the configuration whose `maxNodes` exceeds `computeRequirementBatchSize` is provisioned as several Worker Pools; if one of them fails, those already provisioned are listed, since they are still running, and `--report` reports on the first of them alone, saying so. A Worker Pool specification is always provisioned as a single Worker Pool, with a warning if its `maxNodes` exceeds the batch size, and its `maintainInstanceCount` is set to `false`, as a Worker Pool requires. User Data merged in from the configuration is reported by its source and size, never printed.

The specification file may also be supplied using the deprecated `--worker-pool`/`-p` option; the positional argument is preferred.

See [Worker Pools](worker-pools.md) for the full specification reference.

### yd workerpool resize

The `yd workerpool resize` command resizes a Provisioned Worker Pool to a new number of Nodes, which may be zero but not negative.

```shell
yd workerpool resize [options] <worker-pool-name-or-ID> <new-node-count>
```

A YDID is found in whatever namespace it belongs to; a name is looked up in the configured `namespace` unless it is given as `namespace/name`. To resize a Compute Requirement, use [`yd computerequirement resize`](#yd-computerequirement-resize).

What cannot be resized is reported before anything is asked. A Worker Pool that does not exist exits with code 6. A Worker Pool fails if it is a Configured Worker Pool, is awaiting nodes, or would be taken outside its minimum or maximum number of nodes; it is skipped if it has already shut down or terminated, or already expects the number of nodes asked for. The confirmation shows the current and new sizes.

Key options:
- `--dry-run`/`-D` — report what would be resized, without resizing
- `--follow`/`-f` — follow the Worker Pool after resizing it
- `--auto-follow-compute-requirements`/`-a` — when following, also follow the associated Compute Requirement; refused without `--follow`
- `--json` — emit the actions taken, or with `--dry-run` what would be taken, as a JSON array, each with its `targetInstanceCount` (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd workerpool resize pyex-slurm-pwt_230711-1243561-0d 10
yd workerpool resize ydid:wrkrpool:D9C548:1f020696-ae9a-4786-bed2-c31b484b1d4f 10
```

### yd workerpool shutdown

The `yd workerpool shutdown` command shuts down the Worker Pools in the configured `namespace` whose names include the `tag`. All remaining work will be cancelled, but currently executing Tasks will be allowed to complete, after which a Provisioned Worker Pool's Compute Requirement will be terminated. Worker Pools that are already `SHUTDOWN` or `TERMINATED` are left out.

```shell
yd workerpool shutdown [options] [<worker-pool-name-or-ID> ...]
```

Specific Worker Pool names or YDIDs can optionally be supplied as positional arguments instead of using the `namespace`/`tag` selection. To shut down individual Nodes, use [`yd node shutdown`](#yd-node-shutdown).

They are handled in the order given and confirmed together; one that does not exist is reported as failed, and a Worker Pool that has already finished is skipped with a warning. If a request fails because the Application's credentials are not accepted, or the platform cannot be reached, nothing further is attempted, the remaining items are reported as skipped, and the command exits with that failure's code (see [Machine-readable Output and Exit Codes](json-output.md)).

A Worker Pool name argument can also be a glob pattern (`*`, `?`, `[...]`), matched client-side against Worker Pool names within the namespace (a name without wildcards matches exactly, so use `*` for partial matches); glob patterns cannot be mixed with literal names or YDIDs in the same command. Use `yd list worker-pools --name 'wp-*'` to preview the matches first.

Key options:
- `--terminate`/`-T` — immediately terminate each Provisioned Worker Pool's Compute Requirement, straight after the pool is shut down, rather than waiting for executing Tasks to complete; a Configured Worker Pool has no Compute Requirement
- `--auto-follow-compute-requirements`/`-a` — when following, also follow the associated Compute Requirements; refused without `--follow`
- `--dry-run`/`-D` — show the Worker Pools that would be shut down, whether matched or named, and with `--terminate` the Compute Requirements that would be terminated, without acting
- `--json` — emit the actions taken, or with `--dry-run` what would be taken, as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd workerpool shutdown 'wp-*' --dry-run
```

### yd workerpool token

The `yd workerpool token` command refreshes or regenerates the token of one or more Configured Worker Pools: the token that the YellowDog Agents on a pool's nodes use to register with it. Refreshing keeps the current token and sets its expiry afresh: `--ttl-hours` from now, or, without it, no expiry at all. Regenerating, with `--regenerate`, issues a new token instead, and Agents still holding the old one can no longer use it to register. Either is confirmed before anything is changed, the prompt saying what the tokens' expiry will be; `--yes` skips the confirmation.

```shell
yd workerpool token [options] <worker-pool-name-or-ID> [<worker-pool-name-or-ID> ...]
```

Each argument is a Worker Pool's YDID or name (a bare name is looked up in the configured `namespace`, or give it as `namespace/name`), or a glob pattern (`*`, `?`, `[...]`) matched against Worker Pool names in the namespace, which takes only the Configured Worker Pools it matches that have not been shut down. Arguments are handled in the order given, each pool once. A Worker Pool that does not exist, or is not a Configured Worker Pool, is reported as failed, and one that has already been shut down is skipped with a warning; the others go ahead. If a request fails because the Application's credentials are not accepted, or the platform cannot be reached, nothing further is attempted, the remaining pools are reported as skipped, and the command exits with that failure's code (see [Machine-readable Output and Exit Codes](json-output.md)).

Each pool's token and its expiry time (in UTC, or `never`) are printed; with `--quiet`, the token alone, one per pool. Under `--json`, a token that does not expire has an `expiryTime` of `null`.

Key options:
- `--regenerate`/`-R` — issue a new token, invalidating the current one, rather than setting the current token's expiry afresh
- `--ttl-hours`/`-H` — the token's time to live, in whole hours from now; **without it, the refreshed or regenerated token never expires**
- `--dry-run`/`-D` — report the pools whose tokens would be refreshed or regenerated, without changing anything
- `--json` — emit the actions taken, each with the new `token` and its `expiryTime`, as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd workerpool token my-namespace/my-configured-pool --ttl-hours 720
yd workerpool token 'cwp-*' --regenerate
```

## yd computerequirement

Compute Requirements: `yd computerequirement`, or `yd cr` for short.

| Verb | What it does | Replaces |
|---|---|---|
| [`instantiate`](#yd-computerequirement-instantiate) | Instantiate a Compute Requirement | `yd-instantiate` |
| [`resize`](#yd-computerequirement-resize) | Resize a Compute Requirement | `yd-resize -C` |
| [`stop`](#yd-computerequirement-stop) | Stop Compute Requirements | `yd-compute-stop` |
| [`start`](#yd-computerequirement-start) | Start stopped Compute Requirements | `yd-compute-start` |
| [`reprovision`](#yd-computerequirement-reprovision) | Restore Compute Requirements to their target instance counts | `yd-compute-reprovision` |
| [`autoshutdown`](#yd-computerequirement-autoshutdown) | Set when Compute Requirements are automatically terminated | |
| [`terminate`](#yd-computerequirement-terminate) | Terminate Compute Requirements | `yd-terminate` |
| `list` | `yd list compute-requirements` |  |
| `show` | `yd show`, for Compute Requirement names or IDs and Compute Source IDs, with `--show-source-report` and `--show-exhaustion` |  |
| `follow` | `yd follow`, for Compute Requirement names or IDs |  |
| `wait` | `yd wait`, for Compute Requirement names or IDs |  |

### yd computerequirement instantiate

The `yd computerequirement instantiate` command instantiates a Compute Requirement (i.e. a set of instances that are managed by their creator and do not automatically become part of a YellowDog Worker Pool).

```shell
yd computerequirement instantiate [options] [<compute-requirement-specification-file>]
```

This command uses the data from the `workerPool` configuration section (or, synonymously, the `computeRequirement` section), but only uses the `name`, `templateId`, `targetInstanceCount`, `instanceTags`, `userData` (or `userDataFile`/`userDataFiles`), `requirementTag`, `imagesId`, `maintainInstanceCount`, `autoShutdownTimeout`, `computeRequirementBatchSize`, `workerPoolData` and `computeRequirementData` properties. A Compute Requirement defined in the configuration whose `targetInstanceCount` exceeds `computeRequirementBatchSize` is split across several Compute Requirements; if one of them fails, those already provisioned are listed, since they are still running, and `--report` reports on the first of them alone, saying so. In addition, the Boolean property `maintainInstanceCount` (default = `false`) is available for use with `yd computerequirement instantiate`, as is `autoShutdownTimeout`, the time in minutes after which the Compute Requirement will be terminated (`0` for never; it is inherited by a JSON specification as `autoShutdown`, with the timeout as an ISO 8601 duration such as `"PT2H"`). The auto shutdown can be changed later with [`yd computerequirement autoshutdown`](#yd-computerequirement-autoshutdown).

Compute Requirements can be instantiated directly from JSON (or Jsonnet) specifications, supplied as the positional argument or by using the `computeRequirementData` property in the `workerPool`/`computeRequirement` section. The properties listed above will be inherited from the `config.toml` `workerPool` specification if they are not present in the JSON file.

The specification file may also be supplied using the deprecated `--compute-requirement`/`-C` or `--worker-pool`/`-p` options; the positional argument is preferred.

Variable substitutions must be prefixed and postfixed by a double underscore (`__`), e.g. `"__{{my_variable}}__"`.

Key options:
- `--target`/`-T <n>` — override `targetInstanceCount` from the specification or configuration
- `--report`/`-r` — report on a test run of a Dynamic Template, without provisioning (see below)
- `--content-path`/`-F <directory>` — the directory in which files for upload or user data are found
- `--dry-run`/`-D` — inspect the Compute Requirement specification that would be submitted, in JSON format; the JSON output can itself be used with `yd computerequirement instantiate`
- `--hide-user-data` — with `--dry-run`, show the User Data as a summary of its size rather than the script in full, as for `yd workerpool provision`; refused without `--dry-run`
- `--validate` — check the specification against its schema and stop, reporting every violation, rather than instantiating it (see [Checking Specifications](schemas.md#checking-a-file-before-submitting-it))
- `--follow`/`-f` — follow the Compute Requirement's events after it is created, until it is terminated or Ctrl-C is pressed (its stream stays open while it lives)
- `--jsonnet-dry-run`/`-J` — print the Jsonnet specification converted to JSON, and stop; it and `--validate` are refused when the Compute Requirement comes from the configuration alone, with no specification file
- `--json` — emit a JSON object naming the created Compute Requirement (`id`, `name`, `namespace` and `type`), or an array of them if batching created several; with `--dry-run`, the processed specification; refused with `--report`, which writes its own output (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd computerequirement instantiate my_compute_requirement.json --target 4
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

Values missing from a JSON specification are taken from the configuration file; `targetInstanceCount` only if the configuration actually sets it, so that a specification with no count is never sent with a count of zero. User Data merged in from the configuration is reported by its source and size, never printed. A JSON specification is provisioned as one Compute Requirement, whatever its count.

If a Worker Pool is defined in JSON, using `workerPoolData` in the configuration file or by supplying the command-line positional argument, `yd computerequirement instantiate` will extract the Compute Requirement from the Worker Pool specification (ignoring Worker-Pool-specific data), and use that for instantiating the Compute Requirement.

When `--quiet` (`-q`) is used, only the YDID of the instantiated Compute Requirement is printed to stdout.

#### Test-Running a Dynamic Template

When the `templateId` of a Dynamic Compute Requirement Template is used, the `yd computerequirement instantiate` command can be used to report on a test run of the Template, using the `--report` (or `-r`) command-line option. This can be used with both TOML-defined and JSON-defined Compute Requirement specifications. `yd workerpool provision --report` does the same for a Worker Pool, testing the Compute Requirement it would be provisioned with.

No instances will be provisioned during the test run. For a static template, which has no such report, the command says so.

For example:

```shell
% yd computerequirement instantiate --report --quiet
┌─────┬────────┬────────────┬───────────────────────────┬───────────┬─────────────────┬───────────────────┐
│   # │   Rank │ Provider   │ Type                      │ Region    │ Instance Type   │ Source Name       │
├─────┼────────┼────────────┼───────────────────────────┼───────────┼─────────────────┼───────────────────┤
│   1 │      1 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ t3a.micro       │ awsspot-eu-west-2 │
│   2 │      2 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ t3a.small       │ awsspot-eu-west-2 │
│   3 │      3 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ c5a.large       │ awsspot-eu-west-2 │
│   4 │      3 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ c6a.large       │ awsspot-eu-west-2 │
│   5 │      3 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ t3a.medium      │ awsspot-eu-west-2 │
│   6 │      4 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ m5a.large       │ awsspot-eu-west-2 │
│   7 │      4 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ m5ad.large      │ awsspot-eu-west-2 │
│   8 │      4 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ m6a.large       │ awsspot-eu-west-2 │
│   9 │      4 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ t3a.large       │ awsspot-eu-west-2 │
│  10 │      5 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ r5a.large       │ awsspot-eu-west-2 │
└─────┴────────┴────────────┴───────────────────────────┴───────────┴─────────────────┴───────────────────┘
```

### yd computerequirement resize

The `yd computerequirement resize` command sets a Compute Requirement's target number of Instances, which may be zero but not negative.

```shell
yd computerequirement resize [options] <compute-requirement-name-or-ID> <new-instance-count>
```

A YDID is found in whatever namespace it belongs to; a name is looked up in the configured `namespace` unless it is given as `namespace/name`. A Worker Pool and its Compute Requirement share their name: this command resizes the Compute Requirement, and [`yd workerpool resize`](#yd-workerpool-resize) the Worker Pool.

Only a `RUNNING` Compute Requirement is resized: one in any other state is skipped, as is one whose target is already the number of instances asked for, and a name shared by two `RUNNING` Compute Requirements is ambiguous, so the YDID must be given instead. One that does not exist exits with code 6. The confirmation shows the current and new sizes.

Key options:
- `--dry-run`/`-D` — report what would be resized, without resizing
- `--follow`/`-f` — follow the Compute Requirement's events after resizing it, until it has settled at its new target
- `--wait`/`-w` — wait until the Compute Requirement has its new target of Instances running (see below); refused with `--follow`
- `--timeout <seconds>` — with `--wait`, stop waiting after this many seconds and exit 1 (default: no limit); refused without `--wait`
- `--json` — emit the actions taken, or with `--dry-run` what would be taken, as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

With `--wait`, the command returns only once the resized Compute Requirement has settled: it is `RUNNING`, as many of its Instances are `RUNNING` as its new target asks for, and none is still starting, stopping or terminating. Scaling up therefore waits for the new Instances to start, and scaling down for the surplus Instances to finish terminating, which can take a minute or more. Progress is printed whenever it changes. A Compute Requirement that cannot reach its target, because the cloud provider has no more capacity of the kind it asks for (on-demand as well as spot) or an Allowance or quota stands in the way, never settles, so give a `--timeout` when that is possible: if it passes first, the command reports what is still missing and exits 1, though the resize itself has been made and is recorded as `resized`. `--wait` cannot be combined with `--follow`.

```shell
yd computerequirement resize pyex-slurm-pwt_230712-1102264-4c 5
yd computerequirement resize ydid:compreq:D9C548:600bef1f-7ccd-431c-afcc-b56208565aac 5
yd computerequirement resize pyex-slurm-pwt_230712-1102264-4c 5 --wait --timeout 600
```

### yd computerequirement stop

The `yd computerequirement stop` command stops `RUNNING` Compute Requirements. Stopped Compute Requirements can subsequently be started again using `yd computerequirement start`. To stop individual Instances, use [`yd instance stop`](#yd-instance-stop), or [`yd node stop`](#yd-node-stop) for the Instances on which Worker Pool Nodes are running.

```shell
yd computerequirement stop [options] [<compute-requirement-name-or-ID> ...]
```

If no arguments are supplied, Compute Requirements that match the `namespace` and `tag` found in the configuration file are candidates for stopping. Alternatively, the command accepts a list of Compute Requirement names or YDIDs.

A Compute Requirement name is looked up in the configured namespace unless it is given as `namespace/name`. A name may also be a glob pattern (e.g. `'cr-*'`), which selects every `RUNNING` Compute Requirement whose name it matches, to be confirmed (or chosen from, with `--interactive`) as the candidates found by `namespace` and `tag` are; glob patterns cannot be mixed with explicit names or IDs.

Explicit names and IDs are resolved in the order given, and are confirmed together; the Compute Requirements are then acted on before the Instances. A Compute Requirement that is not `RUNNING` is skipped with a warning. If a request fails because the Application's credentials are not accepted, or the platform cannot be reached, nothing further is attempted, the remaining items are reported as skipped, and the command exits with that failure's code (see [Machine-readable Output and Exit Codes](json-output.md)).

The `--follow`/`-f` option follows the event stream(s) of the Compute Requirement(s) acted on.

Key options:
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd computerequirement stop
yd computerequirement stop my-compute-requirement
yd computerequirement stop ydid:compreq:D9C548:98879b5a-9192-4a56-ad25-fc1330e49185
```

### yd computerequirement start

The `yd computerequirement start` command starts `STOPPED` Compute Requirements. To start individual Instances, use [`yd instance start`](#yd-instance-start), or [`yd node start`](#yd-node-start).

```shell
yd computerequirement start [options] [<compute-requirement-name-or-ID> ...]
```

It accepts the same arguments as `yd computerequirement stop`, and handles them in the same way: if no arguments are supplied, `STOPPED` Compute Requirements that match the `namespace` and `tag` are candidates for starting; otherwise, supply a list of Compute Requirement names (or glob patterns) or YDIDs.

Key options:
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd computerequirement start my-compute-requirement --follow
```

### yd computerequirement reprovision

The `yd computerequirement reprovision` command reprovisions `RUNNING` Compute Requirements: it asks the Platform to provision Instances until as many are running as each Compute Requirement's target instance count asks for. This restores a Compute Requirement that has fewer Instances than its target, for example after Instances were terminated with `yd instance terminate` or reclaimed by the cloud provider, without changing the target. It is the counterpart of `yd instance deprovision`, which reduces the target; to change the target itself, use `yd computerequirement resize`.

```shell
yd computerequirement reprovision [options] [<compute-requirement-name-or-ID> ...]
```

It selects Compute Requirements as `yd computerequirement stop` does: if no arguments are supplied, `RUNNING` Compute Requirements that match the `namespace` and `tag` are candidates for reprovisioning; otherwise, supply a list of Compute Requirement names (or glob patterns) or YDIDs. A Compute Requirement that is not `RUNNING` is skipped with a warning, including one still `PROVISIONING`, which is already provisioning towards its target. Reprovisioning a Compute Requirement that already has as many Instances running as its target count changes nothing. The command returns once the Platform has accepted the request: the Compute Requirement moves to `PROVISIONING` while the new Instances start, and `--follow` shows them being provisioned.

Key options:
- `--follow`/`-f` — follow the Compute Requirements' events as Instances are provisioned, until each is at its target
- `--wait`/`-w` — wait until each Compute Requirement reprovisioned has its target number of Instances running, as for `yd computerequirement resize --wait`; refused with `--follow`
- `--timeout <seconds>` — with `--wait`, stop waiting after this many seconds and exit 1 (default: no limit); refused without `--wait`
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd computerequirement reprovision my-compute-requirement --follow
yd computerequirement reprovision my-compute-requirement --wait --timeout 600
```

### yd computerequirement autoshutdown

The `yd computerequirement autoshutdown` command sets when Compute Requirements are automatically terminated: `--minutes` from now, replacing whatever auto shutdown each had, or with `--minutes 0` never. Running it again restarts the clock, so the same command extends a Compute Requirement's life. A Compute Requirement is given an auto shutdown when it is instantiated by the `autoShutdownTimeout` configuration property (see [Worker Pool Properties](worker-pools.md#worker-pool-properties)), or by `autoShutdown` in its specification; `yd computerequirement show` shows its `autoShutdown` and the `autoShutdownTime` at which it will be terminated.

```shell
yd computerequirement autoshutdown [options] --minutes <minutes> [<compute-requirement-name-or-ID> ...]
```

It selects Compute Requirements as `yd computerequirement terminate` does: if no arguments are supplied, Compute Requirements that match the `namespace` and `tag` are candidates; otherwise, supply a list of Compute Requirement names (or glob patterns) or YDIDs. A Compute Requirement that is already terminating or terminated is skipped with a warning. Each one updated is reported with the time at which it will now be terminated.

Key options:
- `--minutes <minutes>` — required: terminate the Compute Requirements this many minutes from now (a fraction is allowed), or with `0` never automatically
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md)); each record adds the `autoShutdownTime` set, `null` when there is none

```shell
yd computerequirement autoshutdown my-compute-requirement --minutes 120
yd computerequirement autoshutdown my-compute-requirement --minutes 0
yd computerequirement autoshutdown 'batch-*' --minutes 30
```

### yd computerequirement terminate

The `yd computerequirement terminate` command immediately terminates Compute Requirements that match the `namespace` and `tag` found in the configuration file. Any executing Tasks will be terminated immediately, and the Worker Pool will be shut down. A Compute Requirement in any state but `TERMINATING` or `TERMINATED` can be terminated. To terminate individual Instances, use [`yd instance terminate`](#yd-instance-terminate), or [`yd node terminate`](#yd-node-terminate) for a Node's.

```shell
yd computerequirement terminate [options] [<compute-requirement-name-or-ID> ...]
```

Specific Compute Requirement names or YDIDs can optionally be supplied as positional arguments instead of using the `namespace`/`tag` selection.

A Compute Requirement name is looked up in the configured namespace unless it is given as `namespace/name`. A name argument can also be a glob pattern (`*`, `?`, `[...]`), matched client-side against Compute Requirement names within the namespace (a name without wildcards matches exactly, so use `*` for partial matches); glob patterns cannot be mixed with literal names or YDIDs in the same command. Use `--dry-run`, or `yd list compute-requirements --name 'ci-*'`, to preview the matches first.

Explicit names and IDs are handled as [`yd computerequirement stop`](#yd-computerequirement-stop) handles them: in the order given, and confirmed together. A Compute Requirement that is already terminating or terminated is skipped with a warning, and a failure of the Application's credentials or of the connection stops the command, the remaining items being reported as skipped.

Key options:
- `--dry-run`/`-D` — show which Compute Requirements would be terminated, whether selected by `namespace` and `tag`, by glob pattern or by name or ID, without terminating anything
- `--json` — emit the actions taken, or with `--dry-run` what would be taken, as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))
- `--follow`/`-f` — follow the affected Compute Requirements' event streams after the action is applied

```shell
yd computerequirement terminate 'ci-*' --dry-run
```

## yd instance

The Instances of Compute Requirements. An Instance has no YellowDog ID of its own: it is given as `<compute-requirement-ydid>.<instance-id>`, its Compute Requirement's YDID and its provider-assigned instance ID, the form `yd instance list --ids-only` prints. Only the first `.` separates the two, so instance IDs that contain dots of their own (OCI's OCIDs, for example) need no special treatment.

Every `yd instance` verb that acts takes at least one Instance, and takes no `--namespace`, `--tag` or `--interactive`, which select Compute Requirements. The Instances given are resolved in the order given and confirmed together, then acted on a Compute Requirement at a time, those in the same Compute Requirement in a single request. If a request fails because the Application's credentials are not accepted, or the platform cannot be reached, nothing further is attempted, the remaining items are reported as skipped, and the command exits with that failure's code (see [Machine-readable Output and Exit Codes](json-output.md)).

| Verb | What it does | Replaces |
|---|---|---|
| [`stop`](#yd-instance-stop) | Stop Instances | `yd-compute-stop` |
| [`start`](#yd-instance-start) | Start stopped Instances | `yd-compute-start` |
| [`restart`](#yd-instance-restart) | Restart Instances | `yd-compute-restart` |
| [`deprovision`](#yd-instance-deprovision) | Terminate Instances, reducing their Compute Requirements' target counts | `yd-compute-deprovision` |
| [`terminate`](#yd-instance-terminate) | Terminate Instances | `yd-terminate` |
| `list` | `yd list instances` |  |
| `show` | `yd show`, for Instances |  |

### yd instance stop

The `yd instance stop` command stops `RUNNING` Instances; `yd instance start` starts them again. An Instance that is not `RUNNING` is skipped with a warning.

```shell
yd instance stop [options] <cr-id.instance-id> ...
```

Key options:
- `--follow`/`-f` — follow the Compute Requirements' events until nothing is changing
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd instance stop ydid:compreq:D9C548:98879b5a-9192-4a56-ad25-fc1330e49185.i-0a1b2c3d4e5f67890
```

### yd instance start

The `yd instance start` command starts `STOPPED` Instances. An Instance that is not `STOPPED` is skipped with a warning.

```shell
yd instance start [options] <cr-id.instance-id> ...
```

Key options:
- `--follow`/`-f` — follow the Compute Requirements' events until each is at its target and running
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd instance start ydid:compreq:D9C548:98879b5a-9192-4a56-ad25-fc1330e49185.i-0a1b2c3d4e5f67890 --follow
```

### yd instance restart

The `yd instance restart` command restarts (reboots) `RUNNING` Instances; an Instance that is not `RUNNING` is skipped with a warning. Whole Compute Requirements cannot be restarted.

```shell
yd instance restart [options] <cr-id.instance-id> ...
```

Key options:
- `--follow`/`-f` — follow the Compute Requirements' events until each has left its target and settled at it again
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd instance restart ydid:compreq:D9C548:98879b5a-9192-4a56-ad25-fc1330e49185.i-0a1b2c3d4e5f67890
```

### yd instance deprovision

The `yd instance deprovision` command deprovisions Instances: it terminates them and reduces their Compute Requirement's target instance count by the same number, so that they are not replaced. Terminating an Instance with `yd instance terminate` leaves the target count as it was, so a Compute Requirement that maintains its instance count replaces it. To remove a whole Compute Requirement, use `yd computerequirement terminate`.

An Instance of a Provisioned Worker Pool can be deprovisioned too, by its `cr_id.instance_id`, or with [`yd node deprovision`](#yd-node-deprovision) by its Node's YDID. The pool's expected node count follows its Compute Requirement's reduced target, so the pool does not ask for a replacement either. A pool left with no nodes stays up until its idle pool shutdown, if it has one, takes effect; use `yd workerpool shutdown` to shut it down at once.

```shell
yd instance deprovision [options] <cr-id.instance-id> ...
```

An Instance that is already `TERMINATING` or `TERMINATED` is skipped with a warning. The command returns once the Platform has accepted the request: the target count drops at once, and the Instances are terminated shortly afterwards, which `--follow` shows.

Key options:
- `--follow`/`-f` — follow the Compute Requirements' events as the Instances are terminated, until each is at its new target
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd instance deprovision ydid:compreq:D9C548:98879b5a-9192-4a56-ad25-fc1330e49185.i-0a1b2c3d4e5f67890
```

### yd instance terminate

The `yd instance terminate` command terminates Instances immediately. An Instance that is already terminating or terminated is skipped with a warning. Its Compute Requirement's target count is left as it was, so one that maintains its instance count replaces a terminated Instance; to terminate Instances without their being replaced, use [`yd instance deprovision`](#yd-instance-deprovision).

```shell
yd instance terminate [options] <cr-id.instance-id> ...
```

Key options:
- `--dry-run`/`-D` — show which Instances would be terminated, without terminating anything
- `--json` — emit the actions taken, or with `--dry-run` what would be taken, as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))
- `--follow`/`-f` — follow the affected Compute Requirements' events until the Instances have gone and nothing is changing

```shell
yd instance terminate ydid:compreq:D9C548:98879b5a-9192-4a56-ad25-fc1330e49185.i-0a1b2c3d4e5f67890 --dry-run
```

## yd node

Worker Pool Nodes, each given by its YellowDog ID. Every `yd node` verb but `action` acts on the Instance a Node runs on, as the matching `yd instance` verb does, or (`shutdown`) on the Node itself; each takes at least one Node, and handles them as the `yd instance` verbs handle Instances. A Node that is already `TERMINATED` is skipped, and the verbs acting on a Node's Instance refuse a Node in a Configured Worker Pool (whose Instances YellowDog does not manage), one whose Worker Pool has no Compute Requirement, and one that has not yet reported its Instance.

| Verb | What it does | Replaces |
|---|---|---|
| [`action`](#yd-node-action) | Submit Node Actions to Worker Pool Nodes | `yd-nodeaction` |
| [`shutdown`](#yd-node-shutdown) | Shut down Nodes | `yd-shutdown` |
| [`stop`](#yd-node-stop) | Stop the Instances of Nodes | `yd-compute-stop` |
| [`start`](#yd-node-start) | Start the stopped Instances of Nodes | `yd-compute-start` |
| [`terminate`](#yd-node-terminate) | Terminate the Instances of Nodes | `yd-terminate` |
| [`restart`](#yd-node-restart) | Restart the Instances of Nodes | `yd-compute-restart` |
| [`deprovision`](#yd-node-deprovision) | Deprovision the Instances of Nodes | `yd-compute-deprovision` |
| `list` | `yd list nodes` |  |
| `show` | `yd show`, for Node IDs |  |

### yd node action

The `yd node action` command submits Node Actions to running Worker Pool nodes.

```shell
yd node action [options]
```

The command takes no positional arguments: the actions are supplied with `--actions`, which is required unless `--status` is used (and is refused with it). `--worker-pool` accepts a pool name or a Worker Pool YDID; if omitted, an interactive selection is shown of the unfinished pools in the namespace whose names include the tag (configured, or given with `--namespace` and `--tag`), ordered by `--sort` and `--reverse`. Without `--node` or `--all-nodes`, the nodes are chosen interactively from the pool's running ones.

The specification is checked first, so a faulty one fails (exit 1) before anything is looked up or submitted.

Nodes given with `--node` must be node YDIDs, and are each targeted once however often they are given; they must all be in one Worker Pool, which is then found from them (or, with `--worker-pool`, must be the one it names), and a node that has terminated or deregistered is skipped with a warning. A Worker Pool or node that does not exist exits with code 6, and one that has shut down or terminated is refused. If a submission fails because the Application's credentials are not accepted, or the platform cannot be reached, nothing further is attempted, and the command exits with that failure's code.

Key options:
- `--actions`/`-S <file>` — the Node Action spec file, in JSON or Jsonnet format
- `--worker-pool`/`-p <name>` — the target Worker Pool
- `--node`/`-N <node-id>` — target a specific node by ID; can be supplied multiple times
- `--all-nodes` — target all current nodes in the Worker Pool, filtered by `nodeTypes` if present in the spec; cannot be combined with `--node`
- `--follow`/`-f` — poll the node action queues after submission until every one is `EMPTY` or `FAILED`
- `--timeout <seconds>` — with `--follow`, stop after this many seconds, failing (exit 1) if any queue has not finished; by default there is no limit
- `--status` — show the Node Action queue for the selected node(s), or with `--all-nodes` for every running node in the pool; with `--follow`, poll the queues until each is done. `--details`/`-d` shows the full JSON (refused without `--status`)
- `--content-path`/`-F <directory>` — the directory in which files for upload are found
- `--validate` — check the `--actions` file against its schema and stop, reporting every violation, rather than submitting it; refused with `--status` (see [Checking Specifications](schemas.md#checking-a-file-before-submitting-it))
- `--jsonnet-dry-run`/`-J` — print the `--actions` Jsonnet file converted to JSON, and stop; refused with `--status`
- `--json` — emit the submissions, or with `--status` the node action queues, as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
# Submit actions to interactively selected node(s)
yd node action --actions my_actions.json --worker-pool my-pool

# Submit to all current nodes in a pool
yd node action --actions my_actions.json --worker-pool my-pool --all-nodes

# Submit to a specific node by YDID (worker pool resolved automatically)
yd node action --actions my_actions.json --node ydid:node:D9C548:... --follow

# Check node action queue status for a specific node
yd node action --status --node ydid:node:D9C548:... --details
```

See [Node Actions](worker-pools.md#node-actions) for the spec format, action types, and field reference.

### yd node shutdown

The `yd node shutdown` command shuts down individual Worker Pool Nodes. A Node that does not exist is reported as failed, and one that is already `TERMINATED` is skipped with a warning; to shut down whole Worker Pools, use [`yd workerpool shutdown`](#yd-workerpool-shutdown).

```shell
yd node shutdown [options] <node-ID> ...
```

Key options:
- `--dry-run`/`-D` — show the Nodes that would be shut down, without acting
- `--json` — emit the actions taken, or with `--dry-run` what would be taken, as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd node shutdown ydid:node:D9C548:f9d5a10e-5b0e-4b76-b50f-d2bbac0a5cb8
```

### yd node stop

The `yd node stop` command stops the `RUNNING` Instances on which Worker Pool Nodes are running, as [`yd instance stop`](#yd-instance-stop) does.

```shell
yd node stop [options] <node-ID> ...
```

Key options:
- `--follow`/`-f` — follow the Compute Requirements' events until nothing is changing
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd node stop ydid:node:D9C548:f9d5a10e-5b0e-4b76-b50f-d2bbac0a5cb8
```

### yd node start

The `yd node start` command starts the `STOPPED` Instances of Worker Pool Nodes, as [`yd instance start`](#yd-instance-start) does.

```shell
yd node start [options] <node-ID> ...
```

Key options:
- `--follow`/`-f` — follow the Compute Requirements' events until each is at its target and running
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd node start ydid:node:D9C548:f9d5a10e-5b0e-4b76-b50f-d2bbac0a5cb8
```

### yd node terminate

The `yd node terminate` command terminates the Instances of Worker Pool Nodes immediately, as [`yd instance terminate`](#yd-instance-terminate) does.

```shell
yd node terminate [options] <node-ID> ...
```

Key options:
- `--follow`/`-f` — follow the affected Compute Requirements' events until the Instances have gone and nothing is changing
- `--dry-run`/`-D` — show which Nodes' Instances would be terminated, without terminating anything
- `--json` — emit the actions taken, or with `--dry-run` what would be taken, as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd node terminate ydid:node:D9C548:f9d5a10e-5b0e-4b76-b50f-d2bbac0a5cb8
```

### yd node restart

The `yd node restart` command restarts (reboots) the `RUNNING` Instances of Worker Pool Nodes, as [`yd instance restart`](#yd-instance-restart) does.

```shell
yd node restart [options] <node-ID> ...
```

Key options:
- `--follow`/`-f` — follow the Compute Requirements' events until each has left its target and settled at it again
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd node restart ydid:node:D9C548:f9d5a10e-5b0e-4b76-b50f-d2bbac0a5cb8
```

### yd node deprovision

The `yd node deprovision` command deprovisions the Instances of Worker Pool Nodes, reducing their Compute Requirements' target counts, and so their Worker Pools' expected node counts, as [`yd instance deprovision`](#yd-instance-deprovision) does.

```shell
yd node deprovision [options] <node-ID> ...
```

Key options:
- `--follow`/`-f` — follow the Compute Requirements' events as the Instances are terminated, until each is at its new target
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd node deprovision ydid:node:D9C548:f9d5a10e-5b0e-4b76-b50f-d2bbac0a5cb8
```

## yd worker

Workers.

| Verb | What it does | Replaces |
|---|---|---|
| `list` | `yd list workers` |  |
| `show` | `yd show`, for Worker IDs |  |

## yd resource

Resources: Compute Source and Compute Requirement Templates, Keyrings, Credentials, Image Families, Attribute Definitions, Allowances, Namespace Policies, Configured Worker Pools, Groups, Applications and Users, as [Creating, Updating and Removing YellowDog Resources](resources.md) describes them.

| Verb | What it does | Replaces |
|---|---|---|
| [`create`](#yd-resource-create) | Create and update resources | `yd-create` |
| [`remove`](#yd-resource-remove) | Remove resources | `yd-remove` |
| `list <type>` | `yd list`, for the resource types: `allowances`, `applications`, `attribute-definitions`, `compute-requirement-templates`, `compute-source-templates`, `groups`, `image-families`, `keyrings`, `namespace-policies`, `namespaces`, `permissions`, `roles` and `users` |  |
| `show` | `yd show`, for resource IDs, or names with `--type`, with `--show-members` |  |

### yd resource create

The `yd resource create` command creates or updates YellowDog resources, specified in one or more JSON, Jsonnet or TOML files supplied on the command line, or `-` for one read from standard input as JSON. Each file can contain one or more resources. A resource can also be given on the command line, with `--type` and `--set`, in place of a file or as well as files (see [Specifying a Resource on the Command Line](resources.md#specifying-a-resource-on-the-command-line)).

```shell
yd resource create [options] <resource-specification> [<resource-specification> ...]
yd resource create [options] --type <resource-type> --set <property=value> [--set ...]
```

Key options:
- `--type <resource-type>` — the type of a resource given on the command line, such as `Keyring` or `Namespace`, in any case
- `--set <property=value>` — a property of that resource, the value read as JSON where it can be (a number, a list, an object, `true`, `null`) and as text otherwise; repeatable, each property once; needs `--type`
- `--match-allowances-by-description`/`-M` — match using the `description` property when updating Allowances
- `--show-keyring-passwords` — display the YellowDog-generated password when creating a Keyring
- `--regenerate-app-keys` — regenerate the application key and secret when updating an Application; required to grant an existing Application access to Keyrings
- `--no-resequence` — process the resources strictly in the order supplied, rather than in dependency order
- `--dry-run`/`-D` — report what would be created or updated, without applying any changes; a template named in an Allowance or Compute Requirement Template that does not exist yet is left as named, since an earlier specification in the same run may create it
- `--hide-user-data` — with `--dry-run`, show the User Data of Compute Source Templates and Compute Requirement Templates as a summary of its size rather than the script in full, as for `yd workerpool provision`; refused without `--dry-run`
- `--jsonnet-dry-run`/`-J` — dry-run Jsonnet processing into JSON
- `--validate` — check every resource specification against its schema and stop, reporting every violation, rather than creating or updating anything (see [Checking Specifications](schemas.md#checking-a-file-before-submitting-it))
- `--json` — emit the resources created, updated or skipped as a JSON array; with `--dry-run`, the processed specifications (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd resource create my_keyring.json my_compute_templates.jsonnet
yd resource create --type Keyring --set name=team-keys --set description="Team keys"
```

See [Creating, Updating and Removing YellowDog Resources](resources.md) for the full resource specification reference.

### yd resource remove

The `yd resource remove` command removes YellowDog resources, specified in one or more JSON, Jsonnet or TOML files supplied on the command line, `-` for one read from standard input as JSON, or a resource given on the command line with `--type` and `--set`. Each file can contain one or more resources. An argument that is a YellowDog ID (YDID) is removed by its ID, so files and IDs can be given together. Whatever is given, files, IDs or both, is removed in one run, in the order that removes a resource before those it refers to (a template before its Keyring), or with `--no-resequence` in the order given.

```shell
yd resource remove [options] <resource-specification-or-id> [<resource-specification-or-id> ...]
yd resource remove [options] --type <resource-type> <name-or-id> [<name-or-id> ...]
```

Key options:
- `--type <resource-type>` — with arguments, they are the names or YellowDog IDs of resources of that type to remove, such as `--type Keyring team-keys` (`namespace/name` for a namespaced type, `keyring/credential` for a Credential; see [Specifying a Resource on the Command Line](resources.md#specifying-a-resource-on-the-command-line) for which types take names and which IDs); with `--set <property=value>` instead, a resource given on the command line, as for `yd resource create`
- `--ids` — optional: says every argument is a YellowDog ID, refusing anything else; cannot be combined with `--match-allowances-by-description`, `--jsonnet-dry-run`, `--type` or `--set`
- `--match-allowances-by-description`/`-M` — match using the `description` property when removing Allowances
- `--jsonnet-dry-run`/`-J` — dry-run Jsonnet processing into JSON, removing nothing (refused when every argument is an ID)
- `--no-resequence` — remove the resources strictly in the order supplied, files' resources and IDs alike, rather than in dependency order
- `--json` — emit the resources removed or skipped as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd resource remove my_compute_templates.jsonnet
yd resource remove ydid:crt:000000:230e9a42-97db-4d69-aa91-29ff309951b4
yd resource remove my_keyring.json ydid:crt:000000:230e9a42-97db-4d69-aa91-29ff309951b4
yd resource remove --type Keyring team-keys old-keys
```

See [Creating, Updating and Removing YellowDog Resources](resources.md) for details.

## yd allowance

Allowances.

| Verb | What it does | Replaces |
|---|---|---|
| [`boost`](#yd-allowance-boost) | Boost Allowances | `yd-boost` |
| `list` | `yd list allowances` |  |
| `show` | `yd show`, for Allowance IDs |  |

### yd allowance boost

The `yd allowance boost` command adds hours to a YellowDog Allowance. Allowances are time-based compute budgets that limit how many CPU- or GPU-hours can be consumed by a namespace or application. Boosting is useful when a running job is approaching its limit and needs additional headroom.

```shell
yd allowance boost [options] <boost-hours> <allowance-ID> [<allowance-ID> ...]
```

The number of hours to add is supplied first, and must be at least 1, followed by the YDID(s) of one or more Allowances to boost. Allowance names are not accepted, and anything that is not an Allowance YDID is a usage error, before anything is boosted; an Allowance ID given more than once is boosted once.

Each Allowance is looked up first, so one that does not exist is reported as failed before any is boosted, and the rest are confirmed together, each shown with its description (an Allowance has no name); each one's remaining hours are reported once it has been boosted. An authentication or connection failure stops the command, with that failure's [exit code](json-output.md): the Allowances not yet attempted are reported as skipped rather than each failing in the same way.

Key options:
- `--json` — emit the actions taken as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd allowance boost 10 ydid:allow:D9C548:...
yd allowance boost 10 ydid:allow:D9C548:... ydid:allow:D9C548:...
```

See [Allowances](resources.md#allowances) for how Allowances are defined.

## yd data

The five `yd data` verbs provide direct access to remote data stores via rclone, and never contact the YellowDog Platform API. They accordingly do not accept the `--key`, `--secret`, `--url` or `--pac` [Universal Options](#universal-options); the remainder apply as usual, including `--config`, `--namespace`/`--tag` (which supply the default path prefix) and `--property`.

They share a further set of options — `--remote`/`-r`, `--bucket`/`-b`, `--prefix`/`-p`, `--no-prefix`, `--data-client-profile`/`--profile`, `--upgrade-rclone` and `--which-rclone` — which are described under [Data Client](data-client.md), along with the `[dataClient]` configuration section and named profiles.

A remote path given to `yd data upload` (as `--destination`), `yd data download`, `yd data delete` or `yd data copy` cannot contain a `..` segment: it would climb out of the prefix, or the bucket, past the checks that keep these commands from deleting or syncing over the remote's root or the bucket, and object stores do not resolve it as a local disk does. It is refused as the command line is read (exit 2); to reach a path outside the prefix, use `--no-prefix` or `--bucket`. A `.` segment names the directory it is in, so `.` alone is the configured prefix itself. `yd data list`, which only reads, accepts `..`, and a local path may contain it anywhere.

A wildcard (`*`, `?`, `[…]`) is matched against the names in the last part of a remote path only. An entry whose name is exactly the path's last part is taken as itself rather than as a pattern, so a file named `data[1].csv` can be listed, downloaded and deleted by its name, and deleting `file[ab].txt` deletes that file alone, not `filea.txt` and `fileb.txt`.

An inline remote's configuration, which carries its credentials, is passed to rclone in a file only you can read, in the system's temporary directory, and removed when the command ends.

| Verb | What it does | Replaces |
|---|---|---|
| [`upload`](#yd-data-upload) | Upload files to a remote data client | `yd-upload` |
| [`download`](#yd-data-download) | Download files from a remote data client | `yd-download` |
| [`list`](#yd-data-list) | List remote data client files and directories | `yd-ls` |
| [`delete`](#yd-data-delete) | Delete remote data client files and directories | `yd-delete` |
| [`copy`](#yd-data-copy) | Copy files between remote data client locations | `yd-copy` |

### yd data upload

The `yd data upload` command uploads local files or directories to a remote data store.

```shell
yd data upload [options] <local-path> [<local-path> ...]
```

Key options:
- `--recursive`/`-R` — upload directories recursively, preserving the directory structure
- `--flatten` — upload all files in a directory tree to a flat (single-level) remote destination
- `--sync` — synchronise the remote destination to match the local source (implies `--recursive`); files present at the destination but absent locally are deleted; cannot be combined with `--flatten`
- `--destination`/`-d <remote-path>` — override the destination path; supports `{{variable}}` substitution
- `--dry-run`/`-D` — show what would be uploaded, without uploading; with `--sync`, also each remote file that would be deleted
- `--json` — emit the files uploaded as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd data upload --recursive my_input_data/
```

A file is uploaded to its own name under the configured prefix, and a directory's contents to a remote directory of the directory's own name. `--destination` names the remote path instead: for a single file, the file's own path (or, ending in `/`, the directory it goes into); for a single directory, the remote directory its contents go into. With more than one local path, `--destination` is a directory, and every file and directory keeps its own name inside it, so `yd data upload -R -d out a/ b/` produces `out/a/` and `out/b/`. A directory given without `--recursive`, `--flatten` or `--sync` is an error.

Before anything is uploaded, `yd data upload` works out where every argument will land, and refuses the whole run (exit 2) if two of them would land on the same remote path — two directories of the same name would merge, and with `--sync` the second would delete what the first uploaded; with `--flatten`, it is two files landing on one path that is refused. A `--sync` whose destination is the remote's root or the configured bucket itself, whose every other file it would delete, is refused in the same way, as `yd data copy`'s is. A failed upload is reported and recorded, and the rest are still attempted; the command then exits 1. Symbolic links are not uploaded (rclone does not follow them), and a warning says how many were left out.

### yd data download

The `yd data download` command downloads files from a remote data store to the local filesystem.

```shell
yd data download [options] <remote-path> [<remote-path> ...]
```

Remote paths support `{{variable}}` substitution (e.g. `'{{tag}}/results.csv'`) and may also contain wildcard characters (`*`, `?`, `[…]`). On Windows, a remote item whose own name holds a character Windows does not allow in a file name fails, saying so; give `--destination` to name the local file. A wildcard path is expanded against the configured prefix and all matching files and directories are downloaded. The matched names are displayed before the download begins. When a wildcard is used, files are downloaded into the current directory (preserving the names of the matched items) unless `--destination` is specified. `--sync` is supported with wildcards.

Key options:
- `--destination`/`-d <local-path>` — local destination directory (default: mirrors the remote directory name)
- `--into <local-dir>` — local directory to download each remote item into, under its own name (mutually exclusive with `--destination`)
- `--sync` — mirror the remote source to the local destination, deleting local files not present remotely (cannot be combined with `--flatten`)
- `--flatten` — download all files in a remote directory tree to a flat (single-level) local destination, including the directories a wildcard matches; files that share a name, within one remote path argument or across several, are warned about, and the later one overwrites the earlier
- `--dry-run`/`-D` — show what would be downloaded, without downloading; with `--sync`, also each local file that would be deleted
- `--json` — emit the downloads, or with `--dry-run` the matched items, as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

`--destination` and `--into` answer different questions, which matters when downloading more than one item. `--destination` names the local path that *corresponds to* the remote item, so `yd data download -d out mydir` puts the contents of `mydir` directly into `out`; giving several items one `--destination` therefore merges them. `--into` names a container, so `yd data download --into out mydir otherdir` produces `out/mydir/` and `out/otherdir/`, each keeping its own name. A single file is given its own path the same way: `yd data download --into out a.txt` writes the file `out/a.txt`, and `yd data download a.txt` writes `./a.txt`, while `yd data download -d out a.txt` puts it inside `out`, as `out/a.txt`. With a wildcard the two agree, since a wildcard is expanded into the destination by name either way.

With `--sync`, which deletes local files not in the remote, two remote paths that would be synced into the same local path are refused before anything is downloaded (exit 2), since the second would delete what the first fetched, and so is a sync into the current directory itself (a remote path naming the configured prefix, `/`) unless the current directory is named explicitly with `-d .`. A wildcard is checked by listing its matches, each of which is synced to a path of its own; a wildcard whose matches cannot be listed for the check is never synced unchecked, but reported and recorded as failed while the other remote paths still are.

With `--flatten`, each directory's files are placed directly in the destination, the directory's own name and those of its subdirectories being dropped, so `yd data download --flatten -d flat 'my*'` puts every file of every matched directory in `flat`; a file whose name another flattened file already has is reported with a warning naming both, and the later of the two is the one kept.

A remote path that does not exist, or a wildcard that matches nothing, is an error, as is a remote that cannot be reached; an empty directory downloads nothing, successfully. A failed download is reported and recorded, and the other remote paths (and the other items a wildcard matched) are still attempted; the command then exits 1.

```shell
yd data download 'results_*'
```

### yd data list

The `yd data list` command lists files and directories in a remote data store.

```shell
yd data list [options] [<remote-path> ...]
```

If no remote paths are specified, the configured prefix is listed.

Remote paths support `{{variable}}` substitution and may also contain wildcard characters (`*`, `?`, `[…]`). Only entries in the configured prefix whose names match the pattern are listed. With `--recursive`, matching directories are expanded into full trees.

A path that does not exist, or a remote that cannot be reached, is an error: it is reported, the other paths are still listed, and the command exits 1. An empty directory, and a wildcard that matches nothing in a directory that exists, are empty listings rather than errors. A path given twice is listed once.

Key options:
- `--recursive`/`-R` — list recursively; output is displayed as a directory tree
- `--long`/`-l` — long listing, showing file sizes and modification timestamps
- `--json` — emit the listing as a JSON array of rclone `lsjson` entries; not with `--long`, since the entries carry sizes and times anyway (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd data list -Rl 'results_*'
```

### yd data delete

The `yd data delete` command deletes files or directories from a remote data store.

```shell
yd data delete [options] [<remote-path> ...]
```

If no remote paths are specified, `--recursive` deletes the entire configured prefix; without `--recursive` that is refused. The remote's root and the configured bucket itself are never deleted (with `--no-prefix`, the 'prefix' is the bucket, or the root), nor is a wildcard over the remote's root: the command refuses them before deleting anything (exit 2).

Remote paths support `{{variable}}` substitution and may also contain wildcard characters (`*`, `?`, `[…]`). The wildcard is expanded first and the matched names are displayed; confirmation is then requested, and exactly the items shown are deleted — anything that starts matching in the meantime is left alone. A directory, given or matched, requires `--recursive`, and without it is an error. A path that does not exist, or a wildcard that matches nothing, is skipped with a warning, so a deletion of something already gone succeeds. A failed deletion is reported and recorded, the other paths are still attempted, and the command then exits 1.

Key options:
- `--recursive`/`-R` — recursively delete a remote directory tree
- `--dry-run`/`-D` — show what would be deleted, without deleting
- `--json` — emit the deletions, or with `--dry-run` the matched items, as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))
- `--yes`/`-y` — skip confirmation prompts

```shell
yd data delete 'results_*' --dry-run
```

### yd data copy

The `yd data copy` command copies files or directories between remote data client locations. Both source and destination are remote paths; no local files are involved.

```shell
yd data copy [options] <src-path> <dst-path>
```

`<src-path>` and `<dst-path>` are paths relative to their respective configured `remote:bucket/prefix` base paths. Both support `{{variable}}` substitution. The source remote is configured via the standard data client options. The destination is built from the configuration file's `[dataClient]` section and the `YD_DATA_CLIENT_*` environment variables, or from the profile `--dst-profile` names, with `--dst-prefix` in place of its prefix: the source's command-line options (`--remote`, `--bucket`, `--prefix`, `--no-prefix`, `--profile`) do not reach it. A source that does not exist is an error, reported before anything is copied, as is a directory given without `--recursive`.

Key options:
- `--dst-profile <name>` — use a named `[dataClient.<name>]` TOML profile for the destination (inherits unset fields from `[dataClient]`)
- `--dst-prefix <prefix>` — override the destination path prefix; pass `''` to place files at the bucket root
- `--sync` — mirror the source directory to the destination, deleting destination files not present in the source (implies `--recursive`); not for a single file, and not to a remote's root or the destination bucket itself
- `--recursive`/`-R` — copy a directory, recursively; a directory given without it is an error
- `--dry-run`/`-D` — show what would happen, without performing any transfers; with `--sync`, also each destination file that would be deleted
- `--json` — emit the files copied as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```bash
# Copy a file to a new location within the same prefix
yd data copy input/data.csv output/data.csv

# Rename a file while copying (destination path does not end with '/')
yd data copy results/output.csv archive/output-{{date}}.csv

# Copy a directory to a different prefix on the same remote
yd data copy -R --dst-prefix staging input/ input/

# Copy results to a named profile (e.g. a separate bucket defined in config.toml)
yd data copy -R --dst-profile production results/ results/

# Sync a directory to a backup profile (deletes destination files not in source)
yd data copy --sync --dst-profile backup data/ data/

# Copy from outside the configured prefix using --no-prefix (the destination
# keeps the configured prefix: --no-prefix applies to the source alone)
yd data copy --no-prefix shared/configs/base.json configs/base.json

# Dry-run to preview what would be copied without transferring anything
yd data copy -R --dry-run input/ output/
```

## yd cloudinfo

The `yd cloudinfo` verbs list what the YellowDog Platform knows about the cloud providers: their regions and sub-regions (availability zones), their instance types, and the instance types' prices. They answer questions such as which instance types with 4 to 8 vCPUs and at least 16 GiB of RAM are offered in a region, and which of them is cheapest on spot.

```shell
yd cloudinfo <regions|sub-regions|instance-types|prices> [options]
```

Region and sub-region names are matched exactly, so `--region eu-west-2` does not include the Wavelength Zone `eu-west-2-wl1-lon1`; `--name` takes a glob pattern, and a value without wildcards matches the name exactly. Each option applies only to the verbs listed against it below, and the others do not offer it (it is refused if given).

Key options:
- `--provider`/`-p <aws|azure|google|oci>` — list only this provider's items; may be repeated (every verb)
- `--region <region>` — the region (sub-regions, instance-types, prices); prices need `--region` or `--name`, since every region's prices together are far too many to fetch
- `--sub-region <sub-region>` — the sub-region, which needs `--region` (instance-types, prices); prices for a sub-region include the region's on-demand prices, which apply to every sub-region
- `--name <glob>` — the item's name; for prices, the instance type's (every verb)
- `--vcpus <n|n-m>`, `--ram <GiB|GiB-GiB>` — the number of vCPUs, and the RAM in GiB: `n` exactly, `n-m` inclusive, `n-` at least, `-m` at most (instance-types)
- `--arch <x86_64|arm64>` — the processor architecture (instance-types)
- `--usage <spot|on-demand>` — one kind of price only (prices)
- `--os <none|windows>` — prices for this operating system licence, `none` by default (prices, and instance-types with `--prices`)
- `--prices` — add each instance type's on-demand price and lowest spot price in the region, and the sub-region the spot price is found in; needs `--region` (instance-types)
- `--sort <name|vcpus|ram|price|spot|on-demand>[,...]` — `name` (the default) for every verb, `vcpus` and `ram` for instance types, `price` for prices, `spot` and `on-demand` for instance types with `--prices`; give several keys, separated by commas, to sort by each in turn (`--sort spot,vcpus`: cheapest first, the smaller of equally priced types first); items without a value for a key come after those with one, with `--reverse` too
- `--reverse` — reverse the whole order `--sort` gives
- `--count`/`-C` — print only the number of items
- `--json`/`-J` — emit the items as a JSON array (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd cloudinfo instance-types --region eu-west-2 --vcpus 4-8 --ram 16- --prices --sort spot
yd cloudinfo prices --region eu-west-2 --name 't3.*' --usage spot
yd cloudinfo sub-regions --provider aws --region us-east-1
```

Prices are per hour, as the Platform reports them, in the currency it gives them in.

| Verb | What it does | Replaces |
|---|---|---|
| [`regions`](#yd-cloudinfo-regions) | List cloud regions | `yd-cloud-info regions` |
| [`sub-regions`](#yd-cloudinfo-sub-regions) | List cloud sub-regions | `yd-cloud-info sub-regions` |
| [`instance-types`](#yd-cloudinfo-instance-types) | List instance types | `yd-cloud-info instance-types` |
| [`prices`](#yd-cloudinfo-prices) | List instance prices | `yd-cloud-info prices` |

### yd cloudinfo regions

The `yd cloudinfo regions` command lists the cloud providers' regions, with the options described under [`yd cloudinfo`](#yd-cloudinfo).

```shell
yd cloudinfo regions [options]
```

Key options:
- `--provider`/`-p <aws|azure|google|oci>` — list only this provider's regions; may be repeated
- `--name <glob>` — the region's name

```shell
yd cloudinfo regions --provider aws
```

### yd cloudinfo sub-regions

The `yd cloudinfo sub-regions` command lists the cloud providers' sub-regions (availability zones), with the options described under [`yd cloudinfo`](#yd-cloudinfo).

```shell
yd cloudinfo sub-regions [options]
```

Key options:
- `--region <region>` — the region whose sub-regions to list
- `--provider`/`-p <aws|azure|google|oci>` — list only this provider's sub-regions; may be repeated

```shell
yd cloudinfo sub-regions --provider aws --region us-east-1
```

### yd cloudinfo instance-types

The `yd cloudinfo instance-types` command lists the cloud providers' instance types, with the options described under [`yd cloudinfo`](#yd-cloudinfo).

```shell
yd cloudinfo instance-types [options]
```

Key options:
- `--vcpus <n|n-m>`, `--ram <GiB|GiB-GiB>` — the number of vCPUs, and the RAM in GiB
- `--prices` — add each instance type's on-demand price and lowest spot price in the region; needs `--region`

```shell
yd cloudinfo instance-types --region eu-west-2 --vcpus 4-8 --ram 16- --prices --sort spot
```

### yd cloudinfo prices

The `yd cloudinfo prices` command lists the instance types' prices, with the options described under [`yd cloudinfo`](#yd-cloudinfo).

```shell
yd cloudinfo prices [options]
```

Key options:
- `--usage <spot|on-demand>` — one kind of price only
- `--name <glob>` — the instance type's name; prices need `--region` or `--name`

```shell
yd cloudinfo prices --region eu-west-2 --name 't3.*' --usage spot
```

## Other Commands

These commands act on no one kind of object, and are named by their `yd` word alone: `yd list`, `yd show`, `yd follow` and `yd wait` take any type of object, and the rest are utilities.

### yd list

The `yd list` command lists various YellowDog items in the configured `namespace`. Work Requirements, Worker Pools and Compute Requirements are listed with the configured `tag`, selected as the commands acting on them select them when given no names (Work Requirements and Compute Requirements by their tag, Worker Pools by the tag in their name), so a listing shows what `yd workrequirement cancel`, `yd workerpool shutdown` or `yd computerequirement terminate` would consider; give `--tag ''` (or `-t` alone) to list the whole namespace. Templates and Image Families, which nothing selects by tag, are listed whatever their names unless `--tag` is given.

```shell
yd list [options] <entity-type>
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

The interactive selections noted above are made only for the readable listing: with `--json`, `--count` or `--ids-only`, every matching parent's items are listed without asking. To list the items of one parent directly — the Task Groups or Tasks of a Work Requirement, the Instances of a Compute Requirement, the Nodes or Workers of a Worker Pool — name it with `--within` (below).

Unambiguous prefix matching is supported — for example `yd list work-r` resolves to `yd list work-requirements`, and `yd list key` resolves to `yd list keyrings`. Single uppercase synonyms also work, e.g. `yd list W` and `yd list K`.

`yd list` has more options than are listed here; use `yd list --help` to inspect the full set. Commonly used options are:

| Option | Description |
|---|---|
| `--details`/`-d` | Show the full JSON representation of selected objects; in some cases this drills into additional detail, e.g. `yd list keyrings --details` allows inspection of the Credentials within the selected Keyrings |
| `--active-only`/`-l` | List only entities in a non-terminated state: Work Requirements (and their Task Groups and Tasks), Worker Pools (and their Nodes and Workers) and Compute Requirements (and their Instances); a Compute Requirement that is still provisioning counts as active |
| `--name <glob>` | List only entities whose name matches the given glob pattern (`*`, `?`, `[...]`), e.g. `yd list work-requirements --name 'myproject-*'` (a name without wildcards matches exactly, so use `*` for partial matches, e.g. `'linux*'` or `'*linux*'`); applies to Namespaces, Work Requirements, Task Groups, Tasks, Worker Pools, Compute Requirements, Compute Requirement/Source Templates, Image Families, Users, Applications, Groups, Roles, Keyrings and Permissions, and is refused for other entity types (for Groups, Roles, Keyrings and Permissions, whose names are optional, any entries without a name are excluded from matching, with a warning); it's also a non-destructive way to preview which entities a glob passed to `yd workrequirement cancel`, `yd workerpool shutdown` or `yd computerequirement terminate` would select |
| `--status <status>[,...]` | Include only entities whose status matches (case-insensitive); several statuses may be given separated by commas, or by repeating the option, e.g. `yd list tasks --status failed,aborted,cancelled`. Applies to the entity types that have a status: Work Requirements, Task Groups, Tasks, Worker Pools, Nodes, Workers, Compute Requirements and Instances |
| `--ids-only`/`-D` | Print only the YellowDog IDs of the listed entities, one per line. Like `--json`, this lists non-interactively: e.g. `yd list tasks --ids-only` gives the IDs of all Tasks across all matching Work Requirements and Task Groups. An Instance is given as `<compute-requirement-ydid>.<instance-id>`, the form the `yd instance` verbs take. Refused for attribute definitions, namespace policies and permissions, which have no IDs |
| `--json`/`-J` | Emit the listing as a plain JSON array of summary objects (mutually exclusive with `--ids-only`) |
| `--count`/`-C` | Print only the number of matching items. Implies `--quiet`, and overrides `--details`, `--json` and `--ids-only`. Like `--json`, this aggregates non-interactively: e.g. `yd list tasks -C` counts all Tasks across all matching Work Requirements and Task Groups |
| `--sort <name\|created\|status\|namespace>[,...]` | Order listed (and interactively selected) entities by `name` (default), `created` (creation time, earliest first), `status` (status name), or `namespace`. Give several keys, separated by commas, to sort by each in turn: `--sort namespace,status,created` groups by namespace, then by status within it, then by age; the name (for Instances the instance type, for Nodes and Workers the Worker Pool name, for Tasks the task number) breaks any tie that remains. `created`, `status` and `namespace` apply to entities exposing those fields, e.g. Work Requirements, Compute Requirements, Worker Pools; a key an entity type lacks is passed over. This is a global option, so it also affects the numbered selection lists shown by commands such as `yd workrequirement cancel`, `yd workrequirement hold` and `yd workrequirement start` |
| `--reverse` | List items in reverse (descending) order: the whole order `--sort` gives, every key's included |
| `--public-ips-only` | With `instances`, list public IP addresses only; it cannot be combined with `--json`, `--ids-only` or `--details` |
| `--unhealthy` | List only the Work Requirements, Worker Pools or Compute Requirements the Platform marks unhealthy |
| `--provider <aws\|azure\|google\|oci\|on-premise>` | List only the Instances, Nodes or Compute Source Templates of that cloud provider, e.g. `yd list instances --provider google` |
| `--description <glob>` | List only the Allowances whose description matches the glob (they have no name), e.g. `yd list allowances --description 'gpu-*'`; a value without wildcards matches the description exactly |
| `--with-errors` | List only the Tasks that recorded an error, whatever their status: not the same as `--status FAILED`, since a Task can complete after an error (on a retry), e.g. `yd list tasks --with-errors --status COMPLETED` |
| `--within <target>` | List the items of one parent, without asking which. For Task Groups and Tasks, a Work Requirement or Task Group: its YellowDog ID, or its name as `wr`, `wr/tg`, `namespace/wr` or `namespace/wr/tg` (as `yd workrequirement abort` takes it), e.g. `yd list tasks --within my-wr/tg-1 --status failed`; Tasks are listed Task Group by Task Group. For Instances, a Compute Requirement; for Nodes, a Worker Pool; for Workers, a Worker Pool or a Node: its YellowDog ID, or (a Node excepted) its name or `namespace/name`, e.g. `yd list instances --within my-cr --public-ips-only`. A name without a namespace is looked for in the configured one. It combines with the other filters and with `--json`, `--count` and `--ids-only`; a target that does not exist exits 6, and the ID of anything else is refused (exit 2) |
| `--limit <n>` | With `tasks`, `instances`, `nodes` or `workers`, which can number in the millions or the tens of thousands, list at most this many (default 1000; `0` lists them all), across every Work Requirement, Task Group, Compute Requirement, Worker Pool or Node listed. The search stops one item past the limit, and when more match a warning on stderr says so, `--quiet` or not, the output (`--json` included) holding the first N. The first N are as the Platform returns them, parent by parent, and `--sort` orders those; the limit counts only the items the filters keep, and Workers' Nodes are read only as far as the Workers listed need. It cannot be combined with `--count`, which is never limited |
| `--deletable` | With `namespaces`, list only the namespaces the Platform can delete: those never populated, e.g. `yd list namespaces --name 'yd-*' --deletable` |
| `--hide-user-data` | With `--details` or `--json`, show each `userData` value (in Compute Source Templates, Compute Requirement Templates and Compute Requirements) as a summary of its size, e.g. `<user data: 4,812 characters, 131 lines>`, rather than the script in full. It applies to `--output-file` too, whose JSON can then no longer be used with `yd resource create` as it is |

```shell
yd list work-requirements --name 'myproject-*' --active-only
```

For Instances and Nodes, `--status`, `--provider` and `--active-only` are passed to the Platform with the search, so only the matching ones are fetched. For Tasks, which can number in the millions, `--status`, `--with-errors` and `--name` are passed to the Platform with the search, so only the matching Tasks are fetched: `--name` as the longest literal part of its pattern (the Platform matches it as a case-sensitive substring), the pattern itself then applied to what comes back.

`--count` fetches no Tasks at all where it can: each Task Group's own summary gives its count, or with `--status` the count of each status, so only `--name` and `--with-errors` need the Tasks themselves. A Task Group's counts are the Platform's, which catch up a few seconds after Tasks are added, so `--count` taken straight after submitting a Work Requirement can be short of the Tasks it holds; a listing of the Tasks themselves is always current.

An option that does not apply to the entity type listed — `--name`, `--status`, `--active-only`, `--ids-only`, `--public-ips-only`, `--unhealthy`, `--provider`, `--description`, `--with-errors`, `--within`, `--limit`, `--deletable` or `--substitute-ids` — is refused (exit code 2), rather than ignored and the whole listing returned. With `--details`, Compute Requirements are shown in full, as Work Requirements and Worker Pools are.

Each of `--auto-select-all`, `--strip-ids`, `--substitute-ids` and `--output-file` turns `--details` on, saying so. `--output-file` asks before replacing an existing file, which `--yes`/`-y` skips. A `--status` value the entity type has no status of is warned of, the warning listing those it has.

The `--substitute-ids`/`-U`, `--strip-ids`, `--auto-select-all` and `--output-file` options are used when capturing existing resources as specifications — see [Generating Resource Specifications using `yd list`](resources.md#generating-resource-specifications-using-yd-list).

### yd show

The `yd show` command shows the details (in JSON) of any YellowDog entity that has a YellowDog ID.

```shell
yd show [options] <yellowdog-id> [<yellowdog-id> ...]
yd show [options] --type <resource-type> <name-or-id> [<name-or-id> ...]
```

With `--type`, a resource can be given by its name instead: Keyrings, Groups and Applications by name; Compute Source and Requirement Templates, Image Families and Configured Worker Pools as `namespace/name`, or by name in the configured namespace; and Users (`--type InternalUser` or `ExternalUser`) by name or username. `yd resource show --type Keyring team-keys` shows the Keyring named `team-keys` as its ID would show it.

The types with no ID are shown by name too, as `yd resource list <type> --details` shows them: a Namespace by its name, a Namespace Policy by its namespace, a String or Numeric Attribute Definition by its name, and a Credential as `keyring/credential` (its name, description and type, as its Keyring holds it).

A name found in more than one namespace, with none configured, is refused as ambiguous rather than one of them shown. A name that finds nothing is not found (exit 6); an Allowance, which has no name, is shown by its ID; and another type's ID, an ID for a type that has none, and, without `--type`, an argument that is not an ID are refused.

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

Instances have no YellowDog ID of their own: they're identified by the combination of their Compute Requirement and their provider-assigned instance ID. An Instance is therefore supplied in `<compute-requirement-ydid>.<instance-id>` form, the same format the `yd instance` verbs take. Only the first `.` separates the two parts, so instance IDs that contain dots of their own (OCI's OCIDs, for example) need no special treatment.

Key options:
- `--namespace` — the namespace a name is looked up in, with `--type` or by a noun's `show` verb (`yd workrequirement show my-wr`); the configured one if not given
- `--show-token` — include the Worker Pool token when showing the details of a Configured Worker Pool
- `--show-source-report` — follow a Compute Requirement with the Platform's report of how its sources were chosen: the Compute Source Templates considered, selected and rejected, each source's rank and score, and the constraints and preferences applied. Only a Compute Requirement provisioned from a dynamic template has one, and it is kept after the Compute Requirement has been terminated; for any other, a warning says so and the Compute Requirement is still shown
- `--show-exhaustion` — follow a Compute Requirement with `{"computeRequirementId", "exhaustedAllowances"}`, the Allowances that are exhausted for it, each with its `allowanceId`, `allowanceDescription` and `exhaustedSourceIds`; an empty list means no Allowance is holding it back (see [`yd allowance boost`](#yd-allowance-boost))
- `--show-members` — follow a Group with `{"groupId", "users", "applications"}`, its Users (each `{"id", "username", "name"}`, `username` being `null` for an external User) and its Applications (each `{"id", "name"}`), or a Role with `{"roleId", "groups"}`, the Groups that hold it (each `{"id", "name"}`); a Group's own roles are already in its details. It is refused unless at least one of the IDs is a Group's or a Role's
- `--hide-user-data` — show each `userData` value (in Compute Source Templates, Compute Requirement Templates, Compute Requirements and Compute Sources) as a summary of its size rather than the script in full, as for `yd list`, `--output-file` included
- `--substitute-ids`/`-U`, `--strip-ids`, `--output-file <file>` — as for `yd list`; see [Generating Resource Specifications using `yd list`](resources.md#generating-resource-specifications-using-yd-list). `--substitute-ids` is refused unless at least one of the IDs is a Compute Source Template's, a Compute Requirement Template's or an Allowance's

A User is always shown with `groups`, the names of the Groups it belongs to, as an Application is and as `yd list users --details` shows them.

`--show-source-report` and `--show-exhaustion` also apply to a Provisioned Worker Pool's ID, reporting on its Compute Requirement after the pool; a Configured Worker Pool, which has no Compute Requirement, is shown with a warning and no reports. Each is refused unless at least one of the IDs is a Compute Requirement's or a Worker Pool's.

At least one ID is required. A YDID names its entity in whatever namespace it is in, so an ID needs no `--namespace` (which applies to a name given with `--type`), and `yd show` takes no `--tag`.

Supplying more than one ID produces a JSON array, whatever the verbosity options say, so that the shape of the output follows what was asked for rather than how much of it succeeded. A single ID produces the object on its own, except when `--show-token` yields both a Configured Worker Pool and its token, `--show-source-report` or `--show-exhaustion` add their reports after a Compute Requirement or Provisioned Worker Pool, or `--show-members` adds a Group's or a Role's members. Combine with `--quiet`/`-q` to suppress the status messages and leave only the JSON on stdout.

It exits with code 0 if every ID was shown; 6 if those that were not all name entities that do not exist; and 1 if any could not be shown for another reason (an invalid ID, or an API error). The IDs that could be shown are still emitted. If a lookup fails because the Application's credentials are not accepted, or the platform cannot be reached, the remaining IDs are not attempted, what was shown is still emitted, and the command exits with that failure's code (4 or 8).

```shell
yd show ydid:compreq:000000:07e0a2c1-3e0a-4b40-9f5b-0b0f81a29b16 --show-source-report --show-exhaustion
yd show ydid:compreq:000000:07e0a2c1-3e0a-4b40-9f5b-0b0f81a29b16.i-0123456789abcdef0
yd show ydid:compreq:000000:07e0a2c1-3e0a-4b40-9f5b-0b0f81a29b16.ocid1.instance.oc1.uk-london-1.anwgiljtbfkcyvycib2ubsewuwqqffx2jzyp7dolkhxanfvdsgvjzjrytepa
```

### yd follow

The `yd follow` command follows the event streams for one or more Work Requirements, Worker Pools and Compute Requirements, specified by their YellowDog IDs. The nouns' `follow` verbs (`yd workrequirement follow my-wr`) take names too, looked up in `--namespace` or the configured namespace, as described at the [top of this page](#command-list); `yd follow` itself takes IDs alone, so its `--namespace` has no effect.

```shell
yd follow [options] <yellowdog-id> [<yellowdog-id> ...]
```

At least one ID is required, and each must be a Work Requirement's, Worker Pool's or Compute Requirement's: anything else is refused before anything is followed (exit code 2). The IDs are followed in the order given, each once.

The command will continue to run until manually stopped using `CTRL-C`, unless all the IDs to be followed are in a terminal state. A stream that drops is reconnected, waiting 5, 10, 20 and then 30 seconds between attempts, for up to five minutes of continuous outage, which ends only once a stream delivers an event, so a connection that is accepted and then drops before any, over and over, is given up on as well; a stream closed while its entity is still live (by a proxy dropping an idle connection, say) is reconnected too, the entity's status being checked when its stream closes.

It exits with code 0 if every stream could be followed. Otherwise it exits with the code of the failure — for example 6 for an entity that does not exist, 4 for credentials that are not accepted, 8 for a connection that could not be made or re-made (see [Machine-readable Output and Exit Codes](json-output.md) for the others) — or 1 if the streams failed for different reasons. This applies to the event streams that other commands follow with `--follow` too, though only `yd follow` takes its exit code from them.

Note that the exit code reflects only whether the event streams could be followed, not the final status of the entities themselves — use `yd wait` (or `yd workrequirement submit --exit-on-failure`) to act on Work Requirement outcomes.

Key options:
- `--progress` — display a live progress bar for Work Requirement IDs (ignored for Worker Pool and Compute Requirement IDs)
- `--auto-follow-compute-requirements`/`-a` — automatically follow the associated Compute Requirements when following Worker Pools
- `--json` — print each event as a JSON document as it arrives, refused with `--progress` (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd follow ydid:workreq:D9C548:37d3c0cd-2651-4779-be17-89a8601b03b8 \
          ydid:wrkrpool:D9C548:c22f0d9a-4a99-460d-ae42-15653ba264c3 \
          ydid:compreq:D9C548:98879b5a-9192-4a56-ad25-fc1330e49185
```

### yd wait

The `yd wait` command waits for one or more Work Requirements, Worker Pools, or Compute Requirements to reach a terminal state, then exits with a status code reflecting the outcome. The nouns' `wait` verbs (`yd workrequirement wait my-wr`) take names too, looked up in `--namespace` or the configured namespace, as described at the [top of this page](#command-list); `yd wait` itself takes IDs alone, so its `--namespace` has no effect.

```shell
yd wait [options] <yellowdog-id> [<yellowdog-id> ...]
```

At least one ID is required, and each must be the ID of a Work Requirement, Worker Pool or Compute Requirement; anything else is refused before anything is followed (exit 2). Multiple IDs can be supplied, and `yd wait` blocks until all of them have reached a terminal state: `COMPLETED`, `FAILED` or `CANCELLED` for a Work Requirement, `SHUTDOWN` or `TERMINATED` for a Worker Pool, and `TERMINATED` for a Compute Requirement. This makes it suitable for scripting pipelines. Use `--quiet`/`-q` to suppress the progress messages and rely on the exit code; an entity that failed or is still live when following ends is reported even then, on stderr. For interactive observation of event streams, use `yd follow` instead.

- **Exit 0** — every entity reached a terminal state, and no Work Requirement ended `FAILED` or `CANCELLED`
- **Exit 1** — a Work Requirement ended `FAILED` or `CANCELLED`, `--timeout` expired with an entity not finished, or there were failures with different causes
- **Exit 4 to 8** — every failure had the one cause, whose code it is: for example credentials not accepted (4), an entity that does not exist (6), or an event stream that could not be connected or reconnected (8)

An entity that is still not in a terminal state when following ends — because `--timeout` expired, or its event stream was lost — is a failure, reported with its current status, never a success.

Key options:
- `--timeout <seconds>` — stop waiting after this many seconds, and fail if anything has not finished (default: no limit)
- `--json` — emit each item's final status as a JSON array of `{"id", "name", "status", "succeeded"}` (see [Machine-readable Output and Exit Codes](json-output.md))

```bash
WR_ID=$(yd workrequirement submit mywork.json --quiet)
yd wait "$WR_ID" && yd data download results/
```

### yd application

The `yd application` command shows the details of the current Application, i.e. the Application represented by the `key` and `secret` being used.

```shell
yd application [options]
```

It takes no positional arguments, and is the quickest way to confirm which Application a set of credentials belongs to.

Key options:
- `--json`/`-J` — emit the Application's details as JSON instead of the readable report

```shell
yd application --config prod.toml
```

The JSON output contains the Application's properties, plus `portalUrl`, `groups` and `roles`, in alphabetical order. Each of these three is `null` when it can't be determined.

`portalUrl` is derived from the Platform API URL as every Portal link the commands print is: a hostname label that is exactly `api` becomes `portal` (so `https://api.yellowdog.ai` gives `https://portal.yellowdog.ai`), and any other URL, such as `https://host/api`, is used as it is; it is `null` only when the account's name is not known.

`groups` and `roles` are `null` when the Application lacks the permissions required to look them up, which is not a failure, and `groupsAndRoles` is then added, saying `"permission denied"`; an Application in no groups, or with no roles, has `[]` or `{}` (the readable report says `none`); if the lookup fails for any other reason they are `null` too, a warning naming the failure is printed (on stderr, under `--json`), and the command exits with that failure's [exit code](json-output.md) once the rest has been reported.

```shell
yd application --json
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

### yd variables

The `yd variables` command reports the processed values of variable substitutions, as JSON. It shows what a specification file would actually see, once the TOML configuration file, the environment, any `YD_VAR_*` variables, any `--variable`/`-v` options and the built-in defaults have all been taken into account, which makes it the quickest way to debug a variable substitution setup.

```shell
yd variables [options] [<var> ...]
```

Only the named variables are reported if any names are supplied; every variable is reported otherwise. The output is a JSON object keyed by variable name, in alphabetical order. As with `yd show`, it is preceded by any warnings and followed by `Done`; pass `--quiet`/`-q` to get the JSON alone, for example to pipe it into another program.

A name that isn't the name of a variable reports `null`, with a warning that it is not defined, so the command also answers whether a variable is set at all; a name no variable could have, such as `{{tag}}` or `env:HOME`, is refused. `yd variables` never contacts the Platform, so it needs no application key or secret: when they are not configured, `key` and `secret` are reported as `null`.

```shell
yd variables                           # report every variable
yd variables namespace tag             # report only these two
yd variables -v instances=5 instances  # report a variable set on the command line
```

```json
{"namespace": "my-namespace", "tag": "my-tag"}
```

The report redacts the values of `key` and `secret`, replacing each with `<REDACTED>`, and shows an inline data client remote (`dataClient.remote`, or a profile's `dataClient.<name>.remote`) with its name, type and provider only, every other parameter's value withheld as `<N parameters redacted>`, because those parameters are where an inline remote's credentials go; a named remote such as `myremote:` is shown as it is.

This applies whether the variables are named or not, and only `--show-secrets` reports their values; naming `key` or `secret` prints a line saying they were redacted. Naming a variable does not report it in full, so that a caller unable to pass `--show-secrets`, such as the [MCP server](../yellowdog_cli/mcp/README.md)'s tools, cannot ask for a credential by name.

```shell
yd variables                 # 'key' and 'secret' are reported as <REDACTED>
yd variables --show-secrets  # every variable, credentials included
yd variables key secret      # still <REDACTED>, with a line saying so
yd variables --show-secrets key secret  # reported in full
```

A reported variable whose value still contains a reference to a variable that is not defined is reported as it stands, and a [warning](variables.md#undefined-variables) naming it is printed ahead of the JSON. The same applies to the configuration's `namespace`, `tag` and `url`; `key` and `secret` are never checked. `--quiet` suppresses the warnings along with `Done`.

```shell
yd variables -v 'bucket=s3://{{regoin}}' bucket
```

```
WARNING : Variable '{{regoin}}' is not defined, and has been left unsubstituted in 'bucket'
```

A variable that was defined but has been removed by the [unset syntax](variables.md#removing-properties-using-the-unset-suffix) (`{{::}}`, or `{{name::}}` for a `name` that is not defined) is reported as `null` when named, and left out of the full report. So that this can be told apart from a variable that was never defined, a warning also gives the reason, following each `{{name::}}` reference to a variable that was itself unset:

```shell
yd variables -v 'site={{::}}' -v 'pool={{site::}}-p' pool
```

```
WARNING : Variable 'pool' is unset: 'pool' refers to '{{site::}}', and 'site' is unset; 'site' is '{{::}}', which always unsets it
```

**Variables whose names look like credentials are redacted too, and the command says so.** `key`, `secret` and the inline remotes are the only variables the CLI can *know* hold credentials: it adds them to the substitution table itself when it loads the configuration, and the rclone connection string's format says which part of it is parameters.

Beyond them, the report also redacts any variable of your own — defined in `[common.variables]`, via a `YD_VAR_*` environment variable, or with `--variable`/`-v` — whose name contains `secret`, `password`, `passwd`, `token`, `credential` or `private_key`, in any case, and when it does it prints one line ahead of the JSON saying so: `Redacted N variable(s) whose names match 'secret|password|passwd|token|credential|private_key' (case-insensitive); everything else is shown in full. --show-secrets reports all.` (not under `--quiet`, which leaves the JSON alone). As with the others, this applies to a variable named on the command line too, and `--show-secrets` reports them all.

**A variable whose value holds the configured key or secret is redacted too.** Whatever it is called, a variable defined as `{{secret}}`, or as text holding it (`Bearer {{secret}}`), is the credential, so it is reported as `<REDACTED>`, and the command says so ahead of the JSON: `Redacted N variable(s) whose values hold the configured key or secret. --show-secrets reports all.`

**A variable of your own holding an inline rclone connection string is shown as the data client remotes are.** Whatever it is called, a variable whose value is an inline connection string — `NAME,type=...` or rclone's own `:backend,...` form, with or without a leading `rclone:` and a trailing `:path` — is shown with its prefix, name, type and provider, every other parameter's value (and a trailing path) withheld as `<N parameters redacted>`, so `remote_with_keys = "rclone:S3,type=s3,provider=AWS,access_key_id=...,secret_access_key=...,region=eu-west-2"` is reported as `rclone:S3,type=s3,provider=AWS,<3 parameters redacted>`.

A value with a comma in it that has neither form, such as `a,b` or `x,y=z`, is shown in full. When this withholds anything the command says so ahead of the JSON: `Withheld the parameters of N variable(s) holding an inline rclone connection string, keeping its name, type and provider. --show-secrets reports all.` `--show-secrets` reports it in full.

This is a heuristic, and the note is there so that it is not mistaken for a guarantee. `key` on its own is deliberately not in the pattern, so `APP_KEY_DEMO`, an application key's identifier rather than its secret, is shown in full; and a credential held under a name the pattern does not match, such as `APP_CREDS`, is shown in full too. Keeping a credential like that out of a report you send somewhere it will persist is up to you: name the variables you want, or rename the one holding it so that the pattern matches it.

None of `yd completion`, `yd init`, `yd help`, `yd version`, `yd schema`, `yd format-json` and `yd jsonnet2json` requires a configuration file or YellowDog credentials, and none accepts the [Universal Options](#universal-options) other than `--no-format`, which `yd init`, `yd help`, `yd version`, `yd schema` and `yd jsonnet2json` accept (`yd version`'s `--debug` is an option of its own, adding the Python executable and path); `yd doctor` is the exception here, since checking a configuration or a set of credentials means accepting the options that name them, but it never exits on one that is missing or broken — that is what it exists to report.

### yd init

The `yd init` command writes a starter configuration file: `config.toml` in the current directory, or with `--user` your own, `~/.config/yellowdog/config.toml`, which every directory without a `config.toml` of its own reads (see [Configuration](configuration.md)). It asks for the Application key ID and secret (the secret typed without being shown), the namespace, the tag and the Platform API URL, offering the value of `YD_KEY`, `YD_SECRET`, `YD_NAMESPACE`, `YD_TAG` or `YD_URL` for Enter to keep, and writes them to its `[common]` section; a value given none is written commented out, so the file shows where it would go. A file holding the secret is readable by its owner alone. Run `yd doctor` afterwards to check it.

```shell
yd init [options]
```

- `--user`: write your own configuration file, `~/.config/yellowdog/config.toml` (`$XDG_CONFIG_HOME/yellowdog/config.toml` where that is set), rather than `config.toml` in the current directory
- `--overwrite`: replace the file if it exists; without it, an existing file is refused (exit 1) before anything is asked
- `--yes`, `-y`: ask nothing, taking each value from its environment variable and leaving any not set commented out
- `--no-format`: print the messages without colouring

### yd doctor

The `yd doctor` command checks whether this machine, this configuration and these credentials can run the CLI, and reports each check as `OK`, `WARN`, `FAIL` or `SKIP` with a remedy for anything wrong. It is the first thing to run when a command fails unexpectedly, and its output is what to include in a support request: the secret is shown redacted, and an inline data client remote with its name, type and provider only, every other parameter's value withheld.

```shell
yd doctor [options]
```

It checks, in order:

- the Python version and how the CLI was installed
- the CLI and SDK versions, and whether the SDK imports (one that will not is reported here, and the checks that need it are skipped, rather than the doctor failing to start)
- each optional extra (Jsonnet, Cloud Wizard, Commander, the MCP Server), distinguishing "not installed" from "installed but will not load"
- the rclone version
- whether the `yd` first on your `PATH` is this installation's: another `yd`, such as a different tool of the same name, would run in its place, and Tab completion would ask it
- whether your shell's start-up file (`~/.zshrc`, `~/.bashrc` or `~/.bash_profile`, or fish's `config.fish`) loads [`yd completion`](#yd-completion), and with `--names` (names and IDs from the Platform) or without, or runs `yd-completion` instead, which is not a command. The file is read, not run, so a line in a file it sources is reported as not set up
- the proxy and certificate settings (the proxy row reports `HTTPS_PROXY` and, when PAC is on, the proxy PAC resolves for the API URL, or a `WARN` when it resolves none; the live checks, the PyPI one included, then use that proxy)
- whether a newer CLI is on PyPI
- whether the configuration file loads and follows the configuration schema (a `WARN` naming the first few problems, as every command warns of them; see [Configuration](configuration.md)), and where each of the key, secret, namespace, tag and URL came from
- undefined variable references
- the `.env` file in use
- whether the tag is a legal name
- each data client profile

and then, live:

- whether the Platform API is reachable (a `WARN` if it answers with a server error)
- whether the credentials are accepted (naming the Application, its groups and roles, or why not: the key or secret not recognised, the Application without a role, the connection, or a server error)
- whether the configured namespace is readable by the Application
- whether the data client's remote can be reached at the configured prefix, where the data client commands work (a prefix not created yet is `OK` if its bucket is there, and a bucket that is not there is a `FAIL`)

A check that cannot run says why (`SKIP`) rather than disappearing.

Unlike other commands, `yd doctor` never exits on a missing or broken configuration: that is reported as a row.

A long detail or remedy wraps at the terminal's width, its continuation lines indented under its own column, only on a terminal; when piped or redirected, and under `--no-format`, every row and every remedy is one line, for grep and pasting.

Key options:
- `--offline` — skip every check that reaches the network (PyPI, the Platform API, the data store)
- `--json`/`-J` — emit the results as a JSON array, one object per check, for scripts
- `--timeout <seconds>` — the budget for each network call (default 10)
- `--quiet`/`-q` — print only the `WARN` and `FAIL` lines and the summary

```shell
yd doctor                    # everything, against the current configuration
yd doctor --offline          # no network calls
yd doctor --json | jq '.[] | select(.status == "FAIL")'
```

The exit code is 1 if any check failed, else 0, so it can gate a script or a CI job.

### yd help

The `yd help` command lists all available `yd` commands and their purposes, `yd commander` and `yd mcp` included, with the extra each command that needs one requires, or `(<extra> extra installed)` where it is installed already, and closes with how to see a command's options and where the documentation is.

```shell
yd help [--json] [--deprecated] [--no-format]
```

The listing is coloured on a terminal, with the command names and the notes on extras picked out; `--no-format`/`--nf` prints it plain, as it is when piped. `--deprecated` lists the deprecated `yd-*` commands and the `yd` forms that replace them. With `--json` it prints every command as a JSON array of `{"command", "summary"}`: a noun adds `"alias"` (its short form, or `null`) and `"verbs"` (each `{"verb", "summary", "replaces"}`), a deprecated `yd-*` command `"deprecated": true` and `"replacedBy"` (its `yd` forms), and a command needing an extra `"extra"` and `"installed"`; the array is coloured on a terminal unless `--no-format` is given (see [Machine-readable Output and Exit Codes](json-output.md)).

### yd version

The `yd version` command reports the versions of the CLI, the YellowDog SDK, Python, and (if installed) Jsonnet, the rclone binary and the MCP SDK used by `yd mcp` as a table, followed by the CLI's author, licence and documentation link.

```shell
yd version [options]
```

Key options:
- `--cli`, `--sdk`, `--python`, `--jsonnet`, `--rclone`, `--mcp` — mutually exclusive; each prints just that bare version number, for use in scripts
- `--debug` — print the Python path and executable details, as a second table (note that this differs from `--debug` on other commands, which prints a stack trace on error); with the full report or `--json` only, not with a single-version option
- `--no-format`, `--nf` — print the report, or the `--json` object, without colouring, as it is when piped or redirected
- `--json` — print the versions, author and licence as a JSON object, `null` for a component not installed or whose version could not be read; with `--debug`, the Python executable and path too (see [Machine-readable Output and Exit Codes](json-output.md))

```shell
yd version           # report all versions
yd version --cli     # print the CLI version number only
yd version --rclone  # print the rclone binary version only
```

The rclone version is detected using the same lookup order as `yd workrequirement submit --which-rclone` (system `PATH` first, then the `rclone_api` download cache) without triggering a download; an rclone binary that does not answer within 5 seconds is reported as `unknown`. Each single-version option prints nothing and exits 1 if its component is not installed, or its version could not be read, so a script never takes `Not installed` or `unknown` for a version number. The documentation link is the release's own README, or `main`'s for a development build.

### yd format-json

The `yd format-json` command reformats JSON files in place using the CLI's compact JSON encoder (small containers on a single line, larger ones indented). Files not named `*.json` are skipped, each with a message.

```shell
yd format-json [--check] <file.json> [<file.json> ...]
```

Only the layout changes: numbers are written back exactly as they were written (`1.10` stays `1.10`), non-ASCII text is kept rather than escaped, and a file that repeats a key is refused, and left as it is, rather than losing all but one of them. A file is replaced only once its new text is complete, keeping its permissions, so an interruption leaves the original; a file already in this layout is left untouched. `--check` writes nothing, reporting the files that would be reformatted, and exits 1 if there are any, for use in CI. A file that cannot be read, parsed or written is reported on stderr, the others are still processed, and the command exits 1.

```shell
yd format-json my_file.json my_other_file.json
```

### yd jsonnet2json

The `yd jsonnet2json` command converts Jsonnet files to JSON without any additional processing by the CLI (no variable substitution, no property expansion). With a single (non-glob) argument, the resulting JSON is written to stdout, coloured on a terminal unless `--no-format`/`--nf` is given; with multiple arguments or a glob pattern, each file is converted and written to a `<name>.json` file alongside its source.

```shell
yd jsonnet2json [--yes] [--no-format] <file.jsonnet> [<file.jsonnet> ...]
```

```shell
yd jsonnet2json my_spec.jsonnet                 # JSON to stdout
yd jsonnet2json spec_1.jsonnet spec_2.jsonnet   # writes spec_1.json, spec_2.json
yd jsonnet2json 'specs/*.jsonnet'               # writes a .json file per match
```

Errors go to stderr, so a failed conversion piped to a file never leaves an error message in it, and the command exits 1.

Each `.json` file is replaced whole or not at all, keeping an existing file's permissions. Every file is converted before any is written: an existing `.json` file that already holds what the conversion produces is reported as unchanged and left alone, and the others that would be replaced are listed and confirmed with one prompt, since a `.json` file of that name may be a file of its own rather than an earlier conversion. Declining keeps them and still writes the new files; `--yes`/`-y` overwrites without asking, and without a terminal to answer from the command writes nothing and exits 1, naming `--yes`.

Non-ASCII text is kept as it is rather than escaped. A pattern that matches nothing is reported as such, and a file named twice, or matched by more than one pattern, is converted once.

With several files or a glob pattern, a file not named `*.jsonnet` is skipped, with a message. Converting needs the `jsonnet` extra; without it the command exits 1, saying how to install it. A Jsonnet `import` is found beside the file importing it, not in the current directory.

This is the quickest way to verify that a Jsonnet file is syntactically correct and produces the expected JSON structure. For full variable substitution and property expansion, use `--jsonnet-dry-run` or `--dry-run` on the relevant command instead.

See [Jsonnet Support](jsonnet.md) for installation and usage.

### yd schema

The `yd schema` command prints the JSON Schema a specification family must follow, generated from the CLI's own registry and the installed YellowDog SDK: `work-requirement` (what `yd workrequirement submit` accepts), `worker-pool` (`yd workerpool provision`), `compute-requirement` (`yd computerequirement instantiate`), `resources` (`yd resource create`), `node-actions` (`yd node action`) and `config` (the TOML configuration file every command reads; see [Configuration](configuration.md)). It needs no configuration file and no credentials.

```shell
yd schema <family>            # print one family's schema as JSON
yd schema --write <dir>       # write every family's schema, and index.json, to <dir>
yd schema --check <dir>       # exit 0 if <dir> matches the installed CLI and SDK, else 1
yd schema --list              # list the family names
```

A schema printed to a terminal is coloured unless it is longer than 5,000 lines (the `resources` family is); `--no-format`/`--nf` prints it plain, as it is when piped or redirected.

Exactly one of a `<family>`, `--write <dir>`, `--check <dir>` or `--list` must be given. `--write` writes `<family>.schema.json` for every family into `<dir>`, plus an `index.json` naming the CLI and SDK versions that generated them, and exits 1 naming the path if `<dir>` cannot be created or written; point an editor's JSON Schema support (VS Code's `json.schemas`, JetBrains' JSON Schema mappings) at the files it writes.

After upgrading the CLI or the SDK, `yd schema --check <dir>` says whether a written directory is still current — the versions in its index, and every family's file, which must be there and be exactly what the installed CLI and SDK build, so a file edited or missing is reported — and `yd schema --write <dir>` again refreshes it.

A family printed with `yd schema <family>` is exactly what `--write` writes for it (coloured when printed to a terminal, unless `--no-format` is given, so piped or redirected it is the same bytes), and each file is replaced whole or not at all. Every schema also accepts a `{{variable}}` substitution, the `{{name::}}` unset form included, wherever a plain value is otherwise expected.

### yd completion

The `yd completion` command prints a shell completion script for `yd`, for bash, zsh, fish or PowerShell. Once it is loaded, pressing Tab completes:

- The word after `yd`: `yd w` → `wait`, `worker`, `workerpool`, `workrequirement`, `wp`, `wr`.
- A noun's verbs: `yd wr s` → `submit`, `start`, `show`.
- The options a command or verb takes, never one it does not.
- An option's fixed choices. A resource type after `--type` is completed in any case, and offered in lower case when that is what is being typed, so `--type k` completes to `keyring`.
- The keys `--sort` takes, each after a comma too.
- The entity types `yd list` takes.
- Local files and directories, for the options and arguments that name one, such as a specification file or `--config`.
- With `--names`, Work Requirements, Worker Pools and Compute Requirements from the YellowDog Platform, as [described below](#names-and-ids-from-the-platform).

Where the shell shows descriptions (zsh, fish and PowerShell), each verb is shown with its summary and each option with its help.

The deprecated `yd-*` commands, such as `yd-submit`, are not completed. `yd commander` and `yd mcp` complete by name, and their arguments as local files, as the shell would without the script, but not their options.

```shell
yd completion bash | zsh | fish | powershell [--names]
```

Load the script in the shell's start-up file, so that every new shell has it:

```shell
eval "$(yd completion bash)"     # in ~/.bashrc
eval "$(yd completion zsh)"      # in ~/.zshrc, after compinit if it is run there
yd completion fish | source      # in ~/.config/fish/config.fish
```

```powershell
yd completion powershell | Out-String | Invoke-Expression    # in $PROFILE
```

The script asks `yd completion` what completes the word on each Tab, so it follows the installed CLI: upgrading the CLI needs no new script. Completing anything but a name or an ID on the Platform needs no configuration file and no credentials, and contacts nothing.

#### Names and IDs from the Platform

Tab offers the names and IDs of what is on the Platform when the script is printed with `--names`; without it, which is the default, completion is local only and contacts nothing. Load that script in place of the one without:

```shell
eval "$(yd completion bash --names)"     # in ~/.bashrc
eval "$(yd completion zsh --names)"      # in ~/.zshrc
yd completion fish --names | source      # in ~/.config/fish/config.fish
```

```powershell
yd completion powershell --names | Out-String | Invoke-Expression    # in $PROFILE
```

[`yd doctor`](#yd-doctor) says whether the start-up file's line has `--names`.

Where a verb takes Work Requirements, Worker Pools or Compute Requirements, Tab then offers them from the Platform. Every such verb offers their names: `yd workrequirement cancel`, `hold`, `start`, `finish` and `priority`, `yd workerpool resize`, `shutdown` and `token`, `yd computerequirement resize`, `stop`, `start`, `reprovision`, `autoshutdown` and `terminate`, and `show`, `follow` and `wait` on each of the three, with `yd workrequirement compare` (its Worker Pools too). `yd taskgroup show`, `compare` and `priority` offer Work Requirement names, then after `wr/` that Work Requirement's Task Groups, as `wr/tg`, and `yd taskgroup compare` offers Worker Pools too. An ID is still taken wherever a name is.

What is offered is what the command would act on. The namespace and tag are the command's own, from the configuration file, the environment and any `--config`, `--namespace` or `--tag` (and the other configuration options) typed earlier on the same line; Work Requirements and Compute Requirements are selected by tag, and Worker Pools by the tag in their name, as [`yd list`](#yd-list) lists them; type `--tag ''` (or `-n` and `--tag` with other values) before the Tab to widen or move what is offered, for example to reach a Configured (on-premise) Worker Pool, whose name was given by hand. A verb that takes no `--tag`, such as `show`, uses the configuration's tag.

Only the statuses the verb applies to are offered (for example, running Work Requirements for `hold` and held ones for `start`), except by `show`, which offers every status. At most the 200 newest are offered, in whatever order the shell lists them.

A Tab waits at most two seconds for the Platform; past that, or if there is no configuration, no credentials or no connection, nothing is offered and nothing is printed. Where nothing is found after a verb with nothing yet typed, its options are offered instead. What is found is kept for 30 seconds, so the Tabs that follow answer at once (finding nothing is not kept, so a Work Requirement just submitted is offered on the next Tab); an entity that changed in that time may still be offered, and the command reports it when run. The cache is a file per lookup in a directory of your own (readable only by you) under the system's temporary directory, holding names, IDs and statuses but no credentials, and each new lookup removes those older than 30 seconds, so there is nothing to clear.

To switch the lookups off for a while without editing the start-up file, for example on a slow connection, set `YD_COMPLETION_LOOKUPS` to `off` (or `0`, `false` or `no`); it cannot switch them on for a script printed without `--names`:

```shell
export YD_COMPLETION_LOOKUPS=off
```

Proxy auto-configuration (`--pac`, `usePAC`) is not used for a Tab, since fetching the proxy configuration on every Tab would be too slow; a proxy set in `HTTPS_PROXY` is used. Tasks, Instances, Nodes and Workers are not completed from the Platform, nor are option values naming an entity other than `--within`'s, nor the IDs given to the generic `yd show`, `yd follow` and `yd wait`.

The value of [`yd list`](#yd-list)'s `--within` is completed too, with the names of what it lists within: Work Requirements for `yd task list` and `yd taskgroup list` (or `yd list tasks` and `yd list task-groups`), then, once `wr/` is typed, that Work Requirement's Task Groups as `wr/tg`; Compute Requirements for `yd instance list`; and Worker Pools for `yd node list` and `yd worker list`. Since `--within` finds a name in the namespace whatever its tag, these are offered in any status and whatever the tag, at most the 200 newest.

After `--type`, the names or IDs [`yd resource remove`](#yd-resource-remove), `yd resource show` and `yd show` take are completed too, for that resource type:

- Keyrings, Groups, Applications, Namespaces, Namespace Policies (by namespace), Attribute Definitions and Users (by username), by name.
- Compute Source and Requirement Templates, Image Families and Configured Worker Pools, by name in the configured namespace.
- Credentials: their Keyring, then, once `keyring/` is typed, its Credentials as `keyring/credential`.
- Allowances, which have no name, by ID, each shown with its description.

At most the first 200 are offered.

## Deprecated Commands

The `yd-*` commands are deprecated in favour of `yd` and the words after it, and will be removed in a future release. Until then each still runs, with a warning on stderr naming what to use instead (`--quiet` suppresses it where the command has it); the warning is not given when Commander or the MCP server runs a command. `yd help --deprecated` gives the same table.

Where a command acts on more than one kind of object, each kind has a verb of its own: `yd-terminate` takes Compute Requirements, Instances and Nodes, which `yd computerequirement terminate`, `yd instance terminate` and `yd node terminate` take between them, and `yd-resize -C` is `yd computerequirement resize`.

| Deprecated command | Use instead |
|---|---|
| `yd-abort` | `yd task abort` |
| `yd-application` | `yd application` |
| `yd-boost` | `yd allowance boost` |
| `yd-cancel` | `yd workrequirement cancel` |
| `yd-cloud-info` | `yd cloudinfo regions`, `yd cloudinfo sub-regions`, `yd cloudinfo instance-types`, `yd cloudinfo prices` |
| `yd-cloudwizard` | `yd cloudwizard` |
| `yd-commander` | `yd commander` |
| `yd-compare` | `yd workrequirement compare`, `yd taskgroup compare` |
| `yd-compute-deprovision` | `yd instance deprovision`, `yd node deprovision` |
| `yd-compute-reprovision` | `yd computerequirement reprovision` |
| `yd-compute-restart` | `yd instance restart`, `yd node restart` |
| `yd-compute-start` | `yd computerequirement start`, `yd instance start`, `yd node start` |
| `yd-compute-stop` | `yd computerequirement stop`, `yd instance stop`, `yd node stop` |
| `yd-copy` | `yd data copy` |
| `yd-create` | `yd resource create` |
| `yd-delete` | `yd data delete` |
| `yd-doctor` | `yd doctor` |
| `yd-download` | `yd data download` |
| `yd-finish` | `yd workrequirement finish` |
| `yd-follow` | `yd follow` |
| `yd-format-json` | `yd format-json` |
| `yd-help` | `yd help` |
| `yd-hold` | `yd workrequirement hold` |
| `yd-instantiate` | `yd computerequirement instantiate` |
| `yd-jsonnet2json` | `yd jsonnet2json` |
| `yd-list` | `yd list` |
| `yd-ls` | `yd data list` |
| `yd-mcp` | `yd mcp` |
| `yd-nodeaction` | `yd node action` |
| `yd-priority` | `yd workrequirement priority`, `yd taskgroup priority` |
| `yd-provision` | `yd workerpool provision` |
| `yd-remove` | `yd resource remove` |
| `yd-resize` | `yd workerpool resize`, `yd computerequirement resize` |
| `yd-schema` | `yd schema` |
| `yd-show` | `yd show` |
| `yd-shutdown` | `yd workerpool shutdown`, `yd node shutdown` |
| `yd-start` | `yd workrequirement start` |
| `yd-submit` | `yd workrequirement submit` |
| `yd-terminate` | `yd computerequirement terminate`, `yd instance terminate`, `yd node terminate` |
| `yd-token` | `yd workerpool token` |
| `yd-upload` | `yd data upload` |
| `yd-variables` | `yd variables` |
| `yd-version` | `yd version` |
| `yd-wait` | `yd wait` |
