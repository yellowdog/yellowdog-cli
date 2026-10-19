"""
Live: a Task's inputs and outputs (taskDataInputs and taskDataOutputs, which
the Agent transfers with rclone; not the 'taskData' property) through the
instance profile. An input uploaded under the run's prefix is read by a Task
through the keyless Task remote; the Task writes the input's SHA-256 as an
output, which is downloaded and checked. Needs [data], AWS as the primary
and an instance profile; skipped otherwise.
"""

import hashlib
import secrets

import pytest
from harness import data, work

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst-actions")]


def test_a_task_reads_its_input_and_writes_its_output_through_s3(
    live_run, actions_pool, tmp_path
):
    run, yd = live_run.run, live_run.yd
    reason = data.unavailable(run.config)
    if reason:
        pytest.skip(reason)
    minutes = run.config.run["provision_timeout_minutes"]
    payload = secrets.token_bytes(4096)
    source = tmp_path / "input.bin"
    source.write_bytes(payload)
    yd(
        "data",
        "upload",
        str(source),
        "--destination",
        "task-io/input.bin",
        "--json",
        "--quiet",
    )
    with work.cancelled_after(yd) as made:
        wr = work.submit(yd, "task-io-wr.jsonnet", worker_tag=actions_pool.worker_tag)
        made.append(wr["id"])
        assert work.wait_for_status(yd, wr["id"], work.TERMINAL, minutes) == "COMPLETED"
        into = tmp_path / "out"
        into.mkdir()
        yd(
            "data",
            "download",
            "task-io/output.txt",
            "--into",
            str(into),
            "--json",
            "--quiet",
        )
        written = (into / "output.txt").read_text(encoding="utf-8")
        assert hashlib.sha256(payload).hexdigest() in written
