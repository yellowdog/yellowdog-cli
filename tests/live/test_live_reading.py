"""
Live: reading the run's own objects, by 'yd list' and 'yd show' and by the
resource noun's 'list' and 'show'; and reading with [common] readTimeout set,
and set to 0 (no limit), as the SDK client and the CLI's own requests take it.
"""

import pytest

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst-reading")]


def test_yd_list_and_show_find_the_runs_source_templates(live_run):
    run, yd = live_run.run, live_run.yd
    listed = yd(
        "list",
        "compute-source-templates",
        "--namespace",
        run.namespace,
        "--name",
        f"{run.run_id}-*",
        "--json",
        "--quiet",
    ).records
    names = {r["name"] for r in listed}
    assert run.source_template(run.config.primary) in names
    shown = yd("show", listed[0]["id"], "--quiet").document
    assert shown["id"] == listed[0]["id"]


def test_resource_list_and_show_find_the_runs_keyring(live_run):
    run, yd = live_run.run, live_run.yd
    listed = yd(
        "resource",
        "list",
        "keyrings",
        "--namespace",
        "",
        "--name",
        run.keyring,
        "--json",
        "--quiet",
    ).records
    assert [r["name"] for r in listed] == [run.keyring]
    shown = yd("resource", "show", listed[0]["id"], "--quiet").document
    assert shown["name"] == run.keyring


def test_resource_list_finds_the_runs_requirement_templates(live_run):
    run, yd = live_run.run, live_run.yd
    listed = yd(
        "resource",
        "list",
        "compute-requirement-templates",
        "--namespace",
        run.namespace,
        "--name",
        f"{run.run_id}-*",
        "--json",
        "--quiet",
    ).records
    assert run.requirement_template(run.config.primary) in {r["name"] for r in listed}


@pytest.mark.parametrize("seconds", ["30", "0"])
def test_a_read_timeout_set_or_switched_off_still_reads(live_run, seconds):
    run, yd = live_run.run, live_run.yd
    listed = yd(
        "resource",
        "list",
        "keyrings",
        "--namespace",
        "",
        "--name",
        run.keyring,
        "--property",
        f"common.readTimeout={seconds}",
        "--json",
        "--quiet",
    ).records
    assert [keyring["name"] for keyring in listed] == [run.keyring]
