"""
yd-mcp through the SDK's own client over in-memory streams: the catalogue
is listed with its annotations, a call returns the command's document as
structured content, a failure returns the CLI's stderr with isError, and a
bad argument is a tool error. Skipped without the 'mcp' extra.
"""

import json
import os
import sys

import pytest

from tests.mcp_guard import require_mcp

require_mcp()

import anyio  # noqa: E402
from mcp.client.session import ClientSession  # noqa: E402
from mcp.shared.memory import create_client_server_memory_streams  # noqa: E402

from yellowdog_cli.mcp.server import build_server, call_tool  # noqa: E402
from yellowdog_cli.mcp.tools import ServerSettings, build_tools  # noqa: E402
from yellowdog_cli.utils.output_style import REDACTED_VALUE  # noqa: E402
from yellowdog_cli.utils.rclone_version import find_rclone  # noqa: E402


@pytest.fixture
def clean_env(monkeypatch):
    for name in [k for k in os.environ if k.startswith("YD_")]:
        monkeypatch.delenv(name)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return ServerSettings(config_file=None, namespace=None, tag=None, variables=())


def _through_client(server, action):
    """
    Run 'action(session)' against 'server' over in-memory streams.
    """

    async def main():
        async with create_client_server_memory_streams() as (
            client_streams,
            server_streams,
        ):
            async with anyio.create_task_group() as tg:
                tg.start_soon(
                    server.run,
                    server_streams[0],
                    server_streams[1],
                    server.create_initialization_options(),
                )
                async with ClientSession(*client_streams) as session:
                    await session.initialize()
                    result = await action(session)
                tg.cancel_scope.cancel()
        return result

    return anyio.run(main)


def test_the_catalogue_is_listed(settings, clean_env):
    async def action(session):
        return await session.list_tools()

    listed = _through_client(build_server(settings), action)
    by_name = {t.name: t for t in listed.tools}
    assert set(by_name) == {t.name for t in build_tools()}
    assert by_name["yd_cancel"].annotations.destructive_hint is True
    assert by_name["yd_list"].annotations.read_only_hint is True
    assert by_name["yd_list"].input_schema["additionalProperties"] is False
    assert by_name["yd_list"].output_schema["required"] == ["exitCode"]
    assert by_name["yd_submit"].description.startswith("Submit a Work Requirement")


def test_the_server_names_itself(settings, clean_env):
    from yellowdog_cli._version import __version__

    async def action(session):
        return await session.initialize()

    # initialize() twice is harmless here: the helper's own call and this one
    init = _through_client(build_server(settings), action)
    assert init.server_info.name == "yellowdog-cli"
    assert init.server_info.version == __version__
    assert "yd-mcp" in (init.instructions or "")


def test_a_call_returns_the_document(settings, clean_env):
    async def action(session):
        return await session.call_tool("yd_version", {"timeout_seconds": 60})

    result = _through_client(build_server(settings), action)
    assert result.is_error is False
    assert result.structured_content["exitCode"] == 0
    assert result.structured_content["stopped"] is False
    assert "cli" in result.structured_content["result"]
    assert json.loads(result.content[0].text) == result.structured_content["result"]


def test_a_failed_command_is_an_error_with_its_stderr(settings, clean_env):
    async def action(session):
        return await session.call_tool("yd_list", {"entity_type": "work-requirements"})

    result = _through_client(build_server(settings), action)
    assert result.is_error is True
    assert result.structured_content["exitCode"] == 3
    assert "Missing configuration data" in result.content[0].text
    assert "Missing configuration data" in result.structured_content["stderr"]


def test_a_bad_argument_is_a_tool_error(settings, clean_env):
    async def action(session):
        return await session.call_tool(
            "yd_list", {"entity_type": "work-requirements", "nope": 1}
        )

    result = _through_client(build_server(settings), action)
    assert result.is_error is True
    assert "nope" in result.content[0].text
    assert result.structured_content["exitCode"] == 2


def test_an_unknown_tool_is_a_tool_error(settings, clean_env):
    async def action(session):
        return await session.call_tool("yd_nothing", {})

    result = _through_client(build_server(settings), action)
    assert result.is_error is True
    assert "yd_nothing" in result.content[0].text
    assert result.structured_content["exitCode"] == 2


def test_yd_variables_returns_its_document(settings, clean_env, monkeypatch):
    # yd-variables prints its own JSON, with no --json option to silence the
    # wrapper's 'Done' after it: without --quiet the document does not parse
    for name, value in (
        ("YD_KEY", "k"),
        ("YD_SECRET", "s"),
        ("YD_NAMESPACE", "ns"),
        ("YD_TAG", "t"),
    ):
        monkeypatch.setenv(name, value)
    result = call_tool(
        "yd_variables", {"variable_names": ["namespace"]}, settings, dict(os.environ)
    )
    assert result.is_error is False, result.content[0].text
    assert isinstance(result.structured_content["result"], dict)
    assert result.structured_content["result"]["namespace"] == "ns"


def test_an_option_value_cannot_inject_a_flag(settings, clean_env, monkeypatch):
    # namespace='--show-secrets' passed as '-n --show-secrets' is taken by
    # argparse as the (withheld) flag, and the full report shows the secret
    monkeypatch.setenv("YD_KEY", "k")
    monkeypatch.setenv("YD_SECRET", "s")
    result = call_tool(
        "yd_variables", {"namespace": "--show-secrets"}, settings, dict(os.environ)
    )
    assert result.is_error is False, result.content[0].text
    document = result.structured_content["result"]
    assert document["secret"] == REDACTED_VALUE
    assert document["namespace"] == "--show-secrets"


def test_an_error_with_a_document_carries_it_in_its_text(settings, clean_env):
    # yd-doctor exits 1 on its failing checks with its document on stdout and
    # nothing on stderr: the text content is the document, not 'no output'
    result = call_tool("yd_doctor", {"offline": True}, settings, dict(os.environ))
    assert result.is_error is True
    assert result.structured_content["exitCode"] == 1
    document = result.structured_content["result"]
    assert isinstance(document, list) and document
    stderr = result.structured_content["stderr"].strip()
    text = result.content[0].text
    assert text.startswith(stderr)
    assert json.loads(text[len(stderr) :]) == document


def test_a_failure_with_neither_document_nor_stderr_says_so(
    settings, clean_env, monkeypatch
):
    import yellowdog_cli.mcp.server as server_module

    monkeypatch.setattr(
        server_module,
        "command_argv",
        lambda name: [sys.executable, "-c", "import sys; sys.exit(5)"],
    )
    result = call_tool("yd_version", {}, settings, dict(os.environ))
    assert result.is_error is True
    assert result.content[0].text == "yd-version exited 5 with no output"


def test_an_unexpected_exception_is_a_tool_error(settings, clean_env, monkeypatch):
    import yellowdog_cli.mcp.server as server_module

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(server_module, "run", boom)
    result = call_tool("yd_version", {}, settings, dict(os.environ))
    assert result.is_error is True
    assert "boom" in result.content[0].text
    assert result.structured_content["exitCode"] == 2


def test_a_stopped_call_says_so(settings, clean_env, monkeypatch):
    import yellowdog_cli.mcp.server as server_module

    # A follow that never ends: stand a hanging Python in for the command
    monkeypatch.setattr(
        server_module,
        "command_argv",
        lambda name: [
            sys.executable,
            "-c",
            "import sys,time; print('{\"a\": 1}'); sys.stdout.flush(); time.sleep(30)",
        ],
    )
    result = call_tool(
        "yd_follow",
        {"yellowdog_ids": ["ydid:x"], "timeout_seconds": 1},
        settings,
        dict(os.environ),
    )
    assert result.is_error is False
    assert result.structured_content["stopped"] is True
    assert result.structured_content["result"] == [{"a": 1}]
    assert result.content[0].text.startswith("Stopped after 1 seconds")
    assert "stderr" in result.structured_content


def test_an_inline_specification_is_removed_after_the_run(
    settings, clean_env, tmp_path
):
    # yd-submit fails for want of a key, and the file it was given is gone
    result = call_tool(
        "yd_submit",
        {"specification": {"name": "wr"}, "dry_run": True},
        settings,
        dict(os.environ),
    )
    assert result.is_error is True
    assert [p for p in tmp_path.iterdir() if p.name.startswith(".yd-mcp-")] == []


@pytest.mark.skipif(find_rclone() is None, reason="needs an rclone binary")
def test_a_data_client_call_on_the_local_backend(
    settings, clean_env, tmp_path, monkeypatch
):
    (tmp_path / "ns" / "tag").mkdir(parents=True)
    (tmp_path / "ns" / "tag" / "a.txt").write_text("hello")
    monkeypatch.setenv("YD_DATA_CLIENT_REMOTE", "loc,type=local")
    monkeypatch.setenv("YD_NAMESPACE", "ns")
    monkeypatch.setenv("YD_TAG", "tag")
    result = call_tool("yd_ls", {}, settings, dict(os.environ))
    assert result.is_error is False, result.content[0].text
    assert [e["Name"] for e in result.structured_content["result"]] == ["a.txt"]


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="a directory's mode does not bind root",
)
def test_an_unwritable_working_directory_is_a_tool_error(
    clean_env, tmp_path, monkeypatch
):
    readonly = tmp_path / "readonly"
    readonly.mkdir()
    (readonly / "config.toml").write_text("")
    readonly.chmod(0o500)
    try:
        settings = ServerSettings(
            config_file=str(readonly / "config.toml"),
            namespace=None,
            tag=None,
            variables=(),
        )
        result = call_tool(
            "yd_submit",
            {"specification": {"name": "wr"}, "dry_run": True},
            settings,
            dict(os.environ),
        )
    finally:
        readonly.chmod(0o700)
    assert result.is_error is True
    assert str(readonly) in result.content[0].text
    assert result.structured_content["exitCode"] == 2


@pytest.mark.skipif(find_rclone() is None, reason="needs an rclone binary")
def test_a_failed_data_client_run_is_an_error_with_its_stderr(settings, clean_env):
    # The wrapper flushes '[]' on its failure path: an empty document is not
    # a per-item failure, so this is an error, and the stderr is kept
    result = call_tool(
        "yd_ls", {"remote": "x,type=nosuchbackend"}, settings, dict(os.environ)
    )
    assert result.is_error is True
    assert result.structured_content["exitCode"] == 1
    assert result.structured_content["stderr"].strip()
    # The text is the stderr, then the (empty) document the wrapper flushed
    assert result.content[0].text == (
        result.structured_content["stderr"].strip() + "\n[]"
    )


@pytest.mark.skipif(find_rclone() is None, reason="needs an rclone binary")
def test_a_recorded_per_item_failure_is_a_success(
    settings, clean_env, tmp_path, monkeypatch
):
    monkeypatch.setenv("YD_NAMESPACE", "ns")
    monkeypatch.setenv("YD_TAG", "tag")
    result = call_tool(
        "yd_upload",
        {"remote": "loc,type=local", "local_paths": ["nope.txt"]},
        settings,
        dict(os.environ),
    )
    assert result.is_error is False, result.content[0].text
    assert result.structured_content["exitCode"] == 1
    assert any(
        item.get("action") == "failed" for item in result.structured_content["result"]
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
@pytest.mark.parametrize("signal_name", ["SIGINT", "SIGTERM"])
def test_one_signal_stops_the_server_quietly(signal_name, clean_env, tmp_path):
    import signal
    import subprocess
    import threading

    process = subprocess.Popen(
        [sys.executable, "-m", "yellowdog_cli.mcp"],
        cwd=tmp_path,
        env=dict(os.environ),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert process.stdin is not None and process.stdout is not None
        # An answered initialize proves the server is serving, and so that
        # the signal reaches its loop rather than its start-up
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        }
        process.stdin.write(json.dumps(request).encode() + b"\n")
        process.stdin.flush()
        replied = threading.Event()
        reply: list[bytes] = []

        def read_reply() -> None:
            assert process.stdout is not None
            reply.append(process.stdout.readline())
            replied.set()

        threading.Thread(target=read_reply, daemon=True).start()
        assert replied.wait(30), "the server never answered initialize"
        assert json.loads(reply[0])["id"] == 1
        # stdin stays open, as a terminal or a client holds it: closed, the
        # transport's blocked read would end at EOF and hide a stuck stop
        process.send_signal(getattr(signal, signal_name))
        process.wait(timeout=10)
        stderr = process.stderr.read() if process.stderr else b""
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()
    assert process.returncode == 0, stderr.decode(errors="replace")
    assert b"Traceback" not in stderr
    assert b"stopped" in stderr
