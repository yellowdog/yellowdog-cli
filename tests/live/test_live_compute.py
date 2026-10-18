"""
Polling the run's compute, offline: each helper over canned 'yd' answers,
with a clock that advances one poll per sleep.
"""

import pytest
from harness import compute
from harness.compute import ComputeTimeout
from live_fake_yd import FakeYd, result

NS, RUN, POOL, CR = "ns", "ydst-2610130811-ab12", "ydid:wrkrpool:1", "ydid:cmpreq:1"


class Clock:
    """
    A clock whose sleep advances it, so a wait runs out without waiting.
    """

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _timing(clock: Clock) -> dict:
    return {"clock": clock, "sleep": clock.sleep, "poll_seconds": 60}


def _node(pool: str, status: str, instance: str, workers=("SLEEPING",)) -> dict:
    return {
        "workerPoolId": pool,
        "status": status,
        "details": {"instanceId": instance},
        "workers": [{"status": w} for w in workers],
    }


def test_wait_for_returns_once_the_probe_holds():
    answers = iter([(False, "one"), (False, "two"), (True, "three")])
    clock = Clock()
    compute.wait_for("it", lambda: next(answers), 10, **_timing(clock))
    assert clock.now == 120


def test_wait_for_names_what_it_last_saw_when_time_is_up():
    clock = Clock()
    with pytest.raises(
        ComputeTimeout, match=r"it: not reached after 2 minutes; last seen: still"
    ):
        compute.wait_for("it", lambda: (False, "still"), 2, **_timing(clock))


def test_a_worker_counts_only_on_a_running_node_of_the_pool():
    listed = [
        _node("ydid:wrkrpool:other", "RUNNING", "i-1"),
        _node(POOL, "RUNNING", "i-2", workers=()),
        _node(POOL, "RUNNING", "i-3"),
    ]
    yd = FakeYd(lambda args: result(args, document=listed))
    compute.wait_for_worker(yd, NS, RUN, POOL, 1, **_timing(Clock()))
    assert yd.calls[0][:6] == ("list", "nodes", "--namespace", NS, "--tag", RUN)


def test_a_worker_on_a_named_instance_must_be_on_that_instance():
    listed = [_node(POOL, "RUNNING", "i-3")]
    yd = FakeYd(lambda args: result(args, document=listed))
    with pytest.raises(ComputeTimeout):
        compute.wait_for_worker(
            yd, NS, RUN, POOL, 1, instance_id="i-9", **_timing(Clock())
        )


def test_a_worker_wait_that_times_out_carries_the_diagnostics():
    def respond(args):
        if args[:2] == ("list", "nodes"):
            return result(args, document=[])
        return result(args, document={"report": f"report for {args[-2]}"})

    yd = FakeYd(respond)
    with pytest.raises(ComputeTimeout) as raised:
        compute.wait_for_worker(yd, NS, RUN, POOL, 1, cr_id=CR, **_timing(Clock()))
    message = str(raised.value)
    assert "--show-source-report" in message and "--show-exhaustion" in message
    assert ("cr", "show", CR, "--show-source-report", "--quiet") in yd.calls


def test_instances_are_those_of_the_requirement_with_their_statuses():
    def respond(args):
        if "--ids-only" in args:
            stdout = f"{CR}.i-1\n{CR}.i-2\nydid:cmpreq:2.i-3\n"
            return compute_result(args, stdout)
        return result(
            args,
            document=[
                {"id": {"instanceId": "i-1"}, "status": "RUNNING"},
                {"id": {"instanceId": "i-2"}, "status": "PENDING"},
                {"id": {"instanceId": "i-3"}, "status": "RUNNING"},
            ],
        )

    yd = FakeYd(respond)
    assert compute.instances(yd, NS, RUN, CR) == {
        f"{CR}.i-1": "RUNNING",
        f"{CR}.i-2": "PENDING",
    }


def compute_result(args, stdout: str):
    from harness.yd import Result

    return Result(tuple(args), 0, stdout, "")


def test_an_instance_not_found_is_gone():
    yd = FakeYd(lambda args: result(args, exit_code=6))
    assert compute.instance_status(yd, f"{CR}.i-1") == compute.GONE


def test_settled_means_running_at_target_with_nothing_in_transition():
    states = iter(
        [
            (
                {"status": "RUNNING", "targetInstanceCount": 2},
                {"a": "RUNNING", "b": "PENDING"},
            ),
            (
                {"status": "RUNNING", "targetInstanceCount": 2},
                {"a": "RUNNING", "b": "RUNNING"},
            ),
        ]
    )
    current = {}

    def respond(args):
        if args[:2] == ("cr", "show"):
            current["cr"], current["instances"] = next(states)
            return result(args, document=current["cr"])
        if "--ids-only" in args:
            return compute_result(
                args, "".join(f"{CR}.{k}\n" for k in current["instances"])
            )
        return result(
            args,
            document=[
                {"id": {"instanceId": k}, "status": v}
                for k, v in current["instances"].items()
            ],
        )

    settled = compute.wait_until_settled(
        FakeYd(respond), NS, RUN, CR, 5, **_timing(Clock())
    )
    assert settled == {f"{CR}.a": "RUNNING", f"{CR}.b": "RUNNING"}


def test_a_yd_failure_while_polling_is_raised_not_waited_out():
    yd = FakeYd(lambda args: result(args, exit_code=1))
    with pytest.raises(AssertionError, match="exited 1"):
        compute.wait_for_requirement(
            yd, CR, frozenset({"TERMINATED"}), 5, **_timing(Clock())
        )


def test_waiting_for_workers_counts_live_workers_on_running_nodes():
    listed = [
        _node(POOL, "RUNNING", "i-1", workers=("SLEEPING", "DOING_TASK")),
        _node(POOL, "RUNNING", "i-2", workers=("SLEEPING", "LOST")),
        _node(POOL, "LATE", "i-3", workers=("SLEEPING",)),
    ]
    yd = FakeYd(lambda args: result(args, document=listed))
    compute.wait_for_workers(yd, NS, RUN, POOL, 3, 1, **_timing(Clock()))
    with pytest.raises(ComputeTimeout, match="4 Workers"):
        compute.wait_for_workers(yd, NS, RUN, POOL, 4, 1, **_timing(Clock()))


def test_a_worker_wait_can_ask_for_a_new_worker():
    node = _node(POOL, "RUNNING", "i-3")
    node["workers"][0]["id"] = "w-old"
    yd = FakeYd(lambda args: result(args, document=[node]))
    with pytest.raises(ComputeTimeout):
        compute.wait_for_worker(
            yd,
            NS,
            RUN,
            POOL,
            1,
            instance_id="i-3",
            excluding=frozenset({"w-old"}),
            **_timing(Clock()),
        )
    compute.wait_for_worker(yd, NS, RUN, POOL, 1, instance_id="i-3", **_timing(Clock()))
