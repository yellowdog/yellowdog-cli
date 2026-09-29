"""
Tests for Commander's Resize button: 'yd-resize' on a Worker Pool chosen from a
list, with the target node count given in the same dialog. The listing is
stubbed at _capture_json and the command at _run_command_in_subprocess; the
dialog is the real one, driven inside its real modal loop.
"""

import sys

import pytest
import qt_guard

qt_guard.require_qt()

import commander_dialogs
import gui_harness
from PyQt6.QtCore import QEventLoop, QPoint, QProcess, QTimer
from PyQt6.QtWidgets import QApplication, QLabel

from yellowdog_cli.commander.commander import (
    MAX_SPIN_NODES,
    NO_LISTING_TAG,
    YellowDogApp,
)
from yellowdog_cli.commander.selection import (
    AWAITING_NODES_NOTE,
    PROVISIONED_WORKER_POOL_TYPE,
    parse_resizable_pools,
    pool_rows,
)
from yellowdog_cli.commander.startup import StartupSettings


def pool(n: int, expected: int, lo: int, hi: int | None, created: str) -> dict:
    return {
        "type": PROVISIONED_WORKER_POOL_TYPE,
        "id": f"ydid:wrkrpool:{n}",
        "name": f"wp-{n}",
        "status": "RUNNING",
        "createdTime": created,
        "expectedNodeCount": expected,
        "properties": {"minNodes": lo, "maxNodes": hi},
    }


OLDER = pool(1, 3, 0, 10, "2026-09-28T10:00:00.000Z")
NEWER = pool(2, 1, 1, 4, "2026-09-29T10:00:00.000Z")
UNBOUNDED = pool(3, 2, 0, None, "2026-09-27T10:00:00.000Z")
AWAITING = dict(
    pool(4, 0, 0, 10, "2026-09-30T10:00:00.000Z"), status="PENDING", awaitingNodes=True
)
AWAITING_ERROR = (
    "InvalidRequestException: Cannot resize worker pool whilst it is awaiting"
    " nodes {ydid:wrkrpool:4}"
)
CONFIGURED = {
    "type": "co.yellowdog.platform.model.ConfiguredWorkerPool",
    "id": "ydid:wrkrpool:9",
    "name": "on-prem",
    "status": "EMPTY",
    "expectedNodeCount": 1,
    "properties": {"targetNodeCount": 1},
}


def make_window(settings: StartupSettings | None = None) -> YellowDogApp:
    window = YellowDogApp(settings) if settings else YellowDogApp()
    window._discovery.tag = "pwt"
    return window


@pytest.fixture
def window(qapp):
    return make_window()


@pytest.fixture
def captured(window, monkeypatch):
    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        window,
        "_run_command_in_subprocess",
        lambda command, args, **kwargs: calls.append((command, args)),
    )
    return calls


def listed(window, monkeypatch, rows) -> list:
    asked: list = []

    def capture(command, flags, extra_args=None):
        asked.append((command, flags, extra_args))
        return rows

    monkeypatch.setattr(window, "_capture_json", capture)
    return asked


def log(window) -> str:
    return window.log_output.toPlainText()


# --- The listing -------------------------------------------------------------


def test_lists_the_active_worker_pools_in_full(window, captured, monkeypatch):
    # Only the full Worker Pool carries the node count and its bounds, and
    # 'yd-list' lists every pool in the namespace unless it is given the tag.
    asked = listed(window, monkeypatch, [])
    window._resize_worker_pool_action()
    assert asked == [
        (
            "yd-list",
            ["--json"],
            ["worker-pools", "--active-only", "--details", "-t", "pwt"],
        )
    ]


def test_the_name_pattern_narrows_the_listing(window, captured, monkeypatch):
    asked = listed(window, monkeypatch, [])
    window.name_glob_override.setPlainText("wp-*")
    window._resize_worker_pool_action()
    assert asked[0][2][-2:] == ["--name", "wp-*"]


def test_without_a_tag_nothing_is_listed(window, captured, monkeypatch):
    asked = listed(window, monkeypatch, [OLDER])
    window._discovery.tag = None
    window._resize_worker_pool_action()
    assert asked == [] and captured == []
    assert NO_LISTING_TAG in log(window)


# --- The dialog --------------------------------------------------------------


def test_resizing_runs_yd_resize_with_the_ydid_and_count(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER, NEWER])
    commander_dialogs.drive_resize(
        window, monkeypatch, commander_dialogs.ACCEPT, choose=0, nodes=5
    )
    window._resize_worker_pool_action()
    assert captured == [("yd-resize", ["-y", OLDER["id"], "5"])]


def test_the_newest_is_chosen_with_its_own_count_and_bounds(
    window, captured, monkeypatch
):
    listed(window, monkeypatch, [OLDER, NEWER])
    seen: dict = {}

    def inspect(dialog):
        spin = commander_dialogs.target_nodes(dialog)
        rows = commander_dialogs.choice_listing(dialog)
        seen["selected"] = [item.text() for item in rows.selectedItems()]
        seen["spin"] = (spin.value(), spin.minimum(), spin.maximum())

    commander_dialogs.drive_resize(
        window, monkeypatch, commander_dialogs.CANCEL, inspect=inspect
    )
    window._resize_worker_pool_action()
    assert seen["selected"][0].startswith("wp-2")
    assert seen["spin"] == (1, 1, 4)


def test_the_count_follows_the_selection(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER, NEWER])
    seen: dict = {}

    def inspect(dialog):
        spin = commander_dialogs.target_nodes(dialog)
        seen["spin"] = (spin.value(), spin.minimum(), spin.maximum())

    commander_dialogs.drive_resize(
        window, monkeypatch, commander_dialogs.CANCEL, choose=0, inspect=inspect
    )
    window._resize_worker_pool_action()
    assert seen["spin"] == (3, 0, 10)


def test_a_pool_without_a_maximum_gets_the_spin_box_ceiling(
    window, captured, monkeypatch
):
    listed(window, monkeypatch, [UNBOUNDED])
    seen: list = []

    def inspect(dialog):
        seen.append(commander_dialogs.target_nodes(dialog).maximum())

    commander_dialogs.drive_resize(
        window, monkeypatch, commander_dialogs.CANCEL, inspect=inspect
    )
    window._resize_worker_pool_action()
    assert seen == [MAX_SPIN_NODES]


def test_resize_is_greyed_while_the_count_is_unchanged(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER])
    states: list[bool] = []

    def inspect(dialog):
        resize = gui_harness.button_labelled(dialog, "Resize")
        spin = commander_dialogs.target_nodes(dialog)
        states.append(resize.isEnabled())
        spin.setValue(4)
        states.append(resize.isEnabled())
        spin.setValue(3)
        states.append(resize.isEnabled())

    commander_dialogs.drive_resize(
        window, monkeypatch, commander_dialogs.CANCEL, inspect=inspect
    )
    window._resize_worker_pool_action()
    assert states == [False, True, False]


def test_resize_is_greyed_with_nothing_selected(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER])
    states: list[bool] = []

    def inspect(dialog):
        commander_dialogs.target_nodes(dialog).setValue(5)
        commander_dialogs.choice_listing(dialog).clearSelection()
        states.append(gui_harness.button_labelled(dialog, "Resize").isEnabled())

    commander_dialogs.drive_resize(
        window, monkeypatch, commander_dialogs.CANCEL, inspect=inspect
    )
    window._resize_worker_pool_action()
    assert states == [False]


def test_scaling_down_warns(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER])
    shown: list[bool] = []

    def inspect(dialog):
        warning = dialog.findChild(QLabel, "scale_down_warning")
        spin = commander_dialogs.target_nodes(dialog)
        shown.append(warning.isVisible())
        spin.setValue(5)
        shown.append(warning.isVisible())
        spin.setValue(1)
        shown.append(warning.isVisible())

    commander_dialogs.drive_resize(
        window, monkeypatch, commander_dialogs.CANCEL, inspect=inspect
    )
    window._resize_worker_pool_action()
    assert shown == [False, False, True]


def test_cancelling_resizes_nothing(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER])
    commander_dialogs.drive_resize(
        window, monkeypatch, commander_dialogs.CANCEL, nodes=5
    )
    window._resize_worker_pool_action()
    assert captured == []


def test_the_panel_3_checkboxes_do_not_apply(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER])
    window.follow_worker_pool.setChecked(True)
    window.dry_run_worker_pool.setChecked(True)
    commander_dialogs.drive_resize(
        window, monkeypatch, commander_dialogs.ACCEPT, nodes=5
    )
    window._resize_worker_pool_action()
    assert captured == [("yd-resize", ["-y", OLDER["id"], "5"])]


def test_yes_still_shows_the_dialog(qapp, monkeypatch):
    # The dialog is the only place a node count can be given.
    window = make_window(StartupSettings(disable_confirmations=True))
    calls: list = []
    monkeypatch.setattr(
        window,
        "_run_command_in_subprocess",
        lambda command, args, **kwargs: calls.append((command, args)),
    )
    listed(window, monkeypatch, [OLDER])
    commander_dialogs.drive_resize(
        window, monkeypatch, commander_dialogs.ACCEPT, nodes=2
    )
    window._resize_worker_pool_action()
    assert calls == [("yd-resize", ["-y", OLDER["id"], "2"])]


# --- Room for the text -----------------------------------------------------------
# Reported: the message and the warning were clipped, top and bottom, and the
# spin box was too narrow for its digit. A word-wrapped label is sized before it
# knows its width, and the warning appeared after the dialog had taken its size.

LONG_POOL = dict(OLDER, name="pyex-bash-pwt_260929-1350413-vg", expectedNodeCount=2)


def clipped_labels(dialog) -> dict:
    return {
        label.text()[:30]: (label.height(), label.heightForWidth(label.width()))
        for label in dialog.findChildren(QLabel)
        if label.wordWrap()
        and label.isVisible()
        and label.height() < label.heightForWidth(label.width())
    }


def test_no_text_is_clipped_when_the_warning_appears(window, captured, monkeypatch):
    listed(window, monkeypatch, [LONG_POOL])
    seen: dict = {}

    def inspect(dialog):
        QApplication.processEvents()
        seen["before"] = clipped_labels(dialog), dialog.height()
        commander_dialogs.target_nodes(dialog).setValue(1)
        QApplication.processEvents()
        seen["after"] = clipped_labels(dialog), dialog.height()

    commander_dialogs.drive_resize(
        window, monkeypatch, commander_dialogs.CANCEL, inspect=inspect
    )
    window.namespace_override.setPlainText("yd-demo")
    window._resize_worker_pool_action()
    assert seen["before"][0] == {}, f"clipped: {seen['before'][0]}"
    assert seen["after"][0] == {}, f"clipped: {seen['after'][0]}"
    assert seen["before"][1] == seen["after"][1], "the dialog jumped"


def test_the_spin_box_has_room_for_any_count(window, captured, monkeypatch):
    # Sized by its range, a pool with a maximum of 5 got a box one digit wide,
    # and a narrow one at that.
    from PyQt6.QtWidgets import QSpinBox

    listed(window, monkeypatch, [NEWER])
    widths: list = []

    def inspect(dialog):
        QApplication.processEvents()
        probe = QSpinBox()
        probe.setRange(0, MAX_SPIN_NODES)
        widths.append(
            (commander_dialogs.target_nodes(dialog).width(), probe.sizeHint().width())
        )

    commander_dialogs.drive_resize(
        window, monkeypatch, commander_dialogs.CANCEL, inspect=inspect
    )
    window._resize_worker_pool_action()
    assert widths[0][0] >= widths[0][1]


# --- Pools awaiting nodes ------------------------------------------------------
# The platform refuses to resize one: 'Cannot resize worker pool whilst it is
# awaiting nodes'.


def test_a_pool_awaiting_nodes_is_listed_but_cannot_be_chosen(
    window, captured, monkeypatch
):
    # AWAITING is the newest, so it would be the default were it choosable.
    listed(window, monkeypatch, [OLDER, AWAITING])
    seen: dict = {}

    def inspect(dialog):
        rows = commander_dialogs.choice_listing(dialog)
        awaiting = rows.item(1)
        seen["text"] = awaiting.text()
        seen["enabled"] = (
            awaiting.isSelected(),
            bool(awaiting.flags() & awaiting.flags().ItemIsSelectable),
        )
        seen["default"] = [item.text() for item in rows.selectedItems()]
        # Asking for it from code clears the selection (a click on a disabled
        # row does nothing at all); either way it is never the one chosen.
        rows.setCurrentRow(1)
        seen["after"] = [item.text() for item in rows.selectedItems()]
        seen["resize"] = gui_harness.button_labelled(dialog, "Resize").isEnabled()

    commander_dialogs.drive_resize(
        window, monkeypatch, commander_dialogs.CANCEL, inspect=inspect
    )
    window._resize_worker_pool_action()
    assert AWAITING_NODES_NOTE in seen["text"]
    assert seen["enabled"] == (False, False)
    assert seen["default"][0].startswith("wp-1")
    assert not any(text.startswith("wp-4") for text in seen["after"])
    assert seen["resize"] is False


def test_when_every_pool_is_awaiting_nodes_no_dialog_opens(
    window, captured, monkeypatch
):
    listed(window, monkeypatch, [AWAITING])
    opened: list = []
    monkeypatch.setattr(
        window, "_build_resize_dialog", lambda *a, **k: opened.append(a)
    )
    window._resize_worker_pool_action()
    assert opened == [] and captured == []
    assert "all awaiting nodes" in log(window)


def test_a_pool_that_starts_awaiting_nodes_after_the_listing_reports_the_error(
    qapp, monkeypatch
):
    # The listing said it could be resized; by the time 'yd-resize' ran it was
    # awaiting nodes. Nothing Commander can check prevents that, so the platform's
    # refusal has to reach the output window, from a real child process.
    window = make_window()
    listed(window, monkeypatch, [OLDER])
    real_run = window._run_command_in_subprocess
    ran: list = []

    def fail_like_the_platform(command, args, **kwargs):
        ran.append((command, args))
        real_run(
            sys.executable,
            [
                "-c",
                "import sys; sys.stderr.write(bytes.fromhex(sys.argv[1]).decode());"
                " sys.exit(1)",
                AWAITING_ERROR.encode().hex(),
            ],
            yd_command=False,
        )

    monkeypatch.setattr(window, "_run_command_in_subprocess", fail_like_the_platform)
    commander_dialogs.drive_resize(
        window, monkeypatch, commander_dialogs.ACCEPT, nodes=5
    )
    window._resize_worker_pool_action()

    process: QProcess = window._processes[-1]
    loop = QEventLoop()
    process.finished.connect(loop.quit)
    QTimer.singleShot(10_000, loop.quit)
    if process.state() != QProcess.ProcessState.NotRunning:
        loop.exec()
    QApplication.processEvents()

    assert ran == [("yd-resize", ["-y", OLDER["id"], "5"])]
    assert AWAITING_ERROR in log(window)


# --- Refusing rather than guessing -------------------------------------------


def test_a_failed_listing_resizes_nothing(window, captured, monkeypatch):
    listed(window, monkeypatch, None)
    window._resize_worker_pool_action()
    assert captured == []
    assert "Could not list the Worker Pools to resize" in log(window)


def test_rows_without_ydids_resize_nothing(window, captured, monkeypatch):
    listed(window, monkeypatch, [{"name": "wp-no-id"}])
    window._resize_worker_pool_action()
    assert captured == []
    assert "Could not list the Worker Pools to resize" in log(window)


def test_configured_pools_are_left_out_and_said_so(window, captured, monkeypatch):
    listed(window, monkeypatch, [CONFIGURED])
    window._resize_worker_pool_action()
    assert captured == []
    assert "No active Worker Pools" in log(window)
    assert "1 Configured Worker Pool(s) matched" in log(window)


def test_nothing_to_resize_is_a_log_line(window, captured, monkeypatch):
    listed(window, monkeypatch, [])
    shown = commander_dialogs.drive_notice(window, monkeypatch)
    window._resize_worker_pool_action()
    assert captured == [] and shown["count"] == 0
    assert "No active Worker Pools" in log(window)
    assert "Configured" not in log(window)


def test_an_operation_in_flight_refuses(window, captured, monkeypatch):
    asked = listed(window, monkeypatch, [OLDER])
    window._nested_depth = 1
    window._resize_worker_pool_action()
    assert asked == [] and captured == []
    assert "ignoring Resize Worker Pool" in log(window)


# --- Parsing and rows ----------------------------------------------------------


def test_parsing_keeps_provisioned_pools_and_counts_configured_ones():
    pools, configured = parse_resizable_pools([OLDER, CONFIGURED, UNBOUNDED])
    assert [p.id for p in pools] == [OLDER["id"], UNBOUNDED["id"]]
    assert configured == 1
    assert (pools[0].expected_nodes, pools[0].min_nodes, pools[0].max_nodes) == (
        3,
        0,
        10,
    )
    assert pools[1].max_nodes is None
    assert not pools[0].awaiting_nodes
    assert parse_resizable_pools([AWAITING])[0][0].awaiting_nodes


def test_parsing_refuses_rows_without_ids():
    assert parse_resizable_pools([OLDER, {"name": "x"}]) is None
    assert parse_resizable_pools(["not a dict"]) is None


def test_rows_align_their_columns():
    pools, _ = parse_resizable_pools([OLDER, dict(NEWER, name="wp-longer-name")])
    rows = pool_rows(pools)
    assert rows[0].display == "wp-1            RUNNING  3 nodes (0-10)"
    assert rows[1].display == "wp-longer-name  RUNNING  1 node (1-4)"
    assert OLDER["id"] in rows[0].tooltip


def test_a_row_without_a_maximum_gives_the_minimum():
    pools, _ = parse_resizable_pools([UNBOUNDED])
    assert pool_rows(pools)[0].display.endswith("2 nodes (min 0)")


# --- Layout ------------------------------------------------------------------


def test_resize_sits_beside_create(qapp):
    win = gui_harness.shown(YellowDogApp())
    QApplication.processEvents()
    create = win.create_worker_pool.mapTo(win, QPoint(0, 0))
    resize = win.resize_worker_pool.mapTo(win, QPoint(0, 0))
    assert resize.y() == create.y() and resize.x() > create.x()
    for button in (win.create_worker_pool, win.resize_worker_pool):
        assert button.width() >= button.sizeHint().width(), button.objectName()
