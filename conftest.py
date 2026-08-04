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


@pytest.fixture(autouse=True)
def _gui_harness_guard():
    """
    Surface anything that happened inside a Qt callback.

    Dialogs armed with gui_harness.arm_modal() have their exec() called by the
    code under test, so the test never sees a return value. Without this, an
    assertion raised inside the queued interaction would be printed by Qt and
    discarded — leaving the test green — and a dialog that never closed would look
    like a slow test rather than a broken one.

    Autouse and repo-wide so no GUI test can forget it. Silently inert when PyQt6
    is not installed, which is also when there are no GUI tests to guard.
    """
    try:
        import gui_harness
    except (ImportError, pytest.skip.Exception):
        # ImportError: not running from the tests directory. Skipped: gui_harness
        # guards its own Qt import (see tests/qt_guard.py), so on a node where Qt
        # is unusable importing it raises Skipped rather than ImportError. This
        # fixture is autouse for the whole repo, so it must stay inert either way —
        # letting Skipped out of here would skip every test in the suite, GUI or not.
        yield
        return

    gui_harness.reset()
    yield
    gui_harness.check()


@pytest.fixture(autouse=True)
def _no_config_discovery(request, monkeypatch):
    """
    Keep Commander's config discovery out of the GUI unit tests.

    A YellowDogApp defers _set_config_file with singleShot(0), and that calls
    _parse_yd_config, which runs 'yd-show' as a child process and blocks in a nested
    event loop until it finishes. So every test that constructs a window ran a real
    CLI invocation inside whichever event loop spun first — usually a dialog's exec().
    Measured on this repo: 235 invocations across the Commander tests, 18 of their 21
    seconds, and far worse on a small CI node. It also made them depend on an
    installed, working yd-show, and on whatever namespace and tag the environment
    happened to supply.

    None of these tests are about discovery: they set _namespace/_tag directly or
    call _set_placeholders. The two that do exercise _parse_yd_config itself opt out
    with @pytest.mark.real_config_parse.

    Returning False is what the real method returns when it cannot discover anything,
    which leaves the placeholders blank — the same state as a parse that found no
    namespace or tag.
    """
    if "qapp" not in request.fixturenames:
        return  # not a GUI test; nothing constructs a window
    if "real_config_parse" in request.keywords:
        return

    from yellowdog_cli.commander.commander import YellowDogApp

    monkeypatch.setattr(
        YellowDogApp, "_parse_yd_config", lambda self, quiet=False: False
    )


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

    # QtWidgets is the submodule that pulls in the graphical runtime libs, so guard
    # on it rather than on the top-level 'PyQt6' package. Not importorskip: from
    # pytest 9.1 that skips only on ModuleNotFoundError, so a missing libGL — an
    # ImportError but not a ModuleNotFoundError — would error instead of skipping.
    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError as exc:
        pytest.skip(f"Qt is unavailable: {exc}")

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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


_dummy_credentials_used = False


def _supply_dummy_credentials_if_unconfigured(config) -> None:
    """
    Let the default tests run on a machine with no YellowDog configuration.

    Most test modules import a yd-* command module, and those load their
    configuration when imported — wrapper.py does 'CONFIG_COMMON =
    load_config_common()', which reports a missing key or secret and exits. During
    collection that surfaces as a pytest INTERNALERROR with no tests run at all, even
    though the default tests never contact the platform. (Only key and secret bite:
    namespace and tag already fall back to defaults.)

    Whether configuration exists is decided by asking the real loader, not by
    guessing: credentials can come from the environment under either of two names, a
    config.toml, an importCommon indirection inside it, or a .env somewhere above the
    working directory. If the import succeeds, nothing is touched — an environment
    variable outranks both config.toml and .env, so a dummy set over a working
    credential would shadow it.

    Never substituted for a run that talks to the platform: those need real
    credentials, and 'auth failed' hours later is a worse answer than the CLI's own
    'Missing configuration data' now.
    """
    global _dummy_credentials_used

    import os

    from yellowdog_cli.utils.settings import YD_KEY, YD_SECRET

    if any(
        config.getoption(flag)
        for flag in ("--run-system", "--run-system-compute", "--run-demos")
    ):
        return
    if _command_modules_import_cleanly():
        return

    os.environ[YD_KEY] = "dummy-key-for-tests"
    os.environ[YD_SECRET] = "dummy-secret-for-tests"
    _dummy_credentials_used = True


def _command_modules_import_cleanly() -> bool:
    """
    Whether this machine has a configuration a yd-* command can load.

    wrapper.py loads the common config when imported and exits if it cannot, so this
    asks the loader itself. Its output is discarded: on failure the CLI prints an
    error that is about to be made irrelevant by the fallback, and on success it
    prints notes about where the configuration came from that would otherwise appear
    twice. Nothing is wasted either way — collection imports this module immediately
    afterwards, and the second import is cached.
    """
    from contextlib import redirect_stderr, redirect_stdout
    from io import StringIO

    discard = StringIO()
    try:
        with redirect_stdout(discard), redirect_stderr(discard):
            import yellowdog_cli.utils.wrapper  # noqa: F401
    except SystemExit:
        return False
    return True


def pytest_report_header(config):
    if _dummy_credentials_used:
        return (
            "yellowdog: no usable configuration found, so a dummy key/secret is in"
            " use; the default tests do not contact the platform"
        )
    return None


def pytest_configure(config):
    _supply_dummy_credentials_if_unconfigured(config)
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
    config.addinivalue_line(
        "markers",
        "real_config_parse: keep Commander's real _parse_yd_config, which runs"
        " 'yd-show' (see the '_no_config_discovery' fixture)",
    )
