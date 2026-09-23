"""
What the confirmation and chooser dialogs list and hand back: the entities
and objects a dry run enumerated, the checkable rows made from them, the
outcome of a confirmation, and the helpers that read and set a selection
list's check states.
"""

from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QListWidget, QPushButton

from yellowdog_cli.utils.glob_utils import contains_glob_chars

MAX_DIALOG_LIST_ROWS = 12  # visible entity rows before the list scrolls
ENTITY_ROW_GAP = 2  # spaces between the name and status columns


@dataclass(frozen=True)
class EntitySummary:
    """
    The identity of one entity in a '-D --json' enumeration: the YDID used to
    target it on the command line, plus the name and status shown to the user.
    """

    id: str
    name: str
    status: str | None


def parse_entity_summaries(parsed: list) -> list[EntitySummary] | None:
    """
    Convert a parsed '-D --json' array into EntitySummary objects. Returns None
    if any row is not a dict or lacks an 'id' or a 'name': without a YDID the
    entity cannot be targeted individually, and a selection must never fall back
    to name-based targeting, because names are not guaranteed unique and the
    action is destructive.
    """
    summaries: list[EntitySummary] = []
    for obj in parsed:
        if not isinstance(obj, dict):
            return None
        entity_id, name = obj.get("id"), obj.get("name")
        if not entity_id or not name:
            return None
        status = obj.get("status")
        summaries.append(
            EntitySummary(
                id=str(entity_id),
                name=str(name),
                status=None if status is None else str(status),
            )
        )
    return summaries


@dataclass(frozen=True)
class SelectableRow:
    """
    One row of a checkable listing: the text the user reads, the handle passed
    back to the command if the row stays ticked, and the tooltip. The handle is
    deliberately opaque — that is what lets one widget serve both entity YDIDs
    and object storage paths.
    """

    display: str
    handle: str
    tooltip: str


@dataclass(frozen=True)
class Confirmation:
    """
    The outcome of a destructive-action confirmation. 'proceed' is False when the
    user declined or dismissed the dialog. 'handles' is None when there was
    nothing individually selectable — a suppressed confirmation, or an
    enumeration that failed — in which case the caller acts over its whole scope.
    Otherwise 'handles' is exactly what the user left ticked, and an empty list
    means the user deselected everything, which must act on nothing at all.

    The three states are separate fields rather than a nullable list because the
    difference between 'whole scope' and 'nothing' is the difference between
    destroying everything and destroying nothing.
    """

    proceed: bool
    handles: list[str] | None

    def __bool__(self) -> bool:
        """
        Refuse truthiness. Both 'act over the whole scope' and 'act on nothing'
        are legitimate outcomes, so a bare 'if confirmation:' cannot mean
        anything safe — and unlike the list sentinel this replaced, an always-
        truthy object would proceed even when the user declined. Callers must
        read .proceed explicitly.
        """
        raise TypeError("check Confirmation.proceed explicitly, not truthiness")


def entity_rows(entities: list[EntitySummary]) -> list[SelectableRow]:
    """
    Rows for an entity listing: the name padded to a common width so the status
    column lines up, with the YDID as the handle and kept out of the row text
    (full YDIDs are long enough to push the readable columns off-screen). The
    tooltip carries both, so a row elided by a narrow dialog still has a
    recovery path.
    """
    name_width = max((len(entity.name) for entity in entities), default=0)
    gap = " " * ENTITY_ROW_GAP
    return [
        SelectableRow(
            display=(
                f"{entity.name.ljust(name_width)}{gap}{entity.status or ''}".rstrip()
            ),
            handle=entity.id,
            tooltip=f"{entity.name}\n{entity.id}",
        )
        for entity in entities
    ]


@dataclass(frozen=True)
class ObjectSummary:
    """
    One item in a 'yd-delete -D --json' enumeration: the resolved remote path
    used to delete it, its display name (directories carry a trailing '/'), and
    whether it is a directory — which decides whether the confirmation warns
    that a tick takes the directory's whole contents.
    """

    path: str
    name: str
    is_dir: bool


def parse_object_summaries(parsed: list) -> list[ObjectSummary] | None:
    """
    Convert a parsed 'yd-delete -D --json' array into ObjectSummary objects.
    Returns None if any row is not a dict or lacks a 'path' or a 'name': without
    a path the object cannot be targeted, and guessing one would delete
    something other than what the user ticked. A missing 'isDir' defaults to
    False rather than rejecting the row, because it affects only the display and
    the recursion caveat, never which paths are deleted.
    """
    summaries: list[ObjectSummary] = []
    for obj in parsed:
        if not isinstance(obj, dict):
            return None
        path, name = obj.get("path"), obj.get("name")
        if not path or not name:
            return None
        summaries.append(
            ObjectSummary(path=str(path), name=str(name), is_dir=bool(obj.get("isDir")))
        )
    return summaries


def object_rows(objects: list[ObjectSummary]) -> list[SelectableRow]:
    """
    Rows for an object listing: a single column of display names (a directory
    keeps its trailing '/'), with the resolved remote path as the handle. No
    column padding, unlike entity rows — there is no second column to align.
    """
    return [
        SelectableRow(
            display=obj.name,
            handle=obj.path,
            tooltip=f"{obj.name}\n{obj.path}",
        )
        for obj in objects
    ]


def path_would_be_globbed(remote_path: str) -> bool:
    """
    Whether 'yd-delete' would treat this remote path as a wildcard pattern
    rather than a literal object. Mirrors dataclient_utils.is_glob (which
    Commander cannot import, since that module pulls in rclone_api): strip a
    leading 'remote:' prefix, then look for glob metacharacters.

    This matters because an object whose own name contains '*', '?' or '['
    cannot be targeted by path at all — 'yd-delete' would expand it and act on
    whatever it matched instead, which for 'a[1].txt' is the sibling 'a1.txt'.
    """
    path_part = remote_path.split(":", 1)[-1] if ":" in remote_path else remote_path
    return contains_glob_chars(path_part)


def checked_handles(listing: QListWidget) -> list[str]:
    """
    The handles of the ticked rows of a selection list, in list order.
    """
    handles: list[str] = []
    for index in range(listing.count()):
        item = listing.item(index)
        if item is not None and item.checkState() == Qt.CheckState.Checked:
            handles.append(item.data(Qt.ItemDataRole.UserRole))
    return handles


def set_all_check_states(
    listing: QListWidget, state: Qt.CheckState, *_signal_args
) -> None:
    """
    Set every row of a selection list to the same check state, for the All / None
    buttons. Takes and ignores the trailing signal arguments so it can be
    connected to 'clicked' directly.
    """
    for index in range(listing.count()):
        item = listing.item(index)
        if item is not None:
            item.setCheckState(state)


def update_selection_state(
    listing: QListWidget,
    count_label: QLabel,
    yes_btn: QPushButton,
    *_signal_args,
) -> None:
    """
    Refresh the 'N of M selected' label and gate the Yes button on something
    being selected, so the dialog cannot confirm a run that would do nothing.
    """
    selected = len(checked_handles(listing))
    count_label.setText(f"{selected} of {listing.count()} selected")
    yes_btn.setEnabled(selected > 0)
