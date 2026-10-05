"""
The compiled specification validators, kept between runs.

fastjsonschema turns a schema into Python source and Python then compiles
that source, which for the larger families is most of a second on an older
machine, paid again by every process; checking a document against the
result takes a fraction of a millisecond. So the compiled code object is
kept, marshalled as a .pyc is, in a directory under the system's temporary
directory, where the operating system's own clean-up removes it: nothing is
left anywhere a user would have to find it.

A file is named by its stem (the family, or the config family's subset of
sections) and a digest of everything its code depends on: the built schema
itself, fastjsonschema's version and the interpreter's. So a newer SDK,
even one installed without a version change, builds a different schema and
misses; and writing a file removes all but the stem's most recently used
others, so at most CACHE_KEEP per stem are kept. More than one, because the
directory is the user's, not an environment's: two environments that build
different schemas (tox's interpreters, a pipx install beside a development
venv) would otherwise delete each other's file on every run.

Marshalled code is executed when it is loaded, so the directory is used
only if it can be trusted: on POSIX it is per user, created mode 0700, and
refused if it is anything else -- a symlink, another user's, or open to
group or others. Windows' temporary directory is already the user's own.
Whenever the cache cannot be used -- an untrusted or unwritable directory,
an unreadable or corrupt file -- the validator is compiled as it would be
without one, which is always correct, only slower, and the reason is handed
to the reporter the command wrappers register (report_problems_to(), with
print_debug()), once per reason per process. A cache file not being there
yet is no problem, and is never reported.

Imports nothing from the CLI: spec_schema.py is its only caller, and the
reporter is how a message reaches printing.py, which parses the command
line at import.
"""

from __future__ import annotations

import hashlib
import json
import marshal
import os
import stat
import sys
import tempfile
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import fastjsonschema
from fastjsonschema import RefResolver

CACHE_FORMAT = 1  # raised whenever what a cache file holds changes
CACHE_DIRECTORY_NAME = "yellowdog-cli-schemas"
CACHE_SUFFIX = ".bin"
CACHE_KEEP = 4  # files kept per stem, the most recently used
_DIGEST_LENGTH = 32
REPORT_PREFIX = "Schema cache: "
_NOT_USED = "; compiling the schemas without it"

_reporter: Callable[[str], None] | None = None
_REPORTED: set[str] = set()


def report_problems_to(reporter: Callable[[str], None] | None) -> None:
    """Hand every later reason the cache cannot be used to 'reporter'."""
    global _reporter
    _reporter = reporter


def _report(message: str) -> None:
    if _reporter is not None and message not in _REPORTED:
        _REPORTED.add(message)
        _reporter(f"{REPORT_PREFIX}{message}")


def _reason(error: OSError) -> str:
    return error.strerror or str(error)


def _temp_root() -> Path:
    """The system's temporary directory; a seam for the tests."""
    return Path(tempfile.gettempdir())


def cache_directory() -> Path | None:
    """
    The cache directory, created if need be, or None if it cannot be
    created or cannot be trusted.
    """
    if sys.platform == "win32":
        path = _temp_root() / CACHE_DIRECTORY_NAME
        try:
            path.mkdir(exist_ok=True)
        except OSError as e:
            _report(f"cannot create '{path}': {_reason(e)}{_NOT_USED}")
            return None
        if path.is_symlink() or not path.is_dir():
            _report(f"'{path}' is not a directory{_NOT_USED}")
            return None
        return path
    uid = os.getuid()
    path = _temp_root() / f"{CACHE_DIRECTORY_NAME}-{uid}"
    try:
        path.mkdir(mode=0o700, exist_ok=True)
        info = path.lstat()
    except OSError as e:
        _report(f"cannot create '{path}': {_reason(e)}{_NOT_USED}")
        return None
    problem = None
    if stat.S_ISLNK(info.st_mode):
        problem = "is a symbolic link"
    elif not stat.S_ISDIR(info.st_mode):
        problem = "is not a directory"
    elif info.st_uid != uid:
        problem = "belongs to another user"
    elif info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        problem = f"is open to other users (mode {stat.S_IMODE(info.st_mode):o})"
    if problem is not None:
        _report(f"'{path}' {problem}{_NOT_USED}")
        return None
    return path


def _digest(schema: dict[str, Any]) -> str:
    """What the compiled code depends on, as a file-name component."""
    digest = hashlib.sha256()
    for part in (
        str(CACHE_FORMAT),
        fastjsonschema.VERSION,
        sys.version,
        json.dumps(schema, sort_keys=True),
    ):
        digest.update(part.encode())
        digest.update(b"\0")
    return digest.hexdigest()[:_DIGEST_LENGTH]


def _load(path: Path) -> types.CodeType | None:
    """The code cached at 'path', or None: not cached yet, or unusable."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as e:
        _report(f"cannot read '{path}': {_reason(e)}; recompiling")
        return None
    try:
        code = marshal.loads(data)
    except (EOFError, ValueError, TypeError):
        code = None
    if not isinstance(code, types.CodeType):
        _report(f"'{path}' is not a compiled schema; recompiling")
        return None
    try:
        os.utime(path)  # Used: kept ahead of the stem's older files
    except OSError:
        pass  # Only the order of removal depends on it
    return code


def _store(directory: Path, stem: str, path: Path, code: types.CodeType) -> None:
    """
    Write 'code' to 'path' atomically, so a concurrent reader sees the whole
    file or none, then remove the stem's other files beyond the CACHE_KEEP
    most recently used. Any failure leaves the cache as it was: another
    process may hold a file open on Windows.
    """
    try:
        descriptor, partial = tempfile.mkstemp(
            dir=directory, prefix=f".{stem}-", suffix=".part"
        )
    except OSError as e:
        _report(f"cannot write to '{directory}': {_reason(e)}")
        return
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(marshal.dumps(code))
        os.replace(partial, path)
    except OSError as e:
        _report(f"cannot write '{path}': {_reason(e)}")
        try:
            os.remove(partial)
        except OSError:
            pass
        return
    # 'config-common' must not remove 'config-common-workerPool-...'
    others = [
        other
        for other in directory.glob(f"{stem}-*{CACHE_SUFFIX}")
        if other != path and other.stem.rsplit("-", 1)[0] == stem
    ]
    for other in sorted(others, key=_last_used, reverse=True)[CACHE_KEEP - 1 :]:
        try:
            other.unlink()
        except FileNotFoundError:
            pass  # another process removed it first
        except OSError as e:
            _report(f"cannot remove '{other}': {_reason(e)}")


def _last_used(path: Path) -> float:
    """When a cache file was last used (written, or loaded); 0 if gone."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def compile_validator(schema: dict[str, Any], stem: str) -> Callable[[Any], Any]:
    """
    'schema' compiled by fastjsonschema, from the cache when it holds this
    schema's code, else compiled and stored. The validator is the same
    either way: fastjsonschema.compile() executes the same generated code.
    'schema' is rewritten in place by the compile, as by
    fastjsonschema.compile().
    """
    name = RefResolver.from_schema(
        {"$id": schema.get("$id", "")}, store={}
    ).get_scope_name()
    directory = cache_directory()
    path = None
    if directory is not None:
        # Before compiling: fastjsonschema rewrites every '$ref' in place
        path = directory / f"{stem}-{_digest(schema)}{CACHE_SUFFIX}"
        code = _load(path)
        if code is not None:
            try:
                validate = _validator(code, name)
            except Exception as e:
                # Cached code is never trusted to work: compiled afresh instead
                _report(f"'{path}' failed as it loaded ({e}); recompiling")
                validate = None
            else:
                if validate is None:
                    _report(f"'{path}' defines no validator; recompiling")
            if validate is not None:
                return validate
    source = fastjsonschema.compile_to_code(schema)
    code = compile(source, f"<{stem} schema>", "exec")
    if directory is not None and path is not None:
        _store(directory, stem, path, code)
    validate = _validator(code, name)
    if validate is None:
        raise fastjsonschema.JsonSchemaDefinitionException(
            f"the code compiled from the {stem} schema defines no '{name}'"
        )
    return validate


def _validator(code: types.CodeType, name: str) -> Callable[[Any], Any] | None:
    """The validator 'code' defines, or None if it defines none."""
    namespace: dict[str, Any] = {}
    exec(code, namespace)
    validate = namespace.get(name)
    return validate if callable(validate) else None
