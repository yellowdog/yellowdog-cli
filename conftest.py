import atexit
import sys
import time

import pytest
from cli_test_helpers import shell

# Strip pytest's own arguments before any yellowdog_cli modules are imported.
# CLIParser calls parse_args() at module level; without this, pytest's argv
# (e.g. file paths, -v) would be misinterpreted or cause parse errors.
sys.argv = sys.argv[:1]


def pytest_addoption(parser):
    parser.addoption(
        "--run-demos",
        action="store_true",
        default=False,
        help="Run live demos",
    )
    parser.addoption(
        "--run-dryruns",
        action="store_true",
        default=False,
        help="Run demo dry-runs (requires ../python-examples-demos)",
    )
    parser.addoption(
        "--run-system",
        action="store_true",
        default=False,
        help="Run system tests against the live platform",
    )
    parser.addoption(
        "--run-system-compute",
        action="store_true",
        default=False,
        help="Run system tests that provision real cloud compute (implies --run-system)",
    )


def pytest_collection_modifyitems(config, items):
    run_system = config.getoption("--run-system") or config.getoption(
        "--run-system-compute"
    )

    if not config.getoption("--run-demos"):
        skipper = pytest.mark.skip(reason="Only run when '--run-demos' is given")
        for item in items:
            if "demos" in item.keywords:
                item.add_marker(skipper)

    if not config.getoption("--run-dryruns"):
        skipper = pytest.mark.skip(reason="Only run when '--run-dryruns' is given")
        for item in items:
            if "dryruns" in item.keywords:
                item.add_marker(skipper)

    if not run_system:
        skipper = pytest.mark.skip(reason="Only run when '--run-system' is given")
        for item in items:
            if "system" in item.keywords:
                item.add_marker(skipper)

    if not config.getoption("--run-system-compute"):
        skipper = pytest.mark.skip(
            reason="Only run when '--run-system-compute' is given"
        )
        for item in items:
            if "system_compute" in item.keywords:
                item.add_marker(skipper)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cleanup():
    """
    Safety-net teardown fixture. Tests register cleanup commands by calling
    the yielded function; all are executed in reverse order after the test,
    regardless of whether it passed or failed.
    """
    cmds: list[str] = []
    yield cmds.append
    for cmd in reversed(cmds):
        shell(cmd)


@pytest.fixture(scope="session")
def qapp():
    """
    A single offscreen QApplication for Commander GUI tests. Skips (never
    errors) when the GUI cannot be initialised:
    - PyQt6 (the optional 'commander' extra) is not installed, or
    - PyQt6 is installed but its Qt runtime libraries are missing (e.g. a
      minimal headless node without libGL/xcb) so QtWidgets/QApplication fail.
    Offscreen mode means no window is shown and no display is required.
    """
    import os

    # QtWidgets is the submodule that pulls in the graphical runtime libs;
    # importorskip on the top-level 'PyQt6' package would not catch a missing
    # libGL/xcb, so guard on QtWidgets directly.
    pytest.importorskip("PyQt6.QtWidgets")

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    try:
        return QApplication.instance() or QApplication([])
    except Exception as exc:  # Qt platform plugin / runtime libs unavailable
        pytest.skip(f"Qt platform unavailable: {exc}")


@pytest.fixture(scope="session")
def system_tag() -> str:
    """
    Session-unique tag for compute tests (e.g. 'pytest-1741880400').

    Belt-and-braces: registers an atexit handler that cancels any outstanding
    Work Requirements and terminates any Worker Pools carrying the tag, so
    cloud resources are cleaned up even if a test crashes without teardown.
    """
    tag = f"pytest-{int(time.time())}"

    def _cleanup() -> None:
        shell(f"yd-cancel -y -t={tag} -n=pytest-system")
        shell(f"yd-terminate -y -t={tag} -n=pytest-system")

    atexit.register(_cleanup)
    return tag


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def yd_list_row_matches(stdout: str, name: str, status: str) -> bool:
    """
    Return True if any line of ``yd-list`` tabular output contains both
    ``name`` and ``status`` on the same row.

    Useful for asserting that a named resource is in a particular state,
    e.g. ``yd_list_row_matches(result.stdout, "my-pool", "RUNNING")``.
    """
    return any(name in line and status in line for line in stdout.splitlines())


# ---------------------------------------------------------------------------
# pytest configuration
# ---------------------------------------------------------------------------


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "demos: mark test to run only when '--run-demos' is specified"
    )
    config.addinivalue_line(
        "markers", "dryruns: mark test to run only when '--run-dryruns' is specified"
    )
    config.addinivalue_line(
        "markers",
        "system: mark test to run only when '--run-system' is specified",
    )
    config.addinivalue_line(
        "markers",
        "system_compute: mark test to run only when '--run-system-compute' is specified",
    )
