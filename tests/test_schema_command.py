"""
yd-schema: printing, writing and checking the specification schemas
(schema.py, on ARGS_PARSER with no wrapper, like yd-doctor). Subprocess-driven,
as tests/test_doctor.py's are, in a clean environment so nothing in it is
mistaken for configuration -- yd-schema needs none.
"""

import json
import os
import subprocess
import sys

import fastjsonschema
import pytest

from yellowdog_cli.mcp.tools import build_tools
from yellowdog_cli.utils.specs.schema import Family


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("YD_")}


def _run(*args, cwd=None):
    return subprocess.run(
        ["yd-schema", *args],
        cwd=cwd,
        env=_clean_env(),
        capture_output=True,
        text=True,
    )


class TestList:
    def test_names_the_families(self):
        result = _run("--list")
        assert result.returncode == 0, result.stdout + result.stderr
        lines = result.stdout.split()
        assert lines == [f.value for f in Family]


class TestPrintOneFamily:
    @pytest.mark.parametrize("family", [f.value for f in Family])
    def test_prints_a_schema_that_compiles(self, family):
        result = _run(family)
        assert result.returncode == 0, result.stdout + result.stderr
        document = json.loads(result.stdout)
        assert document["$id"].endswith(f"{family}.schema.json")
        fastjsonschema.compile(document)  # raises on a malformed schema

    def test_prints_exactly_what_write_writes(self, tmp_path):
        target = tmp_path / "schemas"
        _run("--write", str(target))
        result = _run("resources")
        assert result.stdout == (target / "resources.schema.json").read_text()


class TestWrite:
    def test_writes_every_schema_and_an_index(self, tmp_path):
        target = tmp_path / "schemas"
        result = _run("--write", str(target))
        assert result.returncode == 0, result.stdout + result.stderr
        for family in Family:
            path = target / f"{family.value}.schema.json"
            assert path.is_file()
            document = json.loads(path.read_text())
            assert document["$id"].endswith(f"{family.value}.schema.json")
        index = json.loads((target / "index.json").read_text())
        assert index["families"] == {
            family.value: f"{family.value}.schema.json" for family in Family
        }
        assert index["cli"]
        assert index["sdk"]

    def test_a_path_that_is_a_file_is_an_error_not_a_traceback(self, tmp_path):
        target = tmp_path / "schemas"
        target.write_text("not a directory")
        result = _run("--write", str(target))
        assert result.returncode == 1
        assert "Traceback" not in result.stderr
        # Rich wraps a long path at any character, so compare without spaces
        output = "".join((result.stdout + result.stderr).split())
        assert str(target) in output and "cannotwrite" in output

    @pytest.mark.skipif(
        sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
        reason="a read-only directory is writable by root, and on Windows",
    )
    def test_an_unwritable_directory_is_an_error_not_a_traceback(self, tmp_path):
        parent = tmp_path / "read-only"
        parent.mkdir()
        parent.chmod(0o555)
        try:
            result = _run("--write", str(parent / "schemas"))
        finally:
            parent.chmod(0o755)
        assert result.returncode == 1
        assert "Traceback" not in result.stderr
        output = " ".join((result.stdout + result.stderr).split())
        assert "cannot write" in output and "Permission denied" in output


class TestCheck:
    def test_exits_zero_right_after_a_write(self, tmp_path):
        target = tmp_path / "schemas"
        _run("--write", str(target))
        result = _run("--check", str(target))
        assert result.returncode == 0, result.stdout + result.stderr

    def test_exits_one_when_the_index_is_stale(self, tmp_path):
        target = tmp_path / "schemas"
        _run("--write", str(target))
        index_path = target / "index.json"
        index = json.loads(index_path.read_text())
        index["sdk"] = "0.0.0-not-installed"
        index_path.write_text(json.dumps(index))

        result = _run("--check", str(target))

        assert result.returncode == 1
        assert "written for" in (result.stdout + result.stderr)

    @pytest.mark.parametrize("damage", ["edited", "missing"])
    def test_exits_one_when_a_schema_is_not_what_is_built(self, tmp_path, damage):
        # The index's versions alone would call this up to date
        target = tmp_path / "schemas"
        _run("--write", str(target))
        path = target / "worker-pool.schema.json"
        if damage == "edited":
            path.write_text(path.read_text().replace('"type"', '"typo"', 1))
        else:
            path.unlink()

        result = _run("--check", str(target))

        assert result.returncode == 1
        output = "".join((result.stdout + result.stderr).split())
        assert "worker-pool.schema.json" in output


class TestNoSdkAtStart:
    def test_list_does_not_import_the_sdk(self):
        # The SDK's version comes from its package metadata: importing
        # anything from yellowdog_client builds the whole Platform client
        probe = (
            "import sys; sys.argv = ['yd-schema', '--list'];"
            " import yellowdog_cli.schema as s; s.main();"
            " print('SDK' if 'yellowdog_client' in sys.modules else 'none')"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            env=_clean_env(),
            capture_output=True,
            text=True,
        )
        assert result.stdout.split()[-1] == "none", result.stdout + result.stderr


class TestArgumentErrors:
    def test_no_mode_at_all_is_a_usage_error(self):
        result = _run()
        assert result.returncode == 2, result.stdout + result.stderr

    def test_a_family_and_list_together_is_a_usage_error(self):
        result = _run("resources", "--list")
        assert result.returncode == 2, result.stdout + result.stderr


class TestHelp:
    def test_mentions_no_configuration(self):
        result = _run("--help")
        assert result.returncode == 0, result.stdout + result.stderr
        lowered = result.stdout.lower()
        for word in ("--key", "--secret", "--config", "--url", "namespace", "--tag"):
            assert word not in lowered, word


class TestMcpTool:
    def test_yd_schema_has_a_family_enum_argument(self):
        tools = {t.name: t for t in build_tools()}
        tool = tools["yd_schema"]
        family_schema = tool.input_schema["properties"]["family"]
        assert set(family_schema["enum"]) == {f.value for f in Family}


class TestHelpListing:
    def test_yd_help_lists_yd_schema(self):
        result = subprocess.run(
            ["yd-help", "--json"],
            env=_clean_env(),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        names = {row["command"] for row in json.loads(result.stdout)}
        assert "yd-schema" in names
