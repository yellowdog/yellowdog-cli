"""
Tests for the Commander's namespace / tag / object-path placeholder text.

Also guards the repaint strategy: the viewports are updated (scheduled) rather
than repainted (forced synchronously), because forcing a text widget to paint
from the context these callers run in — straight after _parse_yd_config's
nested event loop — is what appears to provoke macOS 'TSMSendMessageToUIServer
... FAILED(-1)' log bursts.
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QEvent, QObject

from yellowdog_cli.commander.commander import YellowDogApp


class PaintCounter(QObject):
    """
    Counts Paint events per object. An event filter is used because assigning
    to paintEvent on a C++-owned widget does not intercept Qt's dispatch.
    """

    def __init__(self):
        super().__init__()
        self.counts: dict[int, int] = {}

    def eventFilter(self, obj, event):
        if event is not None and event.type() == QEvent.Type.Paint:
            self.counts[id(obj)] = self.counts.get(id(obj), 0) + 1
        return False


@pytest.fixture
def win(qapp):
    window = YellowDogApp()
    window.show()
    qapp.processEvents()
    yield window
    window.close()


def _fields(win):
    return [win.namespace_override, win.tag_override, win.object_path_override]


def test_placeholders_show_the_namespace_tag_and_object_path(win):
    win._set_placeholders("yd-demo", "my-tag")

    assert [field.placeholderText() for field in _fields(win)] == [
        "yd-demo",
        "my-tag",
        "my-tag*",  # the default object path is derived from the tag
    ]


def test_object_path_placeholder_is_empty_without_a_tag(win):
    win._set_placeholders("yd-demo", "")

    assert win.object_path_override.placeholderText() == ""


def test_placeholders_can_be_cleared(win):
    win._set_placeholders("yd-demo", "my-tag")
    win._set_placeholders("", "")

    assert [field.placeholderText() for field in _fields(win)] == ["", "", ""]


def test_repaint_is_scheduled_not_forced(win, qapp):
    """
    Setting the placeholders must not paint synchronously, but the viewports
    must still be repainted on the next turn of the event loop.
    """
    viewports = [field.viewport() for field in _fields(win)]
    counter = PaintCounter()
    for viewport in viewports:
        viewport.installEventFilter(counter)

    def counts():
        return [counter.counts.get(id(viewport), 0) for viewport in viewports]

    # Control: a forced repaint is observable in this environment, so a count
    # of zero below means 'not painted', not 'not measurable'
    for viewport in viewports:
        viewport.repaint()
    assert all(count >= 1 for count in counts())
    counter.counts.clear()

    win._set_placeholders("yd-demo", "my-tag")
    assert counts() == [0, 0, 0], "painting should be deferred, not forced"

    qapp.processEvents()
    assert all(count >= 1 for count in counts()), "viewports were never repainted"
