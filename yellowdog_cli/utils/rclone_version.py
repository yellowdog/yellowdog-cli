"""
Locate the rclone binary and report its version.

Deliberately dependency-free (stdlib only, with a lazy/guarded rclone_api
import) so it can be used both by yd-version — which is a standalone command
that must not import the args/wrapper machinery — and by rclone_utils.
"""

import shutil
import subprocess


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
    if the binary cannot be run or produces no output.
    """
    try:
        result = subprocess.run(
            [rclone_path, "--version"], capture_output=True, text=True
        )
    except OSError:
        return "unknown"
    return result.stdout.splitlines()[0] if result.stdout else "unknown"


def rclone_version() -> str:
    """
    The bare rclone version, without any leading 'v' (e.g. '1.74.3'), for
    consistency with the other versions reported by yd-version. Returns
    'Not installed' if no binary is found, or 'unknown' if it cannot be run.
    """
    found = find_rclone()
    if found is None:
        return "Not installed"

    line = rclone_version_line(found[0])
    if line == "unknown":
        return "unknown"

    tokens = line.split()
    version = tokens[1] if len(tokens) >= 2 else tokens[0]
    return version[1:] if version.startswith("v") else version
