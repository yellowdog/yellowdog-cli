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
    call _set_placeholders. The ones that do exercise discovery itself opt out with
    @pytest.mark.real_config_parse — two in test_commander_shutdown.py, and the whole
    of test_commander_config_discovery.py, which overrides _yd_show_command instead so
    that it still spawns no yd-show.

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
        YellowDogApp,
        "_parse_yd_config",
        lambda self, quiet=False, timeout_ms=None: False,
    )


@pytest.fixture(scope="session", autouse=True)
def _preserve_qt_sidebar_width():
    """
    Put the machine's own Qt sidebar width back after the test session.

    Qt persists the file dialog's sidebar width in shared user settings — a real
    plist or registry key, belonging to the user rather than to the test session —
    and writes it whenever one of these dialogs closes. Commander reads a
    remembered width as the user's own choice and leaves it alone, so a run that
    left 90 behind quietly turned the widening off on the developer's machine.

    Restored from atexit rather than from this fixture's teardown, because that is
    the last thing to run: the QApplication outlives every fixture (see qapp), and
    the stray write landed after a teardown-time restore.

    Inert without a usable Qt, since this is autouse for the whole repo.
    """
    try:
        from PyQt6.QtCore import QSettings

        from yellowdog_cli.commander.commander import (
            QT_SETTINGS_ORGANISATION,
            QT_SIDEBAR_WIDTH_SETTING,
        )
    except Exception:  # PyQt6 absent, or its Qt runtime libraries are
        yield
        return

    previous = QSettings(QSettings.Scope.UserScope, QT_SETTINGS_ORGANISATION).value(
        QT_SIDEBAR_WIDTH_SETTING
    )

    def restore():
        # A QSettings of its own each time: the one this fixture might have kept is
        # a deleted C++ object by the time the atexit handler runs.
        settings = QSettings(QSettings.Scope.UserScope, QT_SETTINGS_ORGANISATION)
        if previous is None:
            settings.remove(QT_SIDEBAR_WIDTH_SETTING)
        else:
            settings.setValue(QT_SIDEBAR_WIDTH_SETTING, previous)
        settings.sync()

    # Twice over: once here, and once from atexit in case anything writes the
    # setting after the last fixture has been torn down. The QApplication outlives
    # every fixture (see qapp), so a dialog of its own could still be closing.
    atexit.register(restore)
    yield
    restore()


@pytest.fixture
def qt_sidebar_width(_preserve_qt_sidebar_width):
    """
    Set what Qt has remembered for a file dialog's sidebar width: a width, or None
    for a machine that has never had one.

    The sidebar cases would otherwise pass or fail on whatever this machine last
    happened to keep — including passing for free where it is already wide. Putting
    the user's own value back is _preserve_qt_sidebar_width's business.
    """
    from PyQt6.QtCore import QSettings

    from yellowdog_cli.commander.commander import (
        QT_SETTINGS_ORGANISATION,
        QT_SIDEBAR_WIDTH_SETTING,
    )

    settings = QSettings(QSettings.Scope.UserScope, QT_SETTINGS_ORGANISATION)

    def remember(width: int | None):
        if width is None:
            settings.remove(QT_SIDEBAR_WIDTH_SETTING)
        else:
            settings.setValue(QT_SIDEBAR_WIDTH_SETTING, width)
        settings.sync()

    return remember


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


@pytest.fixture(scope="session")
def run_id() -> str:
    """
    The run-unique suffix every corpus resource name carries.

    Also registers a belt-and-braces atexit sweep, mirroring system_tag's own
    pattern above: a live test's in-process teardown (the 'cleanup' fixture, or a
    try/finally) does not run at all if the process is killed rather than exiting
    normally, and this fixture backs tests against a production account. Sweeping
    every live corpus file with 'yd-remove' is safe to do speculatively --
    remove_resources() (remove.py) reports a resource it can't find and moves on
    to the next one rather than raising, the same tolerance create_resources()
    has for a resource it can't create (see resource_live.KNOWN_PARTIAL_FAILURES)
    -- so a file with nothing left to remove, or nothing ever created from it in
    the first place, costs one wasted subprocess call and nothing else.

    Changes into each file's own parent directory before invoking 'yd-remove',
    the way resource_corpus.load_corpus_file() does for the in-process loader, and
    restores the original directory afterwards regardless of outcome. Without
    this, 'yd-remove' runs as a subprocess from pytest's own working directory
    (the repo root): eight of the ten live corpus files start with
    "local base = import 'lib/base.libsonnet';", which cannot resolve from there
    ("couldn't open import ... no match locally or in the Jsonnet library
    paths"), so the sweep would silently fail to even load those files, let
    alone remove anything from them. yd()/shell() never raises on a non-zero
    exit, so that failure would not surface anywhere -- it would just be a sweep
    that never ran, for 8 of the 10 files it exists to protect. (The two
    exceptions are keyrings.jsonnet and namespace-policy.jsonnet, neither of
    which imports anything; the chdir is applied uniformly to every file
    regardless, so those two just get harmlessly redundant treatment.)
    """
    import atexit
    import os

    import resource_corpus
    import resource_live

    def _remove_everything_this_run_might_have_created() -> None:
        original_cwd = os.getcwd()
        for path in resource_corpus.live_corpus_files():
            # live_corpus_files() already yields absolute paths (CORPUS_DIR is
            # built from Path(__file__).parent); .resolve() here is just belt
            # and braces against that ever changing, not a real relative-path
            # fixup.
            resolved = path.resolve()
            try:
                os.chdir(resolved.parent)
                # '-M' (--match-allowances-by-description): without it,
                # remove_allowance() (remove.py) only warns and removes nothing
                # for an Allowance (see resource_live.LIVE_ONLY_EXCLUSIONS'
                # sibling in test_system_resources.py, _remove_args()) --
                # harmless for every other live corpus file, which has no
                # Allowance to match, but required for allowances.jsonnet to be
                # genuinely swept rather than merely attempted.
                resource_live.yd("yd-remove", "-y", "-M", str(resolved))
            finally:
                os.chdir(original_cwd)

    atexit.register(_remove_everything_this_run_might_have_created)
    return resource_live.run_id()


@pytest.fixture(scope="session")
def live_namespace() -> str:
    """
    Ensure the single test namespace exists, and leave it there: the platform will
    not delete a namespace that has ever been populated. create_namespace treats an
    existing namespace as a warning, so this is idempotent.
    """
    import os

    import resource_corpus
    import resource_live

    result = resource_live.yd(
        "yd-create", str(resource_corpus.CORPUS_DIR / "namespace.jsonnet")
    )
    if result.exit_code != 0:
        # This is the first thing every live test touches, so it is where a
        # missing prerequisite surfaces -- and "could not create the test
        # namespace" on its own sent people looking in the wrong place. Name the
        # likely cause, and show what the command said: creating a namespace
        # prints no secret, so its output is safe to quote.
        missing = [name for name in ("YD_KEY", "YD_SECRET") if not os.environ.get(name)]
        if missing:
            cause = (
                f"{' and '.join(missing)} {'is' if len(missing) == 1 else 'are'} not"
                " set in the environment, which is where the live tests take"
                " credentials from -- and deliberately the only place, so nothing is"
                f" fabricated for a run that touches the platform."
                f" Set {'it' if len(missing) == 1 else 'them'} (plus YD_URL for a"
                " non-default platform) and try again."
            )
        else:
            cause = (
                "Credentials are set in the environment, so this is something else --"
                " the account may lack permission to create a namespace, or the"
                " platform may be unreachable."
            )
        # The CLI reports errors on stderr, so quote that first; stdout carries
        # only progress notes. Creating a namespace prints no secret either way,
        # so quoting the command's output here is safe.
        said = (result.stderr or "").strip() or (result.stdout or "").strip()
        raise AssertionError(
            f"Could not create the test namespace. {cause}\n'yd-create' said:\n{said}"
        )
    return resource_corpus.dummy_variables()["namespace"]


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
