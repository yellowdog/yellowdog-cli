"""
Every broad exception handler (a bare 'except:', 'except Exception' or
'except BaseException') either lets the failure reach the wrapper with its
exit code, or is listed in ALLOWED with the reason it may not.

A broad handler is where an authentication or connection failure gets
swallowed, or turned into the wrong exit code: a review of all of them found
ten that did (a 401 shown as 'not found', a lost stream taken as finished, a
failure recorded under exit 0). So a handler passes this scan only if it
re-raises the failure (a bare 'raise', 'raise e', 'raise X from e', or
'raise ReportedFailure(e)' at the top level of the handler), or routes it by
its exit code: it uses classify(), SESSION_FAILURES or
_raise_session_failure(), or calls one of ROUTING_HELPERS, each of which does
so itself (checked below). Anything else is listed in ALLOWED, keyed by its
file, its enclosing function and its place among that function's broad
handlers, with the reason. A new broad handler fails the scan until it routes
its failure or says why it need not; an ALLOWED entry that no longer names a
handler needing it fails too, so the list cannot outlive its reasons.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import yellowdog_cli

PACKAGE = Path(yellowdog_cli.__file__).parent

BROAD = {"Exception", "BaseException"}

# Names whose use in a handler routes the failure by its exit code
CLASSIFYING = {
    "classify",
    "SESSION_FAILURES",
    "_raise_session_failure",
    "ReportedFailure",
}

# Project helpers that route a failure for the handler that calls them: each
# one's own body uses one of CLASSIFYING
ROUTING_HELPERS = {
    "_after_failure",  # yd-nodeaction: the rest recorded, ReportedFailure raised
    "_failed",  # yd-shutdown: recorded, SessionStop raised for a session failure
    "_record_follow_failure",  # Following: recorded by its code, for the exit code
    "_stop",  # yd-boost: ReportedFailure raised for a session failure
    "_stop_if_session_failure",  # yd-abort: the rest recorded, ReportedFailure raised
}

# Broad handlers that need not route their failure, and why
_DATA_CLIENT = (
    "Data client: no Platform session; the argument's failure is reported and"
    " recorded, and the rest still attempted"
)
_STANDALONE = (
    "Standalone, with no Platform session: each file's failure is reported and"
    " counted, and the run exits 1"
)
_AZURE = (
    "Cloud Wizard: an Azure failure, which has no YellowDog exit code, reported"
    " through the counted print_error() (or as a deliberate warning), so the run"
    " exits 1"
)
_DOCTOR = "yd-doctor: a check's failure is its diagnostic row, the check's purpose"
_CURSOR = "Best-effort restoration of the terminal's cursor"
_LOADER = (
    "Configuration loading, before any Platform call: exits 3, and lets the"
    " traceback through under --debug"
)
_ADVISORY = (
    "An advisory schema check: a fault in it is a warning, never a stopped"
    " command; --debug lets it through"
)
ALLOWED: dict[str, str] = {
    "yellowdog_cli/abort.py::_task_group_part#0": (
        "The Task Group's name, for the message, after the Task was aborted:"
        " raising would report a successful abort as failed; a session failure"
        " recurs at the next request"
    ),
    "yellowdog_cli/application.py::_groups_and_roles#0": (
        "Returns the failure, which the caller classifies for the exit code"
    ),
    "yellowdog_cli/commander/command_running.py::CommandRunning._capture_json#0": (
        "Commander: a child's output that is not JSON; None falls back to a"
        " confirmation of the whole scope"
    ),
    "yellowdog_cli/commander/commander.py::run_app#0": (
        "Commander's start-up failure, printed with ERROR_MARKER, exit 1; it makes"
        " no Platform calls itself"
    ),
    "yellowdog_cli/commander/config_discovery.py::ConfigDiscovery._parse_yd_config#0": (
        "Commander: a child's output that cannot be read is reported in the"
        " window, which stays up"
    ),
    "yellowdog_cli/commander/window_base.py::WindowBase._get_config_data_file#0": (
        "Commander: best-effort resolution of a {{variable}} in a file's name,"
        " falling back to its default"
    ),
    "yellowdog_cli/delete.py::main#0": _DATA_CLIENT,
    "yellowdog_cli/download.py::main#0": _DATA_CLIENT,
    "yellowdog_cli/download.py::_refuse_unsafe_syncs#0": (
        "A wildcard the --sync check cannot list is returned, and failed by the"
        " caller rather than synced unchecked"
    ),
    "yellowdog_cli/format_json.py::main#0": _STANDALONE,
    "yellowdog_cli/format_json.py::main#1": _STANDALONE,
    "yellowdog_cli/jsonnet2json.py::main#0": _STANDALONE,
    "yellowdog_cli/jsonnet2json.py::main#1": _STANDALONE,
    "yellowdog_cli/jsonnet2json.py::main#2": _STANDALONE,
    "yellowdog_cli/ls.py::main#0": _DATA_CLIENT,
    "yellowdog_cli/mcp/server.py::call_tool#0": (
        "yd-mcp's last resort, logged with its traceback: raised, the SDK would"
        " answer it as a protocol error the model never sees"
    ),
    "yellowdog_cli/submit.py::cleanup_on_failure#0": (
        "Best-effort cancellation after a failed submission, whose own failure"
        " the caller then re-raises"
    ),
    "yellowdog_cli/submit.py::cleanup_on_failure#1": (
        "Best-effort deletion of the uploaded files after a failed submission,"
        " whose own failure the caller then re-raises"
    ),
    "yellowdog_cli/utils/cloudwizard/azure.py::AzureConfig._create_resource_groups_and_network_resources#0": _AZURE,
    "yellowdog_cli/utils/cloudwizard/azure.py::AzureConfig._create_resource_groups_and_network_resources#1": _AZURE,
    "yellowdog_cli/utils/cloudwizard/azure.py::AzureConfig._remove_resource_groups#0": _AZURE,
    "yellowdog_cli/utils/cloudwizard/azure.py::AzureConfig._remove_resource_group_by_name#0": _AZURE,
    "yellowdog_cli/utils/cloudwizard/azure.py::AzureConfig._create_network_resources#0": _AZURE,
    "yellowdog_cli/utils/cloudwizard/azure.py::AzureConfig._create_network_resources#1": _AZURE,
    "yellowdog_cli/utils/cloudwizard/azure.py::AzureConfig._create_network_resources#2": _AZURE,
    "yellowdog_cli/utils/cloudwizard/azure.py::AzureConfig._create_network_resources#3": _AZURE,
    "yellowdog_cli/utils/cloudwizard/azure.py::AzureConfig.set_ssh_ingress_rule#0": _AZURE,
    "yellowdog_cli/utils/cloudwizard/azure.py::AzureConfig.set_ssh_ingress_rule#1": _AZURE,
    "yellowdog_cli/utils/cloudwizard/common.py::CommonCloudConfig._remove_each#0": (
        "Cloud Wizard teardown: a session failure is raised, as ReportedFailure,"
        " by the clause before; any other is counted, and the rest removed"
    ),
    "yellowdog_cli/utils/cloudwizard/common.py::CommonCloudConfig._save_resource_list#0": (
        "Cloud Wizard: writing the local resource file, counted as an error"
    ),
    "yellowdog_cli/utils/cloudwizard/common.py::CommonCloudConfig._create_keyring#0": (
        "Cloud Wizard setup: counted as an error; a session failure recurs at"
        " setup's next Platform call, which raises it with its own code"
    ),
    "yellowdog_cli/utils/doctor_checks.py::with_timeout.target#0": (
        "Hands the failure back to the calling thread, which raises or reports it"
    ),
    "yellowdog_cli/utils/doctor_checks.py::_run_one#0": _DOCTOR + "; --debug re-raises",
    "yellowdog_cli/utils/doctor_checks.py::check_sdk_imports#0": _DOCTOR,
    "yellowdog_cli/utils/doctor_checks.py::check_newer_cli_on_pypi#0": _DOCTOR,
    "yellowdog_cli/utils/doctor_checks.py::_resolve_pac_proxy#0": _DOCTOR,
    "yellowdog_cli/utils/doctor_checks.py::_load_data_client_profiles#0": _DOCTOR,
    "yellowdog_cli/utils/doctor_checks.py::_load_data_client_under_test#0": _DOCTOR,
    "yellowdog_cli/utils/doctor_checks.py::check_data_client_remote#0": _DOCTOR,
    "yellowdog_cli/utils/doctor_checks.py::check_data_client_remote#1": _DOCTOR,
    "yellowdog_cli/utils/follow_utils.py::follow_work_requirement_with_progress#0": (
        "Cosmetic: the progress bar's counts before the first event"
    ),
    "yellowdog_cli/utils/follow_utils.py::follow_work_requirement_with_progress.on_event#0": (
        "Cosmetic: an event line that is not JSON, skipped by the progress bar"
    ),
    "yellowdog_cli/utils/follow_utils.py::_restore_cursor#0": _CURSOR,
    "yellowdog_cli/utils/follow_utils.py::follow_ids._on_sigint#0": _CURSOR,
    "yellowdog_cli/utils/follow_utils.py::follow_events#0": (
        "Decoding the message of a refused stream; the HTTPError is still"
        " recorded by its status"
    ),
    "yellowdog_cli/utils/json_raw.py::submit_json_raw#1": (
        "Best-effort cancellation of a part-populated Work Requirement; the"
        " original failure is re-raised after it"
    ),
    "yellowdog_cli/utils/load_config.py::warn_of_config_violations#0": _ADVISORY,
    "yellowdog_cli/utils/load_config.py::_load_config_file#0": _LOADER,
    "yellowdog_cli/utils/load_config.py::_load_config_file#1": _LOADER,
    "yellowdog_cli/utils/load_config.py::load_config_work_requirement#0": _LOADER,
    "yellowdog_cli/utils/load_config.py::load_config_worker_pool#0": _LOADER,
    "yellowdog_cli/utils/resource_creation.py::_grant_keyrings#0": (
        "Collected, the other grants tried, then raised from the first failure,"
        " whose code classify() follows"
    ),
    "yellowdog_cli/utils/resource_creation.py::create_namespace#0": (
        "Tolerates only a ConflictException (the namespace exists), recorded as"
        " skipped; anything else is raised from it"
    ),
    "yellowdog_cli/utils/results.py::flush_results_after_failure#0": (
        "The exit code is set before the flush, which must not replace it"
    ),
    "yellowdog_cli/utils/specs/schema_cache.py::compile_validator#0": (
        "Cached code is never trusted: it is compiled afresh from the schema"
    ),
    "yellowdog_cli/utils/specs/validation.py::warn_of_violations#0": _ADVISORY,
    "yellowdog_cli/utils/submit_utils.py::RcloneUploadedFiles.delete#0": (
        "Best-effort deletion of each uploaded file after a failed submission,"
        " whose own failure the caller re-raises"
    ),
    "yellowdog_cli/utils/submit_utils.py::RcloneUploadedFiles._bucket_and_prefix#0": (
        "Formats a message's location, withholding an inline remote's credentials"
    ),
    "yellowdog_cli/utils/task_batches.py::Batches.total#0": (
        "The first failure is kept, and raised as it is once every batch has finished"
    ),
    "yellowdog_cli/utils/task_batches.py::submit_with_retries#0": (
        "Retries a transient failure, and raises it as it is once it is"
        " permanent or the retries are spent"
    ),
    "yellowdog_cli/utils/variable_substitution.py::<module>#0": (
        "getuser() can fail without a login name: the default user name instead"
    ),
}


def _broad(handler: ast.ExceptHandler) -> bool:
    caught = handler.type
    if caught is None:
        return True
    names = caught.elts if isinstance(caught, ast.Tuple) else [caught]
    return any(isinstance(name, ast.Name) and name.id in BROAD for name in names)


def _walk_without_definitions(nodes: list[ast.stmt]) -> Iterator[ast.AST]:
    """
    Every node under 'nodes', but not inside a function, lambda or class
    defined there, whose code does not run as the handler does.
    """
    stack: list[ast.AST] = list(nodes)
    while stack:
        node = stack.pop()
        yield node
        for child in ast.iter_child_nodes(node):
            if not isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
            ):
                stack.append(child)


def _names_used(nodes: list[ast.stmt]) -> set[str]:
    names = set()
    for node in _walk_without_definitions(nodes):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def _raises_the_failure(statement: ast.stmt, name: str | None) -> bool:
    """
    Whether 'statement' raises the handled failure on, so that classify()
    still finds its code: a bare 'raise', 'raise e', 'raise X from e', or
    'raise ReportedFailure(e)'.
    """
    if not isinstance(statement, ast.Raise):
        return False
    raised, cause = statement.exc, statement.cause
    return (
        raised is None
        or (isinstance(raised, ast.Name) and raised.id == name)
        or (isinstance(cause, ast.Name) and cause.id == name)
        or (
            isinstance(raised, ast.Call)
            and isinstance(raised.func, ast.Name)
            and raised.func.id == "ReportedFailure"
        )
    )


def _always_raises(statements: list[ast.stmt], name: str | None) -> bool:
    """
    Whether every path through 'statements' raises the failure on: one of
    them does, or is an 'if' each of whose branches always does.
    """
    for statement in statements:
        if _raises_the_failure(statement, name):
            return True
        if (
            isinstance(statement, ast.If)
            and statement.orelse
            and _always_raises(statement.body, name)
            and _always_raises(statement.orelse, name)
        ):
            return True
    return False


def _reraises(handler: ast.ExceptHandler) -> bool:
    """
    Whether the handler raises the failure on, on every path, or on every
    path but a 404's: 'if not is_http_not_found(e): raise', the tolerance
    of one specific failure that a lookup is allowed.
    """
    if _always_raises(handler.body, handler.name):
        return True
    return "is_http_not_found" in _names_used(handler.body) and any(
        _raises_the_failure(node, handler.name)  # type: ignore[arg-type]
        for node in _walk_without_definitions(handler.body)
        if isinstance(node, ast.Raise)
    )


def _routes(handler: ast.ExceptHandler) -> bool:
    return bool(_names_used(handler.body) & (CLASSIFYING | ROUTING_HELPERS))


def broad_handlers(source: str) -> Iterator[tuple[str, ast.ExceptHandler]]:
    """
    Each broad handler in 'source', keyed by its enclosing function's
    qualified name and its place among that function's broad handlers.
    """
    counts: dict[str, int] = {}

    def visit(node: ast.AST, qualified: str) -> Iterator[tuple[str, ast.ExceptHandler]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                yield from visit(
                    child, f"{qualified}.{child.name}" if qualified else child.name
                )
                continue
            if isinstance(child, ast.ExceptHandler) and _broad(child):
                scope = qualified or "<module>"
                index = counts.get(scope, 0)
                counts[scope] = index + 1
                yield f"{scope}#{index}", child
            yield from visit(child, qualified)

    yield from visit(ast.parse(source), "")


def _unrouted() -> dict[str, int]:
    """
    Each broad handler that neither re-raises nor routes its failure, keyed
    as ALLOWED is, with its line.
    """
    unrouted = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        relative = path.relative_to(PACKAGE.parent).as_posix()
        for key, handler in broad_handlers(path.read_text(encoding="utf-8")):
            if not (_reraises(handler) or _routes(handler)):
                unrouted[f"{relative}::{key}"] = handler.lineno
    return unrouted


def test_every_broad_handler_routes_its_failure_or_says_why_not():
    unlisted = {key: line for key, line in _unrouted().items() if key not in ALLOWED}
    assert unlisted == {}, (
        "A broad exception handler neither re-raises its failure nor routes it"
        " through classify(): re-raise it, check it against SESSION_FAILURES,"
        " or add it to ALLOWED with the reason it need not"
    )


def test_every_allowed_handler_still_needs_it():
    stale = sorted(set(ALLOWED) - set(_unrouted()))
    assert stale == [], (
        "ALLOWED names a handler that is gone, or now routes its failure"
    )


def test_every_routing_helper_routes():
    definitions: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                definitions.setdefault(node.name, []).append(node)
    not_routing = sorted(
        name
        for name in ROUTING_HELPERS
        if not definitions.get(name)
        or not all(
            _names_used(definition.body) & CLASSIFYING
            for definition in definitions[name]
        )
    )
    assert not_routing == []


def test_the_scan_finds_what_it_looks_for():
    # The control: each way of passing, and the handlers that pass none
    source = """
def reraises():
    try: pass
    except Exception: raise

def reraises_from(e):
    try: pass
    except Exception as e: raise RuntimeError("clearer") from e

def reports(e):
    try: pass
    except Exception as e: raise ReportedFailure(e)

def classifies():
    try: pass
    except Exception as e:
        if classify(e) in SESSION_FAILURES: raise
        return None

def narrow():
    try: pass
    except KeyError: pass

def swallows():
    try: pass
    except Exception: pass

def loses_the_code(e):
    try: pass
    except Exception as e: raise RuntimeError(f"clearer: {e}")

def raises_on_both_branches(e):
    try: pass
    except Exception as e:
        if "401" in str(e): raise RuntimeError("bad credentials") from e
        else: raise e

def tolerates_only_a_404(e):
    try: pass
    except Exception as e:
        if not is_http_not_found(e): raise
        return None

def raises_only_sometimes(e):
    try: pass
    except BaseException as e:
        if debug: raise
        print(e)

def bare():
    try: pass
    except: pass
"""
    unrouted = [
        key
        for key, handler in broad_handlers(source)
        if not (_reraises(handler) or _routes(handler))
    ]
    assert unrouted == [
        "swallows#0",
        "loses_the_code#0",
        "raises_only_sometimes#0",
        "bare#0",
    ]
