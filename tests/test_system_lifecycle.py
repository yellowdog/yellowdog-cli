"""
System compute test: minimal end-to-end lifecycle.

Provisions a single worker pool, submits a trivial Work Requirement
(echo hello), follows it to completion, verifies the WR completed, then
shuts down and terminates the pool.

Run with: pytest --run-system-compute tests/test_system_lifecycle.py

Prerequisites: YD_KEY, YD_SECRET (and optionally YD_URL, CONFIG) must be set
in the environment, or a config.toml must be present. The CONFIG variable
selects which imported config to use (defaults to 'test').

This test provisions a real cloud instance and may take 10-20 minutes.
"""

import pytest
from cli_test_helpers import shell

SYSTEM_DIR = "tests/system"
NAMESPACE = "pytest-system"


@pytest.mark.system_compute
class TestSystemLifecycle:
    def test_lifecycle(self, system_tag, cleanup):
        tag = system_tag

        # Register teardown upfront so cleanup runs even on failure.
        # Reversed order: terminate runs before shutdown in fixture teardown,
        # but both are idempotent so ordering doesn't matter for cleanup.
        cleanup(f"cd {SYSTEM_DIR} && yd workerpool shutdown -y -t={tag} -n={NAMESPACE}")
        cleanup(
            f"cd {SYSTEM_DIR} && yd computerequirement terminate -y -t={tag} -n={NAMESPACE}"
        )

        # 1. Provision the worker pool; -q returns just the YDID on stdout.
        result = shell(f"cd {SYSTEM_DIR} && yd workerpool provision -q -t={tag}")
        assert result.exit_code == 0 and result.stdout.strip(), (
            f"yd workerpool provision failed:\n{result.stdout}\n{result.stderr}"
        )

        # 2. Submit trivial WR and follow to completion.
        # -f blocks until all tasks finish; exit 0 means COMPLETED.
        # Provisioning + agent startup typically takes 5-15 minutes.
        result = shell(
            f"cd {SYSTEM_DIR} && yd workrequirement submit -f wr_trivial.json -t={tag}"
        )
        assert result.exit_code == 0, (
            f"yd workrequirement submit failed:\n{result.stdout}\n{result.stderr}"
        )

        # 3. Confirm WR shows COMPLETED in yd list
        result = shell(
            f"cd {SYSTEM_DIR} && yd list work-requirements --nf -n={NAMESPACE} -t={tag}"
        )
        assert result.exit_code == 0
        assert "COMPLETED" in result.stdout, (
            f"WR not COMPLETED in yd list:\n{result.stdout}"
        )
