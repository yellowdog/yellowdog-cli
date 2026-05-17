"""
Shared rclone utilities: instantiation, config parsing, and binary management.
"""

import logging
import os
import platform
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager, nullcontext
from functools import cache
from pathlib import Path

from rclone_api import Config, Rclone

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.printing import print_info, print_simple
from yellowdog_cli.utils.settings import RCLONE_PREFIX


@contextmanager
def _suppress_rclone_download_output():
    """
    Silence rclone-api's binary-download output.

    rclone_api/install.py calls logging.basicConfig(level=DEBUG) and writes
    to the root logger, and the 'download' package it uses emits a tqdm
    progress bar to stderr. Neither can be quieted via the Rclone() API, so
    we suppress them here by temporarily replacing the root logger's handlers
    with a NullHandler and redirecting sys.stdout/sys.stderr to /dev/null.
    """
    root = logging.getLogger()
    old_handlers = root.handlers[:]
    root.handlers = [logging.NullHandler()]
    old_stdout, old_stderr = sys.stdout, sys.stderr
    devnull = open(os.devnull, "w")
    sys.stdout = sys.stderr = devnull
    try:
        yield
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
        devnull.close()
        root.handlers = old_handlers


def _find_rclone_conf() -> Path:
    """
    Locate the system rclone configuration file.

    Respects the RCLONE_CONFIG environment variable; otherwise falls back to
    the platform-default location (~/.config/rclone/rclone.conf on Linux/macOS,
    %APPDATA%\\rclone\\rclone.conf on Windows).

    Raises an exception if no config file is found.
    """
    if env_path := os.environ.get("RCLONE_CONFIG"):
        p = Path(env_path)
        if p.exists():
            return p
        raise FileNotFoundError(f"RCLONE_CONFIG points to missing file: '{env_path}'")

    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA", "")
        p = Path(appdata) / "rclone" / "rclone.conf"
    else:
        p = Path.home() / ".config" / "rclone" / "rclone.conf"

    if p.exists():
        return p
    raise FileNotFoundError("not configured (no rclone.conf found)")


def make_rclone_for_copy(
    src_remote_str: str, dst_remote_str: str
) -> tuple[str, str, "Rclone"]:
    """
    Build an Rclone instance with both src and dst remotes configured.
    Returns (src_remote_name, dst_remote_name, rclone).
    """
    src_name, src_ini = parse_rclone_config(src_remote_str)
    dst_name, dst_ini = parse_rclone_config(dst_remote_str)

    if src_ini is None and dst_ini is None:
        return src_name, dst_name, make_rclone(None)

    # At least one remote uses inline config; build a combined INI
    sections: list[str] = []
    if src_ini is None or dst_ini is None:
        # Include the system conf so named remotes are accessible
        sys_conf_path = _find_rclone_conf()
        sections.append(sys_conf_path.read_text())
    if src_ini is not None:
        sections.append(src_ini)
    if dst_ini is not None:
        sections.append(dst_ini)

    return src_name, dst_name, make_rclone(Config("\n\n".join(sections)))


def make_rclone(config: Config | None) -> Rclone:
    """
    Instantiate Rclone, suppressing download output when --quiet is active.
    Passing None causes rclone to use the system rclone.conf (for locally
    configured remotes).
    """
    rclone_conf: Config | Path = _find_rclone_conf() if config is None else config
    ctx = _suppress_rclone_download_output() if ARGS_PARSER.quiet else nullcontext()
    with ctx:
        return Rclone(rclone_conf)


@cache
def parse_rclone_config(config_str: str) -> tuple[str, str | None]:
    """
    Parses the config portion of an rclone remote string.

    Accepts either a plain remote name (looked up in the system rclone.conf)
    or an inline config string of the form 'NAME,type=...,key=val,...'.
    An optional leading 'rclone:' prefix is stripped before parsing.

    Returns:
        (remote_name, config_ini_section_str_or_None)
        Returns None for the config when there are no inline parameters.
    """
    if config_str.startswith(RCLONE_PREFIX):
        config_str = config_str[len(RCLONE_PREFIX) :]

    if "," not in config_str:
        # No inline params: remote is defined in the system rclone.conf
        remote_name = config_str.strip() or "remote"
        return remote_name, None

    remote_name, params_str = config_str.split(",", 1)
    remote_name = remote_name.strip() or "remote"

    # Parse params (simple comma split - assumes no commas inside values)
    params = {}
    # Split on comma only when followed by key=
    param_list = re.split(r",(?=[a-zA-Z_0-9]+=)", params_str)
    for param in param_list:
        param = param.strip()
        if "=" in param:
            key, value = param.split("=", 1)
            params[key.strip()] = value.strip().strip("'\"")

    # Build valid rclone INI section
    lines = [f"[{remote_name}]"]
    for key, value in params.items():
        lines.append(f"{key} = {value}")
    config_section = "\n".join(lines)

    return remote_name, config_section


def upgrade_rclone():
    """
    Upgrade the rclone binary.
    """
    print_info("Downloading / upgrading the rclone binary")
    ctx = _suppress_rclone_download_output() if ARGS_PARSER.quiet else nullcontext()
    with ctx:
        Rclone.upgrade_rclone()


def which_rclone() -> None:
    """
    Report the path, source, and version of the rclone binary used by rclone_api.
    Mirrors rclone_api's lookup order (system PATH first, then its download cache)
    without triggering a download if no binary is present.
    """
    from rclone_api.util import _RCLONE_EXE

    system_path = shutil.which("rclone")
    if system_path is not None:
        rclone_path = system_path
        source = "system PATH"
    elif _RCLONE_EXE.exists():
        rclone_path = str(_RCLONE_EXE)
        source = "rclone_api cache"
    else:
        print_info("rclone binary not found; run --upgrade-rclone to download it")
        return

    if ARGS_PARSER.quiet:
        print_simple(rclone_path, override_quiet=True)
        return

    result = subprocess.run([rclone_path, "--version"], capture_output=True, text=True)
    version = result.stdout.splitlines()[0] if result.stdout else "unknown"
    print_info(f"rclone: {rclone_path} ({source})")
    print_info(f"Version: {version}")
