"""
Tests for optional-import guards in check_imports.
"""

import builtins
import sys
import types

import pytest

from yellowdog_cli.utils.check_imports import check_commander_imports


def test_check_commander_imports_raises_when_pyqt6_absent(monkeypatch):
    # Setting the module entry to None makes the PyQt6 import raise
    # ModuleNotFoundError, simulating the extra not being installed.
    monkeypatch.setitem(sys.modules, "PyQt6", None)
    with pytest.raises(ImportError, match=r"pip install .*commander") as raised:
        check_commander_imports()
    # The advice must be to install the extra, not to install system libraries.
    assert "apt-get" not in str(raised.value)


def test_check_commander_imports_explains_a_missing_system_library(monkeypatch):
    """
    The case that used to produce a raw traceback: PyQt6 installed, but Qt's own
    shared libraries missing, as on a minimal server image.

    The guard used to probe the top-level 'PyQt6' package, which imports without
    touching those libraries — so it passed, and the failure surfaced from
    commander.py's own 'from PyQt6.QtGui import ...' as an unhandled ImportError.
    Probing QtWidgets moves the failure to where it can be explained.
    """
    module = types.ModuleType("PyQt6")
    module.__path__ = []  # a package, so a submodule import is attempted
    monkeypatch.setitem(sys.modules, "PyQt6", module)

    real_import = builtins.__import__

    def failing_import(name, *args, **kwargs):
        if name == "PyQt6.QtWidgets" or name.startswith("PyQt6.Qt"):
            raise ImportError(
                "libGL.so.1: cannot open shared object file: No such file or directory"
            )
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing_import)

    with pytest.raises(ImportError) as raised:
        check_commander_imports()

    message = str(raised.value)
    # Names the library Qt could not find, and gives the remedy that would work.
    assert "libGL.so.1" in message
    assert "apt-get install" in message
    # Must not send someone to pip, which cannot fix a missing system library.
    assert "pip install" not in message


def test_check_commander_imports_ok_when_present():
    pytest.importorskip("PyQt6.QtWidgets")
    check_commander_imports()  # must not raise
