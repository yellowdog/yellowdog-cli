"""
Which platform Commander is running on. Decided once, at import, and refused
outright on anything but the three Commander knows how to open a file on,
rather than guessing. Qt-free.
"""

import sys
from platform import system as _platform_system

_system = _platform_system()
MACOS = _system == "Darwin"
LINUX = _system == "Linux"
WINDOWS = _system == "Windows"

if not (MACOS or LINUX or WINDOWS):
    print(f"Error: unrecognised platform: {_system}", file=sys.stderr)
    sys.exit(1)
