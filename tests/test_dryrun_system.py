"""
End-to-end dry-run tests. Marked 'system' because they contact the platform to
list entities (they need credentials in the environment / CI). Empty namespace
and tag are used so the matching set is empty and nothing could be acted on.
"""

import json

import pytest
from cli_test_helpers import shell


@pytest.mark.system
@pytest.mark.parametrize("cmd", ["yd-cancel", "yd-shutdown", "yd-terminate"])
def test_dry_run_runs_and_exits_zero(cmd):
    assert shell(f"{cmd} -D -n='' -t=''").exit_code == 0


@pytest.mark.system
@pytest.mark.parametrize("cmd", ["yd-cancel", "yd-shutdown", "yd-terminate"])
def test_dry_run_json_is_valid(cmd):
    result = shell(f"{cmd} -D --json -n='' -t=''")
    assert result.exit_code == 0
    json.loads(result.stdout)  # a JSON array (possibly empty)
