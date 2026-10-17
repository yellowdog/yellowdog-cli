"""
'yd workrequirement submit -V <csv>' end to end, offline: the real command,
run with '--dry-run --json', turns a prototype Task and a CSV file into one
Task per row, each with its row's values, and a '{{...}}' variable in a cell
substituted afterwards. The pieces are unit tested on their own
(test_csv_data.py, test_submit_inputs.py); this holds them together.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

PROTOTYPE = {
    "name": "csv-wr",
    "taskGroups": [
        {
            "name": "tg",
            "taskType": "bash",
            "tasks": [
                {
                    "name": "row-<<n>>",
                    "arguments": ["<<word>>", "<<where>>"],
                    "environment": {"N": "<<n>>"},
                }
            ],
        }
    ],
}


def _submit(directory: Path, *args: str) -> dict:
    """
    Run 'yd wr submit --dry-run --json' in the directory, with its own
    configuration and dummy credentials, and return the document it prints.
    """
    (directory / "config.toml").write_text(
        '[common]\nnamespace = "ns-csv"\ntag = "t-csv"\n', encoding="utf-8"
    )
    # The shell's own YD_* (credentials, YD_VAR_* variables) never reach it
    environment = {k: v for k, v in os.environ.items() if not k.startswith("YD_")}
    environment.update(YD_KEY="dummy-key", YD_SECRET="dummy-secret")
    completed = subprocess.run(
        [
            sys.executable,
            *("-m", "yellowdog_cli.yd", "wr", "submit"),
            *args,
            *("--dry-run", "--json", "--quiet"),
        ],
        cwd=directory,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_each_csv_row_becomes_a_task_with_its_values(tmp_path):
    (tmp_path / "wr.json").write_text(json.dumps(PROTOTYPE), encoding="utf-8")
    rows = [
        (n, f"word-{n}", "{{namespace}}" if n == 1 else f"place-{n}")
        for n in range(1, 11)
    ]
    (tmp_path / "tasks.csv").write_text(
        "n,word,where\n" + "".join(f"{n},{w},{p}\n" for n, w, p in rows),
        encoding="utf-8",
    )

    document = _submit(tmp_path, "wr.json", "-V", "tasks.csv")

    (task_group,) = document["taskGroups"]
    tasks = task_group["tasks"]
    assert len(tasks) == 10
    for task, (n, word, place) in zip(tasks, rows):
        assert task["name"] == f"row-{n}"
        assert task["taskType"] == "bash"  # Inherited from the Task Group
        assert task["environment"] == {"N": str(n)}
        # A '{{...}}' variable in a cell is substituted after the CSV pass
        expected_place = "ns-csv" if place == "{{namespace}}" else place
        assert task["arguments"] == [word, expected_place]
    assert document["namespace"] == "ns-csv"
    assert document["tag"] == "t-csv"


def test_each_task_group_takes_its_own_csv_file(tmp_path):
    prototype = json.loads(json.dumps(PROTOTYPE))
    second = json.loads(json.dumps(prototype["taskGroups"][0]))
    second["name"] = "tg-2"
    prototype["taskGroups"].append(second)
    (tmp_path / "wr.json").write_text(json.dumps(prototype), encoding="utf-8")
    (tmp_path / "first.csv").write_text(
        "n,word,where\n1,a,x\n2,b,y\n", encoding="utf-8"
    )
    (tmp_path / "second.csv").write_text("n,word,where\n3,c,z\n", encoding="utf-8")

    document = _submit(tmp_path, "wr.json", "-V", "first.csv", "-V", "second.csv")

    first, second = document["taskGroups"]
    assert [t["name"] for t in first["tasks"]] == ["row-1", "row-2"]
    assert [t["arguments"] for t in first["tasks"]] == [["a", "x"], ["b", "y"]]
    assert [t["name"] for t in second["tasks"]] == ["row-3"]
    assert second["tasks"][0]["arguments"] == ["c", "z"]
