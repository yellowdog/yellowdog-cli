"""
The CLI's and the SDK's versions as other modules need them: the SDK's read
from its package metadata, and the README link for this version. Shared by
yd-version, yd-help, yd-schema, yd-doctor, the argument parser ('--docs')
and the User-Agent; a utility rather than part of the yd-version command,
so that none of them imports a command module. Imports nothing heavy.
"""

import re
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version

from yellowdog_cli._version import __version__
from yellowdog_cli.utils.rclone_version import NOT_INSTALLED

SDK_DISTRIBUTION = "yellowdog-sdk"


def docs_url(version: str = __version__) -> str:
    """
    The README for this version: its release tag's, or for a version that
    is no release (a development build, '1.2.3.dev4'), main's, since no tag
    exists to link to.
    """
    ref = f"v{version}" if re.fullmatch(r"\d+\.\d+\.\d+", version) else "main"
    return f"https://github.com/yellowdog/yellowdog-cli/blob/{ref}/README.md"


DOCS_URL = docs_url()


def sdk_version() -> str:
    """
    The installed YellowDog SDK's version, from its package metadata: read
    without importing the package, whose __init__ builds the whole Platform
    client (~140ms), so that nothing needs the SDK just to name it.
    """
    try:
        return package_version(SDK_DISTRIBUTION)
    except PackageNotFoundError:
        return NOT_INSTALLED
