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
| `test_compact_json.py` | `utils/compact_json.py` — `CompactJSONEncoder` (inline vs. expanded formatting, float precision) |
| `test_compare.py` | `compare.py` — pure static comparison helpers |
| `test_compute_action_common.py` | `utils/compute_action_common.py` — `yd-compute-stop/start/restart` actions: dispatch, tag-based selection, name/ID, instance and node paths |
| `test_csv_data.py` | `utils/csv_data.py` — `CSVTaskData`, `CSVDataCache`, substitution helpers |
| `test_dataclient_utils.py` | `utils/dataclient_utils.py` — `resolve_remote_path` (rclone remote path resolution, trailing-slash directory intent) |
| `test_environment_merge.py` | `utils/submit_utils.py` — `merge_environment` (addEnvironment merging and key-override behaviour) |
| `test_instance_pricing_preference.py` | `instancePricingPreference` enum, config field, and `load_config_work_requirement()` mapping |
| `test_interactive.py` | `utils/interactive.py` — `confirmed` (--yes / YD_YES shortcuts), `get_selected_list_items` (range parsing: comma, dash, `*`, error recovery) |
| `test_load_config_helpers.py` | `utils/load_config.py` — helpers not covered by other test files |
| `test_ls_formatting.py` | `ls.py` — `_print_listing`, `_print_flat`, `_print_tree` output formatting |
| `test_misc_utils.py` | `utils/misc_utils.py` — name formatting, ID generation, delimiter parsing, etc. |
| `test_node_batching.py` | `provision.py`, `instantiate.py` — `_allocate_nodes_to_batches`: batch count, even distribution, remainder spreading, zero-node edge cases |
| `test_nodeaction_args.py` | `utils/args.py` — `yd-nodeaction` argument parsing |
| `test_nodeaction_parsing.py` | `nodeaction.py` — parsing helpers (`_parse_node_worker_target`, etc.) |
| `test_printing.py` | `utils/printing.py` — `_truncate_text`, `_yes_or_no`, `indent`, `status_counts_msg`, `get_type_name`, `print_string`; table-building helpers |
| `test_property_overrides.py` | `utils/load_config.py` — `_apply_property_overrides`, `_parse_property_value` (CLI `--property` flag) |
| `test_provision_utils.py` | `utils/provision_utils.py` — user data reading/concatenation via `get_user_data_property` |
| `test_rclone_utils.py` | `utils/rclone_utils.py` — `parse_rclone_config` (plain remotes and inline config strings); `make_rclone_for_copy` remote-name collision handling |
| `test_resequence_resources.py` | `utils/load_resources.py` — `_resequence_resources` (creation/removal dependency ordering) |
| `test_resolve_entity_type.py` | `utils/args.py` — `resolve_entity_type` (full names, prefixes, synonyms) |
| `test_select_dc_section.py` | `utils/load_config.py` — `_select_dc_section` (data client profile selection and merging) |
| `test_start_hold_common.py` | `utils/start_hold_common.py` — `yd-start`/`yd-hold` named and tag-based paths |
| `test_submit_batching.py` | `submit.py` — sequential vs. parallel task batch submission in `add_tasks_to_task_group` |
| `test_submit_functions.py` | `submit.py` — `create_task_group` and `submit_work_requirement` |
| `test_submit_utils.py` | `utils/submit_utils.py` — task/task-group naming, `get_task_data_property`, `create_task` |
| `test_type_check.py` | `utils/type_check.py` — `check_int/float/bool/str/list/dict` |
| `test_upload_destination.py` | `upload.py` — `--destination` handling for single vs. multiple files and `dir/` destinations |
| `test_validate_properties.py` | `utils/validate_properties.py` — `validate_properties` (key validation, deprecated and excluded keys) |
| `test_variable_processing.py` | `utils/misc_utils.py` — `split_delimited_string`, `remove_outer_delimiters` |
| `test_variable_subs.py` | `utils/variables.py` — `{{variable}}` substitution engine |
| `test_ydid_utils.py` | `utils/ydid_utils.py` — `get_ydid_type`, type constants |

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
| `test_system_error_handling.py` | Hard failures (exit 1) and soft failures (exit 0 + error message) for bad input, unknown YDIDs, missing resources |
| `test_system_resources.py` | Full create → list → show → remove lifecycle for keyrings, namespaces, image families, namespace policies, attributes, groups |
| `test_system_cancel_hold_finish.py` | Work Requirement control commands: hold, start, finish, cancel (WR stays PENDING — no compute provisioned) |
| `test_system_dataclient.py` | Data client commands (`yd-upload`, `yd-ls`, `yd-download`, `yd-delete`): upload/list/delete cycle, upload→download round-trip, recursive upload and listing, wildcard list and delete, dry-run enforcement for upload/download/delete |

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