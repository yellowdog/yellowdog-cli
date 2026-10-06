"""
Panel 4 of YellowDogApp (see commander.py).
"""

from os.path import exists, join
from typing import cast

from PyQt6.QtWidgets import (
    QDialog,
    QListWidget,
)

from yellowdog_cli.commander.selection import (
    SelectableRow,
    checked_handles,
    object_rows,
)
from yellowdog_cli.commander.window_dialogs import WindowDialogs

RESULTS_DIR = "results"
# Shown when the Path field is empty and the tag is unknown, so there is nothing
# to derive a default object path from. Better than acting on a guess: the tag is
# interpolated into the default path, and a missing one used to produce 'None*'.
# Two ways to have no tag, so the wording covers both: no configuration file is
# selected, in which case none is discovered at all, or one is and discovery of
# it failed.
NO_OBJECT_PATH = (
    "No object path: no tag has been discovered, so there is no default path to"
    " match. Enter a Path, or select a configuration file to discover one from"
    " (reselect it if discovery has already failed)."
)


class ResultsPanel(WindowDialogs):
    """
    Panel 4, Collecting and Managing Results: Download, Delete and browsing
    the results directory.
    """

    def _object_path(self) -> str | None:
        """
        The object path the download and delete actions work on: the Path field
        if it has one, otherwise every object whose name starts with the
        discovered tag.

        None when neither is available — the Path field is empty and no tag has
        been discovered. Callers must refuse rather than carry on: this used to
        interpolate the missing tag and return the literal 'None*', which was
        then handed to 'yd-download' and 'yd-delete' as the scope to act on.
        """
        override = self.object_path_override.toPlainText().strip()
        if override:
            return override
        return f"{self._discovery.tag}*" if self._discovery.tag else None

    def _choose_objects(
        self, title: str, body: str, accept_text: str, rows: list[SelectableRow]
    ) -> list[str] | None:
        """
        Offer a non-destructive chooser over 'rows' and return the handles left
        ticked, or None if the user dismissed it. The accept button is disabled
        while nothing is ticked, so the returned list is never empty.

        Unlike _confirm_destructive this has no action_key and no 'Don't Ask
        Again': you would never want to stop being offered a choice permanently.
        Callers are responsible for honouring '--yes', which is a launch-time
        request for unattended operation rather than a mid-session one.
        """
        dialog, _accept_btn = self._build_chooser_dialog(title, body, accept_text, rows)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted.value:
                return None
            listing = cast(QListWidget, dialog.findChild(QListWidget, "selection_list"))
            return checked_handles(listing)
        finally:
            # Parented to the main window, so without this every chooser — and
            # the rows it owns — would live for the rest of the session.
            dialog.deleteLater()

    def _download_results_action(self):
        """
        Download matching objects from remote storage into the results directory,
        letting the user choose which of the matched items to fetch.

        Enumerates via 'yd-download -D --json' first: with nothing matching, log
        and do nothing; when the enumeration fails there are no paths to choose
        between, so fall back to downloading the whole pattern as before.

        The dry-run-checkbox preview fetches nothing, so it runs directly with no
        enumeration or chooser.

        '--yes' skips the chooser and fetches everything matched, as it does for
        the destructive confirmations. The chooser is not a confirmation, but
        '--yes' asks for unattended operation, and an unattended session cannot
        answer a chooser either; a user who wants a subset without being asked can
        narrow the Path field instead.
        """
        if (
            self._operation_in_flight("Download Matching Objects")
            or not self._properties_are_usable()
        ):
            return

        dst = join(self._working_dir(), RESULTS_DIR)
        path = self._object_path()
        if path is None:
            self._output.log(NO_OBJECT_PATH)
            return

        if self.dry_run_objects.isChecked():
            self._run_command_in_subprocess("yd-download", ["--into", dst, path, "-D"])
            return

        if self._confirmations_disabled:
            self._output.log(
                "Selection suppressed by '--yes';"
                f" downloading all objects matching '{path}'"
            )
            self._run_command_in_subprocess("yd-download", ["--into", dst, path])
            return

        self._output.log(f"Checking which objects match '{path}'...")
        self.log_output.repaint()
        objects = self._capture_dry_run_objects("yd-download", [path])

        if objects is not None and not objects:
            self._output.log(f"No objects match '{path}'")
            return

        if objects is None:
            self._output.log(
                "Could not list matching objects; downloading them all instead"
            )
            self._run_command_in_subprocess("yd-download", ["--into", dst, path])
            return

        body = f"Downloading objects matching '{path}' into '{RESULTS_DIR}'."
        if any(obj.is_dir for obj in objects):
            body += " A ticked directory is downloaded with everything inside it."
        handles = self._choose_objects(
            "Download Objects", body, "Download", object_rows(objects)
        )
        if handles is None:
            return

        if not self._handles_are_safe_to_target(handles, "download", "downloaded"):
            return

        self._run_command_in_subprocess(
            "yd-download",
            ["--into", dst, *handles],
            log_args=self._abbreviated_run_args(["--into", dst], handles, "objects"),
        )

    def _delete_objects_action(self):
        """
        Delete matching objects from remote storage, letting the user select
        which of the matched items to remove. Enumerates via
        'yd-delete -D --json -R <path>' first: with nothing matching, log a
        message and do nothing; when the enumeration fails there are no paths to
        target, so confirm at the scope level (without a list) and delete the
        whole pattern.

        The dry-run-checkbox preview changes nothing, so it runs directly with no
        enumeration or confirmation. The '-y'/per-action-skip bypasses delete the
        whole pattern, logging that they have done so.
        """
        if (
            self._operation_in_flight("Delete Matching Objects")
            or not self._properties_are_usable()
        ):
            return

        path = self._object_path()
        if path is None:
            self._output.log(NO_OBJECT_PATH)
            return

        if self.dry_run_objects.isChecked():
            # Harmless preview: run directly, no enumeration or confirmation.
            self._run_command_in_subprocess("yd-delete", ["-Ry", path, "-D"])
            return

        if self._confirmations_disabled or "delete" in self._skip_confirmations:
            self._output.log(
                f"Confirmations suppressed for 'delete';"
                f" deleting all objects matching '{path}'"
            )
            self._run_command_in_subprocess("yd-delete", ["-Ry", path])
            return

        self._output.log(f"Checking which objects match '{path}'...")
        self.log_output.repaint()
        objects = self._capture_dry_run_objects("yd-delete", ["-R", path])

        if objects is not None and not objects:
            self._output.log(f"No objects match '{path}'")
            return

        body = f"Deleting objects matching '{path}'."
        if objects and any(obj.is_dir for obj in objects):
            body += " A ticked directory is deleted with everything inside it."
        body += "\n\nThis cannot be undone."
        if objects is None:
            self._output.log(
                "Could not list affected objects; confirming by scope instead"
            )

        rows = object_rows(objects) if objects else None
        result = self._confirm_destructive("delete", "Delete Objects", body, rows=rows)
        if not result.proceed:
            return

        if result.handles is None:
            # The enumeration failed, so there are no paths to target: delete the
            # whole pattern the user has just confirmed.
            self._run_command_in_subprocess("yd-delete", ["-Ry", path])
            return

        if not result.handles:
            # 'yd-delete -Ry' with no paths would delete the entire configured
            # prefix, so an empty selection must never reach the command.
            self._output.log("Nothing selected to delete; no objects removed")
            return

        if not self._handles_are_safe_to_target(result.handles, "delete", "removed"):
            return

        self._run_command_in_subprocess(
            "yd-delete",
            ["-Ry", *result.handles],
            log_args=self._abbreviated_run_args(["-Ry"], result.handles, "objects"),
        )

    def _browse_results_directory_action(self):
        """
        Browse the results directory, saying so in a dialog when there is not one
        yet — the commonest reason this button appears to do nothing, and a log
        line alone was missed. The check is repeated in _open_file_viewer, which
        keeps its log-only report for the config-directory button and for the
        directory disappearing between here and there.
        """
        results_dir = join(self._working_dir(), RESULTS_DIR)
        if not exists(results_dir):
            self._notify(f"Directory '{results_dir}' does not (yet) exist")
            return
        self._open_file_viewer(results_dir)
