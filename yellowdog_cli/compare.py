#!/usr/bin/env python3

"""
A script to compare work requirements and task groups with provisioned worker pools,
and to check for matches.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from functools import cache

from tabulate import tabulate
from yellowdog_client.model import (
    ComputeRequirement,
    ComputeSource,
    DoubleRange,
    Node,
    NodeSearch,
    NodeStatus,
    ProvisionedWorkerPool,
    TaskGroup,
    WorkerPool,
    WorkRequirement,
)

from yellowdog_cli.utils.entity_utils import get_task_group_by_id, get_worker_pool_by_id
from yellowdog_cli.utils.exit_codes import (
    SESSION_FAILURES,
    NotFoundError,
    ReportedFailure,
    classify,
)
from yellowdog_cli.utils.misc_utils import is_http_not_found
from yellowdog_cli.utils.printing import indent, print_error, print_info, print_warning
from yellowdog_cli.utils.results import json_requested, record, rows_as_objects
from yellowdog_cli.utils.tables import print_table_core
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, main_wrapper
from yellowdog_cli.utils.ydid_utils import (
    YDIDType,
    get_ydid_type,
)

NONE_STRING = "NONE"
EMPTY_STRING = ""
UNKNOWN_STRING = "NOT CURRENTLY KNOWN"

AWS = "AWS"
AZURE = "AZURE"
GOOGLE = "GOOGLE"
OCI = "OCI"
UNKNOWN_PROVIDER = "UNKNOWN"

# A compute source's provider by the start of its type's class name, for a
# source whose 'provider' the Platform has not filled in
_PROVIDER_BY_TYPE_PREFIX = (
    ("aws", AWS),
    ("azure", AZURE),
    ("gce", GOOGLE),
    ("oci", OCI),
)

# The compute source properties naming an instance type, one per provider
# (the Simulator's is 'instanceType', as AWS's is)
_INSTANCE_TYPE_PROPERTIES = ("instanceType", "vmSize", "machineType", "shape")


class MatchType(Enum):
    YES = "YES"  # Definite match to the worker pool (so far)
    NO = "NO"  # Definite non-match to the worker pool
    MAYBE = "MAYBE (no Nodes available)"  # Possible match to the worker pool; no nodes available


@dataclass
class PropertyMatch:
    property_name: str
    task_group_values: str
    worker_pool_values: str
    match: MatchType


# The detailed report table's headings
DETAIL_HEADINGS = [
    "Property",
    "Task Group Run Specification",
    "Worker Pool",
    "Match Status",
]


def _joined(values: Iterable[str] | None) -> str:
    """
    A Task Group's list of values for display, sorted: empty when there is
    none, which is no constraint.
    """
    return ", ".join(sorted(values)) if values else EMPTY_STRING


def _joined_or_none(values: Iterable[str]) -> str:
    """
    A Worker Pool's values for display, sorted: NONE when it has none.
    """
    return ", ".join(sorted(values)) or NONE_STRING


class MatchReport:
    """
    Class to contain and report on whether a worker pool
    matches a task group.
    """

    def __init__(
        self,
        worker_pool_name: str,
        worker_pool_id: str,
        worker_pool_status: str,
        worker_tags: PropertyMatch,
        task_types: PropertyMatch,
        instance_types: PropertyMatch,
        providers: PropertyMatch,
        regions: PropertyMatch,
        namespaces: PropertyMatch,
        ram: PropertyMatch,
        vcpus: PropertyMatch,
    ):
        self.worker_pool_name = worker_pool_name
        self.worker_pool_id = worker_pool_id
        self.worker_pool_status = worker_pool_status
        self._property_match_list = [
            instance_types,
            namespaces,
            providers,
            ram,
            regions,
            task_types,
            vcpus,
            worker_tags,
        ]

    def summary(self) -> MatchType:
        """
        Summarise the overall match status for the worker pool: NO if any
        property fails to match, else MAYBE if any can't yet be checked,
        else YES.
        """
        matches = {p.match for p in self._property_match_list}
        if MatchType.NO in matches:
            return MatchType.NO
        if MatchType.MAYBE in matches:
            return MatchType.MAYBE
        return MatchType.YES

    def detail_rows(self) -> list[list[str]]:
        """
        The rows of the detailed report's table, one per property compared.
        """
        return [
            [
                p.property_name,
                p.task_group_values,
                p.worker_pool_values,
                p.match.value,
            ]
            for p in self._property_match_list
        ]

    def print_detailed_report(self):
        """
        Print a detailed matching report for the worker pool.
        """
        summary = self.summary()
        if summary == MatchType.YES:
            match_str = "MATCHING"
        elif summary == MatchType.MAYBE:
            match_str = "MAYBE MATCHING"
        else:
            match_str = "NON-MATCHING"
        print_info(
            f"Detailed comparison report for {match_str} ({self.worker_pool_status}) Worker Pool "
            f"'{self.worker_pool_name}' ({self.worker_pool_id})",
            override_quiet=True,
        )

        # Print table
        print_table_core(
            indent(
                tabulate(
                    self.detail_rows(),
                    headers=DETAIL_HEADINGS,
                    tablefmt="simple_outline",
                ),
                indent_width=4,
            )
        )


# The summary table's match column for a Worker Pool that could not be compared
FAILED_STRING = "FAILED"


@dataclass
class FailedComparison:
    """
    A Worker Pool that could not be compared with a Task Group (its Compute
    Requirement or Nodes could not be fetched): reported in its place, and
    the comparison of the others carried on.
    """

    worker_pool_name: str
    worker_pool_id: str
    worker_pool_status: str
    error: Exception


class WorkerPools:
    """
    Class to contain the worker pools to be compared, and to check them for
    matches. Each pool's Compute Requirement and Nodes are fetched once per
    run, however many Task Groups are compared with it.
    """

    def __init__(self, worker_pools: list[ProvisionedWorkerPool]):
        self._worker_pools = worker_pools

    def check_task_group_for_matching_worker_pools(
        self, task_group: TaskGroup
    ) -> list[MatchReport | FailedComparison]:
        """
        Check a task group for matches with the selected worker pools. A pool
        that cannot be compared is a FailedComparison in its place; a
        failure every later request would repeat (authentication, the
        connection) is raised.
        """
        results: list[MatchReport | FailedComparison] = []
        for worker_pool in self._worker_pools:
            try:
                results.append(
                    self._check_worker_pool_for_match(worker_pool, task_group)
                )
            except Exception as e:
                if classify(e) in SESSION_FAILURES:
                    raise
                results.append(
                    FailedComparison(
                        worker_pool_name=worker_pool.name or "",
                        worker_pool_id=worker_pool.id or "",
                        worker_pool_status=str(worker_pool.status),
                        error=e,
                    )
                )
        return results

    def _check_worker_pool_for_match(
        self, worker_pool: ProvisionedWorkerPool, task_group: TaskGroup
    ) -> MatchReport:
        """
        Check a worker pool against the requirements of
        a task group.
        """
        return MatchReport(
            worker_pool_name=worker_pool.name or "",
            worker_pool_id=worker_pool.id or "",
            worker_pool_status=str(worker_pool.status),
            namespaces=self._match_namespaces(task_group, worker_pool),
            worker_tags=self._match_worker_tags(task_group, worker_pool),
            instance_types=self._match_instance_types(task_group, worker_pool),
            task_types=self._match_task_types(task_group, worker_pool),
            providers=self._match_providers(task_group, worker_pool),
            regions=self._match_regions(task_group, worker_pool),
            ram=self._match_ram(task_group, worker_pool),
            vcpus=self._match_vcpus(task_group, worker_pool),
        )

    def _get_sources(self, worker_pool: ProvisionedWorkerPool) -> list[ComputeSource]:
        """
        The compute sources of the worker pool's compute requirement.
        """
        if not worker_pool.computeRequirementId:
            raise RuntimeError(
                f"Worker Pool '{worker_pool.name}' ({worker_pool.id}) has no "
                "Compute Requirement"
            )
        compute_requirement = self._get_compute_requirement(
            worker_pool.computeRequirementId
        )
        return compute_requirement.provisionStrategy.sources or []

    def _get_providers(self, worker_pool: ProvisionedWorkerPool) -> set[str]:
        return {
            self._get_provider_from_source(source)
            for source in self._get_sources(worker_pool)
        }

    def _get_regions(self, worker_pool: ProvisionedWorkerPool) -> set[str]:
        return {
            source.region
            for source in self._get_sources(worker_pool)
            if source.region is not None
        }

    def _get_instance_types(self, worker_pool: ProvisionedWorkerPool) -> set[str]:
        instance_types: set[str] = set()
        for source in self._get_sources(worker_pool):
            for property_name in _INSTANCE_TYPE_PROPERTIES:
                if (instance_type := getattr(source, property_name, None)) is not None:
                    instance_types.add(instance_type)
            # An AWS Fleet source's overrides each name a further type
            for override in getattr(source, "instanceOverrides", None) or []:
                if override.instanceType is not None:
                    instance_types.add(override.instanceType)
        return instance_types

    @staticmethod
    @cache
    def _get_compute_requirement(cr_id: str) -> ComputeRequirement:
        return CLIENT.compute_client.get_compute_requirement_by_id(cr_id)

    @staticmethod
    def _get_provider_from_source(source: ComputeSource) -> str:
        """
        The source's provider: as the Platform reports it, else from the
        source's type, else UNKNOWN_PROVIDER, which no Task Group's provider
        list matches.
        """
        provider = getattr(source, "provider", None)
        if provider is not None:
            return str(getattr(provider, "value", provider))
        type_name = (source.type or "").rsplit(".", 1)[-1].lower()
        for prefix, name in _PROVIDER_BY_TYPE_PREFIX:
            if type_name.startswith(prefix):
                return name
        return UNKNOWN_PROVIDER

    @staticmethod
    def _match_worker_tags(
        task_group: TaskGroup, worker_pool: ProvisionedWorkerPool
    ) -> PropertyMatch:
        runspec_worker_tags = task_group.runSpecification.workerTags
        worker_tag = (
            None if worker_pool.properties is None else worker_pool.properties.workerTag
        )
        return PropertyMatch(
            property_name="Worker Tag(s)",
            task_group_values=_joined(runspec_worker_tags),
            worker_pool_values=EMPTY_STRING if worker_tag is None else worker_tag,
            # Any single workerTag in the list can match; none is no
            # constraint
            match=(
                MatchType.YES
                if not runspec_worker_tags or worker_tag in runspec_worker_tags
                else MatchType.NO
            ),
        )

    def _match_instance_types(
        self, task_group: TaskGroup, worker_pool: ProvisionedWorkerPool
    ) -> PropertyMatch:
        runspec_instance_types = set(task_group.runSpecification.instanceTypes or [])
        worker_pool_instance_types = self._get_instance_types(worker_pool)

        # Calculate match: the instance types in the worker pool must be
        # a subset of those in the run specification
        if (
            not runspec_instance_types
            or worker_pool_instance_types <= runspec_instance_types
        ):
            match_type = MatchType.YES
        else:
            match_type = MatchType.NO

        return PropertyMatch(
            property_name="Instance Type(s)",
            task_group_values=_joined(runspec_instance_types),
            worker_pool_values=_joined_or_none(worker_pool_instance_types),
            match=match_type,
        )

    def _match_task_types(
        self, task_group: TaskGroup, worker_pool: ProvisionedWorkerPool
    ) -> PropertyMatch:
        runspec_task_types = set(task_group.runSpecification.taskTypes or [])
        node = self._node_reporting_task_types(worker_pool)
        node_task_types = (
            set()
            if node is None or node.details is None
            else set(node.details.supportedTaskTypes or [])
        )

        # Calculate match: the task types in the worker pool must include
        # all of those in the run specification. The scheduler calculates
        # this based on what the first node reports, but we have to take
        # a node that possibly is not the first.
        if not runspec_task_types:
            match_type = MatchType.YES
        elif node is None:
            match_type = MatchType.MAYBE
        elif runspec_task_types <= node_task_types:
            match_type = MatchType.YES
        else:
            match_type = MatchType.NO

        return PropertyMatch(
            property_name="Task Type(s)",
            task_group_values=_joined(runspec_task_types),
            worker_pool_values=(
                UNKNOWN_STRING if node is None else _joined_or_none(node_task_types)
            ),
            match=match_type,
        )

    def _match_providers(
        self, task_group: TaskGroup, worker_pool: ProvisionedWorkerPool
    ) -> PropertyMatch:
        runspec_providers = {
            provider.value for provider in task_group.runSpecification.providers or []
        }
        worker_pool_providers = self._get_providers(worker_pool)

        # Calculate match: the providers in the worker pool must be
        # a subset of those in the run specification
        if not runspec_providers or worker_pool_providers <= runspec_providers:
            match_type = MatchType.YES
        else:
            match_type = MatchType.NO

        return PropertyMatch(
            property_name="Provider(s)",
            task_group_values=_joined(runspec_providers),
            worker_pool_values=_joined_or_none(worker_pool_providers),
            match=match_type,
        )

    def _match_regions(
        self, task_group: TaskGroup, worker_pool: ProvisionedWorkerPool
    ) -> PropertyMatch:
        runspec_regions = set(task_group.runSpecification.regions or [])
        worker_pool_regions = self._get_regions(worker_pool)

        # Calculate match: the regions in the worker pool must be
        # a subset of those in the run specification
        if not runspec_regions or worker_pool_regions <= runspec_regions:
            match_type = MatchType.YES
        else:
            match_type = MatchType.NO

        return PropertyMatch(
            property_name="Region(s)",
            task_group_values=_joined(runspec_regions),
            worker_pool_values=_joined_or_none(worker_pool_regions),
            match=match_type,
        )

    @staticmethod
    def _match_namespaces(
        task_group: TaskGroup, worker_pool: ProvisionedWorkerPool
    ) -> PropertyMatch:
        runspec_namespaces = task_group.runSpecification.namespaces
        return PropertyMatch(
            property_name="Namespace(s)",
            task_group_values=_joined(runspec_namespaces),
            worker_pool_values=(
                EMPTY_STRING if worker_pool.namespace is None else worker_pool.namespace
            ),
            # Any single namespace in the list can match; none is no
            # constraint
            match=(
                MatchType.YES
                if not runspec_namespaces or worker_pool.namespace in runspec_namespaces
                else MatchType.NO
            ),
        )

    def _match_ram(
        self, task_group: TaskGroup, worker_pool: ProvisionedWorkerPool
    ) -> PropertyMatch:
        return self._match_range(
            "RAM (GB)",
            task_group.runSpecification.ram,
            [
                node.details.ram
                for node in self._nodes_reporting_details(worker_pool)
                if node.details is not None
            ],
        )

    def _match_vcpus(
        self, task_group: TaskGroup, worker_pool: ProvisionedWorkerPool
    ) -> PropertyMatch:
        return self._match_range(
            "vCPUs Count",
            task_group.runSpecification.vcpus,
            [
                node.details.vcpus
                for node in self._nodes_reporting_details(worker_pool)
                if node.details is not None
            ],
        )

    def _match_range(
        self,
        property_name: str,
        range_: DoubleRange | None,
        node_values: list[float | None],
    ) -> PropertyMatch:
        """
        Match a ranged property against the value each Node with details
        reports: YES if there is no range or every Node is within it, NO if
        any Node is not, MAYBE if no Node has reported yet.
        """
        if range_ is None:
            match_type = MatchType.YES
        elif not node_values:
            match_type = MatchType.MAYBE
        elif all(self._check_in_range(value, range_) for value in node_values):
            match_type = MatchType.YES
        else:
            # If ANY nodes fail to match, the worker
            # pool is not considered a match
            match_type = MatchType.NO

        return PropertyMatch(
            property_name=property_name,
            task_group_values=(
                EMPTY_STRING if range_ is None else self._doublerange_str(range_)
            ),
            worker_pool_values=(
                UNKNOWN_STRING if not node_values else self._values_str(node_values)
            ),
            match=match_type,
        )

    @staticmethod
    def _values_str(values: list[float | None]) -> str:
        """
        The distinct values the Nodes report, in ascending order, with NONE
        for a Node reporting none.
        """
        shown = [str(value) for value in sorted({v for v in values if v is not None})]
        if None in values:
            shown.append(NONE_STRING)
        return ", ".join(shown)

    @staticmethod
    def _check_in_range(value: float | None, range_: DoubleRange) -> bool:
        """
        Check whether a value is within a DoubleRange. An unset (None) bound is
        treated as unbounded on that side, supporting one-sided constraints.
        """
        if value is None:
            return False
        if range_.min is not None and value < range_.min:
            return False
        if range_.max is not None and value > range_.max:
            return False
        return True

    @staticmethod
    def _doublerange_str(dr: DoubleRange) -> str:
        """
        Convert a DoubleRange into a tidy string. An unset (None) bound is shown
        as an open-ended one-sided constraint.
        """
        if dr.min is None and dr.max is None:
            return "any"
        if dr.min is None:
            return f"up to {dr.max}"
        if dr.max is None:
            return f"{dr.min} or more"
        if dr.min == dr.max:
            return str(dr.min)
        return f"{dr.min} to {dr.max}"

    def _nodes_reporting_details(self, worker_pool: WorkerPool) -> list[Node]:
        """
        The worker pool's nodes that have reported their details: a node
        that has registered but not yet reported them can't be compared, and
        is left out rather than counted as a non-match.
        """
        return [
            node
            for node in self._get_all_nodes_in_worker_pool(worker_pool)
            if node.details is not None
        ]

    def _node_reporting_task_types(self, worker_pool: WorkerPool) -> Node | None:
        """
        The node whose task types stand for the worker pool's, as the
        scheduler takes the first node's: the first RUNNING node with
        details, else the first node with details, else None.
        """
        nodes = self._nodes_reporting_details(worker_pool)
        running = [node for node in nodes if node.status == NodeStatus.RUNNING]
        return (running or nodes or [None])[0]

    def _get_all_nodes_in_worker_pool(self, worker_pool: WorkerPool) -> list[Node]:
        """
        Return all nodes in the worker pool. Optionally restrict to running nodes only.
        """
        nodes = self._get_all_nodes_in_worker_pool_cached(worker_pool.id)
        return (
            [node for node in nodes if node.status == NodeStatus.RUNNING]
            if ARGS_PARSER.running_nodes_only
            else nodes
        )

    @staticmethod
    @cache
    def _get_all_nodes_in_worker_pool_cached(worker_pool_id: str) -> list[Node]:
        """
        Cached version of the above with hashable argument.
        """
        try:
            return CLIENT.worker_pool_client.get_nodes(
                search=NodeSearch(worker_pool_id)
            ).list_all()
        except Exception as e:
            raise RuntimeError(f"Unable to get details of nodes: {e}") from e


def _get_work_requirement_by_id(work_requirement_id: str) -> WorkRequirement:
    try:
        return CLIENT.work_client.get_work_requirement_by_id(work_requirement_id)
    except Exception as e:
        if is_http_not_found(e):
            raise NotFoundError(
                f"Work Requirement ID '{work_requirement_id}' not found"
            ) from e
        raise RuntimeError(
            f"Unable to obtain Work Requirement details for '{work_requirement_id}': {e}"
        ) from e


def _get_task_group_by_id(task_group_id: str) -> TaskGroup:
    try:
        return get_task_group_by_id(CLIENT, task_group_id)
    except Exception as e:
        if is_http_not_found(e):
            raise NotFoundError(f"Task Group ID '{task_group_id}' not found") from e
        raise


def _get_provisioned_worker_pool_by_id(worker_pool_id: str) -> ProvisionedWorkerPool:
    try:
        worker_pool = get_worker_pool_by_id(CLIENT, worker_pool_id)
    except Exception as e:
        if is_http_not_found(e):
            raise NotFoundError(f"Worker Pool ID '{worker_pool_id}' not found") from e
        raise RuntimeError(
            f"Unable to obtain Worker Pool details for '{worker_pool_id}': {e}"
        ) from e

    if isinstance(worker_pool, ProvisionedWorkerPool):
        return worker_pool
    else:
        raise TypeError(
            f"Worker Pool ID '{worker_pool_id}' is not a Provisioned Worker Pool; "
            "Configured Worker Pools are not supported by 'yd-compare'"
        )


# The summary table's headings; the first, unheaded, column numbers the rows
SUMMARY_HEADINGS = [
    "",
    "Worker Pool Name",
    "Status",
    "Worker Pool ID",
    "Worker Pool Match?",
]


def _summary_row(index: int, match_report: MatchReport | FailedComparison) -> list:
    return [
        index + 1,
        match_report.worker_pool_name,
        match_report.worker_pool_status,
        match_report.worker_pool_id,
        (
            FAILED_STRING
            if isinstance(match_report, FailedComparison)
            else match_report.summary().value
        ),
    ]


def _failure_message(failure: FailedComparison) -> str:
    return (
        f"Unable to compare Worker Pool '{failure.worker_pool_name}'"
        f" ({failure.worker_pool_id}): {failure.error}"
    )


def _record_comparison(
    task_group: TaskGroup, match_reports: list[MatchReport | FailedComparison]
):
    """
    Record, for '--json', one object per Worker Pool compared with the Task
    Group: the Task Group, the summary table's row for the Worker Pool, and
    its detailed report's rows under "properties", each keyed by its table's
    headings in lowerCamelCase. A Worker Pool that could not be compared
    has FAILED as its match, its "error", and no "properties".
    """
    for index, match_report in enumerate(match_reports):
        (summary,) = rows_as_objects(
            SUMMARY_HEADINGS, [_summary_row(index, match_report)]
        )
        item = {
            "taskGroupName": task_group.name,
            "taskGroupId": task_group.id,
            **summary,
        }
        if isinstance(match_report, FailedComparison):
            item["error"] = str(match_report.error)
            item["properties"] = []
        else:
            item["properties"] = rows_as_objects(
                DETAIL_HEADINGS, match_report.detail_rows()
            )
        record(item)


def _compare_task_group(
    task_group: TaskGroup, worker_pools: WorkerPools
) -> list[Exception]:
    """
    Compare a Task Group; return the failures of the Worker Pools that could
    not be compared with it, each reported.
    """
    print_info(
        f"Comparing Task Group '{task_group.name}' ({task_group.id})",
        # Printed despite '--quiet', but not into '--json' output
        override_quiet=not json_requested(),
    )

    match_reports = worker_pools.check_task_group_for_matching_worker_pools(
        task_group=task_group
    )
    failures = [
        report for report in match_reports if isinstance(report, FailedComparison)
    ]

    if json_requested():
        # The tables, and the messages printed alongside them despite
        # '--quiet', are the result, which '--json' prints instead; a
        # failure's message goes to stderr, with its record
        _record_comparison(task_group, match_reports)
        for failure in failures:
            print_error(_failure_message(failure))
        return [failure.error for failure in failures]

    if len(match_reports) > 1:
        # Summary report
        print_info("Summary of Worker Pool matches:", override_quiet=True)
        table_rows = [
            _summary_row(index, match_report)
            for index, match_report in enumerate(match_reports)
        ]
        print_table_core(
            indent(
                tabulate(
                    table_rows, headers=SUMMARY_HEADINGS, tablefmt="simple_outline"
                ),
                indent_width=4,
            ),
        )

    # Detailed reports
    for match_report in match_reports:
        if isinstance(match_report, FailedComparison):
            print_error(_failure_message(match_report))
        else:
            match_report.print_detailed_report()

    print_info("Task Group comparison complete")
    return [failure.error for failure in failures]


@main_wrapper
def main():
    # The IDs' types are checked as the command line is parsed
    # ('check_compare_ids' in the command registry)
    worker_pool_ids: list[str] = ARGS_PARSER.worker_pool_ids or []
    for wp_id in {i for i in worker_pool_ids if worker_pool_ids.count(i) > 1}:
        print_warning(f"Worker Pool ID '{wp_id}' was given more than once")
    worker_pools = WorkerPools(
        [
            _get_provisioned_worker_pool_by_id(wp_id)
            for wp_id in dict.fromkeys(worker_pool_ids)
        ]
    )

    wr_or_tg_id: str = ARGS_PARSER.wr_or_tg_id or ""

    failures: list[Exception] = []

    # Task group
    if (ydid_type := get_ydid_type(wr_or_tg_id)) == YDIDType.TASK_GROUP:
        failures += _compare_task_group(
            _get_task_group_by_id(wr_or_tg_id), worker_pools
        )

    # Work requirement
    elif ydid_type == YDIDType.WORK_REQUIREMENT:
        work_requirement = _get_work_requirement_by_id(wr_or_tg_id)
        print_info(
            f"Comparing all Task Groups in Work Requirement '{work_requirement.name}' "
            f"({work_requirement.id})",
            # Printed despite '--quiet', but not into '--json' output
            override_quiet=not json_requested(),
        )
        if not work_requirement.taskGroups:
            print_warning(
                f"Work Requirement '{work_requirement.name}' ({work_requirement.id})"
                " has no Task Groups to compare"
            )
        for task_group in work_requirement.taskGroups or []:
            failures += _compare_task_group(task_group, worker_pools)

    else:
        raise ValueError(
            f"Not a YellowDog Work Requirement or Task Group ID: '{wr_or_tg_id}'"
        )

    if failures:
        message = f"{len(failures)} comparison(s) could not be made"
        print_error(message)
        codes = {classify(e) for e in failures}
        # The shared cause's exit code, or FAILURE for different causes
        raise ReportedFailure(failures[0] if len(codes) == 1 else RuntimeError(message))


# Entry point
if __name__ == "__main__":
    main()
