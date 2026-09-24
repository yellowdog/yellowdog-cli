"""
The correction for an item view's check indicators on a style that paints
them at the painter's origin: Qt's macOS style under the macOS 26 control
redesign. See check_indicator_is_misplaced for the cause.
"""

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QImage, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QProxyStyle,
    QStyle,
    QStyleFactory,
    QStyleOption,
    QStyleOptionViewItem,
    QWidget,
)

# The probe below paints a check indicator into a pixmap of its own: an
# indicator-sized rect set well away from both edges, and a pixmap with room for
# a style that draws a larger control than it was asked for.
PROBE_INDICATOR_SIZE = 16
PROBE_INDICATOR_ORIGIN = 32
PROBE_PIXMAP_SIZE = 64


def check_indicator_is_misplaced(style: QStyle, widget: QWidget | None = None) -> bool:
    """
    Does this style paint an item view's check indicator at the painter's origin
    instead of at the rect it is handed?

    macOS 26 redesigned the system controls, and AppKit gates the redesign on the
    *main executable's linked SDK*. Where that is the macOS 26 SDK or later, Qt's
    macOS style draws a checkbox or radio indicator as the new 16x16 control at
    the painter's origin, ignoring the rect it computed; linked against an
    earlier SDK, the same Qt draws the legacy 18x18 control in the rect. Only
    those two indicators are affected — push buttons and combo boxes draw in
    their rect either way.

    That was established causally, one interpreter at a time, by rewriting
    nothing but the SDK field with vtool: 26.5 -> 15.5 on a Homebrew Python's
    Python.app fixes it, 15.5 -> 26.5 on a uv-managed interpreter breaks it, and
    Apple's own opt-out (UIDesignRequiresCompatibility in the app's Info.plist)
    fixes it as well.

    It therefore looks like a Python or PyQt6 version problem and is neither.
    Homebrew rebuilds its interpreters against the current SDK, so every Homebrew
    build measured misplaces it (3.10, 3.12, 3.13, 3.14); uv-managed standalone
    builds target an older one, so every one of those places it correctly (3.10,
    3.12, 3.15) — same PyQt6, same Qt binaries, byte for byte. PyQt6 6.10.1 and
    6.11.0 behave identically on either. Two earlier readings of this, as a Qt
    6.11.0 regression and then as a framework-build difference, were both
    artefacts of that correlation.

    Qt knows: 'Qt for macOS - Specific Issues' records that its Widgets and Quick
    macOS styles "may exhibit drawing artefacts" under Liquid Glass, and names
    the same two escapes measured above — build with Xcode 16, or set
    UIDesignRequiresCompatibility. Both belong to whoever builds the executable,
    which for a Python GUI application is whoever built the interpreter, so
    neither is available to a library running inside it. Correcting the painting
    is the only lever this end of the problem has.

    Hence measuring, rather than keying off a version, a platform or a style
    name: nothing available at runtime names the real condition, and the
    correction has to switch itself off when Qt adapts to the redesign or Apple
    retires the compatibility path. Applied to a style that places the indicator
    correctly, it would offset it twice — the same bug the other way up.

    The probe paints into a transparent pixmap and asks only where the ink
    landed, so it reads no colour and needs no display. A style that paints
    nothing at all reads as not misplaced — which is the honest answer, since a
    translation would have nothing to rescue. Qt's macOS style under the
    offscreen platform is exactly that case, and is why the tests stand a proxy
    style in for it rather than selecting it.
    """
    rect = QRect(
        PROBE_INDICATOR_ORIGIN,
        PROBE_INDICATOR_ORIGIN,
        PROBE_INDICATOR_SIZE,
        PROBE_INDICATOR_SIZE,
    )
    pixmap = QPixmap(PROBE_PIXMAP_SIZE, PROBE_PIXMAP_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)

    option = QStyleOptionViewItem()
    if widget is not None:
        option.initFrom(widget)
    option.rect = rect
    option.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_On

    painter = QPainter(pixmap)
    style.drawPrimitive(
        QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck, option, painter, widget
    )
    painter.end()

    image = pixmap.toImage()
    at_the_origin = QRect(0, 0, rect.width(), rect.height())
    return _has_ink(image, at_the_origin) and not _has_ink(image, rect)


def _has_ink(image: QImage, rect: QRect) -> bool:
    """
    Was anything painted inside this rect of an image filled with transparency?
    """
    for y in range(rect.top(), rect.bottom() + 1):
        for x in range(rect.left(), rect.right() + 1):
            if image.pixelColor(x, y).alpha() > 0:
                return True
    return False


class CheckIndicatorPlacement(QProxyStyle):
    """
    Paint an item view's check indicator where the view asked for it, on a style
    that ignores the position of the rect it is given (see
    check_indicator_is_misplaced).

    An item view clips each row's painting to that row, so an indicator painted
    at the painter's origin survives only for the topmost row: a ten-row
    selection list showed one checkbox, and the nine rows below it looked
    unticked — and untickable — however they were clicked. Only the painting was
    wrong; the ticking underneath it worked throughout, which is what made it
    look like a dialog that allowed one selection.

    Translating the painter is what corrects it, rather than moving the rect: it
    is the rect's position that the style is ignoring, so the painter's own
    transform is the only thing left to carry it.

    Given the style it corrects, and owns it: QProxyStyle deletes the style it
    wraps, so what it is handed must be an instance of its own (see
    platform_style) and never the application's.
    """

    def drawPrimitive(
        self,
        element: QStyle.PrimitiveElement,
        option: QStyleOption | None,
        painter: QPainter | None,
        widget: QWidget | None = None,
    ) -> None:
        if (
            element != QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck
            or option is None
            or painter is None
        ):
            super().drawPrimitive(element, option, painter, widget)
            return

        painter.save()
        painter.translate(option.rect.topLeft())
        super().drawPrimitive(element, option, painter, widget)
        painter.restore()


def platform_style() -> QStyle | None:
    """
    A style object of this application's own style, for a proxy style to wrap and
    take ownership of. None if the style cannot be built by name.

    A function, rather than QProxyStyle's own base-less construction, for two
    reasons. QProxyStyle without a base wraps a fresh instance of the *desktop*
    style, not of the style the application is actually using, which on Linux is
    Fusion under Dark Mode whatever the desktop's is. And the tests need a seam:
    a style that misplaces its check indicators cannot be reached any other way,
    the one that really does so drawing nothing at all under the offscreen
    platform.
    """
    style = QApplication.style()
    return None if style is None else QStyleFactory.create(style.objectName())


def fix_check_indicator_placement(view: QAbstractItemView) -> None:
    """
    Correct where this view's style paints its check indicators, if it needs it.

    The correction is parented to the view because setStyle() does not take
    ownership: left unparented it would be collected while the view was still
    painting with it.
    """
    style = platform_style()
    if style is None or not check_indicator_is_misplaced(style, view):
        return
    correction = CheckIndicatorPlacement(style)
    correction.setParent(view)
    view.setStyle(correction)
