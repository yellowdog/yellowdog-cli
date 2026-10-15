"""
The failure tests' limited Application: one Group with 'work-viewer' in
LIMITED_NAMESPACE alone, and an Application in it, made by
specs/limited-app.jsonnet. Its key and secret are read from the creation's
records and registered with the runner as secrets before the result is
checked, so not even a failed creation's report can show them.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from harness.lifecycle import NOT_FOUND
from harness.run import SPECS, Run
from harness.yd import Yd, YdError

LIMITED_NAMESPACE = "yd-cli-system-tests-limited"
LIMITED_SPEC = SPECS / "limited-app.jsonnet"
# What the limited Application may do: list Work Requirements in its namespace
CONTROL = ("wr", "list", "--namespace", LIMITED_NAMESPACE, "--json", "--quiet")
_SELECT = ("--yes", "--json", "--quiet")
_KEY_FIELDS = (
    ("the limited Application's key", "apiKeyId"),
    ("the limited Application's secret", "apiKeySecret"),
)


@dataclass(frozen=True)
class LimitedApp:
    """
    The limited Application and its Group; the key and secret kept out of
    the repr, which pytest shows in a failure.
    """

    group_name: str
    group_id: str
    app_name: str
    app_id: str
    key: str = field(repr=False)
    secret: str = field(repr=False)


def create_limited_app(yd: Yd, run: Run) -> LimitedApp:
    """
    Create the namespace (when missing), the Group and the Application for
    the run (whose configuration file gives the specification its run ID
    and namespace), registering the Application's key and secret with the
    runner as secrets before anything is reported.
    """
    created = yd(
        "resource",
        "create",
        *_SELECT,
        "--variable",
        f"limited_namespace={LIMITED_NAMESPACE}",
        str(LIMITED_SPEC),
        check=False,
        expect_secret=True,
    )
    try:
        records = created.records
    except ValueError:
        # Nothing can be registered as a secret, so its output is never shown
        raise YdError(
            f"creating run {run.run_id}'s limited Application failed: exit"
            f" {created.exit_code}, its output not JSON (not shown, since it"
            f" may hold the Application's secret)\n--- stderr ---\n"
            + yd.mask(created.stderr)
        ) from None
    by_type = {record.get("resource"): record for record in records}
    application = by_type.get("Application", {})
    for label, name in _KEY_FIELDS:
        if application.get(name):
            yd.add_secret(label, application[name])
    failed = [record for record in records if record.get("action") == "failed"]
    group = by_type.get("Group", {})
    if created.exit_code != 0 or failed or not application.get("apiKeySecret"):
        raise YdError(
            f"creating run {run.run_id}'s limited Application failed:\n"
            + yd.describe(created)
        )
    return LimitedApp(
        group_name=group["name"],
        group_id=group["id"],
        app_name=application["name"],
        app_id=application["id"],
        key=application["apiKeyId"],
        secret=application["apiKeySecret"],
    )


def wait_until_usable(
    limited_yd: Yd,
    bound: float = 120,
    interval: float = 10,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """
    Whether the limited Application's control call works within the bound:
    a new Application's key may take a moment to work everywhere.
    """
    deadline = clock() + bound
    while True:
        if limited_yd(*CONTROL, check=False).exit_code == 0:
            return True
        if clock() >= deadline:
            return False
        sleep(interval)


def remove_application(yd: Yd, app: LimitedApp) -> None:
    yd("resource", "remove", "--ids", app.app_id, *_SELECT, ok=(0, NOT_FOUND))


def remove_group(yd: Yd, app: LimitedApp) -> None:
    yd("resource", "remove", "--ids", app.group_id, *_SELECT, ok=(0, NOT_FOUND))
