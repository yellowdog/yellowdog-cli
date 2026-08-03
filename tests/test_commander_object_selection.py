"""
Tests for selecting which objects a Commander deletion removes: parsing the
enumeration, rendering object rows, and the paths that reach yd-delete.
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidget

from yellowdog_cli.commander.commander import (
    Confirmation,
    ObjectSummary,
    YellowDogApp,
    object_rows,
    parse_object_summaries,
)


@pytest.fixture
def window(qapp):
    return YellowDogApp()


def objects() -> list[ObjectSummary]:
    return [
        ObjectSummary(path="S3:b/pfx/pyex-001", name="pyex-001", is_dir=False),
        ObjectSummary(path="S3:b/pfx/pyex-logs", name="pyex-logs/", is_dir=True),
    ]


def test_parse_reads_path_name_and_isdir():
    parsed = [
        {"name": "pyex-001", "path": "S3:b/pfx/pyex-001", "isDir": False},
        {"name": "pyex-logs/", "path": "S3:b/pfx/pyex-logs", "isDir": True},
    ]
    assert parse_object_summaries(parsed) == objects()


def test_parse_defaults_missing_isdir_to_false():
    # Unlike 'path', isDir affects only the display and the recursion caveat,
    # never which paths are deleted, so a missing value must not reject the row.
    parsed = [{"name": "pyex-001", "path": "S3:b/pfx/pyex-001"}]
    assert parse_object_summaries(parsed) == [
        ObjectSummary(path="S3:b/pfx/pyex-001", name="pyex-001", is_dir=False)
    ]


def test_parse_rejects_row_without_path():
    # Without a path the object cannot be targeted, and guessing one would
    # delete the wrong thing.
    assert parse_object_summaries([{"name": "pyex-001"}]) is None


def test_parse_rejects_row_without_name():
    assert parse_object_summaries([{"path": "S3:b/pfx/pyex-001"}]) is None


def test_parse_rejects_non_dict_row():
    assert parse_object_summaries(["pyex-001"]) is None


def test_parse_empty_list():
    assert parse_object_summaries([]) == []


def test_object_rows_are_one_column_with_the_path_as_handle():
    rows = object_rows(objects())
    assert [row.display for row in rows] == ["pyex-001", "pyex-logs/"]
    # the handle is the path, and a directory's path carries no trailing slash
    assert [row.handle for row in rows] == [
        "S3:b/pfx/pyex-001",
        "S3:b/pfx/pyex-logs",
    ]
    assert rows[1].tooltip == "pyex-logs/\nS3:b/pfx/pyex-logs"


def test_capture_objects_parses_enumeration(window, monkeypatch):
    monkeypatch.setattr(
        window,
        "_capture_dry_run_json",
        lambda command, extra_args=None: [
            {"name": "pyex-001", "path": "S3:b/pfx/pyex-001", "isDir": False}
        ],
    )
    assert window._capture_dry_run_objects(["-R", "pyex*"]) == [objects()[0]]


def test_capture_objects_none_on_enumeration_failure(window, monkeypatch):
    monkeypatch.setattr(
        window, "_capture_dry_run_json", lambda command, extra_args=None: None
    )
    assert window._capture_dry_run_objects(["-R", "pyex*"]) is None


def test_capture_objects_logs_when_paths_missing(window, monkeypatch):
    monkeypatch.setattr(
        window,
        "_capture_dry_run_json",
        lambda command, extra_args=None: [{"name": "pyex-001"}],
    )
    window.log_output.setPlainText("")
    assert window._capture_dry_run_objects(["-R", "pyex*"]) is None
    assert "did not include paths" in window.log_output.toPlainText()


@pytest.fixture
def captured(window, monkeypatch):
    """Capture (command, args, kwargs) an action would run, without spawning it."""
    calls: list[tuple[str, list[str], dict]] = []
    monkeypatch.setattr(
        window,
        "_run_command_in_subprocess",
        lambda command, args, **kwargs: calls.append((command, args, kwargs)),
    )
    return calls


def stub_delete_flow(window, monkeypatch, enumerated, result):
    """Stub the object enumeration and the confirmation for a delete."""
    monkeypatch.setattr(
        window, "_capture_dry_run_objects", lambda extra_args: enumerated
    )
    monkeypatch.setattr(
        window,
        "_confirm_destructive",
        lambda action_key, title, body, rows=None: result,
    )


def drive_dialog(window, monkeypatch, choose: str | None, uncheck: tuple = ()):
    """
    Let _confirm_destructive run without blocking on exec(): replace the
    dialog's exec() with a callback that unticks the given row indices and
    clicks a button, exactly as a user would.

    This is a local equivalent of test_commander_entity_selection.drive_dialog
    rather than a cross-module import: tests/ has no __init__.py, so the two
    test files are not a package, and importing one test module from another
    would lean on pytest's import-mode fallback rather than an explicit,
    supported layout. Keeping a small duplicate here is cheaper than coupling
    the two files together.
    """
    real_build = window._build_destructive_dialog

    def build(title, message, rows=None):
        dialog, yes_btn, skip_btn = real_build(title, message, rows=rows)

        def fake_exec():
            listing = dialog.findChild(QListWidget, "selection_list")
            if listing is not None:
                for index in uncheck:
                    listing.item(index).setCheckState(Qt.CheckState.Unchecked)
            if choose == "yes":
                yes_btn.click()
            elif choose == "skip":
                skip_btn.click()
            return 0

        monkeypatch.setattr(dialog, "exec", fake_exec)
        return dialog, yes_btn, skip_btn

    monkeypatch.setattr(window, "_build_destructive_dialog", build)


def test_unticked_object_is_not_deleted(window, captured, monkeypatch):
    # The end-to-end guarantee: a row the user unticks in the real dialog must
    # not reach the command line. Everything between the dialog and the run is
    # real here; only the two process boundaries are stubbed
    # (_capture_dry_run_objects and, via 'captured', _run_command_in_subprocess).
    all_objects = objects()
    monkeypatch.setattr(
        window, "_capture_dry_run_objects", lambda extra_args: all_objects
    )
    drive_dialog(window, monkeypatch, "yes", uncheck=(0,))
    window._tag = "pyex"
    window._delete_objects_action()
    command, args, _kwargs = captured[0]
    assert (command, args) == ("yd-delete", ["-Ry", "S3:b/pfx/pyex-logs"])


def test_delete_targets_only_the_selected_paths(window, captured, monkeypatch):
    all_objects = objects()
    stub_delete_flow(
        window,
        monkeypatch,
        all_objects,
        Confirmation(proceed=True, handles=["S3:b/pfx/pyex-logs"]),
    )
    window._tag = "pyex"
    window._delete_objects_action()
    command, args, _kwargs = captured[0]
    # the glob is replaced by the chosen paths, not appended to them
    assert (command, args) == ("yd-delete", ["-Ry", "S3:b/pfx/pyex-logs"])
    assert "pyex*" not in args


def test_delete_nothing_selected_removes_nothing(window, captured, monkeypatch):
    stub_delete_flow(
        window, monkeypatch, objects(), Confirmation(proceed=True, handles=[])
    )
    window._tag = "pyex"
    window.log_output.setPlainText("")
    window._delete_objects_action()
    assert captured == []
    assert "Nothing selected" in window.log_output.toPlainText()


def test_delete_declined_removes_nothing(window, captured, monkeypatch):
    stub_delete_flow(
        window, monkeypatch, objects(), Confirmation(proceed=False, handles=None)
    )
    window._tag = "pyex"
    window._delete_objects_action()
    assert captured == []


def test_delete_enumeration_failure_falls_back_to_the_pattern(
    window, captured, monkeypatch
):
    stub_delete_flow(
        window, monkeypatch, None, Confirmation(proceed=True, handles=None)
    )
    window._tag = "pyex"
    window._delete_objects_action()
    _command, args, _kwargs = captured[0]
    assert args == ["-Ry", "pyex*"]


def test_directory_caveat_appears_only_when_a_directory_matched(
    window, captured, monkeypatch
):
    bodies: list[str] = []

    def capture_body(action_key, title, body, rows=None):
        bodies.append(body)
        return Confirmation(proceed=False, handles=None)

    window._tag = "pyex"
    monkeypatch.setattr(window, "_confirm_destructive", capture_body)

    monkeypatch.setattr(
        window, "_capture_dry_run_objects", lambda extra_args: objects()
    )
    window._delete_objects_action()
    assert "everything inside it" in bodies[0]
    assert "pyex*" in bodies[0]

    monkeypatch.setattr(
        window, "_capture_dry_run_objects", lambda extra_args: [objects()[0]]
    )
    window._delete_objects_action()
    assert "everything inside it" not in bodies[1]
    assert captured == []


def test_delete_passes_object_rows_to_the_confirmation(window, captured, monkeypatch):
    seen: list = []

    def capture_rows(action_key, title, body, rows=None):
        seen.append(rows)
        return Confirmation(proceed=False, handles=None)

    monkeypatch.setattr(
        window, "_capture_dry_run_objects", lambda extra_args: objects()
    )
    monkeypatch.setattr(window, "_confirm_destructive", capture_rows)
    window._tag = "pyex"
    window._delete_objects_action()
    assert [row.handle for row in seen[0]] == [obj.path for obj in objects()]
    assert seen[0] is not None


def test_large_delete_selection_is_echoed_as_a_count(window, captured, monkeypatch):
    many = [
        ObjectSummary(path=f"S3:b/pfx/o{n}", name=f"o{n}", is_dir=False)
        for n in range(4)
    ]
    stub_delete_flow(
        window,
        monkeypatch,
        many,
        Confirmation(proceed=True, handles=[obj.path for obj in many]),
    )
    window._tag = "pyex"
    window._delete_objects_action()
    _command, args, kwargs = captured[0]
    assert args == ["-Ry"] + [obj.path for obj in many]
    assert kwargs["log_args"] == ["-Ry", "<4 objects>"]


def test_delete_refuses_a_selection_with_glob_metacharacters(
    window, captured, monkeypatch
):
    # 'a[1].txt' is a legitimate object name, but fnmatch treats '[1]' as a
    # character class, so 'yd-delete' would expand it and delete the sibling
    # 'a1.txt' instead of the object the user actually ticked.
    unsafe_objects = [
        ObjectSummary(path="S3:b/pfx/a[1].txt", name="a[1].txt", is_dir=False),
        ObjectSummary(path="S3:b/pfx/a1.txt", name="a1.txt", is_dir=False),
    ]
    stub_delete_flow(
        window,
        monkeypatch,
        unsafe_objects,
        Confirmation(proceed=True, handles=[obj.path for obj in unsafe_objects]),
    )
    window._tag = "pyex"
    window.log_output.setPlainText("")
    window._delete_objects_action()
    assert captured == []
    assert "wildcard characters" in window.log_output.toPlainText()
    assert "a[1].txt" in window.log_output.toPlainText()


def test_delete_refuses_a_selection_with_a_substitution_placeholder(
    window, captured, monkeypatch
):
    # 'resolve_remote_path' runs variable substitution on the handle before
    # its absolute-path check, so a ticked object named 'x_{{username}}' would
    # be substituted and a *different* path deleted. Undefined variables pass
    # through verbatim, so such a name is a realistic artefact of a Path-field
    # typo, not just a hypothetical.
    unsafe_objects = [
        ObjectSummary(
            path="S3:b/pfx/x_{{username}}", name="x_{{username}}", is_dir=False
        ),
        ObjectSummary(path="S3:b/pfx/a1.txt", name="a1.txt", is_dir=False),
    ]
    stub_delete_flow(
        window,
        monkeypatch,
        unsafe_objects,
        Confirmation(proceed=True, handles=[obj.path for obj in unsafe_objects]),
    )
    window._tag = "pyex"
    window.log_output.setPlainText("")
    window._delete_objects_action()
    assert captured == []
    assert "{{" in window.log_output.toPlainText()
    assert "x_{{username}}" in window.log_output.toPlainText()


def test_delete_runs_when_selected_paths_have_no_glob_metacharacters(
    window, captured, monkeypatch
):
    # The guard must not be over-broad: an ordinary selection still runs.
    stub_delete_flow(
        window,
        monkeypatch,
        objects(),
        Confirmation(proceed=True, handles=[obj.path for obj in objects()]),
    )
    window._tag = "pyex"
    window._delete_objects_action()
    _command, args, _kwargs = captured[0]
    assert args == ["-Ry"] + [obj.path for obj in objects()]
