"""
Smoke tests that the Commander package data (UI file + images) is present and
resolvable via the installed package. Guards against a broken package-data
declaration.
"""

from importlib.resources import files


def test_commander_ui_resource_exists():
    ui = files("yellowdog_cli.commander").joinpath("commander.ui")
    assert ui.is_file()


def test_commander_icon_resource_exists():
    icon = files("yellowdog_cli.commander").joinpath("images").joinpath("IconApi.ico")
    assert icon.is_file()
