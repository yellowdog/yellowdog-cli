"""
Tests for what Commander remembers between sessions: the window's size and
place, Dark Mode once chosen, and the configuration file last selected. Each
test has a settings file of its own (conftest's commander_dialog_settings),
empty unless it fills it.
"""

import os

import pytest
import qt_guard

qt_guard.require_qt()

import gui_harness
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from yellowdog_cli.commander.commander import (
    MAX_OUTPUT_FONT_SIZE,
    MIN_OUTPUT_FONT_SIZE,
    OUTPUT_FONT_SIZE,
    SETTING_CONFIG_FILE,
    SETTING_DARK_MODE,
    SETTING_OUTPUT_FONT_SIZE,
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
    from yellowdog_cli.commander import commander
    from yellowdog_cli.utils import paths

    launch = tmp_path / "launch"
    launch.mkdir()
    monkeypatch.chdir(launch)
    # The CLI's own default, which conftest otherwise keeps out of GUI tests
    monkeypatch.setattr(commander, "default_config_file", paths.default_config_file)
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


def test_a_config_toml_where_launched_comes_first(
    made, commander_dialog_settings, no_config_of_its_own, tmp_path
):
    # The CLI's default, as the Usage Explorer run on its own chooses
    commander_dialog_settings.setValue(SETTING_CONFIG_FILE, config_file(tmp_path))
    launched = no_config_of_its_own / "config.toml"
    launched.write_text("", encoding="utf-8")
    window = made()
    assert window._config_file is not None
    assert os.path.abspath(window._config_file) == str(launched)
    # Selected, so remembered in its turn
    assert commander_dialog_settings.value(SETTING_CONFIG_FILE) == str(launched)


def test_the_users_own_config_comes_next(
    made, commander_dialog_settings, no_config_of_its_own, tmp_path, monkeypatch
):
    commander_dialog_settings.setValue(SETTING_CONFIG_FILE, config_file(tmp_path))
    home = tmp_path / "xdg"
    users = home / "yellowdog" / "config.toml"
    users.parent.mkdir(parents=True)
    users.write_text("", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    window = made()
    assert window._config_file is not None
    assert os.path.abspath(window._config_file) == str(users)


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
    made, commander_dialog_settings, no_config_of_its_own, tmp_path
):
    # Nothing found at all: nothing is selected, and nothing forgotten
    commander_dialog_settings.setValue(
        SETTING_CONFIG_FILE, str(tmp_path / "gone" / "config.toml")
    )
    assert made()._config_file is None
    assert commander_dialog_settings.value(SETTING_CONFIG_FILE) == str(
        tmp_path / "gone" / "config.toml"
    )


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


# --- The output's text size ------------------------------------------------


def press(window: YellowDogApp, key: Qt.Key, times: int = 1) -> None:
    """
    Cmd/Ctrl + 'key', 'times' over, as the keyboard would send it.
    """
    for _ in range(times):
        QTest.keyClick(window, key, Qt.KeyboardModifier.ControlModifier)
    QApplication.processEvents()


def output_size(window: YellowDogApp) -> int:
    return window.log_output.font().pointSize()


def test_the_output_zooms_in_out_and_back(made, commander_dialog_settings):
    window = made()
    assert output_size(window) == OUTPUT_FONT_SIZE
    press(window, Qt.Key.Key_Equal, 2)
    assert output_size(window) == OUTPUT_FONT_SIZE + 2
    press(window, Qt.Key.Key_Minus, 3)
    assert output_size(window) == OUTPUT_FONT_SIZE - 1
    press(window, Qt.Key.Key_0)
    assert output_size(window) == OUTPUT_FONT_SIZE


def test_the_zoom_stays_within_its_range(made):
    window = made()
    press(window, Qt.Key.Key_Equal, MAX_OUTPUT_FONT_SIZE)
    assert output_size(window) == MAX_OUTPUT_FONT_SIZE
    press(window, Qt.Key.Key_Minus, MAX_OUTPUT_FONT_SIZE)
    assert output_size(window) == MIN_OUTPUT_FONT_SIZE


def test_the_size_is_remembered(made, commander_dialog_settings):
    first = made()
    press(first, Qt.Key.Key_Equal, 3)
    assert commander_dialog_settings.value(SETTING_OUTPUT_FONT_SIZE, type=int) == (
        OUTPUT_FONT_SIZE + 3
    )
    assert output_size(made()) == OUTPUT_FONT_SIZE + 3


def test_a_remembered_size_out_of_range_is_brought_into_it(
    made, commander_dialog_settings
):
    commander_dialog_settings.setValue(SETTING_OUTPUT_FONT_SIZE, 400)
    assert output_size(made()) == MAX_OUTPUT_FONT_SIZE


def test_only_the_output_zooms(made):
    # The file previews and dialog listings keep the shared font
    window = made()
    press(window, Qt.Key.Key_Equal, 4)
    assert window._font.pointSize() == OUTPUT_FONT_SIZE


# --- Resetting the appearance ----------------------------------------------


def remember_an_appearance(settings: QSettings) -> None:
    settings.setValue(SETTING_DARK_MODE, True)
    settings.setValue(SETTING_OUTPUT_FONT_SIZE, OUTPUT_FONT_SIZE + 5)
    settings.setValue(SETTING_WINDOW_GEOMETRY, b"not a real geometry")


def appearance_keys(settings: QSettings) -> set[str]:
    return {
        key
        for key in (
            SETTING_DARK_MODE,
            SETTING_OUTPUT_FONT_SIZE,
            SETTING_WINDOW_GEOMETRY,
        )
        if settings.contains(key)
    }


def test_launching_with_reset_appearance_forgets_it(made, commander_dialog_settings):
    remember_an_appearance(commander_dialog_settings)
    remembered_config = "/somewhere/config.toml"
    commander_dialog_settings.setValue(SETTING_CONFIG_FILE, remembered_config)
    window = made(StartupSettings(reset_appearance=True))
    assert appearance_keys(commander_dialog_settings) == set()
    assert output_size(window) == OUTPUT_FONT_SIZE
    system_dark = window._color_scheme() == Qt.ColorScheme.Dark
    assert window.dark_mode.isChecked() is system_dark
    # Not appearance: the configuration file is still remembered
    assert commander_dialog_settings.value(SETTING_CONFIG_FILE) == remembered_config


def test_without_it_the_appearance_is_kept(made, commander_dialog_settings):
    remember_an_appearance(commander_dialog_settings)
    window = made()
    assert output_size(window) == OUTPUT_FONT_SIZE + 5
    assert window.dark_mode.isChecked()


def test_the_shortcut_resets_the_open_window(made, commander_dialog_settings):
    window = made()
    window.setMinimumSize(window.minimumSizeHint())
    press(window, Qt.Key.Key_Equal, 3)
    window.dark_mode.click()  # a choice, remembered
    window.resize(window.minimumWidth() + 200, window.minimumHeight() + 100)
    QApplication.processEvents()
    assert appearance_keys(commander_dialog_settings) >= {
        SETTING_DARK_MODE,
        SETTING_OUTPUT_FONT_SIZE,
    }

    QTest.keyClick(
        window,
        Qt.Key.Key_0,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    QApplication.processEvents()

    assert appearance_keys(commander_dialog_settings) == set()
    assert output_size(window) == OUTPUT_FONT_SIZE
    assert window.dark_mode.isChecked() is (
        window._color_scheme() == Qt.ColorScheme.Dark
    )
    assert (window.width(), window.height()) == (
        window.minimumWidth(),
        window.minimumHeight(),
    )
    assert "Window appearance reset to its defaults" in window.log_output.toPlainText()


def test_the_shortcut_also_fires_as_the_character_shift_0_types(made):
    # A keyboard may report Cmd/Ctrl+Shift+0 as the ')' it types
    window = made()
    press(window, Qt.Key.Key_Equal, 2)
    QTest.keyClick(window, Qt.Key.Key_ParenRight, Qt.KeyboardModifier.ControlModifier)
    QApplication.processEvents()
    assert output_size(window) == OUTPUT_FONT_SIZE
