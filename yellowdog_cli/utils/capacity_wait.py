"""
Waiting for Compute Requirements to reach their target capacity, for the
'--wait' of yd-resize and yd-compute-reprovision; and telling when an action
followed with '--follow' is done (capacity_reached()), for those whose
Compute Requirement stays alive, so that its event stream never closes.

A Compute Requirement has settled when it is RUNNING with no next status, as
many of its Instances are RUNNING as its target asks for, and none is still
starting, stopping or terminating: scaling up waits for the new Instances to
run, scaling down for the surplus to be gone. The SDK's
is_compute_requirement_updating() is no use for this: the Platform clears it
within a second or two of accepting a change, long before any Instance has
started or stopped. A Compute Requirement that cannot reach its target (the
provider out of capacity, on-demand or spot, or a limit reached) never
settles, so the caller's timeout is what ends the wait then.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.limits import CAPACITY_POLL_INTERVAL
from yellowdog_cli.utils.printing import print_info

if TYPE_CHECKING:
    from yellowdog_client.model import ComputeRequirement, Instance

# Instance states that mean a change is still being carried out
_TRANSITIONAL_INSTANCE_STATUSES = ("PENDING", "STOPPING", "TERMINATING")


class CapacityWaitTimeout(RuntimeError):
    """
    The timeout passed before every Compute Requirement settled.
    """


@dataclass(frozen=True)
class Capacity:
    """
    Where a Compute Requirement stands: its status, its target and how many
    of its Instances are in each state that matters.
    """

    label: str
    status: str
    next_status: str | None
    target: int
    instance_counts: tuple[tuple[str, int], ...]

    def count(self, status: str) -> int:
        return dict(self.instance_counts).get(status, 0)

    @property
    def settled(self) -> bool:
        return (
            self.status == "RUNNING"
            and self.next_status is None
            and self.count("RUNNING") == self.target
            and not any(
                self.count(status) for status in _TRANSITIONAL_INSTANCE_STATUSES
            )
        )

    @property
    def quiet(self) -> bool:
        """
        Nothing is changing: RUNNING or STOPPED with no next status, and no
        Instance starting, stopping or terminating. Not necessarily at its
        target, as a stopped one, or one with Instances stopped, is not.
        """
        return (
            self.status in ("RUNNING", "STOPPED")
            and self.next_status is None
            and not any(
                self.count(status) for status in _TRANSITIONAL_INSTANCE_STATUSES
            )
        )

    def describe(self) -> str:
        """
        E.g. "1 of 2 Instance(s) running, 1 pending (PROVISIONING)".
        """
        parts = [f"{self.count('RUNNING'):,d} of {self.target:,d} Instance(s) running"]
        parts += [
            f"{self.count(status):,d} {status.lower()}"
            for status in _TRANSITIONAL_INSTANCE_STATUSES
            if self.count(status)
        ]
        text = ", ".join(parts)
        return text if self.status == "RUNNING" else f"{text} ({self.status})"


def _name(status: object) -> str | None:
    """
    An SDK enum's name (or a plain string), None for None.
    """
    if status is None:
        return None
    return str(getattr(status, "name", status))


def capacity_of(
    compute_requirement: ComputeRequirement, instances: list[Instance]
) -> Capacity:
    counts = Counter(_name(instance.status) for instance in instances)
    return Capacity(
        label=f"'{compute_requirement.namespace}/{compute_requirement.name}'",
        status=str(_name(compute_requirement.status)),
        next_status=_name(compute_requirement.nextStatus),
        target=compute_requirement.targetInstanceCount or 0,
        instance_counts=tuple(
            sorted((status, n) for status, n in counts.items() if status)
        ),
    )


def _current_capacity(ctx: RunContext, cr_id: str) -> Capacity:
    """
    A Compute Requirement's capacity, read afresh: entity_utils caches its
    Instance lookups, which a wait must not.
    """
    from yellowdog_client.model import InstanceSearch

    compute_client = ctx.client.compute_client
    compute_requirement = compute_client.get_compute_requirement_by_id(cr_id)
    instances = compute_client.get_instances(
        InstanceSearch(computeRequirementId=cr_id)
    ).list_all()
    return capacity_of(compute_requirement, instances)


def wait_for_capacity(ctx: RunContext, cr_ids: list[str], timeout: int | None):
    """
    Wait until every Compute Requirement has settled, printing each one's
    progress whenever it changes. Raises CapacityWaitTimeout if 'timeout'
    seconds pass first; any failure to read one (a lost connection, say) is
    raised as it is.
    """
    deadline = None if timeout is None else time.monotonic() + timeout
    pending = list(dict.fromkeys(cr_ids))
    last: dict[str, Capacity] = {}
    print_info(
        f"Waiting for {len(pending)} Compute Requirement(s) to reach their"
        " target instance counts"
    )

    while True:
        for cr_id in list(pending):
            capacity = _current_capacity(ctx, cr_id)
            # A settled one is reported even if unchanged: it is the last word
            if capacity.settled or last.get(cr_id) != capacity:
                print_info(
                    f"Compute Requirement {capacity.label}: {capacity.describe()}"
                )
            if capacity.settled:
                pending.remove(cr_id)
            last[cr_id] = capacity
        if not pending:
            return
        if deadline is not None and time.monotonic() >= deadline:
            raise CapacityWaitTimeout(
                f"Timed out after {timeout:,d}s waiting for Compute Requirement(s)"
                " to reach their target instance counts: "
                + "; ".join(
                    f"{last[cr_id].label} {last[cr_id].describe()}" for cr_id in pending
                )
            )
        time.sleep(
            CAPACITY_POLL_INTERVAL
            if deadline is None
            else max(0.0, min(CAPACITY_POLL_INTERVAL, deadline - time.monotonic()))
        )


# When an action followed is done, given the Compute Requirement's capacity
# and whether it has been seen unsettled since the action ('changed')
DoneWhen = Callable[[Capacity, bool], bool]


def until_settled(capacity: Capacity, changed: bool) -> bool:
    """
    At its target, running: a start, a deprovision, a reprovision, a resize.
    """
    return capacity.settled


def until_settled_again(capacity: Capacity, changed: bool) -> bool:
    """
    At its target again, having left it: a restart, which begins settled.
    """
    return changed and capacity.settled


def until_stopped(capacity: Capacity, changed: bool) -> bool:
    """
    Nothing changing, having changed: a stop, of the Compute Requirement or
    of some of its Instances, after which it is not at its target.
    """
    return changed and capacity.quiet


def capacity_reached(
    ctx: RunContext, done: DoneWhen
) -> Callable[[str], Callable[[dict], bool]]:
    """
    For follow_ids()'s 'settled': for each Compute Requirement followed, a
    test, made after each of its events, of whether the action is done,
    reading its capacity afresh (an event's own counts are per source and
    may lag), and remembering whether it has been seen unsettled.
    """

    def for_stream(cr_id: str) -> Callable[[dict], bool]:
        changed = False

        def settled(_event: dict) -> bool:
            nonlocal changed
            capacity = _current_capacity(ctx, cr_id)
            changed = changed or not capacity.settled
            return done(capacity, changed)

        return settled

    return for_stream
