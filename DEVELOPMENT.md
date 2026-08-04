# Development Guide

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) — install via `brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`; on Windows use `winget install --id=astral-sh.uv` or `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- `git`
- `make` — for formatting, building, and other development tasks
- `bash` — required to run the release script (see [`RELEASING.md`](RELEASING.md))

## Getting Started

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

Unit tests require no credentials and no network access:

```shell
pytest -v
```

See [`tests/README.md`](tests/README.md) for the full test matrix — including dry-run, system, compute, and demo test categories, credentials setup, and parallel execution options.

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

## Type Checking

Static type checking is done with [pyright](https://github.com/microsoft/pyright) in basic mode:

```shell
make pyright
```

Pyright is configured in `pyproject.toml` under `[tool.pyright]`. It uses the active Python environment automatically — no extra setup is needed beyond the normal `uv pip install -e ".[dev,...]"` step.

The codebase targets zero pyright errors. Where the SDK's type stubs are overly pessimistic (e.g. attributes typed `str | None` that are never `None` after an API call), or where CLI code accesses attributes defined on a concrete SDK subclass but not on its abstract base type (e.g. `sources` on `ComputeRequirementStaticTemplate`, provider-specific image properties on `ComputeSource` subclasses), the relevant lines carry a `# type: ignore[...]` comment with a specific error code.

## Building

```shell
make build        # builds the distribution into dist/
make pypi_check   # checks the distribution with twine
```

## Project Structure

```
yellowdog_cli/          # One module per yd-* command
yellowdog_cli/utils/    # Shared utilities (config, variables, printing, SDK wrappers, etc.)
tests/                  # All tests (see tests/README.md)
pyproject.toml          # Package metadata, dependencies, ruff config
uv.lock                 # Locked dependency versions for reproducible installs
Makefile                # format, build, install, update, toc, pypi, pyright targets
config-template.toml    # Annotated template for all TOML configuration properties
RELEASING.md            # Branch model, release process, PyPI credentials
```

For a detailed description of the architecture and coding conventions, see [`CLAUDE.md`](CLAUDE.md).

## Branching

| Branch         | Purpose                                                            |
|----------------|--------------------------------------------------------------------|
| `main`         | Current released version — always matches PyPI                     |
| `next-version` | Ongoing development                                                |
| `feature/*`    | Larger features; branch from `next-version`, merge back when ready |

Day-to-day work goes on `next-version`. See [`RELEASING.md`](RELEASING.md) for the full release process.
