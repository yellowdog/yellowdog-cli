"""
Setting a run up and tearing it down.

Setup is 'yd resource create' over the namespace's specification and then
the run's (never with '--validate', which checks the schema and creates
nothing; creation warns of any violation itself). Teardown finds what a run
made by its name (an Allowance by its description) or, for compute, by the
run's tag, and stops and removes it (its Configured Worker Pools included,
which removal shuts down, the Platform keeping them; and, when asked, its
data under <namespace>/<run ID>), every step attempted whatever the one
before did, except that a run whose compute may still be alive keeps its
Keyring, without whose Credential the Platform cannot terminate it, and its
Allowance, which still caps it. The sweep uses the same teardown on every
run of its namespace older than its age guard, which is what keeps one run's
sweep away from another's live resources; a Keyring or Allowance, which are
not in a namespace, counts only when it names the sweep's.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone

from harness.run import RUN_PREFIX, SPECS, Run, run_id_of, run_started
from harness.yd import Yd, YdError

NOT_FOUND = 6  # ExitCode.NOT_FOUND: nothing matched, which teardown expects
NAMESPACE_SPEC = SPECS / "namespace.jsonnet"
# Removed in this order, each before what it refers to
REMOVAL_ORDER = (
    # Nothing refers to a Configured Worker Pool, so it goes first
    "configured-worker-pools",
    "allowances",
    "compute-requirement-templates",
    "compute-source-templates",
    "keyrings",
)
# Listed as active only, so a long-terminated one does not count
ACTIVE_TYPES = ("work-requirements", "worker-pools", "compute-requirements")
# Not in a namespace: listed with '--namespace ""'
ACCOUNT_WIDE = frozenset({"keyrings", "allowances"})
# What a run keeps while its compute may still be alive
KEPT_WHILE_COMPUTE_LIVES = ("allowances", "keyrings")
# The end of a run's Keyring's description (specs/common.jsonnet)
KEYRING_NAMESPACE = ", namespace {namespace}"
# A Configured Worker Pool's 'type' ends with this
CONFIGURED_POOL_TYPE = "ConfiguredWorkerPool"
FINISHED_POOL_STATUSES = frozenset({"SHUTDOWN", "TERMINATED"})
DISCOVERY_TYPES = (
    "configured-worker-pools",
    "compute-source-templates",
    "compute-requirement-templates",
    "keyrings",
    "allowances",
    *ACTIVE_TYPES,
)
_SELECT = ("--yes", "--json", "--quiet")


class SetupError(AssertionError):
    """
    Setting a run up failed; what it had made was removed.
    """


def setup(run: Run, yd: Yd) -> list[dict]:
    """
    Make sure the namespace exists, then create the run's resources,
    returning the creation records. On any failure, remove what was made
    and raise SetupError.
    """
    yd("resource", "create", *_SELECT, str(NAMESPACE_SPEC))
    created = yd(
        "resource",
        "create",
        *_SELECT,
        *(str(path) for path in run.spec_files()),
        check=False,
    )
    failed = [record for record in created.records if record.get("action") == "failed"]
    if created.exit_code == 0 and not failed:
        return created.records
    problems = remove_resources(yd, run.namespace, run.run_id)
    raise SetupError(
        yd.describe(created) + "".join(f"\nclean-up: {problem}" for problem in problems)
    )


def _listed(
    yd: Yd, entity_type: str, namespace: str, tag: str, *extra: str
) -> list[dict]:
    """
    'yd list' of one type, as records; nothing found is no records.
    """
    return yd(
        "list",
        entity_type,
        "--namespace",
        namespace,
        "--tag",
        tag,
        "--json",
        "--quiet",
        *extra,
        ok=(0, NOT_FOUND),
    ).records


def _scope(entity_type: str, namespace: str) -> str:
    return "" if entity_type in ACCOUNT_WIDE else namespace


def owned(yd: Yd, entity_type: str, namespace: str, run_id: str) -> list[dict]:
    """
    Every entity of the type the run made: found by its name, an Allowance
    by its description, and held to the run's ID exactly.
    """
    scope = _scope(entity_type, namespace)
    if entity_type == "allowances":
        listed = _listed(yd, entity_type, scope, "", "--details")
        return [a for a in listed if run_id_of(a.get("description") or "") == run_id]
    if entity_type == "configured-worker-pools":
        # Not active only: a shut-down one is still a resource to remove
        listed = _listed(yd, "worker-pools", namespace, "", "--name", f"{run_id}-*")
        return [
            pool
            for pool in listed
            if run_id_of(pool.get("name") or "") == run_id
            and (pool.get("type") or "").endswith(CONFIGURED_POOL_TYPE)
        ]
    active = ("--active-only",) if entity_type in ACTIVE_TYPES else ()
    listed = _listed(yd, entity_type, scope, "", "--name", f"{run_id}-*", *active)
    return [e for e in listed if run_id_of(e.get("name") or "") == run_id]


def remove_resources(
    yd: Yd, namespace: str, run_id: str, kept: Iterable[str] = ()
) -> list[str]:
    """
    Remove the run's resources in REMOVAL_ORDER, but those of the 'kept'
    types, returning the problems.
    """
    problems: list[str] = []
    for entity_type in REMOVAL_ORDER:
        if entity_type in kept:
            continue
        try:
            ids = [entity["id"] for entity in owned(yd, entity_type, namespace, run_id)]
            if not ids:
                continue
            removed = yd("resource", "remove", "--ids", *ids, *_SELECT, check=False)
            failed = [r for r in removed.records if r.get("action") == "failed"]
            if removed.exit_code != 0 or failed:
                problems.append(yd.describe(removed))
        except YdError as error:
            problems.append(str(error))
    return problems


def teardown(
    yd: Yd,
    namespace: str,
    run_id: str,
    timeout_minutes: int,
    *,
    stop_compute: bool = True,
    remove: bool = True,
    data: bool = False,
) -> list[str]:
    """
    Tear a run down: cancel its Work Requirements, shut down its Worker
    Pools and terminate its Compute Requirements, wait for them to end,
    then remove its resources. Every step is attempted whatever the one
    before did, but while its compute may still be alive (still running
    when the wait ended, or its state unknown) the run keeps its Keyring and
    Allowance. With 'data', the run's files under <namespace>/<run ID> are
    deleted with its resources. Returns the problems, none when all went well.
    """
    problems: list[str] = []
    compute_ended = True
    if stop_compute:
        selection = ("--namespace", namespace, "--tag", run_id, *_SELECT)
        for words in (
            ("wr", "cancel", "--abort"),
            ("wp", "shutdown", "--terminate"),
            ("cr", "terminate"),
        ):
            try:
                yd(*words, *selection, ok=(0, NOT_FOUND))
            except YdError as error:
                problems.append(str(error))
        try:
            _wait_for_compute(yd, namespace, run_id, timeout_minutes)
        except YdError as error:
            problems.append(str(error))
            compute_ended = False
    if remove:
        if data:
            try:
                yd(
                    "data",
                    "delete",
                    "--recursive",
                    "--yes",
                    "--json",
                    "--quiet",
                    "--no-prefix",
                    f"{namespace}/{run_id}",
                    ok=(0, NOT_FOUND),
                )
            except YdError as error:
                problems.append(str(error))
        kept = () if compute_ended else KEPT_WHILE_COMPUTE_LIVES
        problems += remove_resources(yd, namespace, run_id, kept)
        if kept:
            problems.append(
                f"kept the Keyring and Allowance of run {run_id}: its compute may"
                " still be alive, and the Platform needs its Credential to terminate"
                f" it; tear it down again with: python tests/live/sweep.py --run {run_id}"
            )
    return problems


def _wait_for_compute(
    yd: Yd, namespace: str, run_id: str, timeout_minutes: int
) -> None:
    """
    Wait for the run's Compute Requirements to end; YdError naming any that
    have not when the time is up, since those are what cost money.
    """
    alive = _listed(yd, "compute-requirements", namespace, run_id, "--active-only")
    if not alive:
        return
    yd(
        "cr",
        "wait",
        *(cr["id"] for cr in alive),
        "--timeout",
        str(timeout_minutes * 60),
        "--json",
        "--quiet",
        check=False,
    )
    still = _listed(yd, "compute-requirements", namespace, run_id, "--active-only")
    if still:
        raise YdError(
            f"Compute Requirements still alive after {timeout_minutes} minutes: "
            + ", ".join(cr["id"] for cr in still)
        )


def select_stale(
    names: Iterable[str], now: datetime, older_than: timedelta
) -> list[str]:
    """
    The run IDs among the names whose runs started more than 'older_than'
    ago; a name that is not a run's, or carries an impossible date, is left.
    """
    stale: set[str] = set()
    for name in names:
        run_id = run_id_of(name)
        if run_id is None:
            continue
        try:
            started = run_started(run_id)
        except ValueError:
            continue
        if now - started > older_than:
            stale.add(run_id)
    return sorted(stale)


def stale_runs(
    yd: Yd, namespace: str, older_than: timedelta, now: datetime | None = None
) -> list[str]:
    """
    Every run of the namespace that left something behind and started more
    than 'older_than' ago, found by the names of what it made; a Keyring or
    Allowance only when it names the namespace.
    """
    names: list[str] = []
    for entity_type in DISCOVERY_TYPES:
        scope = _scope(entity_type, namespace)
        if entity_type == "allowances":
            listed = _listed(yd, entity_type, scope, "", "--details")
            names += [
                a.get("description") or ""
                for a in listed
                if a.get("namespace") == namespace
            ]
        elif entity_type == "configured-worker-pools":
            # Unfinished ones only: removing a Worker Pool shuts it down and
            # leaves it on the Platform, so a finished one is nothing to do
            listed = _listed(
                yd,
                "worker-pools",
                namespace,
                "",
                "--name",
                f"{RUN_PREFIX}-*",
                "--active-only",
            )
            names += [
                p.get("name") or ""
                for p in listed
                if (p.get("type") or "").endswith(CONFIGURED_POOL_TYPE)
                and p.get("status") not in FINISHED_POOL_STATUSES
            ]
        elif entity_type == "keyrings":
            listed = _listed(yd, entity_type, scope, "", "--name", f"{RUN_PREFIX}-*")
            ending = KEYRING_NAMESPACE.format(namespace=namespace)
            names += [
                k.get("name") or ""
                for k in listed
                if (k.get("description") or "").endswith(ending)
            ]
        else:
            active = ("--active-only",) if entity_type in ACTIVE_TYPES else ()
            listed = _listed(
                yd, entity_type, scope, "", "--name", f"{RUN_PREFIX}-*", *active
            )
            names += [e.get("name") or "" for e in listed]
    return select_stale(names, now or datetime.now(timezone.utc), older_than)


def sweep(
    yd: Yd,
    namespace: str,
    older_than: timedelta,
    timeout_minutes: int,
    *,
    dry_run: bool = False,
    report: Callable[[str], None] = print,
    data: bool = False,
) -> list[str]:
    """
    Tear down every stale run (its data too, with 'data'), or with
    'dry_run' only say which; returns the problems.
    """
    problems: list[str] = []
    for run_id in stale_runs(yd, namespace, older_than):
        report(f"{'Would sweep' if dry_run else 'Sweeping'} run {run_id}")
        if not dry_run:
            problems += teardown(yd, namespace, run_id, timeout_minutes, data=data)
    return problems
