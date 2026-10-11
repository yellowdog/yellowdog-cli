"""
System compute test: CSV-driven batch of 10 tasks.

Provisions a worker pool, submits wr_csv_batch.json with tasks.csv (10 rows),
follows to completion, and verifies all 10 tasks completed.

Run with: pytest --run-system-compute tests/test_system_csv_batch.py
"""

import pytest
from cli_test_helpers import shell

SYSTEM_DIR = "tests/system"
NAMESPACE = "pytest-system"


@pytest.mark.system_compute
class TestSystemCsvBatch:
    def test_csv_batch(self, system_tag, cleanup):
        tag = system_tag

        # Register teardown upfront
        cleanup(f"cd {SYSTEM_DIR} && yd-workerpool shutdown -y -t={tag} -n={NAMESPACE}")
        cleanup(
            f"cd {SYSTEM_DIR} && yd-computerequirement terminate -y -t={tag} -n={NAMESPACE}"
        )

        # 1. Provision the worker pool
        result = shell(f"cd {SYSTEM_DIR} && yd-workerpool provision -t={tag}")
        assert result.exit_code == 0, (
            f"yd-workerpool provision failed:\n{result.stdout}\n{result.stderr}"
        )

        # 2. Submit 10-task CSV batch and follow to completion
        result = shell(
            f"cd {SYSTEM_DIR} && yd-workrequirement submit -f wr_csv_batch.json -V tasks.csv -t={tag}"
        )
        assert result.exit_code == 0, (
            f"yd-workrequirement submit failed:\n{result.stdout}\n{result.stderr}"
        )

        # 3. Verify all 10 tasks completed
        result = shell(
            f"cd {SYSTEM_DIR} && yd-list work-requirements --nf -n={NAMESPACE} -t={tag}"
        )
        assert result.exit_code == 0
        assert "10/10" in result.stdout, f"Not all 10 tasks completed:\n{result.stdout}"
