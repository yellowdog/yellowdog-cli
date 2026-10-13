"""
Setting a run up, tearing it down, and choosing what the sweep takes, against
a scripted 'yd'.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from harness.lifecycle import (
    REMOVAL_ORDER,
    SetupError,
    select_stale,
    setup,
    stale_runs,
    teardown,
)
from live_fake_yd import FakeYd, result

RUN = "ydst-2610121530-ab12"
OTHER = "ydst-2610121530-cd34"
NOW = datetime(2026, 10, 12, 16, 0, tzinfo=timezone.utc)


def _listing(args) -> list[dict]:
    """
    What 'yd list <type>' finds: one entity of the run's, one of another run's.
    """
    entity_type = args[1]
    if entity_type == "allowances":
        return [
            {"id": "ydid:allow:1", "description": f"{RUN}-allowance"},
            {"id": "ydid:allow:2", "description": f"{OTHER}-allowance"},
        ]
    if entity_type == "compute-requirements":
        return []
    if entity_type == "worker-pools":
        # Configured Worker Pools, removed as resources
        configured = "co.yellowdog.platform.model.ConfiguredWorkerPool"
        return [
            {
                "id": "ydid:configured-worker-pools:1",
                "name": f"{RUN}-x",
                "type": configured,
            },
            {
                "id": "ydid:configured-worker-pools:2",
                "name": f"{OTHER}-x",
                "type": configured,
            },
        ]
    return [
        {"id": f"ydid:{entity_type}:1", "name": f"{RUN}-x"},
        {"id": f"ydid:{entity_type}:2", "name": f"{OTHER}-x"},
    ]


def _quiet_platform(args):
    if args[0] == "list":
        return result(args, document=_listing(args))
    return result(args, document=[])


def test_teardown_stops_compute_then_removes_in_order():
    yd = FakeYd(_quiet_platform)
    assert teardown(yd, "ns", RUN, 15) == []
    words = yd.words()
    assert words[:3] == [("wr", "cancel"), ("wp", "shutdown"), ("cr", "terminate")]
    removed = [call for call in yd.calls if call[:2] == ("resource", "remove")]
    assert [call[3] for call in removed] == [
        f"ydid:{t}:1" if t != "allowances" else "ydid:allow:1" for t in REMOVAL_ORDER
    ]


def test_teardown_selects_compute_by_the_runs_tag():
    yd = FakeYd(_quiet_platform)
    teardown(yd, "ns", RUN, 15)
    cancel = yd.calls[0]
    assert cancel[cancel.index("--tag") + 1] == RUN
    assert cancel[cancel.index("--namespace") + 1] == "ns"


def test_teardown_never_removes_another_runs_resources():
    yd = FakeYd(_quiet_platform)
    teardown(yd, "ns", RUN, 15)
    removed = [
        word for call in yd.calls if call[:2] == ("resource", "remove") for word in call
    ]
    assert not any(word.endswith(":2") for word in removed)


def test_a_failed_step_does_not_stop_the_rest():
    def respond(args):
        if args[:2] == ("wr", "cancel"):
            return result(args, exit_code=4)
        return _quiet_platform(args)

    yd = FakeYd(respond)
    problems = teardown(yd, "ns", RUN, 15)
    assert len(problems) == 1 and "wr cancel" in problems[0]
    assert ("cr", "terminate") in yd.words()
    assert any(call[:2] == ("resource", "remove") for call in yd.calls)


def _compute_alive(args):
    if args[:2] == ("list", "compute-requirements"):
        return result(args, document=[{"id": "ydid:cr:1", "name": f"{RUN}-probe"}])
    return _quiet_platform(args)


def _removed_types(yd) -> list[str]:
    return [
        call[3].split(":")[1] for call in yd.calls if call[:2] == ("resource", "remove")
    ]


def test_compute_still_alive_is_a_problem_but_the_templates_are_still_removed():
    yd = FakeYd(_compute_alive)
    problems = teardown(yd, "ns", RUN, 15)
    assert any("still alive" in p and "ydid:cr:1" in p for p in problems)
    assert ("cr", "wait", "ydid:cr:1") in [call[:3] for call in yd.calls]
    # A Configured Worker Pool has no compute, so it goes whatever the rest does
    assert _removed_types(yd) == [
        "configured-worker-pools",
        "compute-requirement-templates",
        "compute-source-templates",
    ]


def test_compute_still_alive_keeps_the_keyring_and_allowance():
    """
    Without its Credential the Platform cannot terminate the instances, and
    the Allowance is what still caps them.
    """
    yd = FakeYd(_compute_alive)
    problems = teardown(yd, "ns", RUN, 15)
    assert "allow" not in _removed_types(yd)
    assert "keyrings" not in _removed_types(yd)
    assert any("kept the Keyring and Allowance" in p for p in problems)


def test_compute_whose_state_is_unknown_keeps_the_keyring_too():
    def respond(args):
        if args[:2] == ("list", "compute-requirements"):
            return result(args, exit_code=4)
        return _quiet_platform(args)

    yd = FakeYd(respond)
    teardown(yd, "ns", RUN, 15)
    assert "keyrings" not in _removed_types(yd)


def test_nothing_found_to_cancel_is_not_a_problem():
    def respond(args):
        if args[0] in ("wr", "wp", "cr"):
            return result(args, exit_code=6)
        return _quiet_platform(args)

    assert teardown(FakeYd(respond), "ns", RUN, 15) == []


def test_keeping_compute_and_resources_skips_those_steps():
    yd = FakeYd(_quiet_platform)
    teardown(yd, "ns", RUN, 15, stop_compute=False, remove=False)
    assert yd.calls == []


def test_a_failed_removal_is_a_problem():
    def respond(args):
        if args[:2] == ("resource", "remove"):
            return result(
                args, document=[{"id": args[3], "action": "failed", "error": "in use"}]
            )
        return _quiet_platform(args)

    problems = teardown(FakeYd(respond), "ns", RUN, 15)
    assert len(problems) == len(REMOVAL_ORDER)


def _run():
    return SimpleNamespace(
        run_id=RUN, namespace="ns", spec_files=lambda: ["/specs/common.jsonnet"]
    )


def test_setup_creates_the_namespace_then_the_runs_resources():
    yd = FakeYd(lambda args: result(args, document=[{"action": "created"}]))
    records = setup(_run(), yd)
    assert records == [{"action": "created"}]
    first, second = yd.calls
    assert first[-1].endswith("namespace.jsonnet")
    # Not '--validate', which checks the schema and creates nothing
    assert second[:2] == ("resource", "create") and "--validate" not in second
    assert second[-1] == "/specs/common.jsonnet"


def test_a_failed_setup_removes_what_was_made_and_raises():
    def respond(args):
        if args[:2] == ("resource", "create") and args[-1].endswith("common.jsonnet"):
            return result(
                args,
                exit_code=1,
                document=[{"action": "created"}, {"action": "failed"}],
            )
        return _quiet_platform(args)

    yd = FakeYd(respond)
    with pytest.raises(SetupError):
        setup(_run(), yd)
    assert any(call[:2] == ("resource", "remove") for call in yd.calls)


def test_select_stale_takes_old_runs_only():
    old = "ydst-2610101200-aaaa"
    young = "ydst-2610121500-bbbb"
    names = [
        f"{old}-keyring",
        f"{old}-aws-static",
        f"{young}-keyring",
        "ydst-other",
        "mine",
    ]
    assert select_stale(names, NOW, timedelta(hours=24)) == [old]


def test_select_stale_ignores_a_name_with_an_impossible_date():
    assert select_stale(["ydst-2613991200-aaaa-x"], NOW, timedelta(0)) == []


def _account_wide(namespace: str):
    """
    A Platform holding an old run's Keyring and Allowance, of 'namespace'.
    """
    old = "ydst-2610101200-aaaa"

    def respond(args):
        if args[:2] == ("list", "allowances"):
            return result(
                args,
                document=[
                    {
                        "id": "a",
                        "description": f"{old}-allowance",
                        "namespace": namespace,
                    }
                ],
            )
        if args[:2] == ("list", "keyrings"):
            return result(
                args,
                document=[
                    {
                        "id": "k",
                        "name": f"{old}-keyring",
                        "description": f"Live system tests, run {old}, namespace {namespace}",
                    }
                ],
            )
        return result(args, document=[])

    return old, respond


def test_stale_runs_leaves_another_namespaces_keyring_and_allowance():
    _, respond = _account_wide("someone-elses")
    assert stale_runs(FakeYd(respond), "ns", timedelta(hours=24), NOW) == []


def test_stale_runs_takes_this_namespaces_keyring_and_allowance():
    old, respond = _account_wide("ns")
    assert stale_runs(FakeYd(respond), "ns", timedelta(hours=24), NOW) == [old]


def test_stale_runs_looks_everywhere_a_run_leaves_things():
    old = "ydst-2610101200-aaaa"

    def respond(args):
        if args[:2] == ("list", "allowances"):
            return result(
                args,
                document=[
                    {"id": "a", "description": f"{old}-allowance", "namespace": "ns"}
                ],
            )
        return result(args, document=[])

    yd = FakeYd(respond)
    assert stale_runs(yd, "ns", timedelta(hours=24), NOW) == [old]
    listed = {call[1] for call in yd.calls}
    assert {
        "keyrings",
        "allowances",
        "compute-source-templates",
        "compute-requirement-templates",
        "work-requirements",
        "worker-pools",
        "compute-requirements",
    } <= listed


def test_teardown_deletes_the_runs_data_when_asked():
    yd = FakeYd(lambda args: result(args, document=[]))
    teardown(yd, "ns", RUN, 1, data=True)
    deletes = [c for c in yd.calls if c[:2] == ("data", "delete")]
    assert deletes == [
        (
            "data",
            "delete",
            "--recursive",
            "--yes",
            "--json",
            "--quiet",
            "--no-prefix",
            f"ns/{RUN}",
        )
    ]


def test_teardown_leaves_data_alone_unless_asked():
    yd = FakeYd(lambda args: result(args, document=[]))
    teardown(yd, "ns", RUN, 1)
    assert not [c for c in yd.calls if c[:2] == ("data", "delete")]


def test_a_kept_run_keeps_its_data():
    yd = FakeYd(lambda args: result(args, document=[]))
    teardown(yd, "ns", RUN, 1, remove=False, data=True)
    assert not [c for c in yd.calls if c[:2] == ("data", "delete")]


def test_a_failed_data_deletion_is_a_problem_and_the_rest_still_runs():
    def respond(args):
        return result(
            args, exit_code=1 if args[:2] == ("data", "delete") else 0, document=[]
        )

    yd = FakeYd(respond)
    problems = teardown(yd, "ns", RUN, 1, data=True)
    assert any("data delete" in p for p in problems)


CONFIGURED = "co.yellowdog.platform.model.ConfiguredWorkerPool"
PROVISIONED = "co.yellowdog.platform.model.ProvisionedWorkerPool"


def _pools(*pools):
    def respond(args):
        if args[:2] == ("list", "worker-pools"):
            # As the CLI does: '--active-only' leaves out finished pools
            active = "--active-only" in args
            return result(
                args,
                document=[
                    p
                    for p in pools
                    if not active or p["status"] not in ("SHUTDOWN", "TERMINATED")
                ],
            )
        return result(args, document=[])

    return respond


def test_only_configured_pools_are_removed_as_resources():
    yd = FakeYd(
        _pools(
            {
                "id": "wp-c",
                "name": f"{RUN}-configured-pool",
                "type": CONFIGURED,
                "status": "IDLE",
            },
            {
                "id": "wp-p",
                "name": f"{RUN}-aws-pool",
                "type": PROVISIONED,
                "status": "RUNNING",
            },
        )
    )
    teardown(yd, "ns", RUN, 1)
    removed = [c for c in yd.calls if c[:2] == ("resource", "remove")]
    assert any("wp-c" in c for c in removed)
    assert not any("wp-p" in c for c in removed)


def test_a_shut_down_configured_pool_is_removed():
    yd = FakeYd(
        _pools(
            {
                "id": "wp-c",
                "name": f"{RUN}-configured-pool",
                "type": CONFIGURED,
                "status": "SHUTDOWN",
            }
        )
    )
    teardown(yd, "ns", RUN, 1)
    listing = [
        c for c in yd.calls if c[:2] == ("list", "worker-pools") and "--name" in c
    ]
    assert listing and all("--active-only" not in c for c in listing)
    assert any("wp-c" in c for c in yd.calls if c[:2] == ("resource", "remove"))


def test_an_unfinished_configured_pool_counts_toward_a_stale_run():
    yd = FakeYd(
        _pools(
            {
                "id": "wp-c",
                "name": f"{RUN}-configured-pool",
                "type": CONFIGURED,
                "status": "IDLE",
            }
        )
    )
    # The run started 30 minutes before NOW
    assert stale_runs(yd, "ns", timedelta(minutes=10), now=NOW) == [RUN]


def test_a_shut_down_configured_pool_does_not_make_a_run_stale():
    # Removing a Worker Pool only shuts it down: it stays on the Platform, so a
    # finished one counted would make every past run stale for ever
    yd = FakeYd(
        _pools(
            {
                "id": "wp-c",
                "name": f"{RUN}-configured-pool",
                "type": CONFIGURED,
                "status": "SHUTDOWN",
            }
        )
    )
    assert stale_runs(yd, "ns", timedelta(minutes=10), now=NOW) == []
