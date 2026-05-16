"""
Utility function to follow event streams.
"""

import signal
from collections.abc import Callable
from json import loads as json_loads
from threading import Thread
from time import monotonic, sleep, time

import requests
from rich.progress import (
    BarColumn,
    Progress,
    ProgressColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.text import Text
from yellowdog_client.model import TaskStatus

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.entity_utils import (
    get_compute_requirement_id_by_worker_pool_id,
)
from yellowdog_cli.utils.printing import (
    CONSOLE,
    print_error,
    print_event,
    print_info,
    print_warning,
)
from yellowdog_cli.utils.settings import EVENT_STREAM_RETRY_INTERVAL
from yellowdog_cli.utils.wrapper import CLIENT, CONFIG_COMMON
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type


class _WRNameColumn(ProgressColumn):
    """
    Renders the Work Requirement name (stored in task.fields["wr_name"]) in
    brackets with dim styling, for display after the progress bar.
    """

    def render(self, task) -> Text:
        name = task.fields.get("wr_name", "")
        return Text(f"[{name}]" if name else "", style="dim")


def _progress_desc(
    wr_status: str,
    total: int,
    completed: int,
    failed: int,
    aborted: int,
    cancelled: int,
) -> str:
    """
    Build the progress-bar description string.

    Shows WR status and done/total counts, then a breakdown of each terminal
    state (omitting any that are zero).
    """
    done = completed + failed + aborted + cancelled
    desc = f"{wr_status}  {done:,}/{total:,}"
    parts = []
    if completed:
        parts.append(f"{completed:,} completed")
    if failed:
        parts.append(f"{failed:,} failed")
    if aborted:
        parts.append(f"{aborted:,} aborted")
    if cancelled:
        parts.append(f"{cancelled:,} cancelled")
    if parts:
        desc += "  " + " · ".join(parts)
    return desc


def follow_work_requirement_with_progress(ydid: str) -> None:
    """
    Follow a Work Requirement event stream, displaying a live Rich progress bar.

    Safe to call from either the main thread or a daemon thread; signal
    handling is skipped automatically when not in the main thread.
    """
    total_tasks = completed_tasks = failed_tasks = aborted_tasks = cancelled_tasks = 0

    wr = None
    wr_name = ""
    wr_age_seconds = 0.0
    wr_is_terminal = False
    try:
        wr = CLIENT.work_client.get_work_requirement_by_id(ydid)
        wr_name = wr.name or ""
        wr_is_terminal = wr.status is not None and wr.status.finished
        if (
            wr_is_terminal
            and wr.createdTime is not None
            and wr.statusChangedTime is not None
        ):
            # Show how long the WR actually ran, not how long ago we fetched it
            wr_age_seconds = max(
                0.0,
                (wr.statusChangedTime - wr.createdTime).total_seconds(),
            )
        elif wr.createdTime is not None:
            wr_age_seconds = max(0.0, time() - wr.createdTime.timestamp())
    except Exception:
        pass

    progress = Progress(
        TextColumn("{task.description}"),
        BarColumn(
            complete_style="green4",
            finished_style="green4",
            pulse_style="deep_sky_blue4",
        ),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        _WRNameColumn(),
        console=CONSOLE,
        transient=False,
    )
    bar_task = progress.add_task("Starting\u2026", total=None, wr_name=wr_name)
    if wr_age_seconds > 0:
        progress.tasks[0].start_time = monotonic() - wr_age_seconds
    if wr_is_terminal:
        progress.stop_task(bar_task)

    # Pre-populate from the fetched WR so the bar shows a meaningful state
    # even if no events arrive (e.g. the WR is already in a terminal state).
    if wr is not None:
        try:
            for tg in wr.taskGroups or []:
                summary = tg.taskSummary
                if summary:
                    total_tasks += summary.taskCount or 0
                    counts = summary.statusCounts or {}
                    completed_tasks += counts.get(TaskStatus.COMPLETED, 0)
                    failed_tasks += counts.get(TaskStatus.FAILED, 0)
                    aborted_tasks += counts.get(TaskStatus.ABORTED, 0)
                    cancelled_tasks += counts.get(TaskStatus.CANCELLED, 0)
            wr_status = wr.status.value if wr.status else ""
            progress.update(
                bar_task,
                total=total_tasks if total_tasks > 0 else None,
                completed=completed_tasks,
                description=_progress_desc(
                    wr_status,
                    total_tasks,
                    completed_tasks,
                    failed_tasks,
                    aborted_tasks,
                    cancelled_tasks,
                ),
            )
        except Exception:
            pass

    def on_event(event: str, ydid_type: YDIDType) -> None:
        nonlocal \
            total_tasks, \
            completed_tasks, \
            failed_tasks, \
            aborted_tasks, \
            cancelled_tasks
        if not event.startswith("data:"):
            return
        try:
            event_data = json_loads(event[len("data:") :])
        except Exception:
            return
        if ydid_type is not YDIDType.WORK_REQUIREMENT:
            return

        new_total = new_completed = new_failed = new_aborted = new_cancelled = 0
        for tg in event_data.get("taskGroups", []):
            summary = tg.get("taskSummary", {})
            new_total += summary.get("taskCount", 0)
            counts = summary.get("statusCounts", {})
            new_completed += counts.get("COMPLETED", 0)
            new_failed += counts.get("FAILED", 0)
            new_aborted += counts.get("ABORTED", 0)
            new_cancelled += counts.get("CANCELLED", 0)

        total_tasks = new_total
        completed_tasks = new_completed
        failed_tasks = new_failed
        aborted_tasks = new_aborted
        cancelled_tasks = new_cancelled

        wr_status = event_data.get("status", "")
        progress.update(
            bar_task,
            total=total_tasks if total_tasks > 0 else None,
            completed=completed_tasks,
            description=_progress_desc(
                wr_status,
                total_tasks,
                completed_tasks,
                failed_tasks,
                aborted_tasks,
                cancelled_tasks,
            ),
        )

    def _restore_cursor() -> None:
        try:
            CONSOLE.file.write("\033[?25h")
            CONSOLE.file.flush()
        except Exception:
            pass

    _original_sigint = signal.getsignal(signal.SIGINT)

    def _on_sigint(sig: int, frame) -> None:
        _restore_cursor()
        signal.signal(signal.SIGINT, _original_sigint)
        signal.default_int_handler(sig, frame)

    try:
        signal.signal(signal.SIGINT, _on_sigint)
        in_main_thread = True
    except ValueError:
        in_main_thread = False  # Signal handlers only work in the main thread

    print_info(f"Tracking progress for Work Requirement '{ydid}'")
    try:
        with progress:
            follow_events(ydid, YDIDType.WORK_REQUIREMENT, on_event=on_event)
    finally:
        if in_main_thread:
            signal.signal(signal.SIGINT, _original_sigint)
        _restore_cursor()

    terminal_failures = failed_tasks + aborted_tasks + cancelled_tasks
    if terminal_failures:
        parts = []
        if failed_tasks:
            parts.append(f"{failed_tasks:,} failed")
        if aborted_tasks:
            parts.append(f"{aborted_tasks:,} aborted")
        if cancelled_tasks:
            parts.append(f"{cancelled_tasks:,} cancelled")
        print_warning(f"Work Requirement finished with {' · '.join(parts)} task(s)")


_FOLLOWABLE = frozenset(
    [YDIDType.WORK_REQUIREMENT, YDIDType.WORKER_POOL, YDIDType.COMPUTE_REQUIREMENT]
)


def follow_ids(ydids: list[str], auto_cr: bool = False) -> list[str]:
    """
    Creates an event thread for each YDID passed on the command line.

    Returns the deduplicated list of valid original IDs (WR/WP/CR only, before
    any auto-CR expansion) — callers that need to inspect final status after
    the streams conclude can use this list directly.
    """
    if not ydids:
        return []

    ydids_set = set(ydids)  # Eliminate duplicates
    num_duplicates = len(ydids) - len(ydids_set)
    if num_duplicates > 0:
        print_warning(f"Ignoring {num_duplicates} duplicate YellowDog ID(s)")

    # Capture valid original IDs before auto-CR expansion
    valid_original = [ydid for ydid in ydids_set if get_ydid_type(ydid) in _FOLLOWABLE]

    if auto_cr:
        # Automatically add Compute Requirement IDs for
        # Provisioned Worker Pools, to follow both
        cr_ydids = set()
        for ydid in ydids_set:
            if get_ydid_type(ydid) == YDIDType.WORKER_POOL:
                cr_ydid = get_compute_requirement_id_by_worker_pool_id(CLIENT, ydid)
                if cr_ydid is not None:
                    print_info(
                        f"Adding event stream for Compute Requirement '{cr_ydid}'"
                    )
                    cr_ydids.add(cr_ydid)
        ydids_set = ydids_set.union(cr_ydids)

    print_info(f"Following the event stream(s) for {len(ydids_set)} YellowDog ID(s)")

    threads: list[Thread] = []

    for ydid in ydids_set:
        ydid_type = get_ydid_type(ydid)
        if ydid_type not in _FOLLOWABLE:
            print_error(
                f"Invalid YellowDog ID '{ydid}' (Must be valid YDID for Work"
                " Requirement, Worker Pool or Compute Requirement)"
            )
            continue

        if ARGS_PARSER.progress and ydid_type == YDIDType.WORK_REQUIREMENT:
            target, args = follow_work_requirement_with_progress, (ydid,)
        else:
            target, args = follow_events, (ydid, ydid_type)
        thread = Thread(target=target, args=args, daemon=True)
        try:
            thread.start()
        except RuntimeError as e:
            print_error(f"Unable to start event thread for '{ydid}': ({e})")
            continue
        threads.append(thread)

    # Install a SIGINT handler in the main thread so that Ctrl-C restores the
    # terminal cursor even if Rich's Live context is running in a daemon thread
    # (signal handlers can only be installed from the main thread).
    _original_sigint = signal.getsignal(signal.SIGINT)
    if ARGS_PARSER.progress and threads:

        def _on_sigint(sig, frame):
            try:
                CONSOLE.file.write("\033[?25h")
                CONSOLE.file.flush()
            except Exception:
                pass
            signal.signal(signal.SIGINT, _original_sigint)
            signal.default_int_handler(sig, frame)

        signal.signal(signal.SIGINT, _on_sigint)

    # Poll with a short sleep rather than a plain join() so that
    # KeyboardInterrupt (Ctrl-C) is delivered promptly on Windows.
    # sleep() releases the GIL and Python checks for pending signals on
    # return, so Ctrl-C is handled within ~100ms on all platforms.
    while any(t.is_alive() for t in threads):
        sleep(0.1)

    if ARGS_PARSER.progress:
        signal.signal(signal.SIGINT, _original_sigint)

    if len(threads) > 1 and not ARGS_PARSER.print_pid:
        print_info("All event streams have concluded")

    return valid_original


def follow_events(
    ydid: str,
    ydid_type: YDIDType,
    on_event: Callable[[str, YDIDType], None] | None = None,
):
    """
    Follow events for a single YDID.

    If on_event is provided it is called for each raw SSE line instead of
    print_event(), allowing callers to handle events themselves (e.g. to
    update a progress bar).
    """
    while True:
        response = requests.get(
            headers={
                "Authorization": f"yd-key {CONFIG_COMMON.key}:{CONFIG_COMMON.secret}"
            },
            url=get_event_url(ydid, ydid_type),
            stream=True,
        )

        if response.status_code != 200:
            try:
                error_text = response.json()["message"]
            except Exception:
                error_text = "(JSON error cannot be decoded)"
            print_error(f"'{ydid}': {error_text}")
            break

        if response.encoding is None:
            response.encoding = "utf-8"

        try:
            for event in response.iter_lines(decode_unicode=True):
                if event:
                    if on_event is not None:
                        on_event(event, ydid_type)
                    else:
                        print_event(event, ydid_type)
            break

        except Exception as e:
            if "Connection broken" in str(e):
                print_warning(
                    f"Event stream interruption for '{ydid}' "
                    f"(retrying in {EVENT_STREAM_RETRY_INTERVAL}s)"
                )
                sleep(EVENT_STREAM_RETRY_INTERVAL)
                continue
            else:
                print_error(f"Event stream error: {e}")
                break

    print_info(f"Event stream concluded for '{ydid}'")


def get_event_url(ydid: str, ydid_type: YDIDType) -> str:
    """
    Get the event stream URL. Assumes we've already checked that the
    YDID is one of these types.
    """
    if ydid_type is YDIDType.WORK_REQUIREMENT:
        return f"{CONFIG_COMMON.url}/work/requirements/{ydid}/updates"
    if ydid_type == YDIDType.WORKER_POOL:
        return f"{CONFIG_COMMON.url}/workerPools/{ydid}/updates"
    return f"{CONFIG_COMMON.url}/compute/requirements/{ydid}/updates"
