"""
commander/stderr_filter.py, run in a fresh interpreter because it replaces the
process's fd 2: a line holding a marker is dropped, every other line reaches
the real stderr, including one written just before exit or left without a
newline, and a faulthandler dump bypasses the filter.
"""

import subprocess
import sys
import textwrap

import pytest

TSM_LINE = (
    "2026-10-06 19:37:03.709 Python[35770:11101615] TSMSendMessageToUIServer: "
    "CFMessagePortSendRequest FAILED(-1) to send to port com.apple.tsm.uiserver"
)


def _stderr_of(body: str) -> str:
    script = textwrap.dedent(
        """
        import os, sys
        from yellowdog_cli.commander.stderr_filter import install_stderr_filter
        assert install_stderr_filter()
        """
    ) + textwrap.dedent(body)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        timeout=30,
        check=False,
    )
    return result.stderr.decode("utf-8")


def test_the_tsm_line_is_dropped_and_the_rest_kept():
    stderr = _stderr_of(
        f"""
        os.write(2, b"before\\n")
        os.write(2, {TSM_LINE!r}.encode() + b"\\n")
        os.write(2, b"after\\n")
        """
    )
    assert stderr == "before\nafter\n"


def test_a_message_printed_just_before_exit_still_appears():
    stderr = _stderr_of(
        """
        print("last words", file=sys.stderr)
        sys.exit(1)
        """
    )
    assert stderr == "last words\n"


def test_a_final_line_without_a_newline_still_appears():
    stderr = _stderr_of('os.write(2, b"no newline")\n')
    assert stderr == "no newline"


def test_a_line_split_across_writes_is_judged_whole():
    stderr = _stderr_of(
        """
        os.write(2, b"TSMSend")
        os.write(2, b"MessageToUIServer: FAILED(-1)\\nkept\\n")
        """
    )
    assert stderr == "kept\n"


@pytest.mark.crashes
def test_a_faulthandler_dump_reaches_the_real_stderr():
    stderr = _stderr_of(
        """
        import faulthandler
        faulthandler._sigsegv()  # A crash: no atexit drain, so no thread to rely on
        """
    )
    assert "Fatal Python error: Segmentation fault" in stderr
