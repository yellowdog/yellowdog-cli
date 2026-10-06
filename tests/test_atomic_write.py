"""
utils/atomic_write.py: a file replaced whole or not at all, an existing
file keeping its permissions and a new one getting the umask's.
"""

import os
import stat
import sys

import pytest

import yellowdog_cli.utils.atomic_write as atomic_write


def test_the_text_is_written(tmp_path):
    path = tmp_path / "a.txt"
    atomic_write.write_text_atomically(str(path), "café\n")
    assert path.read_text(encoding="utf-8") == "café\n"


def test_an_interrupted_write_leaves_the_original(tmp_path, monkeypatch):
    path = tmp_path / "a.txt"
    path.write_text("original", encoding="utf-8")

    def interrupted(source, destination):
        raise OSError("disk full")

    monkeypatch.setattr(atomic_write.os, "replace", interrupted)
    with pytest.raises(OSError):
        atomic_write.write_text_atomically(str(path), "new")
    assert path.read_text(encoding="utf-8") == "original"
    assert os.listdir(tmp_path) == ["a.txt"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_an_existing_file_keeps_its_permissions(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("x", encoding="utf-8")
    path.chmod(0o640)
    atomic_write.write_text_atomically(str(path), "y")
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_a_new_file_gets_the_umasks_permissions(tmp_path):
    previous = os.umask(0o022)
    try:
        path = tmp_path / "new.txt"
        atomic_write.write_text_atomically(str(path), "y")
        assert stat.S_IMODE(path.stat().st_mode) == 0o644
    finally:
        os.umask(previous)
