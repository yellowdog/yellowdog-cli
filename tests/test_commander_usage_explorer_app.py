"""
The Usage Explorer run on its own (commander/usage_explorer_app.py, `yd
commander --usage-explorer`): the configuration chosen at launch, the base
arguments and directory its runs get, Select..., its log on stderr and its
appearance, with its Dark Mode checkbox. The children are faked as in test_commander_usage_explorer.py.
"""

import qt_guard

qt_guard.require_qt()

import pytest
from PyQt6.QtWidgets import QApplication
from test_commander_usage_explorer import (  # noqa: F401
    BASE_ARGS,
    children,
    fetch,
    is_view,
    settle,
    usage_answer,
)

from yellowdog_cli.commander import usage_explorer_app
from yellowdog_cli.commander.commander import SETTING_DARK_MODE
from yellowdog_cli.commander.launcher import parse_args
from yellowdog_cli.commander.usage_explorer_app import (
    StandaloneExplorer,
    chosen_config_file,
    explorer_title,
)


@pytest.fixture
def project(tmp_path, monkeypatch):
    """
    A launch directory and a project directory beside it holding a config.
    """
    launch = tmp_path / "launch"
    launch.mkdir()
    monkeypatch.chdir(launch)
    config = tmp_path / "project" / "config.toml"
    config.parent.mkdir()
    config.write_text("[common]\n", encoding="utf-8")
    return config


@pytest.fixture
def standalone(qapp, children, project):
    children.answer = usage_answer
    settings = parse_args(
        [
            "--usage-explorer",
            "-c",
            str(project),
            "--property",
            "common.requestTimeout=30",
            "--property",
            "workRequirement.tags=[a, b]",
            "-n",
            "team-render",
        ]
    )
    made = StandaloneExplorer(settings, str(project))
    made.explorer.show()
    settle(made.explorer)
    yield made
    made.explorer.shut_down()
    QApplication.processEvents()


def test_the_config_given_is_used(project):
    asked = []
    assert chosen_config_file(str(project), asked.append) == str(project)
    assert asked == []


def test_the_clis_default_config_is_used_next(project, monkeypatch):
    monkeypatch.chdir(project.parent)
    assert chosen_config_file(None, lambda _: None) == str(project)


def test_with_no_config_the_user_is_asked(project):
    assert chosen_config_file(None, lambda directory: str(project)) == str(project)
    assert chosen_config_file(None, lambda directory: None) is None


def test_runs_are_given_the_config_and_properties_in_its_directory(
    standalone, children, project
):
    explorer = standalone.explorer
    assert explorer.windowTitle() == explorer_title(str(project))
    assert standalone._working_dir() == str(project.parent)
    assert explorer._config_path.isVisible()
    assert explorer._config_path.text() == str(project)
    # Starting on the namespace given, awaiting Fetch Report
    assert explorer._namespace.currentText() == "team-render"
    assert not [a for c, a in children.started if is_view(c, a)]
    fetch(explorer)
    [args] = [a for c, a in children.started if is_view(c, a)]
    assert args[:7] == [
        "-c",
        "config.toml",
        "--nf",
        "-q",
        "--json",
        "--property=common.requestTimeout=30",
        "--property=workRequirement.tags=[a, b]",
    ]
    assert args[args.index("-n") + 1] == "team-render"


def test_select_resets_the_explorer_for_another_config(
    standalone, children, project, monkeypatch
):
    explorer = standalone.explorer
    fetch(explorer)
    other = project.parent / "other" / "staging.toml"
    other.parent.mkdir()
    other.write_text("[common]\n", encoding="utf-8")
    asked = []

    def select_file(**kwargs):
        asked.append(kwargs)
        return str(other)

    monkeypatch.setattr(standalone._dialogs, "select_file", select_file)
    runs = len([c for c, a in children.started if is_view(c, a)])
    explorer._select_config.click()
    settle(explorer)
    assert asked[0]["directory"] == str(project.parent)
    assert explorer.windowTitle() == explorer_title(str(other))
    assert explorer._config_path.text() == str(other)
    assert explorer._model.rowCount() == 0
    assert len([c for c, a in children.started if is_view(c, a)]) == runs
    fetch(explorer)
    args = [a for c, a in children.started if is_view(c, a)][-1]
    assert args[:2] == ["-c", "staging.toml"]
    assert standalone._working_dir() == str(other.parent)


def test_select_dismissed_changes_nothing(standalone, project, monkeypatch):
    monkeypatch.setattr(standalone._dialogs, "select_file", lambda **_: None)
    standalone.explorer._select_config.click()
    assert standalone.config_file == str(project)


def test_nothing_is_printed_to_the_terminal(standalone, capsys):
    capsys.readouterr()
    standalone.explorer.logged.emit("Fetched the usage report: yd usage ...")
    fetch(standalone.explorer)
    printed = capsys.readouterr()
    assert (printed.out, printed.err) == ("", "")


def test_dark_mode_is_commanders_remembered_choice(
    qapp, children, project, commander_dialog_settings, monkeypatch
):
    children.answer = usage_answer
    commander_dialog_settings.setValue(SETTING_DARK_MODE, True)
    applied: list[bool] = []
    monkeypatch.setattr(
        usage_explorer_app, "apply_application_appearance", applied.append
    )
    made = StandaloneExplorer(parse_args(["--usage-explorer"]), str(project))
    try:
        assert made.explorer._dark
        assert made.explorer._dark_mode.isChecked()
        assert applied == [True]
    finally:
        made.explorer.shut_down()
        QApplication.processEvents()


def test_dark_mode_ticked_switches_and_is_remembered(
    standalone, commander_dialog_settings, monkeypatch
):
    applied: list[bool] = []
    monkeypatch.setattr(
        usage_explorer_app, "apply_application_appearance", applied.append
    )
    box = standalone.explorer._dark_mode
    assert box.isVisible()
    box.setChecked(False)
    box.click()
    assert applied == [True]
    assert standalone.explorer._dark
    assert commander_dialog_settings.value(SETTING_DARK_MODE, type=bool) is True
    box.click()
    assert applied == [True, False]
    assert not standalone.explorer._dark
    assert commander_dialog_settings.value(SETTING_DARK_MODE, type=bool) is False


def test_inside_commander_the_configuration_row_is_hidden(qapp, children, tmp_path):
    from yellowdog_cli.commander.usage_explorer import UsageExplorer

    children.answer = usage_answer
    explorer = UsageExplorer(
        "Usage Explorer",
        lambda: str(tmp_path),
        lambda: list(BASE_ARGS),
        qapp.font(),
        False,
    )
    try:
        explorer.show()
        assert not explorer._config_path.isVisible()
        assert not explorer._select_config.isVisible()
        assert not explorer._dark_mode.isVisible()
    finally:
        explorer.shut_down()
        QApplication.processEvents()
