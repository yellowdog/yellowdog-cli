"""
The Usage Explorer (commander/usage_explorer.py): its runner (a child process
per view, the latest request's result emitted, an older one dropped, Stop) and
its window, built directly. The child is replaced by a Python script, as
test_commander_commands.py does; for the window, one answering with a fixture
document chosen by the '--by' and '--where' it was given.
"""

import csv
import json
import os
import re
import sys
import time

import gui_harness
import pytest
import qt_guard

qt_guard.require_qt()

from PyQt6 import sip
from PyQt6.QtCore import QObject, QPoint, QProcess, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QStyle

import yellowdog_cli.commander.usage_explorer as usage_explorer
from yellowdog_cli.commander import commander
from yellowdog_cli.commander.branding import BRANDING_IMAGE_SIZE
from yellowdog_cli.commander.commander import YellowDogApp
from yellowdog_cli.commander.output_pane import (
    TABLE_OUTLINE_RGB_DARK,
    TABLE_OUTLINE_RGB_LIGHT,
)
from yellowdog_cli.commander.usage_explorer import (
    CRUMB_SEPARATOR,
    DARK_SEPARATOR_STYLE,
    KEPT_SEPARATOR,
    SETTING_EXPLORER_COST,
    SETTING_EXPLORER_EXPORT_TOTAL,
    SETTING_EXPLORER_FONT_SIZE,
    SETTING_EXPLORER_GEOMETRY,
    SETTING_EXPLORER_HIDDEN_COLUMNS,
    SETTING_EXPLORER_PRESET,
    TABLE_INDENT,
    RunResult,
    UsageExplorer,
    UsageRunner,
    grid_colour,
)
from yellowdog_cli.commander.usage_table import DURATION_HEADING, STATUS_COLUMNS
from yellowdog_cli.commander.usage_views import (
    KEY_VALUE_SEPARATOR,
    USAGE_GROUP_KEYS,
    heading,
)

TIMEOUT = 10.0


@pytest.fixture
def children(monkeypatch):
    """
    Each child runs the next script in 'scripts' (the last repeating), and
    what it would have been is recorded in 'started'.
    """

    class Children:
        def __init__(self) -> None:
            self.scripts: list[str] = []
            self.started: list[tuple[str, list[str]]] = []
            # (command, args) -> (stdout, stderr, exit code, seconds to wait);
            # used in place of 'scripts' where set
            self.answer = None

    holder = Children()

    def program(command, args):
        holder.started.append((command, args))
        if holder.answer is not None:
            out, err, code, delay = holder.answer(command, args)
            return sys.executable, [
                "-c",
                f"import sys, time; time.sleep({delay}); sys.stdout.write({out!r});"
                f" sys.stderr.write({err!r}); sys.exit({code})",
            ]
        index = min(len(holder.started), len(holder.scripts)) - 1
        return sys.executable, ["-c", holder.scripts[index]]

    monkeypatch.setattr(usage_explorer, "cli_program", program)
    return holder


@pytest.fixture
def runner(qapp, tmp_path):
    parent = QObject()
    runner = UsageRunner(parent, lambda: str(tmp_path), lambda: ["--nf", "-q"])
    yield runner
    runner.stop_all()
    parent.deleteLater()


def wait_until(qapp, condition) -> None:
    deadline = time.monotonic() + TIMEOUT
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        qapp.processEvents()
        time.sleep(0.01)


def collect(runner) -> list[RunResult]:
    results: list[RunResult] = []
    runner.finished.connect(results.append)
    return results


def test_a_run_emits_its_document(qapp, runner, children):
    children.scripts = ["print('{\"groups\": []}')"]
    results = collect(runner)
    request = runner.run(["--by", "namespace"])
    assert runner.running()
    wait_until(qapp, lambda: results)
    [result] = results
    assert (result.request, result.document, result.exit_code, result.error) == (
        request,
        {"groups": []},
        0,
        "",
    )
    assert result.arguments == ["--by", "namespace"]
    assert not runner.running()


def test_a_json_array_is_a_document(qapp, runner, children):
    children.scripts = ['print(\'["a", "b"]\')']
    results = collect(runner)
    runner.run([])
    wait_until(qapp, lambda: results)
    assert results[0].document == ["a", "b"]


def test_a_failure_carries_stderr_and_exit_code(qapp, runner, children):
    children.scripts = [
        "import sys; print('no permission', file=sys.stderr); sys.exit(5)"
    ]
    results = collect(runner)
    runner.run([])
    wait_until(qapp, lambda: results)
    [result] = results
    assert (result.document, result.exit_code, result.error) == (
        None,
        5,
        "no permission",
    )


def test_output_that_is_not_json_is_a_failure(qapp, runner, children):
    children.scripts = ["print('hello')"]
    results = collect(runner)
    runner.run([])
    wait_until(qapp, lambda: results)
    [result] = results
    assert result.document is None
    assert result.exit_code != 0
    assert result.error == "yd usage did not print a JSON document"


def test_another_command_is_named_in_its_error(qapp, tmp_path, children):
    children.scripts = ["print('x')"]
    parent = QObject()
    runner = UsageRunner(parent, lambda: str(tmp_path), list, command="yd list")
    results = collect(runner)
    runner.run([])
    wait_until(qapp, lambda: results)
    assert results[0].error == "yd list did not print a JSON document"
    runner.stop_all()


def test_an_older_result_is_dropped(qapp, runner, children):
    children.scripts = [
        "import time; time.sleep(0.5); print('{\"n\": 1}')",
        "print('{\"n\": 2}')",
    ]
    results = collect(runner)
    runner.run(["one"])
    second = runner.run(["two"])
    wait_until(qapp, lambda: results)
    # Give the older child time to finish; its result must not arrive
    end = time.monotonic() + 1.0
    while time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.01)
    [result] = results
    assert (result.request, result.document) == (second, {"n": 2})


def test_stop_ends_the_latest_run(qapp, runner, children):
    children.scripts = ["import time; time.sleep(30)"]
    results = collect(runner)
    runner.run([])
    runner.stop()
    wait_until(qapp, lambda: results)
    [result] = results
    assert (result.document, result.exit_code, result.error) == (None, -1, "Stopped")
    assert not runner.running()


def test_stop_all_kills_every_child_and_emits_nothing(qapp, runner, children):
    children.scripts = ["import time; time.sleep(30)"]
    results = collect(runner)
    runner.run([])
    runner.run([])
    runner.stop_all()
    end = time.monotonic() + 0.5
    while time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.01)
    assert results == []
    assert not runner.running()


def test_started_waiting_fires_after_the_delay(qapp, runner, children):
    children.scripts = ["import time; time.sleep(3); print('{}')"]
    results = collect(runner)
    waits: list[bool] = []
    runner.started_waiting.connect(lambda: waits.append(True))
    runner.run([])
    assert waits == []
    wait_until(qapp, lambda: waits)
    assert runner.running() and runner.elapsed_seconds() >= 0.25
    wait_until(qapp, lambda: results)


def test_a_quick_run_never_waits(qapp, runner, children):
    children.scripts = ["print('{}')"]
    runner.WAIT_DELAY_MS = 5000
    results = collect(runner)
    waits: list[bool] = []
    runner.started_waiting.connect(lambda: waits.append(True))
    runner.run([])
    wait_until(qapp, lambda: results)
    end = time.monotonic() + 0.5
    while time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.01)
    assert waits == []


def test_base_arguments_come_first(qapp, runner, children):
    children.scripts = ["print('{}')"]
    results = collect(runner)
    runner.run(["--by", "tag"])
    wait_until(qapp, lambda: results)
    assert children.started == [("yd usage", ["--nf", "-q", "--by", "tag"])]


def test_stderr_on_success_is_not_an_error(qapp, runner, children):
    children.scripts = [
        "import sys; print('a warning', file=sys.stderr); print('{\"a\": 1}')"
    ]
    results = collect(runner)
    runner.run([])
    wait_until(qapp, lambda: results)
    assert (results[0].document, results[0].exit_code, results[0].error) == (
        {"a": 1},
        0,
        "",
    )


def test_stderr_lines_on_success_are_carried_as_warnings(qapp, runner, children):
    children.scripts = [
        "import sys; print('WARNING : Could not read the Applications',"
        " file=sys.stderr); print('{\"a\": 1}')"
    ]
    results = collect(runner)
    runner.run([])
    wait_until(qapp, lambda: results)
    assert results[0].warnings == ["Could not read the Applications"]
    assert results[0].error == ""


def test_destroying_the_parent_mid_run_is_safe(qapp, tmp_path, children):
    children.scripts = ["import time; time.sleep(30)"]
    parent = QObject()
    runner = UsageRunner(parent, lambda: str(tmp_path), list)
    results = collect(runner)
    runner.run([])
    process = runner._runs[1].process
    wait_until(qapp, lambda: process.state() != process.ProcessState.NotRunning)
    sip.delete(parent)
    end = time.monotonic() + 0.6
    while time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.01)
    assert results == []
    assert sip.isdeleted(runner)


# The window ---------------------------------------------------------------

FROM_ISO = "2026-11-18T15:02:00Z"
UNTIL_ISO = "2026-11-25T15:02:00Z"
# The same window as a pinned view passes it (window_time())
FROM_TEXT = "2026-11-18 15:02 UTC"
UNTIL_TEXT = "2026-11-25 15:02 UTC"
BASE_ARGS = ["-c", "config.toml", "--nf", "-q", "--json"]
STATES = ("pending", "running", "stopping", "stopped", "terminating", "unknown")


def group(
    keys: dict,
    instances: int,
    running: float,
    stopped: float = 0.0,
    cost: float | None = None,
    unpriced: float = 0.0,
) -> dict:
    """
    A group as `yd usage --json` writes it, its times given in hours.
    """
    seconds = dict.fromkeys(STATES, 0.0)
    seconds.update(running=running * 3600, stopped=stopped * 3600)
    seconds["total"] = (running + stopped) * 3600
    return {
        **keys,
        "instances": instances,
        "hours": {key: value / 3600 for key, value in seconds.items()},
        "seconds": seconds,
        "estimatedCost": cost,
        "unpricedRunningHours": unpriced,
    }


def document(
    by: list[str],
    groups: list[dict],
    reused: bool = True,
    unpriced: tuple = (),
    where: dict | None = None,
) -> dict:
    """
    A `yd usage --cost --json` document over the groups, with their total.
    """
    total = group({}, sum(g["instances"] for g in groups), 0.0)
    for key in (*STATES, "total"):
        total["seconds"][key] = sum(g["seconds"][key] for g in groups)
    costs = [g["estimatedCost"] for g in groups if g["estimatedCost"] is not None]
    total["estimatedCost"] = round(sum(costs), 2) if costs else None
    total["unpricedRunningHours"] = sum(g["unpricedRunningHours"] for g in groups)
    total["groups"] = len(groups)
    return {
        "from": FROM_ISO,
        "until": UNTIL_ISO,
        "namespace": None,
        "namespaces": ["team-render", "team-sim"],
        "by": by,
        "where": where or {},
        "fetched": "2026-11-25T15:02:30Z",
        "reused": reused,
        "reportFile": "/tmp/report.zip",
        "groups": groups,
        "total": total,
        "currency": "USD",
        "unpriced": list(unpriced),
        "unreadablePrices": [],
        "pricesRefused": False,
    }


NAMESPACES = [
    {"id": "ydid:ns:1", "namespace": "team-render", "deletable": False},
    {"id": "ydid:ns:2", "namespace": "team-sim", "deletable": False},
]
UNPRICED = {
    "provider": "aws",
    "region": "eu-west-2",
    "instanceType": "g4dn.xlarge",
    "pricing": "spot",
    "runningHours": 0.7,
}


def value_of(args: list[str], option: str) -> str | None:
    return args[args.index(option) + 1] if option in args else None


def wheres(args: list[str]) -> list[str]:
    return [args[i + 1] for i, arg in enumerate(args) if arg == "--where"]


# Two reports kept, as yd usage --reports --json lists them (the first with
# the fractions of a second a window resolved at fetch time has)
KEPT = [
    {
        "from": "2026-10-01T00:00:00.559218Z",
        "until": "2026-11-01T00:00:00.601337Z",
        "namespace": "team-render",
        "namespaces": ["team-render"],
        "fetched": "2026-11-20T09:00:00Z",
        "lastUsed": "2026-11-24T09:00:00Z",
        "bytes": 12345,
        "reportFile": "/tmp/a/report.zip",
        "command": "yd usage --from 2026-10-01T00:00:00Z --until"
        " 2026-11-01T00:00:00Z -n team-render",
    },
    {
        "from": FROM_ISO,
        "until": UNTIL_ISO,
        "namespace": None,
        "namespaces": None,
        "fetched": "2026-11-25T15:02:30Z",
        "lastUsed": "2026-11-25T15:02:30Z",
        "bytes": 23456,
        "reportFile": "/tmp/b/report.zip",
        "command": f"yd usage --from {FROM_ISO} --until {UNTIL_ISO}",
    },
]


def is_view(command: str, args: list[str]) -> bool:
    """
    Whether a child is a view's yd usage run, not the kept reports' listing.
    """
    return command == "yd usage" and "--reports" not in args


def usage_answer(command: str, args: list[str]):
    """
    The fake CLI: namespaces for 'yd list', else a document by '--by' and
    '--where'. A view of a window as typed fetches the report; one pinned to
    the report's own window reuses it.
    """
    if command == "yd list":
        return json.dumps(NAMESPACES), "", 0, 0
    if "--reports" in args:
        return json.dumps(KEPT), "", 0, 0
    by = value_of(args, "--by") or "namespace"
    reused = value_of(args, "--from") == FROM_TEXT and "--refresh" not in args
    if by == "namespace":
        groups = [
            group({"namespace": "team-render"}, 17, 47.2, 12.0, 248.10, 0.7),
            group({"namespace": "team-sim"}, 3, 6.0, 0.0, 31.70),
        ]
        return json.dumps(document(["namespace"], groups, reused)), "", 0, 0
    if by == "cr" and "namespace==team-render" in wheres(args):
        groups = [
            group({"cr": "render-nightly"}, 14, 41.2, 0.0, 216.40, 0.7),
            group({"cr": "render-adhoc"}, 3, 6.0, 12.0, 31.70),
        ]
        body = document(["cr"], groups, reused, unpriced=(UNPRICED,))
        return json.dumps(body), "", 0, 0
    keys = by.split(",")
    groups = [group(dict.fromkeys(keys, "x"), 1, 1.0, 0.0, 1.0)]
    return json.dumps(document(keys, groups, reused)), "", 0, 0


def usage_args(children) -> list[str]:
    """
    The view's own arguments of the latest 'yd usage' child.
    """
    [args] = [a for c, a in children.started if is_view(c, a)][-1:]
    assert args[: len(BASE_ARGS)] == BASE_ARGS
    return args[len(BASE_ARGS) :]


def fetch(explorer) -> None:
    """
    Click Fetch Report, which is up, and let the run finish.
    """
    assert explorer._fetch_overlay.isVisible()
    explorer._fetch.click()
    settle(explorer)
    assert not explorer._fetch_overlay.isVisible()


def settle(explorer) -> None:
    wait_for(
        lambda: (
            not any(
                runner.running()
                for runner in (
                    explorer._runner,
                    explorer._namespace_runner,
                    explorer._reports_runner,
                )
            )
        )
    )


def wait_for(condition, timeout: float = TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        QApplication.processEvents()
        time.sleep(0.01)


def cells(explorer, row: int) -> list[str]:
    model = explorer._model
    return [
        model.data(model.index(row, column)) for column in range(model.columnCount())
    ]


def column_of(explorer, name: str) -> int:
    """
    The column headed name, a time column's by its name alone ('Running' for
    'Running (h:mm)').
    """
    model = explorer._model
    headings = [
        model.headerData(c, Qt.Orientation.Horizontal)
        for c in range(model.columnCount())
    ]
    return next(
        c
        for c, h in enumerate(headings)
        if h in (name, DURATION_HEADING.format(heading=name))
    )


def click_heading(explorer, name: str) -> None:
    header = explorer._table.horizontalHeader()
    column = column_of(explorer, name)
    x = header.sectionViewportPosition(column) + header.sectionSize(column) // 2
    QTest.mouseClick(
        header.viewport(),
        Qt.MouseButton.LeftButton,
        pos=QPoint(x, header.height() // 2),
    )


def double_click_row(explorer, row: int) -> None:
    table = explorer._table
    rect = table.visualRect(explorer._model.index(row, 0))
    QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    QTest.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())


@pytest.fixture
def explorer(qapp, children, tmp_path):
    children.answer = usage_answer
    logged: list[str] = []
    window = UsageExplorer(
        "Usage Explorer — config.toml",
        lambda: str(tmp_path),
        lambda: list(BASE_ARGS),
        QFont(),
        False,
    )
    window.logged.connect(logged.append)
    window.log_lines = logged  # type: ignore[attr-defined]
    window.resize(1000, 640)
    window.show()
    settle(window)
    fetch(window)
    yield window
    if not sip.isdeleted(window):
        window.shut_down()
    QApplication.processEvents()


def test_the_top_level_shows_namespaces_and_the_total(explorer, children):
    assert explorer.isVisible() and not explorer.isModal()
    assert explorer.windowTitle() == "Usage Explorer — config.toml"
    assert children.started[0] == ("yd list", [*BASE_ARGS, "namespaces"])
    assert usage_args(children) == [
        "--from",
        "7 days ago",
        "--until",
        "now",
        "--by",
        "namespace",
        "--cost",
    ]
    assert explorer._model.rowCount() == 3
    assert cells(explorer, 0)[:6] == [
        "team-render",
        "17",
        "47:12",
        "12:00",
        "59:12",
        "248.10+",
    ]
    assert cells(explorer, 1)[0] == "team-sim"
    assert cells(explorer, 2)[:2] == ["Total", "20"]
    assert explorer._model.data(
        explorer._model.index(2, 0), Qt.ItemDataRole.FontRole
    ).bold()
    assert (
        explorer._model.data(explorer._model.index(0, 0), Qt.ItemDataRole.FontRole)
        is None
    )
    combo = explorer._namespace
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "All namespaces",
        "team-render",
        "team-sim",
    ]
    assert explorer.breadcrumb_text() == "All"
    # The status columns are hidden until asked for
    table = explorer._table
    assert table.isColumnHidden(column_of(explorer, "Pending"))
    assert not table.isColumnHidden(column_of(explorer, "Running"))
    cost = column_of(explorer, "Est. cost (USD)")
    assert explorer._model.headerData(
        cost, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole
    ) == (
        "Linux list prices today; spot Instances at the region's mean spot"
        " price; no discounts, savings plans, licences or disks; running time only"
    )


def test_double_clicking_a_row_drills_and_pins_the_window(explorer, children):
    double_click_row(explorer, 0)
    settle(explorer)
    args = usage_args(children)
    assert value_of(args, "--from") == FROM_TEXT
    assert value_of(args, "--until") == UNTIL_TEXT
    assert wheres(args) == ["namespace==team-render"]
    assert value_of(args, "--by") == "cr"
    assert explorer.breadcrumb_text() == f"All{CRUMB_SEPARATOR}team-render"
    assert cells(explorer, 0)[0] == "render-nightly"
    # The Total row is no group, and drills nowhere
    started = len(children.started)
    double_click_row(explorer, 2)
    QApplication.processEvents()
    assert len(children.started) == started


def test_the_breadcrumb_steps_back_to_the_same_view(explorer, children):
    click_heading(explorer, "Running")
    settle(explorer)
    double_click_row(explorer, 0)
    settle(explorer)
    assert explorer.breadcrumb_text() == f"All{CRUMB_SEPARATOR}team-render"
    assert explorer._back.isEnabled()
    explorer._crumb_buttons[0].click()
    settle(explorer)
    args = usage_args(children)
    assert wheres(args) == []
    assert value_of(args, "--by") == "namespace"
    assert value_of(args, "--sort") == "running"
    assert explorer.breadcrumb_text() == "All"
    assert not explorer._back.isEnabled()
    assert cells(explorer, 0)[0] == "team-render"


def test_a_column_heading_sorts_through_the_cli(explorer, children):
    click_heading(explorer, "Running")
    settle(explorer)
    args = usage_args(children)
    assert value_of(args, "--sort") == "running" and "--reverse" not in args
    click_heading(explorer, "Running")
    settle(explorer)
    args = usage_args(children)
    assert value_of(args, "--sort") == "running" and "--reverse" in args
    click_heading(explorer, "Namespace")
    settle(explorer)
    args = usage_args(children)
    assert value_of(args, "--sort") == "namespace" and "--reverse" not in args
    # A status column is not one the CLI sorts by
    explorer._show_column("pending", True)
    started = len(children.started)
    click_heading(explorer, "Pending")
    QApplication.processEvents()
    assert len(children.started) == started


def test_changing_the_window_resets_the_breadcrumb(explorer, children):
    double_click_row(explorer, 0)
    settle(explorer)
    started = len(children.started)
    explorer._preset.setCurrentText("Last 30 days")
    QApplication.processEvents()
    # Nothing runs until Fetch Report
    assert len(children.started) == started
    assert explorer.breadcrumb_text() == f"All{CRUMB_SEPARATOR}team-render"
    fetch(explorer)
    args = usage_args(children)
    assert args[:4] == ["--from", "30 days ago", "--until", "now"]
    assert wheres(args) == [] and "--refresh" not in args
    assert explorer.breadcrumb_text() == "All"
    # Typing a window makes it Custom, awaiting Fetch Report once typed
    explorer._from.setFocus()
    explorer._from.selectAll()
    QTest.keyClicks(explorer._from, "2 days ago")
    assert explorer._preset.currentText() == "Custom"
    explorer._from.editingFinished.emit()
    fetch(explorer)
    assert usage_args(children)[:2] == ["--from", "2 days ago"]
    # Choosing a namespace awaits it too
    explorer._namespace.setCurrentText("team-sim")
    explorer._namespace.activated.emit(2)
    fetch(explorer)
    assert value_of(usage_args(children), "-n") == "team-sim"


def test_controls_put_back_to_the_report_shown_need_no_fetch(explorer, children):
    started = len(children.started)
    explorer._preset.setCurrentText("Last 30 days")
    QApplication.processEvents()
    assert explorer._fetch_overlay.isVisible()
    explorer._preset.setCurrentText("Last 7 days")
    QApplication.processEvents()
    assert not explorer._fetch_overlay.isVisible()
    assert len(children.started) == started
    # The view actions work again on the report shown
    double_click_row(explorer, 0)
    settle(explorer)
    assert wheres(usage_args(children)) == ["namespace==team-render"]


def test_cmd_r_fetches_a_report_awaited(explorer, children):
    explorer._preset.setCurrentText("Last 30 days")
    QApplication.processEvents()
    QTest.keyClick(explorer._table, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier)
    settle(explorer)
    assert not explorer._fetch_overlay.isVisible()
    assert usage_args(children)[:2] == ["--from", "30 days ago"]


def test_an_empty_report_shows_an_empty_table(explorer, children):
    children.answer = lambda c, a: (json.dumps(document(["namespace"], [])), "", 0, 0)
    explorer._refresh.click()
    settle(explorer)
    assert explorer._model.rowCount() == 0
    assert "No Instances in this window" in explorer._notes.text()


def test_a_failed_run_keeps_the_previous_view(explorer, children):
    double_click_row(explorer, 0)
    settle(explorer)
    before = [cells(explorer, row) for row in range(explorer._model.rowCount())]
    children.answer = lambda c, a: (
        "",
        "ERROR : This Application may not read usage in 'team-render'\nmore\n",
        5,
        0,
    )
    click_heading(explorer, "Total")
    settle(explorer)
    assert [cells(explorer, row) for row in range(explorer._model.rowCount())] == (
        before
    )
    assert explorer.breadcrumb_text() == f"All{CRUMB_SEPARATOR}team-render"
    notes = explorer._notes.text()
    assert "This Application may not read usage in 'team-render'" in notes
    assert "This Application may not read usage there" in notes
    assert "ERROR" not in notes
    # Both lines are seen, the strip given the height they need
    end = time.monotonic() + 0.3
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)
    notes_view = explorer._notes
    assert notes_view.height() >= notes_view.document().size().height()
    assert explorer.log_lines[-1] == (
        "yd usage failed (exit 5): This Application may not read usage in 'team-render'"
    )
    # Exit code 8's meaning, and a usage error's message alone
    children.answer = lambda c, a: ("", "ERROR : Timed out\n", 8, 0)
    explorer._rerun()
    settle(explorer)
    assert (
        "a larger requestTimeout in [common] gives it longer" in explorer._notes.text()
    )
    children.answer = lambda c, a: ("", "ERROR : bad --from\n", 2, 0)
    explorer._rerun()
    settle(explorer)
    assert explorer._notes.text() == "bad --from"


def test_a_long_error_wraps_to_the_window(explorer, children):
    url = "https://api.example.com/api/" + "x" * 300 + "/namespaces/"
    children.answer = lambda c, a: (
        "",
        f"ERROR : 404 Client Error: Not Found for url: {url} Response Body:\n",
        6,
        0,
    )
    minimum = explorer.minimumSizeHint().width()
    one_line = explorer._notes.fontMetrics().lineSpacing()
    click_heading(explorer, "Total")
    settle(explorer)
    notes = explorer._notes
    assert url in notes.text()
    QApplication.processEvents()
    # Wrapped over several lines, the URL broken, within the window
    assert notes.height() > 3 * one_line
    assert notes.height() >= notes.document().size().height()
    assert notes.width() <= explorer.width()
    assert explorer.minimumSizeHint().width() == minimum
    # Wider, it takes fewer lines
    narrow = notes.height()
    explorer.resize(explorer.width() + 400, explorer.height())
    QApplication.processEvents()
    assert notes.height() < narrow


def test_cost_notes_and_partial_costs(explorer, children):
    double_click_row(explorer, 0)
    settle(explorer)
    cost = column_of(explorer, "Est. cost (USD)")
    assert cells(explorer, 0)[cost] == "216.40+"
    assert cells(explorer, 1)[cost] == "31.70"
    assert cells(explorer, 2)[cost] == "248.10+"
    assert "1 instance type had no list price (0:42 running)" in explorer._notes.text()
    assert explorer._details_button.isVisible()
    assert not explorer._details.isVisible()
    explorer._details_button.click()
    assert explorer._details.isVisible()
    assert "aws eu-west-2 g4dn.xlarge (spot): 0:42 running" in explorer._details.text()


def test_the_command_line_is_the_views_and_can_be_copied(explorer, children, qapp):
    started = [a for c, a in children.started if is_view(c, a)][-1]
    assert explorer._command_line.text() == (
        "yd usage -c config.toml --from '7 days ago' --until now --by namespace --cost"
    )
    assert explorer._command_line.isReadOnly()
    assert started == BASE_ARGS + usage_args(children)
    explorer._copy_command.click()
    assert qapp.clipboard().text() == explorer._command_line.text()
    double_click_row(explorer, 0)
    settle(explorer)
    assert "--where namespace==team-render" in explorer._command_line.text()
    assert FROM_TEXT in explorer._command_line.text()


def test_a_fetch_is_logged_and_a_regroup_is_not(explorer, children):
    assert explorer.log_lines == [
        "Fetched the usage report: yd usage -c config.toml"
        " --from '7 days ago' --until now --by namespace --cost"
    ]
    assert "fetched" in explorer._report.text()
    double_click_row(explorer, 0)
    settle(explorer)
    assert len(explorer.log_lines) == 1
    assert "reused" in explorer._report.text()
    assert "2026-11-18 15:02 → 2026-11-25 15:02 UTC" in explorer._report.text()


def test_preferences_are_remembered(
    explorer, children, commander_dialog_settings, monkeypatch
):
    explorer._preset.setCurrentText("Last 30 days")
    fetch(explorer)
    explorer._cost.click()
    settle(explorer)
    explorer._show_column("pending", True)
    explorer._show_column("unknown", True)
    explorer._show_column("unknown", False)
    explorer.close()
    QApplication.processEvents()
    settings = commander_dialog_settings
    assert settings.value(SETTING_EXPLORER_PRESET) == "Last 30 days"
    assert settings.value(SETTING_EXPLORER_COST, type=bool) is False
    saved = settings.value(SETTING_EXPLORER_GEOMETRY)
    assert saved is not None
    # What is handed back to restoreGeometry(), not the size it gives: Qt
    # holds a restored window to its screen and its own minimum, which on
    # Windows is close to the test machine's screen width
    restored: list = []
    monkeypatch.setattr(
        UsageExplorer,
        "restoreGeometry",
        lambda self, geometry: restored.append(geometry) or True,
    )
    again = UsageExplorer(
        "Usage Explorer — config.toml",
        lambda: ".",
        lambda: list(BASE_ARGS),
        QFont(),
        False,
    )
    again.show()
    settle(again)
    try:
        fetch(again)
        assert again._preset.currentText() == "Last 30 days"
        assert (again._from.text(), again._until.text()) == ("30 days ago", "now")
        assert not again._cost.isChecked()
        assert "--cost" not in usage_args(children)
        assert not again._table.isColumnHidden(column_of(again, "Pending"))
        assert again._table.isColumnHidden(column_of(again, "Unknown"))
        assert restored == [saved]
    finally:
        again.shut_down()


def test_custom_dates_are_not_remembered(explorer, commander_dialog_settings):
    explorer._from.setText("2 days ago")
    explorer._from.textEdited.emit("2 days ago")
    explorer.close()
    assert commander_dialog_settings.value(SETTING_EXPLORER_PRESET) in (
        None,
        "Last 7 days",
    )


def tick(explorer, *keys: str) -> None:
    """
    Tick or untick keys in Total by's menu, then close it, which applies them.
    """
    menu = explorer._total_by.menu()
    for key in keys:
        [action] = [a for a in menu.actions() if a.text() == heading(key)]
        action.trigger()
    menu.aboutToHide.emit()


def ticked(explorer) -> list[str]:
    return [a.text() for a in explorer._total_by.menu().actions() if a.isChecked()]


def test_total_by_adds_and_removes_keys_and_keeps_the_filter(explorer, children):
    double_click_row(explorer, 0)
    settle(explorer)
    assert ticked(explorer) == [heading("cr")]
    tick(explorer, "region")
    settle(explorer)
    args = usage_args(children)
    assert value_of(args, "--by") == "cr,region"
    assert wheres(args) == ["namespace==team-render"]
    assert explorer.breadcrumb_text() == f"All{CRUMB_SEPARATOR}team-render"
    assert [
        explorer._model.headerData(c, Qt.Orientation.Horizontal) for c in (0, 1)
    ] == [heading("cr"), "Region"]
    assert explorer._total_by.text() == f"{heading('cr')}, Region"
    tick(explorer, "cr")
    settle(explorer)
    assert value_of(usage_args(children), "--by") == "region"
    assert explorer._model.headerData(0, Qt.Orientation.Horizontal) == "Region"
    # The last key stays
    started = len(children.started)
    tick(explorer, "region")
    QApplication.processEvents()
    assert len(children.started) == started
    assert ticked(explorer) == ["Region"]


def test_total_by_changes_several_keys_in_one_run(explorer, children):
    double_click_row(explorer, 0)
    settle(explorer)
    started = len(children.started)
    menu = explorer._total_by.menu()
    for key in ("region", "tag", "cr"):
        [action] = [a for a in menu.actions() if a.text() == heading(key)]
        action.trigger()
    # Staged while the menu is open: nothing runs yet
    QApplication.processEvents()
    assert len(children.started) == started
    assert sorted(ticked(explorer)) == sorted(["Region", heading("tag")])
    menu.aboutToHide.emit()
    settle(explorer)
    views = [a for c, a in children.started[started:] if is_view(c, a)]
    assert len(views) == 1
    assert value_of(usage_args(children), "--by") == "region,tag"


def test_total_by_closed_unchanged_runs_nothing(explorer, children):
    started = len(children.started)
    tick(explorer, "region", "region")
    QApplication.processEvents()
    assert len(children.started) == started
    assert ticked(explorer) == ["Namespace"]


def test_the_total_by_menu_stays_open_while_ticking(explorer, children):
    menu = explorer._total_by.menu()
    menu.popup(explorer.mapToGlobal(explorer._total_by.geometry().bottomLeft()))
    QApplication.processEvents()
    assert menu.isVisible()
    started = len(children.started)
    [region] = [a for a in menu.actions() if a.text() == "Region"]
    QTest.mouseClick(
        menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(region).center()
    )
    assert menu.isVisible()
    assert region.isChecked()
    menu.setActiveAction(region)
    QTest.keyClick(menu, Qt.Key.Key_Space)
    assert menu.isVisible()
    assert not region.isChecked()
    QTest.keyClick(menu, Qt.Key.Key_Return)
    assert menu.isVisible() and region.isChecked()
    QApplication.processEvents()
    assert len(children.started) == started
    menu.hide()
    settle(explorer)
    assert value_of(usage_args(children), "--by") == "namespace,region"


def test_total_by_offers_only_the_keys_left_open(explorer, children):
    offered = [a.text() for a in explorer._total_by.menu().actions()]
    assert offered == [heading(key) for key in USAGE_GROUP_KEYS]
    double_click_row(explorer, 0)
    settle(explorer)
    offered = [a.text() for a in explorer._total_by.menu().actions()]
    assert "Namespace" not in offered


def test_a_multi_key_row_drills_on_every_key(explorer, children):
    tick(explorer, "region")
    settle(explorer)
    double_click_row(explorer, 0)
    settle(explorer)
    args = usage_args(children)
    assert wheres(args) == ["namespace==x", "region==x"]
    assert value_of(args, "--by") == "cr"
    assert explorer.breadcrumb_text() == f"All{CRUMB_SEPARATOR}x{KEY_VALUE_SEPARATOR}x"


def test_the_cost_checkbox_keeps_the_pin(explorer, children):
    explorer._cost.click()
    settle(explorer)
    args = usage_args(children)
    assert "--cost" not in args
    assert (value_of(args, "--from"), value_of(args, "--until")) == (
        FROM_TEXT,
        UNTIL_TEXT,
    )
    assert "Est. cost (USD)" not in [
        explorer._model.headerData(c, Qt.Orientation.Horizontal)
        for c in range(explorer._model.columnCount())
    ]


def test_refresh_refetches_from_the_typed_window(explorer, children):
    double_click_row(explorer, 0)
    settle(explorer)
    explorer._refresh.click()
    settle(explorer)
    args = usage_args(children)
    assert "--refresh" in args
    assert args[:4] == ["--from", "7 days ago", "--until", "now"]
    assert wheres(args) == []
    assert explorer.breadcrumb_text() == "All"
    assert len(explorer.log_lines) == 2


def test_keys_drill_back_and_copy(explorer, children, qapp):
    table = explorer._table
    table.setFocus()
    table.setCurrentIndex(explorer._model.index(0, 0))
    QTest.keyClick(table, Qt.Key.Key_Return)
    settle(explorer)
    assert explorer.breadcrumb_text() == f"All{CRUMB_SEPARATOR}team-render"
    QTest.keyClick(table, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
    settle(explorer)
    assert explorer.breadcrumb_text() == "All"
    assert wheres(usage_args(children)) == []
    # Cmd/Ctrl+R runs the view again
    started = len(children.started)
    QTest.keyClick(table, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier)
    settle(explorer)
    assert len(children.started) == started + 1
    # Cmd/Ctrl+C copies the selected cells, with their headings
    model = explorer._model
    selection = table.selectionModel()
    selection.clearSelection()
    for column in (0, 1):
        for row in (0, 1):
            selection.select(model.index(row, column), selection.SelectionFlag.Select)
    QTest.keyClick(table, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert qapp.clipboard().text() == (
        "Namespace\tInstances\nteam-render\t17\nteam-sim\t3"
    )
    # Esc leaves the window open
    QTest.keyClick(explorer, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert explorer.isVisible()


def test_a_slow_view_dims_the_table_and_stop_ends_it(explorer, children):
    children.answer = lambda c, a: ("{}", "", 0, 30)
    explorer._rerun()
    wait_for(lambda: explorer._overlay.isVisible())
    assert explorer._overlay.geometry() == explorer._table.rect()
    assert explorer._overlay_text.text().startswith("Running yd usage… 0:0")
    explorer._stop.click()
    settle(explorer)
    assert not explorer._overlay.isVisible()
    assert explorer._notes.text() == "Stopped"
    assert explorer._model.rowCount() == 3


def test_reset_starts_again_at_the_top(explorer, children):
    double_click_row(explorer, 0)
    settle(explorer)
    runs = len([c for c, a in children.started if is_view(c, a)])
    explorer.reset("Usage Explorer — other.toml")
    settle(explorer)
    assert explorer.windowTitle() == "Usage Explorer — other.toml"
    assert explorer.breadcrumb_text() == "All"
    assert explorer._model.rowCount() == 0
    assert len([c for c, a in children.started if is_view(c, a)]) == runs
    fetch(explorer)
    args = usage_args(children)
    assert args[:2] == ["--from", "7 days ago"] and wheres(args) == []
    assert children.started.count(("yd list", [*BASE_ARGS, "namespaces"])) == 2


def test_a_namespace_listing_failure_is_logged(qapp, children, tmp_path):
    def answer(command, args):
        if command == "yd list":
            return "", "ERROR : no permission\n", 4, 0
        return usage_answer(command, args)

    children.answer = answer
    logged: list[str] = []
    window = UsageExplorer(
        "t", lambda: str(tmp_path), lambda: list(BASE_ARGS), QFont(), False
    )
    window.logged.connect(logged.append)
    settle(window)
    try:
        assert window._namespace.count() == 1
        assert "yd list namespaces failed (exit 4): no permission" in logged
    finally:
        window.shut_down()


def test_view_actions_wait_for_a_new_scopes_first_run(explorer, children):
    double_click_row(explorer, 0)
    settle(explorer)

    def slow_new_window(command, args):
        out, err, code, _ = usage_answer(command, args)
        return out, err, code, 1.0 if "30 days ago" in args else 0

    children.answer = slow_new_window
    explorer._preset.setCurrentText("Last 30 days")
    QApplication.processEvents()

    def refused() -> None:
        started = len(children.started)
        explorer._table.setFocus()
        QTest.keyClick(explorer._table, Qt.Key.Key_Return)
        explorer._back.click()
        before = ticked(explorer)
        tick(explorer, "region")
        QApplication.processEvents()
        assert len(children.started) == started
        assert ticked(explorer) == before

    # Awaiting Fetch Report, then while its first run is under way
    refused()
    explorer._fetch.click()
    QApplication.processEvents()
    refused()
    settle(explorer)
    args = usage_args(children)
    assert args[:4] == ["--from", "30 days ago", "--until", "now"]
    assert explorer.breadcrumb_text() == "All"
    # The cost checkbox, awaiting Fetch Report, is taken by the fetch
    explorer._preset.setCurrentText("Last 7 days")
    started = len(children.started)
    explorer._cost.click()
    QApplication.processEvents()
    assert len(children.started) == started
    fetch(explorer)
    args = usage_args(children)
    assert args[:2] == ["--from", "7 days ago"] and "--cost" not in args
    assert explorer.breadcrumb_text() == "All"


def test_a_new_scopes_failed_first_run_puts_the_controls_back(explorer, children):
    def missing_namespace(command, args):
        if value_of(args, "-n") == "team-gone":
            return "", "ERROR : Namespace 'team-gone' does not exist\n", 6, 0
        return usage_answer(command, args)

    children.answer = missing_namespace
    explorer._namespace.setCurrentText("team-gone")
    explorer._namespace.activated.emit(0)
    fetch(explorer)
    assert "The namespace does not exist" in explorer._notes.text()
    assert explorer._namespace.currentText() == "All namespaces"
    assert explorer._preset.currentText() == "Last 7 days"
    assert cells(explorer, 0)[0] == "team-render"
    double_click_row(explorer, 0)
    settle(explorer)
    args = usage_args(children)
    assert "-n" not in args
    assert value_of(args, "--from") == FROM_TEXT
    assert wheres(args) == ["namespace==team-render"]
    # The failure was not rerun on leaving the field
    started = len(children.started)
    explorer._namespace.lineEdit().editingFinished.emit()
    QApplication.processEvents()
    assert len(children.started) == started


def test_a_stopped_regroup_puts_the_controls_back(explorer, children):
    double_click_row(explorer, 0)
    settle(explorer)
    tick(explorer, "region")
    settle(explorer)
    assert explorer._cost.isChecked()
    before = ticked(explorer)
    children.answer = lambda c, a: ("{}", "", 0, 30)
    explorer._cost.click()
    tick(explorer, "tag")
    wait_for(lambda: explorer._overlay.isVisible())
    explorer._stop.click()
    settle(explorer)
    assert explorer._cost.isChecked()
    assert ticked(explorer) == before
    children.answer = usage_answer
    double_click_row(explorer, 0)
    settle(explorer)
    assert "--cost" in usage_args(children)


def test_a_failed_regroup_puts_the_cost_checkbox_back(explorer, children):
    double_click_row(explorer, 0)
    settle(explorer)
    assert explorer._cost.isChecked()
    children.answer = lambda c, a: ("", "ERROR : Timed out\n", 8, 0)
    explorer._cost.click()
    settle(explorer)
    assert explorer._cost.isChecked()
    children.answer = usage_answer
    tick(explorer, "region")
    settle(explorer)
    assert "--cost" in usage_args(children)


def test_rerunning_a_failed_regroup_brings_the_controls_with_it(
    explorer, children, commander_dialog_settings
):
    double_click_row(explorer, 0)
    settle(explorer)
    children.answer = lambda c, a: ("", "ERROR : Timed out\n", 8, 0)
    explorer._cost.click()
    settle(explorer)
    assert explorer._cost.isChecked()
    assert commander_dialog_settings.value(SETTING_EXPLORER_COST, type=bool)
    children.answer = usage_answer
    QTest.keyClick(explorer._table, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier)
    settle(explorer)
    assert "--cost" not in usage_args(children)
    assert not explorer._cost.isChecked()
    assert not commander_dialog_settings.value(SETTING_EXPLORER_COST, type=bool)


def test_turning_the_cost_off_and_on_again_shows_it(explorer, children):
    explorer._cost.click()
    settle(explorer)
    explorer._cost.click()
    settle(explorer)
    assert "--cost" in usage_args(children)
    column = column_of(explorer, "Est. cost (USD)")
    assert not explorer._table.isColumnHidden(column)
    assert cells(explorer, 0)[column] == "248.10+"
    for key in STATUS_COLUMNS:
        assert explorer._table.isColumnHidden(explorer._model.figure_column(key))


def test_the_table_is_inset_with_grid_lines_at_its_left_and_top(explorer):
    table = explorer._table
    frame = table.parentWidget()
    inset = frame.frameWidth() + TABLE_INDENT
    assert (table.x(), table.y()) == (inset, inset)
    grid = QColor.fromRgb(
        table.style().styleHint(QStyle.StyleHint.SH_Table_GridLineColor, None, table)
        & 0xFFFFFFFF
    )
    image = frame.grab().toImage()
    rows = table.viewport().mapTo(frame, QPoint(0, table.rowViewportPosition(0)))
    assert image.pixelColor(table.x() - 1, rows.y() + 2).rgb() == grid.rgb()
    below = rows.y() + table.rowViewportPosition(2) + table.rowHeight(2) + 10
    # The line along the top of the headings; the frame is the style's own
    assert image.pixelColor(frame.width() - 1, below).rgb() != grid.rgb()
    assert image.pixelColor(table.x() + 20, table.y() - 1).rgb() == grid.rgb()
    assert image.pixelColor(table.x() - 1, below).rgb() != grid.rgb()


def test_the_headings_are_bold_tinted_and_ruled_off(explorer):
    table = explorer._table
    header = table.horizontalHeader()
    image = header.grab().toImage()
    base = table.palette().color(QPalette.ColorRole.Base)
    middle = header.sectionViewportPosition(1) + 3
    assert image.pixelColor(middle, 2).rgb() != base.rgb()
    grid = QColor.fromRgb(
        table.style().styleHint(QStyle.StyleHint.SH_Table_GridLineColor, None, table)
        & 0xFFFFFFFF
    )
    assert image.pixelColor(middle, header.height() - 1).rgb() == grid.rgb()
    divider = header.sectionViewportPosition(1) + header.sectionSize(1) - 1
    assert image.pixelColor(divider, header.height() // 2).rgb() == grid.rgb()
    assert header.font().bold()


def test_the_grid_is_the_command_outputs_table_blue(explorer):
    assert grid_colour(explorer._table).getRgb()[:3] == TABLE_OUTLINE_RGB_LIGHT
    explorer.set_dark(True)
    assert grid_colour(explorer._table).getRgb()[:3] == TABLE_OUTLINE_RGB_DARK
    image = explorer._table.viewport().grab().toImage()
    rows = explorer._table
    y = rows.rowViewportPosition(0) + rows.rowHeight(0) - 1
    assert image.pixelColor(20, y).getRgb()[:3] == TABLE_OUTLINE_RGB_DARK


def test_a_rule_sets_the_scope_controls_apart(explorer):
    rule = explorer._separator.geometry()
    assert (
        rule.top()
        > explorer._namespace.mapTo(
            explorer, explorer._namespace.rect().bottomLeft()
        ).y()
    )
    assert (
        rule.bottom()
        < explorer._back.mapTo(explorer, explorer._back.rect().topLeft()).y()
    )
    assert explorer._separator.styleSheet() == ""
    explorer.set_dark(True)
    assert explorer._separator.styleSheet() == DARK_SEPARATOR_STYLE
    explorer.set_dark(False)
    assert explorer._separator.styleSheet() == ""


def test_the_window_can_be_maximised_and_minimised(explorer):
    flags = explorer.windowFlags()
    assert flags & Qt.WindowType.WindowMaximizeButtonHint
    assert flags & Qt.WindowType.WindowMinimizeButtonHint
    assert flags & Qt.WindowType.WindowCloseButtonHint


def test_the_dog_is_shown_at_the_top_right(explorer):
    branding = explorer._branding
    pixmap = branding.pixmap()
    assert pixmap is not None and not pixmap.isNull()
    assert branding.size() == QSize(BRANDING_IMAGE_SIZE, BRANDING_IMAGE_SIZE)
    assert branding.geometry().right() > explorer._refresh.geometry().right()
    assert branding.geometry().bottom() < explorer._table.mapTo(explorer, QPoint()).y()


def export_to(explorer, path, monkeypatch, raw: bool = False) -> list[dict]:
    """
    Choose Export CSV's As Shown (or Raw Numbers) with the save dialog
    answering 'path' (None: dismissed), returning what the dialog was asked.
    """
    asked: list[dict] = []

    def save_file(**kwargs):
        asked.append(kwargs)
        return None if path is None else str(path)

    monkeypatch.setattr(explorer._file_dialogs, "save_file", save_file)
    (explorer._export_raw if raw else explorer._export_shown).trigger()
    return asked


def read_csv(path) -> list[list[str]]:
    with open(path, encoding="utf-8", newline="") as file:
        return list(csv.reader(file))


def test_export_offers_raw_numbers_first(explorer):
    menu = explorer._export.menu()
    assert [action.text() for action in menu.actions()] == [
        "Raw Numbers…",
        "As Shown…",
        "",
        "Include Total Row",
    ]
    # The Total row included unless unticked
    assert explorer._export_total.isCheckable()
    assert explorer._export_total.isChecked()


@pytest.mark.parametrize("raw", [True, False])
def test_the_total_row_can_be_left_out_of_an_export(
    explorer, tmp_path, monkeypatch, raw, commander_dialog_settings
):
    explorer._export_total.trigger()
    assert not explorer._export_total.isChecked()
    assert (
        commander_dialog_settings.value(SETTING_EXPLORER_EXPORT_TOTAL, type=bool)
        is False
    )
    target = tmp_path / "out.csv"
    export_to(explorer, target, monkeypatch, raw=raw)
    rows = read_csv(target)
    assert len(rows) == 1 + explorer._model.rowCount() - 1
    assert "Total" not in [row[0] for row in rows[1:]]
    # Ticked again, it is back
    explorer._export_total.trigger()
    export_to(explorer, target, monkeypatch, raw=raw)
    assert read_csv(target)[-1][0] == "Total"


def test_leaving_out_the_total_row_is_remembered(
    qapp, children, tmp_path, commander_dialog_settings
):
    children.answer = usage_answer
    commander_dialog_settings.setValue(SETTING_EXPLORER_EXPORT_TOTAL, False)
    window = UsageExplorer(
        "Usage Explorer", lambda: str(tmp_path), lambda: list(BASE_ARGS), QFont(), False
    )
    try:
        assert not window._export_total.isChecked()
    finally:
        window.shut_down()
        QApplication.processEvents()


def test_export_of_raw_numbers(explorer, tmp_path, monkeypatch):
    target = tmp_path / "raw.csv"
    export_to(explorer, target, monkeypatch, raw=True)
    rows = read_csv(target)
    assert rows[0] == [
        "Namespace",
        "Instances",
        "Running (hours)",
        "Stopped (hours)",
        "Total (hours)",
        "Est. cost (USD)",
        "Unpriced running (hours)",
    ]
    body = json.loads(usage_answer("yd usage", ["--by", "namespace"])[0])
    expected = [
        [
            name,
            str(source["instances"]),
            str(source["hours"]["running"]),
            str(source["hours"]["stopped"]),
            str(source["hours"]["total"]),
            str(source["estimatedCost"]),
            str(source["unpricedRunningHours"]),
        ]
        for name, source in (
            *((g["namespace"], g) for g in body["groups"]),
            ("Total", body["total"]),
        )
    ]
    assert rows[1:] == expected
    assert rows[1][1:3] == ["17", "47.2"]
    assert rows[1][5:] == ["248.1", "0.7"]


def test_a_raw_status_column_is_in_hours(explorer, tmp_path, monkeypatch):
    explorer._show_column("pending", True)
    target = tmp_path / "raw.csv"
    export_to(explorer, target, monkeypatch, raw=True)
    rows = read_csv(target)
    assert rows[0][-1] == "Pending (hours)"
    assert rows[1][-1] == "0.0"


def test_a_raw_export_without_cost_has_no_cost_columns(explorer, tmp_path, monkeypatch):
    explorer._cost.click()
    settle(explorer)
    target = tmp_path / "raw.csv"
    export_to(explorer, target, monkeypatch, raw=True)
    assert read_csv(target)[0][-1] == "Total (hours)"


def test_export_saves_the_table_as_shown(explorer, tmp_path, monkeypatch):
    assert explorer._export.isEnabled()
    target = tmp_path / "out.csv"
    [asked] = export_to(explorer, target, monkeypatch)
    suggested = asked["directory"]
    assert os.path.dirname(suggested) == str(tmp_path)
    assert re.fullmatch(r"usage-\d{8}-\d{6}\.csv", os.path.basename(suggested))
    with open(target, encoding="utf-8", newline="") as file:
        rows = list(csv.reader(file))
    # The status columns are hidden, so not exported
    assert rows[0] == [
        "Namespace",
        "Instances",
        "Running (h:mm)",
        "Stopped (h:mm)",
        "Total (h:mm)",
        "Est. cost (USD)",
    ]
    assert rows[1:] == [
        cells(explorer, row)[: len(rows[0])]
        for row in range(explorer._model.rowCount())
    ]
    assert rows[-1][0] == "Total"
    assert rows[1][-1] == "248.10+"
    assert explorer.log_lines[-1] == f"Saved the Usage Explorer's table to '{target}'"


def test_export_includes_a_status_column_shown(explorer, tmp_path, monkeypatch):
    explorer._show_column("pending", True)
    target = tmp_path / "out.csv"
    export_to(explorer, target, monkeypatch)
    with open(target, encoding="utf-8", newline="") as file:
        assert next(csv.reader(file))[-1] == "Pending (h:mm)"


def test_a_dismissed_export_writes_nothing(explorer, tmp_path, monkeypatch):
    logged = len(explorer.log_lines)
    export_to(explorer, None, monkeypatch)
    assert not list(tmp_path.glob("*.csv"))
    assert len(explorer.log_lines) == logged


def test_a_failed_export_is_said_and_logged(explorer, tmp_path, monkeypatch):
    export_to(explorer, tmp_path, monkeypatch)
    assert explorer.log_lines[-1].startswith(
        f"Could not save the table to '{tmp_path}'"
    )
    assert explorer._notes.text().startswith("Could not save the table")


def test_export_waits_for_a_table(explorer):
    explorer.reset("Usage Explorer — other.toml")
    assert not explorer._export.isEnabled()
    settle(explorer)
    fetch(explorer)
    assert explorer._export.isEnabled()


def shown_headings(explorer) -> list[str]:
    model = explorer._model
    return [
        model.headerData(c, Qt.Orientation.Horizontal)
        for c in range(model.columnCount())
        if not explorer._table.isColumnHidden(c)
    ]


def test_the_column_menu_offers_every_figure_but_the_cost(explorer):
    menu = explorer._column_menu()
    assert [a.text() for a in menu.actions()] == [
        "Instances",
        "Running",
        "Stopped",
        "Total",
        "",
        "Pending",
        "Stopping",
        "Terminating",
        "Unknown",
    ]
    assert [a.isChecked() for a in menu.actions() if not a.isSeparator()] == [
        True,
        True,
        True,
        True,
        False,
        False,
        False,
        False,
    ]


def test_a_figure_column_can_be_hidden_and_stays_so(
    explorer, children, tmp_path, monkeypatch, commander_dialog_settings
):
    [stopped] = [a for a in explorer._column_menu().actions() if a.text() == "Stopped"]
    stopped.trigger()
    assert shown_headings(explorer) == [
        "Namespace",
        "Instances",
        "Running (h:mm)",
        "Total (h:mm)",
        "Est. cost (USD)",
    ]
    assert commander_dialog_settings.value(SETTING_EXPLORER_HIDDEN_COLUMNS) == (
        "stopped,pending,stopping,terminating,unknown"
    )
    # Hidden at the next level, and with the cost column taken away
    double_click_row(explorer, 0)
    settle(explorer)
    assert "Stopped (h:mm)" not in shown_headings(explorer)
    explorer._cost.click()
    settle(explorer)
    assert shown_headings(explorer)[-1] == "Total (h:mm)"
    target = tmp_path / "out.csv"
    export_to(explorer, target, monkeypatch, raw=True)
    assert "Stopped (hours)" not in read_csv(target)[0]


def reports_runs(children) -> int:
    return len([a for c, a in children.started if "--reports" in a])


def test_kept_reports_lists_them_the_last_fetched_first(explorer, children):
    assert explorer._kept.isEnabled()
    labels = [a.text() for a in explorer._kept.menu().actions()]
    assert labels == [
        f"2026-10-01 00:00 \u2192 2026-11-01 00:00 UTC{KEPT_SEPARATOR}team-render",
        f"2026-11-18 15:02 \u2192 2026-11-25 15:02 UTC{KEPT_SEPARATOR}All namespaces",
    ]
    [args] = [a for c, a in children.started if "--reports" in a][:1]
    assert args == [*BASE_ARGS, "--reports"]


def test_choosing_a_kept_report_shows_it_at_once(explorer, children):
    double_click_row(explorer, 0)
    settle(explorer)
    explorer._kept.menu().actions()[0].trigger()
    QApplication.processEvents()
    assert explorer._preset.currentText() == "Custom"
    # Written to the minute, as the report line shows times
    assert (explorer._from.text(), explorer._until.text()) == (
        "2026-10-01 00:00 UTC",
        "2026-11-01 00:00 UTC",
    )
    assert explorer._namespace.currentText() == "team-render"
    # No Fetch Report: it is used again, at the top level
    assert not explorer._fetch_overlay.isVisible()
    settle(explorer)
    assert explorer.breadcrumb_text() == "All"
    args = usage_args(children)
    assert args[:4] == [
        "--from",
        "2026-10-01 00:00 UTC",
        "--until",
        "2026-11-01 00:00 UTC",
    ]
    assert value_of(args, "-n") == "team-render"


def test_kept_reports_is_listed_again_after_a_fetch_only(explorer, children):
    listed = reports_runs(children)
    # A regroup of the report shown reuses it: no new report kept
    double_click_row(explorer, 0)
    settle(explorer)
    assert reports_runs(children) == listed
    explorer._refresh.click()
    settle(explorer)
    assert reports_runs(children) == listed + 1


def test_with_none_kept_the_button_is_disabled(qapp, children, tmp_path):
    def none_kept(command, args):
        if "--reports" in args:
            return "[]", "", 0, 0
        return usage_answer(command, args)

    children.answer = none_kept
    window = UsageExplorer(
        "Usage Explorer", lambda: str(tmp_path), lambda: list(BASE_ARGS), QFont(), False
    )
    try:
        settle(window)
        assert not window._kept.isEnabled()
        assert window._kept.menu().actions() == []
    finally:
        window.shut_down()
        QApplication.processEvents()


def test_a_partial_account_report_says_which_namespaces(explorer, children):
    assert (
        "Reporting on the 2 namespaces this Application can read usage in:"
        " team-render, team-sim" in explorer._notes.text()
    )

    def named(command, args):
        out, err, code, delay = usage_answer(command, args)
        body = json.loads(out)
        body["namespace"] = value_of(args, "-n")
        return json.dumps(body), err, code, delay

    children.answer = named
    explorer._namespace.setCurrentText("team-render")
    explorer._namespace.activated.emit(0)
    fetch(explorer)
    assert "Reporting on" not in explorer._notes.text()


def test_warnings_of_a_successful_run_are_shown(explorer, children):
    def warned(command, args):
        out, _, code, delay = usage_answer(command, args)
        return out, "WARNING : Creators are shown by ID\n", code, delay

    children.answer = warned
    explorer._rerun()
    settle(explorer)
    assert "Creators are shown by ID" in explorer._notes.text()
    assert "WARNING" not in explorer._notes.text()


def test_the_first_click_on_total_reverses_its_order(explorer, children):
    click_heading(explorer, "Total")
    settle(explorer)
    args = usage_args(children)
    assert value_of(args, "--sort") == "total" and "--reverse" in args


# Opened from the main window ----------------------------------------------


@pytest.fixture
def window(qapp, children):
    children.answer = usage_answer
    window = YellowDogApp()
    gui_harness.shown(window)
    # The deferred start-up selection of the configuration file runs first,
    # or it would replace the one a test selects
    QApplication.processEvents()
    yield window
    window.shutdown()
    window.close()


@pytest.fixture
def config(window, tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[common]\n", encoding="utf-8")
    window._set_config_file(str(path))
    return path


def usage_children(children) -> list[list[str]]:
    return [args for command, args in children.started if is_view(command, args)]


def test_the_button_needs_a_configuration(window):
    assert not window.show_usage_explorer.isEnabled()


def test_the_button_follows_the_configuration_selection(window, config):
    assert window.show_usage_explorer.isEnabled()
    window._deselect_config_file()
    assert not window.show_usage_explorer.isEnabled()


def test_the_button_opens_one_explorer_and_raises_it(window, config, children):
    window.show_usage_explorer.click()
    explorer = window._usage_explorer
    assert explorer is not None and explorer.isVisible()
    assert explorer.parent() is None
    assert explorer.windowTitle() == f"Usage Explorer \N{EM DASH} {config}"
    settle(explorer)
    # No report until asked for
    assert usage_children(children) == []
    fetch(explorer)
    window.show_usage_explorer.click()
    assert window._usage_explorer is explorer
    settle(explorer)
    assert len(usage_children(children)) == 1
    # Closing it forgets it, so the button makes another
    explorer.close()
    assert window._usage_explorer is None
    window.show_usage_explorer.click()
    assert window._usage_explorer is not explorer
    settle(window._usage_explorer)


def test_the_explorer_ignores_commanders_namespace_override(window, config, children):
    window.namespace_override.setPlainText("team-override")
    window.tag_override.setPlainText("tag-override")
    window.user_variables.setPlainText("a=1 b=2")
    window.properties.setPlainText("common.requestTimeout=30")
    window.show_usage_explorer.click()
    settle(window._usage_explorer)
    fetch(window._usage_explorer)
    expected = [
        "-c",
        "config.toml",
        "--nf",
        "-q",
        "--json",
        # No '-v': yd usage takes none (a command is given what it offers)
        "--property=common.requestTimeout=30",
    ]
    for command, args in children.started:
        assert args[: len(expected)] == expected
        assert "team-override" not in args and "tag-override" not in args
        assert "a=1" not in args
    assert {command for command, _ in children.started} == {"yd list", "yd usage"}


def test_a_new_configuration_resets_the_explorer(window, config, children, tmp_path):
    window.show_usage_explorer.click()
    explorer = window._usage_explorer
    settle(explorer)
    fetch(explorer)
    double_click_row(explorer, 0)
    settle(explorer)
    assert explorer.breadcrumb_text() != "All"
    runs = len(usage_children(children))
    other = tmp_path / "other.toml"
    other.write_text("[common]\n", encoding="utf-8")
    window._set_config_file(str(other))
    settle(explorer)
    assert window._usage_explorer is explorer
    assert explorer.windowTitle() == f"Usage Explorer \N{EM DASH} {other}"
    assert explorer.breadcrumb_text() == "All"
    assert len(usage_children(children)) == runs
    fetch(explorer)
    assert len(usage_children(children)) == runs + 1
    assert usage_children(children)[-1][:2] == ["-c", "other.toml"]


def test_deselecting_the_configuration_closes_the_explorer(window, config):
    window.show_usage_explorer.click()
    settle(window._usage_explorer)
    window._deselect_config_file()
    assert window._usage_explorer is None
    assert not window.show_usage_explorer.isEnabled()


def test_the_button_refuses_an_unusable_properties_field(window, config, children):
    window.properties.setPlainText("'common.requestTimeout=30")
    window.show_usage_explorer.click()
    assert window._usage_explorer is None
    assert children.started == []


def test_a_later_unusable_properties_field_fails_the_run(window, config, children):
    window.show_usage_explorer.click()
    explorer = window._usage_explorer
    settle(explorer)
    runs = len(usage_children(children))
    logged: list[str] = []
    explorer.logged.connect(logged.append)
    window.properties.setPlainText("'common.requestTimeout=30")
    explorer._rerun()
    QApplication.processEvents()
    assert len(usage_children(children)) == runs
    assert explorer._notes.text().startswith("The Properties field cannot be split: ")
    assert explorer._error_showing
    assert any(
        "yd usage failed" in line and "The Properties field cannot be split" in line
        for line in logged
    )
    # A usable field runs again
    window.properties.setPlainText("")
    explorer._rerun()
    settle(explorer)
    assert len(usage_children(children)) == runs + 1
    assert not explorer._error_showing


def test_quitting_stops_a_running_view(window, config, children):
    children.answer = lambda command, args: (*usage_answer(command, args)[:3], 30)
    window.show_usage_explorer.click()
    explorer = window._usage_explorer
    explorer._fetch.click()
    wait_for(lambda: explorer._runner.running())
    processes = [
        run.process
        for runner in (explorer._runner, explorer._namespace_runner)
        for run in runner._runs.values()
    ]
    assert processes
    window.shutdown()
    QApplication.processEvents()
    assert sip.isdeleted(explorer) or not explorer.isVisible()
    assert all(
        sip.isdeleted(process) or process.state() == QProcess.ProcessState.NotRunning
        for process in processes
    )


def test_dark_mode_reaches_the_explorer_and_zoom_does_not(window, config, children):
    window.show_usage_explorer.click()
    explorer = window._usage_explorer
    settle(explorer)
    assert not explorer._dark
    before = window._output_font.pointSize()
    window.dark_mode.setChecked(True)
    window._dark_mode_action(Qt.CheckState.Checked)
    try:
        assert explorer._dark
    finally:
        window.dark_mode.setChecked(False)
        window._dark_mode_action(Qt.CheckState.Unchecked)
    assert not explorer._dark
    window._zoom_output(1)
    assert window._output_font.pointSize() == before + 1
    # The table's text has a size of its own
    assert explorer._table.font().pointSize() == commander.OUTPUT_FONT_SIZE


def test_the_explorers_text_size_is_its_own(
    window, config, children, commander_dialog_settings
):
    window.show_usage_explorer.click()
    explorer = window._usage_explorer
    settle(explorer)
    fetch(explorer)
    output = window._output_font.pointSize()
    table = explorer._table
    row = table.rowHeight(0)
    assert table.font().pointSize() == commander.OUTPUT_FONT_SIZE
    for key, size in (
        (Qt.Key.Key_Equal, commander.OUTPUT_FONT_SIZE + 1),
        (Qt.Key.Key_Equal, commander.OUTPUT_FONT_SIZE + 2),
        (Qt.Key.Key_Minus, commander.OUTPUT_FONT_SIZE + 1),
    ):
        QTest.keyClick(table, key, Qt.KeyboardModifier.ControlModifier)
        assert table.font().pointSize() == size
    assert table.rowHeight(0) > row
    assert window._output_font.pointSize() == output
    assert (
        commander_dialog_settings.value(SETTING_EXPLORER_FONT_SIZE, type=int)
        == commander.OUTPUT_FONT_SIZE + 1
    )
    for _ in range(commander.MAX_OUTPUT_FONT_SIZE):
        QTest.keyClick(table, Qt.Key.Key_Equal, Qt.KeyboardModifier.ControlModifier)
    assert table.font().pointSize() == commander.MAX_OUTPUT_FONT_SIZE
    QTest.keyClick(table, Qt.Key.Key_0, Qt.KeyboardModifier.ControlModifier)
    assert table.font().pointSize() == commander.OUTPUT_FONT_SIZE
    assert table.rowHeight(0) == row


def test_the_explorer_opens_at_its_remembered_text_size(
    qapp, children, tmp_path, commander_dialog_settings
):
    children.answer = usage_answer
    commander_dialog_settings.setValue(SETTING_EXPLORER_FONT_SIZE, 99)
    font = QFont()
    font.setPointSize(12)
    window = UsageExplorer(
        "Usage Explorer", lambda: str(tmp_path), lambda: list(BASE_ARGS), font, False
    )
    try:
        settle(window)
        assert window._table.font().pointSize() == commander.MAX_OUTPUT_FONT_SIZE
    finally:
        window.shut_down()
        QApplication.processEvents()


def test_an_older_runs_result_does_not_replace_the_unusable_failure(
    window, config, children
):
    window.show_usage_explorer.click()
    explorer = window._usage_explorer
    settle(explorer)
    rows = [cells(explorer, row) for row in range(explorer._model.rowCount())]
    crumbs = explorer.breadcrumb_text()
    # A slow run in flight, then the properties break and another is requested
    children.answer = lambda command, args: (*usage_answer(command, args)[:3], 1.0)
    explorer._rerun()
    wait_for(lambda: explorer._runner.running())
    window.properties.setPlainText("'common.requestTimeout=30")
    explorer._rerun()
    # Wait for the slow child to finish; its result is the older request's
    time.sleep(1.3)
    wait_for(lambda: not explorer._runner._runs)
    QApplication.processEvents()
    assert explorer._notes.text().startswith("The Properties field cannot be split: ")
    assert explorer._error_showing
    assert [cells(explorer, row) for row in range(explorer._model.rowCount())] == rows
    assert explorer.breadcrumb_text() == crumbs
