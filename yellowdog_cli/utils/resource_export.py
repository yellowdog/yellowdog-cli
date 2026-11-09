"""
The engine of 'yd resource export': which types an export covers, and the
export itself, which writes the specifications as a JSON array.

Each chosen type's exporter (utils/resource_exporters.py) finds its resources
and writes each out; with '--with-dependencies' the resources they refer to
are found and written too. Everything is read before anything is written, so
a failure that stops the run (SESSION_FAILURES) leaves no file and prints no
array; any other failure is reported, the resource left out, the rest
written, and the run raises ReportedFailure with the first failure's code, as
utils/resource_plan.py's plan_resources() does.
"""

import glob
import json
import logging
import sys
from collections.abc import Callable
from contextlib import redirect_stdout
from dataclasses import dataclass
from functools import partial
from typing import Literal, TypeVar

from yellowdog_cli.utils import interactive
from yellowdog_cli.utils.atomic_write import write_text_atomically
from yellowdog_cli.utils.compact_json import CompactJSONEncoder
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import ET_CREDENTIALS
from yellowdog_cli.utils.exit_codes import (
    SESSION_FAILURES,
    ExitCode,
    ReportedFailure,
    classify,
)
from yellowdog_cli.utils.jsonnet_style import is_jsonnet_path, jsonnet_style
from yellowdog_cli.utils.load_resources import RESOURCE_CREATION_ORDER
from yellowdog_cli.utils.noun_registry import EXPORT_TYPES
from yellowdog_cli.utils.output_settings import OUTPUT
from yellowdog_cli.utils.output_style import JSON_INDENT
from yellowdog_cli.utils.printing import (
    counted,
    print_error,
    print_info,
    print_json_text,
    print_warning,
)
from yellowdog_cli.utils.property_names import PROP_RESOURCE
from yellowdog_cli.utils.resource_exporters import (
    ALL_TYPES,
    DEFAULT_TYPES,
    EXPORTERS,
    Exported,
    Exporter,
    Found,
    Reference,
    Selection,
    literal_for_jsonnet,
)
from yellowdog_cli.utils.resource_plan import RESOURCE_TYPE_NAMES
from yellowdog_cli.utils.results import record_resource
from yellowdog_cli.utils.settings import NAMESPACE_PREFIX_SEPARATOR

_LOG = logging.getLogger(__name__)

_T = TypeVar("_T")


@dataclass(frozen=True)
class ExportOptions:
    """
    What 'yd resource export' was asked for.
    """

    types: tuple[str, ...]  # as given, prefixes resolved; () for the default
    all_types: bool = False
    name_glob: str | None = None
    interactive: bool = False
    with_dependencies: bool = False
    include_credentials: bool = False
    output_file: str | None = None


def chosen_types(options: ExportOptions) -> tuple[str, ...]:
    """
    The types an export covers, in EXPORT_TYPES order, each once: those
    given, else every type but Credentials with --all, else the default
    types; Credentials too with --include-credentials.
    """
    if options.types:
        wanted = set(options.types)
    elif options.all_types:
        wanted = set(ALL_TYPES)
    else:
        wanted = set(DEFAULT_TYPES)
    if options.include_credentials:
        wanted.add(ET_CREDENTIALS)
    return tuple(t for t in EXPORT_TYPES if t in wanted)


@dataclass(frozen=True)
class ExportRecord:
    """
    What happened to one resource: exported, or skipped for a failure.
    """

    resource_type: str  # an RN_* name; the type word for a failed search
    name: str | None  # None for a failed search, which names no resource
    outcome: Literal["exported", "skipped"]
    reason: str | None = None  # 'a dependency of <name>', or the failure


@dataclass
class _Export:
    """
    One export as it is read: the resources written out, keyed by type word
    and name, a record per resource, the failures kept, and where notes go.
    """

    warn: Callable[[str], None]
    exported: dict[tuple[str, str], tuple[Found, Exported]]
    records: list[ExportRecord]
    failures: list[Exception]

    def attempt(
        self, read: Callable[[], _T], action: str, failed: ExportRecord
    ) -> _T | None:
        """
        read(), or None for a failure, reported, recorded 'skipped' with
        its message and kept; a SESSION_FAILURES failure is raised, since
        every later request would fail the same way.
        """
        try:
            return read()
        except Exception as e:
            if classify(e) in SESSION_FAILURES:
                raise
            _LOG.debug("Failed to %s", action, exc_info=True)
            print_error(f"Failed to {action}: {e}")
            self.records.append(
                ExportRecord(failed.resource_type, failed.name, "skipped", str(e))
            )
            self.failures.append(e)
            return None


def export_specifications(
    ctx: RunContext,
    options: ExportOptions,
    warn: Callable[[str], None] | None = None,
) -> tuple[list[dict], list[ExportRecord]]:
    """
    The specifications of the resources the export covers, in creation
    order then by name, and a record for each resource. A SESSION_FAILURES
    failure is raised at once; any other is reported and recorded
    'skipped', the rest still read. Each exporter's note is given to 'warn'
    (a warning on stderr by default).
    """
    specifications, records, _ = _read(ctx, options, warn or _warning)
    return specifications, records


def export_resources(ctx: RunContext, options: ExportOptions) -> None:
    """
    Write the resources as specifications, a JSON array (in the Jsonnet
    style for a '.jsonnet' file): to the output file, else alone to standard
    output. Everything is read before anything is written. A failure other
    than a session failure leaves its resource out and, once the rest is
    written, raises ReportedFailure with the first failure's code.
    """
    _refuse_an_empty_namespace(ctx, options)
    # Warnings still go to stderr when stdout is the array, unless asked not to
    show_warnings = not OUTPUT.quiet
    if options.output_file is None:
        # Standard output is the array alone
        OUTPUT.quiet = True

    def warn(message: str) -> None:
        print_warning(message, override_quiet=show_warnings, stderr=True)

    if not options.types and not options.all_types:
        account_wide = [
            t for t in ALL_TYPES if t in EXPORTERS and not EXPORTERS[t].namespaced
        ]
        if account_wide:
            warn(
                "Account-wide resources are not exported by default"
                f" ({', '.join(account_wide)}): name their types, or give '--all'"
            )

    specifications, records, failures = _read(ctx, options, warn)
    if not specifications:
        warn("No resources to export")

    jsonnet = options.output_file is not None and is_jsonnet_path(options.output_file)
    text = json.dumps(
        literal_for_jsonnet(specifications) if jsonnet else specifications,
        indent=JSON_INDENT,
        cls=CompactJSONEncoder,
        ensure_ascii=False,
    )
    if options.output_file is None:
        print_json_text(text + "\n")
    else:
        if jsonnet:
            text = jsonnet_style(text)
        write_text_atomically(options.output_file, text + "\n")
        print_info(
            f"Exported {counted(len(specifications), 'resource')}"
            f" to '{options.output_file}'"
        )
        for export_record in records:
            record_resource(
                export_record.resource_type,
                export_record.name,
                None,
                export_record.outcome,
                **({"reason": export_record.reason} if export_record.reason else {}),
            )

    if failures:
        raise ReportedFailure(failures[0])


def _refuse_an_empty_namespace(ctx: RunContext, options: ExportOptions) -> None:
    """
    Exit as a configuration error if a namespaced type is to be exported and
    the configured namespace is empty (a 'namespace = ""' or an empty
    YD_NAMESPACE; '-n' is refused as parsed), which would search every
    namespace and keep none, exporting nothing without saying why.
    """
    if ctx.config.namespace != "":
        return
    namespaced = [
        t for t in chosen_types(options) if t in EXPORTERS and EXPORTERS[t].namespaced
    ]
    if namespaced:
        print_error(
            "The configured namespace is empty: set one to export"
            f" {', '.join(namespaced)}"
        )
        sys.exit(ExitCode.CONFIGURATION)


def _read(
    ctx: RunContext, options: ExportOptions, warn: Callable[[str], None]
) -> tuple[list[dict], list[ExportRecord], list[Exception]]:
    """
    The specifications in order, the records, and the failures kept.
    """
    export = _Export(warn=warn, exported={}, records=[], failures=[])
    pending: list[tuple[str, Found, str | None]] = []  # (type word, found, reason)
    for export_type in chosen_types(options):
        exporter = EXPORTERS.get(export_type)
        if exporter is None:  # A type with no exporter yet is passed over
            continue
        selection = Selection(
            namespace=ctx.config.namespace if exporter.namespaced else None,
            name_glob=options.name_glob,
        )
        found = export.attempt(
            partial(exporter.find, ctx, selection),
            f"find {export_type}",
            ExportRecord(export_type, None, "skipped"),
        )
        if found and options.interactive:
            found = _selected(ctx, found)
        pending.extend((export_type, item, None) for item in found or ())

    # Each resource is exported once, however many refer to it
    queued = {(export_type, item.name) for export_type, item, _ in pending}
    while pending:
        export_type, item, reason = pending.pop(0)
        exporter = EXPORTERS[export_type]
        exported = export.attempt(
            partial(exporter.export, ctx, item),
            f"export {item.name}",
            ExportRecord(item.resource_type, item.name, "skipped"),
        )
        if exported is None:
            continue
        export.exported[(export_type, item.name)] = (item, exported)
        export.records.append(
            ExportRecord(item.resource_type, item.name, "exported", reason)
        )
        for note in exported.notes:
            warn(note)
        if not options.with_dependencies:
            continue
        for reference in exported.references:
            if (reference.export_type, reference.name) in queued:
                continue
            queued.add((reference.export_type, reference.name))
            dependency = _dependency(ctx, export, reference)
            if dependency is not None:
                pending.append(
                    (reference.export_type, dependency, f"a dependency of {item.name}")
                )

    ordered = sorted(
        export.exported.values(),
        key=lambda pair: (
            RESOURCE_CREATION_ORDER.index(pair[1].specification[PROP_RESOURCE]),
            pair[0].name,
        ),
    )
    specifications = [exported.specification for _, exported in ordered]
    return specifications, export.records, export.failures


def _dependency(ctx: RunContext, export: _Export, reference: Reference) -> Found | None:
    """
    The resource a reference names, found by its exact name through its
    type's exporter, in the namespace the name gives for a namespaced type
    (an account-wide name holding a '/' is a name: Group 'ops/admin'); None
    if its exporter does not follow it (a public Image Family), or, with a
    note, if there is no exporter for its type or no such resource (one
    deleted). A failed lookup is recorded as its resource type and name.
    """
    exporter: Exporter | None = EXPORTERS.get(reference.export_type)
    if exporter is not None:
        failed = ExportRecord(
            exporter.resource_type or reference.export_type, reference.name, "skipped"
        )
        if exporter.followed is not None:
            followed = export.attempt(
                partial(exporter.followed, ctx, reference.name),
                f"find {reference.name}",
                failed,
            )
            if followed is None:  # Failed, reported and recorded
                return None
            if not followed:
                _LOG.debug("'%s' is not followed", reference.name)
                return None
        if exporter.namespaced:
            namespace, _, name = reference.name.rpartition(NAMESPACE_PREFIX_SEPARATOR)
        else:
            namespace, name = "", reference.name
        # The exact name, its glob characters ('render[1]') matched as written
        selection = Selection(namespace=namespace or None, name_glob=glob.escape(name))
        found = export.attempt(
            partial(exporter.find, ctx, selection), f"find {reference.name}", failed
        )
        if found is None:  # Failed, reported and recorded
            return None
        for item in found:
            if item.name == reference.name:
                return item
    _LOG.debug("No %s named '%s' to export", reference.export_type, reference.name)
    export.warn(f"'{reference.name}' could not be found to export")
    return None


def _selected(ctx: RunContext, found: list[Found]) -> list[Found]:
    """
    The resources picked from those found. The list and its prompt go to
    stderr, since standard output may be the array.
    """
    with redirect_stdout(sys.stderr):
        return interactive.select(
            ctx.client,
            found,
            object_type_name=RESOURCE_TYPE_NAMES.get(
                found[0].resource_type, found[0].resource_type
            ),
            force_interactive=True,
        )


def _warning(message: str) -> None:
    print_warning(message, stderr=True)
