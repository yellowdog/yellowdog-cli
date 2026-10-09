"""
The MCP server: the SDK's low-level Server over the tool catalogue
(tools.py) and the runner (runner.py). Its stdout is the transport, so its
own messages go to stderr through logging. The one module in the package
that imports 'mcp'.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import signal
import sys
from typing import Any

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from yellowdog_cli._version import __version__
from yellowdog_cli.mcp.runner import Run, command_argv, parse_event_documents, run
from yellowdog_cli.mcp.tools import (
    OUTPUT_SCHEMA,
    ServerSettings,
    ToolArgumentError,
    ToolSpec,
    build_tools,
    fixed_args,
    timeout_of,
    to_argv,
    tool_named,
)
from yellowdog_cli.utils.settings import MCP_SERVER_NAME

LOG = logging.getLogger("yd-mcp")

# A call refused before any command ran: argparse's usage exit code
USAGE_EXIT_CODE = 2

INSTRUCTIONS = (
    "These tools are the YellowDog CLI's yd-* commands, one tool per command, run"
    " with --json: a tool's result is the command's JSON document, as the CLI's"
    " 'Machine-readable Output and Exit Codes' page (docs/json-output.md)"
    " describes, and a"
    " failure carries the command's error text and exit code. Destructive tools"
    " (cancel, terminate, shut down, remove, delete) run without a confirmation"
    " prompt, so confirm with the user first; every acting or destructive tool"
    " that has dry_run can enumerate what it would do. Every tool takes"
    " timeout_seconds and returns what it had if stopped. Specifications may be"
    " given inline. yd-mcp's own README documents the server."
)


def _tool(spec: ToolSpec) -> types.Tool:
    # Copies, so the SDK can never mutate the cached catalogue's schemas
    return types.Tool(
        name=spec.name,
        title=spec.title,
        description=spec.description,
        input_schema=copy.deepcopy(spec.input_schema),
        output_schema=copy.deepcopy(OUTPUT_SCHEMA),
        annotations=types.ToolAnnotations.model_validate(spec.annotations),
    )


def _error(text: str, **structured: Any) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        structured_content=structured or None,
        is_error=True,
    )


def _records_a_failure(document: Any) -> bool:
    """
    Whether 'document' is a list holding a record whose 'outcome' or 'action'
    is 'failed': the CLI's per-item failure (results.any_failed()), the one
    exit 1 that is still a result rather than an error. Both wrappers flush
    '[]' on every failure path, so a document alone proves nothing.
    """
    return isinstance(document, list) and any(
        isinstance(item, dict)
        and (item.get("outcome") == "failed" or item.get("action") == "failed")
        for item in document
    )


def _error_text(tool: ToolSpec, result: Run, document: Any) -> str:
    """
    A failed run's text content: its stderr, then its document as compact
    JSON when it left one (yd-doctor's failing checks and yd-wait's failed
    Work Requirement exit 1 with the document alone), so the text says as
    much as structuredContent does.
    """
    parts = [result.stderr.strip()] if result.stderr.strip() else []
    if document is not None:
        parts.append(json.dumps(document, separators=(",", ":")))
    return "\n".join(parts) or (
        f"{tool.command.name} exited {result.exit_code} with no output"
    )


def _result_of(
    tool: ToolSpec, result: Run, timeout_seconds: int
) -> types.CallToolResult:
    document = (
        parse_event_documents(result.stdout)
        if tool.command.name == "yd-follow"
        else result.document
    )
    succeeded = (
        result.stopped
        or result.exit_code == 0
        or (result.exit_code == 1 and _records_a_failure(document))
    )
    if not succeeded:
        return _error(
            _error_text(tool, result, document),
            result=document,
            exitCode=result.exit_code,
            stderr=result.stderr,
        )
    text = json.dumps(document, separators=(",", ":"))
    if result.stopped:
        text = f"Stopped after {timeout_seconds} seconds; the result so far:\n{text}"
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        structured_content={
            "result": document,
            "exitCode": result.exit_code,
            "stopped": result.stopped,
            **({"stderr": result.stderr} if result.stopped else {}),
        },
        is_error=False,
    )


def call_tool(
    name: str,
    arguments: dict[str, Any],
    settings: ServerSettings,
    environment: dict[str, str],
) -> types.CallToolResult:
    """
    One tool call, synchronously: the command line from the arguments, the
    run, the result. Every failure is a tool error (isError), never an
    exception, so the model sees it and can retry.
    """
    tool = tool_named(name)
    if tool is None:
        return _error(f"Unknown tool: {name}", exitCode=USAGE_EXIT_CODE)
    written = []
    try:
        timeout_seconds = timeout_of(tool, arguments)
        own_args, written = to_argv(tool, arguments, settings.working_dir)
        argv = (
            command_argv(tool.command.name)
            + fixed_args(tool.command, settings)
            + own_args
        )
        LOG.info("%s: %s", name, " ".join(argv[2:]))
        result = run(argv, settings.working_dir, environment, timeout_seconds)
        LOG.info(
            "%s: exit %d%s",
            name,
            result.exit_code,
            " (stopped)" if result.stopped else "",
        )
        return _result_of(tool, result, timeout_seconds)
    except ToolArgumentError as error:
        return _error(str(error), exitCode=USAGE_EXIT_CODE)
    except OSError as error:
        # Writing an inline specification, or starting the child
        where = f": {error.filename}" if error.filename else ""
        return _error(
            f"{tool.command.name} could not be run{where}: {error.strerror or error}",
            exitCode=USAGE_EXIT_CODE,
        )
    except Exception as error:
        # The last resort: anything else raised here would reach the SDK,
        # which answers it as a protocol error the model never sees
        LOG.exception("%s failed", name)
        return _error(
            f"{tool.command.name} could not be run: {error}",
            exitCode=USAGE_EXIT_CODE,
        )
    finally:
        for path in written:
            try:
                path.unlink()
            except OSError:
                pass


def build_server(settings: ServerSettings) -> Server:
    tools = [_tool(spec) for spec in build_tools()]

    async def on_list_tools(_context, _params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=tools)

    async def on_call_tool(
        _context, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        # In a worker thread, so the event loop keeps serving while a
        # command runs
        return await anyio.to_thread.run_sync(
            call_tool,
            params.name,
            dict(params.arguments or {}),
            settings,
            dict(os.environ),
        )

    return Server(
        MCP_SERVER_NAME,
        version=__version__,
        instructions=INSTRUCTIONS,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


STOP_SIGNALS = tuple(
    getattr(signal, name) for name in ("SIGINT", "SIGTERM") if hasattr(signal, name)
)


async def _stop_on_signal() -> None:
    """
    End the process at the first SIGINT or SIGTERM. Cancelling the serving
    task group is not enough: the SDK's stdin reader blocks in readline() in
    an anyio worker thread, which a cancel waits for (not abandoned, and not
    a daemon, so the interpreter would wait for it at exit too), and so does
    a tool call in progress; the stop was absorbed until a line arrived or a
    second Ctrl-C interrupted it with a traceback. So the stop is logged,
    the log flushed, and the process ended at once; a command still running
    is left to finish on its own.
    """
    with anyio.open_signal_receiver(*STOP_SIGNALS) as signals:
        async for received in signals:
            LOG.info("stopped (%s)", signal.Signals(received).name)
            logging.shutdown()
            os._exit(0)


async def _serve_stdio(settings: ServerSettings) -> None:
    server = build_server(settings)
    async with stdio_server() as (read_stream, write_stream):
        async with anyio.create_task_group() as tg:
            if sys.platform != "win32":
                # Windows has no signal receiver: KeyboardInterrupt is the route
                tg.start_soon(_stop_on_signal)
            await server.run(
                read_stream, write_stream, server.create_initialization_options()
            )
            tg.cancel_scope.cancel()


def run_server(settings: ServerSettings) -> None:
    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO, format="%(name)s: %(message)s"
    )
    LOG.info(
        "serving %d tools over %s; config %s; working directory %s",
        len(build_tools()),
        settings.transport,
        settings.config_file or "none (--nc)",
        settings.working_dir,
    )
    try:
        anyio.run(_serve_stdio, settings)
    except KeyboardInterrupt:
        # The fallback where no signal receiver runs (Windows): a quiet stop
        LOG.info("stopped")
