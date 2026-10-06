"""
System tests: Work Requirement control commands — hold, start, finish, cancel.

These tests submit a WR to the live platform and exercise state-transition
commands without provisioning compute. The WR stays PENDING (no matching
workers), so the commands are fast and cheap.

Run with: pytest --run-system tests/test_system_cancel_hold_finish.py
"""

import pytest
from cli_test_helpers import shell

SYSTEM_DIR = "tests/system"
NAMESPACE = "pytest-system"


_WR_STATUSES = (
    "PENDING",
    "RUNNING",
    "HELD",
    "FINISHING",
    "COMPLETING",
    "COMPLETED",
    "CANCELLING",
    "CANCELLED",
    "FAILED",
)


def _wr_status(tag: str) -> str:
    """
    Return the current status string of the WR matching tag in NAMESPACE.

    Filters yd-list to exactly one WR via tag+namespace, then scans the full
    output for the first known status word. Log messages never contain WR
    status words, so no false positives from the surrounding log output.
    """
    result = shell(
        f"cd {SYSTEM_DIR} && yd-list work-requirements -n={NAMESPACE} -t={tag}"
    )
    output = result.stdout + result.stderr
    for status in _WR_STATUSES:
        if status in output:
            return status
    return ""


@pytest.mark.system
class TestWRControlCommands:
    def test_hold_start_cancel(self, system_tag, cleanup):
        tag = system_tag

        # Register upfront cleanup
        cleanup(f"cd {SYSTEM_DIR} && yd-cancel -y -t={tag} -n={NAMESPACE}")

        # Submit a WR that will stay PENDING (no matching worker pool)
        result = shell(f"cd {SYSTEM_DIR} && yd-submit wr_trivial.json -t={tag}")
        assert result.exit_code == 0, (
            f"yd-submit failed:\n{result.stdout}\n{result.stderr}"
        )

        # Hold
        result = shell(f"cd {SYSTEM_DIR} && yd-hold -y -t={tag} -n={NAMESPACE}")
        assert result.exit_code == 0, (
            f"yd-hold failed:\n{result.stdout}\n{result.stderr}"
        )
        assert _wr_status(tag) == "HELD", f"Expected HELD, got: {_wr_status(tag)}"

        # Start (releases the hold)
        result = shell(f"cd {SYSTEM_DIR} && yd-start -y -t={tag} -n={NAMESPACE}")
        assert result.exit_code == 0, (
            f"yd-start failed:\n{result.stdout}\n{result.stderr}"
        )
        status = _wr_status(tag)
        assert status in (
            "PENDING",
            "RUNNING",
        ), f"Expected PENDING or RUNNING after start, got: {status}"

        # Cancel
        result = shell(f"cd {SYSTEM_DIR} && yd-cancel -y -t={tag} -n={NAMESPACE}")
        assert result.exit_code == 0, (
            f"yd-cancel failed:\n{result.stdout}\n{result.stderr}"
        )
        status = _wr_status(tag)
        assert status in (
            "CANCELLING",
            "CANCELLED",
        ), f"Expected CANCELLING or CANCELLED, got: {status}"

    def test_finish(self, system_tag, cleanup):
        tag = system_tag

        # Register upfront cleanup
        cleanup(f"cd {SYSTEM_DIR} && yd-cancel -y -t={tag} -n={NAMESPACE}")

        # Submit
        result = shell(f"cd {SYSTEM_DIR} && yd-submit wr_trivial.json -t={tag}")
        assert result.exit_code == 0, (
            f"yd-submit failed:\n{result.stdout}\n{result.stderr}"
        )

        # Finish — transitions WR to FINISHING (no new tasks dispatched).
        # With no workers, the WR may move directly to COMPLETING/COMPLETED.
        result = shell(f"cd {SYSTEM_DIR} && yd-finish -y -t={tag} -n={NAMESPACE}")
        assert result.exit_code == 0, (
            f"yd-finish failed:\n{result.stdout}\n{result.stderr}"
        )
        status = _wr_status(tag)
        assert status not in (
            "PENDING",
            "RUNNING",
            "HELD",
        ), f"Expected WR to leave active state after finish, got: {status}"
