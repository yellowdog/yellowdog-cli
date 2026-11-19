"""
yd usage's engine: the Platform's compute usage report for a time window,
kept as the zip it arrives as in a private temporary directory, and its
Instance rows
totalled by the keys asked for.

The report (PUT usage/compute/report) is the one usage endpoint an
Application key may call: the others answer only a user's login. It is a
zip of three CSV files -- a summary, the Compute Requirements active in the
window, and one row per Instance with the seconds it spent in each status
within the window -- kept as it arrives, the CSV files read from it in
place (a tenth of their size extracted, and as quick to read), in a
directory named by a digest of what the report depends on (the URL, the
key ID, the window as given and the namespace filter). A report found
there is used, unless refreshed, while each end of its window is within
USAGE_REPORT_REUSE_SECONDS of the window asked for, whose end is taken as
now at the latest, since the Platform's report ends there: a window of
fixed past dates is used until it is removed, being one that no longer
changes, and one ending now for ten minutes after it was fetched. The
window, the time it was fetched and the report's size are said with every
summary. Each fetch removes the reports unused (neither fetched nor read)
for USAGE_REPORTS_UNUSED_SECONDS, a week, and then the least recently used
beyond USAGE_REPORTS_KEPT, so the directory stays bounded on any platform
(Windows clears its temporary directory only if told to); a report's
directory is touched when it is read, its modification time being when it
was last used. The directory is under the system's temporary directory,
per user and mode 0700 on POSIX (completion_cache.cache_directory()).

An Instance's namespace, tag and Compute Requirement name come from its
Compute Requirement's row.
"""

from __future__ import annotations

import csv
import fnmatch
import io
import json
import logging
import os
import re
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

from yellowdog_cli.utils.completion_cache import cache_directory, cache_key
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.limits import (
    USAGE_REPORT_REUSE_SECONDS,
    USAGE_REPORTS_KEPT,
    USAGE_REPORTS_UNUSED_SECONDS,
)
from yellowdog_cli.utils.printing import print_info

_LOG = logging.getLogger(__name__)

USAGE_CACHE_DIRECTORY_NAME = "yellowdog-cli-usage"
REPORT_PATH = "usage/compute/report"

REPORT_ZIP = "report.zip"
FETCHED_JSON = "fetched.json"

# The prefixes of the report's CSV files' names ('instances_<account>_<time>.csv')
SUMMARY = "summary"
REQUIREMENTS = "compute-requirements"
INSTANCES = "instances"
_REPORT_FILES = (SUMMARY, REQUIREMENTS, INSTANCES)

# The Instance CSV's status columns, as the summary names them
STATUS_COLUMNS = {
    "pending": "Pending (s)",
    "running": "Running (s)",
    "stopping": "Stopping (s)",
    "stopped": "Stopped (s)",
    "terminating": "Terminating (s)",
    "unknown": "Unknown (s)",
}

# What the usage can be grouped by: the key, and how a row gives it
GROUP_KEYS = (
    "namespace",
    "tag",
    "requirement",
    "provider",
    "region",
    "instance-type",
    "source",
    "spot",
)


class UsageReportError(Exception):
    """
    A report the Platform sent that cannot be read.
    """


@dataclass
class Report:
    """
    A usage report as kept: where its files are, the window it covers and
    when it was fetched, and the size of what the Platform sent (None for
    a report kept without it).
    """

    directory: Path
    from_time: str
    until_time: str
    fetched: datetime
    from_cache: bool
    fetched_bytes: int | None = None
    # The namespaces asked for (None for every one), and those left out as
    # not readable for usage
    namespaces: list[str] | None = None
    refused: list[str] = field(default_factory=list)

    @property
    def path(self) -> Path:
        """
        The zip itself, as the Platform sent it.
        """
        return self.directory / REPORT_ZIP


@dataclass
class UsageGroup:
    """
    The Instances sharing the grouping keys' values, and their seconds in
    each status.
    """

    keys: dict[str, str]
    instances: int = 0
    seconds: dict[str, float] = field(
        default_factory=lambda: dict.fromkeys(STATUS_COLUMNS, 0.0)
    )

    @property
    def total_seconds(self) -> float:
        return sum(self.seconds.values())


def report_key(
    ctx: RunContext, from_text: str, until_text: str, namespace: str | None
) -> str:
    """
    The digest naming a report's directory: what the report depends on,
    in 16 hex digits, enough to tell a user's reports apart and short
    enough to read.
    """
    return cache_key(
        "usage-report",
        ctx.config.url,
        ctx.config.key or "",
        from_text,
        until_text,
        namespace or "",
    )[:16]


def usage_report(
    ctx: RunContext,
    from_time: datetime,
    until_time: datetime,
    from_text: str,
    until_text: str,
    namespace: str | None,
    refresh: bool,
    now: datetime | None = None,
) -> Report:
    """
    The report for the window: the one kept for it unless refreshed, absent
    or no longer the window asked for (window_matches()), else fetched from
    the Platform and kept. Without a usable cache directory, it is kept in a
    fresh temporary one.
    """
    root = cache_directory(USAGE_CACHE_DIRECTORY_NAME)
    key = report_key(ctx, from_text, until_text, namespace)
    if root is not None:
        directory = root / key
        if not refresh:
            cached = _read_kept(directory)
            if cached is not None and window_matches(
                cached, from_time, until_time, now or datetime.now(timezone.utc)
            ):
                _LOG.debug("Using the usage report kept in %s", directory)
                _touch(directory)
                return cached
            if cached is not None:
                _LOG.debug(
                    "Not using the usage report kept in %s: its window, %s to %s,"
                    " is no longer the one asked for",
                    directory,
                    cached.from_time,
                    cached.until_time,
                )
    else:
        import tempfile

        root = Path(tempfile.mkdtemp(prefix=f"{USAGE_CACHE_DIRECTORY_NAME}-"))
        directory = root / key
    print_info("Fetching the usage report from the Platform")
    fetched = _fetch(ctx, from_time, until_time, namespace)
    _keep(root, directory, fetched)
    prune(root, keep=directory)
    report = _read_kept(directory)
    if report is None:
        raise UsageReportError(
            f"The usage report kept in '{directory}' could not be read"
        )
    report.from_cache = False
    return report


def prune(root: Path, keep: Path, now: float | None = None) -> None:
    """
    Remove the kept reports unused for USAGE_REPORTS_UNUSED_SECONDS, then
    the least recently used beyond USAGE_REPORTS_KEPT, never 'keep' (the
    report just fetched); a partial directory another fetch left is removed
    once it is that old. Each removal that fails is logged and left for the
    next.
    """
    now = time.time() if now is None else now
    try:
        entries = [path for path in root.iterdir() if path != keep]
    except OSError:
        _LOG.debug("Cannot list the kept usage reports in %s", root, exc_info=True)
        return
    used: list[tuple[float, Path]] = []
    for path in entries:
        try:
            info = path.lstat()
        except OSError:
            _LOG.debug("Cannot read the kept usage report %s", path, exc_info=True)
            continue
        if now - info.st_mtime > USAGE_REPORTS_UNUSED_SECONDS:
            _remove(path, "unused for a week")
        elif ".part-" not in path.name:
            used.append((info.st_mtime, path))
    surplus = len(used) + 1 - USAGE_REPORTS_KEPT  # 'keep' counts too
    for _, path in sorted(used)[: max(surplus, 0)]:
        _remove(path, f"beyond the {USAGE_REPORTS_KEPT} most recently used")


def _remove(path: Path, why: str) -> None:
    """
    Remove a kept report (or a stray file), logging a failure, which the
    next fetch tries again.
    """
    _LOG.debug("Removing the usage report kept in %s: %s", path, why)
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError:
        _LOG.debug(
            "Could not remove the usage report kept in %s; the next fetch will"
            " try again",
            path,
            exc_info=True,
        )


def _touch(directory: Path) -> None:
    """
    Mark a kept report used now, so that pruning keeps it.
    """
    try:
        os.utime(directory)
    except OSError:
        _LOG.debug(
            "Could not mark the usage report kept in %s as used",
            directory,
            exc_info=True,
        )


def window_matches(
    report: Report, from_time: datetime, until_time: datetime, now: datetime
) -> bool:
    """
    Whether each end of the kept report's window is within
    USAGE_REPORT_REUSE_SECONDS of the window asked for, its end taken as
    now at the latest, as the Platform takes it; False for a kept window
    that cannot be read.
    """
    try:
        kept_from = _instant(report.from_time)
        kept_until = _instant(report.until_time)
    except ValueError:
        return False
    asked_until = min(until_time, now)
    return (
        abs((kept_from - from_time).total_seconds()) <= USAGE_REPORT_REUSE_SECONDS
        and abs((kept_until - asked_until).total_seconds())
        <= USAGE_REPORT_REUSE_SECONDS
    )


def _instant(iso: str) -> datetime:
    """
    A time from the report ('2026-11-12T07:46:44.428279Z'), as UTC.
    """
    when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


@dataclass
class Fetched:
    """
    What the Platform sent, and the namespaces asked for: None for every
    namespace; and those left out because the Application may not read
    usage in them.
    """

    content: bytes
    namespaces: list[str] | None
    refused: list[str] = field(default_factory=list)


def _fetch(
    ctx: RunContext,
    from_time: datetime,
    until_time: datetime,
    namespace: str | None,
) -> Fetched:
    """
    The report's zip, as the Platform sends it: for the namespace given,
    else scoped as a search is (entity_utils.search_namespaces()), every
    namespace for an Application that can read them all and those it can
    read for one that cannot, since the Platform refuses an unscoped report
    to an Application without usage permission everywhere. A namespace the
    Application can read but not read usage in is named by the Platform's
    refusal, and dropped, the rest asked for again; one that can read every
    namespace but not usage in all of them asks for them by name in the same
    way. A refusal with nothing left to ask for, or of a namespace given,
    is raised.
    """
    from yellowdog_cli.utils import entity_utils
    from yellowdog_cli.utils.task_batches import raise_for_response

    if namespace:
        response = _request(ctx, from_time, until_time, [namespace])
        if response.status_code != 200:
            raise_for_response(response)
        return Fetched(response.content, [namespace])

    namespaces = entity_utils.search_namespaces(ctx.client, None)
    response = _request(ctx, from_time, until_time, namespaces)
    if (
        response.status_code == 403
        and namespaces is None
        and entity_utils.get_application_details(ctx.client).allNamespacesReadable
    ):
        namespaces = _all_namespaces(ctx)
        _LOG.debug(
            "Usage is not readable in every namespace: asking for the %d"
            " namespaces by name",
            len(namespaces),
        )
        response = _request(ctx, from_time, until_time, namespaces)
    refused: list[str] = []
    if response.status_code == 403 and namespaces:
        refused = sorted(set(_refused_namespaces(response.text)) & set(namespaces))
        remaining = [n for n in namespaces if n not in refused]
        if refused and remaining:
            _LOG.debug(
                "Usage is not readable in %s: asking for %s alone", refused, remaining
            )
            namespaces = remaining
            response = _request(ctx, from_time, until_time, namespaces)
    if response.status_code != 200:
        raise_for_response(response)
    return Fetched(response.content, namespaces, refused)


def _request(
    ctx: RunContext,
    from_time: datetime,
    until_time: datetime,
    namespaces: list[str] | None,
) -> requests.Response:
    body: dict = {"fromTime": _iso(from_time), "untilTime": _iso(until_time)}
    if namespaces is not None:
        body["namespaces"] = namespaces
    _LOG.debug(
        "Fetching the usage report from %s until %s, %s",
        body["fromTime"],
        body["untilTime"],
        f"in {namespaces}" if namespaces is not None else "in every namespace",
    )
    return requests.put(
        url=f"{ctx.config.url}/{REPORT_PATH}",
        headers={"Authorization": f"yd-key {ctx.config.key}:{ctx.config.secret}"},
        json=body,
        timeout=ctx.config.request_timeout,
    )


# The namespaces a refusal names: 'Missing required permissions:
# COMPUTE_USAGE_READ (namespaces: [ray-test, yd-demo], namespaceIds: [])'
_REFUSED_NAMESPACES = re.compile(r"\(namespaces: \[([^\]]*)\]")


def _refused_namespaces(text: str) -> list[str]:
    match = _REFUSED_NAMESPACES.search(text)
    if match is None:
        return []
    return [name.strip() for name in match.group(1).split(",") if name.strip()]


def namespace_exists(ctx: RunContext, namespace: str) -> bool:
    """
    Whether the namespace exists, searched for by name; True when the search
    cannot say (a missing permission, say), so that only a namespace known
    not to exist is reported as missing.
    """
    from yellowdog_client.model import NamespaceSearch

    from yellowdog_cli.utils.exit_codes import SESSION_FAILURES, classify

    try:
        found = ctx.client.namespaces_client.get_namespaces(
            NamespaceSearch(namespaceContains=namespace)
        ).list_all()
    except Exception as error:
        if classify(error) in SESSION_FAILURES:
            raise
        _LOG.debug(
            "Cannot tell whether namespace '%s' exists", namespace, exc_info=True
        )
        return True
    return any(n.namespace == namespace for n in found)


def _all_namespaces(ctx: RunContext) -> list[str]:
    from yellowdog_client.model import NamespaceSearch

    found = ctx.client.namespaces_client.get_namespaces(NamespaceSearch()).list_all()
    return sorted(n.namespace for n in found if n.namespace)


def _iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _keep(root: Path, directory: Path, fetched: Fetched) -> None:
    """
    The zip as the Platform sent it, once it is known to hold the three CSV
    files, kept in 'directory' with when it was fetched and its size,
    replacing what was there, through a partial directory renamed into
    place so that a reader never finds half a report.
    """
    try:
        names = zipfile.ZipFile(io.BytesIO(fetched.content)).namelist()
    except zipfile.BadZipFile as error:
        raise UsageReportError(
            "The Platform's usage report is not a zip file"
        ) from error
    missing = [prefix for prefix in _REPORT_FILES if _member(names, prefix) is None]
    if missing:
        raise UsageReportError(
            "The Platform's usage report has no "
            + ", ".join(f"{prefix} file" for prefix in missing)
        )
    partial = root / f"{directory.name}.part-{os.getpid()}"
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(mode=0o700)
    try:
        (partial / REPORT_ZIP).write_bytes(fetched.content)
        (partial / FETCHED_JSON).write_text(
            json.dumps(
                {
                    "fetched": time.time(),
                    "bytes": len(fetched.content),
                    "namespaces": fetched.namespaces,
                    "refused": fetched.refused,
                }
            ),
            encoding="utf-8",
        )
        shutil.rmtree(directory, ignore_errors=True)
        partial.rename(directory)
    finally:
        shutil.rmtree(partial, ignore_errors=True)


def _read_kept(directory: Path) -> Report | None:
    """
    The report kept in 'directory', or None if there is none whole.
    """
    try:
        fetched = json.loads((directory / FETCHED_JSON).read_text(encoding="utf-8"))
        with zipfile.ZipFile(directory / REPORT_ZIP) as archive:
            if any(_member(archive.namelist(), p) is None for p in _REPORT_FILES):
                return None
            summary = dict(row[:2] for row in _rows(archive, SUMMARY) if len(row) >= 2)
    except (OSError, ValueError, zipfile.BadZipFile):
        return None
    return Report(
        directory=directory,
        from_time=summary.get("From Time", ""),
        until_time=summary.get("Until Time", ""),
        fetched=datetime.fromtimestamp(fetched["fetched"], tz=timezone.utc),
        from_cache=True,
        fetched_bytes=_bytes(fetched.get("bytes")),
        namespaces=_names(fetched.get("namespaces")),
        refused=_names(fetched.get("refused")) or [],
    )


def _names(value: object) -> list[str] | None:
    if isinstance(value, list) and all(isinstance(name, str) for name in value):
        return value
    return None


def _bytes(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _member(names: list[str], prefix: str) -> str | None:
    """
    The zip member that is the report's CSV file of that kind, or None.
    """
    return next(
        (name for name in names if Path(name).name.startswith(f"{prefix}_")), None
    )


def _text(archive: zipfile.ZipFile, prefix: str) -> io.TextIOWrapper:
    name = _member(archive.namelist(), prefix)
    if name is None:
        raise UsageReportError(f"The usage report has no {prefix} file")
    return io.TextIOWrapper(archive.open(name), encoding="utf-8", newline="")


def _rows(archive: zipfile.ZipFile, prefix: str) -> list[list[str]]:
    with _text(archive, prefix) as file:
        return list(csv.reader(file))


def _records(archive: zipfile.ZipFile, prefix: str) -> list[dict[str, str]]:
    with _text(archive, prefix) as file:
        return list(csv.DictReader(file))


def grouped_usage(
    report: Report, by: list[str], where: dict[str, list[str]] | None = None
) -> list[UsageGroup]:
    """
    The report's Instances totalled by the keys in 'by', most total time
    first; only those matching 'where' (filter_of()) when it is given.
    """
    with zipfile.ZipFile(report.path) as archive:
        requirements = {
            row["Compute Requirement ID"]: row
            for row in _records(archive, REQUIREMENTS)
        }
        instances = _records(archive, INSTANCES)
    groups: dict[tuple[str, ...], UsageGroup] = {}
    for instance in instances:
        requirement = requirements.get(instance["Compute Requirement ID"], {})
        if where and not _matches(where, instance, requirement):
            continue
        values = {key: _value(key, instance, requirement) for key in by}
        group = groups.setdefault(tuple(values.values()), UsageGroup(keys=values))
        group.instances += 1
        for status, column in STATUS_COLUMNS.items():
            group.seconds[status] += _seconds(instance.get(column))
    return sorted(
        groups.values(),
        key=lambda group: (-group.total_seconds, tuple(group.keys.values())),
    )


def filter_of(where: list[tuple[str, str]] | None) -> dict[str, list[str]]:
    """
    The '--where' entries as each key's patterns, in the order given.
    """
    patterns: dict[str, list[str]] = {}
    for key, pattern in where or ():
        patterns.setdefault(key, []).append(pattern)
    return patterns


def _matches(
    where: dict[str, list[str]], instance: dict[str, str], requirement: dict
) -> bool:
    """
    Whether the Instance's value for every key matches one of its patterns,
    as globs in any case ('provider=aws' matching 'AWS').
    """
    return all(
        any(
            fnmatch.fnmatchcase(
                _value(key, instance, requirement).casefold(), pattern.casefold()
            )
            for pattern in patterns
        )
        for key, patterns in where.items()
    )


def _value(key: str, instance: dict[str, str], requirement: dict) -> str:
    match key:
        case "namespace":
            return requirement.get("Namespace") or "-"
        case "tag":
            return requirement.get("Tag") or "-"
        case "requirement":
            return requirement.get("Name") or instance["Compute Requirement ID"]
        case "provider":
            return instance.get("Provider") or "-"
        case "region":
            return instance.get("Region") or "-"
        case "instance-type":
            return instance.get("Instance Type") or "-"
        case "source":
            return instance.get("Source Name") or "-"
        case "spot":
            return "spot" if instance.get("Spot") == "true" else "on-demand"
    raise ValueError(f"Unknown usage grouping '{key}'")


def _seconds(text: str | None) -> float:
    try:
        return float(text) if text else 0.0
    except ValueError:
        return 0.0


def size_text(size: int) -> str:
    """
    A size in bytes in powers of 1000, as Finder and Windows Explorer give
    it (and Commander's file previews), one decimal place above a kilobyte.
    """
    if size < 1000:
        return f"{size} byte{'' if size == 1 else 's'}"
    scaled = float(size)
    for unit in ("kB", "MB"):
        scaled /= 1000
        if scaled < 1000:
            return f"{scaled:,.1f} {unit}"
    return f"{scaled / 1000:,.1f} GB"


# The environment variables naming the temporary directory, as a shell
# writes each: POSIX's, then Windows'
_TEMP_VARIABLES = (("TMPDIR", "$TMPDIR"), ("TEMP", "%TEMP%"), ("TMP", "%TMP%"))


def shown_path(path: Path) -> str:
    """
    A kept report's path as the summary shows it: the temporary directory
    written as the environment variable naming it ('$TMPDIR/...',
    '%TEMP%\\...'), which a shell expands, where one does; else in full.
    """
    text = str(path)
    for variable, written in _TEMP_VARIABLES:
        value = os.environ.get(variable)
        if not value:
            continue
        base = os.path.normpath(value)
        # Case aside, as Windows compares paths (normcase does nothing on POSIX)
        if os.path.normcase(text).startswith(os.path.normcase(base + os.sep)):
            return written + text[len(base) :]
    return text
