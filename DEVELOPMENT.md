# Development Guide

<!--ts-->
   * [Prerequisites](#prerequisites)
   * [Getting Started](#getting-started)
   * [Code Formatting](#code-formatting)
      * [Pre-commit Hook](#pre-commit-hook)
      * [Pre-push Hook](#pre-push-hook)
   * [Testing](#testing)
      * [Coverage](#coverage)
      * [Complexity](#complexity)
      * [Commander GUI Tests](#commander-gui-tests)
      * [Testing Across Python Versions](#testing-across-python-versions)
         * [Python Pre-Releases](#python-pre-releases)
   * [Type Checking](#type-checking)
   * [Building](#building)
   * [Commander](#commander)
   * [MCP Server](#mcp-server)
   * [Architecture](#architecture)
      * [One set of commands, three front ends](#one-set-of-commands-three-front-ends)
      * [The life of a command](#the-life-of-a-command)
      * [The command registry](#the-command-registry)
      * [Laziness: importing does nothing](#laziness-importing-does-nothing)
      * [Passing context rather than reading globals](#passing-context-rather-than-reading-globals)
      * [Thin commands over libraries](#thin-commands-over-libraries)
      * [From specification to Platform object](#from-specification-to-platform-object)
      * [Output and failure](#output-and-failure)
      * [Rules held by tests](#rules-held-by-tests)
   * [Project Structure](#project-structure)
   * [Branching](#branching)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Fri Oct  9 16:28:00 BST 2026 -->

<!--te-->

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) — install via `brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`; on Windows use `winget install --id=astral-sh.uv` or `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- `git`
- `make` — for formatting, building, and other development tasks
- `bash` — required to run the release script (see [`RELEASING.md`](RELEASING.md))
- On a minimal Linux image, `libatomic` — needed only by `make pyright` (see [Type Checking](#type-checking)); `libatomic1` on Debian/Ubuntu, `libatomic` on the RHEL family
- On a minimal Linux image, Qt's runtime libraries — needed only to run [Commander](#commander) or its tests (see [Commander GUI Tests](#commander-gui-tests)); on Debian/Ubuntu, `libgl1` is the one PyQt6 asks for first
- On macOS, `coreutils` — provides `timeout`, which the demo tests put every `yd-*` command under; `brew install coreutils`. Standard on Linux, so nothing to install there, and needed only by `pytest --run-demos`

## Getting Started

On an unconfigured Ubuntu or Debian machine, [`setup-ubuntu.sh`](setup-ubuntu.sh) does everything below — system packages, uv, Python, the clone, the install — and then runs the suite. Nothing needs to be in place but `curl`:

```shell
curl -LsSf https://raw.githubusercontent.com/yellowdog/yellowdog-cli/next-version/setup-ubuntu.sh | bash
```

That clones into `./yellowdog-cli`; add `-s --` to pass options, e.g. `| bash -s -- --dir ~/src/yellowdog-cli --no-test`. Run from inside an existing checkout (`./setup-ubuntu.sh`) it uses that checkout as it stands and clones nothing — it never fetches, switches branches or pulls. It is idempotent, and installs nothing outside apt, uv's own `~/.local` downloads, and the checkout's `.venv`. `--help` lists the options.

Elsewhere, or to do it by hand:

```shell
git clone https://github.com/yellowdog/yellowdog-cli
cd yellowdog-cli
git checkout next-version

# Create and activate a virtual environment (Python 3.10+ required; uv will download it if not available)
uv venv --python 3.14
source .venv/bin/activate      # macOS/Linux
# .venv\Scripts\activate       # Windows

# Install in editable mode with all dev dependencies
uv pip install -e ".[dev,jsonnet,cloudwizard,commander,mcp]"
```

This installs the package in editable mode, making all `yd-*` commands available in your environment and reflecting any local code changes immediately. You may need to re-source the venv to access the commands immediately.

PyCharm supports uv natively — point it at the `.venv` created above via `Settings → Project → Python Interpreter`.

To update all dependencies to their latest versions:

```shell
make update
```

## Code Formatting

All formatting is handled by [ruff](https://docs.astral.sh/ruff/):

```shell
make format
```

This runs `ruff check --fix` (import sorting, pyupgrade, unused imports) followed by `ruff format` (Black-compatible formatting). Always run before committing. Ruff is configured in `pyproject.toml` under `[tool.ruff]`.

### Pre-commit Hook

A pre-commit hook is configured in `.pre-commit-config.yaml` to run ruff automatically on `git commit`. To activate it:

```shell
pre-commit install
```

This ensures formatting is always applied before a commit reaches the repository. To run it manually across all files:

```shell
pre-commit run --all-files
```

### Pre-push Hook

`main` requires signed commits. Its GitHub ruleset lets an account with bypass rights push unsigned ones, with only a warning once the push has happened, so `scripts/pre-push` refuses a push that would add an unsigned (or badly signed) commit to `main` before it leaves. Pushes to other branches are not checked. To install it as this clone's pre-push hook:

```shell
make pre_push_hook
```

`git push --no-verify` skips it. `scripts/unsigned_commits.sh <range>` lists a range's unsigned commits, and `release.sh` runs it before it merges anything. Rewriting history with `git filter-branch` or `git filter-repo` drops signatures; `git rebase` re-signs under `commit.gpgsign`.

## Testing

Unit tests require no credentials, no configuration file and no network access:

```shell
pytest -v
```

`conftest.py` loads the configuration as the test run starts (as importing a yd-* command module once did), so without a key and secret the run would stop before collection. Where no usable configuration is found, `conftest.py` substitutes a dummy key and secret and says so in the pytest header. A working configuration is never overridden — an environment variable outranks both `config.toml` and `.env`, so a dummy set over a real credential would shadow it — and nothing is substituted for `--run-system`, `--run-system-compute` or `--run-demos`, which need genuine credentials.

See [`tests/README.md`](tests/README.md) for the full test matrix — including dry-run, system, compute, and demo test categories, credentials setup, and parallel execution options.

### Coverage

Line and branch coverage of the unit tests, from `pytest-cov` (in the `dev` extra):

```bash
make coverage
```

It prints a summary per file, leaving out those fully covered, and writes the detail, line by line and branch by branch, to `htmlcov/index.html`. Its settings are in `pyproject.toml` under `[tool.coverage.*]`. Only code run inside the pytest process is counted: what a test runs in a subprocess (`yd-schema`'s command-line tests, the Commander stderr filter, the fresh-interpreter import checks, the demo dry runs) shows as uncovered though it is tested. Use it to find untested paths, failure branches above all, rather than as a target to reach.

### Complexity

A report of the package's code complexity:

```bash
make complexity
make complexity ARGS="--threshold 20 --top 20"   # what it lists: complexity over 20, and 20 of each
```

It lists the functions whose McCabe complexity is over the threshold (15 by default), worst first; counts the functions ruff finds with too many branches, statements, returns or arguments; and gives the median and 90th-percentile function length with the longest functions. It is a report, never a failure: the checks it runs are enabled for it alone, not in `pyproject.toml`'s ruff configuration, so `make format` and the pre-commit hook are unaffected. The script is `scripts/complexity_report.py`.

### Commander GUI Tests

Around 290 of the unit tests exercise the Commander GUI. They run offscreen with no display, so a headless node is fine, but they do need PyQt6 (the `commander` extra) and the Qt runtime libraries it links against. Where either is missing, those test modules skip and the rest of the suite runs normally — installing them is only necessary to test Commander itself.

On a minimal Linux image the libraries are the part that is usually absent, and the skip message names the missing one, e.g. `Qt is unavailable, so Commander cannot be tested here: libGL.so.1: cannot open shared object file`. They are dependencies of Qt itself rather than of the display, so offscreen needs them too — text is still laid out, just never shown. On a fresh Ubuntu node the following was enough to run the whole suite:

```shell
sudo apt-get install -y libgl1 libegl1 libxkbcommon0 libdbus-1-3 libfontconfig1
```

Each library surfaces separately as the previous one is satisfied, so install them together rather than chasing them one message at a time. If a run names something not listed here, the package is usually the library's name with the version suffix moved to the end (`libxkbcommon.so.0` → `libxkbcommon0`).

### Testing Across Python Versions

To run the unit tests against all supported Python versions (3.10–3.14), use [tox](https://tox.wiki/) via:

```shell
make tox
```

tox is configured in `pyproject.toml` under `[tool.tox]` and uses `tox-uv` as its backend. uv will automatically download any Python version that isn't already installed — no manual setup required, and this works consistently on macOS, Linux, and Windows. Each environment installs every extra (`dev`, `commander`, `mcp`, `jsonnet` and `cloudwizard`), so no test skips for want of one, and runs pytest with eight [pytest-xdist](https://pytest-xdist.readthedocs.io/) workers (`-n 8`, as `make test` does); the environments themselves run one after another.

To target a specific version or subset:

```shell
tox -e py310            # single version
tox -e py310,py314      # just the bounds
```

To pass extra pytest arguments (e.g. to run demos or system tests), call `tox` directly using `--` as a separator — `make tox` cannot forward arguments this way. A `-n` given there overrides the default of eight workers, and `-n 0` runs without xdist:

```shell
tox -- --run-demos
tox -- --run-system --run-demos
tox -e py310,py314 -- --run-demos tests/test_demos.py -n 12
```

#### Python Pre-Releases

Python 3.15 has a `py315` environment, deliberately kept out of `env_list` so that `make tox` neither runs it nor is broken by it; `tox list` shows it under *additional environments*, and it is run explicitly:

```shell
tox -e py315
```

The interpreter itself is no obstacle — uv downloads pre-release CPython like any other version — but as of October 2026 (3.15.0rc3) the environment cannot be created, because `pre-commit`, in the `dev` extra, requires `pyyaml`, which publishes no cp315 wheel and whose source build fails under 3.15 in Cython. The runtime extras all install, `rclone-api`'s `psycopg2-binary` (a blocker in August) included, but PyQt6 6.11 crashes the interpreter as `PyQt6.QtCore` is imported, in `PyQt6-sip`'s `createContainerType`, so Commander cannot run on 3.15 yet. Use rc3 or later: on 3.15.0a8, `anyio`, which the `mcp` extra pulls in, fails as pytest loads its plugin, needing the builtin `sentinel` that later pre-releases provide.

Until then, the rest of the suite can be run in a throwaway venv without `pre-commit` and PyQt6, the Commander tests skipping as Qt is missing; in October 2026 it passed there:

```shell
uv venv --python cpython-3.15.0rc3 /tmp/py315  # or a later 3.15 release; a bare 3.15 takes whichever is installed
VIRTUAL_ENV=/tmp/py315 uv pip install -e ".[mcp,jsonnet,cloudwizard]" pytest pytest-xdist cli-test-helpers python-dispatch
/tmp/py315/bin/python -m pytest -n 8
```

Once `pyyaml` and PyQt6 work on 3.15, `tox -e py315` should pass, at which point `py315` belongs in `env_list` and `3.15` in the classifiers in `pyproject.toml`.

## Type Checking

Static type checking is done with [pyright](https://github.com/microsoft/pyright) in basic mode:

```shell
make pyright
```

Pyright is configured in `pyproject.toml` under `[tool.pyright]`. It uses the active Python environment automatically, so no Python-side setup is needed beyond the normal `uv pip install -e ".[dev,...]"` step.

Pyright itself runs on Node, though, and that is the one place a bare Linux node can trip. `pyright-python` prefers a `node` already on `PATH` and otherwise downloads its own into `~/.cache/pyright-python/`; that prebuilt binary is dynamically linked against libatomic, which minimal images often omit. The failure is `node: error while loading shared libraries: libatomic.so.1` and `make: *** [pyright] Error 127`. Install `libatomic1` on Debian/Ubuntu or `libatomic` on the RHEL family; installing a distro `nodejs` also works, since pyright then prefers it, but that package depends on libatomic anyway. Nothing else in the toolchain needs Node — `pytest` and `make format` are unaffected.

The codebase targets zero pyright errors. Where the SDK's type stubs are overly pessimistic (e.g. attributes typed `str | None` that are never `None` after an API call), or where CLI code accesses attributes defined on a concrete SDK subclass but not on its abstract base type (e.g. `sources` on `ComputeRequirementStaticTemplate`, provider-specific image properties on `ComputeSource` subclasses), the relevant lines carry a `# type: ignore[...]` comment with a specific error code.

## Building

```shell
make build        # builds the distribution into dist/
make pypi_check   # checks the distribution with twine
```

The specification schemas' property descriptions are extracted from the Work Requirement Property Dictionary (`docs/property-dictionary.md`) into `yellowdog_cli/spec_data/descriptions.json`, which ships with the package. Regenerate it after editing the dictionary, as the `toc` targets regenerate the tables of contents; `tests/test_spec_properties.py` fails while the shipped file is stale:

```shell
make schema_descriptions
```

## Commander

`yd-commander` is a PyQt6 desktop GUI over the CLI, in `yellowdog_cli/commander/`. [`yellowdog_cli/commander/README.md`](yellowdog_cli/commander/README.md) documents it for users, and [`CLAUDE.md`](CLAUDE.md) describes how it is put together; what follows is what you need in order to work on it.

```shell
yd-commander                        # or: python -m yellowdog_cli.commander
yd-commander config.toml            # pre-select a configuration file
yd-commander -y                     # skip the destructive-action confirmations
```

PyQt6 is the optional `commander` extra, installed by the `uv pip install` line in [Getting Started](#getting-started). Without it, `yd-commander` exits with an instruction to install it rather than a traceback, and the GUI tests skip (see [Commander GUI Tests](#commander-gui-tests)).

The GUI holds no API client and imports neither the SDK nor `utils/wrapper.py`: every action runs a `yd-*` command as a child process. Two consequences worth keeping in mind when changing a command:

- Its behaviour, output and configuration precedence are the CLI's, so a fix to a command reaches the GUI for free.
- The selection dialogs are built by parsing `-D --json` output from `yd-cancel`, `yd-shutdown`, `yd-terminate`, `yd-download` and `yd-delete` (`parse_entity_summaries`, `parse_object_summaries`, and `parse_download_summaries` for `yd-download`'s per-file records). Changing the shape of that JSON will change what the GUI offers to act on, and the tests for those parsers are where that will show up.

The window layout is `commander.ui`, Qt Designer XML. Edit it in Designer if you have Qt's tools installed, otherwise the XML directly; either way keep widget names in step with the code, since `loadUi()` binds them by name and `YellowDogApp.__init__` connects signals to them — a renamed widget fails at construction, which `tests/test_commander_ui_loads.py` exists to catch.

Assets ship through `[tool.setuptools.package-data]` in `pyproject.toml`, which lists `*.ui` and `images/*`; `include-package-data` is `false`, so anything new has to be added there or it will be missing from the wheel while still working from a checkout. `screenshots/` is for the README and is deliberately not shipped.

## MCP Server

`yd-mcp` is an MCP server over the CLI, in `yellowdog_cli/mcp/`. [`yellowdog_cli/mcp/README.md`](yellowdog_cli/mcp/README.md) documents it for users, and [`CLAUDE.md`](CLAUDE.md) describes how it is put together.

```shell
yd-mcp config.toml                  # or: python -m yellowdog_cli.mcp config.toml
```

The `mcp` extra (`mcp>=2.2`) is installed by the `uv pip install` line in [Getting Started](#getting-started). Without it, `yd-mcp` exits with an instruction to install it rather than a traceback, and `tests/test_mcp_server.py`, the one test module that needs the extra, skips (`tests/mcp_guard.py`'s `require_mcp()`); the other three MCP test modules need neither the extra nor the SDK.

Like Commander, the server holds no API client and runs every tool call as a `yd-*` command in a child process, under its own interpreter (`python -m yellowdog_cli.<command>`) rather than the console scripts, so a fix to a command reaches it for free.

## Architecture

This section is the big picture: how the pieces fit together and why they are shaped as they are. [`CLAUDE.md`](CLAUDE.md) and the subsystem notes in `.claude/rules/` hold the detail, including the rules that are easy to break.

### One set of commands, three front ends

Everything the CLI does is done by a `yd-*` command, one module per command in `yellowdog_cli/`. The terminal is one way to run them; the other two front ends run them too, as child processes, rather than holding API clients of their own:

```
  terminal ──────────────┐
  yd-commander (PyQt6) ──┼──>  yd-* command  ──>  YellowDog SDK  ──>  Platform API
  yd-mcp (MCP server) ───┘          │
                                    └──────────>  rclone  ──>  object storage
```

Commander starts a command for each button, and the MCP server one for each tool call, both under their own interpreter (`python -m yellowdog_cli.<command>`) and reading what it prints, the MCP server always through `--json`. Neither imports the SDK. The consequence is that a command's behaviour, configuration precedence, output and exit codes exist in exactly one place, and a fix to a command reaches all three front ends without further work. The price is that the commands' machine-readable output is an interface: changing the shape of a `--json` record changes what Commander offers to act on and what an MCP client sees.

### The life of a command

A command's `main()` is decorated by a wrapper (`utils/wrapper.py`'s `@main_wrapper` for commands that talk to the Platform, `utils/dataclient/wrapper.py`'s `@dataclient_wrapper` for those that only move files), and both wrappers hand the run to `utils/command_runner.py`, so a command is run the same way whichever kind it is:

1. **Prepare** (`prepare_run()`). The command line is parsed, the configuration is loaded from the command line, the environment and `config.toml`, the output settings are configured, and the command's configuration sections are built. This all happens before the command starts and outside its error handling, so a bad argument exits 2 and a broken configuration exits 3, with nothing on stdout.
2. **Run.** `main()` is called with a context (`utils/context.py`): a `RunContext` holding the parsed arguments, the configuration and the API client, or a `DataClientContext` holding the arguments alone. The client itself is built only when the command first uses it.
3. **Report.** With `--json`, the outcomes the command recorded (`utils/results.py`) are printed as one JSON document, even when the command failed part-way, so a script still learns what was done.
4. **Exit.** Whatever escaped `main()` is classified (`utils/exit_codes.py`'s `classify()`) into an exit code saying what kind of failure it was: not found, not authorised, a connection failure, a server error, and so on.

A handful of commands sit outside this. `yd-help`, `yd-version`, `yd-format-json` and `yd-jsonnet2json` need neither credentials nor configuration and have a plain `main()`. `yd-doctor` and `yd-schema` build their own run, because `yd-doctor` exists to diagnose exactly the missing or broken configuration that would stop a wrapper before `main()`.

### The command registry

Every command and every option is declared once, as data, in `utils/command_registry.py`. The registry is the source for argparse (`CLIParser` in `utils/args.py` builds each command's parser from it), for `yd-help`'s listing, for the MCP server's tool catalogue and its JSON Schemas, and for the tests that hold the Command List (`docs/commands.md`) and `pyproject.toml`'s entry points to the commands that exist. A command declares its kind there: `API` (gets the full set of common options, including the credentials), `DATA_CLIENT` (no `--key`, `--secret`, `--url` or `--pac`, since it never contacts the Platform) or `STANDALONE`. Adding an option is therefore an edit to the registry, after which the parser, the help, the MCP tool and the checks all follow.

### Laziness: importing does nothing

Importing any module in the package parses no command line, reads no file, builds no client, prints nothing and exits nowhere. The values that once came into being on import — the parsed arguments, the configuration, the client, each command's configuration sections — are stand-ins from `utils/lazy.py`, built on first use, and the wrappers build the ones a command needs in `prepare_run()`. Two things follow. Tests can import any module freely and set up what they need. And commands that have no use for the SDK — the data client commands and `yd-variables` — start without importing it at all, which saves most of a command's start-up time; the modules every command imports keep their SDK imports inside the functions that use them, and a test fails if one of those commands ever loads it.

### Passing context rather than reading globals

Code that needs the command line, the configuration or the client takes the context as its first parameter and passes it on, library code included, rather than reading module globals. How output looks and how the CLI asks questions (`--quiet`, `--json`, `--debug`, `--yes` and the rest) is the one exception: it is read from a single settings object, `OUTPUT` in `utils/output_settings.py`, configured as the command starts, which the printing, table, prompting and results modules consult. No library reads the parsed command line directly.

### Thin commands over libraries

Command modules are mostly thin: the work lives in libraries under `utils/`, which are shared between commands and with the Cloud Wizard, and never import a command module. The larger ones, roughly in the order a newcomer meets them:

- **Finding things** (`entity_utils.py`): cached lookups of Platform entities by name, ID or glob, scoped to namespaces.
- **Acting on things** (`action_runner.py`): the shared resolve, confirm, act and record sequence behind the sixteen action commands (`yd-cancel`, `yd-shutdown`, the `yd-compute-*` commands and the rest).
- **Resources** (`load_resources.py`, `resource_creation.py`, `resource_removal.py`): `yd-create` and `yd-remove` as libraries, reading resource specifications, ordering them by dependency, and creating, updating or removing them.
- **Submitting work** (`submit.py` with `task_groups.py`, `task_generation.py`, `task_batches.py` and `property_cascade.py`): one pipeline for both creating a Work Requirement and adding to an existing one, building Task Groups and then Tasks in batches, with each Task inheriting properties from its Task Group and the Work Requirement.
- **Provisioning** (`provision_utils.py`): what `yd-provision` (Worker Pools) and `yd-instantiate` (Compute Requirements) share, such as User Data and template lookup.
- **Following** (`follow_utils.py`, `event_printing.py`): the Platform's event streams, with reconnection, for `--follow`, `yd-follow` and `yd-wait`.
- **Moving data** (`dataclient/`): the data client commands' layer over rclone, which imports no SDK.

### From specification to Platform object

Most of what users write is specifications: Work Requirements, Worker Pools, Compute Requirements, resources and Node Actions, as TOML, JSON or Jsonnet. Each passes through the same stages. It is loaded (`utils/specs/loading.py`, or `load_resources.py` for `yd-create` and `yd-remove`), with Jsonnet converted to JSON first; its `{{variables}}` are substituted (`variable_substitution.py`, with CSV expansion in `csv_data.py`), from the configuration, the environment, the command line and the CLI's own defaults; it is checked against a JSON Schema (`utils/specs/`), built at run time from the CLI's own property registry and from the installed SDK's model classes, so a newer SDK is described as soon as it is installed; and it is turned into the SDK's model objects and sent to the Platform. Properties the CLI defines itself, such as the Work Requirement properties settable at several levels, are recorded as data in `utils/specs/properties.py`, and their descriptions come from the Work Requirement Property Dictionary in `docs/`, so the user documentation is their single source.

### Output and failure

Human-readable output goes through `printing.py`, never `print()`, and tables through `tables.py`. With `--json`, those messages are silenced and the command's result is the recorded outcomes instead, so every site that reports an outcome also records it. Failures are classified rather than merely reported: an error re-raised with a clearer message is raised `from` the original so that its exit code survives, and an action command that stops on an authentication or connection failure records what it did and did not attempt before exiting with that failure's code.

### Rules held by tests

Many of the conventions above are enforced by the test suite rather than left to review: that importing any module has no side effects, that the SDK-free commands never load the SDK, that the registry matches the entry points and the README, that every option is either an MCP tool parameter or deliberately excluded, that every broad exception handler routes or re-raises authentication and connection failures, that every text file is opened as UTF-8, and that each command's option shapes match a recorded snapshot. When one of these tests fails after a change, it is usually pointing at the rule rather than at a fault in the test; [`tests/README.md`](tests/README.md) lists them.

## Project Structure

```
yellowdog_cli/            # One module per yd-* command
yellowdog_cli/utils/      # Shared utilities (config, variables, printing, SDK wrappers, etc.)
yellowdog_cli/utils/cloudwizard/  # The Cloud Wizard's provider support (the cloudwizard extra)
yellowdog_cli/utils/dataclient/   # The data client commands' layer over rclone
yellowdog_cli/utils/specs/        # Specification properties, schemas, validation and loading
yellowdog_cli/commander/  # yd-commander: the PyQt6 GUI, its .ui layout, images, and user README
yellowdog_cli/mcp/        # yd-mcp: the MCP server over the yd-* commands, and its user README
yellowdog_cli/spec_data/  # Data shipped for the specification schemas (descriptions.json)
docs/                    # The user documentation, by topic, that README.md points to: commands.md (the Command List), configuration, variables, work requirements, worker pools, resources, ...
scripts/                  # Build-time helpers run by make targets; the pre-push hook and its signed-commit check
tests/                    # All tests (see tests/README.md)
pyproject.toml            # Package metadata, dependencies, ruff config
CHANGELOG.md              # the release notes: each release's user-visible changes, and those not yet released under '## Unreleased'
Makefile                  # format, test, coverage, complexity, pyright, tox, build, install, uninstall, update, clean, pre_push_hook, toc and toc_* targets, schema_descriptions, pypi_check/pypi_upload/pypi_test_upload
setup-ubuntu.sh           # Bare Ubuntu/Debian machine -> a checkout that runs the tests
config-template.toml      # Annotated template for all TOML configuration properties
RELEASING.md              # Branch model, release process, PyPI credentials
```

For the architecture in outline, see [Architecture](#architecture); for the detail and the coding conventions, see [`CLAUDE.md`](CLAUDE.md).

## Branching

| Branch         | Purpose                                                            |
|----------------|--------------------------------------------------------------------|
| `main`         | Current released version — always matches PyPI                     |
| `next-version` | Ongoing development                                                |
| `feature/*`    | Larger features; branch from `next-version`, merge back when ready |

Day-to-day work goes on `next-version`. See [`RELEASING.md`](RELEASING.md) for the full release process.
