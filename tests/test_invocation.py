"""
utils/invocation.py: the command the dispatcher selected, the prog it is
shown as, and the name a command was invoked by.
"""

import pytest

from yellowdog_cli.utils import invocation


@pytest.fixture(autouse=True)
def _no_selection(monkeypatch):
    monkeypatch.setattr(invocation, "_SELECTED", None)


def test_nothing_selected_gives_the_default_prog():
    assert invocation.selected() is None
    assert invocation.selected_prog("yd-help") == "yd-help"


def test_the_selection_gives_its_prog():
    invocation.select_command("yd-help", "yd help")
    assert invocation.selected() == ("yd-help", "yd help")
    assert invocation.selected_prog("yd-help") == "yd help"


@pytest.mark.parametrize(
    "argv0, name",
    [
        ("yd", "yd"),
        ("/usr/local/bin/yd", "yd"),
        (r"C:\Python\Scripts\yd.exe", "yd"),
        (r"C:\Python\Scripts\yd-script.py", "yd"),
        ("/x/yellowdog_cli/submit.py", "submit.py"),
    ],
)
def test_invoked_name(argv0, name):
    assert invocation.invoked_name(argv0) == name
