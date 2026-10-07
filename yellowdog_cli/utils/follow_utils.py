"""
Utility function to follow event streams.
"""

import signal
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from json import loads as json_loads
from threading import Event, Lock, Thread
from time import monotonic, sleep, time

import requests
from rich.progress import (
    BarColumn,
    Progress,
    ProgressColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.text import Text
from yellowdog_client.model import (
    ComputeRequirementStatus,
    ProvisionedWorkerPool,
    TaskGroup,
    TaskStatus,
    WorkRequirement,
)

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.event_printing import print_event
from yellowdog_cli.utils.exit_codes import (
    SESSION_FAILURES,
    ExitCode,
    ReportedFailure,
    classify,
)
from yellowdog_cli.utils.limits import (
    EVENT_STREAM_CONNECT_TIMEOUT,
    EVENT_STREAM_MAX_OUTAGE,
    EVENT_STREAM_MAX_RETRY_INTERVAL,
    EVENT_STREAM_READ_TIMEOUT,
    EVENT_STREAM_RECONNECT_DELAY,
    EVENT_STREAM_RETRY_INTERVAL,
)
from yellowdog_cli.utils.misc_utils import is_http_not_found
from yellowdog_cli.utils.printing import CONSOLE, print_error, print_info, print_warning
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

# Work Requirement terminal states that indicate failure. Shared by yd-wait
# and yd-submit so both agree on what constitutes an unsuccessful WR.
WR_FAILURE_STATUS_VALUES = frozenset({"FAILED", "CANCELLED"})

# The exit code of each failure to follow an event stream (an invalid YDID,
# an entity not found, a refused or broken connection), recorded from the
# daemon threads that follow the streams. Consulted by yd-follow for its exit
# code; other commands that follow after their primary action ignore it.
_FOLLOW_FAILURES: list[ExitCode] = []
_FOLLOW_FAILURES_LOCK = Lock()


def _record_follow_failure(failure: BaseException | ExitCode) -> None:
    code = failure if isinstance(failure, ExitCode) else classify(failure)
    with _FOLLOW_FAILURES_LOCK:
        _FOLLOW_FAILURES.append(code)


def follow_errors_occurred() -> bool:
    """
    True if any error occurred while setting up or following event streams.
    """
    with _FOLLOW_FAILURES_LOCK:
        return bool(_FOLLOW_FAILURES)


def follow_exit_code() -> ExitCode:
    """
    The exit code for the streams followed: SUCCESS if all were; the code of
    their failures if all had the same cause (NOT_FOUND, AUTHENTICATION,
    CONNECTION and so on); FAILURE if their causes differed.
    """
    with _FOLLOW_FAILURES_LOCK:
        codes = set(_FOLLOW_FAILURES)
    if not codes:
        return ExitCode.SUCCESS
    return codes.pop() if len(codes) == 1 else ExitCode.FAILURE


def reset_follow_errors() -> None:
    """
    Forget the failures recorded (used by tests).
    """
    with _FOLLOW_FAILURES_LOCK:
        _FOLLOW_FAILURES.clear()


def work_requirement_exit_code(ctx: RunContext, wr_id: str) -> ExitCode:
    """
    The exit code of yd-submit's --exit-on-failure, once a Work Requirement
    has been followed: FAILURE if it ended in a failure state (FAILED or
    CANCELLED) or its status cannot be fetched; if it has not finished
    because following it failed, that failure's own code, since its outcome
    was never seen; otherwise SUCCESS. An authentication or connection
    failure fetching the status is raised as ReportedFailure, to exit with
    its own code. Prints a warning (or error) describing a failure; success
    is left to the caller.
    """
    try:
        wr = ctx.client.work_client.get_work_requirement_by_id(wr_id)
    except Exception as e:
        print_error(f"Could not fetch final status for '{wr_id}': {e}")
        if classify(e) in SESSION_FAILURES:
            # Exits with the failure's own code, not as a failed Work Requirement
            raise ReportedFailure(e)
        return ExitCode.FAILURE
    status = wr.status.value if wr.status else "UNKNOWN"
    if status in WR_FAILURE_STATUS_VALUES:
        print_warning(
            f"Work Requirement '{wr_id}' ended with status '{status}'",
            override_quiet=True,
        )
        return ExitCode.FAILURE
    finished = wr.status is not None and wr.status.finished
    if not finished and (code := follow_exit_code()) != ExitCode.SUCCESS:
        print_error(
            f"Work Requirement '{wr_id}' could not be followed to its end, so its"
            f" outcome is not known (its status is '{status}')"
        )
        return code
    return ExitCode.SUCCESS


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
    resubmitted: int = 0,
) -> str:
    """
    Build the progress-bar description string.

    Shows WR status and done/total counts, then a breakdown of each terminal
    state (omitting any that are zero). RESUBMITTED counts as done — those
    Tasks have been re-issued in another Task Group per a FailurePolicy.
    """
    done = completed + failed + aborted + cancelled + resubmitted
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
    if resubmitted:
        parts.append(f"{resubmitted:,} resubmitted")
    if parts:
        desc += "  " + " · ".join(parts)
    return desc


@dataclass
class _TaskCounts:
    """
    A Work Requirement's Task counts, as its progress bar shows them.
    """

    total: int = 0
    completed: int = 0
    failed: int = 0
    aborted: int = 0
    cancelled: int = 0
    resubmitted: int = 0

    def add_task_groups(self, task_groups: list[TaskGroup] | None) -> None:
        """
        Add a fetched Work Requirement's Task Groups' counts.
        """
        for task_group in task_groups or []:
            summary = task_group.taskSummary
            if summary:
                self.total += summary.taskCount or 0
                counts = summary.statusCounts or {}
                self.completed += counts.get(TaskStatus.COMPLETED, 0)
                self.failed += counts.get(TaskStatus.FAILED, 0)
                self.aborted += counts.get(TaskStatus.ABORTED, 0)
                self.cancelled += counts.get(TaskStatus.CANCELLED, 0)
                self.resubmitted += counts.get(TaskStatus.RESUBMITTED, 0)

    @staticmethod
    def of_event(event_data: dict) -> "_TaskCounts":
        """
        The counts in a Work Requirement event's Task Groups.
        """
        counts = _TaskCounts()
        for task_group in event_data.get("taskGroups", []):
            summary = task_group.get("taskSummary", {})
            counts.total += summary.get("taskCount", 0)
            status_counts = summary.get("statusCounts", {})
            counts.completed += status_counts.get("COMPLETED", 0)
            counts.failed += status_counts.get("FAILED", 0)
            counts.aborted += status_counts.get("ABORTED", 0)
            counts.cancelled += status_counts.get("CANCELLED", 0)
            counts.resubmitted += status_counts.get("RESUBMITTED", 0)
        return counts

    def show(self, progress: Progress, bar_task: TaskID, wr_status: str) -> None:
        progress.update(
            bar_task,
            total=self.total if self.total > 0 else None,
            completed=self.completed,
            description=_progress_desc(
                wr_status,
                self.total,
                self.completed,
                self.failed,
                self.aborted,
                self.cancelled,
                self.resubmitted,
            ),
        )

    def failures(self) -> str | None:
        """
        The Tasks that did not succeed, as the closing warning gives them, or
        None if there were none.
        """
        parts = []
        if self.failed:
            parts.append(f"{self.failed:,} failed")
        if self.aborted:
            parts.append(f"{self.aborted:,} aborted")
        if self.cancelled:
            parts.append(f"{self.cancelled:,} cancelled")
        return " · ".join(parts) if parts else None


@dataclass(frozen=True)
class _FetchedWorkRequirement:
    """
    What the progress bar starts from: the Work Requirement, if it could be
    fetched, how long it has run (or ran) and whether it has finished.
    """

    wr: WorkRequirement | None = None
    age_seconds: float = 0.0
    finished: bool = False


def _fetch_for_progress(ctx: RunContext, ydid: str) -> _FetchedWorkRequirement | None:
    """
    The Work Requirement to follow, or None if it does not exist, having
    reported that.
    """
    try:
        wr = ctx.client.work_client.get_work_requirement_by_id(ydid)
    except Exception as e:
        if is_http_not_found(e):
            # Fail fast with a plain error rather than starting the live
            # progress display around an event stream that will just 404
            print_error(f"Work Requirement '{ydid}' not found")
            _record_follow_failure(ExitCode.NOT_FOUND)
            return None
        # Other fetch errors may be transient; leave them to the event stream
        return _FetchedWorkRequirement()

    finished = wr.status is not None and wr.status.finished
    age_seconds = 0.0
    if finished and wr.createdTime is not None and wr.statusChangedTime is not None:
        # Show how long the WR actually ran, not how long ago we fetched it
        age_seconds = max(0.0, (wr.statusChangedTime - wr.createdTime).total_seconds())
    elif wr.createdTime is not None:
        age_seconds = max(0.0, time() - wr.createdTime.timestamp())
    return _FetchedWorkRequirement(wr, age_seconds, finished)


def follow_work_requirement_with_progress(ctx: RunContext, ydid: str) -> None:
    """
    Follow a Work Requirement event stream, displaying a live Rich progress bar.

    Safe to call from either the main thread or a daemon thread; signal
    handling is skipped automatically when not in the main thread.
    """
    fetched = _fetch_for_progress(ctx, ydid)
    if fetched is None:
        return

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
    wr_name = (fetched.wr.name or "") if fetched.wr is not None else ""
    bar_task = progress.add_task("Starting\u2026", total=None, wr_name=wr_name)
    if fetched.age_seconds > 0:
        progress.tasks[0].start_time = monotonic() - fetched.age_seconds
    if fetched.finished:
        progress.stop_task(bar_task)

    counts = _TaskCounts()
    # Pre-populate from the fetched WR so the bar shows a meaningful state
    # even if no events arrive (e.g. the WR is already in a terminal state).
    if fetched.wr is not None:
        try:
            counts.add_task_groups(fetched.wr.taskGroups)
            wr_status = fetched.wr.status.value if fetched.wr.status else ""
            counts.show(progress, bar_task, wr_status)
        except Exception:
            pass

    def on_event(event: str, ydid_type: YDIDType) -> None:
        nonlocal counts
        if not event.startswith("data:"):
            return
        try:
            event_data = json_loads(event[len("data:") :])
        except Exception:
            return
        if ydid_type is not YDIDType.WORK_REQUIREMENT:
            return
        counts = _TaskCounts.of_event(event_data)
        counts.show(progress, bar_task, event_data.get("status", ""))

    print_info(f"Tracking progress for Work Requirement '{ydid}'")
    with _cursor_restored_on_interrupt(), progress:
        follow_events(ctx, ydid, YDIDType.WORK_REQUIREMENT, on_event=on_event)

    if (failures := counts.failures()) is not None:
        print_warning(f"Work Requirement finished with {failures} task(s)")


def _restore_cursor() -> None:
    try:
        CONSOLE.file.write("\033[?25h")
        CONSOLE.file.flush()
    except Exception:
        pass


@contextmanager
def _cursor_restored_on_interrupt() -> Iterator[None]:
    """
    Restore the terminal's cursor, which the progress bar hides, when the
    block ends and on a keyboard interrupt, which is then raised as usual.
    The interrupt is caught only in the main thread, the only one signal
    handlers can be set in.
    """
    original_sigint = signal.getsignal(signal.SIGINT)

    def on_sigint(sig: int, frame) -> None:
        _restore_cursor()
        signal.signal(signal.SIGINT, original_sigint)
        signal.default_int_handler(sig, frame)

    try:
        signal.signal(signal.SIGINT, on_sigint)
        in_main_thread = True
    except ValueError:
        in_main_thread = False  # Signal handlers only work in the main thread

    try:
        yield
    finally:
        if in_main_thread:
            signal.signal(signal.SIGINT, original_sigint)
        _restore_cursor()


_FOLLOWABLE = frozenset(
    [YDIDType.WORK_REQUIREMENT, YDIDType.WORKER_POOL, YDIDType.COMPUTE_REQUIREMENT]
)


# Set once a deadline (yd-wait's '--timeout') stops the following: each
# stream's thread then prints nothing more and does not reconnect, and ends
# with the process, being a daemon
_STOP_FOLLOWING = Event()


def follow_ids(
    ctx: RunContext,
    ydids: list[str],
    auto_cr: bool = False,
    timeout: float | None = None,
) -> list[str]:
    """
    Creates an event thread for each YDID passed on the command line. With
    'timeout', stops following once that many seconds have passed, whether
    or not every stream has concluded.

    Returns the deduplicated list of valid original IDs (WR/WP/CR only, before
    any auto-CR expansion) — callers that need to inspect final status after
    the streams conclude can use this list directly.
    """
    if not ydids:
        return []

    # In the order given, without duplicates
    unique_ydids = list(dict.fromkeys(ydids))
    num_duplicates = len(ydids) - len(unique_ydids)
    if num_duplicates > 0:
        print_warning(f"Ignoring {num_duplicates} duplicate YellowDog ID(s)")

    # Capture valid original IDs before auto-CR expansion
    valid_original = [
        ydid for ydid in unique_ydids if get_ydid_type(ydid) in _FOLLOWABLE
    ]

    to_follow = list(unique_ydids)
    if auto_cr:
        # Automatically add Compute Requirement IDs for
        # Provisioned Worker Pools, to follow both
        for ydid in unique_ydids:
            if get_ydid_type(ydid) == YDIDType.WORKER_POOL:
                cr_ydid = _compute_requirement_of_worker_pool(ctx, ydid)
                if cr_ydid is not None and cr_ydid not in to_follow:
                    print_info(
                        f"Adding event stream for Compute Requirement '{cr_ydid}'"
                    )
                    to_follow.append(cr_ydid)

    print_info(f"Following the event stream(s) for {len(to_follow)} YellowDog ID(s)")

    # Rich only supports one live display at a time, so the progress bar can
    # only be used when following a single Work Requirement
    use_progress = bool(ctx.args.progress)
    if (
        use_progress
        and sum(
            1 for ydid in to_follow if get_ydid_type(ydid) == YDIDType.WORK_REQUIREMENT
        )
        > 1
    ):
        print_warning(
            "'--progress' supports a single Work Requirement only; "
            "using plain event following instead"
        )
        use_progress = False

    # Before any stream starts, or one could see a stop left by an earlier call
    _STOP_FOLLOWING.clear()
    threads: list[Thread] = []

    for ydid in to_follow:
        ydid_type = get_ydid_type(ydid)
        if ydid_type not in _FOLLOWABLE:
            print_error(
                f"Invalid YellowDog ID '{ydid}' (Must be valid YDID for Work"
                " Requirement, Worker Pool or Compute Requirement)"
            )
            _record_follow_failure(ExitCode.FAILURE)
            continue

        if use_progress and ydid_type == YDIDType.WORK_REQUIREMENT:
            target, args = follow_work_requirement_with_progress, (ctx, ydid)
        else:
            target, args = follow_events, (ctx, ydid, ydid_type)
        thread = Thread(target=target, args=args, daemon=True)
        try:
            thread.start()
        except RuntimeError as e:
            print_error(f"Unable to start event thread for '{ydid}': ({e})")
            _record_follow_failure(e)
            continue
        threads.append(thread)

    # Install a SIGINT handler in the main thread so that Ctrl-C restores the
    # terminal cursor even if Rich's Live context is running in a daemon thread
    # (signal handlers can only be installed from the main thread).
    _original_sigint = signal.getsignal(signal.SIGINT)
    if ctx.args.progress and threads:

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
    deadline = None if timeout is None else monotonic() + timeout
    while any(t.is_alive() for t in threads):
        if deadline is not None and monotonic() >= deadline:
            _STOP_FOLLOWING.set()
            print_warning(f"Stopped following after {timeout:,g} second(s)")
            break
        sleep(0.1)

    if ctx.args.progress:
        signal.signal(signal.SIGINT, _original_sigint)

    if len(threads) > 1 and not ctx.args.print_pid:
        print_info("All event streams have concluded")

    return valid_original


def _compute_requirement_of_worker_pool(
    ctx: RunContext, worker_pool_id: str
) -> str | None:
    """
    The Compute Requirement of a Provisioned Worker Pool, to follow with it;
    None for a Configured one, which has none. A pool that cannot be fetched
    is a failure to follow, recorded as one.
    """
    try:
        worker_pool = ctx.client.worker_pool_client.get_worker_pool_by_id(
            worker_pool_id
        )
    except Exception as e:
        print_error(
            f"Unable to find the Compute Requirement of Worker Pool"
            f" '{worker_pool_id}': {e}"
        )
        _record_follow_failure(e)
        return None
    if isinstance(worker_pool, ProvisionedWorkerPool):
        return worker_pool.computeRequirementId
    return None


def _entity_finished(ctx: RunContext, ydid: str, ydid_type: YDIDType) -> bool | None:
    """
    Whether the entity whose event stream has closed has finished, as the
    Platform closes a stream when it does. A stream closed for any other
    reason (a proxy dropping an idle connection, say) is reconnected. An
    entity whose status cannot be fetched is taken as finished, with a
    warning, rather than reconnected for ever; but an authentication or
    connection failure is reported and recorded, and None returned, for the
    following to stop without the stream counting as concluded.
    """
    try:
        if ydid_type == YDIDType.WORK_REQUIREMENT:
            status = ctx.client.work_client.get_work_requirement_by_id(ydid).status
            return status is None or status.finished
        if ydid_type == YDIDType.WORKER_POOL:
            status = ctx.client.worker_pool_client.get_worker_pool_by_id(ydid).status
            return status is None or status.finished
        status = ctx.client.compute_client.get_compute_requirement_by_id(ydid).status
        return status is None or status == ComputeRequirementStatus.TERMINATED
    except Exception as e:
        if classify(e) in SESSION_FAILURES:
            print_error(
                f"The event stream for '{ydid}' closed, and its status could not be"
                f" checked: {e}"
            )
            _record_follow_failure(e)
            return None
        print_warning(
            f"The event stream for '{ydid}' closed, and its status could not be"
            f" checked ({e}): taking it to have finished"
        )
        return True


class _Outage:
    """
    The reconnection of a stream that has dropped: a wait that doubles from
    EVENT_STREAM_RETRY_INTERVAL to EVENT_STREAM_MAX_RETRY_INTERVAL, for as
    long as the outage has lasted less than EVENT_STREAM_MAX_OUTAGE.
    """

    def __init__(self):
        self._started: float | None = None
        self._attempts = 0

    def end(self) -> None:
        self._started = None
        self._attempts = 0

    def wait(self) -> bool:
        """
        Wait before the next attempt to reconnect, and return True; or
        return False, at once, once the outage has lasted too long.
        """
        if self._started is None:
            self._started = monotonic()
        elif monotonic() - self._started >= EVENT_STREAM_MAX_OUTAGE:
            return False
        sleep(
            min(
                EVENT_STREAM_RETRY_INTERVAL * 2**self._attempts,
                EVENT_STREAM_MAX_RETRY_INTERVAL,
            )
        )
        self._attempts += 1
        return True


def follow_events(
    ctx: RunContext,
    ydid: str,
    ydid_type: YDIDType,
    on_event: Callable[[str, YDIDType], None] | None = None,
):
    """
    Follow events for a single YDID.

    If on_event is provided it is called for each raw SSE line instead of
    print_event(), allowing callers to handle events themselves (e.g. to
    update a progress bar).

    A stream that drops is reconnected (see _Outage), as is one that closes
    while its entity is still live (_entity_finished()). A first connection
    that fails is reported at once. Each failure is recorded for the exit
    code (follow_exit_code()).
    """
    outage = _Outage()
    connected = False
    concluded = False
    while not _STOP_FOLLOWING.is_set():
        try:
            response = requests.get(
                headers={
                    "Authorization": f"yd-key {ctx.config.key}:{ctx.config.secret}"
                },
                url=get_event_url(ctx, ydid, ydid_type),
                stream=True,
                timeout=(EVENT_STREAM_CONNECT_TIMEOUT, EVENT_STREAM_READ_TIMEOUT),
            )
        except requests.exceptions.RequestException as e:
            if connected and outage.wait():
                continue
            print_error(
                f"Unable to {'reconnect' if connected else 'connect'} to the event"
                f" stream for '{ydid}': {e}"
            )
            _record_follow_failure(e)
            break

        with response:
            if response.status_code != 200:
                try:
                    error_text = response.json()["message"]
                except Exception:
                    error_text = "(JSON error cannot be decoded)"
                print_error(f"'{ydid}': {error_text}")
                # An HTTPError carrying the response, classified by its status
                _record_follow_failure(
                    requests.HTTPError(error_text, response=response)
                )
                break

            connected = True
            outage.end()
            if response.encoding is None:
                response.encoding = "utf-8"

            try:
                for event in response.iter_lines(decode_unicode=True):
                    if _STOP_FOLLOWING.is_set():
                        return
                    if event and isinstance(event, str):
                        if on_event is not None:
                            on_event(event, ydid_type)
                        else:
                            print_event(event, ydid_type)

            except requests.exceptions.Timeout:
                # A read timeout just means a quiet (or silently dropped)
                # connection; reconnect without alarming the user
                continue

            except (
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ConnectionError,
                ConnectionResetError,
            ):
                print_warning(f"Event stream interruption for '{ydid}' (reconnecting)")
                if outage.wait():
                    continue
                print_error(f"Unable to reconnect to the event stream for '{ydid}'")
                _record_follow_failure(ExitCode.CONNECTION)
                break

            except Exception as e:
                print_error(f"Event stream error: {e}")
                _record_follow_failure(e)
                break

        # Closed cleanly: by the Platform once the entity has finished, or by
        # something in between, in which case it is reconnected
        if _STOP_FOLLOWING.is_set():
            return
        finished = _entity_finished(ctx, ydid, ydid_type)
        if finished is None:  # Reported and recorded
            break
        if finished:
            concluded = True
            break
        sleep(EVENT_STREAM_RECONNECT_DELAY)

    if concluded:
        print_info(f"Event stream concluded for '{ydid}'")


def get_event_url(ctx: RunContext, ydid: str, ydid_type: YDIDType) -> str:
    """
    Get the event stream URL. Assumes we've already checked that the
    YDID is one of these types.
    """
    if ydid_type is YDIDType.WORK_REQUIREMENT:
        return f"{ctx.config.url}/work/requirements/{ydid}/updates"
    if ydid_type == YDIDType.WORKER_POOL:
        return f"{ctx.config.url}/workerPools/{ydid}/updates"
    return f"{ctx.config.url}/compute/requirements/{ydid}/updates"
