# Changelog

The user-visible changes in each release of the YellowDog CLI, the newest first. Releases up to v13.1.0 are not recorded here.

## Unreleased

### New commands

- **`yd-compute-deprovision`** terminates Instances and reduces their Compute Requirement's target instance count to match, so that they are not replaced, as they would be after `yd-terminate` in a Compute Requirement that maintains its instance count. Instances are named as `yd-compute-restart` takes them (`cr_id.instance_id` or a Node ID), confirmed together, with `--json` and `--follow`. It is also available to MCP clients as the `yd_compute_deprovision` tool.
- **`yd-token`** refreshes the token of one or more Configured Worker Pools, keeping it and setting its expiry afresh, or with `--regenerate` issues a new one, invalidating the old. Either is confirmed first, the prompt saying what the expiry will be. `--ttl-hours` sets the token's time to live from now; without it, the token does not expire. Pools are named by ID, name or glob pattern; the new token and its expiry are printed, or recorded with `--json`. It is also available to MCP clients as the `yd_token` tool.

### Diagnosing a Compute Requirement

- **`yd-show --show-source-report`** follows a Compute Requirement with the Platform's report of how its sources were chosen (considered, selected and rejected Compute Source Templates, ranks, scores, constraints and preferences), for one provisioned from a dynamic template.
- **`yd-show --show-exhaustion`** follows it with the Allowances exhausted for it, so that you can see which to boost with `yd-boost`.
- Both also take a Provisioned Worker Pool's ID, reporting on its Compute Requirement.

### Output

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
