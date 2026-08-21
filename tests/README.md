# Tests

Tests are run using [pytest](https://docs.pytest.org/).

The unit tests need no configuration at all: a yd-* command module loads its configuration when imported, so `conftest.py` substitutes a dummy key and secret where none can be found, and reports that in the pytest header. Anything already working is left alone, and no substitution is made for the flags below that reach the platform.

## Test Categories

Five categories of test exist, controlled by pytest flags:

| Flag | Marker | Description |
|---|---|---|
| *(none)* | — | Unit tests; no platform connectivity, configuration file or credentials required |
| `--run-dryruns` | `dryruns` | Demo dry-runs (no platform calls); requires `../python-examples-demos` |
| `--run-demos` | `demos` | Full live demo runs on the platform |
| `--run-system` | `system` | System tests (resource CRUD, error handling, WR control); requires credentials |
| `--run-system-compute` | `system_compute` | System tests that provision real cloud compute (implies `--run-system`) |

Around 350 of the unit tests are [Commander GUI tests](#commander-gui-tests). They are controlled by no flag, but they skip where PyQt6 or Qt's runtime libraries are unavailable, so a run without them reports fewer passes and more skips rather than any failure.

## Quick Reference

```shell
# Unit tests only (no credentials needed)
pytest -v

# Add demo dry-runs (requires ../python-examples-demos)
pytest -v --run-dryruns

# Add system tests (credentials required)
pytest -v --run-system

# Add compute-provisioning tests (slow, costs money)
pytest -v --run-system-compute

# Add live demos
pytest -v --run-demos

# Everything
pytest -v --run-dryruns --run-system-compute --run-demos

# Run a single file or pattern
pytest -v tests/test_ydid_utils.py
pytest -v -k test_variable

# Parallel execution
pytest -v -n 4 --run-dryruns
pytest -v -n 4 --run-demos
```

## Test Files

### Unit Tests (no flags required, no credentials needed)

| File | What it tests |
|---|---|
| `test_add_to.py` | `submit.py` — `--add-to` feature: offset-aware task/task-group naming and dispatch logic |
| `test_args_command_detection.py` | `utils/args.py` — command detection uses the basename of `sys.argv[0]`, not the full install path |
| `test_arguments_assembly.py` | `utils/submit_utils.py` — `assemble_arguments` (argumentsPrefix + arguments + argumentsPostfix combination) |
| `test_build_dc_substitutions.py` | `utils/load_config.py` — `_build_dc_substitutions` (data client config merging and inheritance) |
| `test_cancel_glob.py` | `cancel.py` — glob vs. literal name/YDID selection for `yd-cancel`: dry-run reporting of the matched Work Requirements, exclusion of terminal statuses |
| `test_check_imports.py` | `utils/check_imports.py` — the optional-import guards (jsonnet, Cloud Wizard, Commander) and their install hints |
| `test_compact_json.py` | `utils/compact_json.py` — `CompactJSONEncoder` (inline vs. expanded formatting, float precision) |
| `test_compare.py` | `compare.py` — pure static comparison helpers |
| `test_compute_action_common.py` | `utils/compute_action_common.py` — `yd-compute-stop/start/restart` actions: dispatch, tag-based selection, name/ID, instance and node paths |
| `test_csv_data.py` | `utils/csv_data.py` — `CSVTaskData`, `CSVDataCache`, substitution helpers |
| `test_dataclient_utils.py` | `utils/dataclient_utils.py` — `resolve_remote_path` (rclone remote path resolution, trailing-slash directory intent) |
| `test_download_destination.py` | `download.py` — where each item lands locally: `--destination` vs. `--into` for one glob, one literal path and several literal paths |
| `test_dryrun_flags.py` | `utils/args.py` — the dry-run flags on `yd-cancel`/`yd-shutdown`/`yd-terminate`: presence in `--help` and the parse-time by-name guard (no platform contact) |
| `test_dryrun_utils.py` | `utils/dryrun_utils.py` — `report_dry_run` (human table via `yd-list`'s renderer, JSON output, empty match set) |
| `test_environment_merge.py` | `utils/submit_utils.py` — `merge_environment` (addEnvironment merging and key-override behaviour) |
| `test_follow_utils.py` | `utils/follow_utils.py` — SSE event-stream following: subscription, reconnection after a dropped stream, thread lifecycle |
| `test_glob_utils.py` | `utils/glob_utils.py`, `utils/entity_utils.py`, `utils/dataclient_utils.py` — the shared glob helpers: `contains_glob_chars`, `glob_search_prefix`, `is_glob`, `filter_summaries_by_name_glob`, `resolve_name_glob`, `expand_name_globs`, `describe_glob_scope` |
| `test_instance_pricing_preference.py` | `instancePricingPreference` enum, config field, and `load_config_work_requirement()` mapping |
| `test_interactive.py` | `utils/interactive.py` — `confirmed` (--yes / YD_YES shortcuts), `get_selected_list_items` (range parsing: comma, dash, `*`, error recovery) |
| `test_list_name_glob.py` | `list.py` — `yd-list --name` glob filtering for every entity type that supports it, rejection for those that don't, and the warnings for unnamed items |
| `test_load_config_helpers.py` | `utils/load_config.py` — helpers not covered by other test files |
| `test_ls_formatting.py` | `ls.py` — `_print_listing`, `_print_flat`, `_print_tree` output formatting |
| `test_matched_item_rows.py` | `utils/dataclient_utils.py` — `matched_item_rows`, the enumeration behind `yd-delete`/`yd-download --dry-run --json`: each row's path must be usable verbatim and joined to the directory it came from |
| `test_misc_utils.py` | `utils/misc_utils.py` — name formatting, ID generation, delimiter parsing, etc. |
| `test_node_batching.py` | `provision.py`, `instantiate.py` — `_allocate_nodes_to_batches`: batch count, even distribution, remainder spreading, zero-node edge cases |
| `test_nodeaction_args.py` | `utils/args.py` — `yd-nodeaction` argument parsing |
| `test_nodeaction_parsing.py` | `nodeaction.py` — parsing helpers (`_parse_node_worker_target`, etc.) |
| `test_printing.py` | `utils/printing.py` — `_truncate_text`, `_yes_or_no`, `indent`, `status_counts_msg`, `get_type_name`, `print_string`; table-building helpers |
| `test_property_overrides.py` | `utils/load_config.py` — `_apply_property_overrides`, `_parse_property_value` (CLI `--property` flag) |
| `test_provision_utils.py` | `utils/provision_utils.py` — user data reading/concatenation via `get_user_data_property` |
| `test_rclone_utils.py` | `utils/rclone_utils.py` — `parse_rclone_config` (plain remotes and inline config strings); `make_rclone_for_copy` remote-name collision handling |
| `test_rclone_version.py` | `utils/rclone_version.py` — the rclone version lookup order, parsing of `rclone --version` output, and not-installed handling |
| `test_resequence_resources.py` | `utils/load_resources.py` — `_resequence_resources` (creation/removal dependency ordering) |
| `test_resolve_entity_type.py` | `utils/args.py` — `resolve_entity_type` (full names, prefixes, synonyms) |
| `test_resource_property_coverage.py` | `resource_models.py` — the write-side coverage gate: every settable property of every SDK model the resource corpus (`tests/resources/`) touches must be set by some specification, or excluded with an evidenced reason |
| `test_resource_specs.py` | `resource_corpus.py`/`resource_models.py` — offline coverage of the resource corpus: each `.jsonnet` file is loaded through the CLI's own loader and built into the same SDK model(s) `create.py` builds, checking every property survives with the value sent; no credentials or network needed |
| `test_retry_failure_policy.py` | `utils/submit_utils.py`, `submit.py` — the `RetryPolicy`/`FailurePolicy`/`TaskErrorSelector`/`Selection` builders, and the conflict and deprecation handling around them |
| `test_select_dc_section.py` | `utils/load_config.py` — `_select_dc_section` (data client profile selection and merging) |
| `test_show_instance.py` | `show.py` — the Instance (`cr_id.instance_id`) form: routing, lookup and error paths |
| `test_shutdown_glob.py` | `shutdown.py` — glob vs. literal name selection for `yd-shutdown`, excluding already-finished Worker Pools |
| `test_sorted_objects.py` | `utils/printing.py` — `sorted_objects`: `--sort created` ordering of entity summaries, earliest first, with `--reverse` inverting it |
| `test_start_hold_common.py` | `utils/start_hold_common.py` — `yd-start`/`yd-hold` named and tag-based paths |
| `test_submit_batching.py` | `submit.py` — sequential vs. parallel task batch submission in `add_tasks_to_task_group` |
| `test_submit_functions.py` | `submit.py` — `create_task_group` and `submit_work_requirement` |
| `test_submit_utils.py` | `utils/submit_utils.py` — task/task-group naming, `get_task_data_property`, `create_task` |
| `test_terminate_glob.py` | `terminate.py` — name/ID selection for `yd-terminate`: glob filtering, literal names, and the Instance (`cr_id.instance_id`) form |
| `test_type_check.py` | `utils/type_check.py` — `check_int/float/bool/str/list/dict` |
| `test_upload_destination.py` | `upload.py` — `--destination` handling for single vs. multiple files and `dir/` destinations |
| `test_user_agent.py` | `utils/user_agent.py` — direct CLI calls carry a CLI-only User-Agent, SDK calls additionally advertise the SDK version |
| `test_validate_properties.py` | `utils/validate_properties.py` — `validate_properties` (key validation, deprecated and excluded keys) |
| `test_variable_processing.py` | `utils/misc_utils.py` — `split_delimited_string`, `remove_outer_delimiters` |
| `test_variable_subs.py` | `utils/variables.py` — `{{variable}}` substitution engine |
| `test_ydid_utils.py` | `utils/ydid_utils.py` — `get_ydid_type`, `split_instance_specification` (the `cr_id.instance_id` form, including dotted instance IDs), type constants |

### Commander GUI Tests (no flags required; skipped without a usable Qt)

Around 350 tests covering `yd-commander`. They need PyQt6 (the `commander` extra) and the Qt runtime libraries it links against; where either is missing every module below skips and the rest of the suite runs normally. See [Commander GUI Tests](../DEVELOPMENT.md#commander-gui-tests) in the development guide for the libraries a minimal Linux image needs, and the *Testing Commander's GUI* section of [`CLAUDE.md`](../CLAUDE.md) for the conventions these follow — chiefly that a dialog under test runs its real `exec()`, and that geometry is asserted as relationships rather than pixel counts.

| File | What it tests |
|---|---|
| `test_commander_button_wiring.py` | Every main-window button is connected to the action it claims to perform — a button wired to nothing, or to the wrong action, looks healthy to every other test |
| `test_commander_commands.py` | Each action translates into the correct `yd-*` command and arguments (`_run_command_in_subprocess` stubbed, so nothing is spawned), and a selected definition file survives the hand-over — its path resolved against the directory the command runs in, and read back through Show |
| `test_commander_dialog_behaviour.py` | The dialogs as dialogs: real `exec()`, real clicks, real geometry — the bug classes that reached users (inert buttons, a stolen default button, a list squeezed until no row shows) |
| `test_commander_entity_selection.py` | Choosing which entities a bulk destructive action affects: the listing, the `Confirmation` returned, and the YDIDs that reach the command |
| `test_commander_entity_summaries.py` | Parsing `-D --json` entity listings; a listing without YDIDs must be refused rather than falling back to name-based targeting |
| `test_commander_object_selection.py` | Choosing which objects a deletion removes: enumeration, object rows, and the paths that reach `yd-delete` |
| `test_commander_download_selection.py` | Choosing which objects a download fetches, and how the chooser differs from a destructive confirmation |
| `test_commander_deselect.py` | The Deselect Files action: which of the currently-selected files get deselected |
| `test_commander_selection_labels.py` | Selected definition files shown on their own 'Select' buttons, without widening the left-hand column |
| `test_commander_reentrancy.py` | The guard that stops a second action starting while one is enumerating in a nested event loop |
| `test_commander_shutdown.py` | The shutdown path: no process destroyed while running, no handler firing against a deleted object, nested loops released |
| `test_commander_file_preview.py` | The preview pane the file dialogs carry — image, text, binary, directory and vanished-file branches, its headings staying at the top of the pane, and its draggable width — the names-only expandable listing (including that a file picked inside an expanded directory comes back with its full path) and the width the places sidebar opens at, both remembered as the user leaves them, the hand-over to the platform's file viewer, and what browsing, selecting and saving do with the file the user picks |
| `test_commander_save_output.py` | Saving the output window: what is written, dismissal, and that a write failure is reported rather than swallowed |
| `test_commander_notices.py` | The modal notice for a missing `results` directory: shown and logged, one OK button, plain text so a Windows path survives, and log-only under `--yes` or shutdown |
| `test_commander_logging.py` | How a command is echoed into the output window; many YDIDs collapse to a count |
| `test_commander_config_discovery.py` | The `yd-show` run behind the placeholders: what each failure reports, that a timed-out discovery is retried once with a longer budget, and that every path into discovery gets that retry |
| `test_commander_placeholders.py` | Namespace / tag / object-path placeholder text, and the repaint strategy that avoids a macOS log burst |
| `test_commander_history.py` | `CommandHistory` recall-pointer logic (pure Python, no event loop) |
| `test_commander_line_buffer.py` | `LineBuffer` reassembly of subprocess output across read boundaries |
| `test_commander_elide_path.py` | Display-elision helpers for the config path and definition filenames |
| `test_commander_ui_loads.py` | `commander.ui` loads against the installed PyQt6, every code-referenced widget exists, the separator below the View Config Directory row lies between that row and the one beneath it, and the top two rows of the two columns share a grid row with the separator under them |
| `test_commander_resources.py` | The package data (`.ui` file and images) is present and resolvable through the installed package |
| `test_commander_entrypoint.py` | The `yd-commander` console script is registered and has its own CLI, not the shared parser |
| `test_gui_harness.py` | Self-tests for the harness itself: that it surfaces hangs and assertions instead of swallowing them, and that its geometry helper measures what it claims |

These are supported by three non-test modules and by fixtures in the root `conftest.py`:

| File | Role |
|---|---|
| `gui_harness.py` | Generic Qt helpers: run or arm a dialog so an interaction lands inside its real modal loop, watchdogged; count visible rows; find buttons |
| `commander_dialogs.py` | Drivers for Commander's own confirmation, chooser and notice, for the cases where production builds and execs the dialog |
| `qt_guard.py` | `require_qt()` — the module-level skip, used instead of `pytest.importorskip` so that PyQt6-present-but-unusable skips rather than errors |
| `conftest.py` | `qapp` (one offscreen `QApplication`), `_gui_harness_guard` (surfaces what happened inside Qt callbacks), `_no_config_discovery` (stubs `_parse_yd_config`, so no test spawns `yd-show`; opt out with `@pytest.mark.real_config_parse`), `commander_dialog_settings` (points `dialog_settings()` at an ini file of the test's own, so no test reads or writes the developer's real file-dialog preferences), and `qt_sidebar_width` with `_preserve_qt_sidebar_width` (set what *Qt* remembers for its sidebar width — the one case that proves Commander ignores it — and put the machine's own value back afterwards) |

### Dry-run Tests (`--run-dryruns`, requires `../python-examples-demos`)

| File | What it tests |
|---|---|
| `test_dryruns.py` | All standard demos in `--dry-run` mode (no platform calls); GUI starts and stays up |

### Other No-Flag Tests (no credentials needed)

| File | What it tests |
|---|---|
| `test_entrypoints.py` | All `yd-*` CLI entry points are present and respond to `--help` |

### System Tests (`--run-system`, credentials required)

| File | What it tests |
|---|---|
| `test_dryrun_system.py` | End-to-end `--dry-run` for `yd-cancel`/`yd-shutdown`/`yd-terminate`: they contact the platform to list entities, using an empty namespace and tag so the matching set is empty and nothing can be acted on |
| `test_system_error_handling.py` | Hard failures (exit 1) and soft failures (exit 0 + error message) for bad input, unknown YDIDs, missing resources |
| `test_system_resources.py` | Create → `yd-show`/`yd-list --details` → remove lifecycle for every file in the resource corpus (`tests/resources/`), parametrized one case per file, comparing what the platform returns against what was sent; also the read gate, confirming every property the write-side coverage gate excludes as platform-assigned actually comes back from a live response at least once |
| `test_system_cancel_hold_finish.py` | Work Requirement control commands: hold, start, finish, cancel (WR stays PENDING — no compute provisioned) |
| `test_system_dataclient.py` | Data client commands (`yd-upload`, `yd-ls`, `yd-download`, `yd-delete`): upload/list/delete cycle, upload→download round-trip, recursive upload and listing, wildcard list and delete, dry-run enforcement for upload/download/delete |

`test_system_resources.py` is built on the resource corpus and shares its three supporting modules with the offline `test_resource_specs.py`/`test_resource_property_coverage.py` above:

| File | Role |
|---|---|
| `resource_corpus.py` | Loads a corpus file the way `yd-create` does — Jsonnet expansion, `{{variable}}` substitution, dependency resequencing — without a platform |
| `resource_models.py` | Which SDK model(s) `create.py` builds for each resource type, and the write-side coverage gate over their settable properties |
| `resource_live.py` | Helpers for the live suite: `yd()`/`ydids()`/`show()` subprocess wrappers, and `mismatches()`, the create-vs-`yd-show` comparison |

Beyond the general platform-test prerequisites below, the resource corpus needs only `YD_KEY` and `YD_SECRET` in the environment (plus `YD_URL` for a non-default platform). It requires no configuration file of your own and no cloud credentials: `tests/resources/test-config.toml` supplies the namespace and the dummy infrastructure values, and deliberately carries no credentials and imports none — see `tests/resources/README.md`.

### System Compute Tests (`--run-system-compute`, provisions real cloud instances)

| File | What it tests |
|---|---|
| `test_system_lifecycle.py` | Minimal end-to-end: provision pool → submit trivial WR → follow to completion → shutdown |
| `test_system_csv_batch.py` | CSV-driven batch: 10 tasks from `tasks.csv`, all verified complete |
| `test_system_resize.py` | Worker Pool resize: provision with 1 node, resize to 2, verify, tear down |

### Demo Tests (`--run-demos`, provisions real cloud instances)

| File | What it tests                                                  |
|---|----------------------------------------------------------------|
| `test_demos.py` | Full live runs of all standard python-examples-demos workloads |

### Other Platform Tests (no flags, but credentials required)

| File | What it tests |
|---|---|
| `test_create_remove.py` | `yd-create` / `yd-remove` round-trips for all resource types |
| `test_list.py` | `yd-list` with various resource-type filters |

`test_create_remove.py`'s fourteen cases depend on `tests/resource-examples/`, a directory that is not tracked in the repository — a deliberate choice, not an oversight, so it only runs on the repository owner's machine, and fails on missing files for anyone else who runs it. It overlaps `test_system_resources.py`'s live corpus suite in what it exercises, but asserts only exit codes, never that a returned property matches what was sent. It is currently the only coverage this suite has of a user update (`user.json`) and of an application granted access to a keyring (`application-with-keyring.json`), neither of which the resource corpus covers.

## Prerequisites for Platform Tests

Set credentials in the environment or provide a `config.toml`:

```shell
export YD_KEY=...
export YD_SECRET=...
export YD_URL=...   # optional, defaults to production
```

`test_system_dataclient.py` additionally requires a `[dataClient]` section in `tests/system/config.toml` (rclone connection string and remote path).

## Parallel Execution

Unit, dry-run, and demo tests support parallel execution via `pytest-xdist`:

```shell
pytest -v -n 4                                         # 4 workers, unit tests only
pytest -v -n 4 --run-dryruns tests/test_dryruns.py    # parallel dry-runs (target file directly)
pytest -v -n 12 --run-demos tests/test_demos.py       # parallel live demos (target file directly)
pytest -v -n 4 --run-demos tests/test_demos.py -k 'bash or primes'
```

> Targeting the test file directly avoids unit tests consuming all workers before the slower tests are scheduled.