"""
What the '--debug' trace says a command did, run as a user runs it: 'yd' in
a subprocess, with a configuration and files of the test's own, nothing
reaching the Platform (dry runs). The trace's own form is test_debug_log.py's
and its secrets test_debug_secrets.py's; this file holds what it reports.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

TRACE_LINE = re.compile(
    r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?: \(\d+\))? : DEBUG : \[\+\d+\.\d{3}s\] (\S+): (.*)$"
)

CONFIG = """
[common]
namespace = "image-processing"
tag = "render"
"""


def _trace(args: list[str], cwd: Path) -> list[tuple[str, str]]:
    """
    Run 'yd <args> --debug' in 'cwd', check it succeeded, and return its
    trace as (module, message) pairs.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("YD_")}
    env.update({"YD_KEY": "a-key", "YD_SECRET": "a-secret"})
    result = subprocess.run(
        [sys.executable, "-m", "yellowdog_cli.yd", *args, "--debug"],
        capture_output=True,
        encoding="utf-8",
        env=env,
        cwd=cwd,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return [
        (m.group(1), m.group(2))
        for line in result.stderr.splitlines()
        if (m := TRACE_LINE.match(line))
    ]


def _messages(trace: list[tuple[str, str]], module: str) -> list[str]:
    return [message for name, message in trace if name == module]


class TestFiles:
    """
    Each file a command reads is traced, by the full path it was read from,
    and so is where the files a specification names are looked for.
    """

    def test_a_submit_traces_its_specification_csv_and_task_data(self, tmp_path):
        (tmp_path / "config.toml").write_text(CONFIG, encoding="utf-8")
        work = tmp_path / "work"
        work.mkdir()
        (work / "wr.json").write_text(
            json.dumps(
                {
                    "taskGroups": [
                        {
                            "tasks": [
                                {
                                    "taskType": "bash",
                                    "arguments": ["-c", "echo <<frame>>"],
                                    "taskDataFile": "params.txt",
                                }
                            ]
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (work / "params.txt").write_text("quality=high\n", encoding="utf-8")
        (work / "frames.csv").write_text("frame\n1\n2\n3\n", encoding="utf-8")

        trace = _trace(
            [
                "workrequirement",
                "submit",
                "work/wr.json",
                "-V",
                "frames.csv",
                "--dry-run",
            ],
            tmp_path,
        )

        assert f"Reading '{work / 'wr.json'}'" in _messages(trace, "file_substitution")
        assert (
            f"Read CSV file '{work / 'frames.csv'}': 3 data row(s), headings 'frame'"
            in _messages(trace, "csv_data")
        )
        assert (
            f"Files the Work Requirement names are found from the specification's"
            f" directory, 'work'" in _messages(trace, "submit")
        )
        assert (
            f"Reading Task Data file 'params.txt' from '{work / 'params.txt'}'"
            in _messages(trace, "submit_utils")
        )

    def test_content_path_is_traced_as_where_files_are_found(self, tmp_path):
        (tmp_path / "config.toml").write_text(CONFIG, encoding="utf-8")
        (tmp_path / "wr.json").write_text(
            json.dumps(
                {
                    "taskGroups": [
                        {"tasks": [{"taskType": "bash", "taskDataFile": "p.txt"}]}
                    ]
                }
            ),
            encoding="utf-8",
        )
        data = tmp_path / "data"
        data.mkdir()
        (data / "p.txt").write_text("x\n", encoding="utf-8")

        trace = _trace(
            ["workrequirement", "submit", "wr.json", "-F", "data", "--dry-run"],
            tmp_path,
        )

        assert (
            "Files the Work Requirement names are found from --content-path, 'data'"
            in (_messages(trace, "submit"))
        )
        assert f"Reading Task Data file 'p.txt' from '{data / 'p.txt'}'" in _messages(
            trace, "submit_utils"
        )
