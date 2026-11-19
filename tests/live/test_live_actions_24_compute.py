"""
Live: a standalone Compute Requirement stopped and started as a whole,
listed, shown by its name, followed in a thread while it is terminated,
waited for by ID and, terminated, by name, and found in the usage report
('yd usage') with its running and stopped hours. It
runs last of the 'ydst-actions' modules, after the actions pool has ended,
so its time never counts against the pool's idle timeouts.
"""

import pytest
from harness import compute, work

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst-actions")]

_ACT = ("--yes", "--json", "--quiet")


def test_a_requirement_is_stopped_started_followed_and_waited_for(live_run):
    run, yd = live_run.run, live_run.yd
    minutes = run.config.run["provision_timeout_minutes"]
    primary = run.config.primary
    created = yd(
        "cr",
        "instantiate",
        "--property",
        f"workerPool.templateId={run.namespace}/{run.requirement_template(primary)}",
        "--property",
        f"workerPool.name={run.actions_standalone_name()}",
        "--target",
        "1",
        "--json",
        "--quiet",
    ).document
    cr_id = created["id"]
    with work.cleaned_up(lambda: yd("cr", "terminate", cr_id, *_ACT, ok=(0, 6))):
        states = compute.wait_until_settled(
            yd, run.namespace, run.run_id, cr_id, minutes
        )
        (instance,) = [n for n, s in states.items() if s == "RUNNING"]

        yd("cr", "stop", cr_id, *_ACT)
        compute.wait_for_instance(yd, instance, frozenset({"STOPPED"}), minutes)
        yd("cr", "start", cr_id, *_ACT)
        compute.wait_for_instance(yd, instance, frozenset({"RUNNING"}), minutes)

        listed = yd(
            "cr",
            "list",
            "--namespace",
            run.namespace,
            "--tag",
            run.run_id,
            "--json",
            "--quiet",
        ).records
        assert cr_id in {r["id"] for r in listed}
        instances = yd(
            "instance",
            "list",
            "--namespace",
            run.namespace,
            "--tag",
            run.run_id,
            "--json",
            "--quiet",
        ).records
        assert instance.split(".", 1)[1] in {
            (r.get("id") or {}).get("instanceId") for r in instances
        }

        # By name, in the configured namespace
        cr_name = yd("cr", "show", cr_id, "--quiet").document["name"]
        assert yd("cr", "show", cr_name, "--quiet").document["id"] == cr_id

        followed = work.follow_alongside(
            yd,
            ("cr", "follow", cr_id),
            lambda: yd("cr", "terminate", cr_id, *_ACT),
            run.config.run["teardown_timeout_minutes"] * 60,
        )
        work.ended_with(work.follow_events(followed.stdout), {"TERMINATED"})
        (record,) = yd("cr", "wait", cr_id, "--json", "--quiet", ok=(0, 1)).records
        assert record["status"] == "TERMINATED", record
        # A terminated one is still found by its name
        (by_name,) = yd("cr", "wait", cr_name, "--json", "--quiet", ok=(0, 1)).records
        assert by_name["id"] == cr_id, by_name

        # Its one Instance ran, was stopped and started: the usage report
        # has it, by the requirement's name, with running and stopped hours
        usage = compute.requirement_usage(
            yd, run.namespace, cr_name, frozenset({"running", "stopped"}), minutes
        )
        assert usage["instances"] == 1, usage
        assert usage["hours"]["total"] >= usage["hours"]["running"], usage

        # The report fetched is kept: the same window again, without
        # '--refresh', reads it rather than fetching another
        kept = [
            yd(
                "usage",
                "--namespace",
                run.namespace,
                "--from",
                "1 day ago",
                "--json",
                "--quiet",
            ).document
            for _ in range(2)
        ]
        assert kept[0]["fetched"] == kept[1]["fetched"], kept
        assert kept[0]["groups"] == kept[1]["groups"], kept
