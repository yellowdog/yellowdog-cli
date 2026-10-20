"""
The answers to Tab completion's Platform lookups, kept for the Tabs that
follow (utils/completion_lookups.py).

One JSON file per lookup, named by its key (cache_key(): a digest of what
the lookup depends on, never a credential), holding when it was written and
the items found: names, IDs, statuses and creation times. An entry is read
only while younger than COMPLETION_CACHE_SECONDS, and every write removes
each file older than that, so the directory holds the lookups of the last
half-minute and nothing a user would ever have to clear; it is under the
system's temporary directory besides, which the operating system cleans.

The directory is per user on POSIX, created mode 0700, and not used if it
is anything else -- a symlink, another user's, or open to group or others
-- as the compiled-schema cache's is (specs/schema_cache.py). Windows'
temporary directory is already the user's own. Every failure means no
cache, never an error: completion must answer, or stay silent.

Imports nothing from the CLI.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tempfile
import time
from pathlib import Path

from yellowdog_cli.utils.limits import COMPLETION_CACHE_SECONDS

CACHE_DIRECTORY_NAME = "yellowdog-cli-completion"
_SUFFIX = ".json"
_PARTIAL_SUFFIX = ".part"


def _temp_root() -> Path:
    """
    The system's temporary directory; a seam for the tests.
    """
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
        except OSError:
            return None
        return None if path.is_symlink() or not path.is_dir() else path
    uid = os.getuid()
    path = _temp_root() / f"{CACHE_DIRECTORY_NAME}-{uid}"
    try:
        path.mkdir(mode=0o700, exist_ok=True)
        info = path.lstat()
    except OSError:
        return None
    if (
        not stat.S_ISDIR(info.st_mode)  # a symlink is not, by lstat()
        or info.st_uid != uid
        or info.st_mode & (stat.S_IRWXG | stat.S_IRWXO)
    ):
        return None
    return path


def cache_key(*parts: str) -> str:
    """
    A file-name-safe digest of the parts a lookup depends on.
    """
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode())
        digest.update(b"\0")
    return digest.hexdigest()[:32]


def read(key: str, now: float | None = None) -> list[dict] | None:
    """
    The items cached under 'key', or None: none cached, expired, or
    unusable.
    """
    directory = cache_directory()
    if directory is None:
        return None
    try:
        with open(directory / f"{key}{_SUFFIX}", encoding="utf-8") as file:
            entry = json.load(file)
    except (OSError, ValueError):
        return None
    if not isinstance(entry, dict):
        return None
    written, items = entry.get("written"), entry.get("items")
    if not isinstance(written, (int, float)) or not isinstance(items, list):
        return None
    # An entry from the future (the clock set back since) has no known age
    age = (time.time() if now is None else now) - written
    if not 0 <= age < COMPLETION_CACHE_SECONDS:
        return None
    return items


def write(key: str, items: list[dict], now: float | None = None) -> None:
    """
    Cache 'items' under 'key', atomically, then remove every file that has
    expired. Any failure leaves the cache as it was.
    """
    directory = cache_directory()
    if directory is None:
        return
    now = time.time() if now is None else now
    try:
        descriptor, partial = tempfile.mkstemp(
            dir=directory, prefix=f".{key}-", suffix=_PARTIAL_SUFFIX
        )
    except OSError:
        return
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump({"written": now, "items": items}, file)
        os.replace(partial, directory / f"{key}{_SUFFIX}")
    except (OSError, TypeError, ValueError):
        try:
            os.remove(partial)
        except OSError:
            pass
        return
    _remove_expired(directory, now)


def _remove_expired(directory: Path, now: float) -> None:
    """
    Remove every cache file, and every partial one left by a writer that
    died, last modified COMPLETION_CACHE_SECONDS ago or more.
    """
    for path in [
        *directory.glob(f"*{_SUFFIX}"),
        *directory.glob(f".*{_PARTIAL_SUFFIX}"),
    ]:
        try:
            if now - path.stat().st_mtime >= COMPLETION_CACHE_SECONDS:
                path.unlink()
        except OSError:
            pass  # another process removed it first, or holds it open
