# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

YellowDog CLI (`yellowdog-cli`) is a Python CLI tool suite for managing distributed computing jobs and resources on the YellowDog platform. It provides ~25 `yd-*` commands (e.g., `yd-submit`, `yd-provision`, `yd-list`, `yd-upload`, `yd-download`) installable as a package.

Current version: defined in `yellowdog_cli/_version.py`.

## Commands

```bash
# Install in editable/development mode
make install          # builds then pip install -U -e .

# Format code (ruff check --fix + ruff format)
make format

# Build distribution
make build            # python -m build

# Run tests
pytest -v                           # standard tests only
pytest -v --run-demos               # include demo integration tests
pytest -v -n 4 --run-demos tests/test_demos.py  # parallel demos (target file to avoid unit tests consuming workers first)
pytest -v -k test_variable          # run a single test file/pattern

# Run tests across all supported Python versions (3.10–3.14) via tox + uv
make tox

# Type checking
make pyright

# Update dependencies
make update           # uv pip install -U -e ".[dev,jsonnet,cloudwizard]"
```

## Architecture

### Package Structure

```
yellowdog_cli/
├── __init__.py                  # Version only
├── *.py                         # ~29 command modules (one per yd-* command)
└── utils/
    ├── wrapper.py               # Global CLIENT + CONFIG_COMMON; @main_wrapper decorator
    ├── args.py                  # CLIParser class (single shared instance: ARGS_PARSER)
    ├── config_types.py          # Configuration dataclasses
    ├── load_config.py           # Config loading from TOML/env vars
    ├── settings.py              # Constants, env var names, Rich theme
    ├── entity_utils.py          # API entity lookups (LRU-cached search functions)
    ├── printing.py              # Rich-based output formatting
    ├── variables.py             # Variable substitution engine ({{ }} delimiters)
    ├── submit_utils.py          # Work requirement construction helpers; resolve_task_data() resolves taskData/taskDataFile (with variable substitution) for tasks and taskTemplate
    ├── csv_data.py              # CSV batch task processing; substitution uses << >> delimiters
    ├── property_names.py        # All TOML/JSON spec property name constants + ALL_KEYS list
    ├── ydid_utils.py            # YDIDType enum + get_ydid_type() prefix parser
    ├── items.py                 # Item TypeVar — union of all SDK model types used as a generic
    ├── type_check.py            # check_int/float/bool/str/list/dict — raise on type mismatch
    ├── validate_properties.py   # validate_properties(): checks dict keys against ALL_KEYS; warns on deprecated names
    ├── misc_utils.py            # generate_id(), format_yd_name(), load_dotenv_file(), link_entity(); delimiter-parsing helpers used by variables.py
    ├── load_resources.py        # load_resource_specifications(): loads TOML/JSON/Jsonnet files, applies substitutions, re-sequences in dependency order
    ├── provision_utils.py       # get_user_data_property() (reads/concatenates userdata scripts), get_template_id() (name→ID), get_image_id()
    ├── rclone_utils.py          # RcloneUploadedFiles: uploads task data input files via rclone; parses rclone connection strings; deduplicates
    ├── dataclient_utils.py      # Core logic for rclone-backed data client commands: resolve_remote_path(), upload_file/directory(), download_files(), delete_remote(), list_remote(), glob support
    ├── dataclient_wrapper.py    # @dataclient_wrapper decorator used by yd-upload/download/delete/ls (no SDK client needed)
    ├── follow_utils.py          # follow_ids(): subscribes to SSE event streams for WRs/WPs/CRs in daemon threads; auto-reconnects on drop
    ├── interactive.py           # confirmed() (respects --yes/YD_YES), select() (numbered list selection with range syntax e.g. 1,2,4-7)
    ├── start_hold_common.py     # Shared logic for yd-start and yd-hold: filter by status, confirm, apply action
    ├── compact_json.py          # CompactJSONEncoder: small containers on one line, larger ones indented
    ├── check_imports.py         # Guards for optional imports (jsonnet, cloudwizard) with install hints
    ├── rich_console_input_fixed.py  # ConsoleWithInputBackspaceFixed: workaround for Rich backspace-deletes-prompt bug
    └── cloudwizard_*.py         # AWS/Azure/GCP provider integration (cloudwizard_common, _aws, _aws_types, _azure, _gcp); sets up compute source/requirement templates and credentials; no longer creates cloud storage buckets or namespace storage configurations
```

### Command Pattern

Most command modules use `@main_wrapper` (requires YellowDog SDK client):

```python
from yellowdog_cli.utils.wrapper import main_wrapper

# Module-level config loading (runs at import time)
CONFIG_XXX = load_config_xxx()

@main_wrapper
def main():
    # Command logic using CLIENT, ARGS_PARSER, CONFIG_COMMON from wrapper
    ...

if __name__ == "__main__":
    main()
```

A small number of standalone commands (`yd-help`, `yd-version`, `yd-format-json`, `yd-jsonnet2json`) need neither credentials nor a config file — they just define a bare `main()` function with no decorator.

Data client commands (`yd-upload`, `yd-download`, `yd-delete`, `yd-ls`) use `@dataclient_wrapper` instead — no SDK client is initialised:

```python
from yellowdog_cli.utils.dataclient_wrapper import dataclient_wrapper

CONFIG_DATA_CLIENT: ConfigDataClient = load_config_data_client()

@dataclient_wrapper
def main():
    # Command logic using ARGS_PARSER and CONFIG_DATA_CLIENT
    ...
```

### Global State (wrapper.py)

`wrapper.py` initialises two module-level globals used everywhere:
- `CLIENT` — `PlatformClient` instance (YellowDog SDK)
- `CONFIG_COMMON` — loaded from `config.toml` (or `--config` arg / env vars)

`ARGS_PARSER` is a `CLIParser` instance from `args.py`, also module-level. These three are imported directly by command modules.

The `@main_wrapper` decorator handles: PAC proxy setup, exception catching (permission/auth errors), `CLIENT.close()`, and exit codes.

### Configuration

Config is loaded from (in priority order): CLI args → environment variables → TOML file. Exception: if the config file is explicitly selected with `--config`/`-c`, its contents (including `[common.variables]`) take precedence over environment variables, but not over CLI args (see `config_file_explicitly_selected()` in `misc_utils.py` and `add_substitutions_from_config_file()` in `variables.py`). The `YD_CONF` env var is no longer supported (commands error if it is set). Key env vars: `YD_KEY`, `YD_SECRET`, `YD_NAMESPACE`, `YD_TAG`, `YD_URL`. Variables prefixed `YD_VAR_` are available for substitution in specs.

Any TOML property can be overridden on the command line with `--property 'section.key=value'` (repeatable). Valid sections: `common`, `dataClient`, `workRequirement`, `workerPool`, `computeRequirement`. Values are JSON-parsed first (handles bool, int, float, list, dict), falling back to plain string. Overrides are applied after TOML validation in `load_config.py` via `_apply_property_overrides()`.

### Variable Substitution

Specs (TOML/JSON/Jsonnet) support `{{variable_name}}` substitution with type tags: `num:`, `bool:`, `array:`, `table:`, `format_name:`. Default values use `:=` separator. Environment variables via `env:` prefix. Up to 3 levels of nesting (`TOML_VAR_NESTED_DEPTH = 3`).

The `::` unset suffix (`{{varname::}}`) removes a property entirely when the variable is undefined; if defined, its value is used normally. The bare `{{::}}` always removes the property unconditionally. Both work in TOML, JSON, and Jsonnet — `process_variable_substitutions_in_file_contents` leaves unset tokens intact so `process_variable_substitutions_insitu` can remove them after parsing.

CSV batch task prototypes use a separate `<<variable_name>>` delimiter system (defined in `csv_data.py`), distinct from `{{`/`}}` to allow both to coexist in the same spec without ambiguity.

### Coding Conventions

- Python 3.10+ syntax: use `str | None` (not `Optional[str]`), `match` statements where appropriate
- Type hints on all new functions
- Constants in `settings.py` (UPPERCASE); property name constants prefixed `PROP_`, resource name constants prefixed `RN_`
- Use `print_error()`, `print_info()`, `print_warning()` from `printing.py` — never `print()` directly
- LRU cache on entity lookup functions in `entity_utils.py`
- Config dataclasses in `config_types.py`; no raw dicts for structured config

### Testing Commander's GUI

Commander's dialogs are tested as dialogs, through `tests/gui_harness.py` (generic Qt helpers) and `tests/commander_dialogs.py` (drivers for Commander's own confirmation and chooser). Three rules, each of which exists because breaking it let a bug reach a user:

- **Never stub `dialog.exec()`.** Use `gui_harness.run_modal()` when the test owns the dialog, or `commander_dialogs.drive_confirmation()` / `drive_chooser()` when production builds and execs it. Both queue the interaction with `QTimer.singleShot(0, ...)` so it lands inside the *real* modal loop, which means a click has to travel the real button-box wiring to have any effect. A stubbed `exec()` cannot tell a working button from an inert one.
- **Assert geometric relationships, never pixel counts.** `gui_harness.visible_rows(listing)` rather than a height in pixels: CI nodes substitute fonts, so absolute measurements do not travel. A list squeezed flat or robbed of its height by a scrollbar still has correct-looking arithmetic — only "how many rows can be seen" catches it.
- **Assert outcomes, not arguments.** Contract tests over `_run_command_in_subprocess` args are useful but blind: every GUI bug that has reached a user lived in a seam those tests stubbed or asserted around.

Everything runs under `QT_QPA_PLATFORM=offscreen` with no display, so it works on a headless CI node. Nodes without a usable Qt skip: every Commander test module calls `tests/qt_guard.py`'s `require_qt()` before importing anything that pulls in Qt, and the `qapp` fixture guards again. That guard is deliberately not `pytest.importorskip` — from pytest 9.1 it skips only on `ModuleNotFoundError`, so PyQt6-installed-but-`libGL`-missing (a minimal Linux image) errored instead of skipping. Calling it before the imports is what the `E402` per-file ignores in `pyproject.toml` are for. Modal runs are watchdogged, because a dialog that never closes would hang CI rather than fail it. An autouse `conftest` fixture surfaces assertions raised inside Qt callbacks, which Qt would otherwise print and discard.

Note that `_build_destructive_dialog` returns a dialog whose buttons are *not* wired — `_confirm_destructive` attaches a `clicked` handler afterwards, because it needs to know which button was pressed. Drive it through `_confirm_destructive`, not from the builder. `_build_chooser_dialog` wires its own box and can be driven directly.

### Dependencies

- `yellowdog-sdk` — YellowDog platform API client
- `rich` (pinned 13.9.4) — terminal output formatting
- `tomli` — TOML parsing
- `python-dotenv` — `.env` file support
- `pypac` — proxy auto-configuration
- `jsonnet` — optional, for Jsonnet spec templating
- `rclone_api` — Python wrapper around the rclone binary; used by data client commands
- Cloud wizard extras: `boto3`, `google-cloud-*`, `azure-*`