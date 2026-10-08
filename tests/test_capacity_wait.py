"""
Unit tests for utils/capacity_wait.py, the '--wait' of yd-resize and
yd-compute-reprovision, against a fake Platform that steps through scripted
states, and for the command-line rules on '--wait' and '--timeout'.

Covers:
  - what counts as settled: RUNNING with no next status, as many Instances
    RUNNING as the target, none PENDING, STOPPING or TERMINATING (scaling up,
    scaling down, and a target of 0)
  - progress printed only when a Compute Requirement's picture changes
  - several Compute Requirements waited for together, each read afresh
  - the timeout, raised with what is still missing; no limit by default
  - a failure reading a Compute Requirement raised as it is
  - '--wait' refused with '--follow', on yd-resize for a Worker Pool (no
    '-C', nor a Compute Requirement ID), and '--timeout' without '--wait'
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from requests import ConnectionError as RequestsConnectionError
from yellowdog_client.model import ComputeRequirementStatus, InstanceStatus

from yellowdog_cli.utils import capacity_wait
from yellowdog_cli.utils.args import CLIParser
from yellowdog_cli.utils.capacity_wait import (
    CapacityWaitTimeout,
    capacity_of,
    wait_for_capacity,
)
from yellowdog_cli.utils.context import RunContext

CR_ID = "ydid:compreq:d9c548:98879b5a-9192-4a56-ad25-fc1330e49185"
WP_ID = "ydid:wrkrpool:d9c548:1f020696-ae9a-4786-bed2-c31b484b1d4f"
CR_ID_2 = "ydid:compreq:d9c548:11111111-2222-3333-4444-555555555555"

RUNNING = ComputeRequirementStatus.RUNNING
PROVISIONING = ComputeRequirementStatus.PROVISIONING


def _cr(name="cr-a", status=RUNNING, next_status=None, target=1) -> Any:
    return SimpleNamespace(
        namespace="ns",
        name=name,
        status=status,
        nextStatus=next_status,
        targetInstanceCount=target,
    )


def _instances(*statuses: InstanceStatus) -> list[Any]:
    return [SimpleNamespace(status=status) for status in statuses]


class FakePlatform:
    """
    Each Compute Requirement's states, one per poll: (cr, instances). The
    last state is repeated once the script runs out; 'reads' counts polls.
    """

    def __init__(self, scripts: dict[str, list[tuple[Any, list[Any]]]]):
        self.scripts = scripts
        self.reads: dict[str, int] = dict.fromkeys(scripts, 0)
        self.failure: Exception | None = None
        client = MagicMock()
        client.compute_client.get_compute_requirement_by_id.side_effect = self._cr
        client.compute_client.get_instances.side_effect = self._instances
        self.client = client

    def _state(self, cr_id: str) -> tuple[Any, list[Any]]:
        script = self.scripts[cr_id]
        return script[min(self.reads[cr_id], len(script) - 1)]

    def _cr(self, cr_id: str) -> Any:
        if self.failure is not None:
            raise self.failure
        return self._state(cr_id)[0]

    def _instances(self, search) -> Any:
        cr_id = search.computeRequirementId
        instances = self._state(cr_id)[1]
        self.reads[cr_id] += 1
        return SimpleNamespace(list_all=lambda: instances)


@pytest.fixture
def clock(monkeypatch):
    """
    A clock that sleeping advances, so a wait takes no real time.
    """
    now = SimpleNamespace(t=0.0, sleeps=[])

    def sleep(seconds):
        now.sleeps.append(seconds)
        now.t += seconds

    monkeypatch.setattr(capacity_wait.time, "monotonic", lambda: now.t)
    monkeypatch.setattr(capacity_wait.time, "sleep", sleep)
    return now


@pytest.fixture
def printed(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(capacity_wait, "print_info", lines.append)
    return lines


def _wait(platform: FakePlatform, cr_ids: list[str], timeout: int | None = None):
    wait_for_capacity(
        RunContext(args=SimpleNamespace(), config=None, client=platform.client),
        cr_ids,
        timeout,
    )


# ---------------------------------------------------------------------------
# What counts as settled
# ---------------------------------------------------------------------------


class TestSettled:
    def test_running_at_target(self):
        assert capacity_of(
            _cr(target=2), _instances(*[InstanceStatus.RUNNING] * 2)
        ).settled

    def test_terminated_instances_do_not_count(self):
        capacity = capacity_of(
            _cr(target=1), _instances(InstanceStatus.RUNNING, InstanceStatus.TERMINATED)
        )
        assert capacity.settled

    @pytest.mark.parametrize(
        "cr, instances",
        [
            (_cr(target=2), _instances(InstanceStatus.RUNNING)),  # short
            (_cr(target=1), _instances(InstanceStatus.RUNNING, InstanceStatus.RUNNING)),
            (_cr(target=1), _instances(InstanceStatus.RUNNING, InstanceStatus.PENDING)),
            (
                _cr(target=1),
                _instances(InstanceStatus.RUNNING, InstanceStatus.TERMINATING),
            ),
            (_cr(status=PROVISIONING), _instances(InstanceStatus.RUNNING)),
            (_cr(next_status=RUNNING), _instances(InstanceStatus.RUNNING)),
        ],
    )
    def test_not_yet(self, cr, instances):
        assert not capacity_of(cr, instances).settled

    def test_a_target_of_zero(self):
        assert capacity_of(_cr(target=0), _instances(InstanceStatus.TERMINATED)).settled
        assert not capacity_of(
            _cr(target=0), _instances(InstanceStatus.TERMINATING)
        ).settled

    def test_the_description(self):
        capacity = capacity_of(
            _cr(status=PROVISIONING, target=2),
            _instances(InstanceStatus.RUNNING, InstanceStatus.PENDING),
        )
        assert capacity.describe() == (
            "1 of 2 Instance(s) running, 1 pending (PROVISIONING)"
        )


# ---------------------------------------------------------------------------
# Waiting
# ---------------------------------------------------------------------------


class TestWaiting:
    def test_scaling_up_waits_for_the_new_instance(self, clock, printed):
        platform = FakePlatform(
            {
                CR_ID: [
                    (
                        _cr(status=PROVISIONING, target=2),
                        _instances(InstanceStatus.RUNNING),
                    ),
                    (
                        _cr(status=PROVISIONING, target=2),
                        _instances(InstanceStatus.RUNNING, InstanceStatus.PENDING),
                    ),
                    (
                        _cr(status=PROVISIONING, target=2),
                        _instances(InstanceStatus.RUNNING, InstanceStatus.PENDING),
                    ),
                    (_cr(target=2), _instances(*[InstanceStatus.RUNNING] * 2)),
                ]
            }
        )
        _wait(platform, [CR_ID])
        assert platform.reads[CR_ID] == 4
        # One line per change, none for the unchanged third poll
        assert printed[1:] == [
            "Compute Requirement 'ns/cr-a': 1 of 2 Instance(s) running (PROVISIONING)",
            "Compute Requirement 'ns/cr-a': 1 of 2 Instance(s) running, 1 pending"
            " (PROVISIONING)",
            "Compute Requirement 'ns/cr-a': 2 of 2 Instance(s) running",
        ]

    def test_scaling_down_waits_for_the_surplus_to_go(self, clock, printed):
        platform = FakePlatform(
            {
                CR_ID: [
                    (_cr(target=1), _instances(*[InstanceStatus.RUNNING] * 2)),
                    (
                        _cr(target=1),
                        _instances(InstanceStatus.RUNNING, InstanceStatus.TERMINATING),
                    ),
                    (
                        _cr(target=1),
                        _instances(InstanceStatus.RUNNING, InstanceStatus.TERMINATED),
                    ),
                ]
            }
        )
        _wait(platform, [CR_ID])
        assert platform.reads[CR_ID] == 3

    def test_already_settled_returns_at_once(self, clock, printed):
        platform = FakePlatform({CR_ID: [(_cr(), _instances(InstanceStatus.RUNNING))]})
        _wait(platform, [CR_ID])
        assert clock.sleeps == []
        assert (
            printed[-1] == "Compute Requirement 'ns/cr-a': 1 of 1 Instance(s) running"
        )

    def test_several_are_waited_for_together(self, clock, printed):
        platform = FakePlatform(
            {
                CR_ID: [(_cr(), _instances(InstanceStatus.RUNNING))],
                CR_ID_2: [
                    (_cr("cr-b"), _instances(InstanceStatus.PENDING)),
                    (_cr("cr-b"), _instances(InstanceStatus.RUNNING)),
                ],
            }
        )
        _wait(platform, [CR_ID, CR_ID_2, CR_ID])
        # The settled one is not read again; a repeated ID is waited for once
        assert platform.reads == {CR_ID: 1, CR_ID_2: 2}
        assert "2 Compute Requirement(s)" in printed[0]

    def test_no_limit_by_default(self, clock, printed):
        script = [(_cr(target=2), _instances(InstanceStatus.RUNNING))] * 100 + [
            (_cr(target=2), _instances(*[InstanceStatus.RUNNING] * 2))
        ]
        platform = FakePlatform({CR_ID: script})
        _wait(platform, [CR_ID])
        assert platform.reads[CR_ID] == 101

    def test_the_timeout_says_what_is_missing(self, clock, printed):
        platform = FakePlatform(
            {CR_ID: [(_cr(target=2), _instances(InstanceStatus.RUNNING))]}
        )
        with pytest.raises(CapacityWaitTimeout) as raised:
            _wait(platform, [CR_ID], timeout=12)
        assert str(raised.value) == (
            "Timed out after 12s waiting for Compute Requirement(s) to reach their"
            " target instance counts: 'ns/cr-a' 1 of 2 Instance(s) running"
        )
        assert clock.t == 12  # the last sleep cut short to the deadline

    def test_a_failure_is_raised_as_it_is(self, clock, printed):
        platform = FakePlatform({CR_ID: [(_cr(), _instances())]})
        platform.failure = RequestsConnectionError("reset")
        with pytest.raises(RequestsConnectionError):
            _wait(platform, [CR_ID])


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


class TestCommandLine:
    def _parse(self, name: str, argv: list[str]):
        """
        The arguments as parsed, the command's validators run.
        """
        return CLIParser(name, argv).args

    @pytest.mark.parametrize(
        "name, argv",
        [
            ("yd-resize", ["-C", "cr-a", "2", "--wait", "--timeout", "60"]),
            ("yd-resize", [CR_ID, "2", "--wait"]),
            ("yd-compute-reprovision", ["cr-a", "-w"]),
        ],
    )
    def test_accepted(self, name, argv):
        assert self._parse(name, argv).wait

    @pytest.mark.parametrize(
        "name, argv, words",
        [
            ("yd-resize", ["wp-a", "2", "--wait"], "--compute-requirement"),
            ("yd-resize", [WP_ID, "2", "--wait"], "--compute-requirement"),
            ("yd-resize", ["-C", "cr-a", "2", "-w", "-f"], "--follow"),
            ("yd-compute-reprovision", ["-w", "-f"], "--follow"),
            ("yd-resize", ["-C", "cr-a", "2", "--timeout", "60"], "only with --wait"),
            ("yd-compute-reprovision", ["--timeout", "60"], "only with --wait"),
        ],
    )
    def test_refused(self, capsys, name, argv, words):
        with pytest.raises(SystemExit) as raised:
            self._parse(name, argv)
        assert raised.value.code == 2
        assert words in capsys.readouterr().err
