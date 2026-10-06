"""
Shared rclone utilities: instantiation, config parsing, and binary management.
"""

# rclone_api is heavy to import (~90 ms). It is imported lazily inside the
# functions that actually use it so that commands importing this module for
# other helpers (e.g. parse_rclone_config, find_rclone) don't pay that cost.
from __future__ import annotations

import logging
import os
import platform
import re
import sys
from contextlib import contextmanager, nullcontext
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rclone_api import Config, Rclone

from yellowdog_cli.utils.dataclient.rclone_version import (
    find_rclone,
    rclone_version_line,
)
from yellowdog_cli.utils.output_settings import OUTPUT
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
    devnull = open(os.devnull, "w", encoding="utf-8")
    sys.stdout = sys.stderr = devnull
    try:
        yield
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
        devnull.close()
        root.handlers = old_handlers


def _keep_logging_off_stdout() -> None:
    """
    Move any root logging handler that writes to stdout onto stderr.

    Importing rclone_api installs one (rclone_api/log.py's basicConfig, a
    StreamHandler on sys.stdout at INFO), through which it logs its first-run
    binary download and some of its errors; under '--json' stdout holds only
    the result document, which those lines would corrupt.
    """
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.StreamHandler) and handler.stream in (
            sys.stdout,
            sys.__stdout__,
        ):
            handler.setStream(sys.stderr)


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
        raise FileNotFoundError(
            f"RCLONE_CONFIG names an rclone configuration file that does not"
            f" exist: '{env_path}'"
        )

    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA", "")
        p = Path(appdata) / "rclone" / "rclone.conf"
    else:
        p = Path.home() / ".config" / "rclone" / "rclone.conf"

    if p.exists():
        return p
    raise FileNotFoundError(
        f"No rclone configuration file found (looked for '{p}'); set"
        " RCLONE_CONFIG, or use an inline connection string"
    )


def _unique_remote_name(name: str, suffix: str, taken: set[str]) -> str:
    candidate = f"{name}-{suffix}"
    count = 2
    while candidate in taken:
        candidate = f"{name}-{suffix}{count}"
        count += 1
    return candidate


def make_rclone_for_copy(
    src_remote_str: str, dst_remote_str: str
) -> tuple[str, str, Rclone]:
    """
    Build an Rclone instance with both src and dst remotes configured.

    Remote names must be unique in the combined config: an inline remote that
    shares its name with the other inline remote (or with a remote in the
    system rclone.conf) would otherwise silently resolve both endpoints to a
    single backend. Colliding inline remotes are renamed, so callers must use
    the returned names when building paths.

    Returns (src_remote_name, dst_remote_name, rclone).
    """
    from rclone_api import Config

    src_name, src_ini = parse_rclone_config(src_remote_str)
    dst_name, dst_ini = parse_rclone_config(dst_remote_str)

    if src_ini is None and dst_ini is None:
        return src_name, dst_name, make_rclone(None)

    # Identical inline configs on both sides: one shared section suffices
    if src_ini is not None and src_ini == dst_ini:
        return src_name, dst_name, make_rclone(Config(src_ini))

    # At least one remote uses inline config; build a combined INI
    sections: list[str] = []
    taken: set[str] = set()
    if src_ini is None or dst_ini is None:
        # Include the system conf so named remotes are accessible
        sys_conf = _find_rclone_conf().read_text(encoding="utf-8")
        sections.append(sys_conf)
        taken.update(re.findall(r"^\[(.+)\]", sys_conf, flags=re.MULTILINE))

    if src_ini is not None:
        if src_name in taken:
            new_name = _unique_remote_name(src_name, "src", taken)
            src_ini = src_ini.replace(f"[{src_name}]", f"[{new_name}]", 1)
            src_name = new_name
        taken.add(src_name)
        sections.append(src_ini)

    if dst_ini is not None:
        if dst_name in taken:
            new_name = _unique_remote_name(dst_name, "dst", taken)
            dst_ini = dst_ini.replace(f"[{dst_name}]", f"[{new_name}]", 1)
            dst_name = new_name
        taken.add(dst_name)
        sections.append(dst_ini)

    return src_name, dst_name, make_rclone(Config("\n\n".join(sections)))


def make_rclone(config: Config | None) -> Rclone:
    """
    Instantiate Rclone, suppressing download output when --quiet is active.
    Passing None causes rclone to use the system rclone.conf (for locally
    configured remotes).
    """
    from rclone_api import Rclone

    _keep_logging_off_stdout()
    rclone_conf: Config | Path = _find_rclone_conf() if config is None else config
    ctx = _suppress_rclone_download_output() if OUTPUT.quiet else nullcontext()
    with ctx:
        return Rclone(rclone_conf)


# A parameter's start, 'key=', spaces allowed around the '='; and a comma that
# begins the next one, which ends an unquoted value
_PARAMETER_START = re.compile(r"\s*([A-Za-z0-9_]+)\s*=\s*")
_NEXT_PARAMETER = re.compile(r",(?=\s*[A-Za-z0-9_]+\s*=)")


def _parameters(params: str) -> dict[str, str]:
    """
    An inline remote's 'key=value' parameters, read as rclone reads a
    connection string's: a value in double or single quotes may hold commas
    (a doubled quote is the quote itself), and an unquoted value runs to the
    comma that begins the next parameter. Text that is no 'key=value' is
    ignored.
    """
    result: dict[str, str] = {}
    position = 0
    while position < len(params):
        match = _PARAMETER_START.match(params, position)
        if match is None:
            following = _NEXT_PARAMETER.search(params, position)
            if following is None:
                break
            position = following.end()
            continue
        key, position = match.group(1), match.end()
        if params[position : position + 1] in ('"', "'"):
            quote = params[position]
            position += 1
            value: list[str] = []
            while position < len(params):
                character = params[position]
                if character == quote:
                    if params[position + 1 : position + 2] == quote:
                        value.append(quote)  # A doubled quote is the quote
                        position += 2
                        continue
                    position += 1
                    break
                value.append(character)
                position += 1
            result[key] = "".join(value)
            comma = params.find(",", position)
            position = len(params) if comma == -1 else comma + 1
        else:
            following = _NEXT_PARAMETER.search(params, position)
            end = len(params) if following is None else following.start()
            result[key] = params[position:end].strip()
            position = len(params) if following is None else end + 1
    return result


@cache
def parse_rclone_config(config_str: str) -> tuple[str, str | None]:
    """
    Parses the config portion of an rclone remote string.

    Accepts a plain remote name (looked up in the system rclone.conf), an
    inline config string of the form 'NAME,type=...,key=val,...', or
    rclone's own ':backend,key=val,...' form, read as a remote named for its
    backend with that 'type'. An optional leading 'rclone:' prefix is
    stripped before parsing. Values are read as rclone reads them (see
    _parameters()).

    Returns:
        (remote_name, config_ini_section_str_or_None)
        Returns None for the config when there are no inline parameters.
    """
    if config_str.startswith(RCLONE_PREFIX):
        config_str = config_str[len(RCLONE_PREFIX) :]

    remote_name, _, params_str = config_str.partition(",")
    remote_name = remote_name.strip()
    params = _parameters(params_str)

    if remote_name.startswith(":"):
        # rclone's ':backend' form: the backend is the remote's type
        backend = remote_name[1:]
        remote_name = backend or "remote"
        params = {"type": backend, **params} if "type" not in params else params
    elif not params_str:
        # No inline params: remote is defined in the system rclone.conf
        return remote_name or "remote", None
    remote_name = remote_name or "remote"

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
    from rclone_api import Rclone

    _keep_logging_off_stdout()
    print_info("Downloading / upgrading the rclone binary")
    ctx = _suppress_rclone_download_output() if OUTPUT.quiet else nullcontext()
    with ctx:
        Rclone.upgrade_rclone()


def which_rclone() -> None:
    """
    Report the path, source, and version of the rclone binary used by rclone_api.
    Mirrors rclone_api's lookup order (system PATH first, then its download cache)
    without triggering a download if no binary is present.
    """
    found = find_rclone()
    if found is None:
        print_info("rclone binary not found; run --upgrade-rclone to download it")
        return

    rclone_path, source = found
    if OUTPUT.quiet:
        print_simple(rclone_path, override_quiet=True)
        return

    print_info(f"rclone: {rclone_path} ({source})")
    print_info(f"Version: {rclone_version_line(rclone_path)}")


# An inline remote's parameters that are never secrets, and say what it is
SHOWN_REMOTE_PARAMETERS = ("type", "provider")


# An inline connection string's parameters: 'key=value', each after a comma,
# spaces allowed around the '=' as the parser allows them
_INLINE_REMOTE_PARAMETER = re.compile(r",\s*([A-Za-z0-9_]+)\s*=")


def is_inline_remote(value: str) -> bool:
    """
    Whether 'value' is an inline rclone connection string, and so carries
    parameters that may be credentials: either rclone's own form, a
    ':backend' followed by parameters, or the CLI's 'NAME,type=...' form,
    each with an optional 'rclone:' prefix and trailing ':path'. Anything
    else with a comma in it -- which parse_rclone_config() would read as a
    remote -- is not, so an ordinary value is never taken for one.
    """
    config = value.strip()
    if config.startswith(RCLONE_PREFIX):
        config = config[len(RCLONE_PREFIX) :]
    keys = _INLINE_REMOTE_PARAMETER.findall(config)
    if not keys or not re.match(r":?[\w.-]+\s*,", config):
        return False
    return config.startswith(":") or "type" in keys


def shown_remote(remote: str) -> str:
    """
    A remote as a report may show it. A named remote ('myremote:') is shown
    as is; an inline connection string keeps its 'rclone:' prefix, name,
    type and provider, and every other parameter's value is withheld, since
    those are where its credentials go -- and yd-doctor's report is one the
    README says to paste, while yd-variables' is one that gets sent along
    with it. A trailing ':path' is withheld with the last parameter, because
    it cannot be told apart from a ':port' in that parameter's URL.
    """
    prefix = RCLONE_PREFIX if remote.startswith(RCLONE_PREFIX) else ""
    config = remote[len(prefix) :].strip()
    remote_name, section = parse_rclone_config(remote)
    if section is None:
        return remote
    # rclone's ':backend' form is shown as written: its 'type' is the backend
    # the parser added, unless the string also gave one
    rclone_form = config.startswith(":")
    implied_type = rclone_form and "type" not in _INLINE_REMOTE_PARAMETER.findall(
        config
    )
    if rclone_form:
        remote_name = ":" + remote_name
    kept: list[str] = []
    withheld = 0
    for line in section.splitlines()[1:]:
        key, _, value = line.partition(" = ")
        if key == "type" and implied_type:
            continue
        if key in SHOWN_REMOTE_PARAMETERS:
            kept.append(f"{key}={value.rstrip(':')}")
        else:
            withheld += 1
    if withheld:
        kept.append(f"<{withheld} parameter{'' if withheld == 1 else 's'} redacted>")
    trailing = ":" if remote.rstrip().endswith(":") else ""
    return prefix + ",".join([remote_name, *kept]) + trailing
