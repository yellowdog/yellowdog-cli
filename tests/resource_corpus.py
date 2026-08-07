"""
Loading the resource specification corpus in-process, without a platform.

The CLI's loader reads its file list from ARGS_PARSER, so load_corpus_file sets that
rather than passing a path: going through the real entry point is the point, since it
brings Jsonnet expansion, variable substitution and dependency re-sequencing with it.
"""

import os
from pathlib import Path

import pytest
import tomllib

from yellowdog_cli.utils.load_resources import RESOURCE_SOURCE_DIR

CORPUS_DIR = Path(__file__).parent / "resources"
TEST_CONFIG = CORPUS_DIR / "test-config.toml"

# Keys the loader stamps onto a resource that are not properties of it.
# RESOURCE_SOURCE_DIR is imported from the loader rather than spelled '_sourceDir'
# here, so a rename in load_resources.py cannot leave this set (or
# resource_models.build_models(), which imports the same constant) quietly
# comparing a bookkeeping key against a model that has no such field.
META_KEYS = {"resource", RESOURCE_SOURCE_DIR}


def require_jsonnet() -> None:
    """
    Skip the calling module unless the optional 'jsonnet' extra is installed. Uses
    the CLI's own guard, so the skip reason carries its installation hint.
    """
    from yellowdog_cli.utils.check_imports import check_jsonnet_import

    try:
        check_jsonnet_import()
    except ImportError as exc:
        pytest.skip(str(exc), allow_module_level=True)


def dummy_variables() -> dict[str, str]:
    """
    The [common.variables] table from the test config, plus namespace, tag and a
    'run_id' of 'offline'.

    The 'run_id' default is the reason resource_live.load_corpus_file() exists at
    all: every corpus resource's name embeds '{{run_id}}' (lib/base.libsonnet's
    name()), so loading a corpus file through this module alone produces
    'yd-test-offline-...' names -- fine for the offline layer, which never sends
    them anywhere, but useless to the live layer, which has to match a returned
    entity back to the specification that created it under *this run's* id.
    resource_live.load_corpus_file() overrides exactly this one value for that
    reason. Set with setdefault, not assignment, so a caller (or a config file)
    that has already chosen a run id keeps it.
    """
    with open(TEST_CONFIG, "rb") as file:
        config = tomllib.load(file)
    common = config["common"]
    variables = dict(common.get("variables", {}))
    variables.setdefault("namespace", common["namespace"])
    variables.setdefault("tag", common["tag"])
    variables.setdefault("run_id", "offline")
    return variables


def install_variables() -> dict[str, str | None]:
    """
    Force the corpus's dummy values into the substitution engine, returning what
    each key held beforehand so remove_variables() can put it back exactly.

    Set directly rather than through YD_VAR_* environment variables: variables.py
    scans the environment at import, which has already happened by the time a
    fixture runs.

    *Forcing* rather than merging, and that distinction is the whole point. An
    earlier version used add_substitutions_without_overwriting(), which skips a key
    that already has a value -- and 'namespace' and 'tag' always do by the time a
    test runs, because conftest's credential probe imports wrapper, which loads the
    ambient configuration and registers them. The corpus therefore resolved
    '{{namespace}}' to whatever config.toml happened to say (observed: 'yd-demo')
    while the live layer, which passes '-c test-config.toml' to a subprocess,
    resolved it to 'yd-cli-tests'. The two layers disagreed about what the corpus
    said and nothing caught it, since the offline comparison checks a specification
    against a model built from that same specification.

    Forcing here gives the test config the precedence the CLI itself gives an
    explicitly selected config file (see add_substitutions_from_config_file), which
    is what '-c' means in the live layer.
    """
    from yellowdog_cli.utils.variables import (
        VARIABLE_SUBSTITUTIONS,
        _update_and_resolve_substitutions,
    )

    subs = dummy_variables()
    previous: dict[str, str | None] = {
        key: VARIABLE_SUBSTITUTIONS.get(key) for key in subs
    }
    # Incoming wins, and the resolution pass runs -- which a plain dict assignment
    # would skip, leaving a value that references another variable unresolved.
    _update_and_resolve_substitutions({**VARIABLE_SUBSTITUTIONS, **subs})
    return previous


def remove_variables(previous: dict[str, str | None]) -> None:
    """
    Restore exactly what install_variables() found.

    VARIABLE_SUBSTITUTIONS is a process-global dict shared with every other test
    module in the session; leaving the dummy values in it would let a later test's
    lookup of a generically-named variable (namespace, tag, run_id) silently
    succeed where it expected to default. A key that was absent beforehand is
    removed, and a key that held some other value gets that value back rather than
    being deleted -- deleting it would leave the session subtly different from how
    the test found it, which is the same class of failure in the other direction.
    """
    from yellowdog_cli.utils.variables import (
        VARIABLE_SUBSTITUTIONS,
        _update_and_resolve_substitutions,
    )

    merged = dict(VARIABLE_SUBSTITUTIONS)
    for key, value in previous.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    _update_and_resolve_substitutions(merged)


def corpus_files() -> list[Path]:
    """Every corpus file, in a stable order."""
    return sorted(CORPUS_DIR.glob("*.jsonnet"))


# Files the live layer (Tasks 7-8) must not create: credentials need real provider
# secrets, which are out of scope for these tests, and the namespace file is handled
# once per test account by the session fixture rather than as a per-test resource
# specification.
OFFLINE_ONLY = {"credentials.jsonnet", "namespace.jsonnet"}


def live_corpus_files() -> list[Path]:
    """Every corpus file the live layer may create, in the same stable order."""
    return [path for path in corpus_files() if path.name not in OFFLINE_ONLY]


def load_corpus_file(path: Path) -> list[dict]:
    """
    Load one corpus file the way yd-create does.

    ARGS_PARSER.resource_specifications is a read-only property (it has a getter
    but no setter, since only yd-create/yd-remove populate the underlying argparse
    namespace); the assignment goes to the namespace attribute it reads from
    instead of to the property itself.

    Also chdir's to the file's own directory for the duration of the load: a
    Jsonnet 'import' is resolved relative to the current working directory, not to
    the file doing the importing, because VariableSubstitutedJsonnetFile
    (variables.py) writes its variable-substituted copy into os.getcwd() before
    handing it to the Jsonnet evaluator (see that class's own commit message,
    "Create Jsonnet temporary file in current directory to fix import path
    issue") -- i.e. a real invocation is expected to run from the directory
    containing the spec and anything it imports. Without matching that here,
    'lib/base.libsonnet' resolves against the repo root (pytest's cwd) instead of
    tests/resources/, and the import fails regardless of how correct the corpus
    file itself is.
    """
    from yellowdog_cli.utils.args import ARGS_PARSER
    from yellowdog_cli.utils.load_resources import load_resource_specifications

    original = ARGS_PARSER.resource_specifications
    original_cwd = os.getcwd()
    ARGS_PARSER.args.resource_specifications = [str(path.resolve())]
    try:
        os.chdir(path.parent)
        return load_resource_specifications()
    finally:
        os.chdir(original_cwd)
        ARGS_PARSER.args.resource_specifications = original


def spec_properties(resource: dict) -> dict:
    """The resource's properties, without the loader's own bookkeeping keys."""
    return {k: v for k, v in resource.items() if k not in META_KEYS}
