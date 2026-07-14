"""
Tests that run the standard demos.
Use 'pytest --run-demos', otherwise these will be skipped.
"""

import pytest
from cli_test_helpers import shell

DEMO_DIR = "../python-examples-demos"

# Provision, then submit and follow with '-E' (--exit-on-failure), which exits
# non-zero if the WR ends FAILED/CANCELLED, so a WR that does not complete
# successfully fails the test. Cleanup (terminate/delete) always runs regardless
# of the WR outcome, and the WR's exit code is surfaced via 'exit $rc'.
CMD_SEQ = (
    "yd-provision && yd-submit -f -E; "
    "rc=$?; yd-terminate -y; yd-delete -Ry '{{tag}}*'; exit $rc"
)
NEXTFLOW = "/Users/pwt/nextflow/nextflow"

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
        result = shell(
            f"cd {DEMO_DIR}/modelled-on-premise && yd-instantiate "
            "&& sleep 120 && yd-terminate -y"
        )
        assert result.exit_code == 0

    def test_video_demo(self):
        result = shell(
            f"cd {DEMO_DIR}/video-demo && yd-provision -v instances=1 -v max_nodes=1 "
            "&& yd-submit -C 1 -f -E; "
            "rc=$?; yd-terminate -y; yd-delete -Ry '{{tag}}*'; exit $rc"
        )
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
