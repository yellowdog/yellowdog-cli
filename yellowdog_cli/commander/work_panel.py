"""
Panel 2 of YellowDogApp (see commander.py).
"""

from os.path import abspath
from typing import cast

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

from yellowdog_cli.commander.selection import (
    SelectableRow,
    all_tasks_completed,
    entity_rows,
    newest_entity_id,
    parse_entity_summaries,
)
from yellowdog_cli.commander.window_base import CWD, NO_LISTING_TAG
from yellowdog_cli.commander.window_dialogs import DIALOG_SECTION_SPACING, WindowDialogs

SELECTED_WR_PREFIX = "Work Requirement: "
# The Work Requirement statuses 'yd workrequirement submit --add-to' accepts,
# the only ones Add to offers: 'yd list --active-only' also keeps FINISHING and
# CANCELLING ones, which take no new Tasks. Spelled out rather than imported:
# nothing in Commander imports the SDK.
ADDABLE_STATUSES = ("RUNNING", "HELD")
WR_DATA = "workRequirementData"

RESUBMIT_DIALOG_TITLE = "Resubmit Tasks"
FOLLOW_DIALOG_TITLE = "Follow Work Requirement"
# The Task statuses the resubmit dialog offers, in the order shown and passed,
# with their 'yd workrequirement resubmit' options; spelled out because nothing
# in Commander imports the SDK
FAILED_STATUS = "FAILED"
RESUBMIT_STATUS_LABELS = {
    FAILED_STATUS: "Failed",
    "ABORTED": "Aborted",
    "CANCELLED": "Cancelled",
}
RESUBMIT_STATUS_FLAGS = {
    FAILED_STATUS: "--failed",
    "ABORTED": "--aborted",
    "CANCELLED": "--cancelled",
}
RESUBMIT_STATUS_SPACING = 12


class WorkPanel(WindowDialogs):
    """
    Panel 2, Submitting and Managing Work: selecting a Work Requirement file,
    Submit and Add to, Resubmit Tasks and Follow, Cancel and Cancel & Abort,
    and showing the file.
    """

    # The statuses the resubmit dialog last left ticked, kept for the session;
    # a tuple, so the class default is never changed in place
    _resubmit_statuses: tuple[str, ...] = (FAILED_STATUS,)

    def _show_wr_selection(self):
        self._show_selection_on_button(
            self.select_work_requirement,
            SELECTED_WR_PREFIX,
            self._select_wr_default_text,
            self._select_wr_default_tooltip,
            self._wr_file,
        )

    def _select_work_requirement_action(self):
        directory = CWD if self._config_file is None else self._config_dir()
        file = self._file_dialogs.select_file(
            caption="Please select a Work Requirement definition file",
            directory=directory,
            file_pattern="*.json *.jsonnet",
        )
        if file is None:
            self._output.log("No Work Requirement definition file selected")
        else:
            self._set_wr_file(file)

    def _set_wr_file(self, file: str):
        """
        Select a Work Requirement definition, from the Select button or the
        command line. Stored absolute; see the note on _wr_file in __init__.
        """
        self._wr_file = abspath(file)
        self._output.log(f"Selected Work Requirement definition '{self._wr_file}'")
        self._show_wr_selection()

    def _submit_args(self, follow: bool = True) -> list[str] | None:
        """
        The 'yd workrequirement submit' arguments Panel 2 sets, shared by
        Submit and Add to: the selected definition, Dry Run, Follow Progress
        (unless 'follow' is False) and the Extra Options. None, having said
        why, when the Extra Options cannot be split.
        """
        if self._wr_file is None:
            args = []
        else:
            args = ["-r", self._wr_file]
        dry_run = self.dry_run.isChecked()
        follow_progress = follow and self.follow_progress.isChecked()
        if dry_run:
            args += ["-D"]
        if follow_progress and not dry_run:
            args += ["-f"]
        extra_options = self._split_field(self.wr_submit_options, "Extra Options")
        if extra_options is None:
            return None
        return args + extra_options

    def _submit_work_requirement_action(self):
        if not self._properties_are_usable():
            return
        submit_args = self._submit_args()
        if submit_args is None:
            return
        self._run_command_in_subprocess("yd workrequirement submit", submit_args)

    def _add_to_work_requirement_action(self):
        """
        Add the Task Groups and Tasks of the selected definition (or the
        configuration file's) to an existing Work Requirement, chosen from a
        list of those that can still be added to: 'yd workrequirement submit
        --add-to <ydid>', with the same Panel 2 settings as Submit.

        Lists the candidates with 'yd list work-requirements --active-only
        --json', in the current namespace and tag or matching the Name pattern.
        '--active-only' leaves out COMPLETED, CANCELLED and FAILED, and
        CANCELLING is dropped here, since 'yd workrequirement submit --add-to'
        refuses it too.

        Every failure refuses rather than falling back. The destructive actions
        fall back to acting over their whole scope when the listing fails, but
        there is no scope here: the only fallbacks would be guessing a target, or
        a plain submission, which creates a Work Requirement nobody asked for.

        The target is passed by YDID, not by name, because names are not
        guaranteed unique and 'yd workrequirement submit' takes the first one
        that matches.

        '--yes' skips the chooser when there is exactly one candidate, and
        refuses when there are several: an unattended session cannot choose, and
        Commander does not choose for it.
        """
        title = "Add to Work Requirement"
        if self._operation_in_flight(title) or not self._properties_are_usable():
            return
        # Before the listing, so that a quoting mistake is not found only after
        # a Work Requirement has been chosen
        submit_args = self._submit_args()
        if submit_args is None:
            return

        name_args = self._name_glob_args()
        scope = self._listing_scope("tags", name_args)

        scope_args = self._yd_list_scope_args(name_args)
        if scope_args is None:
            self._output.log(NO_LISTING_TAG)
            return

        self._output.log("Checking which Work Requirements can be added to...")
        self.log_output.repaint()
        parsed = self._capture_json(
            "yd list", ["--json"], ["work-requirements", "--active-only", *scope_args]
        )
        entities = None if parsed is None else parse_entity_summaries(parsed)
        if parsed is None or entities is None:
            self._output.log(
                "Could not list the Work Requirements to add to; nothing submitted"
            )
            return

        entities = [entity for entity in entities if entity.status in ADDABLE_STATUSES]
        if not entities:
            self._output.log(f"No active Work Requirements{scope} to add to")
            return

        if self._confirmations_disabled:
            if len(entities) > 1:
                self._output.log(
                    f"{len(entities)} active Work Requirements{scope}, and"
                    " '--yes' leaves no way to choose between them; nothing"
                    " submitted. Narrow the choice with the Name field."
                )
                return
            target = entities[0].id
            self._output.log(
                f"Selection suppressed by '--yes'; adding to the only active"
                f" Work Requirement{scope}, '{entities[0].name}'"
            )
        else:
            # The newest of those offered, not one left out as not addable
            newest = newest_entity_id(parsed, {e.id for e in entities})
            target = self._choose_one(
                title,
                f"Choose the Work Requirement{scope} to add the Task Groups and"
                " Tasks to.",
                "Add",
                entity_rows(entities),
                selected=newest,
            )
            if target is None:
                return

        # Followed already, by the Submit that created it or an earlier Add to,
        # a second stream would show every event twice
        following = self._output.run_following(target)
        follow_asked = self.follow_progress.isChecked() and not self.dry_run.isChecked()
        if following is not None and follow_asked:
            name = next(
                (entity.name for entity in entities if entity.id == target), target
            )
            self._output.log(
                f"Not following Work Requirement '{name}' again:"
                f" {following.bar_subject} is following it already"
            )
            submit_args = self._submit_args(follow=False)
            if submit_args is None:
                return

        self._run_command_in_subprocess(
            "yd workrequirement submit", ["-A", target, *submit_args]
        )

    def _resubmit_tasks_action(self):
        """
        Resubmit the Tasks of a Work Requirement chosen from a list, as a new
        Work Requirement: 'yd workrequirement resubmit <ydid>' with the
        statuses ticked in the dialog ('--failed', '--aborted', '--cancelled')
        and Panel 2's Dry Run and Follow Progress. The Extra Options are not
        passed: they are written for 'yd workrequirement submit', whose options
        resubmit mostly does not take.

        Lists the Work Requirements in the current namespace and tag, or
        matching the Name pattern, in any status, since a running Work
        Requirement can have failed Tasks as well as a finished one. Those
        whose Tasks have all completed are left out, having none to resubmit;
        the listing carries no count by status, so one with nothing in the
        statuses ticked is offered, and resubmit says it found nothing.

        Refuses rather than falls back, as Add to does: there is no scope to
        act over, and the target is passed by YDID. '--yes' resubmits the
        FAILED Tasks of a sole candidate and refuses between several.
        """
        title = RESUBMIT_DIALOG_TITLE
        if self._operation_in_flight(title) or not self._properties_are_usable():
            return

        name_args = self._name_glob_args()
        scope = self._listing_scope("tags", name_args)

        scope_args = self._yd_list_scope_args(name_args)
        if scope_args is None:
            self._output.log(NO_LISTING_TAG)
            return

        self._output.log("Checking which Work Requirements have Tasks to resubmit...")
        self.log_output.repaint()
        parsed = self._capture_json(
            "yd list", ["--json"], ["work-requirements", *scope_args]
        )
        entities = None if parsed is None else parse_entity_summaries(parsed)
        if parsed is None or entities is None:
            self._output.log(
                "Could not list the Work Requirements to resubmit from;"
                " nothing resubmitted"
            )
            return

        unfinished = {row["id"] for row in parsed if not all_tasks_completed(row)}
        entities = [entity for entity in entities if entity.id in unfinished]
        if not entities:
            self._output.log(
                f"No Work Requirements{scope} with Tasks that did not complete"
            )
            return

        if self._confirmations_disabled:
            if len(entities) > 1:
                self._output.log(
                    f"{len(entities)} Work Requirements{scope} with Tasks that"
                    " did not complete, and '--yes' leaves no way to choose"
                    " between them; nothing resubmitted. Narrow the choice with"
                    " the Name field."
                )
                return
            target = entities[0].id
            statuses: tuple[str, ...] = (FAILED_STATUS,)
            self._output.log(
                "Selection suppressed by '--yes'; resubmitting the FAILED Tasks"
                f" of the only Work Requirement{scope} with Tasks that did not"
                f" complete, '{entities[0].name}'"
            )
        else:
            chosen = self._choose_resubmission(
                f"Choose the Work Requirement{scope} whose Tasks are"
                " resubmitted, as a new Work Requirement, and the statuses of"
                " the Tasks to resubmit.",
                entity_rows(entities),
                selected=newest_entity_id(parsed, {e.id for e in entities}),
            )
            if chosen is None:
                return
            target, statuses = chosen

        args = [target, *(RESUBMIT_STATUS_FLAGS[status] for status in statuses)]
        if self.dry_run.isChecked():
            args += ["-D"]
        elif self.follow_progress.isChecked():
            args += ["-f"]
        self._run_command_in_subprocess("yd workrequirement resubmit", args)

    def _follow_work_requirement_action(self):
        """
        Follow the events of an active Work Requirement, chosen from a list:
        'yd workrequirement follow <ydid>'.

        Lists them with 'yd list work-requirements --active-only --json', in
        the current namespace and tag or matching the Name pattern, the newest
        selected. Refuses rather than falls back, as Add to does, and follows
        nothing a command still running in the window follows already, which
        would show every event twice. '--yes' follows a sole candidate and
        refuses between several.
        """
        title = FOLLOW_DIALOG_TITLE
        if self._operation_in_flight(title) or not self._properties_are_usable():
            return

        name_args = self._name_glob_args()
        scope = self._listing_scope("tags", name_args)
        scope_args = self._yd_list_scope_args(name_args)
        if scope_args is None:
            self._output.log(NO_LISTING_TAG)
            return

        self._output.log("Checking which Work Requirements are active...")
        self.log_output.repaint()
        parsed = self._capture_json(
            "yd list", ["--json"], ["work-requirements", "--active-only", *scope_args]
        )
        entities = None if parsed is None else parse_entity_summaries(parsed)
        if parsed is None or entities is None:
            self._output.log(
                "Could not list the Work Requirements to follow; nothing followed"
            )
            return
        if not entities:
            self._output.log(f"No active Work Requirements{scope} to follow")
            return

        if self._confirmations_disabled:
            if len(entities) > 1:
                self._output.log(
                    f"{len(entities)} active Work Requirements{scope}, and"
                    " '--yes' leaves no way to choose between them; nothing"
                    " followed. Narrow the choice with the Name field."
                )
                return
            target = entities[0].id
            self._output.log(
                "Selection suppressed by '--yes'; following the only active"
                f" Work Requirement{scope}, '{entities[0].name}'"
            )
        else:
            target = self._choose_one(
                title,
                f"Choose the active Work Requirement{scope} to follow.",
                "Follow",
                entity_rows(entities),
                selected=newest_entity_id(parsed),
            )
            if target is None:
                return

        following = self._output.run_following(target)
        if following is not None:
            name = next((e.name for e in entities if e.id == target), target)
            self._output.log(
                f"Not following Work Requirement '{name}' again:"
                f" {following.bar_subject} is following it already"
            )
            return
        self._run_command_in_subprocess("yd workrequirement follow", [target])

    def _build_resubmit_dialog(
        self,
        message: str,
        rows: list[SelectableRow],
        selected: str | None = None,
    ) -> tuple[QDialog, QPushButton]:
        """
        Build (but do not show) the resubmit dialog: the single-choice listing
        of 'rows', a 'Resubmit:' row of one checkbox per Task status, ticked as
        last left in this session, and Cancel / Resubmit. Returns the dialog
        and the Resubmit button, which is greyed while no row is selected or
        no status ticked. 'rows' must be non-empty.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle(RESUBMIT_DIALOG_TITLE)
        layout = QVBoxLayout(dialog)
        self._size_dialog_to_its_text(layout)

        message_label = QLabel(message)
        message_label.setWordWrap(True)
        layout.addWidget(message_label)
        layout.addSpacing(DIALOG_SECTION_SPACING)

        listing = self._new_single_choice_listing(rows)
        layout.addWidget(listing)
        layout.addSpacing(DIALOG_SECTION_SPACING)

        status_row = QHBoxLayout()
        status_row.setSpacing(RESUBMIT_STATUS_SPACING)
        status_row.addWidget(QLabel("Resubmit:"))
        boxes: dict[str, QCheckBox] = {}
        for status, label in RESUBMIT_STATUS_LABELS.items():
            box = QCheckBox(label)
            box.setObjectName(f"resubmit_{status.lower()}")
            box.setChecked(status in self._resubmit_statuses)
            # Laid out by its painted width, or the row's spacing vanishes on
            # macOS (see _space_paired_checkboxes)
            box.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect)
            status_row.addWidget(box)
            boxes[status] = box
        status_row.addStretch(1)
        layout.addLayout(status_row)
        layout.addSpacing(DIALOG_SECTION_SPACING)

        button_box = QDialogButtonBox(dialog)
        button_box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        resubmit_btn = cast(
            QPushButton,
            button_box.addButton("Resubmit", QDialogButtonBox.ButtonRole.AcceptRole),
        )
        resubmit_btn.setDefault(True)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        def refresh() -> None:
            resubmit_btn.setEnabled(
                bool(listing.selectedItems())
                and any(box.isChecked() for box in boxes.values())
            )

        listing.itemSelectionChanged.connect(refresh)
        for box in boxes.values():
            box.toggled.connect(lambda _checked: refresh())
        # Double-clicking accepts only what Resubmit would
        listing.itemDoubleClicked.connect(
            lambda _item: dialog.accept() if resubmit_btn.isEnabled() else None
        )

        self._select_row(listing, rows, selected)
        refresh()
        return dialog, resubmit_btn

    def _choose_resubmission(
        self, message: str, rows: list[SelectableRow], selected: str | None = None
    ) -> tuple[str, tuple[str, ...]] | None:
        """
        Offer the resubmit dialog and return the handle chosen and the statuses
        ticked, in RESUBMIT_STATUS_LABELS' order, or None if it was dismissed.
        The statuses are kept for the next time it opens, in this session.
        """
        dialog, _resubmit_btn = self._build_resubmit_dialog(message, rows, selected)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted.value:
                return None
            listing = cast(QListWidget, dialog.findChild(QListWidget, "choice_list"))
            chosen = listing.selectedItems()
            statuses = tuple(
                status
                for status in RESUBMIT_STATUS_LABELS
                if cast(
                    QCheckBox,
                    dialog.findChild(QCheckBox, f"resubmit_{status.lower()}"),
                ).isChecked()
            )
            if not chosen or not statuses:
                return None
            self._resubmit_statuses = statuses
            return chosen[0].data(Qt.ItemDataRole.UserRole), statuses
        finally:
            dialog.deleteLater()

    def _cancel_work_requirements_action(self):
        self._run_destructive_with_listing(
            action_key="cancel",
            command="yd workrequirement cancel",
            run_args=["-y"],
            title="Cancel Work Requirements",
            gerund="Cancelling",
            plural="Work Requirements",
            match_word="tags",
        )

    def _cancel_work_requirements_and_abort_action(self):
        self._run_destructive_with_listing(
            action_key="cancel_abort",
            command="yd workrequirement cancel",
            run_args=["-ay"],
            title="Cancel and Abort Work Requirements",
            gerund="Cancelling",
            plural="Work Requirements",
            match_word="tags",
            and_abort=True,
        )

    def _show_wr_json_action(self):
        path = self._wr_file or self._get_config_data_file(WR_DATA)
        if path is None:
            self._output.log("No Work Requirement definition file selected")
            return
        self._display_file(path, "Work Requirement file")

    def _follow_progress_set(self, checked_state: Qt.CheckState):
        if self.dry_run.isChecked() and checked_state == Qt.CheckState.Checked:
            # Uncheck the dry run flag and ensure the follow flag is checked
            self.dry_run.setChecked(False)
            self.follow_progress.setChecked(True)

    def _dry_run_set(self, _checked_state: Qt.CheckState):
        if self.follow_progress.isChecked():
            self.follow_progress.setChecked(False)
