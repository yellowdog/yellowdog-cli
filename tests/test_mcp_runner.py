"""
yellowdog_cli/mcp/runner.py: one command line run as a child process with a bound,
its document parsed from stdout, and a stopped run reported as such. Real
children: yd-version, a Python one-liner that hangs, and yd-ls against
rclone's local backend (skipped without an rclone binary).
"""

import os
import sys

import pytest

from yellowdog_cli.mcp.runner import command_argv, parse_event_documents, run
from yellowdog_cli.utils.dataclient.rclone_version import find_rclone


def _clean_env() -> dict[str, str]:
    # No YD_* leaks from the developer's shell into the child
    return {k: v for k, v in os.environ.items() if not k.startswith("YD_")}


def test_command_argv_runs_the_module_with_this_interpreter():
    assert command_argv("yd-compute-stop") == [
        sys.executable,
        "-m",
        "yellowdog_cli.compute_stop",
    ]


def test_yd_version_json(tmp_path):
    result = run(
        [*command_argv("yd-version"), "--json"], str(tmp_path), _clean_env(), 60
    )
    assert result.exit_code == 0 and not result.stopped
    assert isinstance(result.document, dict) and "cli" in result.document


def test_a_configuration_failure_is_a_run_with_no_document(tmp_path):
    result = run(
        [*command_argv("yd-list"), "--nc", "--nf", "--json", "work-requirements"],
        str(tmp_path),
        _clean_env(),
        60,
    )
    assert result.exit_code == 3  # ExitCode.CONFIGURATION: no key
    assert "Missing configuration data" in result.stderr
    assert result.document is None


def test_a_hanging_command_is_stopped_with_what_it_wrote(tmp_path):
    argv = [
        sys.executable,
        "-c",
        "import sys, time; print('[1,'); sys.stdout.flush(); time.sleep(30)",
    ]
    result = run(argv, str(tmp_path), _clean_env(), 1)
    assert result.stopped
    assert result.stdout.startswith("[1,")
    assert result.document is None
    assert result.exit_code != 0


def test_stdin_is_closed(tmp_path):
    argv = [sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"]
    result = run(argv, str(tmp_path), _clean_env(), 10)
    assert result.stdout.strip() == "''"


def test_the_working_directory_is_the_childs(tmp_path):
    argv = [sys.executable, "-c", "import os; print(os.getcwd())"]
    result = run(argv, str(tmp_path), _clean_env(), 10)
    assert os.path.realpath(result.stdout.strip()) == os.path.realpath(str(tmp_path))


def test_the_environment_is_the_childs(tmp_path):
    argv = [
        sys.executable,
        "-c",
        "import os; print(os.environ.get('YD_PROBE', 'unset'))",
    ]
    result = run(argv, str(tmp_path), {**_clean_env(), "YD_PROBE": "yes"}, 10)
    assert result.stdout.strip() == "yes"


def test_undecodable_output_is_replaced_not_raised(tmp_path):
    # 0xff is invalid UTF-8, and 0x81 is undefined in cp1252 too, so the
    # output is undecodable under either locale encoding
    argv = [
        sys.executable,
        "-c",
        "import sys; sys.stdout.buffer.write(b'[1]\\xff\\x81')",
    ]
    result = run(argv, str(tmp_path), _clean_env(), 10)
    assert result.exit_code == 0
    assert "\ufffd" in result.stdout


def test_a_missing_executable_is_a_run_that_failed(tmp_path):
    result = run(["/no/such/yd-command"], str(tmp_path), _clean_env(), 10)
    assert result.exit_code != 0 and "No such file" in result.stderr


class TestEventDocuments:
    def test_indented_documents_one_after_another(self):
        text = '{\n  "a": 1\n}\n{\n  "a": 2\n}\n'
        assert parse_event_documents(text) == [{"a": 1}, {"a": 2}]

    def test_a_partial_last_document_is_dropped(self):
        assert parse_event_documents('{"a": 1}\n{"a": ') == [{"a": 1}]

    def test_nothing_is_an_empty_list(self):
        assert parse_event_documents("") == []
        assert parse_event_documents("   \n") == []


@pytest.mark.skipif(find_rclone() is None, reason="needs an rclone binary")
def test_yd_ls_json_on_the_local_backend(tmp_path):
    (tmp_path / "ns" / "tag").mkdir(parents=True)
    (tmp_path / "ns" / "tag" / "a.txt").write_text("hello")
    env = {
        **_clean_env(),
        "YD_DATA_CLIENT_REMOTE": "loc,type=local",
        "YD_NAMESPACE": "ns",
        "YD_TAG": "tag",
    }
    result = run(
        [*command_argv("yd-ls"), "--nc", "--nf", "--json"], str(tmp_path), env, 60
    )
    assert result.exit_code == 0, result.stderr
    names = [entry["Name"] for entry in result.document]
    assert names == ["a.txt"]


def test_command_argv_uses_the_entry_point_module():
    # 'yd-commander' runs yellowdog_cli.commander.launcher, which no rule on
    # the name gives
    assert command_argv("yd-commander")[2] == "yellowdog_cli.commander.launcher"
    with pytest.raises(ValueError):
        command_argv("yd-no-such-command")


def test_the_child_writes_utf8(tmp_path):
    result = run(
        [sys.executable, "-c", "import os; print(os.environ['PYTHONIOENCODING'])"],
        str(tmp_path),
        _clean_env(),
        30,
    )
    assert result.stdout.strip() == "utf-8"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_a_stop_kills_what_the_command_started(tmp_path):
    """
    A data client command's rclone went on transferring after the call was
    reported stopped: the stop killed the command alone. Its whole process
    group is killed now, and the result comes back although the grandchild
    held the output pipe open.
    """
    marker = tmp_path / "written-after-the-stop"
    grandchild = (
        "import time, pathlib; time.sleep(3);"
        f" pathlib.Path({str(marker)!r}).write_text('x')"
    )
    script = (
        "import subprocess, sys, time;"
        f" subprocess.Popen([sys.executable, '-c', {grandchild!r}]);"
        " print('started', flush=True); time.sleep(60)"
    )
    from time import monotonic, sleep

    started = monotonic()
    result = run([sys.executable, "-c", script], str(tmp_path), _clean_env(), 1)
    assert result.stopped
    assert "started" in result.stdout
    assert monotonic() - started < 10, "the stop waited on the grandchild"
    sleep(4)
    assert not marker.exists(), "the grandchild survived the stop"
