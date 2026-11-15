"""
Tests for what Commander remembers between sessions: the window's size and
place, Dark Mode once chosen, and the configuration file last selected. Each
test has a settings file of its own (conftest's commander_dialog_settings),
empty unless it fills it.
"""

import pytest
import qt_guard

qt_guard.require_qt()

import gui_harness
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QApplication

from yellowdog_cli.commander.commander import (
    SETTING_CONFIG_FILE,
    SETTING_DARK_MODE,
    SETTING_WINDOW_GEOMETRY,
    YellowDogApp,
)
from yellowdog_cli.commander.startup import StartupSettings


@pytest.fixture
def made(qapp):
    """
    Build windows, closed and shut down afterwards; each is shown, and its
    deferred configuration selection has run.
    """
    windows: list[YellowDogApp] = []

    def make(settings: StartupSettings | None = None) -> YellowDogApp:
        window = YellowDogApp(settings)
        gui_harness.shown(window)
        QApplication.processEvents()
        windows.append(window)
        return window

    yield make
    for window in windows:
        # Dark Mode is the application's, so none is left to a later test
        window._dark_mode_action(Qt.CheckState.Unchecked)
        window.shutdown()
        window.close()


@pytest.fixture
def no_config_of_its_own(tmp_path, monkeypatch):
    """
    Launched where the CLI finds no configuration of its own: no config.toml
    in the directory, and none of the user's (conftest empties
    XDG_CONFIG_HOME for the session).
    """
    launch = tmp_path / "launch"
    launch.mkdir()
    monkeypatch.chdir(launch)
    return launch


def config_file(tmp_path, name: str = "config.toml") -> str:
    path = tmp_path / "project" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text('[common]\nnamespace = "image-processing"\n', encoding="utf-8")
    return str(path)


# --- Dark Mode -------------------------------------------------------------


def test_never_chosen_dark_mode_follows_the_system(made, commander_dialog_settings):
    window = made()
    system_dark = window._color_scheme() == Qt.ColorScheme.Dark
    assert window.dark_mode.isChecked() is system_dark
    # Starting from the system's appearance is not a choice to remember
    assert not commander_dialog_settings.contains(SETTING_DARK_MODE)


def test_dark_mode_as_last_chosen(made, commander_dialog_settings: QSettings):
    commander_dialog_settings.setValue(SETTING_DARK_MODE, True)
    assert made().dark_mode.isChecked()


def test_choosing_dark_mode_is_remembered(made, commander_dialog_settings):
    window = made()
    window.dark_mode.click()
    chosen = window.dark_mode.isChecked()
    assert commander_dialog_settings.value(SETTING_DARK_MODE, type=bool) is chosen
    window.dark_mode.click()
    assert commander_dialog_settings.value(SETTING_DARK_MODE, type=bool) is not chosen


# --- The configuration file ------------------------------------------------


def test_the_last_configuration_file_is_selected_again(
    made, commander_dialog_settings, no_config_of_its_own, tmp_path
):
    remembered = config_file(tmp_path)
    commander_dialog_settings.setValue(SETTING_CONFIG_FILE, remembered)
    window = made()
    assert window._config_file is not None
    assert window._config_file.endswith("config.toml")
    assert "Selected configuration file" in window.log_output.toPlainText()


def test_a_file_named_at_launch_wins(
    made, commander_dialog_settings, no_config_of_its_own, tmp_path
):
    commander_dialog_settings.setValue(SETTING_CONFIG_FILE, config_file(tmp_path))
    named = config_file(tmp_path, "other.toml")
    window = made(StartupSettings(config_file=named))
    assert window._config_file is not None
    assert window._config_file.endswith("other.toml")


def test_not_over_a_config_toml_where_launched(
    made, commander_dialog_settings, no_config_of_its_own, tmp_path
):
    # Commander's commands use it when none is selected; a remembered file
    # would silently replace it
    commander_dialog_settings.setValue(SETTING_CONFIG_FILE, config_file(tmp_path))
    (no_config_of_its_own / "config.toml").write_text("", encoding="utf-8")
    assert made()._config_file is None


def test_not_once_it_is_gone(
    made, commander_dialog_settings, no_config_of_its_own, tmp_path
):
    commander_dialog_settings.setValue(
        SETTING_CONFIG_FILE, str(tmp_path / "gone" / "config.toml")
    )
    assert made()._config_file is None


def test_selecting_remembers_and_deselecting_forgets(
    made, commander_dialog_settings, no_config_of_its_own, tmp_path
):
    chosen = config_file(tmp_path)
    window = made()
    window._set_config_file(chosen)
    assert commander_dialog_settings.value(SETTING_CONFIG_FILE) == chosen
    window._deselect_config_file()
    assert not commander_dialog_settings.contains(SETTING_CONFIG_FILE)


def test_starting_with_nothing_selected_forgets_nothing(
    made, commander_dialog_settings, tmp_path, monkeypatch
):
    # Launched where the CLI has a configuration of its own, nothing is
    # selected, but the remembered file is kept for a launch elsewhere
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text("", encoding="utf-8")
    remembered = config_file(tmp_path)
    commander_dialog_settings.setValue(SETTING_CONFIG_FILE, remembered)
    assert made()._config_file is None
    assert commander_dialog_settings.value(SETTING_CONFIG_FILE) == remembered


# --- The window ------------------------------------------------------------


def test_the_window_comes_back_as_it_was_left(
    made, commander_dialog_settings, monkeypatch
):
    # What Commander does: the geometry saved at shutdown is the one handed
    # back to Qt. Qt then keeps it on a screen and no smaller than the window's
    # minimum, which the offscreen platform's small screen makes untestable as
    # sizes: it clamps a restored window to the screen, as resize() does not
    first = made()
    first.resize(first.minimumWidth() + 120, first.minimumHeight() + 80)
    QApplication.processEvents()
    first.shutdown()
    saved = commander_dialog_settings.value(SETTING_WINDOW_GEOMETRY)
    assert saved == first.saveGeometry()

    second = made()
    restored = []
    monkeypatch.setattr(second, "restoreGeometry", restored.append)
    second.restore_window_geometry()
    assert restored == [saved]


def test_with_nothing_remembered_the_window_is_left_alone(made):
    window = made()
    before = window.size()
    window.restore_window_geometry()
    assert window.size() == before
