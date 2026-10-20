"""
Running work for the live suite: submitting a specification from
tests/live/specs with variables, reading a Work Requirement and its Tasks,
waiting for their states, reading 'wr follow --json' (an indented JSON
document per event) and holding them to the entity's end, following an
entity while another call ends it, a Node verb with its outcome checked,
and cleaning up after a scenario (cancelling what it made) without hiding
the scenario's own failure.
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import contextmanager

from harness.compute import NOT_FOUND, ComputeTimeout, wait_for
from harness.run import SPECS
from harness.yd import Result, Yd

TERMINAL = frozenset({"COMPLETED", "FAILED", "CANCELLED"})


def submit(yd: Yd, spec: str, *extra: str, **variables: str) -> dict:
    """
    'yd wr submit' of a specification, with variables; the created entity.
    """
    words = [
        arg
        for name, value in variables.items()
        for arg in ("--variable", f"{name}={value}")
    ]
    return yd(
        "wr", "submit", str(SPECS / spec), *words, *extra, "--json", "--quiet"
    ).document


def work_requirement(yd: Yd, wr_id: str) -> dict:
    return yd("wr", "show", wr_id, "--quiet").document


def tasks_of(yd: Yd, namespace: str, run_id: str, wr_id: str) -> list[dict]:
    """
    The Work Requirement's Tasks: the run's, in its Task Groups.
    """
    groups = {g["id"] for g in work_requirement(yd, wr_id).get("taskGroups") or []}
    listed = yd(
        "task",
        "list",
        "--namespace",
        namespace,
        "--tag",
        run_id,
        "--json",
        "--quiet",
        ok=(0, NOT_FOUND),
    ).records
    return [task for task in listed if task.get("taskGroupId") in groups]


def wait_for_status(
    yd: Yd, wr_id: str, statuses: frozenset[str], timeout_minutes: float, **timing
) -> str:
    seen = {"status": "UNKNOWN"}

    def probe() -> tuple[bool, str]:
        seen["status"] = work_requirement(yd, wr_id).get("status") or "UNKNOWN"
        return seen["status"] in statuses, seen["status"]

    wait_for(f"{wr_id} {'/'.join(sorted(statuses))}", probe, timeout_minutes, **timing)
    return seen["status"]


def wait_for_task(
    yd: Yd,
    namespace: str,
    run_id: str,
    wr_id: str,
    status: str,
    timeout_minutes: float,
    **timing,
) -> dict:
    """
    The first of the Work Requirement's Tasks to be in the status.
    """
    found: dict = {}

    def probe() -> tuple[bool, str]:
        current = tasks_of(yd, namespace, run_id, wr_id)
        matching = [task for task in current if task.get("status") == status]
        if matching:
            found.update(matching[0])
        return bool(matching), ", ".join(
            t.get("status", "?") for t in current
        ) or "no Tasks"

    wait_for(f"a Task of {wr_id} {status}", probe, timeout_minutes, **timing)
    return found


def follow_events(stdout: str) -> list[dict]:
    """
    The events 'wr follow --json' printed: JSON documents one after another,
    each indented (so spanning lines), as the CLI prints every document.
    """
    decoder = json.JSONDecoder()
    events: list[dict] = []
    index = 0
    while True:
        while index < len(stdout) and stdout[index].isspace():
            index += 1
        if index == len(stdout):
            return events
        event, index = decoder.raw_decode(stdout, index)
        events.append(event)


def ended_with(events: list[dict], statuses: Iterable[str]) -> None:
    """
    Hold a follow's events to the entity's end: at least one, each naming a
    status, the last in 'statuses'.
    """
    assert events, "no events"
    shown = [event.get("status") for event in events]
    assert all(shown), f"an event with no status: {shown}"
    assert shown[-1] in set(statuses), f"the follow ended at {shown[-1]}: {shown}"


class CleanupFailedWarning(UserWarning):
    """
    A clean-up failed after the scenario it followed had failed.
    """


@contextmanager
def cleaned_up(cleanup: Callable[[], object]) -> Iterator[None]:
    """
    Run 'cleanup' after the block, however it ends. When the block failed,
    a failing clean-up is a warning, so the scenario's own failure is the
    one reported; after a block that passed, it fails the test.
    """
    try:
        yield
    except BaseException:
        try:
            cleanup()
        except Exception as error:
            warnings.warn(
                CleanupFailedWarning(f"clean-up after a failed scenario: {error}"),
                stacklevel=3,
            )
        raise
    cleanup()


@contextmanager
def cancelled_after(yd: Yd) -> Iterator[list[str]]:
    """
    The IDs of the Work Requirements a scenario makes, each added as it is
    submitted, all cancelled (cancel_all()) after the block, as cleaned_up()
    does.
    """
    made: list[str] = []
    with cleaned_up(lambda: cancel_all(yd, made)):
        yield made


def cancel_all(yd: Yd, wr_ids: Iterable[str]) -> None:
    """
    Cancel each Work Requirement, aborting its Tasks; one already finished
    is nothing to do.
    """
    for wr_id in wr_ids:
        yd(
            "wr",
            "cancel",
            "--abort",
            "--yes",
            "--json",
            "--quiet",
            wr_id,
            ok=(0, NOT_FOUND),
        )


def act_on_node(yd: Yd, verb: str, node_id: str) -> list[dict]:
    """
    A Node verb ('restart', 'deprovision', 'terminate', 'shutdown') on one
    Node; its records, which must show it done, neither failed nor skipped.
    """
    done = yd("node", verb, node_id, "--yes", "--json", "--quiet")
    undone = [r for r in done.records if r.get("outcome") in ("failed", "skipped")]
    assert done.records and not undone, yd.describe(done)
    return done.records


def follow_alongside(
    yd: Yd,
    follow_args: tuple[str, ...],
    action: Callable[[], None],
    timeout_seconds: float,
) -> Result:
    """
    Follow an entity in a thread while 'action' ends it; the follow's result,
    or ComputeTimeout if it has not ended 'timeout_seconds' after the action.
    A failing action, or a follow that overruns, is raised at once, without
    waiting for the follow, which its own timeout ends.
    """
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(
            yd, *follow_args, "--json", "--quiet", timeout=timeout_seconds + 60
        )
        action()
        try:
            return future.result(timeout=timeout_seconds)
        except FutureTimeout:
            raise ComputeTimeout(
                f"{' '.join(follow_args)}: still following {timeout_seconds:g}s after"
                " the entity was ended"
            ) from None
    finally:
        pool.shutdown(wait=False)
