#!/usr/bin/env python3

"""
yd status: the Work Requirements, Worker Pools and Compute Requirements in
the namespace and tag, on one screen, the active alone with
'--active-only'. Each section lists what 'yd list' lists for its type, with
the same option (utils/active_entities.py), in the 'yd list' tables less
their Namespace and Tag columns, which the scope line above them names,
with a total beneath; a closing warning counts what is unhealthy. A search that fails is said in its section and
the others are still shown, the command then exiting with that failure's
code; an authentication or connection failure stops it at once. '--json'
prints one document holding the three lists and the failures.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from yellowdog_cli.utils.active_entities import (
    compute_requirements,
    work_requirements,
    worker_pools,
)
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    ET_COMPUTE_REQUIREMENTS,
    ET_WORK_REQUIREMENTS,
    ET_WORKER_POOLS,
)
from yellowdog_cli.utils.entity_utils import filter_phrase, namespace_scope
from yellowdog_cli.utils.exit_codes import (
    SESSION_FAILURES,
    ReportedFailure,
    classify,
)
from yellowdog_cli.utils.printing import (
    counted,
    objects_as_json,
    plural,
    print_error,
    print_info,
    print_json,
    print_warning,
)
from yellowdog_cli.utils.tables import (
    compute_requirement_table,
    print_table,
    sorted_objects,
    work_requirement_table,
    worker_pool_table,
)
from yellowdog_cli.utils.wrapper import main_wrapper

# The columns the scope line names, left out of every section's table
_SCOPE_COLUMNS = frozenset({"Namespace", "Tag"})


@dataclass
class _Section:
    """
    One kind of thing shown: how it is found, tabulated and totalled, and
    once searched, what was found or why nothing could be.
    """

    entity_type: str
    name: str
    search: Callable[[Any, str | None, str | None, bool], list]
    table: Callable[[list], tuple[list[str], list[list]]]
    total: Callable[[list], str]
    items: list = field(default_factory=list)
    failure: Exception | None = None


@main_wrapper
def main(ctx: RunContext):
    show_status(ctx)


def show_status(ctx: RunContext) -> None:
    """
    Search for each kind of thing, then show the sections or print the
    document, raising the failure of any search once everything is shown.
    """
    namespace, tag = ctx.config.namespace, ctx.config.name_tag
    sections = [
        _Section(
            ET_WORK_REQUIREMENTS,
            "Work Requirement",
            work_requirements,
            work_requirement_table,
            _work_requirements_total,
        ),
        _Section(
            ET_WORKER_POOLS,
            "Worker Pool",
            worker_pools,
            worker_pool_table,
            _worker_pools_total,
        ),
        _Section(
            ET_COMPUTE_REQUIREMENTS,
            "Compute Requirement",
            compute_requirements,
            compute_requirement_table,
            _compute_requirements_total,
        ),
    ]
    active_only = bool(ctx.args.active_only)
    for section in sections:
        _search(ctx, section, namespace, tag, active_only)

    if ctx.args.json_output:
        _print_document(sections, namespace, tag)
    else:
        print_info(
            f"{'Active items' if active_only else 'Items'}"
            f" {namespace_scope(ctx.client, namespace)}"
            + filter_phrase("with tags including '{}'", tag)
        )
        for section in sections:
            _print_section(section, active_only)
        _warn_of_unhealthy(sections)

    failures = [s.failure for s in sections if s.failure is not None]
    if failures:
        raise ReportedFailure(_shared_cause(failures))


def _search(
    ctx: RunContext,
    section: _Section,
    namespace: str | None,
    tag: str | None,
    active_only: bool,
) -> None:
    """
    Fill a section in, keeping a failure for it to show unless it ends the
    session, which is raised: the other searches would fail the same way.
    """
    try:
        section.items = sorted_objects(
            section.search(ctx.client, namespace, tag, active_only)
        )
    except Exception as e:
        if classify(e) in SESSION_FAILURES:
            raise
        section.failure = e


def _print_section(section: _Section, active_only: bool) -> None:
    print_info(f"{plural(section.name, 2)}:")
    if section.failure is not None:
        print_error(f"Cannot list {plural(section.name, 2)}: {section.failure}")
        return
    if not section.items:
        print_info(f"No {'active ' if active_only else ''}{plural(section.name, 2)}")
        return
    headers, rows = section.table(section.items)
    print_table(*_without_scope_columns(headers, rows))
    print_info(section.total(section.items))


def _without_scope_columns(
    headers: list[str], rows: list[list]
) -> tuple[list[str], list[list]]:
    kept = [i for i, header in enumerate(headers) if header not in _SCOPE_COLUMNS]
    return [headers[i] for i in kept], [[row[i] for i in kept] for row in rows]


def _sum(items: Sequence[Any], attribute: str) -> tuple[int, bool]:
    """
    The sum of an attribute over the items, and whether every item had it:
    the Platform leaves a count null where it does not know it.
    """
    values = [getattr(item, attribute, None) for item in items]
    return sum(v for v in values if v is not None), None not in values


def _unknown(*known: bool) -> str:
    return "" if all(known) else " (some counts unknown)"


def _work_requirements_total(items: list) -> str:
    done, done_known = _sum(items, "completedTaskCount")
    total, total_known = _sum(items, "totalTaskCount")
    return (
        f"{counted(len(items), 'Work Requirement')}:"
        f" {done:,} of {counted(total, 'Task')} done"
        + _unknown(done_known, total_known)
    )


def _worker_pools_total(items: list) -> str:
    nodes, nodes_known = _sum(items, "registeredNodeCount")
    claimed, claimed_known = _sum(items, "claimedWorkerCount")
    workers, workers_known = _sum(items, "registeredWorkerCount")
    return (
        f"{counted(len(items), 'Worker Pool')}: {counted(nodes, 'Node')},"
        f" {claimed:,} of {counted(workers, 'Worker')} claimed"
        + _unknown(nodes_known, claimed_known, workers_known)
    )


def _compute_requirements_total(items: list) -> str:
    alive, alive_known = _sum(items, "aliveInstanceCount")
    expected, expected_known = _sum(items, "expectedInstanceCount")
    return (
        f"{counted(len(items), 'Compute Requirement')}:"
        f" {alive:,} of {counted(expected, 'Instance')} alive"
        + _unknown(alive_known, expected_known)
    )


def _warn_of_unhealthy(sections: list[_Section]) -> None:
    """
    One warning counting the unhealthy items of each kind, if any are.
    """
    parts = [
        counted(unhealthy, section.name)
        for section in sections
        if (
            unhealthy := sum(
                1 for i in section.items if getattr(i, "healthy", None) is False
            )
        )
    ]
    if not parts:
        return
    listed = (
        parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    )
    print_warning(f"{listed} unhealthy")


def _print_document(
    sections: list[_Section], namespace: str | None, tag: str | None
) -> None:
    keys = {
        ET_WORK_REQUIREMENTS: "workRequirements",
        ET_WORKER_POOLS: "workerPools",
        ET_COMPUTE_REQUIREMENTS: "computeRequirements",
    }
    document: dict[str, Any] = {"namespace": namespace, "tag": tag}
    for section in sections:
        document[keys[section.entity_type]] = objects_as_json(section.items)
    document["failures"] = [
        {"type": section.entity_type, "error": str(section.failure)}
        for section in sections
        if section.failure is not None
    ]
    print_json(document)


def _shared_cause(failures: list[Exception]) -> Exception:
    """
    The failure the exit code comes from: the one, or the first of several
    sharing a code, else a failure with no code of its own.
    """
    if len({classify(f) for f in failures}) == 1:
        return failures[0]
    return RuntimeError("searches failed for different reasons")


if __name__ == "__main__":
    main()
