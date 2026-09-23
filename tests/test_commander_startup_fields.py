"""
Tests for applying yd-commander's command-line options to the window: the
fields they fill, the definition files they select, and that the first config
discovery is the only one and already sees them.
"""

from os.path import join, realpath

import pytest
import qt_guard

qt_guard.require_qt()

from PyQt6.QtWidgets import QApplication

from yellowdog_cli.commander.commander import SELECTED_WR_PREFIX, YellowDogApp
from yellowdog_cli.commander.config_discovery import ConfigDiscovery
from yellowdog_cli.commander.startup import StartupSettings


@pytest.fixture
def make_window(qapp):
    windows: list[YellowDogApp] = []

    def make(settings: StartupSettings) -> YellowDogApp:
        window = YellowDogApp(settings)
        windows.append(window)
        return window

    yield make
    for window in windows:
        window.close()


def test_the_text_fields_are_filled(make_window):
    window = make_window(
        StartupSettings(
            namespace="ns",
            tag="tag",
            name_glob="proj-*",
            object_path="tag/out*",
            variables=("a=1", "b=2"),
        )
    )
    assert window.namespace_override.toPlainText() == "ns"
    assert window.tag_override.toPlainText() == "tag"
    assert window.name_glob_override.toPlainText() == "proj-*"
    assert window.object_path_override.toPlainText() == "tag/out*"
    assert window._namespace_tag_and_user_vars() == [
        "-n",
        "ns",
        "-t",
        "tag",
        "-v",
        "a=1",
        "-v",
        "b=2",
    ]
    assert window._object_path() == "tag/out*"
    assert window._name_glob_args() == ["proj-*"]


def test_the_variables_survive_a_later_edit(make_window):
    # Joined with spaces: joined with newlines, the edit-box handler would
    # delete them on the first keystroke and fuse the variables together
    window = make_window(StartupSettings(variables=("a=1", "b=2")))
    # Typed where a click at the end of the text would put the cursor
    window.user_variables.insertPlainText(" c=3")
    assert window.user_variables.toPlainText().split() == ["a=1", "b=2", "c=3"]


def test_the_first_discovery_is_the_only_one_and_sees_the_fields(
    make_window, monkeypatch
):
    seen: list[tuple[ConfigDiscovery, list[str]]] = []
    monkeypatch.setattr(
        ConfigDiscovery,
        "_parse_yd_config",
        lambda self, quiet=False, timeout_ms=None: (
            seen.append((self, self._override_args())) or False
        ),
    )
    window = make_window(StartupSettings(tag="tag", variables=("a=1",)))
    QApplication.processEvents()  # runs the deferred _set_config_file
    # Filtered to this window: an earlier test's window, closed but not yet
    # deleted, can have its own deferred parse still to run
    assert [args for d, args in seen if d is window._discovery] == [
        ["-t", "tag", "-v", "a=1"]
    ]
    # Filled after the connections, the user-variables box would have started
    # its reparse timer and run a second parse 600ms later
    assert not window._discovery._user_vars_reparse_timer.isActive()


def test_the_definition_files_are_selected(make_window, tmp_path):
    wr = str(tmp_path / "wr.json")
    wp = str(tmp_path / "wp.jsonnet")
    window = make_window(StartupSettings(wr_file=wr, wp_file=wp))
    assert window._wr_file == wr
    assert window._wp_file == wp
    assert window.select_work_requirement.text().startswith(SELECTED_WR_PREFIX)
    assert window.select_work_requirement.toolTip() == wr
    assert window.select_worker_pool.toolTip() == wp


def test_a_selected_work_requirement_reaches_yd_submit(
    make_window, monkeypatch, tmp_path
):
    # Resolved the way the child process resolves it, from the config file's
    # directory, which is not the directory the definition is in
    (tmp_path / "configs").mkdir()
    config = tmp_path / "configs" / "config.toml"
    config.write_text("")
    wr = tmp_path / "wr.json"
    wr.write_text("{}")
    window = make_window(StartupSettings(config_file=str(config), wr_file=str(wr)))
    QApplication.processEvents()  # selects the config file

    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        window,
        "_run_command_in_subprocess",
        lambda command, args, **kwargs: calls.append((command, args)),
    )
    window._submit_work_requirement_action()
    [(command, args)] = calls
    assert command == "yd-submit"
    handed_over = args[args.index("-r") + 1]
    assert realpath(join(window._working_dir(), handed_over)) == realpath(wr)
