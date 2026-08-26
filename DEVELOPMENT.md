# Development Guide

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) — install via `brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`; on Windows use `winget install --id=astral-sh.uv` or `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- `git`
- `make` — for formatting, building, and other development tasks
- `bash` — required to run the release script (see [`RELEASING.md`](RELEASING.md))
- On a minimal Linux image, `libatomic` — needed only by `make pyright` (see [Type Checking](#type-checking)); `libatomic1` on Debian/Ubuntu, `libatomic` on the RHEL family
- On a minimal Linux image, Qt's runtime libraries — needed only to run [Commander](#commander) or its tests (see [Commander GUI Tests](#commander-gui-tests)); on Debian/Ubuntu, `libgl1` is the one PyQt6 asks for first

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
uv pip install -e ".[dev,jsonnet,cloudwizard,commander]"
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

## Testing

Unit tests require no credentials, no configuration file and no network access:

```shell
pytest -v
```

A yd-* command module loads its configuration when it is imported, so without a key and secret the test run used to stop during collection. Where no usable configuration is found, `conftest.py` substitutes a dummy key and secret and says so in the pytest header. A working configuration is never overridden — an environment variable outranks both `config.toml` and `.env`, so a dummy set over a real credential would shadow it — and nothing is substituted for `--run-system`, `--run-system-compute` or `--run-demos`, which need genuine credentials.

See [`tests/README.md`](tests/README.md) for the full test matrix — including dry-run, system, compute, and demo test categories, credentials setup, and parallel execution options.

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

tox is configured in `pyproject.toml` under `[tool.tox]` and uses `tox-uv` as its backend. uv will automatically download any Python version that isn't already installed — no manual setup required, and this works consistently on macOS, Linux, and Windows.

To target a specific version or subset:

```shell
tox -e py310            # single version
tox -e py310,py314      # just the bounds
```

To pass extra pytest arguments (e.g. to run demos or system tests), call `tox` directly using `--` as a separator — `make tox` cannot forward arguments this way:

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

The interpreter itself is no obstacle — uv downloads pre-release CPython like any other version — but as of August 2026 the environment cannot be created, because two dependencies publish no cp315 wheel. `rclone-api` requires `psycopg2-binary`, so uv falls back to building it from source and fails on the missing `pg_config`; and `PyQt6_sip`, pulled in by the `commander` extra, is missing a wheel too. Once both ship for cp315, `tox -e py315` should pass, at which point `py315` belongs in `env_list` and `3.15` in the classifiers in `pyproject.toml`.

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
- The selection dialogs are built by parsing `-D --json` output from `yd-cancel`, `yd-shutdown`, `yd-terminate`, `yd-download` and `yd-delete` (`parse_entity_summaries` and `parse_object_summaries`). Changing the shape of that JSON will change what the GUI offers to act on, and the tests for those parsers are where that will show up.

The window layout is `commander.ui`, Qt Designer XML. Edit it in Designer if you have Qt's tools installed, otherwise the XML directly; either way keep widget names in step with the code, since `loadUi()` binds them by name and `YellowDogApp.__init__` connects signals to them — a renamed widget fails at construction, which `tests/test_commander_ui_loads.py` exists to catch.

Assets ship through `[tool.setuptools.package-data]` in `pyproject.toml`, which lists `*.ui` and `images/*`; `include-package-data` is `false`, so anything new has to be added there or it will be missing from the wheel while still working from a checkout. `screenshots/` is for the README and is deliberately not shipped.

## Project Structure

```
yellowdog_cli/            # One module per yd-* command
yellowdog_cli/utils/      # Shared utilities (config, variables, printing, SDK wrappers, etc.)
yellowdog_cli/commander/  # yd-commander: the PyQt6 GUI, its .ui layout, images, and user README
tests/                    # All tests (see tests/README.md)
pyproject.toml            # Package metadata, dependencies, ruff config
uv.lock                   # Locked dependency versions for reproducible installs
Makefile                  # format, build, install, update, toc, pypi, pyright targets
setup-ubuntu.sh           # Bare Ubuntu/Debian machine -> a checkout that runs the tests
config-template.toml      # Annotated template for all TOML configuration properties
RELEASING.md              # Branch model, release process, PyPI credentials
```

For a detailed description of the architecture and coding conventions, see [`CLAUDE.md`](CLAUDE.md).

## Branching

| Branch         | Purpose                                                            |
|----------------|--------------------------------------------------------------------|
| `main`         | Current released version — always matches PyPI                     |
| `next-version` | Ongoing development                                                |
| `feature/*`    | Larger features; branch from `next-version`, merge back when ready |

Day-to-day work goes on `next-version`. See [`RELEASING.md`](RELEASING.md) for the full release process.
