"""
Tests that run the standard demos.
Use 'pytest --run-demos', otherwise these will be skipped.
"""

import pytest
from cli_test_helpers import shell

DEMO_DIR = "../python-examples-demos"
NEXTFLOW = "/Users/pwt/nextflow/nextflow"

# Wall-clock budget for any single 'yd-*' command in a demo. A demo that exceeds
# it has hung rather than merely run long: a Work Requirement that is never
# allocated -- an image carrying an Agent version the platform will not schedule
# to, say -- sits WAITING indefinitely, and neither '-E' nor a WR 'taskTimeout'
# ever fires, because no task ever reaches EXECUTING.
DEMO_TIMEOUT = 900  # seconds


def _timed(command: str, timeout: int = DEMO_TIMEOUT) -> str:
    """
    Run a single command under a wall-clock timeout, exiting 124 if it expires.

    Applied per command, never to a compound 'sh -c "a && b"': 'timeout' signals
    its direct child, which for a compound command is the shell, and the shell
    does not pass the signal on -- leaving the real command orphaned, still
    following a Work Requirement that cleanup is deleting underneath it.
    """
    return f"timeout {timeout} {command}"


def _with_cleanup(work: str, cleanup: str) -> str:
    """
    Run 'work', then 'cleanup' whatever the outcome, exiting with work's code.

    Cleanup sits outside the timeout and off the '&&' chain deliberately: it
    terminates real cloud instances, so it has to run when the work fails and
    when it hangs, not only when it succeeds.
    """
    return f"{work}; rc=$?; {cleanup}; exit $rc"


# Terminate the Worker Pool and delete the objects the demo uploaded.
CLEANUP = "yd-terminate -y; yd-delete -Ry '{{tag}}*'"

# Provision, then submit and follow with '-E' (--exit-on-failure), which exits
# non-zero if the WR ends FAILED/CANCELLED, so a WR that does not complete
# successfully fails the test. The WR's exit code is surfaced via 'exit $rc'.
CMD_SEQ = _with_cleanup(
    f"{_timed('yd-provision')} && {_timed('yd-submit -f -E')}", CLEANUP
)

_STANDARD_DEMOS = [
    "bash",
    "bash/gce-instance-groups",
    "batch-allocation",
    "blender-2",
    "cmd.exe",
    "common-factors-csv",
    "image-montage",
    "montecarlo",
    "powershell",
    "primes",
]


@pytest.mark.demos
class TestDemos:
    @pytest.mark.parametrize("demo", _STANDARD_DEMOS)
    def test_demo(self, demo: str):
        result = shell(f"cd {DEMO_DIR}/{demo} && {CMD_SEQ}")
        assert result.exit_code == 0

    def test_cmd_modelled_on_premise(self):
        cmd_seq = _with_cleanup(
            f"{_timed('yd-instantiate')} && sleep 120", "yd-terminate -y"
        )
        result = shell(f"cd {DEMO_DIR}/modelled-on-premise && {cmd_seq}")
        assert result.exit_code == 0

    def test_video_demo(self):
        cmd_seq = _with_cleanup(
            f"{_timed('yd-provision -v instances=1 -v max_nodes=1')} && "
            f"{_timed('yd-submit -C 1 -f -E')}",
            CLEANUP,
        )
        result = shell(f"cd {DEMO_DIR}/video-demo && {cmd_seq}")
        assert result.exit_code == 0

    # def test_nextflow_image_montage(self):
    #     result = shell(
    #         f"cd {DEMO_DIR}/nextflow/image-montage && {NEXTFLOW} main.nf "
    #         "&& cd .. && ./cleanup.sh"
    #     )
    #     assert result.exit_code == 0

    # def test_nextflow_salmon_rna(self):
    #     result = shell(
    #         f"cd {DEMO_DIR}/nextflow/salmon-rna && {NEXTFLOW} main.nf "
    #         "&& cd .. && ./cleanup.sh"
    #     )
    #     assert result.exit_code == 0


class TestDemoCommandHarness:
    """
    The shell idioms the demo commands are built from, exercised with stub
    commands rather than 'yd-*' ones. Deliberately unmarked, so these run in the
    standard suite: they provision nothing, and they guard both the coreutils
    'timeout' dependency and the contract that cleanup always runs.
    """

    def test_cleanup_runs_when_work_fails(self):
        result = shell(_with_cleanup("false", "echo CLEANED"))
        assert result.exit_code == 1
        assert "CLEANED" in result.stdout

    def test_cleanup_runs_when_work_succeeds(self):
        result = shell(_with_cleanup("true", "echo CLEANED"))
        assert result.exit_code == 0
        assert "CLEANED" in result.stdout

    def test_hung_work_times_out_and_still_cleans_up(self):
        result = shell(_with_cleanup(_timed("sleep 30", timeout=1), "echo CLEANED"))
        # 124 rather than 1, so a hang is distinguishable from a failed WR
        assert result.exit_code == 124
        assert "CLEANED" in result.stdout

    def test_timed_out_command_short_circuits_the_rest_of_the_work(self):
        work = f"{_timed('sleep 30', timeout=1)} && echo SUBMITTED"
        result = shell(_with_cleanup(work, "echo CLEANED"))
        assert result.exit_code == 124
        assert "SUBMITTED" not in result.stdout
        assert "CLEANED" in result.stdout
