"""
Panel 3 of YellowDogApp (see commander.py).
"""

from os.path import abspath
from typing import cast

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from yellowdog_cli.commander.selection import (
    ResizablePool,
    newest_entity_id,
    parse_resizable_pools,
    pool_rows,
)
from yellowdog_cli.commander.window_base import CWD, NO_LISTING_TAG
from yellowdog_cli.commander.window_dialogs import DIALOG_SECTION_SPACING, WindowDialogs

SELECTED_WP_PREFIX = "Worker Pool: "
RESIZE_DIALOG_TITLE = "Resize Worker Pool"
SCALE_DOWN_WARNING = (
    "Fewer nodes than now: nodes will be shut down, and any tasks running on"
    " them may be interrupted."
)
# The spin box's ceiling for a Worker Pool that sets no maximum of its own
MAX_SPIN_NODES = 10_000
WP_DATA = "workerPoolData"


class ComputePanel(WindowDialogs):
    """
    Panel 3, Provisioning and Managing Compute: selecting a Worker Pool file,
    Provision, Resize, Shut Down and Terminate, and showing the file.
    """

    def _show_wp_selection(self):
        self._show_selection_on_button(
            self.select_worker_pool,
            SELECTED_WP_PREFIX,
            self._select_wp_default_text,
            self._select_wp_default_tooltip,
            self._wp_file,
        )

    def _select_worker_pool_action(self):
        directory = CWD if self._config_file is None else self._config_dir()
        file = self._file_dialogs.select_file(
            caption="Please select a Worker Pool definition file",
            directory=directory,
            file_pattern="*.json *.jsonnet",
        )
        if file is None:
            self._output.log("No Worker Pool definition file selected")
        else:
            self._set_wp_file(file)

    def _set_wp_file(self, file: str):
        """
        Select a Worker Pool definition, from the Select button or the command
        line. Stored absolute; see the note on _wr_file in __init__.
        """
        self._wp_file = abspath(file)
        self._output.log(f"Selected Worker Pool definition '{self._wp_file}'")
        self._show_wp_selection()

    def _build_resize_dialog(
        self,
        message: str,
        pools: list[ResizablePool],
        selected: str | None = None,
    ) -> tuple[QDialog, QPushButton]:
        """
        Build (but do not show) the resize dialog: the single-choice listing of
        'pools', a 'Target nodes' spin box and Cancel / Resize. Returns the
        dialog and the Resize button.

        The spin box follows the selection, bounded by the selected pool's
        minimum and maximum and set to the node count it expects now. Resize
        is greyed while that count is unchanged, since the resize would do
        nothing, and a warning shows while the count is below it. 'pools' must
        be non-empty.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle(RESIZE_DIALOG_TITLE)
        layout = QVBoxLayout(dialog)
        self._size_dialog_to_its_text(layout)

        message_label = QLabel(message)
        message_label.setWordWrap(True)
        layout.addWidget(message_label)
        layout.addSpacing(DIALOG_SECTION_SPACING)

        rows = pool_rows(pools)
        listing = self._new_single_choice_listing(rows)
        layout.addWidget(listing)
        layout.addSpacing(DIALOG_SECTION_SPACING)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Target nodes:"))
        spin = QSpinBox()
        spin.setObjectName("target_nodes")
        # Sized by its range, a pool with a maximum of 5 would get a box one
        # narrow digit wide; sized for the ceiling, every pool gets the same
        # box and any count fits it.
        probe = QSpinBox()
        probe.setRange(0, MAX_SPIN_NODES)
        spin.setMinimumWidth(probe.sizeHint().width())
        size_row.addWidget(spin)
        size_row.addStretch(1)
        layout.addLayout(size_row)

        # Its room is kept while it is hidden, so the dialog is the same size
        # whether or not it shows, and nothing is clipped when it appears.
        warning = QLabel(SCALE_DOWN_WARNING)
        warning.setObjectName("scale_down_warning")
        warning.setWordWrap(True)
        policy = warning.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        warning.setSizePolicy(policy)
        layout.addWidget(warning)

        button_box = QDialogButtonBox(dialog)
        button_box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        resize_btn = cast(
            QPushButton,
            button_box.addButton("Resize", QDialogButtonBox.ButtonRole.AcceptRole),
        )
        resize_btn.setDefault(True)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        by_id = {pool.id: pool for pool in pools}

        def current() -> ResizablePool | None:
            chosen = listing.selectedItems()
            return by_id[chosen[0].data(Qt.ItemDataRole.UserRole)] if chosen else None

        def refresh() -> None:
            pool = current()
            changed = pool is not None and spin.value() != pool.expected_nodes
            resize_btn.setEnabled(changed)
            warning.setVisible(pool is not None and spin.value() < pool.expected_nodes)

        def follow_selection() -> None:
            pool = current()
            if pool is not None:
                spin.setRange(
                    pool.min_nodes,
                    MAX_SPIN_NODES if pool.max_nodes is None else pool.max_nodes,
                )
                spin.setValue(pool.expected_nodes)
            refresh()

        listing.itemSelectionChanged.connect(follow_selection)
        spin.valueChanged.connect(lambda _value: refresh())

        self._select_row(listing, rows, selected)
        follow_selection()

        return dialog, resize_btn

    def _choose_pool_size(
        self, message: str, pools: list[ResizablePool], selected: str | None = None
    ) -> tuple[str, int] | None:
        """
        Offer the resize dialog and return the chosen pool's YDID and target
        node count, or None if the user dismissed it.
        """
        dialog, _resize_btn = self._build_resize_dialog(message, pools, selected)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted.value:
                return None
            listing = cast(QListWidget, dialog.findChild(QListWidget, "choice_list"))
            spin = cast(QSpinBox, dialog.findChild(QSpinBox, "target_nodes"))
            chosen = listing.selectedItems()
            if not chosen:
                return None
            return chosen[0].data(Qt.ItemDataRole.UserRole), spin.value()
        finally:
            dialog.deleteLater()

    def _create_worker_pool_action(self):
        if not self._properties_are_usable():
            return
        if self._wp_file is None:
            args = []
        else:
            args = ["-p", self._wp_file]
        if self.follow_worker_pool.isChecked():
            args += ["-af"]
        elif self.dry_run_worker_pool.isChecked():
            args += ["-D"]
        extra_options = self._split_field(self.wp_provision_options, "Extra Options")
        if extra_options is None:
            return
        self._run_command_in_subprocess("yd-provision", args + extra_options)

    def _resize_worker_pool_action(self):
        """
        Resize a Worker Pool, chosen from a list with the target node count, by
        'yd-resize -y <ydid> <nodes>': the dialog is the confirmation, so the
        CLI's own is not asked for as well.

        Lists the candidates with 'yd-list worker-pools --active-only --details
        --json', since only the full Worker Pool carries the node count and its
        bounds, in the current namespace and tag or matching the Name pattern.
        Configured Worker Pools are left out, since their nodes are not a
        number the platform can change. A pool awaiting nodes is listed but
        cannot be chosen, since the platform refuses to resize it, and when
        every pool is awaiting nodes no dialog opens. A pool that starts
        awaiting nodes after the listing still fails in 'yd-resize', whose
        error reaches the output window like any other. Every failure
        refuses, as for Add to.

        Neither Panel 3 checkbox applies: a Worker Pool being resized is
        probably being followed already, and Dry Run is labelled for creation,
        while the dialog already shows what the resize will do.
        '--yes' does not skip the dialog, which is the only place a node count
        can be given; the Deselect... dialog is not skipped either, for the same
        reason.
        """
        if (
            self._operation_in_flight(RESIZE_DIALOG_TITLE)
            or not self._properties_are_usable()
        ):
            return

        name_args = self._name_glob_args()
        scope = self._listing_scope("names", name_args)
        scope_args = self._yd_list_scope_args(name_args)
        if scope_args is None:
            self._output.log(NO_LISTING_TAG)
            return

        self._output.log("Checking which Worker Pools can be resized...")
        self.log_output.repaint()
        parsed = self._capture_json(
            "yd-list",
            ["--json"],
            ["worker-pools", "--active-only", "--details", *scope_args],
        )
        result = None if parsed is None else parse_resizable_pools(parsed)
        if parsed is None or result is None:
            self._output.log("Could not list the Worker Pools to resize; none resized")
            return

        pools, configured = result
        if not pools:
            left_out = (
                f"; {configured} Configured Worker Pool(s) matched, which cannot"
                " be resized"
                if configured
                else ""
            )
            self._output.log(f"No active Worker Pools{scope} to resize{left_out}")
            return
        if all(pool.awaiting_nodes for pool in pools):
            self._output.log(
                f"No Worker Pools{scope} can be resized yet: {len(pools)} matched,"
                " all awaiting nodes, which the platform will not resize"
            )
            return

        choice = self._choose_pool_size(
            f"Choose the Worker Pool{scope} to resize, and the number of nodes"
            " to resize it to.",
            pools,
            selected=newest_entity_id(parsed),
        )
        if choice is None:
            return

        pool_id, nodes = choice
        self._run_command_in_subprocess("yd-resize", ["-y", pool_id, str(nodes)])

    def _shutdown_all_worker_pools_action(self):
        self._run_destructive_with_listing(
            action_key="shutdown",
            command="yd-shutdown",
            run_args=["-y"],
            title="Shut Down Worker Pools",
            gerund="Shutting down",
            plural="Worker Pools",
            match_word="names",
        )

    def _terminate_all_compute_requirements_action(self):
        self._run_destructive_with_listing(
            action_key="terminate",
            command="yd-terminate",
            run_args=["-y"],
            title="Terminate Compute Requirements",
            gerund="Terminating",
            plural="Compute Requirements",
            match_word="tags",
        )

    def _show_wp_json_action(self):
        path = self._wp_file or self._get_config_data_file(WP_DATA)
        if path is None:
            self._output.log("No Worker Pool definition file selected")
            return
        try:
            with open(path, encoding="utf-8") as f:
                self._output.log(f"Displaying contents of '{path}':\n")
                self._output.log(f.read(), prefix=False)
        except OSError as e:
            self._output.log(f"Cannot open Worker Pool file '{path}': {e}")

    def _follow_worker_pool_set(self, checked_state: Qt.CheckState):
        if (
            self.dry_run_worker_pool.isChecked()
            and checked_state == Qt.CheckState.Checked
        ):
            # Uncheck the dry run flag and ensure the follow flag is checked
            self.dry_run_worker_pool.setChecked(False)
            self.follow_worker_pool.setChecked(True)

    def _dry_run_worker_pool_set(self, _checked_state: Qt.CheckState):
        if self.follow_worker_pool.isChecked():
            self.follow_worker_pool.setChecked(False)
