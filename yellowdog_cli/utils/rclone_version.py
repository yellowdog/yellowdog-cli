"""
Locate the rclone binary and report its version.

Deliberately dependency-free (stdlib only, with a lazy/guarded rclone_api
import) so it can be used both by yd-version — which is a standalone command
that must not import the args/wrapper machinery — and by rclone_utils.
"""

import shutil
import subprocess

# How long 'rclone --version' may take: a binary that hangs (a quarantine
# prompt, a stalled mount, a broken wrapper) must not hang yd-version
RCLONE_VERSION_TIMEOUT = 5

NOT_INSTALLED = "Not installed"
UNKNOWN = "unknown"


def find_rclone() -> tuple[str, str] | None:
    """
    Locate the rclone binary that rclone_api would use, mirroring its lookup
    order (system PATH first, then the rclone_api download cache) without
    triggering a download. Returns (path, source) or None if not found.
    """
    system_path = shutil.which("rclone")
    if system_path is not None:
        return system_path, "system PATH"

    try:
        from rclone_api.util import _RCLONE_EXE

        if _RCLONE_EXE.exists():
            return str(_RCLONE_EXE), "rclone_api cache"
    except ImportError:
        pass

    return None


def rclone_version_line(rclone_path: str) -> str:
    """
    The first line of `rclone --version` (e.g. 'rclone v1.74.3'), or 'unknown'
    if the binary cannot be run, produces no output, or takes longer than
    RCLONE_VERSION_TIMEOUT.
    """
    try:
        result = subprocess.run(
            [rclone_path, "--version"],
            capture_output=True,
            text=True,
            timeout=RCLONE_VERSION_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return UNKNOWN
    return result.stdout.splitlines()[0] if result.stdout else UNKNOWN


def rclone_version() -> str:
    """
    The bare rclone version, without any leading 'v' (e.g. '1.74.3'), for
    consistency with the other versions reported by yd-version. Returns
    'Not installed' if no binary is found, or 'unknown' if it cannot be run.
    """
    found = find_rclone()
    if found is None:
        return NOT_INSTALLED

    line = rclone_version_line(found[0])
    if line == UNKNOWN:
        return UNKNOWN

    tokens = line.split()
    version = tokens[1] if len(tokens) >= 2 else tokens[0]
    return version[1:] if version.startswith("v") else version
