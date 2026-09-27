"""
Module-level skip for tests that need the 'mcp' extra. Catches ImportError,
not ModuleNotFoundError alone, for the same reason as qt_guard.py.
"""

from importlib import import_module

import pytest


def require_mcp() -> None:
    try:
        import_module("mcp.server.lowlevel")
    except ImportError as exc:
        pytest.skip(f"needs the 'mcp' extra: {exc}", allow_module_level=True)
