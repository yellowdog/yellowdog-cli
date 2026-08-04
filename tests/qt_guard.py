"""
Module-level skip for tests that need a working Qt.

Deliberately not `pytest.importorskip("PyQt6.QtWidgets")`. As of pytest 9.1 that
skips only on ModuleNotFoundError — the module being absent — so it does not cover
the case these tests most need covered: PyQt6 installed, but its Qt runtime
libraries missing. A minimal Linux image without libGL raises

    ImportError: libGL.so.1: cannot open shared object file

which is an ImportError but not a ModuleNotFoundError, so pytest 9.1 lets it
through and every Commander test module fails to collect. Observed on a fresh
Ubuntu node: 19 collection errors.

`exc_type=ImportError` would also fix it, but only on pytest >= 8.2, and pytest is
unpinned in pyproject.toml. Catching ImportError ourselves works on any version and
states the intent plainly: skip whenever Qt cannot be used, whatever the reason.
"""

from importlib import import_module

import pytest


def require_qt() -> None:
    """
    Skip the calling module unless PyQt6 and its Qt runtime libraries both work.

    Call this before importing PyQt6 or anything that imports Commander, which
    imports QtWidgets at module level. gui_harness and commander_dialogs call it
    themselves, so importing either of those is safe in any order.
    """
    try:
        # QtWidgets is the submodule that pulls in the graphical runtime libraries;
        # guarding on the top-level 'PyQt6' package would not catch a missing
        # libGL/xcb. Imported via import_module so no name is bound and left unused.
        import_module("PyQt6.QtWidgets")
    except ImportError as exc:
        pytest.skip(
            f"Qt is unavailable, so Commander cannot be tested here: {exc}",
            allow_module_level=True,
        )
