"""
Tests for optional-import guards in check_imports.
"""

import sys

import pytest

from yellowdog_cli.utils.check_imports import check_commander_imports


def test_check_commander_imports_raises_when_pyqt6_absent(monkeypatch):
    # Setting the module entry to None makes `import PyQt6` raise ImportError,
    # simulating the extra not being installed.
    monkeypatch.setitem(sys.modules, "PyQt6", None)
    with pytest.raises(ImportError, match="commander"):
        check_commander_imports()


def test_check_commander_imports_ok_when_present():
    pytest.importorskip("PyQt6")
    check_commander_imports()  # must not raise
