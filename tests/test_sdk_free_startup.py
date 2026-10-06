"""
The commands that never use a Platform client -- yd-variables and the data
client commands -- run without importing the YellowDog SDK, whose package
__init__ builds the whole client (~140ms of every start). Each command's
real main() runs in a fresh interpreter, which records at exit whether
'yellowdog_client' (and 'requests') were ever imported; a module-level SDK
import anywhere on the path, or one on a path the command takes at run time,
fails here rather than quietly costing every start its 140ms again.
"""

import json
import os
import subprocess
import sys

import pytest

from yellowdog_cli.utils.dataclient.rclone_version import find_rclone

PROBE = """
import atexit, json, sys
record, module, *argv = sys.argv[1:]
sys.argv = argv

def _record():
    with open(record, "w") as f:
        json.dump(
            {
                "sdk": "yellowdog_client" in sys.modules,
                "requests": "requests" in sys.modules,
            },
            f,
        )

atexit.register(_record)
__import__(module, fromlist=["main"]).main()
"""

COMMON = '[common]\nnamespace = "ns"\ntag = "tag"\n'
SDK_BACKED_SECTIONS = "[workRequirement]\ntaskCount = 1\n[workerPool]\nmaxNodes = 2\n"


def _loaded(tmp_path, module: str, argv: list[str], config: str) -> dict:
    (tmp_path / "config.toml").write_text(config)
    record = tmp_path / "loaded.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith("YD_")}
    env.update({"YD_KEY": "a-key", "YD_SECRET": "a-secret"})
    result = subprocess.run(
        [sys.executable, "-c", PROBE, str(record), module, *argv],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=120,
    )
    assert record.exists(), result.stdout + result.stderr
    return {**json.loads(record.read_text()), "returncode": result.returncode}


class TestVariables:
    def test_commanders_discovery_loads_no_sdk(self, tmp_path):
        # Commander runs 'yd-variables --quiet'; the SDK-backed sections'
        # schema is never built, since '--quiet' shows no warning
        loaded = _loaded(
            tmp_path,
            "yellowdog_cli.variables",
            ["yd-variables", "--quiet"],
            COMMON + SDK_BACKED_SECTIONS,
        )
        assert loaded == {"sdk": False, "requests": False, "returncode": 0}

    def test_a_config_with_no_sdk_backed_section_loads_no_sdk(self, tmp_path):
        loaded = _loaded(tmp_path, "yellowdog_cli.variables", ["yd-variables"], COMMON)
        assert loaded == {"sdk": False, "requests": False, "returncode": 0}

    def test_checking_an_sdk_backed_section_does_load_it(self, tmp_path):
        # The control: the probe sees the SDK when something does load it
        loaded = _loaded(
            tmp_path,
            "yellowdog_cli.variables",
            ["yd-variables"],
            COMMON + SDK_BACKED_SECTIONS,
        )
        assert loaded["sdk"] is True


@pytest.mark.skipif(find_rclone() is None, reason="rclone is not installed")
class TestDataClient:
    """
    Every data client command, each doing its work on a local remote: an
    import of the SDK on any of their paths -- interactive.py's, for
    yd-delete's confirmation, was one -- fails here.
    """

    CONFIG = COMMON + '[dataClient]\nremote = "loc,type=local"\nbucket = "store"\n'

    @pytest.fixture
    def store(self, tmp_path):
        (tmp_path / "store" / "ns" / "tag").mkdir(parents=True)
        (tmp_path / "store" / "ns" / "tag" / "a.txt").write_text("a")
        (tmp_path / "local.txt").write_text("l")
        return tmp_path

    @pytest.mark.parametrize(
        "module, argv",
        [
            ("yellowdog_cli.ls", ["yd-ls", "--json"]),
            ("yellowdog_cli.upload", ["yd-upload", "--json", "local.txt"]),
            ("yellowdog_cli.download", ["yd-download", "--json", "a.txt", "-d", "out"]),
            ("yellowdog_cli.delete", ["yd-delete", "--json", "-y", "a.txt"]),
            ("yellowdog_cli.copy", ["yd-copy", "--json", "a.txt", "b.txt"]),
        ],
    )
    def test_a_command_loads_no_sdk(self, store, module, argv):
        loaded = _loaded(store, module, argv, self.CONFIG)
        assert loaded["returncode"] == 0, module  # It did its work
        assert loaded["sdk"] is False, module

    def test_a_failure_loads_no_sdk(self, store):
        # The failure path too: the exit code is classified and the '--json'
        # result flushed without the SDK's exception classes or its Json
        loaded = _loaded(
            store, "yellowdog_cli.ls", ["yd-ls", "--json", "no-such-path"], self.CONFIG
        )
        assert loaded["returncode"] == 1
        assert loaded["sdk"] is False
