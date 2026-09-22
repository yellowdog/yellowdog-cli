"""
Tests for Commander's namespace / tag discovery — the 'yd-variables' run behind the
placeholder text — and for what happens when it fails.

Written for a Windows incident: launched with a configuration file, the
placeholders stayed blank for the whole session, and the next launch was fine.
The first 'yd-*' invocation of a session can take longer than the 10s budget to
start on Windows (interpreter start, SDK imports, a virus scan), and nothing
retried afterwards, so one slow start cost the placeholders until a restart.

These drive the real _parse_yd_config, with _yd_variables_command() overridden to run
a Python one-liner instead of 'yd-variables' — a real child process with a real exit
code, so the timeout, non-zero-exit, failed-to-start and bad-JSON branches are
exercised as they are in production rather than stubbed past.
"""

import sys
from time import monotonic

import pytest
import qt_guard

qt_guard.require_qt()

from PyQt6.QtCore import QEventLoop
from PyQt6.QtWidgets import QApplication

from yellowdog_cli.commander import commander as commander_module
from yellowdog_cli.commander.commander import YellowDogApp
from yellowdog_cli.utils.settings import MISSING_CONFIG_DATA

# These are the tests discovery itself is the subject of, so they opt out of
# conftest's stub of _parse_yd_config. No 'yd-variables' is spawned all the same:
# _yd_variables_command is overridden to run a Python one-liner instead.
pytestmark = pytest.mark.real_config_parse

# Long enough that a slow CI node does not mistake a working retry for a stuck
# one; short enough that a genuinely stuck test fails rather than hanging.
SETTLE_TIMEOUT_S = 10.0


@pytest.fixture
def win(qapp, monkeypatch):
    """
    A window whose startup discovery has already happened.

    Constructing one defers _set_config_file with singleShot(0), and that
    discovers as soon as any event loop spins — including the nested loop a
    test's own attempt blocks in, which is how the startup attempt otherwise
    turns up in the middle of a test as a second attempt nobody asked for. So it
    is given a harmless command and let run here, before anything is counted.
    """
    monkeypatch.setattr(
        YellowDogApp,
        "_yd_variables_command",
        lambda self: (sys.executable, ["-c", "print('{}')"]),
    )
    window = YellowDogApp()
    deadline = monotonic() + SETTLE_TIMEOUT_S
    while window._config_parse_invalid and monotonic() < deadline:
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
    assert not window._config_parse_invalid, "the startup discovery never ran"

    window._invalidate_config_parse()
    window.log_output.setPlainText("")
    yield window
    window.close()


def python_commands(win, monkeypatch, *scripts: str) -> list[int | None]:
    """
    Make each successive discovery attempt run the next of 'scripts' as Python,
    instead of running 'yd-variables'. Returns the list the timeout of each attempt is
    recorded in, so a test can see what budget each attempt was given.

    The last script is reused if there are more attempts than scripts, so a test
    asserting 'this is not retried' fails by recording an extra attempt rather
    than by dying on an IndexError.
    """
    timeouts: list[int | None] = []
    remaining = list(scripts)

    def command():
        script = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return sys.executable, ["-c", script]

    real_parse = win._parse_yd_config

    def parse(quiet=False, timeout_ms=None):
        timeouts.append(timeout_ms)
        return real_parse(quiet=quiet, timeout_ms=timeout_ms)

    monkeypatch.setattr(win, "_yd_variables_command", command)
    monkeypatch.setattr(win, "_parse_yd_config", parse)
    return timeouts


PRINTS_CONFIG = 'print(\'{"namespace": "yd-demo", "tag": "my-tag"}\')'
NEVER_FINISHES = "import time; time.sleep(60)"
EXITS_NON_ZERO = "import sys; sys.stderr.write('bad config\\n'); sys.exit(3)"
PRINTS_RUBBISH = "print('not json at all')"
# What 'yd-variables --nc' says when the environment holds no YellowDog credentials:
# load_common_config() raises KeyError('key') and the CLI exits 1. Built from the
# CLI's own constant, so renaming the message cannot leave this passing against
# wording Commander no longer recognises.
NO_CREDENTIALS_STDERR = f"2026-01-01 00:00:00 : Error: {MISSING_CONFIG_DATA}: 'key'"
NO_CREDENTIALS = (
    f"import sys; sys.stderr.write({NO_CREDENTIALS_STDERR!r} + chr(10)); sys.exit(1)"
)


def settle(win, attempts: list, expected: int) -> None:
    """
    Run the event loop until the given number of discovery attempts have been
    made, so a retry scheduled on a timer actually gets to run. Fails rather
    than hanging if it never happens.
    """
    deadline = monotonic() + SETTLE_TIMEOUT_S
    while len(attempts) < expected and monotonic() < deadline:
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
    assert len(attempts) == expected, (
        f"expected {expected} discovery attempts, saw {len(attempts)}: {attempts}"
    )


def test_discovery_fills_in_the_placeholders(win, monkeypatch):
    python_commands(win, monkeypatch, PRINTS_CONFIG)

    win._reparse_placeholders()

    assert win.namespace_override.placeholderText() == "yd-demo"
    assert win.tag_override.placeholderText() == "my-tag"
    assert win.object_path_override.placeholderText() == "my-tag*"


def test_a_timed_out_discovery_is_retried_with_a_longer_budget(win, monkeypatch):
    # The incident: the first attempt does not finish in time. The retry is what
    # a user got by restarting Commander, and should not need a restart.
    monkeypatch.setattr(commander_module, "CONFIG_PARSE_TIMEOUT_MS", 300)
    monkeypatch.setattr(commander_module, "CONFIG_PARSE_RETRY_TIMEOUT_MS", 9000)
    monkeypatch.setattr(commander_module, "CONFIG_PARSE_RETRY_DELAY_MS", 0)
    attempts = python_commands(win, monkeypatch, NEVER_FINISHES, PRINTS_CONFIG)

    win._reparse_placeholders()
    settle(win, attempts, 2)

    assert attempts == [None, 9000], "the retry should get the longer budget"
    assert win.namespace_override.placeholderText() == "yd-demo"
    assert win.tag_override.placeholderText() == "my-tag"
    log = win.log_output.toPlainText()
    assert "Timed out" in log
    assert "Retrying" in log


def test_a_retry_that_also_times_out_is_not_retried_again(win, monkeypatch):
    monkeypatch.setattr(commander_module, "CONFIG_PARSE_TIMEOUT_MS", 300)
    monkeypatch.setattr(commander_module, "CONFIG_PARSE_RETRY_TIMEOUT_MS", 300)
    monkeypatch.setattr(commander_module, "CONFIG_PARSE_RETRY_DELAY_MS", 0)
    attempts = python_commands(win, monkeypatch, NEVER_FINISHES)

    win._reparse_placeholders()
    settle(win, attempts, 2)
    # Give a third attempt every chance to appear before concluding there is none.
    deadline = monotonic() + 1.0
    while monotonic() < deadline:
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)

    assert len(attempts) == 2, "one retry, not a loop"
    assert win.namespace_override.placeholderText() == ""


def test_a_new_configuration_file_gets_a_fresh_retry(win, monkeypatch, tmp_path):
    # The retry budget is per parse, not per session: selecting another config
    # file must not inherit the exhausted budget of the previous one.
    monkeypatch.setattr(commander_module, "CONFIG_PARSE_TIMEOUT_MS", 300)
    monkeypatch.setattr(commander_module, "CONFIG_PARSE_RETRY_TIMEOUT_MS", 300)
    monkeypatch.setattr(commander_module, "CONFIG_PARSE_RETRY_DELAY_MS", 0)
    attempts = python_commands(win, monkeypatch, NEVER_FINISHES)

    win._reparse_placeholders()
    settle(win, attempts, 2)

    win._invalidate_config_parse()
    win._reparse_placeholders()
    settle(win, attempts, 4)


def test_a_non_zero_exit_is_reported_even_though_the_parse_is_quiet(win, monkeypatch):
    # This was silent: the placeholders stayed blank with nothing in the output
    # window to say why, which is what made the incident undiagnosable.
    attempts = python_commands(win, monkeypatch, EXITS_NON_ZERO)

    win._reparse_placeholders()

    log = win.log_output.toPlainText()
    assert "Exit 3" in log
    assert "bad config" in log
    assert len(attempts) == 1, "a bad configuration will not fix itself; no retry"


def test_a_command_that_cannot_be_started_is_reported(win, monkeypatch):
    monkeypatch.setattr(
        win, "_yd_variables_command", lambda: ("yd-variables-does-not-exist", [])
    )

    assert win._parse_yd_config(quiet=True) is False

    assert "yd-variables" in win.log_output.toPlainText()


def test_output_that_is_not_json_is_reported(win, monkeypatch):
    python_commands(win, monkeypatch, PRINTS_RUBBISH)

    win._reparse_placeholders()

    assert "Error reading config variables" in win.log_output.toPlainText()


def test_the_same_failure_is_not_reported_over_and_over(win, monkeypatch):
    # The user-variables box reparses 600ms after every edit, so a broken config
    # would otherwise fill the output window with one repeated line.
    #
    # No _invalidate_config_parse() between the two, deliberately: a failed parse
    # leaves _config_parse_invalid set, so the reparse this stands in for runs
    # again without one — and the box's reparse does not call it in any case.
    # Calling it here reset what the suppression compares against, which is the
    # behaviour a configuration file being reselected needs and this one must not
    # have.
    python_commands(win, monkeypatch, EXITS_NON_ZERO)

    win._reparse_placeholders()
    win._reparse_placeholders()

    assert win.log_output.toPlainText().count("Exit 3") == 1


def test_a_failure_after_a_success_is_reported_again(win, monkeypatch):
    # Suppressing repeats must not suppress a recurrence: the config being fixed
    # and broken again is two things the user needs to see.
    python_commands(win, monkeypatch, EXITS_NON_ZERO)
    win._reparse_placeholders()
    win._invalidate_config_parse()

    python_commands(win, monkeypatch, PRINTS_CONFIG)
    win._reparse_placeholders()
    win._invalidate_config_parse()

    python_commands(win, monkeypatch, EXITS_NON_ZERO)
    win._reparse_placeholders()

    assert win.log_output.toPlainText().count("Exit 3") == 2


def test_nothing_is_reported_or_retried_while_shutting_down(win, monkeypatch):
    monkeypatch.setattr(commander_module, "CONFIG_PARSE_TIMEOUT_MS", 300)
    monkeypatch.setattr(commander_module, "CONFIG_PARSE_RETRY_DELAY_MS", 0)
    attempts = python_commands(win, monkeypatch, NEVER_FINISHES)
    win._shutting_down = True

    win._reparse_placeholders()
    deadline = monotonic() + 1.0
    while monotonic() < deadline:
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)

    assert len(attempts) == 1, "the widgets are going away; do not retry into them"
    assert win.log_output.toPlainText() == ""


# --- The paths a discovery is actually started from ---------------------------
# Each of these has its own call into discovery, and the incident was on the one
# that runs at startup — so a retry only wired into one of them is no retry.


def test_selecting_a_configuration_file_retries_a_timed_out_discovery(
    win, monkeypatch, tmp_path
):
    # This is the incident itself: Commander launched with a configuration file,
    # the first 'yd-variables' too slow to finish, the placeholders blank until the
    # next launch. _set_config_file is the path a supplied file arrives by.
    monkeypatch.setattr(commander_module, "CONFIG_PARSE_TIMEOUT_MS", 300)
    monkeypatch.setattr(commander_module, "CONFIG_PARSE_RETRY_TIMEOUT_MS", 9000)
    monkeypatch.setattr(commander_module, "CONFIG_PARSE_RETRY_DELAY_MS", 0)
    config_file = tmp_path / "config.toml"
    config_file.write_text('[common]\nnamespace = "yd-demo"\ntag = "my-tag"\n')
    attempts = python_commands(win, monkeypatch, NEVER_FINISHES, PRINTS_CONFIG)

    win._set_config_file(str(config_file))
    settle(win, attempts, 2)

    assert win.namespace_override.placeholderText() == "yd-demo"
    assert win.tag_override.placeholderText() == "my-tag"


def test_deselecting_a_configuration_file_clears_the_placeholders(win, monkeypatch):
    attempts = python_commands(win, monkeypatch, EXITS_NON_ZERO)
    win._set_placeholders("yd-demo", "my-tag")

    win._set_config_file(None)

    assert win.namespace_override.placeholderText() == ""
    assert win.tag_override.placeholderText() == ""
    assert len(attempts) == 1


def test_a_configuration_file_changing_on_disk_retries_a_timed_out_discovery(
    win, monkeypatch, tmp_path
):
    monkeypatch.setattr(commander_module, "CONFIG_PARSE_TIMEOUT_MS", 300)
    monkeypatch.setattr(commander_module, "CONFIG_PARSE_RETRY_TIMEOUT_MS", 9000)
    monkeypatch.setattr(commander_module, "CONFIG_PARSE_RETRY_DELAY_MS", 0)
    config_file = tmp_path / "config.toml"
    config_file.write_text('[common]\nnamespace = "yd-demo"\n')
    win._config_file = str(config_file)
    attempts = python_commands(win, monkeypatch, NEVER_FINISHES, PRINTS_CONFIG)

    win._on_config_file_changed(str(config_file))
    settle(win, attempts, 2)

    assert win.tag_override.placeholderText() == "my-tag"


# --- Discovery while a user-defined variable is being typed -------------------
# The user-variables box reparses 600ms after every keystroke, and every
# variable is typed through states that are not yet 'name=value' — 'instances'
# on the way to 'instances=3'. Handed one of those, 'yd-variables' exits 1 with
# "Error in variable substitution 'instances'", so simply adding a variable
# reported an error the user had not made.


def type_user_variables(win, text: str) -> None:
    """
    Put text in the user-variables box the way typing does, and let the
    debounced reparse it schedules run. The real timer and the real connection,
    with the debounce interval taken down to nothing so the test does not wait
    it out.
    """
    win._user_vars_reparse_timer.setInterval(0)
    win.user_variables.setPlainText(text)
    assert win._user_vars_reparse_timer.isActive(), "editing should schedule a reparse"
    deadline = monotonic() + SETTLE_TIMEOUT_S
    while win._user_vars_reparse_timer.isActive() and monotonic() < deadline:
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
    assert not win._user_vars_reparse_timer.isActive(), "the reparse never ran"
    QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)


def test_a_half_typed_variable_does_not_run_discovery(win, monkeypatch):
    attempts = python_commands(win, monkeypatch, EXITS_NON_ZERO)

    type_user_variables(win, "instances")

    assert attempts == [], "'yd-variables' cannot resolve 'instances'; do not ask it to"
    assert win.log_output.toPlainText() == "", "the user has not made a mistake yet"


def test_a_completed_variable_runs_discovery(win, monkeypatch):
    attempts = python_commands(win, monkeypatch, PRINTS_CONFIG)

    type_user_variables(win, "instances=3")

    assert len(attempts) == 1
    assert win.namespace_override.placeholderText() == "yd-demo"


def test_a_half_typed_second_variable_does_not_run_discovery(win, monkeypatch):
    attempts = python_commands(win, monkeypatch, EXITS_NON_ZERO)

    type_user_variables(win, "instances=3 nodes")

    assert attempts == [], "one incomplete variable is enough to hold the reparse"


def test_a_variable_with_an_empty_name_does_not_run_discovery(win, monkeypatch):
    # The CLI rejects this too, so there is nothing to be learnt from running it
    # 600ms after a keystroke. The user hears about it when they run a command.
    attempts = python_commands(win, monkeypatch, EXITS_NON_ZERO)

    type_user_variables(win, "=3")

    assert attempts == []


def test_an_empty_variables_box_runs_discovery(win, monkeypatch):
    attempts = python_commands(win, monkeypatch, PRINTS_CONFIG)
    # Filled in and then emptied again, since setting the text of an already
    # empty box emits nothing and so schedules no reparse to observe.
    win.user_variables.setPlainText("instances=3")
    win._user_vars_reparse_timer.stop()

    type_user_variables(win, "")

    assert len(attempts) == 1, "nothing typed is not the same as something incomplete"


# --- 'Nothing is configured' is not a failure ---------------------------------
# With no configuration file selected, 'yd-variables' is run with '--nc' and has only
# the environment to work from. An environment with no YellowDog credentials
# makes it exit 1 before it can resolve anything, and that was reported as an
# error — at startup, and again on every Deselect, to a user who had done
# nothing. It alone is suppressed. Discovery still runs, because credentials and
# namespace/tag in YD_* variables with no configuration file at all is a
# supported way to drive Commander, and everything else it can say is still
# worth hearing.


def test_no_credentials_and_no_configuration_file_reports_nothing(win, monkeypatch):
    assert win._config_file is None
    python_commands(win, monkeypatch, NO_CREDENTIALS)

    win._reparse_placeholders()

    assert win.log_output.toPlainText() == ""
    assert win.namespace_override.placeholderText() == ""


def test_starting_with_no_credentials_reports_nothing(qapp, monkeypatch):
    # The report this exists for arrived before the user had touched anything.
    monkeypatch.setattr(
        YellowDogApp,
        "_yd_variables_command",
        lambda self: (sys.executable, ["-c", NO_CREDENTIALS]),
    )
    window = YellowDogApp()
    try:
        deadline = monotonic() + SETTLE_TIMEOUT_S
        while window._config_parse_invalid and monotonic() < deadline:
            QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)

        assert window.log_output.toPlainText() == ""
    finally:
        window.close()


def test_the_environment_alone_still_fills_in_the_placeholders(win, monkeypatch):
    # The case the suppression must not cost: no configuration file, everything
    # in YD_* variables, the definition files nominated by hand.
    assert win._config_file is None
    python_commands(win, monkeypatch, PRINTS_CONFIG)

    win._reparse_placeholders()

    assert win.namespace_override.placeholderText() == "yd-demo"
    assert win.tag_override.placeholderText() == "my-tag"
    assert win.object_path_override.placeholderText() == "my-tag*"


def test_any_other_failure_is_still_reported_with_nothing_selected(win, monkeypatch):
    # Only 'nothing is configured' is suppressed, not discovery's failures in
    # general: running from the environment alone is supported, so its failures
    # are as worth seeing as any other.
    python_commands(win, monkeypatch, EXITS_NON_ZERO)

    win._reparse_placeholders()

    assert "Exit 3" in win.log_output.toPlainText()


def test_a_missing_configuration_is_reported_when_a_file_is_selected(
    win, monkeypatch, tmp_path
):
    # With a file selected the same message means something else entirely: the
    # file the user chose cannot be used. That is theirs to see.
    config_file = tmp_path / "config.toml"
    config_file.write_text('[common]\nnamespace = "yd-demo"\n')
    python_commands(win, monkeypatch, NO_CREDENTIALS)

    win._set_config_file(str(config_file))

    assert MISSING_CONFIG_DATA in win.log_output.toPlainText()


def test_a_suppressed_failure_does_not_mask_the_next_one(win, monkeypatch, tmp_path):
    # _report_discovery_failure suppresses a repeat of the message it said last,
    # and a suppressed failure never becomes that message — so without the reset
    # in _invalidate_config_parse the second 'Exit 3' here looks like a repeat of
    # the first and is swallowed, though the user selected the file again in
    # between.
    config_file = tmp_path / "config.toml"
    config_file.write_text('[common]\nnamespace = "yd-demo"\n')
    python_commands(win, monkeypatch, EXITS_NON_ZERO, NO_CREDENTIALS, EXITS_NON_ZERO)

    win._set_config_file(str(config_file))  # selected: reported
    win._set_config_file(None)  # deselected: suppressed
    win._set_config_file(str(config_file))  # selected again: reported again

    assert win.log_output.toPlainText().count("Exit 3") == 2


def test_deselecting_a_configuration_file_clears_the_discovered_tag(win, monkeypatch):
    # Not just the placeholders: _object_path() builds the default download and
    # delete path out of the tag, so a stale one is a path acted on.
    python_commands(win, monkeypatch, PRINTS_CONFIG, NO_CREDENTIALS)
    win._set_config_file(None)  # a no-op selection-wise, to run the first script
    assert win._tag == "my-tag"

    win._set_config_file(None)

    assert win._namespace is None
    assert win._tag is None
    assert win._object_path() is None
