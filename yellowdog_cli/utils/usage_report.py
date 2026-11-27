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
directory named by a digest of its scope (the URL, the key ID and the
namespace filter: report_scope()) and the window it was fetched for. A
kept report of the same scope is used, unless refreshed, while each end of
its window is within USAGE_REPORT_REUSE_SECONDS of the window asked for,
whose end is taken as now at the latest, since the Platform's report ends
there; however the window was written, so a window given as '24h' to
'now' is found again by the dates its summary shows. A window of fixed
past dates is used until it is removed, being one that no longer changes,
and one ending now for ten minutes after it was fetched; of several that
match, the one fetched last. A namespace asked for with none kept of its
own is read from a kept report of every namespace for the window, which
asked for it and was not refused it, its rows held to that namespace as
they are read (Report.only_namespace): the Platform's namespace filter is
the Compute Requirement's Namespace, so the rows are the ones a report of
that namespace holds. The window, the time it was fetched and the
report's size are said with every summary. Each fetch removes the reports unused (neither fetched nor read)
for USAGE_REPORTS_UNUSED_SECONDS, a week, and then the least recently used
beyond USAGE_REPORTS_KEPT, so the directory stays bounded on any platform
(Windows clears its temporary directory only if told to); a report's
directory is touched when it is read, its modification time being when it
was last used. The directory is under the system's temporary directory,
per user and mode 0700 on POSIX (completion_cache.cache_directory()).

An Instance's namespace, tag and Compute Requirement name come from its
Compute Requirement's row.

The first read of a report sums its Instances alike in every column a
grouping, a filter or a price reads (SUMMED_COLUMNS: every one but the
Instance's ID) into one row each, with their count and seconds, and keeps
them beside the zip (SUMMED_CSV), so that a report of a million Instances,
a few tens of thousands of such rows, is read again in a moment: only a
grouping or filter by Instance ID reads the Instances one by one, streamed
from the zip, never held. A run reads the zip once (Report's contents,
kept on it), however many passes it makes over the rows.
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
import sys
import time
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from operator import itemgetter
from pathlib import Path
from typing import TYPE_CHECKING

import requests

from yellowdog_cli.utils import direct_http
from yellowdog_cli.utils.atomic_write import write_text_atomically
from yellowdog_cli.utils.completion_cache import cache_directory, cache_key
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.limits import (
    RAW_CONNECT_TIMEOUT,
    USAGE_PROGRESS_LINE_SECONDS,
    USAGE_REPORT_CHUNK_BYTES,
    USAGE_REPORT_READ_TIMEOUT,
    USAGE_REPORT_REUSE_SECONDS,
    USAGE_REPORTS_KEPT,
    USAGE_REPORTS_UNUSED_SECONDS,
)
from yellowdog_cli.utils.printing import print_info
from yellowdog_cli.utils.settings import USAGE_PROGRESS_LINES, USAGE_PROGRESS_PREFIX
from yellowdog_cli.utils.usage_text import report_time, size_text

if TYPE_CHECKING:
    from yellowdog_cli.utils.usage_cost import Costing

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

# Instances alike in these columns, every one a grouping, a filter or a
# price reads but the Instance's ID, are summed into one row of SUMMED_CSV,
# kept beside the zip; its name changes with its form, so that a copy of
# another form is never read
SUMMED_CSV = "summed-v1.csv"
CR_ID = "Compute Requirement ID"
INSTANCE_ID = "Instance ID"
SUMMED_COLUMNS = (CR_ID, "Provider", "Region", "Instance Type", "Source Name", "Spot")
SUMMED_COUNT = "Instances"
# The keys whose values are the Instance's own, read from the zip one by one
INSTANCE_LEVEL_KEYS = frozenset({"instance-id"})

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
    "cr",
    "cr-id",
    "creator",
    "creator-id",
    "provider",
    "region",
    "instance-type",
    "source",
    "pricing",
    "instance-id",
)


# The Compute Requirement CSV's column naming who provisioned it: an
# Application's ID or a user's
CREATED_BY = "Created by ID"

# A creator's kind, by the second field of its ID ('ydid:app:...')
_CREATOR_KINDS = {"app": "Application", "user": "User"}

# A creator its ID alone shows: one the listings did not name
_UNRESOLVED = "(?)"


@dataclass
class CreatorNames:
    """
    The names of the creators the listings could read, by ID, and the kinds
    ('Applications', 'Users') that could not be listed.
    """

    names: dict[str, str] = field(default_factory=dict)
    unreadable: list[str] = field(default_factory=list)

    def shown(self, creator_id: str) -> str:
        """
        A creator as the report shows it: 'render-farm (Application)', or
        its ID marked '(?)' where it has no name, so that two unnamed
        creators are never shown alike.
        """
        name = self.names.get(creator_id)
        fields = creator_id.split(":")
        kind = _CREATOR_KINDS.get(fields[1]) if len(fields) > 1 else None
        if name is None or kind is None:
            return f"{creator_id} {_UNRESOLVED}"
        return f"{name} ({kind})"


def creator_names(ctx: RunContext) -> CreatorNames:
    """
    The names of the account's Applications and Users, by ID, read with one
    listing of each. A listing the Application is not permitted (403) leaves
    that kind unnamed, noted in 'unreadable', since its creators can still be
    shown by ID; any other failure is raised.
    """
    from yellowdog_cli.utils import entity_utils
    from yellowdog_cli.utils.exit_codes import ExitCode, classify

    creators = CreatorNames()
    listings = (
        ("Applications", entity_utils.get_all_applications),
        ("Users", entity_utils.get_all_users),
    )
    for kind, listing in listings:
        try:
            found = listing(ctx.client)
        except Exception as e:
            if classify(e) != ExitCode.PERMISSION:
                raise
            _LOG.debug("not permitted to list %s", kind, exc_info=True)
            creators.unreadable.append(kind)
            continue
        for item in found:
            name = item.name or getattr(item, "username", None)
            if name and item.id:
                creators.names[item.id] = name
        _LOG.debug("read the names of %d %s", len(found), kind)
    return creators


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
    # A kept report of every namespace read for this one namespace alone
    # (None: the report as the Platform sent it, for its own scope)
    only_namespace: str | None = None
    # The account's name, looked up as it was fetched (None if it could not
    # be, or for a report kept without it)
    account_name: str | None = None
    # What the run has read of it (_contents()), kept so that it is read
    # once; never copied by dataclasses.replace()
    _read: _Contents | None = field(default=None, init=False, repr=False, compare=False)

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
    # The creator's ID where grouped by creator (None for none)
    creator_id: str | None = None
    seconds: dict[str, float] = field(
        default_factory=lambda: dict.fromkeys(STATUS_COLUMNS, 0.0)
    )
    # With '--cost' (usage_cost.Costing): the estimated cost of the running
    # time priced, and the running seconds priced and not
    cost: float = 0.0
    priced_seconds: float = 0.0
    unpriced_seconds: float = 0.0

    @property
    def total_seconds(self) -> float:
        return sum(self.seconds.values())


def report_scope(ctx: RunContext, namespace: str | None) -> str:
    """
    The digest of what a report depends on besides its window: the URL,
    the key ID and the namespace filter. Kept with the report, so that one
    of another account or namespace is never used.
    """
    return cache_key(
        "usage-report", ctx.config.url, ctx.config.key or "", namespace or ""
    )


def report_account(ctx: RunContext) -> str:
    """
    The digest of the account and Application a report was fetched with
    (the URL and the key ID), any namespace: what yd usage --reports lists by.
    """
    return cache_key("usage-account", ctx.config.url, ctx.config.key or "")


def report_key(scope: str, from_time: datetime, until_time: datetime) -> str:
    """
    The digest naming a report's directory: its scope and the window it was
    fetched for, in 16 hex digits, enough to tell a user's reports apart
    and short enough to read.
    """
    return cache_key(scope, _iso(from_time), _iso(until_time))[:16]


def usage_report(
    ctx: RunContext,
    from_time: datetime,
    until_time: datetime,
    namespace: str | None,
    refresh: bool,
    now: datetime | None = None,
) -> Report:
    """
    The report for the window: a kept one of the same scope whose window
    matches it (window_matches()) unless refreshed, else for a namespace one
    of every namespace that covers it (kept_namespace_report()), else
    fetched from the Platform and kept. Without a usable cache directory, it
    is kept in a fresh temporary one.
    """
    now = now or datetime.now(timezone.utc)
    root = cache_directory(USAGE_CACHE_DIRECTORY_NAME)
    scope = report_scope(ctx, namespace)
    key = report_key(scope, from_time, min(until_time, now))
    if root is not None:
        if not refresh:
            cached = kept_report(root, scope, from_time, until_time, now)
            if cached is None and namespace:
                cached = kept_namespace_report(
                    root, report_scope(ctx, None), namespace, from_time, until_time, now
                )
            if cached is not None:
                _LOG.debug("Using the usage report kept in %s", cached.directory)
                _touch(cached.directory)
                return cached
    else:
        import tempfile

        root = Path(tempfile.mkdtemp(prefix=f"{USAGE_CACHE_DIRECTORY_NAME}-"))
    directory = root / key
    print_info("Fetching the usage report from the Platform")
    fetched = _fetch(ctx, from_time, until_time, namespace)
    fetched.scope = scope
    fetched.account = report_account(ctx)
    fetched.namespace = namespace
    fetched.account_name = account_name(ctx)
    _keep(root, directory, fetched)
    prune(root, keep=directory)
    report = _read_kept(directory)
    if report is None:
        raise UsageReportError(
            f"The usage report kept in '{directory}' could not be read"
        )
    report.from_cache = False
    return report


def kept_report(
    root: Path, scope: str, from_time: datetime, until_time: datetime, now: datetime
) -> Report | None:
    """
    The kept report of this scope whose window matches the one asked for,
    the last fetched of several; None for none. A report kept without its
    scope is never used, and is pruned in time.
    """
    try:
        entries = [path for path in root.iterdir() if ".part-" not in path.name]
    except OSError:
        _LOG.debug("Cannot list the kept usage reports in %s", root, exc_info=True)
        return None
    matching: list[Report] = []
    for directory in entries:
        if _kept_scope(directory) != scope:
            continue
        report = _read_kept(directory)
        if report is None:
            continue
        if window_matches(report, from_time, until_time, now):
            matching.append(report)
        else:
            _LOG.debug(
                "Not using the usage report kept in %s: its window, %s to %s,"
                " is not the one asked for",
                directory,
                report.from_time,
                report.until_time,
            )
    return max(matching, key=lambda report: report.fetched, default=None)


def kept_namespace_report(
    root: Path,
    every_scope: str,
    namespace: str,
    from_time: datetime,
    until_time: datetime,
    now: datetime,
) -> Report | None:
    """
    The kept report of every namespace (every_scope: report_scope() with
    none) whose window matches, held to the one namespace given, as a
    report fetched for it alone would be; None unless it asked for that
    namespace (asking for every one, or naming it) and was not refused it,
    so that a namespace usage may not be read in is still asked for, and
    refused by the Platform.
    """
    report = kept_report(root, every_scope, from_time, until_time, now)
    if report is None:
        return None
    if namespace in report.refused or (
        report.namespaces is not None and namespace not in report.namespaces
    ):
        _LOG.debug(
            "Not reading namespace %s from the usage report kept in %s,"
            " which does not cover it",
            namespace,
            report.directory,
        )
        return None
    _LOG.debug(
        "Reading namespace %s from the usage report of every namespace kept in %s",
        namespace,
        report.directory,
    )
    report.only_namespace = namespace
    report.namespaces = [namespace]
    report.refused = []
    return report


@dataclass
class KeptReport:
    """
    A kept report as yd usage --reports lists it: the report, the namespace
    it was fetched for (None for every one) and when it was last used.
    """

    report: Report
    namespace: str | None
    last_used: datetime


def kept_reports(root: Path, account: str) -> list[KeptReport]:
    """
    The whole reports kept in 'root' for the account and Application,
    the last fetched first, read without marking any of them used. A report
    kept without its account (by an earlier version) is not listed, and is
    pruned in time.
    """
    try:
        entries = [path for path in root.iterdir() if ".part-" not in path.name]
    except OSError:
        _LOG.debug("Cannot list the kept usage reports in %s", root, exc_info=True)
        return []
    kept: list[KeptReport] = []
    for directory in entries:
        try:
            fetched = json.loads((directory / FETCHED_JSON).read_text(encoding="utf-8"))
            last_used = directory.stat().st_mtime
        except (OSError, ValueError):
            continue
        if not isinstance(fetched, dict) or fetched.get("account") != account:
            continue
        report = _read_kept(directory)
        if report is None:
            continue
        namespace = fetched.get("namespace")
        kept.append(
            KeptReport(
                report,
                namespace if isinstance(namespace, str) else None,
                datetime.fromtimestamp(last_used, tz=timezone.utc),
            )
        )
    return sorted(kept, key=lambda item: item.report.fetched, reverse=True)


def reports_kept(ctx: RunContext) -> list[KeptReport]:
    """
    yd usage --reports: the reports kept for the configuration's account
    and Application; none without a usable cache directory.
    """
    root = cache_directory(USAGE_CACHE_DIRECTORY_NAME)
    return [] if root is None else kept_reports(root, report_account(ctx))


def _kept_scope(directory: Path) -> str | None:
    """
    The scope a report was kept with, read without opening its zip; None
    for none.
    """
    try:
        fetched = json.loads((directory / FETCHED_JSON).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    scope = fetched.get("scope") if isinstance(fetched, dict) else None
    return scope if isinstance(scope, str) else None


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
    when = report_time(iso)
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
    # report_scope(), kept with the report
    scope: str = ""
    # report_account() and the namespace asked for (None for every one),
    # kept readable for yd usage --reports
    account: str = ""
    namespace: str | None = None
    # The account's name (account_name())
    account_name: str | None = None


def _fetch(
    ctx: RunContext,
    from_time: datetime,
    until_time: datetime,
    namespace: str | None,
) -> Fetched:
    """
    The report, fetched under a progress display (_FetchProgress) while
    the Platform builds it and while it arrives.
    """
    with _FetchProgress() as progress:
        return _fetch_shown(ctx, from_time, until_time, namespace, progress)


def _fetch_shown(
    ctx: RunContext,
    from_time: datetime,
    until_time: datetime,
    namespace: str | None,
    progress: _FetchProgress,
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

    wait = _report_timeout(ctx.config.read_timeout)[1]
    if namespace:
        response = _request(ctx, from_time, until_time, [namespace], progress)
        if response.status_code != 200:
            raise_for_response(response)
        return Fetched(_body(response, progress, wait), [namespace])

    namespaces = entity_utils.search_namespaces(ctx.client, None)
    response = _request(ctx, from_time, until_time, namespaces, progress)
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
        response = _request(ctx, from_time, until_time, namespaces, progress)
    refused: list[str] = []
    if response.status_code == 403 and namespaces:
        refused = sorted(set(_refused_namespaces(response.text)) & set(namespaces))
        remaining = [n for n in namespaces if n not in refused]
        if refused and remaining:
            _LOG.debug(
                "Usage is not readable in %s: asking for %s alone", refused, remaining
            )
            namespaces = remaining
            response = _request(ctx, from_time, until_time, namespaces, progress)
    if response.status_code != 200:
        raise_for_response(response)
    return Fetched(_body(response, progress, wait), namespaces, refused)


def _report_timeout(read_timeout: float | None) -> tuple[float, float | None]:
    """
    (connect, read) for the report request: requestTimeout, but at least
    USAGE_REPORT_READ_TIMEOUT, since the Platform builds the report before
    it answers; None (requestTimeout = 0) is no limit, as everywhere.
    """
    if read_timeout is None:
        return (RAW_CONNECT_TIMEOUT, None)
    return (RAW_CONNECT_TIMEOUT, max(read_timeout, USAGE_REPORT_READ_TIMEOUT))


def _waited(seconds: float) -> str:
    """
    A wait as a message gives it: '5 minutes', '90 seconds'.
    """
    if seconds % 60 == 0:
        minutes = int(seconds // 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    return f"{seconds:g} seconds"


def _progress_shown() -> bool:
    """
    Whether the fetch's progress is shown: on a terminal alone, and never
    under --json, --quiet or --no-format, which ask for output read as a
    whole.
    """
    from yellowdog_cli.utils import printing
    from yellowdog_cli.utils.output_settings import OUTPUT

    return bool(
        printing.CONSOLE_ERR.is_terminal
        and not (OUTPUT.json_output or OUTPUT.quiet or OUTPUT.no_format)
    )


class _FetchProgress:
    """
    One line on standard error, updated in place while the report is
    fetched: how long the Platform has taken to answer, then how much of
    the report has arrived and how fast; removed when the fetch ends, done
    or failed. Nothing at all where it is not shown (_progress_shown()).
    The wait and the size are logged under --debug either way. With
    USAGE_PROGRESS_LINES set to 1, plain lines for a program to read
    instead (_line()), whatever else is shown.
    """

    def __init__(self) -> None:
        self._progress = None
        self._task = None
        self._since = time.monotonic()
        self._received = 0
        self._lines = os.environ.get(USAGE_PROGRESS_LINES) == "1"
        self._last_line = 0.0

    def __enter__(self) -> _FetchProgress:
        if _progress_shown():
            from rich.progress import Progress, ProgressColumn, Task
            from rich.text import Text

            from yellowdog_cli.utils import printing

            class FetchColumn(ProgressColumn):
                """
                The wait, then the size received and its rate.
                """

                def render(self, task: Task) -> Text:
                    if not task.fields["downloading"]:
                        waited = int(time.monotonic() - task.fields["since"])
                        return Text(
                            "Waiting for the Platform to build the report\u2026"
                            f" {waited // 60}:{waited % 60:02}"
                        )
                    shown = (
                        f"Downloading the report\u2026 {size_text(int(task.completed))}"
                    )
                    if task.speed:
                        shown += f" ({size_text(int(task.speed))}/s)"
                    return Text(shown)

            self._progress = Progress(
                FetchColumn(), console=printing.CONSOLE_ERR, transient=True
            )
            self._progress.start()
            self._task = self._progress.add_task(
                "", total=None, downloading=False, since=self._since
            )
        return self

    def __exit__(self, *exc_info) -> None:
        if self._progress is not None:
            self._progress.stop()

    def waiting(self) -> None:
        """
        A request is sent: the wait for its answer starts.
        """
        self._since = time.monotonic()
        self._received = 0
        self._show(downloading=False, completed=0, since=self._since)
        self._line("waiting")

    def answered(self) -> None:
        _LOG.debug("The Platform answered after %.1fs", time.monotonic() - self._since)

    def received(self, count: int) -> None:
        """
        A chunk of the report arrived.
        """
        self._received += count
        self._show(downloading=True, completed=self._received)
        if time.monotonic() - self._last_line >= USAGE_PROGRESS_LINE_SECONDS:
            self._line(f"received {self._received}")

    def done(self) -> None:
        _LOG.debug("Received %s", size_text(self._received))
        self._line(f"received {self._received}")

    def _line(self, text: str) -> None:
        """
        A progress line for the program that asked for them, written to
        standard error as it is, flushed: a protocol, never a message for
        a reader, so not through printing.py, whose settings would change it.
        """
        if not self._lines:
            return
        self._last_line = time.monotonic()
        sys.stderr.write(f"{USAGE_PROGRESS_PREFIX} {text}\n")
        sys.stderr.flush()

    def _show(self, **fields) -> None:
        if self._progress is None or self._task is None:
            return
        completed = fields.pop("completed")
        self._progress.update(self._task, completed=completed, **fields)
        self._progress.refresh()


def _body(
    response: requests.Response, progress: _FetchProgress, wait: float | None
) -> bytes:
    """
    A report's body, read in chunks so that its arrival can be shown. A
    stall longer than the read timeout ('wait') is said as the request's
    own timeout is; requests raises it as a ConnectionError holding urllib3's
    ReadTimeoutError, kept as it is (its exit code) with a clearer message.
    """
    from urllib3.exceptions import ReadTimeoutError

    progress.answered()
    chunks = []
    try:
        for chunk in response.iter_content(chunk_size=USAGE_REPORT_CHUNK_BYTES):
            if chunk:
                chunks.append(chunk)
                progress.received(len(chunk))
    except requests.ConnectionError as e:
        if e.args and isinstance(e.args[0], ReadTimeoutError):
            raise type(e)(_timed_out(wait)) from e
        raise
    progress.done()
    return b"".join(chunks)


def _timed_out(wait: float | None) -> str:
    """
    What a report the Platform was too slow to send is reported as.
    """
    return (
        f"The Platform sent nothing of the usage report for {_waited(wait or 0)};"
        " a larger [common] requestTimeout (or --property"
        " common.requestTimeout=<seconds>) gives it longer"
    )


def _request(
    ctx: RunContext,
    from_time: datetime,
    until_time: datetime,
    namespaces: list[str] | None,
    progress: _FetchProgress,
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
    timeout = _report_timeout(ctx.config.read_timeout)
    progress.waiting()
    try:
        # Streamed, so that the report's body can be read in chunks
        return direct_http.put(
            url=f"{ctx.config.url}/{REPORT_PATH}",
            headers={"Authorization": f"yd-key {ctx.config.key}:{ctx.config.secret}"},
            json=body,
            timeout=timeout,
            stream=True,
        )
    except requests.ReadTimeout as e:
        # Its own message, of its own kind and keeping its exit code; a
        # connect timeout is no wait for the report, and keeps requests' own
        raise type(e)(_timed_out(timeout[1])) from e


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
                    "accountName": fetched.account_name,
                    "scope": fetched.scope,
                    "account": fetched.account,
                    "namespace": fetched.namespace,
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
        account_name=_non_empty_text(fetched.get("accountName")),
    )


def _non_empty_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def account_name(ctx: RunContext) -> str | None:
    """
    The name of the account the Application is in, for the report to say
    whose it is: None if it cannot be read, which leaves the report as it
    is. An authentication or connection failure is raised, as any other
    request's would be.
    """
    from yellowdog_cli.utils import entity_utils
    from yellowdog_cli.utils.exit_codes import SESSION_FAILURES, classify

    try:
        name = entity_utils.get_application_details(ctx.client).accountName
    except Exception as error:
        if classify(error) in SESSION_FAILURES:
            raise
        _LOG.debug("Cannot read the account's name", exc_info=True)
        return None
    return _non_empty_text(name)


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
    report: Report,
    by: list[str],
    where: dict[str, list[str]] | None = None,
    creators: CreatorNames | None = None,
    costing: Costing | None = None,
) -> list[UsageGroup]:
    """
    The report's Instances totalled by the keys in 'by', most total time
    first; only those matching 'where' (filter_of()) when it is given. A
    creator is named from 'creators' (creator_names()), and grouped by its
    ID, so that two creators sharing a name are never one group. With a
    'costing' (usage_cost.Costing), each Instance's running time is priced
    into its group.
    """
    creators = creators or CreatorNames()
    groups: dict[tuple[str, ...], UsageGroup] = {}
    instance_level = bool(INSTANCE_LEVEL_KEYS & {*by, *(where or ())})
    for row, requirement in _counted(report, where, creators, instance_level):
        creator_id = requirement.get(CREATED_BY) or None
        values = {key: _value(key, row.values, requirement, creators) for key in by}
        identity = tuple(
            (creator_id or "") if key == "creator" else value
            for key, value in values.items()
        )
        group = groups.get(identity)
        if group is None:
            group = groups[identity] = UsageGroup(
                keys=values, creator_id=creator_id if "creator" in by else None
            )
        group.instances += row.count
        for status, seconds in row.seconds.items():
            group.seconds[status] += seconds
        if costing is not None:
            costing.add(group, row.values, row.seconds["running"])
    return sorted(
        groups.values(),
        key=lambda group: (-group.total_seconds, tuple(group.keys.values())),
    )


def counted_places(
    report: Report,
    where: dict[str, list[str]] | None = None,
    creators: CreatorNames | None = None,
) -> set[tuple[str, str]]:
    """
    The (provider, region) of every Instance 'where' counts that ran and
    names its region: the places whose prices '--cost' needs, since one with
    no running time costs nothing and one with no region cannot be priced.
    """
    instance_level = bool(INSTANCE_LEVEL_KEYS & set(where or ()))
    return {
        (row.values.get("Provider") or "", row.values["Region"])
        for row, _ in _counted(
            report, where, creators or CreatorNames(), instance_level
        )
        if row.values.get("Region") and row.seconds["running"] > 0
    }


@dataclass
class _Instances:
    """
    Instances alike in SUMMED_COLUMNS (one Instance, its ID among its
    values, where read one by one): their values, how many, and their
    seconds in each status, summed.
    """

    values: dict[str, str]
    count: int
    seconds: dict[str, float]


@dataclass
class _Contents:
    """
    What a run reads of a report, once: each Compute Requirement's row by
    its ID, and the Instances summed.
    """

    requirements: dict[str, dict[str, str]]
    summed: list[_Instances]


def _counted(
    report: Report,
    where: dict[str, list[str]] | None,
    creators: CreatorNames,
    instance_level: bool = False,
) -> Iterator[tuple[_Instances, dict]]:
    """
    Each row of Instances the report holds that 'where' matches, with its
    Compute Requirement's row ({} where the report does not list it): the
    summed rows, or with 'instance_level' each Instance, read from the zip.
    """
    contents = _contents(report)
    rows = _each_instance(report) if instance_level else contents.summed
    for row in rows:
        requirement = contents.requirements.get(row.values[CR_ID], {})
        if (
            report.only_namespace is not None
            and requirement.get("Namespace") != report.only_namespace
        ):
            continue
        if where and not _matches(where, row.values, requirement, creators):
            continue
        yield row, requirement


def _contents(report: Report) -> _Contents:
    """
    The report's contents, read on first use and kept on it: one opening of
    the zip for its Compute Requirements, and for its Instances where no
    summed copy is kept beside it, which this keeps.
    """
    if report._read is not None:
        return report._read
    summed_path = report.directory / SUMMED_CSV
    summed = _read_summed(summed_path)
    with zipfile.ZipFile(report.path) as archive:
        requirements = {row[CR_ID]: row for row in _records(archive, REQUIREMENTS)}
        if summed is None:
            summed = _summed(_instances(archive))
            _keep_summed(summed_path, summed)
    report._read = _Contents(requirements, summed)
    return report._read


def _each_instance(report: Report) -> Iterator[_Instances]:
    """
    Each Instance in the report, one at a time.
    """
    with zipfile.ZipFile(report.path) as archive:
        yield from _instances(archive, (*SUMMED_COLUMNS, INSTANCE_ID))


def _instances(
    archive: zipfile.ZipFile, columns: tuple[str, ...] = SUMMED_COLUMNS
) -> Iterator[_Instances]:
    """
    Each Instance row of the zip, streamed: its values in 'columns' ('' for
    a column or a cell missing) and its seconds. Read by position rather
    than as a dict per row, the cost of reading a million rows.
    """
    with _text(archive, INSTANCES) as file:
        reader = csv.reader(file)
        heading = next(reader, [])
        place = {name: index for index, name in enumerate(heading)}
        # A column the file lacks is read from past the heading's end, where
        # every row is padded with ''
        absent = len(heading)
        value_places = [place.get(name, absent) for name in columns]
        status_places = [
            place.get(column, absent) for column in STATUS_COLUMNS.values()
        ]
        width = max(value_places + status_places) + 1
        values_of = itemgetter(*value_places)
        seconds_of = itemgetter(*status_places)
        statuses = list(STATUS_COLUMNS)
        for row in reader:
            if len(row) < width:
                row += [""] * (width - len(row))
            yield _Instances(
                dict(zip(columns, values_of(row))),
                1,
                dict(zip(statuses, map(_seconds, seconds_of(row)))),
            )


def _summed(instances: Iterator[_Instances]) -> list[_Instances]:
    """
    The Instances summed by their values.
    """
    rows: dict[tuple[str, ...], _Instances] = {}
    for instance in instances:
        identity = tuple(instance.values.values())
        row = rows.get(identity)
        if row is None:
            rows[identity] = instance
            continue
        row.count += instance.count
        for status, seconds in instance.seconds.items():
            row.seconds[status] += seconds
    return list(rows.values())


def _summed_heading() -> list[str]:
    return [*SUMMED_COLUMNS, SUMMED_COUNT, *STATUS_COLUMNS.values()]


def _keep_summed(path: Path, summed: list[_Instances]) -> None:
    """
    The summed rows kept beside the zip; one that cannot be written is
    summed again by the next run, so is no failure.
    """
    text = io.StringIO()
    writer = csv.writer(text, lineterminator="\n")
    writer.writerow(_summed_heading())
    for row in summed:
        writer.writerow(
            [
                *row.values.values(),
                row.count,
                *(repr(row.seconds[status]) for status in STATUS_COLUMNS),
            ]
        )
    try:
        write_text_atomically(str(path), text.getvalue())
    except OSError:
        _LOG.debug("could not keep the summed Instances at %s", path, exc_info=True)
        return
    _LOG.debug("kept %d summed rows at %s", len(summed), path)


def _read_summed(path: Path) -> list[_Instances] | None:
    """
    The summed rows kept at 'path', or None where there are none whole, to
    be summed again from the zip.
    """
    try:
        with open(path, encoding="utf-8", newline="") as file:
            reader = csv.reader(file)
            if next(reader, None) != _summed_heading():
                return None
            values = len(SUMMED_COLUMNS)
            return [
                _Instances(
                    dict(zip(SUMMED_COLUMNS, row[:values])),
                    int(row[values]),
                    {
                        status: float(row[values + 1 + index])
                        for index, status in enumerate(STATUS_COLUMNS)
                    },
                )
                for row in reader
            ]
    except FileNotFoundError:
        return None
    except (OSError, ValueError, IndexError):
        _LOG.debug("summing again: could not read %s", path, exc_info=True)
        return None


def filter_of(where: list[tuple[str, str]] | None) -> dict[str, list[str]]:
    """
    The '--where' entries as each key's patterns, in the order given.
    """
    patterns: dict[str, list[str]] = {}
    for key, pattern in where or ():
        patterns.setdefault(key, []).append(pattern)
    return patterns


def _matches(
    where: dict[str, list[str]],
    instance: dict[str, str],
    requirement: dict,
    creators: CreatorNames,
) -> bool:
    """
    Whether the Instance's value for every key matches one of its patterns,
    as globs in any case ('provider=aws' matching 'AWS'), or exactly, with
    its case, where the pattern begins '=' ('cr==Render' matching 'Render'
    alone); a creator's pattern matches its name or its ID.
    """
    return all(
        any(
            (value == pattern[1:])
            if pattern.startswith("=")
            else fnmatch.fnmatchcase(value.casefold(), pattern.casefold())
            for pattern in patterns
            for value in _matched(key, instance, requirement, creators)
        )
        for key, patterns in where.items()
    )


def _matched(
    key: str, instance: dict[str, str], requirement: dict, creators: CreatorNames
) -> list[str]:
    """
    The values a key's '--where' patterns are matched against: the value
    shown, and for a creator its name (where it has one) and its ID too, so
    that a creator can be given as the table shows it or by either.
    """
    if key != "creator":
        return [_value(key, instance, requirement, creators)]
    creator_id = requirement.get(CREATED_BY)
    if not creator_id:
        return ["-"]
    name = creators.names.get(creator_id)
    values = [creators.shown(creator_id), creator_id]
    return values if name is None else [*values, name]


def _value(
    key: str, instance: dict[str, str], requirement: dict, creators: CreatorNames
) -> str:
    match key:
        case "namespace":
            return requirement.get("Namespace") or "-"
        case "tag":
            return requirement.get("Tag") or "-"
        case "cr":
            return requirement.get("Name") or instance["Compute Requirement ID"]
        case "cr-id":
            return instance["Compute Requirement ID"]
        case "creator":
            creator_id = requirement.get(CREATED_BY)
            return creators.shown(creator_id) if creator_id else "-"
        case "creator-id":
            return requirement.get(CREATED_BY) or "-"
        case "provider":
            return instance.get("Provider") or "-"
        case "region":
            return instance.get("Region") or "-"
        case "instance-type":
            return instance.get("Instance Type") or "-"
        case "source":
            return instance.get("Source Name") or "-"
        case "pricing":
            return "spot" if instance.get("Spot") == "true" else "on-demand"
        case "instance-id":
            return instance.get("Instance ID") or "-"
    raise ValueError(f"Unknown usage grouping '{key}'")


def _seconds(text: str | None) -> float:
    try:
        return float(text) if text else 0.0
    except ValueError:
        return 0.0


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
