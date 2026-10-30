# Changelog

The user-visible changes in each release of the YellowDog CLI, the newest first. Releases up to v13.1.0 are not recorded here.

## Unreleased

### Listing and actions

- **`yd task list` can list the Tasks of several Task Groups at once**: at the Task Group prompt, answer with a list, a range or `*` (`1,3`, `1-4`), and their Tasks are listed in one table, each row naming its Task Group. Only one Task Group could be chosen before.
- **An empty listing says so the same way for every type**: `No matching <Type>` (`No matching Instances`, `No matching Keyrings`), in place of the mix of `No Nodes to display`, `No instances to list` and `... found`; a listing of Task Groups, Attribute Definitions or Permissions that found none now says so rather than printing nothing.

## 15.6.0 — 2026-10-30

### Upgrading

These changes alter what a command prints without `--debug`:

- **Messages about how a command works out what it sends are in the `--debug` trace**, not its ordinary output: what `yd workerpool provision` and `yd computerequirement provision` fill in from the configuration file (`Setting 'provisionedProperties.workerTag': ...`), what `--property` sets in a Work Requirement, a template name replaced with its ID, a Compute Requirement name resolved to its ID, the check for Allowances to replace, `Attempting to create or update Attribute Definition`, `Checking Allowance exhaustion`, and the notes that `--strip-ids`, `--substitute-ids` and `--no-resequence` are in effect. What a command created, changed or removed is still printed.

### Listing and actions

- **`yd application` and `yd doctor` show the Keyrings the Application can use**, each with the names of its credentials: `yd application` in its report and as `keyrings` under `--json`, and `yd doctor` in a Keyrings row, a `WARN` when there are none.
- **`yd task list` shows each Task's Task Group**: the table of Tasks has a Task Group column, so Tasks listed across a Work Requirement's Task Groups (`--within` a Work Requirement, or every Task) can be told apart; `--details` and `--json` are unchanged.
- **`yd taskgroup list` shows each Task Group's Tasks**, completed of total, as `yd workrequirement list` does for a Work Requirement's.
- **`yd workerpool list` shows each pool's Nodes, its Workers (working of all) and whether it is healthy.**
- **`yd worker list` shows each Worker's Node, and the Task Group that has claimed it** (`Claimed By`).
- **`yd task list --with-errors` says it lists Tasks with errors only**, as `--active-only` says it lists active Work Requirements only.
- **A `--debug` line names the part of the CLI that wrote it by its place in the package**, so the `yd data` verbs' rclone runs are `dataclient.operations` rather than `operations`.
- **A `--debug` line for a setting given on the command line names its option**, and the value for the namespace, tag and URL: `Using 'namespace' 'yd-demo' from the command line (--namespace)`.

## 15.5.0 — 2026-10-28

### Upgrading

These changes alter what `--debug` does:

- **`--debug` writes a trace to stderr**: as well as the start-up preamble, which it printed to stdout, it traces each request the command makes to the Platform, each name resolved and file read, the decisions a command makes (how Tasks are batched, how `--add-to` numbers them, event streams reconnected, the order resources are created in, the rclone commands the `yd data` verbs run, what `compare` read of a Worker Pool), and a failure's stack trace, each line starting with the date and time as the command's other messages do; [What the Trace Shows](docs/troubleshooting.md#what-the-trace-shows) lists it all. `--quiet` and `--json` no longer suppress it, and stdout holds what it would hold without `--debug`, so a script's `--json` run can be traced. The trace never includes the application key or secret.
- **A command run with `--debug` exits with the code it would give without it**: a failure's stack trace is written to the trace and the command exits with the failure's own code (4 for a refused credential, 6 for something not found), where it exited 1 for every failure. A fault in a configuration or specification schema check is warned of, its stack trace traced, rather than ending the command, and `yd doctor --debug` reports a failing check as a row, tracing its stack trace, rather than stopping.

### Work Requirements

- **`--add-to` straight after Tasks were added to a Task Group adds to it**: adding Tasks to an existing Task Group within seconds of a submission or another `--add-to` adding to it named them as the Tasks already there, since the Platform's count of them had not yet caught up, so the Platform refused the batch ("Task names must be unique within task group") and the command exited 1. `--add-to` now looks for the name its first new Task would have and, when it is already taken, says so and waits for the count to catch up before numbering the new Tasks; a name taken while the count stands still for 10 seconds is refused as one already in use, before anything is added.
- **`yd workrequirement compare` and `yd taskgroup compare` compare instance pricing**: a new Instance Pricing row checks a Task Group's `instancePricingPreference` of `SPOT_ONLY` or `ON_DEMAND_ONLY` against the pricing of the Worker Pool's Compute Sources, every one of which must provision that pricing alone, as the Scheduler requires to scale the pool up. Such a pool was reported as matching though it never got the work. `--json`'s `properties` gain the row.
- **`maximumTaskRetries` is sent only when it is set**: a Task Group with no retry settings is submitted without it, rather than with `0`, so `--dry-run` no longer shows the deprecated property. The Platform's default is the same, no retries, so nothing changes in how Tasks are retried.

### Variables and configuration

- **An environment value a `--config` file outranks is reported**: with the configuration file chosen by `--config`, which wins over the environment, `yd doctor` warns of each environment variable it passed over, `YD_NAMESPACE`, a `YD_VAR_*` variable or a `YD_DATA_CLIENT_*` field set to something else, naming it and what it would have set but never its value, and `--debug` says so as each is found. Nothing changes in which value is used.
- **`--config`'s help says that the file it names outranks the environment**, as a file found by default does not, and `yd doctor`'s `Config schema` hint no longer says the warnings are given under `--quiet`, which skips that check.
- **Documentation:** the Work Requirement Property Dictionary is now [docs/work-requirement-property-dictionary.md](docs/work-requirement-property-dictionary.md), where it was `docs/property-dictionary.md`.

### Dependencies

- **`rclone-api` 1.5.6 or later is required**: upgrading the CLI now upgrades an older `rclone-api` with it, which it left as it was. With a release before 1.5.3, `--upgrade-rclone` failed (`type object 'Rclone' has no attribute 'upgrade_rclone'`), with one before 1.5.4 `yd data list` failed, and with one before 1.5.6 a run with an inline remote printed `Error deleting config file` on stdout as it exited, breaking `--json`.

## 15.4.0 — 2026-10-27

### Upgrading

These changes alter what an existing specification gives:

- **A plain `{{name}}` in a Worker Pool or Compute Requirement specification is substituted**: outside their User Data and Node Actions (`nodeEvents`), where the Platform's own Mustache runs and `__{{name}}__` is still needed, a property can be written `{{name}}`, as it is in the configuration file's `[workerPool]` section, and `__{{name}}__` works as before; a plain `{{name}}` there was passed to the Platform unchanged, and an undefined one is now warned of. In a Jsonnet specification the plain form is substituted after evaluation, so Jsonnet code computing with a variable still takes `__{{name}}__`.
- **A Configured Worker Pool resource's Node Actions take `__{{name}}__`**: its `nodeEvents`, which the Platform's Mustache processes, are substituted only in the `__{{name}}__` form, as a Worker Pool specification's are, so the Platform's `{{node.details.hostname}}` is neither substituted nor warned of; a plain `{{name}}` there, which was substituted, is now left for the Platform.

### Variables and configuration

- **`__{{name}}__` in a Jsonnet resource file's User Data and Node Actions is substituted**: it gave `__value__`, the underscores kept.
- **`{{raw:name}}` writes `{{name}}` literally**: text meant for another tool that holds a `{{name}}` this CLI would substitute, such as `{{date}}` or `{{task_name}}`, can be passed through unchanged by writing `raw:` after its opening braces; everything after `raw:` is text, and nothing substitutes it later. It works in every specification, the configuration file, CSV cells, the files substituted as text, and the `__{{raw:name}}__` form of Worker Pool specifications and User Data.
- **Documentation:** the README's Documentation section is now a map of every page, each with what it covers; Getting Started has moved to the [YellowDog Documentation](https://docs.yellowdog.ai/#/getting-started/getting-started), whose CLI track the README links to; and [one table](docs/variables.md#variable-substitutions-in-worker-pool-and-compute-requirement-specifications-and-in-user-data) says where `__{{name}}__` is written and where `{{name}}`.
- **`{{ name }}` with spaces is warned of**: a substitution written with space inside its braces is not a substitution and is left as it is, as before, but where the name inside is a variable that would be substituted (defined, an environment variable set, or one of the Task variables) a warning now says so and gives the form without the space; text naming nothing, such as another tool's template, is not reported.

## 15.3.0 — 2026-10-26

### Upgrading

These changes alter what an existing script or configuration will see:

- **`--property` beats a specification**: `--property workRequirement.<key>=<value>` replaces the property wherever a Work Requirement specification sets it, at the Work Requirement, Task Group and Task levels (`name` and `tag` at the Work Requirement level only), and `--property workerPool.<key>` (or `computeRequirement.<key>`) a Worker Pool or Compute Requirement specification's own value, each replacement reported; a specification's own value won, the override only filling in one it lacked.
- **`--property` beats the environment**: `--property common.namespace=x` (and `tag`, `key`, `secret`, `url`, `readTimeout`) is used whatever `YD_NAMESPACE` and the others hold, and `--property dataClient.bucket=x` (or `remote`, `prefix`, for `[dataClient]` or a profile) whatever `YD_DATA_CLIENT_BUCKET` holds, as a command-line value; the environment won unless the file was chosen with `--config`. `--namespace` and the other options still win over `--property`.
- **`[common.variables]` overrides the default variables**: `username = "build"` in the configuration file replaces `{{username}}` (as it does `{{date}}`, `{{random}}` and the other defaults) whether or not the file was chosen with `--config`, where it was ignored without it; `-v` and `YD_VAR_*` still win over the file.
- **`YD_ENV_OVERRIDE=false` leaves the override off**: `0`, `false`, `no` and `off`, in any case, are read as off, as `YD_COMPLETION_LOOKUPS` reads them, where any value at all made `.env` win over the environment.
- **`{{dataClient.prefix}}` is empty under `--no-prefix`**, the prefix the command uses, where it kept the default `{{namespace}}/{{tag}}`.
- **`workersPerVCPU` keeps a fraction**: `workersPerVCPU = 0.5` establishes one Worker for every two vCPUs, where it was taken as `0`, establishing none.

### Listing and actions

- **Options a verb never takes are no longer offered**: each `yd cloudinfo` verb's `--help`, Tab completion and MCP tool leave out the filters it refuses (`yd cloudinfo regions` takes no `--vcpus`), and `yd node shutdown` no `--follow`, which followed nothing; each is still refused if given.
- **`yd instance terminate --follow` and `yd node terminate --follow` end**: they return once the Instances have gone and nothing is changing in their Compute Requirement, where they followed it until Ctrl-C, since terminating some of its Instances leaves it running.

### Variables and configuration

- **`--validate` needs no credentials**: checking a specification contacts nothing, so it runs with no Application key or secret configured, where it exited 3 without them.

## 15.2.0 — 2026-10-25

### Upgrading

These changes alter what an existing script or habit will see:

- **Combinations that were accepted and ignored are refused** (exit 2): `-a` (`--auto-follow-compute-requirements`) without `--follow`; `yd node action --details` without `--status`; `yd workrequirement submit --empty` with a specification or CSV file, `--task-count` or `--task-group-count` (and, exit 1, with one named in the configuration), where it submitted their Tasks; `--json-raw` with `--task-type`, `--overwrite` or `--content-path`; `yd list --status ''`, which listed everything; and a `yd list` filter given as `0` or `""` for a type it does not apply to.
- **Options a verb never takes are no longer offered**: `yd workerpool resize --wait`/`--timeout`, `--substitute-ids` on the `show` verbs other than resources' and Allowances', `yd resource list --within`/`--limit`/`--unhealthy`/`--with-errors`, and `yd data list --dry-run`. They are gone from `--help`, Tab completion and the MCP tools, and refused if given.
- **Which value wins**: `--property common.variables.<name>=<value>` acts as `-v <name>=<value>` does, set before the configuration file is read, so the file's properties and the variables built from it take it; a configuration file's own `[common.variables]` win over an `importCommon` file's, with `--config` as without; and a named data client profile's own fields beat `YD_DATA_CLIENT_*` (`yd data copy --dst-profile backup` reaches the bucket `[dataClient.backup]` names), a field it inherits still being overridden.
- **`yd resource remove`**: with no namespace configured (`-n ''`), a name of a namespaced type is refused, where it removed the resource of that name in every namespace; a Compute Source Template name found in more than one namespace is refused as ambiguous, where the first found was used; and `--json` names a Worker Pool removed by its ID `ConfiguredWorkerPool`, as one removed by name is, where it was `WorkerPool`.
- **`yd node action --status --json` gives `null` for a queue's missing status or action**, where it gave `"-"`, as it already did for a node whose queue could not be fetched.
- **A `[common]` `namespace`, `tag`, `key` or `secret` that is not text** (`tag = 2026`) is a configuration error, exit 3; and **`yd variables` redacts a variable whose value holds the configured key or secret** (one defined as `{{secret}}`), whatever it is called.

### Configuration

- **Your own configuration file**: with no `config.toml` in the current directory and none named with `--config`, `yd` reads `~/.config/yellowdog/config.toml` (`$XDG_CONFIG_HOME/yellowdog/config.toml` where that is set), so one set of credentials and defaults serves every directory; a local `config.toml` is read in its place, the environment wins over it as over any `config.toml`, and `yd doctor` names it.

- **`yd init` writes a starter configuration file**: it asks for the key, secret, namespace, tag and URL (offering `YD_KEY` and the others' values, the secret typed unseen; `--yes` asks nothing) and writes `config.toml`, or with `--user` your own file; an existing file is replaced only with `--overwrite`, and one holding the secret is readable by its owner alone.

### Data client

- **Transfers record what happened**: `yd data upload` uploads a symbolic link given among other files, where it recorded it as uploaded and sent nothing; `yd data delete` records files as failed when a deletion and the listing that checks it both fail, where it recorded every file as deleted and exited 0; and `yd data copy --json` records a source that is missing or cannot be reached.
- **Paths**: a `..` in a relative remote path holding a `:` (`../run-10:00`) is refused, as any other `..` is, where it climbed out of the prefix; and at a remote's root, with no bucket or prefix, `yd data copy a.txt sub/` names the copy `sub/a.txt`, and `yd data list --recursive` and `yd data upload --flatten` keep their paths relative to the remote.

### Work Requirements

- **`--progress` keeps following when an event leaves a Task count empty**, as the Platform can before a Task Group has Tasks, where it stopped with an "Event stream error" (and `-E` then exited with a failure).
- **Numbering**: `--add-to` numbers a new Task Group on from the existing ones, in its own properties as in its Tasks'; `{{task_count}}` for Tasks added to an existing Task Group is its whole count everywhere; and `{{task_count}}` in a Task Group's name and properties is the number of Tasks `--task-count` gives it.
- **Failures part-way**: `--parallel-batches` stops building batches once one has failed; `--json-raw` without `--follow` or `--progress` does not fetch the Work Requirement it submitted, so a lost connection then cannot fail a submission that succeeded; a specification whose `taskGroups` or `tasks` is `null` is reported as missing it; and `yd workrequirement abort` with no targets records a Work Requirement whose Tasks cannot be listed as failed and goes on, exiting with the failure's code.

### Listing and actions

- **`yd list`**: `tasks --status` filters the Tasks alone, so `--status EXECUTING` shows the executing Tasks; `workers --active-only` includes BATCH_ALLOCATION and LATE Workers; text that looks like a number is shown as written (a tag of `1.10`, not `1.1`); and a Task Group both starved and waiting shows `/STARVED/WAITING` when followed, as when listed.
- **A value the Platform did not give is a blank cell in every table**: never the text `None` (a missing status, `None/None` Tasks, a reset of `5 None`), a `No` for an unknown yes or no, or a `-` (Cloud Info's and the node action queue's tables); and a Compute Requirement missing an instance count, an Allowance or Attribute Definition missing its type, or a Role missing its permissions is listed rather than stopping the listing.
- **Actions**: `yd workerpool shutdown -n ''` acts in every namespace, where it matched nothing; `yd task cancel` skips a RESUBMITTED Task; a Work Requirement or Compute Requirement name only finished ones share finds the newest; `yd allowance boost` follows the other actions' rules (`Cannot find Allowance <ID>`, a repeated ID acted on once); and `yd node action --status` records a node whose queue cannot be fetched and exits with its code, and takes `-J` for its `--actions` file.

### Resources

- **`yd resource create --json` records what was done when part of it fails** (a new Group whose role grant failed, each Allowance removed by `--match-allowances-by-description`, a Configured Worker Pool returned without a token, a failed removal as `namespace/name`); `yd resource remove --quiet` still lists the Allowances to choose from; and a Compute Requirement Template source without `sourceTemplateId` is reported as a missing property.

### Variables and configuration

- **A variable inside an array or table variable keeps its backslashes and quotes** (a Windows path); a chain of variables however long resolves, where more than about ten links was reported as circular; a `{{variable}}` inside a Jsonnet comment is left alone; and `yd schema --check` reports a malformed `index.json` or a schema file that is not UTF-8 rather than a traceback.

### Tab completion

- **The options of `yd version`, `yd help`, `yd format-json` and `yd jsonnet2json` complete**; on macOS's bash 3.2, `--sort=cr<Tab>` completes to `--sort=created`; a file after `--option=` completes in bash 3.2, zsh and PowerShell; a quoted word is read as the command will take it (`-n 'my ns'`); and with `--names`, `--within=<Tab>` looks up what `--within <Tab>` does and `yd taskgroup priority` completes `wr/tg`.

### Commander

- **Closing the window stops what was under way**: an action listing what it would affect does nothing more, where Download went on to download everything matching and the others asked to act on their whole scope; and a pending configuration rediscovery is cancelled.
- **The Show buttons say why they cannot show a file** (moved, deleted, not UTF-8), where Commander crashed; an edited Namespace or Tag field is discovered again, so confirmations and the default object path follow it, and an older discovery never overwrites a newer one; and a command finishing leaves input open to a later one still waiting for it.
- **The configuration row is closed off by one line across the window**, the divider between the panels starting beneath it.
- **Smaller fixes**: the quit dialog names commands as typed; Copy and Save keep their tooltips; a commented-out `workRequirementData`/`workerPoolData` line is skipped; Add to and Resize preselect the newest row; and a command typed with `--` gets Commander's options ahead of it.

### MCP server

- **A number argument that is not a number is refused**: a list given as a priority added its items as targets, and `[5, 0]` as `auto_shutdown_minutes` disabled the auto shutdown.

### Cloud Wizard

- **AWS** `add-ssh` and `setup` use the default VPC's `default` security group, where they took the first group with `default` in its name in any VPC; `setup` without a region stops before creating anything; and declining an access key's deletion keeps it and creates no new key. **Azure** `add-ssh` asks before opening port 22, and a teardown removes the YellowDog resources first. **Every provider** saves its resource file when adding the Credential fails, and exits 1 (or with a lost connection's code).

### Other

- **`--help` lists a command's own options first**, and the options every command shares (`--config`, `--key`, `--debug`, ...) after them under `universal options`, shown in the usage line as `[universal options]`, so the line names what the command itself takes.
- **A misspelt command, verb, option, sort key or resource type is answered with the word meant**: `yd wr submti` says `did you mean 'submit'?`, and `--namepsace` `did you mean '--namespace'?`; with nothing close, the choices are listed as before.
- **A prompt interrupted with Ctrl-C, or given no answer, ends its line**, so the message that follows starts on a line of its own rather than after the question.
- **`yd doctor`** names uv and pip in its advice, and skips the Remote reachable check without an rclone binary, where it downloaded one with no time limit; an abbreviated `--docs` (`--doc`) prints the documentation link; and a message that sets a command on a line of its own keeps its line breaks.

## 15.1.0 — 2026-10-23

### Upgrading

These changes alter what an existing script or habit will see:

- **On Windows, a script reading `yd`'s output through a pipe or a file decodes it as UTF-8**, which `yd` now writes there (see below), where it wrote the Windows code page: Python's `subprocess.run(..., text=True)` decodes in the code page by default, and should be given `encoding="utf-8"`; output that is all ASCII, which most is, reads the same either way.

### Changes

- **On Windows, `yd` writes UTF-8 when its output goes to a file or a pipe**, as it does to a console: `yd version > versions.txt`, or any output holding a character outside the Windows code page, failed with a `UnicodeEncodeError`, and the rest of the output reached the file in the Windows code page, garbling characters such as the em dash. `--json` output is now always UTF-8, as JSON exchanged between programs must be.
- **On Windows, `yd data download` refuses an item whose own name no Windows file name can hold** (one containing `:`, `<`, `>`, `"`, `|`, `?` or `*`), saying so and suggesting `--destination` to name the local file, where a `:` sent the item somewhere else (`--into results` wrote `a:b.txt` to the drive-relative path `a:b.txt`); the other items still download, and files inside a downloaded directory are named by rclone, as before.

## 15.0.0 — 2026-10-23

### Upgrading

These changes alter what an existing script or habit will see:

- **`yd resource remove` removes IDs given alone in dependency order**, as it removes files and IDs given together: a resource before those it refers to (an Application before a Group, a template before its Keyring), where IDs alone were removed in the order given. A script that lists IDs in a deliberate order of its own gives `--no-resequence` to keep it.
- **`yd data ls` is now `yd data list`**, as every other noun's listing is named; `yd data ls` is refused (`unknown verb 'ls'`, exit 2). Its options are unchanged. The deprecated `yd-ls` command points to `yd data list`, and the MCP server's `yd_data_ls` tool is `yd_data_list`, so an MCP client's saved permission for it needs granting again.

### Changes

- **`yd resource remove --no-resequence`** removes the resources in the order given, as `yd resource create --no-resequence` creates them, rather than in dependency order; with files and YellowDog IDs given together, each file's resources are removed where the file was given among the IDs.
- **`yd data` transfers many files about three times faster**: a directory's download, upload or `--sync`, and the files a wildcard matches, are copied 128 at a time rather than 32, since on S3 a small file's transfer is mostly waiting for the request. With 20,000 1 KB files on S3, `yd data download --sync` took 11 s (was 34 s) and `yd data upload --recursive` 22 s (was 52 s). Before the transfer starts, a directory on S3 or other bucket storage is listed once rather than twice, which for 100,000 files saves as long as one listing of them takes. An SFTP or FTP server that limits how many connections it accepts may refuse some of the 128; cap them with the remote's `connections` (SFTP) or `concurrency` (FTP) option (see [Data Client](docs/data-client.md#data-client)).

## 14.2.0 — 2026-10-22

- **A Compute Requirement can be terminated automatically**, with YellowDog SDK 15.9.0 (now the minimum): `autoShutdownTimeout` in `[workerPool]` or `[computeRequirement]` gives `yd computerequirement instantiate` the minutes after which the Compute Requirement it creates is terminated (`0` for never), and a JSON specification can set `autoShutdown` itself (`{"enabled": true, "timeout": "PT2H"}`). `yd workerpool provision` ignores the property, with a warning. `yd computerequirement show` shows the `autoShutdownTime`.
- **`yd computerequirement autoshutdown` sets when Compute Requirements are terminated**: `--minutes 120` terminates them two hours from now, replacing any auto shutdown already set, so running it again extends a Compute Requirement's life, and `--minutes 0` means never. It selects Compute Requirements as `yd computerequirement terminate` does, by name, glob, YDID, or namespace and tag; under `--json` each record adds the `autoShutdownTime` set. It has no `yd-*` command.
- **`addEnvironment` accumulates down the levels, and a Task's `environment` takes precedence over it**: the TOML file's, the Work Requirement's and a Task Group's `addEnvironment` tables are added together, a lower level winning a shared key (`null` clears what came from above), where the lowest level's used to replace the others; and once the Task's `environment` is inherited, a key in both keeps the `environment` value, where `addEnvironment` used to override it, so a Task Group's `addEnvironment` could override a variable a Task set for itself.
- **`yd data` handles many files in one rclone run rather than one each**: the files a wildcard matches are downloaded or deleted, and the files given to `yd data upload` uploaded, a directory's at a time with rclone's parallel transfers, and a `--flatten` download or upload copies 16 files at a time. With 1,000 files on S3: uploading them took 2.8 s (was 212 s), downloading a wildcard's matches 2.2 s (210 s), a flattened download 12.9 s (202 s), and deleting a wildcard's matches 5.7 s (254 s). Each file is still recorded under `--json`, a failed run's by whether it arrived. A wildcard's summary line names the first 10 matches and counts the rest.
- **`yd data` commands list large remote directories much faster on S3**: the listings that don't show a modification time no longer read one, which on S3 cost a request per object before anything was transferred. Downloading 5,000 small files with `yd data download --sync` took 9 seconds rather than 3 minutes; a directory of 100,000 had not started downloading after 30 minutes. `yd data ls` still shows modification times.
- **A cloud provider's own image ID is used without comment**: an AWS AMI ID (`ami-…`), an Azure `market:`, `gallery:` or `/subscriptions/…` image, a GCP `projects/…/global/images/…` image or an OCI `ocid1.image.…` OCID no longer prints `No Images ID substitution possible`. Any other image value that names no Image Family or Group is still mentioned, now as `'<value>' is not the name of an Image Family or Group; it is passed on as the provider's image ID`, since it may be a misspelt Image Family name.
- **`--task-count`/`-C` and `--task-group-count`/`-G` override the specification**: `yd workrequirement submit wr.json -C 10` submits 10 copies of the Task even where `wr.json` sets `taskCount`; they took effect only where the specification set none.
- **`show`, `follow`, `wait` and `compare` take names on the nouns that have them**, since the noun says what a name stands for: `yd wr show nightly-run`, `yd tg show nightly-run/render`, `yd task show nightly-run/render/frame-1`, `yd wp follow gpu-pool`, `yd cr wait my-cr`, `yd wr compare nightly-run gpu-pool`. A name is looked up in `--namespace` (new on these commands) or the configured namespace, or in one given ahead of it (`namespace/name`), whether the object is live or finished; a name that finds nothing exits 6. `yd show`, `yd follow` and `yd wait` themselves still take IDs alone.
- **`yd resource remove` recognises YellowDog IDs without `--ids`**, so specification files and IDs can be given together: `yd resource remove keyring.json ydid:crt:...` removes both in one run, a resource before those it refers to, with one exit code and, under `--json`, one array. `--ids` still works, saying every argument is an ID, and notes that it is optional.
## 14.1.0 — 2026-10-20

- **A Platform request whose response stalls fails after 90 seconds** rather than waiting indefinitely, with YellowDog SDK 15.8.0 (now the minimum); the CLI's own requests (`--json-raw`, and the raw provisioning paths) wait 90 seconds too, where they waited five minutes. **`readTimeout` in `[common]`** (or `YD_READ_TIMEOUT`, or `--property common.readTimeout=<seconds>`) changes how long, and `0` waits indefinitely. A request is resent after a timeout, but not one that may have been carried out: a Task batch that times out is resubmitted only when all its Tasks have names, since the Platform refuses duplicate names and an unnamed Task could be added twice; otherwise the command fails, saying to check the Work Requirement's Tasks.
- **`{{dataClient.prefix}}` is the data client's default prefix, `{{namespace}}/{{tag}}`, when none is set**, as `yd data upload` uses it, with or without a `[dataClient]` section; likewise `{{dataClient.<name>.prefix}}` for a profile setting none. A specification naming it was given the expression unsubstituted, with a warning, so a Task looked for its input somewhere other than where it was uploaded.
- **`yd doctor` shows a Group the Platform returns without a name by its ID** in the Groups and roles row, which failed on one.
- **Tab completes `--type`'s resource types in any case**, as `yd resource create`, `remove` and `show` read them: `--type k` completes to `keyring`, and `--type Name` offers `Namespace` and `NamespacePolicy`.
- **Tab completes names and IDs from the Platform, when asked for**: load the completion script with `--names` (`eval "$(yd completion zsh --names)"`, or `bash`, `fish --names | source`, `powershell --names`) and Tab offers Work Requirements, Worker Pools and Compute Requirements as the command would act on them, by name, for every verb that takes them (`show`, `follow`, `wait` and `compare` included, and `yd taskgroup show` and `compare` as `wr/tg`), in the namespace, tag and statuses the command uses (`--tag ''` typed first widens them to the whole namespace); `yd list`'s `--within` value from what it lists within (Work Requirements, then their Task Groups as `wr/tg`, Compute Requirements or Worker Pools); and after `--type`, the names or IDs `yd resource remove`, `yd resource show` and `yd show` take for that resource type (a Credential's after `keyring/`, an Allowance's ID with its description). A Tab waits at most two seconds and answers are cached for 30 seconds; `YD_COMPLETION_LOOKUPS=off` switches the lookups off without editing the start-up file. Without `--names`, as before, completion is local only, and `yd doctor` says which the start-up file loads. See [Names and IDs from the Platform](docs/commands.md#names-and-ids-from-the-platform).

## 14.0.0 — 2026-10-18

### Upgrading

Most of this release adds to what the CLI does. These changes alter what an existing script, configuration or habit will see:

- **Use `yd`.** The `yd-*` commands still run, with a warning on stderr, but are deprecated and will be removed in a future release. `yd help --deprecated` names what replaces each: `yd-submit` is `yd workrequirement submit` (or `yd wr submit`), `yd-list` is `yd list`, and so on.
- **Listing Work Requirements, Worker Pools and Compute Requirements applies the configured tag**, as acting on them does. Give `--tag ''` to list the whole namespace.
- **`yd list tasks`, `instances`, `nodes` and `workers` stop at 1000 items**, with a warning on stderr when more match. Give `--limit 0` for them all.
- **Exit codes name the cause of a failure** for the action commands, `yd show` and `yd wait`: 6 for not found, 5 for a missing permission, 7 for a Platform error, where many exited 1. A script that tests for exit code 1 should test for a non-zero one. See [Machine-readable Output and Exit Codes](docs/json-output.md).
- **MCP clients:** the tools for the commands the nouns replace are renamed (`yd_submit` is `yd_workrequirement_submit`), so a client's saved permissions for them need granting again. An MCP client configured to run `yd-mcp` keeps working; `"command": "yd", "args": ["mcp", ...]` is the new form.
- **`yd help --json`** names each command as it is typed after `yd` (`list`, not `yd-list`).

### Changes

- **Python 3.15 is supported.**
- **The CLI is one command, `yd`.** Commands name the object they act on, then what to do to it: `yd workrequirement submit` instead of `yd-submit`, `yd instance terminate` instead of `yd-terminate`. The nouns are `workrequirement`, `taskgroup`, `task`, `workerpool`, `node`, `worker`, `computerequirement`, `instance`, `resource`, `allowance`, `data` and `cloudinfo`, and `wr`, `tg`, `wp` and `cr` are short for the four longest (`yd wr submit`). `yd <noun> --help` lists a noun's verbs. A verb offers only the options that apply to its object, refuses any other (exit 2), and refuses a target of the wrong kind: `yd instance terminate` takes Instances, and is refused a Compute Requirement. Every noun also has `list` and `show`, and the Work Requirement, Worker Pool and Compute Requirement nouns have `follow` and `wait`, restricted to that object. Every other command is `yd <command>`: `yd list`, `yd show`, `yd follow` and `yd wait`, for any type of object, and `yd application`, `yd cloudwizard`, `yd doctor`, `yd variables`, `yd schema`, `yd format-json`, `yd jsonnet2json`, `yd help`, `yd version`, `yd commander` and `yd mcp`. `yd` alone, or `yd help`, lists them all. See the [Command List](docs/commands.md).
- **The `yd-*` commands are deprecated**, and will be removed in a future release. Until then they run as before, with a warning on stderr naming what to use instead (`--quiet` suppresses it where the command has it); `yd help --deprecated` lists each with what replaces it. An MCP client configured with `yd-mcp` keeps working; `"command": "yd", "args": ["mcp", ...]` is the new form.
- **`yd help --json` names each command as typed after `yd`** (`list`, not `yd-list`), each noun with its `alias` and `verbs`, and lists each `yd-*` command with `deprecated` and `replacedBy`.
- **Commander runs the `yd` commands** (`yd workrequirement submit`, `yd data download`, ...), and shows them in its output window. Its command box takes a noun and verb as one command (`yd wr submit`), and `yd list` and the like as one, adding the configuration file, namespace, tag and variables after them, and only where the command takes them; an older `yd-*` name typed there still runs. A `yd` command it does not recognise is reported by the CLI rather than handed to the shell.
- **MCP: the tools for the commands the nouns replace are renamed for their noun forms**, one per noun and verb: `yd_submit` is `yd_workrequirement_submit`, `yd_terminate` is `yd_computerequirement_terminate`, `yd_instance_terminate` and `yd_node_terminate`, and `yd_cloud_info` is `yd_cloudinfo_regions`, `_sub_regions`, `_instance_types` and `_prices`. Each takes only its verb's options, and the Instance and Node tools need at least one target. The tools of the other commands (`yd_list`, `yd_show`, `yd_follow`, `yd_wait`, `yd_doctor`, `yd_variables`, `yd_schema`, `yd_application`, `yd_version`) keep their names. A client's saved permissions for the old names need granting again.
- **Tab completion for bash, zsh, fish and PowerShell**, from the new `yd completion` command: `eval "$(yd completion zsh)"` in `~/.zshrc` (or `bash` in `~/.bashrc`), `yd completion fish | source` in `~/.config/fish/config.fish`, or `yd completion powershell | Out-String | Invoke-Expression` in a PowerShell profile. It completes the word after `yd`, a noun's verbs, a command's options, and the values the CLI knows (fixed choices, `--sort` keys, `yd list`'s entity types, local files for the options and arguments that name one), and follows the installed CLI without regenerating. The deprecated `yd-*` commands are not completed, and the commands whose options it does not know (`yd commander`, `yd mcp`, `yd format-json`, `yd jsonnet2json`, `yd help`, `yd version`) complete local files. See [yd completion](docs/commands.md#yd-completion).
- **`yd doctor` checks that `yd` on your `PATH` is this CLI**, warning when another `yd` comes first (it would run in its place, and Tab completion would ask it), and **whether your shell loads `yd completion`**, naming the line to add to `~/.zshrc`, `~/.bashrc` or fish's `config.fish`, or warning of a line that still runs the pre-release `yd-completion`.
- **Commander filters its output by text**: type in the new *Filter lines* field above the Command Output window (Cmd+F, or Ctrl+F on Windows and Linux) to show only the lines containing that text, ignoring case, with `*` and `?` as wildcards. It works together with the filter by process, and Copy and Save take only the lines shown.
- **An empty namespace or tag is described as what it searches**: with `-n ''` (or no namespace set), the listings and the actions selecting by namespace and tag say `in all namespaces`, or name the namespaces searched (`in namespaces 'a', 'b'`) for an Application that cannot read them all, and an empty tag or name filter is left out, where they printed `in namespace '' with '' in name`.
- **Listing Work Requirements, Worker Pools and Compute Requirements uses the configured tag**, as the commands acting on them do, so `yd workerpool list` shows the Worker Pools `yd workerpool shutdown` would consider (and likewise `cancel` and `terminate`); `yd list` and the noun `list` verbs previously listed the whole namespace unless given `--tag`. Give `--tag ''` (or `-t` alone) for the whole namespace. Templates and Image Families are still listed whatever their names unless `--tag` is given.
- **`yd workerpool shutdown` says why nothing was shut down**: given no names, or a pattern, when nothing active matches it reports either that nothing matched or which matching Worker Pools are already finished, and their status, where it printed only `No Worker Pools or Nodes shut down`.
- **`yd data download --into` names a file at the remote's root by its own name**: `yd data download loc:a.txt --into out` wrote `out/loc:a.txt`. Under `--json`, a download of such a file with `--destination` recorded `out/loc:a.txt` as its destination, though the file was written to `out/a.txt`; and a `:` in a downloaded item's own name, such as `a:b.txt`, was taken for the remote's, so Commander's download chooser offered it as `b.txt`.
- **`yd data download --flatten` warns of a file landing on one an earlier argument fetched**, as it did within one argument: `yd data download d1 d2 --flatten -d out` silently replaced `out/same.txt` from `d1` with the one from `d2`.
- **A `retryPolicy` without `maxRetries` is accepted**, with `maxRetries` defaulting to `0` (no retries), as the SDK and the Platform treat it. `yd workrequirement submit` used to refuse it.
- **`null` stops a Work Requirement property being inherited.** Setting an inherited property to `null` at the Work Requirement, a Task Group or a Task gives it its default there and below, rather than the value from a level above: `"arguments": null` on a Task Group means its Tasks have no arguments, whatever the TOML file or the Work Requirement sets. The specification check now accepts `null` wherever it does this; it warned of it before. See [Stopping Inheritance with `null`](docs/work-requirements.md#stopping-inheritance-with-null). Four cases that did not work: `"taskTypes": null` on a Task Group failed with `unsupported operand type(s)`; a `null` (or empty) `taskData`, `taskDataFile` or `taskDataFiles` was passed over, so the Task took the Task Data from the level above; `"setTaskNames": null` stopped Tasks being named, where the default names them; and `"taskType": null` on a Task gave its Task Group a `null` Task Type, where it is now taken as the Task setting none.
- **Documentation:** the [variable substitutions](docs/variables.md#unset-properties-and-property-inheritance) and [Work Requirements](docs/work-requirements.md#property-inheritance) pages now say how the unset syntax (`{{::}}`) interacts with property inheritance: a property removed at one level is still inherited from the level above, unlike one set to `null`.
- **`yd wait` charges an entity still running when `--timeout` ends with the timeout**, not with another ID's failure: `yd wr wait <running> <missing> --timeout 10` exited 6 (not found) for both, and now exits 1, the two having different causes.
- **`yd show` exits with its failures' shared cause**: an ID the Application may not read exits 5, as one that does not exist exits 6, where it exited 1; a Platform failure (HTTP 5xx) exits 7. IDs failing for different reasons still exit 1.
- **The action commands exit with their failures' shared cause** (`cancel`, `shutdown`, `priority`, `token`, `start`, `hold`, `finish`, `terminate`, `abort`, `yd allowance boost`, `yd node action` and the Compute Requirement, Instance and Node actions): a target that does not exist exits 6, and one the Application may not act on 5, where they exited 1. Targets failing for different reasons still exit 1, and each record's `error` still says why.
- **A refused request is explained wherever it is reported**: when an action's target, an ID shown or a resource created is refused for a missing permission (403) or an unrecognised key (401), the CLI now says what to check (the Application's groups and their roles, or its key and secret), once per run, as it already did for a failure that stopped the command; the per-item errors used to show the Platform's raw response alone.
- **MCP: an action tool whose targets were not found or refused still returns its result**, now that those commands exit 6 or 5: a run reporting its own per-item failures is a result whatever its exit code, bar an authentication (4) or connection (8) failure, which stopped it and is an error.
- **`yd list namespaces` takes `--name` and `--deletable`**: `--name <glob>` lists the namespaces whose name matches, as it does for other types, and `--deletable` only those the Platform can delete, never having been populated.
- **`yd list` has more filters**: `--name <glob>` now applies to Tasks and Task Groups too (matching their own names); `--unhealthy` lists only the Work Requirements, Worker Pools or Compute Requirements the Platform marks unhealthy; `--provider` (`aws`, `azure`, `google`, `oci`, `on-premise`) only the Instances, Nodes or Compute Source Templates of that provider; and `--description <glob>` only the Allowances whose description matches. Each is refused for the types it does not apply to.
- **A resource can be given on the command line, without a specification file**: `yd resource create --type Keyring --set name=team-keys --set description="Team keys"` (and `yd resource remove --type Keyring --set name=team-keys`); and `yd resource remove --type <type>` takes the names or IDs of resources of that type to remove, such as `yd resource remove --type Keyring team-keys old-keys` (`namespace/name` for a namespaced type, `keyring/credential` for a Credential), refusing a name or ID that cannot identify one. `yd resource show --type <type>` (and `yd show --type`) shows resources by name likewise, `yd resource show --type Keyring team-keys`, those with no ID included (a Namespace, a Namespace Policy, an Attribute Definition, a Credential as `keyring/credential`), a name that finds nothing exiting 6. `--type` takes any resource type, in any case, and each `--set property=value` one of its properties, read as JSON where it can be and as text otherwise, with variables substituted; it is checked, processed and reported as a file's resource is. `-` reads a specification from standard input, as JSON: `generate | yd resource create -`. See [Specifying a Resource on the Command Line](docs/resources.md#specifying-a-resource-on-the-command-line).
- **`yd list --within <target>` lists the items of one parent without asking which**: the Task Groups or Tasks of a Work Requirement or Task Group (its YellowDog ID, or its name as `wr`, `wr/tg`, `namespace/wr` or `namespace/wr/tg`, e.g. `yd task list --within my-wr/tg-1 --status failed`), the Instances of a Compute Requirement (`yd instance list --within my-cr`), the Nodes of a Worker Pool, and the Workers of a Worker Pool or Node (each by its YellowDog ID, or by its name or `namespace/name`, a Node excepted). Tasks are listed Task Group by Task Group.
- **`yd list tasks`, `instances`, `nodes` and `workers` list at most 1000 by default** (and their noun forms, `yd task list` and the like), warning on stderr when more match; `--limit <n>` sets the limit and `--limit 0` lists them all. Only the items listed (and one more, to know whether more match) are fetched, where every matching one was fetched before. `--count` is never limited.
- **Listing Instances and Nodes fetches only the matching ones**: `--status`, `--provider` and `--active-only` are passed to the Platform with the search, where every Instance or Node was fetched and filtered by the CLI. The results are the same.
- **`yd list workers --status` filters the Workers alone**: it was applied to their Nodes too, so `yd list workers --status DOING_TASK` listed nothing, a Node's status never being a Worker's. It combines with the other filters and with `--json`, `--count` and `--ids-only`; a target that does not exist exits 6, and the ID of anything else is refused (exit 2).
- **`yd list tasks --with-errors`** lists only the Tasks that recorded an error, whatever their status: a Task can complete after an error, on a retry, so it is not the same as `--status FAILED`.
- **`yd list --status` takes several statuses separated by commas** (`--status failed,aborted,cancelled`), as well as repeated.
- **Listing Tasks fetches only the matching ones**: `yd list tasks` passes `--status`, `--with-errors` and `--name` to the Platform with its search, where it used to fetch every Task of each Task Group and filter them itself, which on a Task Group of millions of Tasks is the difference between a quick listing and a very long one; and `--count`, alone or with `--status`, takes each Task Group's own counts and fetches no Tasks at all. Those counts catch up a few seconds after Tasks are added, so a count taken straight after submitting can be short. The results are the same.

## 13.4.0 — 2026-10-09

- **`--sort` takes several keys, separated by commas**, sorting by each in turn: `yd-list workers --sort status,created`, `yd-cloud-info instance-types --region eu-west-2 --prices --sort spot,vcpus`. `--reverse` inverts the whole order. An unknown or repeated key is refused (exit 2). In the MCP tools, `sort` is now a list of keys rather than one.
- **A missing Application key or secret says why**: that no configuration file was found (and where it was looked for), or that `--no-config` set it aside, and how else to give it; it said only "Missing configuration data: 'key'".
- **An API URL not beginning `https://` (or `http://`) is a configuration error** (exit 3), named as such; it failed later with 'No connection adapters were found' and exit 1. **A connection failure names the Platform URL and what to check**, rather than printing urllib3's connection-pool text.
- **Specification and configuration files saved with a UTF-8 byte-order mark** (as Windows Notepad saves them) are read; they were refused. One that is not UTF-8 at all is refused naming the file.
- **A namespace or tag that looks like a file name is refused** (exit 2): `-n` and `-t` take an optional value, so `yd-submit -t wr.json` made the tag `wr.json` and submitted no specification.
- **`yd-list` applies `--sort` and `--reverse` to Users, Applications, Groups, Roles, Namespaces and Namespace Policies**, which were sorted by name, or not at all, whatever was asked; its help now says that the configured tag is not used.
- **Help text corrected**: `--json` on `yd-submit`, `yd-provision` and `yd-instantiate`, `yd-remove`'s `--yes` and `--json`, `yd-list`'s `--active-only` and `--substitute-ids`, `yd-instantiate`'s specification, and `yd-cloudwizard`'s operation; and a data client dry run ends 'Dry run complete: nothing was uploaded' (downloaded, copied), not 'Upload complete'.
- **`--follow` ends once an action that leaves its entity alive is done**, rather than running until Ctrl-C: `yd-hold` once the Work Requirement is held, `yd-compute-stop` once stopped, `yd-compute-start`, `-deprovision`, `-reprovision` and `yd-resize` once the Compute Requirement is running at its target, and `yd-compute-restart` once it is so again. The event stream of an entity that has not finished never closes, so these followed it indefinitely. A resized Configured Worker Pool, which has no Compute Requirement to tell by, is still followed until Ctrl-C.
- **`yd-cancel`, `yd-shutdown` and `yd-terminate` take `--dry-run` with explicit names and IDs**, reporting what each would act on (and, for `yd-shutdown --terminate`, the Compute Requirements it would terminate); it was refused, so the most destructive commands were the only ones unable to preview a named target.
- **`yd-submit -C`, `-G`, `-b` and `-l` must be at least 1, and `-P` and `yd-provision`/`yd-instantiate --target` at least 0** (exit 2): `-C 0` quietly became 1, and `-l 0` failed only once the Work Requirement existed.
- **`yd-create` and `yd-remove` stop at a confirmation that cannot be answered** (stdin at its end, as from a script without `--yes`), recording the rest as not attempted, as `yd-delete` does; each resource was prompted for, failed and recorded in turn.
- **`yd-create --dry-run` refuses an unknown resource type**, as the real run does, and **keeps `type`** in a Compute Requirement Template and a Compute Source Template's `source`, so its output can be given back to `yd-create`.
- **`yd-list instances --active-only` leaves out terminated Instances**: it filtered their Compute Requirements only. `yd-list workers` lists a Worker on a Node that reports no details, which it left out.
- **MCP: an action tool given no targets is refused unless it sets `all_in_scope`.** `yd_cancel`, `yd_abort`, `yd_shutdown`, `yd_terminate`, `yd_start`, `yd_hold`, `yd_finish`, `yd_compute_start`, `yd_compute_stop`, `yd_compute_reprovision` and `yd_delete` acted on everything matching the namespace and tag (or, for `yd_delete`, the whole default prefix) when their targets were left out, since the server passes `--yes`; `yd_abort` aborted every executing Task while its description said it selected interactively. Setting `all_in_scope: true` still does that, deliberately.
- **MCP: `yd_resize` takes `compute_requirement` and `yd_nodeaction` takes `worker_pool` again.** Excluding the specification-file options by name hid these two, which share the names but are no files: a Compute Requirement could not be resized by name, and a Node Action could not name its Worker Pool, failing on a prompt instead.
- **MCP: a call stopped at its `timeout_seconds` returns what the command had done.** The command was killed outright, so its `--json` document was lost: a `yd_download` stopped part-way returned `null` with files written. It is now interrupted first, as a Ctrl-C would, and its document comes back. A Ctrl-C of a data client command at the terminal now also reports what it had done under `--json`, rclone_api's own Ctrl-C handler having ended the process before it could.
- **Commander: a command typed into the command box is given only the Namespace, Tag, User-Defined Variables and Properties it takes.** `yd-show <id>`, `yd-follow`, `yd-cloud-info`, `yd-priority` and others failed on an option they do not have.
- **Commander: Cancel & Abort finds Work Requirements already cancelling**, the ones it is for once Cancel has run; it found none. **Add to…** offers only running or held Work Requirements, the ones `yd-submit --add-to` accepts; a finishing one was offered, and failed.
- **`yd-wait` and `--follow` no longer give up on an entity that is quiet for a while.** A read timeout on a quiet event stream was taken for a dropped connection, warned of, and counted toward the five-minute outage limit, so a Work Requirement, Worker Pool or Compute Requirement with no events for about ten minutes made `yd-wait` exit 8 and stopped `--follow`. A quiet stream is now reconnected without a warning, however long it stays quiet.
- **`yd-submit -C`, `-G`, `-T` and `-b` apply when the configuration file has no `[workRequirement]` section**, and `--property` applies when there is no configuration file at all; both were ignored without a word.
- **Under `--json`, the first-run download of the rclone binary no longer writes to stdout**, ahead of the JSON document; its progress goes to stderr.
- **`yd-submit` refuses Task Groups that share a name**, such as `taskGroupCount` copies of one named without `{{task_group_number}}`: Tasks are added to a Task Group by name, so they would all have gone to one of them. A dry run showed one with every Task and the other with none.
- **A name cut to 60 characters, or stripped of characters a YellowDog name cannot hold, is warned of**, once per run for each: long Task names became one name, and `Café` became `caf`, without a word.
- **Data client: `..` in a remote path is refused.** `yd-delete`, `yd-download`, `yd-copy` and `yd-upload --destination` refuse a remote path with a `..` segment (exit 2): it climbed out of the prefix past the checks that refuse deleting or syncing over the remote's root or the bucket, so `yd-delete -R ../..` could delete outside the bucket. A `.` segment is now dropped, so `.` is the prefix itself and the bucket refusals see it as such. `yd-ls` still accepts `..`.
- **`yd-upload --sync` refuses the remote's root or the bucket itself as its destination** (exit 2), as `yd-copy --sync` already did: it would have deleted every other file there.
- **An inline rclone remote's credentials are no longer written to the current directory.** rclone_api wrote the configuration, readable by all, to `.rclone/tmp_config/` under the current directory, where `yd-upload -R .` would upload it, and a read-only directory made every data client command fail. It is now written to a file only you can read, in the system's temporary directory, and removed when the command ends.
- **`yd-delete` deletes the files it reports deleted.** A file whose name began with `#` or `;`, or with a space, was recorded as deleted and left in place; and on a local or SFTP remote whose bucket is an absolute path, deleting a file failed, stopping a wildcard's other deletions.
- **A file whose name holds a wildcard character can be named.** `data[1].csv` could not be listed, downloaded or deleted, and `yd-delete 'file[ab].txt'` deleted `filea.txt` and `fileb.txt` instead. An entry named exactly as the path given is now taken as itself.
- **`yd-submit` no longer deletes input files it did not upload.** When a submission failed, its clean-up deleted every `localPath` file named in the specification, including one already at its upload path, which may be the input of another Work Requirement still running. Only files the run itself created are now deleted; a file it skipped as already there, or replaced with `--overwrite`, is left in place.
- **`yd-submit --add-to` adds Tasks to the right Work Requirement when it is in another namespace.** Given a YDID or `namespace/name` outside the configured namespace, the new Task Groups were added to the right Work Requirement but their Tasks were sent to the configured namespace, failing with not found or landing in a same-named Work Requirement there; `YD_NAMESPACE` and the `--json` record also named the configured namespace. All three now use the target's namespace.
- **Documentation:** the README is now a short landing page, and the rest of the documentation has moved to pages under [docs/](docs/), one per topic: the [Command List](docs/commands.md), [configuration](docs/configuration.md), [variable substitutions](docs/variables.md), [Work Requirements](docs/work-requirements.md) and their [Property Dictionary](docs/work-requirement-property-dictionary.md), [Worker Pools](docs/worker-pools.md), the [data client](docs/data-client.md), [resources](docs/resources.md), [Jsonnet](docs/jsonnet.md), and [machine-readable output and exit codes](docs/json-output.md). Each top-level section's old heading in the README remains, pointing to its page; a link to a deeper section of the old README (e.g. `README.md#yd-submit`) now lands at the top of the README.
- **Documentation fixes:** automatic upload of a Task input's local file is enabled by `localPath`, not `localFile` as the documentation said; the "all possible properties" Work Requirement examples now submit as written (one of `taskData`/`taskDataFile`/`taskDataFiles`, and `retryPolicy`/`failurePolicy` in place of the deprecated retry properties); `config-template.toml`'s commented examples for `retryableErrors`, `providers`, `taskDataInputs` and `taskDataOutputs` now work when uncommented, and its descriptions of `timeout`, `minWorkers`, `tasksPerWorker`, `workersPerVCPU`, `workersCustomCommand` and `addYDEnvironment` match what the properties do; and the `resource` values `yd-create` accepts are listed correctly (`InternalUser`/`ExternalUser` and `Namespace`, not `User`).
- **Commander** no longer repeats a broken configuration's error in the output window after every pause in typing in the User-Defined Variables or Properties box: the error is shown once, and again only if the configuration file is reselected or the error changes.
- **Commander's Show** buttons, with no definition file selected, resolve a `{{variable}}` in the configuration's `workRequirementData` or `workerPoolData` with Commander's own CLI rather than whichever `yd-variables` is on the `PATH`, and no longer fall back to the variable's default when the configuration prints a warning.

## 13.3.1 — 2026-10-09

- **Cloud Wizard for GCP** is best run on Python 3.11 or later, as the Cloud Wizard README now says: on Python 3.10, Google's libraries print a `FutureWarning` as `yd-cloudwizard --cloud-provider gcp` starts, and they no longer receive updates for 3.10. The setup itself is unaffected.

## 13.3.0 — 2026-10-08

### New commands

- **`yd-priority`** changes the priority of Work Requirements and Task Groups after submission: `yd-priority 10 my-run` or `yd-priority 5 my-run/render`. Targets are named as for `yd-abort`, confirmed together showing each one's current and new priority, with `--dry-run` and `--json` (recording `previousPriority` and `priority`). It is also available to MCP clients as the `yd_priority` tool.
- **`yd-compute-deprovision`** terminates Instances and reduces their Compute Requirement's target instance count to match, so that they are not replaced, as they would be after `yd-terminate` in a Compute Requirement that maintains its instance count. Instances are named as `yd-compute-restart` takes them (`cr_id.instance_id` or a Node ID), confirmed together, with `--json` and `--follow`. It is also available to MCP clients as the `yd_compute_deprovision` tool.
- **`yd-compute-reprovision`** asks the Platform to provision Instances until a `RUNNING` Compute Requirement has as many as its target instance count, restoring one left short (by `yd-terminate`, say, or a reclaimed spot Instance) without changing the target. It selects Compute Requirements as `yd-compute-stop` does: by name, glob pattern or ID, or by `namespace` and `tag`.
- **`yd-token`** refreshes the token of one or more Configured Worker Pools, keeping it and setting its expiry afresh, or with `--regenerate` issues a new one, invalidating the old. Either is confirmed first, the prompt saying what the expiry will be. `--ttl-hours` sets the token's time to live from now; without it, the token does not expire. Pools are named by ID, name or glob pattern; the new token and its expiry are printed, or recorded with `--json`. It is also available to MCP clients as the `yd_token` tool.

### Waiting for capacity

- **`yd-resize --wait`** (resizing a Compute Requirement) and **`yd-compute-reprovision --wait`** return only once each Compute Requirement acted on has its target number of Instances running and none starting or terminating, printing progress as it changes. `--timeout <seconds>` limits the wait, exiting 1 if it passes first (the change itself is still made and recorded); without it there is no limit, so a Compute Requirement left short, because the provider has run out of capacity of the kind it asks for (on-demand as well as spot) or a limit stands in the way, waits indefinitely.

### Resizing

- **`yd-resize` takes a Compute Requirement's ID without `--compute-requirement`/`-C`**, since the ID says what it names. The option is still needed with a name, which a Worker Pool and its Compute Requirement share, and is refused with a Worker Pool's ID.

### Diagnosing a Compute Requirement

- **`yd-provision --report`** reports on a test run of the Worker Pool's Compute Requirement Template, provisioning nothing, as `yd-instantiate --report` does for a Compute Requirement. It works with a Worker Pool defined in the configuration or in a JSON specification; when `computeRequirementBatchSize` would divide the pool, the report is for the first of them, and says so.

- **`yd-show --show-source-report`** follows a Compute Requirement with the Platform's report of how its sources were chosen (considered, selected and rejected Compute Source Templates, ranks, scores, constraints and preferences), for one provisioned from a dynamic template.
- **`yd-show --show-exhaustion`** follows it with the Allowances exhausted for it, so that you can see which to boost with `yd-boost`.
- Both also take a Provisioned Worker Pool's ID, reporting on its Compute Requirement.

### Group and Role membership

- **`yd-show --show-members`** follows a Group with its Users and Applications, and a Role with the Groups that hold it, so that "who is in this Group?" and "which Groups have this Role?" can be answered from the CLI.
- **`yd-show`** now shows a User with `groups`, the names of the Groups it belongs to, as it already did for an Application.

### Dependencies

- **`yellowdog-sdk` 15.7.0 or later is required.** It adds `serviceAccountEmail` to the GCE Compute Source types (`GceInstancesComputeSource`, `GceInstanceGroupComputeSource`), which a Compute Requirement Template specification can now set.

### Fixes

- **`yd-instantiate --report` works with a JSON Compute Requirement specification**, as it already did with one defined in the configuration file; it was refused before.
- **`yd-provision` and `yd-instantiate` send a JSON specification through the YellowDog SDK**, as they already did a TOML-defined one, rather than posting it to the REST API directly. What is provisioned is unchanged; a property the installed SDK does not know is now ignored with a warning rather than passed on.
- **`yd-compute-restart` refuses a glob pattern** as it is parsed, since a pattern selects Compute Requirements and the command restarts only Instances. A pattern was accepted, and any Compute Requirement it matched was confirmed and then failed with an internal error. `yd-compute-deprovision` refuses one likewise.
- **Role IDs are accepted.** The Platform gives a Role a YellowDog ID with no account segment (`ydid:role:<uuid>`), which the CLI rejected as invalid: `yd-show` reported it as an invalid ID, and a Group specification naming a role by its ID failed as if the role did not exist.

### Output

- **`yd-create`** reports a failed specification as "Failed to create or update …" and ends with "N resource(s) failed to create or update", since the specification may have been updating an existing resource; it said "create" either way.
- **`yd-create`** now shows a new Configured Worker Pool's token expiry with its time zone (`2026-10-07 14:02:42+00:00`), since the Platform gives it in UTC and the log timestamps beside it are local, and shows `never` for a token without an expiry rather than `None`.

## 13.2.0 — 2026-10-07

### New command

- **`yd-cloud-info`** lists the cloud providers' regions, sub-regions, instance types and prices as the YellowDog Platform knows them, filtered by provider, region, name, vCPUs, RAM and processor architecture. `yd-cloud-info instance-types --region <region> --prices` adds each instance type's on-demand price and lowest spot price in the region, so `--sort spot` finds the cheapest. It is also available to MCP clients as the `yd_cloud_info` tool.

### Exit codes and failure reporting

Several commands that hid a failure, or reported it under the wrong exit code, now report it. The exit codes are those in the README's *Machine-readable Output and Exit Codes*: 4 when the credentials are not accepted, 8 when the Platform cannot be reached.

- **`yd-list` and `yd-show` with `--substitute-ids`** (Compute Requirement and Compute Source Templates): losing the connection, or having the credentials refused, while looking up the names to substitute now stops the command with exit 4 or 8. It used to print the templates with their IDs left unsubstituted and exit 0.
- **`yd-submit --exit-on-failure` (`-E`)**:
  - A Work Requirement that could not be followed to its end (its event stream lost, say) and has not finished now exits with the code of that failure, 8 for a lost stream, since its outcome is not known. It used to exit 0. A Work Requirement that finished is judged by its outcome as before, even if its stream failed.
  - Losing the connection, or having the credentials refused, while fetching the final status now exits 4 or 8, not 1 as if the Work Requirement had failed.
  - Without `-E`, `yd-submit`'s exit code still reflects the submission alone.
- **`yd-follow`**: when a stream closes and the entity's status cannot then be fetched because the connection is lost or the credentials are refused, this is reported and `yd-follow` exits with that failure's code. It used to take the entity as finished and exit 0.
- **Event stream reconnection** (`yd-follow`, `yd-wait`, and `--follow` on other commands): a connection that is accepted and then drops before delivering any event, over and over, is now given up on after five minutes, as a refused connection is (exit 8 for `yd-follow` and `yd-wait`). It used to be reconnected every 5 seconds indefinitely. A stream that delivers events between drops is kept up as before.
- **`yd-nodeaction --follow`** (with `--status`, or after submitting actions): a node whose action queue cannot be fetched is now reported (as "not found" for a node that does not exist), the other nodes' queues are still recorded, and the command exits 1, as it does without `--follow`. It used to drop the node, report that all queues had finished, and exit 0.
- **`yd-resize --json`**: a failure to find the target (a 401, or a lost connection, as well as not found) is now recorded as the target's `failed` record. The document used to be empty in that case. The exit code is unchanged.
- **`yd-delete`**: a confirmation prompt that cannot be answered (stdin at end of input, no `--yes`) now stops the command once. It used to record each path as a failed deletion and prompt again for the next.
- **`yd-download --sync`**: a wildcard whose matches the `--sync` safety check cannot list is now reported and recorded as failed, and not synced, while the other remote paths are still downloaded. It could previously be synced without the check, if its listing failed during the check and succeeded during the download.
- **`yd-submit`**, cleaning up after a failed submission: every uploaded file is now attempted for deletion. A failure deleting one used to stop the deletion of the rest.
- **`yd-doctor`**: a PAC failure whose message is empty now shows the exception's type.
- **`--debug`**: a failure loading the configuration file, or the `[workerPool]` section, that the loader cannot name now shows its traceback under `--debug`, as a failure in the `[workRequirement]` section already did. Without `--debug` it still exits 3 with the message.

### Cloud Wizard

- **Teardown** (AWS, Azure, GCP): if the connection to the YellowDog Platform is lost, or the YellowDog credentials are refused, part-way through, the YellowDog removals left are no longer attempted (each would fail the same way) and are recorded as not attempted, but the cloud provider's own removals still run. The run then ends by saying to run the teardown again, which removes what was left, and exits 8 or 4. It used to retry every remaining template, reporting the same error for each, and exit 1.
- **Azure setup**:
  - A region whose resource group cannot be checked is now counted as an error, so a setup that created nothing exits 1. It used to be a warning, and could exit 0.
  - A rollback that cannot delete a resource group the run has just created is now counted as an error, with the reason.
  - If the Platform cannot be reached when the YellowDog credential is created, the resource definition file is still saved, and the run ends by saying to run setup again, which creates what is missing, with exit 8 or 4.

### Commander

- On macOS, the system's `TSMSendMessageToUIServer ... FAILED(-1)` messages, which bypass Qt's logging, are no longer shown on Commander's stderr.
- A standalone command typed into Commander (`yd-version`, `yd-help`, `yd-schema`, `yd-jsonnet2json`) is now given `--nf`, unless that was typed too, so its output is plain text in the output pane.

### Development

- **`make coverage`**: line and branch coverage of the unit tests, with `pytest-cov` added to the `dev` extra. It prints a summary per file and writes the detail to `htmlcov/index.html`; see `DEVELOPMENT.md`.
- **`make complexity`**: a report of the package's code complexity — McCabe complexity worst first, ruff's counts of functions with too many branches, statements, returns or arguments, and function lengths; see `DEVELOPMENT.md`.
- **A test holds every broad exception handler** (`except Exception`, `except BaseException`, a bare `except:`) to either letting its failure reach the exit code, or being listed with the reason it need not (`tests/test_broad_excepts.py`).
- **Test runs**:
  - On macOS, the test that deliberately crashes a child interpreter is skipped unless `--run-crash-tests` is given, since each crash put up the system's "quit unexpectedly" dialog.
  - The Commander file dialog tests run on one pytest-xdist worker (`--dist=loadgroup`, now in `pyproject.toml`'s `addopts`), since Qt's file dialogs share settings that no test can isolate. Run in parallel, they failed intermittently.
- **Internal restructuring**, with no change to output: dispatch chains in `yd-show`, `yd-list`, the table builders and YDID typing replaced by tables, held by tests to the full set of types; the long functions in `yd-provision`, `yd-instantiate`, the configuration loaders, image name resolution, following and node actions split into named steps; and leftover module globals removed.
- **New tests** for the failure paths coverage found untested: the configuration's error exits, the event stream's failures, a missing property for every resource type `yd-create` and `yd-remove` handle, an Image Family's partial failures, and each `yd-list` table against the SDK model it reads.
