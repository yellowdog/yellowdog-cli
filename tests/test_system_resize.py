"""
System compute test: Worker Pool resize.

Provisions a pool with 1 node, resizes to 2, verifies the target instance
count changes in yd list compute-requirements output, then tears down.

Run with: pytest --run-system-compute tests/test_system_resize.py
"""

import time

import pytest
from cli_test_helpers import shell

SYSTEM_DIR = "tests/system"
NAMESPACE = "pytest-system"


def _resize_with_retry(wp_id: str, target: int, timeout: int = 600) -> bool:
    """
    Attempt yd workerpool resize, retrying every 30 s if the pool is still
    awaiting nodes.

    The platform rejects a resize while a pool is registering its initial nodes;
    retrying is the most reliable way to wait out that transient state.
    Returns True once the resize succeeds, False if timeout elapses first.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = shell(f"cd {SYSTEM_DIR} && yd workerpool resize -y {wp_id} {target}")
        if result.exit_code == 0:
            return True
        combined = result.stdout + result.stderr
        if "awaiting nodes" not in combined:
            # Unexpected error — surface it immediately rather than spinning.
            return False
        time.sleep(30)
    return False


@pytest.mark.system_compute
class TestSystemResize:
    def test_resize(self, system_tag, cleanup):
        tag = system_tag

        # Register teardown
        cleanup(f"cd {SYSTEM_DIR} && yd workerpool shutdown -y -t={tag} -n={NAMESPACE}")
        cleanup(
            f"cd {SYSTEM_DIR} && yd computerequirement terminate -y -t={tag} -n={NAMESPACE}"
        )

        # 1. Provision with 1 node (no -f: following runs to auto-shutdown).
        # --quiet returns just the Worker Pool YDID on stdout.
        result = shell(f"cd {SYSTEM_DIR} && yd workerpool provision -q -t={tag}")
        assert result.exit_code == 0, (
            f"yd workerpool provision failed:\n{result.stdout}\n{result.stderr}"
        )
        wp_id = result.stdout.strip()

        # 2. Resize to 2 nodes, retrying until the pool is no longer awaiting nodes.
        assert _resize_with_retry(wp_id, 2), (
            f"yd workerpool resize did not succeed within timeout for {wp_id}"
        )

        # 3. Verify the target instance count changed to 2 in yd list compute-requirements.
        # The compute requirement table shows "STATUS (target/expected/alive)",
        # so after resize the target column will read "2".
        result = shell(
            f"cd {SYSTEM_DIR} && yd list compute-requirements --nf -n={NAMESPACE} -t={tag}"
        )
        assert result.exit_code == 0
        assert "(2/" in result.stdout, (
            f"Target instance count not updated to 2:\n{result.stdout}"
        )
