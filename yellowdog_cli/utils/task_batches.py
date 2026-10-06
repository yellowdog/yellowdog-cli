"""
Submitting Tasks in batches, for yd-submit: a Task Group's Tasks from a
specification, and a '--json-raw' file's.

run_batches() splits the Tasks into batches and sends them one after
another, pausing between them as '--pause-between-batches' asks, or on a
pool of threads (Batches) when more than one is allowed. What a batch is
and how it is sent are the caller's: 'make_batch' builds the Tasks of a
range, 'send_batch' submits them, through submit_with_retries(), which
retries a failure a retry could cure (is_permanent_failure() says which
cannot) and raises the last one as it was raised, so that the exit code
names it.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from math import ceil
from threading import Event
from time import sleep
from typing import TYPE_CHECKING, Any, NoReturn

import requests

from yellowdog_cli.utils.exit_codes import MISSING_PERMISSION_TEXT, UNAUTHORIZED_TEXT
from yellowdog_cli.utils.interactive import wait_for_enter
from yellowdog_cli.utils.limits import (
    BATCH_SUBMIT_RETRY_DELAY,
    MAX_BATCH_SUBMIT_ATTEMPTS,
)
from yellowdog_cli.utils.printing import print_error, print_info, print_warning
from yellowdog_cli.utils.results import json_requested

if TYPE_CHECKING:
    from yellowdog_cli.utils.context import RunContext


class Batches:
    """
    Batches uploaded on a pool of threads. Once one fails, a batch not yet
    started is skipped: the Work Requirement is about to be cancelled, and
    its Tasks would only be submitted to it. Each batch checks as it starts,
    rather than the queue being cancelled, since a thread takes the next
    batch as soon as it is free, before the failure can be seen.
    """

    def __init__(self, executor: ThreadPoolExecutor):
        self._executor = executor
        self._stop = Event()
        self._futures: list[Future] = []

    def submit(self, function: Callable[..., int], *args) -> None:
        self._futures.append(self._executor.submit(self._run, function, *args))

    def _run(self, function: Callable[..., int], *args) -> int:
        if self._stop.is_set():
            return 0
        try:
            return function(*args)
        except BaseException:
            self._stop.set()
            raise

    def total(self) -> int:
        """
        The Tasks submitted, once every batch has finished or been skipped;
        the first failure is raised then.
        """
        total = 0
        failure: BaseException | None = None
        for future in self._futures:
            try:
                total += future.result()
            except BaseException as e:
                failure = failure or e
        if failure is not None:
            raise failure
        return total


def run_batches(
    ctx: RunContext,
    num_tasks: int,
    batch_size: int,
    parallel_threads: int,
    make_batch: Callable[[int, int], list[Any]],
    send_batch: Callable[[list[Any], int, int], int],
) -> int:
    """
    Submit 'num_tasks' Tasks in batches of 'batch_size', returning how many
    were submitted. 'make_batch(start, end)' builds the Tasks numbered from
    'start' up to 'end'; 'send_batch(tasks, batch_number, num_batches)'
    submits them, returning how many. One thread, or one batch, sends them
    in turn, with '--pause-between-batches'; more send them in parallel, the
    batches still built in turn, here. A failure raises, once any batches
    already under way have finished.
    """
    num_batches = ceil(num_tasks / batch_size)

    def batch(batch_number: int) -> list[Any]:
        return make_batch(
            batch_size * batch_number, min(batch_size * (batch_number + 1), num_tasks)
        )

    # A Task Group with no Tasks has no batches, and a pool of no threads
    # cannot be built for it
    if parallel_threads == 1 or num_batches <= 1:
        if num_batches > 1:
            print_info(f"Uploading {num_batches} Task batches sequentially")
        submitted = 0
        for batch_number in range(num_batches):
            if ctx.args.pause_between_batches is not None and num_batches > 1:
                pause_between_batches(ctx, batch_size, batch_number, num_tasks)
            submitted += send_batch(batch(batch_number), batch_number, num_batches)
        return submitted

    if ctx.args.pause_between_batches is not None:
        print_warning(
            "Option 'pause-between-batches/-P' is ignored for parallel batch uploads"
        )
    max_workers = min(num_batches, parallel_threads)
    print_info(
        f"Submitting Task batches using {max_workers} parallel submission threads"
    )
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        batches = Batches(executor)
        for batch_number in range(num_batches):
            batches.submit(send_batch, batch(batch_number), batch_number, num_batches)
        return batches.total()


def pause_between_batches(
    ctx: RunContext, task_batch_size: int, batch_number: int, num_tasks: int
):
    """
    Process a pause between Task batches.
    """
    if ctx.args.pause_between_batches is None:
        return

    first_batch: bool = batch_number == 0
    task_num_start = (task_batch_size * batch_number) + 1
    task_num_end = min(task_batch_size * (batch_number + 1), num_tasks)
    task_range_str = (
        f"Tasks {task_num_start}-{task_num_end}"
        if task_num_start != task_num_end
        else f"Task {task_num_start}"
    )

    if ctx.args.pause_between_batches <= 0:  # Manual delay
        if first_batch:
            print_info(
                f"Submitting batch number {batch_number + 1} ({task_range_str})",
                override_quiet=not json_requested(),
            )
        else:
            # The prompt goes to stderr under '--json', and with no terminal
            # to answer from NoAnswerToPrompt is raised, not an EOFError
            wait_for_enter(
                "Pausing before submitting batch number"
                f" {batch_number + 1} ({task_range_str}). Press enter to continue:"
            )

    elif ctx.args.pause_between_batches > 0:  # Automatic delay
        print_info(
            f"Submitting batch number {batch_number + 1} ({task_range_str})"
            if first_batch
            else (
                f"Pausing for {ctx.args.pause_between_batches} seconds before"
                f" submitting batch number {batch_number + 1}"
                f" ({task_range_str})"
            )
        )
        if not first_batch:
            sleep(ctx.args.pause_between_batches)


def submit_with_retries(
    attempt: Callable[[], None],
    report_success: Callable[[], None],
    batch: str,
    batch_in_full: str,
) -> None:
    """
    Make one batch submission, retrying it with a growing delay while it
    fails in a way a retry could cure. Returns once it succeeds; raises its
    last failure, as it was raised, once it cannot.
    """
    for attempt_number in range(MAX_BATCH_SUBMIT_ATTEMPTS):
        try:
            attempt()
            report_success()
            return

        except Exception as e:
            # On a retry, this implies that the previous attempt, which
            # reported an error, did in fact add the batch. On the first
            # attempt it is a genuine name collision: a failure, and one not
            # to retry, since the retry would take it for success.
            duplicate_names = "Task names must be unique within task group" in str(e)
            if duplicate_names and attempt_number > 0:
                report_success()
                return

            # Raised as it is, not wrapped, so that the wrapper's classify()
            # still sees its type and the exit code names the kind of failure
            if (
                duplicate_names
                or is_permanent_failure(e)
                or attempt_number == MAX_BATCH_SUBMIT_ATTEMPTS - 1
            ):
                print_error(f"Failed to submit {batch_in_full}")
                raise

            if attempt_number == 0:
                print_warning(f"Failed to submit {batch}: {e}")
            delay = BATCH_SUBMIT_RETRY_DELAY * 2**attempt_number
            print_info(
                f"Retrying submission of {batch} in {delay:g}s "
                f"(retry attempt {attempt_number + 1} of {MAX_BATCH_SUBMIT_ATTEMPTS - 1})"
            )
            sleep(delay)

    raise AssertionError("unreachable: the last attempt returns or raises")


def is_permanent_failure(exception: Exception) -> bool:
    """
    A failure that resubmitting the same batch cannot cure: the request
    itself is invalid, or the credentials are refused or lack permission;
    for a direct request ('--json-raw'), any 4xx but a timeout or 429.
    """
    from yellowdog_client.model.exceptions.invalid_request_exception import (
        InvalidRequestException,
    )
    from yellowdog_client.model.exceptions.not_authorised_exception import (
        NotAuthorisedException,
    )

    if isinstance(exception, (InvalidRequestException, NotAuthorisedException)):
        return True
    if isinstance(exception, requests.HTTPError):
        # A refusal, but not a timeout or a request to slow down
        status = getattr(exception.response, "status_code", None)
        if isinstance(status, int) and 400 <= status < 500:
            return status not in (408, 429)
    message = str(exception)
    return any(
        text in message
        for text in (
            "InvalidRequestException",
            MISSING_PERMISSION_TEXT,
            UNAUTHORIZED_TEXT,
        )
    )


def raise_for_response(response: requests.Response) -> NoReturn:
    """
    Raise a failed response as an HTTPError carrying it, so that the
    wrapper's classify() can name the failure by its status code, with the
    Platform's own explanation (the response body) as its message.
    """
    raise requests.HTTPError(
        f"HTTP {response.status_code}: {response.text}", response=response
    )
