# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

YellowDog CLI (`yellowdog-cli`) is a Python CLI tool suite for managing distributed computing jobs and resources on the YellowDog platform. It provides ~25 `yd-*` commands (e.g., `yd-submit`, `yd-provision`, `yd-list`, `yd-upload`, `yd-download`) installable as a package. It also provides `yd-commander`, a PyQt6 desktop GUI that drives those same commands (see [Commander](#commander)).

Current version: defined in `yellowdog_cli/_version.py`.

## Commands

```bash
# Install in editable/development mode
make install          # builds, then uv pip install -U -e ".[commander,jsonnet,cloudwizard]"

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
make update           # uv pip install -U -e ".[dev,commander,jsonnet,cloudwizard]"
```

## Architecture

### Package Structure

```
yellowdog_cli/
├── __init__.py                  # Version only
├── *.py                         # ~29 command modules (one per yd-* command)
├── commander/                   # yd-commander: the PyQt6 desktop GUI (see Commander below)
│   ├── launcher.py              # Entry point; argument parsing and the PyQt6 guard, before any Qt import
│   ├── __main__.py              # 'python -m yellowdog_cli.commander'
│   ├── commander.py             # The whole GUI: YellowDogApp plus its dialogs and helpers
│   ├── commander.ui             # Qt Designer layout, loaded by loadUi() at construction
│   ├── images/                  # Branding and window icons (light/dark)
│   └── README.md                # User-facing documentation for the GUI
└── utils/
    ├── wrapper.py               # Global CLIENT + CONFIG_COMMON; @main_wrapper decorator
    ├── args.py                  # CLIParser class (single shared instance: ARGS_PARSER)
    ├── config_types.py          # Configuration dataclasses
    ├── load_config.py           # Config loading from TOML/env vars
    ├── settings.py              # Constants, env var names, Rich theme
    ├── entity_utils.py          # API entity lookups (LRU-cached search functions); name-glob resolution, expansion and filtering for entity selection
    ├── glob_utils.py            # contains_glob_chars() and glob_search_prefix(): the glob-character set, and the literal prefix a pattern can be searched by
    ├── printing.py              # Rich-based output formatting
    ├── variables.py             # Variable substitution engine ({{ }} delimiters)
    ├── submit_utils.py          # Work requirement construction helpers; resolve_task_data() resolves taskData/taskDataFile (with variable substitution) for tasks and taskTemplate
    ├── csv_data.py              # CSV batch task processing; substitution uses << >> delimiters
    ├── property_names.py        # All TOML/JSON spec property name constants + ALL_KEYS list
    ├── ydid_utils.py            # YDIDType enum + get_ydid_type() prefix parser; split_instance_specification() splits 'cr_id.instance_id' on the first dot only, so dotted instance IDs (OCI OCIDs) survive
    ├── items.py                 # Item TypeVar — union of all SDK model types used as a generic
    ├── type_check.py            # check_int/float/bool/str/list/dict — raise on type mismatch
    ├── validate_properties.py   # validate_properties(): checks dict keys against ALL_KEYS; warns on deprecated names
    ├── misc_utils.py            # generate_id(), format_yd_name(), load_dotenv_file(), link_entity(); delimiter-parsing helpers used by variables.py
    ├── load_resources.py        # load_resource_specifications(): loads TOML/JSON/Jsonnet files, applies substitutions, re-sequences in dependency order
    ├── provision_utils.py       # get_user_data_property() (reads/concatenates userdata scripts), get_template_id() (name→ID), get_image_id()
    ├── rclone_utils.py          # RcloneUploadedFiles: uploads task data input files via rclone; parses rclone connection strings; deduplicates
    ├── rclone_version.py        # find_rclone()/rclone_version(): locates the rclone binary (system PATH, then rclone_api's cache) and reports its version; stdlib-only, so the standalone yd-version can use it
    ├── dataclient_utils.py      # Core logic for rclone-backed data client commands: resolve_remote_path(), upload_file/directory(), download_files(), delete_remote(), list_remote(), glob support
    ├── dataclient_wrapper.py    # @dataclient_wrapper decorator used by yd-upload/download/delete/ls (no SDK client needed)
    ├── follow_utils.py          # follow_ids(): subscribes to SSE event streams for WRs/WPs/CRs in daemon threads; auto-reconnects on drop
    ├── interactive.py           # confirmed() (respects --yes/YD_YES), select() (numbered list selection with range syntax e.g. 1,2,4-7)
    ├── start_hold_common.py     # Shared logic for yd-start and yd-hold: filter by status, confirm, apply action
    ├── compute_action_common.py # ComputeAction (COMPUTE_STOP/START/RESTART) and the shared logic for yd-compute-stop/start/restart: CR names/globs/IDs, node IDs, and instances in 'cr_id.instance_id' form
    ├── dryrun_utils.py          # report_dry_run(): lists what yd-cancel/yd-shutdown/yd-terminate would affect, as yd-list's table or as JSON, without acting
    ├── compact_json.py          # CompactJSONEncoder: small containers on one line, larger ones indented
    ├── check_imports.py         # Guards for optional imports (jsonnet, cloudwizard, commander) with install hints
    ├── user_agent.py            # set_user_agent(), called at wrapper.py import: CLI_USER_AGENT on direct calls, SDK_USER_AGENT on calls made through the SDK
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

`yd-commander` is the exception to all of this: it uses neither wrapper, loads no config at import, and never touches the SDK, because it runs the other commands as child processes. Its `main()` is in `commander/launcher.py` and stays free of Qt so that the missing-extra message works without PyQt6 installed. See [Commander](#commander).

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

### Commander

`yd-commander` is a PyQt6 desktop GUI over the CLI, in `yellowdog_cli/commander/`. It is not a second API client: **every action it takes runs a `yd-*` command as a child process** (`_run_command_in_subprocess`, via `QProcess`), so behaviour, output and configuration precedence are the CLI's. Nothing in the package imports the SDK or `wrapper.py`, and there is no `CLIENT`. `yellowdog_cli/commander/README.md` documents it for users; the notes here are the ones that matter when changing it.

- **PyQt6 is an optional extra** (`pip install "yellowdog-cli[commander]"`). `launcher.py` is deliberately free of Qt and of the heavy CLI imports, so `--help` and the missing-extra message (`check_commander_imports()`) work without it. Only after that guard does it import `commander.py` and call `run_app()`.
- **The layout lives in `commander.ui`**, loaded by `loadUi()` in `YellowDogApp.__init__`, which then connects signals to widgets by name. A renamed or deleted widget therefore fails at construction rather than at use — `tests/test_commander_ui_loads.py` is what catches that.
- **Bulk destructive actions enumerate before they act.** `_capture_dry_run_json/_summaries/_objects` run the same command with `-D --json` to list what would be affected, then `_confirm_destructive` (entities and objects) or `_choose_objects` (downloads) offers a tick-list, and only the chosen handles are passed back as explicit arguments. The shared primitives are `SelectableRow`, `entity_rows`/`object_rows`, `_build_selection_list_widget`, `checked_handles` and `update_selection_state`. If a seventh action needs them, move them out of `commander.py` into their own module.
- **The file dialogs are Qt's own, with a preview pane.** `_build_browse_dialog` (the directory buttons) and `_select_file` build a non-native `QFileDialog`, call `_add_preview_pane()` and run it through `_run_file_dialog()`; `_save_file` builds and runs one the same way but adds no pane, because it names a file that does not exist yet. The selectors accept with **Select** and the browsers with **Open**, which is the honest split: only a browser opens what it is given. The pane is a `FilePreview` added to the dialog's *own* splitter — that is what makes its width draggable, and `_remember_preview_width()` keeps that width on the window for the session. The preview exists because leaving the platform's file viewer behind also leaves Quick Look behind; it decides text-versus-binary by decoding the head of the file, never by extension (task output is named whatever the task named it), and it keeps the decoded `QImage` so a widened pane rescales from the original. `_thumbnail()` activates the layout before measuring, because a pane only just shown or resized has not had its layout event delivered yet. The pane's two heading lines are pinned to the top and to the height their text needs, with a **stretch-0** spacer below them: a label defaults to taking a share of the spare height and centring its text in it, and a directory — named and kinded, with no body to show — is nothing but spare height, so the two headings ended up a third and two thirds of the way down; a spacer with stretch 1 instead would be an equal claimant with whichever body is on show and halve it.
- **One method sets the file dialogs up, and Commander keeps their preferences.** `_apply_dialog_preferences()` sets the view mode (`DIALOG_VIEW_MODE`, `ViewMode.List` — names only, since Detail spends the width on size/kind/date and elides the name), the sidebar's width and the preview's, and connects `_remember_dialog_preferences()` to `finished`; all three dialogs call it once the pane (if any) is in place. The widths go in a single `setSizes`, stating every pane's but the listing's, and both of those matter because it runs on a dialog that has not been shown: the splitter reports placeholder sizes rather than the widths Qt restored, so a second call throws the first call's away, and a pane left out of the list is squashed to its minimum. That second trap was live for a while — every dialog carrying a preview showed a 90px `Co...` sidebar however wide Qt had it. The placeholders are also useless for measuring how much wider the dialog should be, so each pane says that for itself: the preview counts its whole width, being new, and the sidebar only what it gains over `sizeHint()`, capped at `SIDEBAR_PANE_WIDTH` because a sidebar dragged wider than that is a listing the user chose to shrink.
- **The dialog preferences are Commander's own** (`dialog_settings()`, under `COMMANDER_SETTINGS_ORGANISATION`), deliberately not the ones Qt keeps under `FileDialog/*`. Qt writes its own whenever one of these dialogs closes, so every machine that has ever opened one carries a value: a default applied only when 'nothing is remembered' was therefore a no-op everywhere but a brand-new profile — and worse, the value sitting there was the 90 left by the squash bug above. Commander's store has no such ambiguity, because only Commander writes it: a value present is a value the user was shown and left, absent means they have set nothing. `_remember_dialog_preferences()` writes on every close for that reason, defaults included. `dialog_settings()` is a function, not a constant, so `conftest`'s `commander_dialog_settings` can point it at an ini file of the test's own — otherwise every GUI test would read and overwrite the developer's real preferences. The preview pane's width stays session-only (`_preview_width`), which is the one dialog preference not in that store.
- **The browse dialog can hand over to the platform's file viewer.** `_add_platform_viewer_button()` puts an `ActionRole` button (`NATIVE_VIEWER_BUTTON_TEXT`, worded per platform) on the dialog's button box; `_switch_to_platform_viewer()` passes `dialog.directory()` — what is on screen, not what it opened at — to `_open_with_default_application()` and rejects the dialog, so `_run_file_dialog` reports no chosen file. It exists because the Qt dialog is read-only and deleting things in `results` needs the real file manager. Two details are load-bearing. `setAutoDefault(False)`: focused, an autoDefault button takes the default role from Accept, so Return would mean Finder rather than Open. And the button is moved to index 0 of the box's layout by hand, because each style appends an `ActionRole` button where it likes — macOS after Cancel, Fusion before Open — so left alone it moves about between platforms; it survives as a box member with its role, but a *style change* makes the box relayout from its own button list and undoes the move. The offscreen style used in the tests already puts it first, so `MacButtonLayout` (a `QProxyStyle` returning `MacLayout` for `SH_DialogButtonLayout`) is what makes the placement testable at all — without it the assertion passes whatever the code does.
- **`_notify()` is the modal notice**: it logs the message and then shows it, so the output window keeps the whole narrative either way, and it degrades to log-only when `--yes` is set (nobody is there to press OK) or while shutting down. `_build_notice_dialog()` is split out so a test can arm the real dialog rather than stub `exec()`, and it forces `PlainText` — a notice carries Windows paths and entity names, which as rich text lose their backslashes and their angle-bracketed parts. Only one caller so far, deliberately: View Results Directory with no results directory yet. The other dead-end notices remain log-only, and `tests/test_commander_notices.py` holds that line.
- **`Confirmation.__bool__` raises deliberately.** A confirmation carries both `proceed` and `handles`, and `if self._confirm_destructive(...)` — which is what the natural mistake looks like — would be true even for a refusal. Check `.proceed`.
- **Synchronous helpers block in nested event loops** (`_run_nested`), which keeps the window responsive while a child process runs. That makes re-entrancy possible, so the enumerating actions are guarded by `_operation_in_flight()` and a `_nested_depth` counter (a counter, not a flag: the config parse deferred with `singleShot(0)` runs inside the first loop to spin, so depth 2 is normal). A re-entrant enumeration returning `None` would read as "enumeration failed", which for a destructive action means falling back to the whole scope — hence refusing early.
- **Placeholders come from `yd-show`.** `_parse_yd_config()` runs it (via `_yd_show_command()`, the seam the tests override) to resolve the namespace and tag for the current config file. Every failure is reported through `_report_discovery_failure()` however quiet the parse was — a quiet parse suppresses the announcement, never the reason it failed — and a *timed-out* one is retried once, after a delay and with a longer budget, because the first `yd-*` of a session on Windows can need longer than the 10s budget to start and nothing else would try again before a restart. Wire new discovery callers through `_reparse_placeholders()`, which is the only thing that pairs a parse with the placeholders and with that retry; calling `_parse_yd_config()` directly is how three of the four callers silently had no retry. It is stubbed in the tests (see below), so nothing there spawns a CLI process for it.
- **A missing tag is not a path.** `_object_path()` returns `None` when the Path field is empty and no tag has been discovered, and the download and delete actions must refuse on it (`NO_OBJECT_PATH`). It used to interpolate the missing tag into the default `f"{tag}*"`, so a failed discovery handed `yd-download`/`yd-delete` the literal `None*` — and with confirmations suppressed, `yd-delete -Ry None*` would have run.
- `commander.py` carries `E402`/`RUF005` per-file ignores in `pyproject.toml`: it was lifted from the standalone `yellow-gui` demo repo, and those are pre-existing findings kept out of the relocation diff.

### Resource Specification Test Corpus

`tests/resources/` is the single source of resource specifications used by the resource-definition tests (`test_resource_specs.py`, `test_resource_property_coverage.py`, `test_system_resources.py`) — one Jsonnet file per resource type, each with a minimal variant (only required properties) and a maximal one (every settable property), loaded through the CLI's own loader rather than duplicated as separate fixtures. See `tests/resources/README.md` for the minimal/maximal convention and how to add a new resource type.

`tests/resource_models.py` is a write-side coverage gate: it introspects the SDK's own dataclasses for every model the corpus's resource types build (via `create.py`'s `_get_model_object`) and fails, naming the property, when a settable property is set by no specification at all. A property can only be excluded from the gate by a registry entry (`SERVER_ASSIGNED_COVERAGE`, `NOT_SETTABLE`, `NOT_TESTED`) carrying a stated reason — never inferred from the dataclass's own `field.init`, since the SDK structures an `init=False` field from a specification exactly like any other. A live read gate in `test_system_resources.py` then demands every property excluded as platform-assigned either actually come back from a real `yd-show` at least once, or carry a recorded reason why this suite cannot make it come back (most of the waived ones belong to a compute source that never provisions a real instance, so it has no status, no instance summary and no exhaustion to report); an exclusion the platform has started honouring is reported as stale, so a waiver cannot outlive its reason. Consequently, closing a coverage gap the SDK opens (a new property on an existing model) is an edit to one `.jsonnet` file, not to several JSON fixtures.

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

Constructing a `YellowDogApp` defers `_set_config_file` with `singleShot(0)`, and that runs `yd-show` in a child process inside whichever event loop spins first — usually a dialog's `exec()`. `conftest`'s autouse `_no_config_discovery` stubs `_parse_yd_config` for any test that uses `qapp`, since none of them are about discovery; the two that test the method itself carry `@pytest.mark.real_config_parse`. Left live it cost 235 CLI invocations and most of the GUI suite's runtime, made the tests depend on an installed `yd-show`, and let the environment's namespace and tag leak in.

Everything runs under `QT_QPA_PLATFORM=offscreen` with no display, so it works on a headless CI node. Nodes without a usable Qt skip: every Commander test module calls `tests/qt_guard.py`'s `require_qt()` before importing anything that pulls in Qt, and the `qapp` fixture guards again. That guard is deliberately not `pytest.importorskip` — from pytest 9.1 it skips only on `ModuleNotFoundError`, so PyQt6-installed-but-`libGL`-missing (a minimal Linux image) errored instead of skipping. Calling it before the imports is what the `E402` per-file ignores in `pyproject.toml` are for. Modal runs are watchdogged, because a dialog that never closes would hang CI rather than fail it. An autouse `conftest` fixture surfaces assertions raised inside Qt callbacks, which Qt would otherwise print and discard.

Note that `_build_destructive_dialog` returns a dialog whose buttons are *not* wired — `_confirm_destructive` attaches a `clicked` handler afterwards, because it needs to know which button was pressed. Drive it through `_confirm_destructive`, not from the builder. `_build_chooser_dialog` wires its own box and can be driven directly.

### Dependencies

- `yellowdog-sdk` — YellowDog platform API client
- `rich` (pinned 13.9.4) — terminal output formatting
- `tomli` — TOML parsing
- `python-dotenv` — `.env` file support
- `pypac` — proxy auto-configuration
- `jsonnet` — optional, for Jsonnet spec templating
- `PyQt6` — optional (the `commander` extra), for the `yd-commander` GUI; on a minimal Linux image it also needs Qt's runtime libraries, which `setup-ubuntu.sh` installs
- `rclone_api` — Python wrapper around the rclone binary; used by data client commands
- Cloud wizard extras: `boto3`, `google-cloud-*`, `azure-*`

## Keeping the Ancillary Files in Step

Documentation here is spread across several files, each with its own audience, and a change that lands in the code but not in them leaves the repo describing something it no longer is. **Before finishing any change, go through this list and update what the change has made wrong or incomplete.** Most changes touch one or two of these; some touch none. Say which ones you updated, or that none needed it.

| File | Update it when |
|---|---|
| `README.md` | User-visible CLI behaviour changes: a new command, flag, property, or a change in what one does. Run `make toc` afterwards — never hand-edit the table of contents |
| `README_CLOUDWIZARD.md` | Cloud Wizard behaviour changes (`make toc_cloudwizard` for its TOC) |
| `PYPI_README.md` | The command list or the headline description changes — it is the PyPI landing page, so it summarises rather than documents |
| `yellowdog_cli/commander/README.md` | Commander's GUI behaviour changes: a new button, dialog, or a change in what an action does |
| `DEVELOPMENT.md` | Anything a developer runs or needs installed changes: make targets, prerequisites, the venv or extras, `setup-ubuntu.sh`, the project layout |
| `tests/README.md` | Test files are added, renamed or removed, or a category, flag, marker or shared fixture changes |
| `CLAUDE.md` (this file) | A new module, pattern or convention arrives, or an existing one is described here and changes |
| `config-template.toml` | A new or changed TOML configuration property — it is the annotated reference for all of them |
| `pyproject.toml` | A new entry point, extra, or package-data file (`include-package-data` is `false`, so an unlisted asset ships broken) |
| `RELEASING.md` | The release process, branch model or PyPI arrangements change |

Two traps worth naming, both of which have bitten:

- A **new test file is invisible** unless it is added to `tests/README.md` — nothing fails, the table just quietly stops being a list of the tests.
- **Docs that describe a mechanism drift silently.** If a paragraph names a function, flag, package or file, check that it still exists and still behaves that way, rather than assuming the prose is fine because the code compiles.