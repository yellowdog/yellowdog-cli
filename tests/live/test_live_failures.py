"""
Live: failing on purpose. Not found, authentication, permission, connection
and timeout, each held to its exit code, a clean message, a parseable
'--json' document and no secret in the output (the harness's own check, the
limited Application's key and secret included). The cases run in order on
one worker; the revoked key is the last, since it removes the Application.
Provisions no compute.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from harness import limited, work
from harness.failures import (
    AUTHENTICATION,
    CONNECTION,
    PERMISSION,
    check_failure,
    expected,
    fake_ydid,
)
from harness.limited import LIMITED_NAMESPACE, LimitedApp
from harness.yd import Result, Yd, YdError

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst-failures")]

# Seconds: the Platform caches permissions for about 5 minutes (YEL-14547)
REVOKED_BOUND = 360
_JSON = ("--json", "--quiet")
_ACT = ("--yes", "--json", "--quiet")


@dataclass
class Limited:
    """
    The limited Application, the runner acting as it, and whether its key
    worked in time and whether it has been removed.
    """

    app: LimitedApp
    yd: Yd
    usable: bool
    removed: bool = False


@pytest.fixture(scope="module")
def stuck_wr(live_run) -> Iterator[str]:
    yd = live_run.yd
    wr_id = work.submit(yd, "stuck-wr.jsonnet")["id"]
    yield wr_id
    work.cancel_all(yd, [wr_id])


@pytest.fixture(scope="module")
def limited_app(live_run) -> Iterator[Limited]:
    run, yd = live_run.run, live_run.yd
    app = limited.create_limited_app(yd, run)
    state = Limited(app, yd.with_credentials(app.key, app.secret), usable=False)
    problems: list[str] = []
    try:
        state.usable = limited.wait_until_usable(state.yd)
        yield state
    finally:
        removals = [limited.remove_group]
        if not state.removed:
            removals.insert(0, limited.remove_application)
        for remove in removals:
            try:
                remove(yd, app)
            except YdError as error:
                problems.append(str(error))
    if problems:
        pytest.fail("removing the limited Application:\n" + "\n".join(problems))


@pytest.fixture
def as_limited(limited_app) -> Yd:
    if not limited_app.usable:
        pytest.skip(
            "the limited Application's key did not start working within 2 minutes"
        )
    return limited_app.yd


@pytest.fixture
def wrong_secret(limited_app) -> Yd:
    return limited_app.yd.with_credentials(
        limited_app.app.key, "wrong-secret-" + "0" * 24
    )


def _fails(
    yd: Yd, case: str, exit_code: int, phrase: str | None, *args: str, **kwargs
) -> Result:
    """
    Run a case's command, made to fail, and hold it to the failure expected:
    the defaults given, or the case's pin.
    """
    code, phrase = expected(case, exit_code, phrase)
    result = yd(*args, check=False, ok=(code,), expected_failure=True, **kwargs)
    check_failure(yd, result, code, phrase)
    return result


def _platform(live_run) -> tuple[str, str]:
    platform = live_run.run.config.platform
    return platform["key"], platform["secret"]


# Not found


def test_not_found_wr_show(live_run, stuck_wr):
    missing = fake_ydid(stuck_wr, "workreq")
    _fails(
        live_run.yd,
        "not-found-wr-show",
        6,
        missing,
        "wr",
        "show",
        missing,
        "--quiet",
    )


def test_not_found_cr_show(live_run, stuck_wr):
    missing = fake_ydid(stuck_wr, "compreq")
    _fails(
        live_run.yd,
        "not-found-cr-show",
        6,
        missing,
        "cr",
        "show",
        missing,
        "--quiet",
    )


def test_not_found_wr_cancel_by_name(live_run):
    name = live_run.run.name("no-such-wr")
    result = _fails(
        live_run.yd,
        "not-found-wr-cancel-by-name",
        6,
        name,
        "wr",
        "cancel",
        name,
        *_ACT,
    )
    assert all(r.get("outcome") != "cancelled" for r in result.records)


def test_not_found_resource_remove(live_run, stuck_wr):
    missing = fake_ydid(stuck_wr, "keyring")
    _fails(
        live_run.yd,
        "not-found-resource-remove",
        6,
        missing,
        "resource",
        "remove",
        "--ids",
        missing,
        *_ACT,
    )


def test_not_found_one_of_two_shown(live_run, stuck_wr):
    missing = fake_ydid(stuck_wr, "workreq")
    result = _fails(
        live_run.yd,
        "not-found-one-of-two-shown",
        6,
        missing,
        "wr",
        "show",
        stuck_wr,
        missing,
        "--quiet",
    )
    assert [r["id"] for r in result.records] == [stuck_wr]


def test_not_found_within_name(live_run):
    name = live_run.run.name("no-such-wr")
    _fails(
        live_run.yd,
        "not-found-within-name",
        6,
        name,
        "task",
        "list",
        "--within",
        name,
        *_JSON,
    )


def test_not_found_within_wr_id(live_run, stuck_wr):
    missing = fake_ydid(stuck_wr, "workreq")
    _fails(
        live_run.yd,
        "not-found-within-wr-id",
        6,
        missing,
        "task",
        "list",
        "--within",
        missing,
        *_JSON,
    )


def test_not_found_within_task_group_id(live_run, stuck_wr):
    # The stuck Work Requirement's, by a number none of its Task Groups has
    missing = stuck_wr.replace("ydid:workreq:", "ydid:taskgrp:") + ":99"
    _fails(
        live_run.yd,
        "not-found-within-task-group-id",
        6,
        missing,
        "task",
        "list",
        "--within",
        missing,
        *_JSON,
    )


# Authentication: the limited Application's key with a wrong secret


def test_auth_wrong_secret_read(wrong_secret):
    _fails(wrong_secret, "auth-wrong-secret-read", 4, AUTHENTICATION, *limited.CONTROL)


def test_auth_wrong_secret_action(wrong_secret, stuck_wr):
    missing = fake_ydid(stuck_wr, "workreq")
    result = _fails(
        wrong_secret,
        "auth-wrong-secret-action",
        4,
        AUTHENTICATION,
        "wr",
        "cancel",
        stuck_wr,
        missing,
        *_ACT,
    )
    first, second = result.records
    assert first["outcome"] == "failed"
    # The session failure stops the run: the rest is not attempted
    assert second["outcome"] == "skipped"
    assert second["error"].startswith("not attempted")


# Permission: the limited Application, 'work-viewer' in LIMITED_NAMESPACE alone


def test_permission_control(as_limited):
    assert as_limited(*limited.CONTROL).records == []


def test_permission_other_namespace(live_run, as_limited):
    _fails(
        as_limited,
        "permission-other-namespace",
        5,
        PERMISSION,
        "wr",
        "list",
        "--namespace",
        live_run.run.namespace,
        *_JSON,
    )


def test_permission_unscoped(as_limited):
    result = _fails(
        as_limited,
        "permission-unscoped",
        5,
        PERMISSION,
        "wr",
        "list",
        "--namespace",
        "",
        *_JSON,
    )
    # Pinned: the search reaches only the limited namespace, which is empty
    assert result.records == []


def test_permission_keyrings(as_limited):
    _fails(
        as_limited,
        "permission-keyrings",
        5,
        PERMISSION,
        "resource",
        "list",
        "keyrings",
        "--namespace",
        "",
        *_JSON,
    )


def test_permission_compute_requirements(as_limited):
    _fails(
        as_limited,
        "permission-compute-requirements",
        5,
        PERMISSION,
        "cr",
        "list",
        "--namespace",
        LIMITED_NAMESPACE,
        *_JSON,
    )


def test_permission_show_other_namespace(as_limited, stuck_wr):
    _fails(
        as_limited,
        "permission-show-other-namespace",
        5,
        PERMISSION,
        "wr",
        "show",
        stuck_wr,
        "--quiet",
    )


def test_permission_within(as_limited, stuck_wr):
    _fails(
        as_limited,
        "permission-within",
        5,
        PERMISSION,
        "task",
        "list",
        "--within",
        stuck_wr,
        *_JSON,
    )


def test_permission_create(live_run, as_limited):
    run = live_run.run
    name = run.name("limited-keyring")
    spec = run.directory / "limited-keyring.json"
    keyring = {
        "resource": "Keyring",
        "name": name,
        # Named for the run and its namespace, so teardown removes it
        "description": f"Live system tests, run {run.run_id}, namespace {run.namespace}",
    }
    spec.write_text(json.dumps([keyring]), encoding="utf-8")
    _fails(
        as_limited,
        "permission-create",
        5,
        PERMISSION,
        "resource",
        "create",
        str(spec),
        *_ACT,
    )
    found = live_run.yd(
        "resource",
        "list",
        "keyrings",
        "--namespace",
        "",
        "--name",
        name,
        *_JSON,
        ok=(0, 6),
    )
    assert found.records == [], f"the limited Application created Keyring {name}"


def test_permission_cancel(live_run, as_limited, stuck_wr):
    _fails(
        as_limited,
        "permission-cancel",
        5,
        PERMISSION,
        "wr",
        "cancel",
        stuck_wr,
        *_ACT,
    )
    status = work.work_requirement(live_run.yd, stuck_wr)["status"]
    assert status not in work.TERMINAL, (
        f"the limited Application cancelled {stuck_wr}: {status}"
    )


# Connection: the run's own key, towards addresses nothing answers


def test_connection_closed_port(live_run):
    url = "https://127.0.0.1:9"
    yd = live_run.yd.with_credentials(*_platform(live_run), url=url)
    _fails(yd, "connection-closed-port", 8, CONNECTION, "wr", "list", *_JSON)


def test_connection_unresolvable(live_run):
    # '.invalid' never resolves (RFC 2606)
    url = "https://ydst.invalid"
    yd = live_run.yd.with_credentials(*_platform(live_run), url=url)
    _fails(yd, "connection-unresolvable", 8, CONNECTION, "wr", "list", *_JSON)


# Timeout


def test_timeout_wait(live_run, stuck_wr):
    result = _fails(
        live_run.yd,
        "timeout-wait",
        1,
        None,
        "wr",
        "wait",
        stuck_wr,
        "--timeout",
        "10",
        *_JSON,
    )
    assert [(r["id"], r["succeeded"]) for r in result.records] == [(stuck_wr, False)]


def test_timeout_wait_one_missing(live_run, stuck_wr):
    missing = fake_ydid(stuck_wr, "workreq")
    result = _fails(
        live_run.yd,
        "timeout-wait-one-missing",
        1,
        None,
        "wr",
        "wait",
        stuck_wr,
        missing,
        "--timeout",
        "10",
        *_JSON,
    )
    assert [r["id"] for r in result.records] == [stuck_wr, missing]


# Last: removing the limited Application revokes its key


def test_auth_revoked(live_run, limited_app):
    if not limited_app.usable:
        pytest.skip("the limited Application's key never worked")
    limited.remove_application(live_run.yd, limited_app.app)
    limited_app.removed = True
    code, phrase = expected("auth-revoked", 4, AUTHENTICATION)
    deadline = time.monotonic() + REVOKED_BOUND
    while True:
        result = limited_app.yd(*limited.CONTROL, check=False, expected_failure=True)
        if result.exit_code == code or time.monotonic() >= deadline:
            break
        time.sleep(15)
    check_failure(limited_app.yd, result, code, phrase)
