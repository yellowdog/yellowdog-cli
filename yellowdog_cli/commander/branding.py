"""
The YellowDog dog, which the main window and the Usage Explorer each show at
their top right.
"""

from os.path import abspath, dirname, join

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon, QPixmap

# The YellowDog dog in YellowDog yellow (#FAB842), which reads on the light and
# the dark window alike, so one image serves both
BRANDING_IMAGE = join(dirname(abspath(__file__)), "images", "IconYellowDog.svg")
BRANDING_IMAGE_SIZE = 54


def branding_pixmap() -> QPixmap:
    """
    The dog drawn from the SVG at BRANDING_IMAGE_SIZE, crisp on any screen.
    """
    return QIcon(BRANDING_IMAGE).pixmap(QSize(BRANDING_IMAGE_SIZE, BRANDING_IMAGE_SIZE))
