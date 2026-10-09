# Changelog

The user-visible changes in each release of the YellowDog CLI, the newest first. Releases up to v13.1.0 are not recorded here.

## Unreleased

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
- **Documentation:** the README is now a short landing page, and the rest of the documentation has moved to pages under [docs/](docs/), one per topic: the [Command List](docs/commands.md), [configuration](docs/configuration.md), [variable substitutions](docs/variables.md), [Work Requirements](docs/work-requirements.md) and their [Property Dictionary](docs/property-dictionary.md), [Worker Pools](docs/worker-pools.md), the [data client](docs/data-client.md), [resources](docs/resources.md), [Jsonnet](docs/jsonnet.md), and [machine-readable output and exit codes](docs/json-output.md). Each top-level section's old heading in the README remains, pointing to its page; a link to a deeper section of the old README (e.g. `README.md#yd-submit`) now lands at the top of the README.
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
