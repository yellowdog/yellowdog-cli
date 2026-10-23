"""
utils/output_encoding.py: on Windows, standard output and standard error
written to a pipe or a file are switched to UTF-8 (a character outside the
ANSI code page would otherwise end the command); elsewhere, and where a
stream is UTF-8 already, nothing changes. Every entry point reaches it
before printing anything.
"""

import io
import sys
from importlib import import_module
from inspect import getsource
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10: tomli, which the CLI already depends on
    import tomli as tomllib

import pytest

from yellowdog_cli.utils import output_encoding
from yellowdog_cli.utils.output_encoding import use_utf8_output


def _stream(encoding: str, errors: str = "strict") -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(), encoding=encoding, errors=errors)


def _redirected(monkeypatch) -> tuple[io.TextIOWrapper, io.TextIOWrapper]:
    """
    Standard output and error as Windows has them for a pipe or a file.
    Set in the test itself: pytest's capture puts its own back as the test
    starts, so a fixture's would be gone.
    """
    out, err = _stream("cp1252"), _stream("cp1252", errors="backslashreplace")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    return out, err


def test_on_windows_a_pipe_or_file_becomes_utf8(monkeypatch):
    monkeypatch.setattr(output_encoding.sys, "platform", "win32")
    streams = _redirected(monkeypatch)
    use_utf8_output()
    out, err = streams
    assert out.encoding == "utf-8" and err.encoding == "utf-8"
    out.write("— ✓")
    out.flush()
    assert out.buffer.getvalue() == "— ✓".encode()  # type: ignore[attr-defined]


def test_each_stream_keeps_its_error_handling(monkeypatch):
    monkeypatch.setattr(output_encoding.sys, "platform", "win32")
    streams = _redirected(monkeypatch)
    use_utf8_output()
    assert [stream.errors for stream in streams] == ["strict", "backslashreplace"]


def test_elsewhere_nothing_changes(monkeypatch):
    monkeypatch.setattr(output_encoding.sys, "platform", "darwin")
    streams = _redirected(monkeypatch)
    use_utf8_output()
    assert [stream.encoding for stream in streams] == ["cp1252", "cp1252"]


def test_utf8_already_is_left_alone(monkeypatch):
    monkeypatch.setattr(output_encoding.sys, "platform", "win32")
    stream = _stream("UTF-8")
    monkeypatch.setattr(sys, "stdout", stream)
    use_utf8_output()
    assert stream.encoding == "UTF-8"


@pytest.mark.parametrize("stream", [None, object()], ids=["none", "no-reconfigure"])
def test_a_stream_that_cannot_be_reconfigured_is_left_alone(monkeypatch, stream):
    monkeypatch.setattr(output_encoding.sys, "platform", "win32")
    monkeypatch.setattr(sys, "stdout", stream)
    use_utf8_output()
    assert sys.stdout is stream


# Commander has no console output, and the MCP server's standard output is
# its transport, which its SDK writes as UTF-8 itself
_OWN_OUTPUT = {"yellowdog_cli.commander.launcher", "yellowdog_cli.mcp.launcher"}


def _entry_point_modules() -> list[str]:
    with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
        scripts = tomllib.load(f)["project"]["scripts"]
    return sorted({target.split(":")[0] for target in scripts.values()} - _OWN_OUTPUT)


@pytest.mark.parametrize("module", _entry_point_modules())
def test_every_entry_point_switches_before_printing(module):
    # The first statement of what runs: a wrapper's prepare_run(), which
    # calls it first, or the command's own call
    source = getsource(import_module(module).main)
    first = next(
        line.strip()
        for line in source.splitlines()[1:]
        if line.strip() and not line.strip().startswith(("#", '"""'))
    )
    assert first.startswith("prepare_run(") or first == "use_utf8_output()", module


def test_the_wrappers_switch_before_anything_else():
    from yellowdog_cli.utils import command_runner

    body = getsource(command_runner.prepare_run).split('"""')[2]
    assert body.strip().splitlines()[0] == "use_utf8_output()"
