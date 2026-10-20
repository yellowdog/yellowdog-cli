"""
Tests for the cache of Platform lookups that Tab completion keeps
(utils/completion_cache.py): a JSON file per key in a per-user directory
under the system's temporary directory, read only while fresh, and every
stale file removed whenever one is written.
"""

import json
import os
import stat
import sys

import pytest

from yellowdog_cli.utils import completion_cache
from yellowdog_cli.utils.limits import COMPLETION_CACHE_SECONDS

ITEMS = [{"id": "ydid:wrkreq:000000:a", "name": "a", "status": "RUNNING"}]
NOW = 1_000_000.0

posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="the directory checks are POSIX's"
)


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(completion_cache, "_temp_root", lambda: tmp_path)
    return tmp_path


def test_a_written_entry_is_read_back(root):
    completion_cache.write("k", ITEMS, now=NOW)

    assert completion_cache.read("k", now=NOW + 1) == ITEMS


def test_an_entry_expires(root):
    completion_cache.write("k", ITEMS, now=NOW)

    assert completion_cache.read("k", now=NOW + COMPLETION_CACHE_SECONDS) is None


def test_a_missing_entry_is_a_miss(root):
    assert completion_cache.read("nothing", now=NOW) is None


def test_writing_removes_stale_files_and_keeps_fresh_ones(root):
    completion_cache.write("old", ITEMS, now=NOW)
    directory = completion_cache.cache_directory()
    assert directory is not None
    stale = directory / "old.json"
    os.utime(stale, (NOW, NOW))
    completion_cache.write("fresh", ITEMS, now=NOW + COMPLETION_CACHE_SECONDS - 1)
    os.utime(directory / "fresh.json", (NOW + 5, NOW + 5))

    completion_cache.write("new", ITEMS, now=NOW + COMPLETION_CACHE_SECONDS + 1)

    assert not stale.exists()
    assert (directory / "fresh.json").exists()
    assert (directory / "new.json").exists()


def test_a_left_over_partial_file_is_removed(root):
    completion_cache.write("k", ITEMS, now=NOW)
    directory = completion_cache.cache_directory()
    assert directory is not None
    partial = directory / ".k-abc.part"
    partial.write_text("{", encoding="utf-8")
    os.utime(partial, (NOW, NOW))

    completion_cache.write("k", ITEMS, now=NOW + COMPLETION_CACHE_SECONDS + 1)

    assert not partial.exists()


@pytest.mark.parametrize("content", ["{not json", '["a list"]', '{"written": "x"}'])
def test_an_unreadable_entry_is_a_miss(root, content):
    completion_cache.write("k", ITEMS, now=NOW)
    directory = completion_cache.cache_directory()
    assert directory is not None
    (directory / "k.json").write_text(content, encoding="utf-8")

    assert completion_cache.read("k", now=NOW) is None


@posix_only
def test_the_directory_is_private(root):
    directory = completion_cache.cache_directory()

    assert directory is not None
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert str(os.getuid()) in directory.name


@posix_only
def test_a_directory_open_to_others_is_not_used(root):
    directory = completion_cache.cache_directory()
    assert directory is not None
    directory.chmod(0o777)

    assert completion_cache.cache_directory() is None
    completion_cache.write("k", ITEMS, now=NOW)
    assert not (directory / "k.json").exists()
    assert completion_cache.read("k", now=NOW) is None


@posix_only
def test_a_symlinked_directory_is_not_used(root, tmp_path_factory):
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    elsewhere.chmod(0o700)
    (root / f"{completion_cache.CACHE_DIRECTORY_NAME}-{os.getuid()}").symlink_to(
        elsewhere
    )

    assert completion_cache.cache_directory() is None


def test_the_key_is_stable_and_depends_on_every_part():
    key = completion_cache.cache_key("url", "ns", "tag")

    assert key == completion_cache.cache_key("url", "ns", "tag")
    assert key != completion_cache.cache_key("url", "ns", "tag2")
    # Parts are separated, so moving a boundary changes the key
    assert key != completion_cache.cache_key("url", "nst", "ag")


def test_the_file_holds_no_more_than_the_items(root):
    completion_cache.write("k", ITEMS, now=NOW)
    directory = completion_cache.cache_directory()
    assert directory is not None

    stored = json.loads((directory / "k.json").read_text(encoding="utf-8"))

    assert stored == {"written": NOW, "items": ITEMS}


def test_an_entry_written_in_the_future_is_a_miss(root):
    # The clock set back since: its age is unknown, so it is not trusted
    completion_cache.write("k", ITEMS, now=NOW)

    assert completion_cache.read("k", now=NOW - 1) is None
