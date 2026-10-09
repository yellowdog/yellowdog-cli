"""
Panel 2 of YellowDogApp (see commander.py).
"""

from os.path import abspath

from PyQt6.QtCore import Qt

from yellowdog_cli.commander.selection import (
    entity_rows,
    newest_entity_id,
    parse_entity_summaries,
)
from yellowdog_cli.commander.window_base import CWD, NO_LISTING_TAG
from yellowdog_cli.commander.window_dialogs import WindowDialogs

SELECTED_WR_PREFIX = "Work Requirement: "
# The Work Requirement statuses 'yd-submit --add-to' accepts, the only ones Add
# to offers: 'yd-list --active-only' also keeps FINISHING and CANCELLING ones,
# which take no new Tasks. Spelled out rather than imported: nothing in
# Commander imports the SDK.
ADDABLE_STATUSES = ("RUNNING", "HELD")
WR_DATA = "workRequirementData"


class WorkPanel(WindowDialogs):
    """
    Panel 2, Submitting and Managing Work: selecting a Work Requirement file,
    Submit and Add to, Cancel and Cancel & Abort, and showing the file.
    """

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
        The 'yd-submit' arguments Panel 2 sets, shared by Submit and Add to: the
        selected definition, Dry Run, Follow Progress (unless 'follow' is False)
        and the Extra Options. None, having said why, when the Extra Options
        cannot be split.
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
        self._run_command_in_subprocess("yd-submit", submit_args)

    def _add_to_work_requirement_action(self):
        """
        Add the Task Groups and Tasks of the selected definition (or the
        configuration file's) to an existing Work Requirement, chosen from a list
        of those that can still be added to: 'yd-submit --add-to <ydid>', with
        the same Panel 2 settings as Submit.

        Lists the candidates with 'yd-list work-requirements --active-only
        --json', in the current namespace and tag or matching the Name pattern.
        '--active-only' leaves out COMPLETED, CANCELLED and FAILED, and CANCELLING
        is dropped here, since 'yd-submit --add-to' refuses it too.

        Every failure refuses rather than falling back. The destructive actions
        fall back to acting over their whole scope when the listing fails, but
        there is no scope here: the only fallbacks would be guessing a target, or
        a plain submission, which creates a Work Requirement nobody asked for.

        The target is passed by YDID, not by name, because names are not
        guaranteed unique and 'yd-submit' takes the first one that matches.

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
            "yd-list", ["--json"], ["work-requirements", "--active-only", *scope_args]
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
            newest = newest_entity_id(parsed)
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

        self._run_command_in_subprocess("yd-submit", ["-A", target, *submit_args])

    def _cancel_work_requirements_action(self):
        self._run_destructive_with_listing(
            action_key="cancel",
            command="yd-cancel",
            run_args=["-y"],
            title="Cancel Work Requirements",
            gerund="Cancelling",
            plural="Work Requirements",
            match_word="tags",
        )

    def _cancel_work_requirements_and_abort_action(self):
        self._run_destructive_with_listing(
            action_key="cancel_abort",
            command="yd-cancel",
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
        try:
            with open(path, encoding="utf-8") as f:
                self._output.log(f"Displaying contents of '{path}':\n")
                self._output.log(f.read(), prefix=False)
        except OSError as e:
            self._output.log(f"Cannot open Work Requirement file '{path}': {e}")

    def _follow_progress_set(self, checked_state: Qt.CheckState):
        if self.dry_run.isChecked() and checked_state == Qt.CheckState.Checked:
            # Uncheck the dry run flag and ensure the follow flag is checked
            self.dry_run.setChecked(False)
            self.follow_progress.setChecked(True)

    def _dry_run_set(self, _checked_state: Qt.CheckState):
        if self.follow_progress.isChecked():
            self.follow_progress.setChecked(False)
