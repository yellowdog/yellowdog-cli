"""
YellowDogApp's dialogs (see commander.py).
"""

from functools import partial as functools_partial
from typing import cast

from PyQt6.QtCore import (
    QSize,
    Qt,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollBar,
    QStyle,
    QVBoxLayout,
)

from yellowdog_cli.commander.check_indicator import fix_check_indicator_placement
from yellowdog_cli.commander.command_running import CommandRunning
from yellowdog_cli.commander.selection import (
    MAX_DIALOG_LIST_ROWS,
    Confirmation,
    SelectableRow,
    checked_handles,
    entity_rows,
    set_all_check_states,
    update_selection_state,
)
from yellowdog_cli.commander.window_base import WINDOW_TITLE

SKIP_CONFIRMATION_BUTTON_TEXT = "Yes to All (Don't Ask Again)"
ENTITY_LIST_PADDING = 6  # px of breathing room inside the entity list's frame
# Extra space between a dialog's message, its listing and what follows, which
# otherwise sit at the layout's default spacing and read as crowded
DIALOG_SECTION_SPACING = 6


class WindowDialogs(CommandRunning):
    """
    The window's dialogs: the destructive confirmation, the choosers and the
    single-choice listing, the notice, and running a destructive command over
    what a dry run listed.
    """

    def _confirm_destructive(
        self,
        action_key: str,
        title: str,
        body: str,
        *,
        rows: list[SelectableRow] | None = None,
    ) -> Confirmation:
        """
        Show a warning confirmation dialog for a destructive action. Returns a
        Confirmation with 'proceed' False if the action must not proceed;
        otherwise 'handles' is None when there was nothing individually
        selectable (no listing, or a suppressed confirmation) — the caller
        acts over its whole scope — or the ticked subset when 'rows' was
        supplied, where an empty list means the user deselected everything and
        the caller must act on nothing at all.

        'rows' is keyword-only because 'names' — a second, positionally
        adjacent listing parameter — used to sit here too; a positional call
        would have silently landed the wrong argument in this slot. Now there
        is only one listing parameter, but the call stays keyword-only so a
        future one can't reintroduce the hazard.

        'Yes to All (Don't Ask Again)' confirms and suppresses future
        confirmations for this same action (identified by action_key) for the
        rest of the session; the suppression is per-action, not global. It acts
        on every listed row regardless of the tick states, as its label says.
        """
        if self._confirmations_disabled or action_key in self._skip_confirmations:
            return Confirmation(proceed=True, handles=None)
        dialog, yes_btn, skip_btn = self._build_destructive_dialog(
            title, body, rows=rows
        )
        buttons = cast(QDialogButtonBox, dialog.findChild(QDialogButtonBox))
        clicked: dict[str, object] = {}
        buttons.clicked.connect(
            lambda button: (clicked.__setitem__("button", button), dialog.accept())
        )
        dialog.exec()

        try:
            if clicked.get("button") is skip_btn:
                self._skip_confirmations.add(action_key)
                return Confirmation(
                    proceed=True,
                    handles=[row.handle for row in rows] if rows else None,
                )
            if clicked.get("button") is not yes_btn:
                return Confirmation(proceed=False, handles=None)
            if not rows:
                return Confirmation(proceed=True, handles=None)
            listing = cast(QListWidget, dialog.findChild(QListWidget, "selection_list"))
            return Confirmation(proceed=True, handles=checked_handles(listing))
        finally:
            # Parented to the main window, so without this every confirmation
            # dialog — and the hundreds of list items it may own — would live
            # for the rest of the session.
            dialog.deleteLater()

    def _build_selection_list_widget(
        self, rows: list[SelectableRow], checked: set[str] | None = None
    ) -> QListWidget:
        """
        A checkable list, every row ticked unless 'checked' names the handles
        that are. Each row shows its display text in
        the monospaced output font and holds its handle in UserRole, which is
        where the run arguments are read from; the tooltip carries the fuller
        text so a row elided by a narrow dialog (QListWidget's default
        ElideRight) is still recoverable. The widget's height is fixed to its
        content, capped at MAX_DIALOG_LIST_ROWS rows so a long listing scrolls
        instead of growing the dialog past the screen.

        The horizontal scrollbar is turned off explicitly, and the height is
        fixed rather than merely capped, because of one bug in each direction. A
        scrollbar appears when a name overflows a narrow dialog and then eats the
        height budgeted for the rows — on Windows that left a 1px viewport, so the
        list showed nothing but the scrollbar. And a bare maximum lets the layout
        squeeze the list towards nothing when the dialog is short of space, which
        is platform- and font-dependent. Eliding plus the tooltip is the intended
        way to cope with a long name, not scrolling sideways.

        ENTITY_LIST_PADDING keeps the rows off the frame, which otherwise reads
        as cramped once there are more than a handful. Qt folds stylesheet
        padding into frameWidth(), so the height below picks it up on its own —
        do not add it a second time.

        A QListWidget is used rather than a column of QCheckBox widgets (as
        _build_deselect_dialog uses for its three fixed rows) because a busy
        namespace or bucket prefix can enumerate hundreds of items, which
        QListWidget scrolls, keyboard-navigates and repaints natively. 'rows'
        must be non-empty.

        The check indicators are the point of the widget, so it is here that
        fix_check_indicator_placement() puts them back where they belong on a
        style that paints them somewhere else.
        """
        listing = self._new_dialog_listing("selection_list")
        fix_check_indicator_placement(listing)
        for row in rows:
            item = QListWidgetItem(row.display)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if checked is None or row.handle in checked
                else Qt.CheckState.Unchecked
            )
            item.setToolTip(row.tooltip)
            item.setData(Qt.ItemDataRole.UserRole, row.handle)
            listing.addItem(item)

        self._fit_dialog_listing_height(listing)
        return listing

    def _new_dialog_listing(self, name: str) -> QListWidget:
        """
        An empty list for a dialog, in the output font, padded off its frame and
        with no horizontal scrollbar; see _build_selection_list_widget for why.
        Fill it, then fit its height with _fit_dialog_listing_height().

        Parented to the main window from the start, although it is going into a
        dialog's layout, which reparents it: the height is fitted using the
        frame width, and the macOS style frames a widget with no parent — a
        prospective window of its own — 1px narrower than one inside a window.
        Fitted unparented, every list came out 2px short of its rows, so a
        confirmation showed a scrollbar and clipped its last row. The offscreen
        platform frames both alike, so no test here can see it; measured on
        macOS, 6px unparented against 7px in a dialog.
        """
        listing = QListWidget(self)
        listing.setObjectName(name)
        listing.setFont(self._font)
        listing.setStyleSheet(f"QListWidget {{ padding: {ENTITY_LIST_PADDING}px; }}")
        listing.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return listing

    @staticmethod
    def _fit_dialog_listing_height(listing: QListWidget):
        """
        Fix a filled dialog list's height to its rows, capped at
        MAX_DIALOG_LIST_ROWS so that a long one scrolls; see
        _build_selection_list_widget for why fixed rather than merely capped.
        """
        row_height = listing.sizeHintForRow(0)
        if row_height > 0:
            visible_rows = min(listing.count(), MAX_DIALOG_LIST_ROWS)
            height = row_height * visible_rows + 2 * listing.frameWidth()
            listing.setFixedHeight(height)

    def _build_destructive_dialog(
        self,
        title: str,
        message: str,
        *,
        rows: list[SelectableRow] | None = None,
    ) -> tuple[QDialog, QPushButton, QPushButton]:
        """
        Build (but do not show) the destructive-action confirmation dialog: a
        warning icon and message, an optional listing of the affected items, and
        No / Yes / 'Yes to All' buttons (default No). Returns the dialog and the
        Yes / skip buttons so the caller can identify which was clicked.

        With 'rows', the listing is a checkable QListWidget with All / None
        buttons and an 'N of M selected' label, so the user can act on a subset;
        Yes is disabled while nothing is ticked. Without 'rows' — nothing was
        individually selectable — there is no listing at all, and the caller
        acts over its whole scope.

        A plain QDialog is used rather than QMessageBox so the listing has full
        formatting control (no ugly wrapping) and no native-alert 'detailed
        text' limitations.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)

        header = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(
            cast(QStyle, self.style())
            .standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
            .pixmap(QSize(48, 48))
        )
        icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        header.addWidget(icon_label)
        message_label = QLabel(message)
        message_label.setWordWrap(True)
        header.addWidget(message_label, stretch=1)
        layout.addLayout(header)

        selection_listing, count_label = self._add_selection_listing(layout, rows)

        button_box = QDialogButtonBox()
        no_btn = cast(
            QPushButton,
            button_box.addButton("No", QDialogButtonBox.ButtonRole.RejectRole),
        )
        yes_btn = cast(
            QPushButton,
            button_box.addButton("Yes", QDialogButtonBox.ButtonRole.AcceptRole),
        )
        skip_btn = cast(
            QPushButton,
            button_box.addButton(
                SKIP_CONFIRMATION_BUTTON_TEXT,
                QDialogButtonBox.ButtonRole.AcceptRole,
            ),
        )
        no_btn.setDefault(True)
        layout.addWidget(button_box)

        self._wire_selection_gating(selection_listing, count_label, yes_btn)

        return dialog, yes_btn, skip_btn

    def _add_selection_listing(
        self,
        layout: QVBoxLayout,
        rows: list[SelectableRow] | None,
        checked: set[str] | None = None,
    ) -> tuple[QListWidget | None, QLabel | None]:
        """
        Add the checkable listing and its All / None buttons and count label to a
        dialog's layout, returning both so the caller can gate its accept button
        on them. Returns (None, None) when there are no rows — nothing was
        individually selectable — in which case the dialog shows no listing.

        Shared by the destructive-confirmation dialog and the download chooser,
        which differ only in their surrounding chrome (warning icon, wording and
        buttons), not in how a selection is presented or read back.
        """
        if not rows:
            return None, None

        listing = self._build_selection_list_widget(rows, checked)
        count_label = QLabel()
        count_label.setObjectName("selection_count")
        all_btn = QPushButton("All")
        all_btn.setObjectName("select_all")
        all_btn.clicked.connect(
            functools_partial(set_all_check_states, listing, Qt.CheckState.Checked)
        )
        none_btn = QPushButton("None")
        none_btn.setObjectName("select_none")
        none_btn.clicked.connect(
            functools_partial(set_all_check_states, listing, Qt.CheckState.Unchecked)
        )
        # These are the first focusable widgets in the dialog, and an autoDefault
        # QPushButton that has focus takes over as the dialog's default button —
        # which would leave 'All' highlighted instead of the intended default
        # ('No' on a confirmation, 'Download' on a chooser) and make Return do the
        # wrong thing. Opt them out so the explicit default stands.
        all_btn.setAutoDefault(False)
        none_btn.setAutoDefault(False)
        controls = QHBoxLayout()
        controls.addWidget(all_btn)
        controls.addWidget(none_btn)
        controls.addStretch(1)
        controls.addWidget(count_label)
        layout.addLayout(controls)
        layout.addWidget(listing)
        return listing, count_label

    def _wire_selection_gating(
        self,
        listing: QListWidget | None,
        count_label: QLabel | None,
        accept_btn: QPushButton,
    ) -> None:
        """
        Keep the 'N of M selected' label and the accept button in step with the
        listing's check states, so neither dialog can accept a selection of
        nothing. A no-op when there is no listing, since then the caller acts
        over its whole scope rather than a selection.
        """
        if listing is None or count_label is None:
            return
        refresh = functools_partial(
            update_selection_state, listing, count_label, accept_btn
        )
        listing.itemChanged.connect(refresh)
        refresh()

    def _build_chooser_dialog(
        self,
        title: str,
        message: str,
        accept_text: str,
        rows: list[SelectableRow],
        checked: set[str] | None = None,
    ) -> tuple[QDialog, QPushButton]:
        """
        Build (but do not show) a non-destructive chooser: a message, the same
        checkable listing the confirmation dialog uses (every row ticked unless
        'checked' names the handles that are), and Cancel / <accept_text>
        buttons with the accept button as the default. Returns the dialog and that
        button so the caller can tell acceptance from dismissal.

        Deliberately unlike _build_destructive_dialog: no warning icon, no 'this
        cannot be undone', and no 'Don't Ask Again'. Following the precedent set
        by the Deselect... dialog, a chooser is not a confirmation — nothing it
        does is irreversible, and suppressing it would remove the only way to
        pick a subset. 'rows' must be non-empty; with nothing to choose there is
        no reason to ask.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)

        message_label = QLabel(message)
        message_label.setWordWrap(True)
        layout.addWidget(message_label)

        listing, count_label = self._add_selection_listing(layout, rows, checked)

        button_box = QDialogButtonBox(dialog)
        button_box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        accept_btn = cast(
            QPushButton,
            button_box.addButton(accept_text, QDialogButtonBox.ButtonRole.AcceptRole),
        )
        accept_btn.setDefault(True)
        # Unlike the confirmation dialog, whose caller inspects which button was
        # clicked, this one only needs accept-or-dismiss — so wire the box straight
        # to the dialog. Without these the buttons do nothing at all and exec()
        # never returns.
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        self._wire_selection_gating(listing, count_label, accept_btn)

        return dialog, accept_btn

    def _build_single_choice_dialog(
        self,
        title: str,
        message: str,
        accept_text: str,
        rows: list[SelectableRow],
        selected: str | None = None,
    ) -> tuple[QDialog, QPushButton]:
        """
        Build (but do not show) a chooser of exactly one row: a message, a plain
        selectable listing with the row whose handle is 'selected' (else the
        first) selected, and Cancel / <accept_text> buttons with the accept
        button as the default. Returns the dialog and that button.

        Not _build_chooser_dialog with a flag, because what that dialog is built
        around — ticks, All / None, 'N of M selected' — means nothing when the
        answer is one row. With no check indicators there is nothing for
        fix_check_indicator_placement() to correct, either. The accept button is
        gated on a selection all the same, since a ctrl-click can clear it, and
        double-clicking a row accepts it. The listing opens wide enough for its
        longest row, up to the main window's width, as the process chooser's
        does, so the status column is not elided behind a long name. 'rows'
        must be non-empty.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        self._size_dialog_to_its_text(layout)

        message_label = QLabel(message)
        message_label.setWordWrap(True)
        layout.addWidget(message_label)
        layout.addSpacing(DIALOG_SECTION_SPACING)

        listing = self._new_single_choice_listing(rows)
        layout.addWidget(listing)
        layout.addSpacing(DIALOG_SECTION_SPACING)

        button_box = QDialogButtonBox(dialog)
        button_box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        accept_btn = cast(
            QPushButton,
            button_box.addButton(accept_text, QDialogButtonBox.ButtonRole.AcceptRole),
        )
        accept_btn.setDefault(True)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        def refresh() -> None:
            accept_btn.setEnabled(bool(listing.selectedItems()))

        listing.itemSelectionChanged.connect(refresh)
        listing.itemDoubleClicked.connect(lambda _item: dialog.accept())

        self._select_row(listing, rows, selected)
        refresh()

        return dialog, accept_btn

    def _new_single_choice_listing(self, rows: list[SelectableRow]) -> QListWidget:
        """
        A single-selection dialog list of 'rows', named 'choice_list', its
        height fitted to them and wide enough for the longest, up to the main
        window's width, as the process chooser's is.
        """
        listing = self._new_dialog_listing("choice_list")
        listing.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        for row in rows:
            item = QListWidgetItem(row.display)
            item.setToolTip(row.tooltip)
            item.setData(Qt.ItemDataRole.UserRole, row.handle)
            if not row.enabled:
                item.setFlags(
                    item.flags()
                    & ~Qt.ItemFlag.ItemIsSelectable
                    & ~Qt.ItemFlag.ItemIsEnabled
                )
            listing.addItem(item)
        self._fit_dialog_listing_height(listing)
        scrollbar = cast(QScrollBar, listing.verticalScrollBar())
        listing.setMinimumWidth(
            min(
                listing.sizeHintForColumn(0)
                + 2 * listing.frameWidth()
                + (
                    scrollbar.sizeHint().width()
                    if listing.count() > MAX_DIALOG_LIST_ROWS
                    else 0
                ),
                self.width(),
            )
        )
        return listing

    @staticmethod
    def _size_dialog_to_its_text(layout: QVBoxLayout) -> None:
        """
        Size a dialog to its layout, word-wrapped labels included. Left to
        itself a dialog takes its size before a wrapped label knows how wide it
        will be, so a message that wraps to three lines is given the height of
        two and clipped top and bottom. A fixed-size constraint has the layout
        size the dialog from each label's height for its actual width instead.
        The dialog can then not be resized by hand, which none of these small
        dialogs needs; its listing scrolls beyond MAX_DIALOG_LIST_ROWS.
        """
        layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

    @staticmethod
    def _select_row(
        listing: QListWidget, rows: list[SelectableRow], selected: str | None
    ) -> None:
        """
        Select the row whose handle is 'selected', else the first; a disabled
        row is passed over for the first enabled one. Selects nothing when no
        row is enabled.
        """
        enabled = [index for index, row in enumerate(rows) if row.enabled]
        preferred = [
            index for index in enabled if rows[index].handle == selected
        ] or enabled
        if preferred:
            listing.setCurrentRow(preferred[0])

    def _choose_one(
        self,
        title: str,
        message: str,
        accept_text: str,
        rows: list[SelectableRow],
        selected: str | None = None,
    ) -> str | None:
        """
        Offer a single-choice chooser over 'rows' and return the handle chosen,
        or None if the user dismissed it. Callers honour '--yes' themselves, as
        for _choose_objects.
        """
        dialog, _accept_btn = self._build_single_choice_dialog(
            title, message, accept_text, rows, selected
        )
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted.value:
                return None
            listing = cast(QListWidget, dialog.findChild(QListWidget, "choice_list"))
            chosen = listing.selectedItems()
            return chosen[0].data(Qt.ItemDataRole.UserRole) if chosen else None
        finally:
            dialog.deleteLater()

    def _run_destructive_with_listing(
        self,
        action_key: str,
        command: str,
        run_args: list[str],
        title: str,
        gerund: str,
        plural: str,
        match_word: str,
        and_abort: bool = False,
    ) -> None:
        """
        Confirm and run a destructive action, listing the affected entities for
        the user to select from and then targeting exactly that selection by
        YDID. Enumerates via '<command> -D --json' first: with no affected
        entities, log a message and do nothing; when the enumeration fails there
        are no YDIDs to target, so confirm at the scope level (without a list)
        and run over the whole scope.

        The Name pattern narrows the *enumeration* only. It must not reach a run
        that passes YDIDs, because the CLI rejects mixing glob patterns with
        literal names/IDs ('cannot mix name glob patterns with explicit
        names/IDs'); by then the pattern's job is done, the selection having
        been resolved from the entities it enumerated.

        The '-y' / per-action-skip bypasses run the command over the whole scope
        without enumerating, logging that they have done so. 'gerund'/'plural'
        describe the action (e.g. 'Cancelling'/'Work Requirements') and
        'match_word' is how the CLI selects entities ('tags' or 'names').
        """
        if self._operation_in_flight(title) or not self._properties_are_usable():
            return

        name_args = self._name_glob_args()
        scope = self._listing_scope(match_word, name_args)

        if self._confirmations_disabled or action_key in self._skip_confirmations:
            self._output.log(
                f"Confirmations suppressed for '{action_key}';"
                f" acting on all {plural}{scope}"
            )
            self._run_command_in_subprocess(command, run_args + name_args)
            return

        self._output.log(f"Checking which {plural} would be affected...")
        self.log_output.repaint()
        entities = self._capture_dry_run_summaries(command, extra_args=name_args)

        if entities is not None and not entities:
            self._output.log(f"No matching {plural}{scope}")
            return

        abort_clause = ", and aborting their running tasks" if and_abort else ""
        body = f"{gerund} {plural}{scope}{abort_clause}.\n\nThis cannot be undone."
        if entities is None:
            self._output.log(
                "Could not list affected entities; confirming by scope instead"
            )

        rows = entity_rows(entities) if entities else None
        result = self._confirm_destructive(action_key, title, body, rows=rows)
        if not result.proceed:
            return

        if result.handles is None:
            # Nothing was individually selectable — the enumeration failed — so
            # run over the scope the user has just confirmed.
            self._run_command_in_subprocess(command, run_args + name_args)
            return

        if not result.handles:
            # 'run_args + []' IS the whole-scope command, so an empty selection
            # must never fall through to the run below.
            self._output.log(f"Nothing selected to act on; no {plural} affected")
            return

        self._run_command_in_subprocess(
            command,
            run_args + result.handles,
            log_args=self._abbreviated_run_args(run_args, result.handles, plural),
        )

    def _notify(self, message: str):
        """
        Log a message and show it in a modal notice, for a click that did nothing
        and would otherwise say so only in the output window.

        Logged first and always, so the output window keeps the whole narrative
        with its timestamps whether or not a dialog is shown — and so the notice
        survives the two cases that get no dialog: an unattended session, where
        '--yes' says nobody is there to press OK and a modal would hang, and
        shutdown, where the widgets are going away.
        """
        self._output.log(message)
        if self._confirmations_disabled or self._shutting_down:
            return
        dialog = self._build_notice_dialog(message)
        try:
            dialog.exec()
        finally:
            # Parented to the main window, so without this every notice would
            # live for the rest of the session.
            dialog.deleteLater()

    def _build_notice_dialog(self, message: str) -> QMessageBox:
        """
        Build (but do not show) the notice: one message, one OK button.

        Plain text deliberately: a notice carries filesystem paths and entity
        names, and as rich text a Windows path loses its backslashes while
        anything between angle brackets disappears as an unknown tag.

        Split from _notify so that a test can arm the real dialog rather than
        stub exec() — the convention the other dialogs here follow.
        """
        dialog = QMessageBox(self)
        dialog.setWindowTitle(WINDOW_TITLE)
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(message)
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        return dialog
