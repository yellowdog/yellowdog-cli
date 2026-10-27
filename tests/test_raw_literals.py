"""
'{{raw:...}}', which gives the text inside it, with its delimiters, as written:
'{{raw:site}}' is the literal '{{site}}', whatever 'site' is.

The engine writes that text with markers in place of its delimiters, so that
no later pass substitutes it -- a Work Requirement is resolved as it loads,
once it is named, and for each Task Group and Task -- and literal_text() puts
them back where a value leaves the CLI. The engine's part is tested first;
then each of those places, through the real commands' dry runs where they
have one, each output checked for a marker that was never put back.
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest

import yellowdog_cli.utils.file_substitution as file_module
import yellowdog_cli.utils.variable_substitution as var_module
from yellowdog_cli.utils.config_types import ConfigDataClient
from yellowdog_cli.utils.dataclient.operations import resolve_remote_path
from yellowdog_cli.utils.variable_substitution import (
    literal_text,
    resolve_variables_in_string,
    resolve_variables_insitu,
)

MARKERS = (var_module._RAW_OPENING, var_module._RAW_CLOSING)


@pytest.fixture(autouse=True)
def table(monkeypatch):
    monkeypatch.setattr(var_module, "VARIABLE_SUBSTITUTIONS", {"site": "lon"})
    monkeypatch.setattr(var_module, "_DEFINITIONS", {"site": "lon"})


@pytest.fixture()
def warnings(monkeypatch) -> MagicMock:
    monkeypatch.setattr(var_module, "_UNDEFINED_VARIABLE_WARNINGS", True)
    monkeypatch.setattr(var_module, "_UNDEFINED_VARIABLES_REPORTED", set())
    warning = MagicMock()
    monkeypatch.setattr(var_module, "print_warning", warning)
    return warning


def _literal(text: str) -> object:
    return literal_text(resolve_variables_in_string(text, source="test"))


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


class TestTheText:
    @pytest.mark.parametrize(
        "written, text",
        [
            ("{{raw:site}}", "{{site}}"),
            ("a {{raw:site}} {{site}}", "a {{site}} lon"),
            ("{{raw:nope}}", "{{nope}}"),
            # The syntax inside is text too
            ("{{raw:num:site}}", "{{num:site}}"),
            ("{{raw:site:=x}}", "{{site:=x}}"),
            ("{{raw:site::}}", "{{site::}}"),
            ("{{raw:env:HOME}}", "{{env:HOME}}"),
            ("{{raw:}}", "{{}}"),
            # A nested expression is taken as written, not substituted
            ("{{raw:a_{{site}}}}", "{{a_{{site}}}}"),
            # As a default, used where the variable is undefined
            ("{{nope:={{raw:site}}}}", "{{site}}"),
            ("{{site:={{raw:x}}}}", "lon"),
            # Text that is no expression of ours is left as it was
            ("{{ .Values.site }}", "{{ .Values.site }}"),
        ],
    )
    def test_is_written_as_it_stands(self, written, text):
        assert _literal(written) == text

    def test_a_type_tag_before_it_is_refused_naming_the_way_round(self):
        with pytest.raises(ValueError) as e:
            resolve_variables_in_string("{{num:raw:x}}")
        assert str(e.value) == (
            "Cannot substitute '{{num:raw:x}}': 'raw:' gives text, which has no"
            " type; to write the text '{{num:x}}', write '{{raw:num:x}}'"
        )

    def test_the_markers_stand_until_put_back(self):
        value = resolve_variables_in_string("{{raw:site}}")
        assert isinstance(value, str)
        assert "{{" not in value and all(marker in value for marker in MARKERS)


class TestEveryPassLeavesIt:
    def test_repeated_passes_never_substitute_it(self):
        # What 'yd workrequirement submit' does: a pass as the file loads,
        # another once the Work Requirement is named, more for each Task
        data = {"args": ["{{raw:site}}"], "env": {"A": "{{raw:site}} {{site}}"}}
        for _ in range(3):
            resolve_variables_insitu(data)
        assert literal_text(data) == {
            "args": ["{{site}}"],
            "env": {"A": "{{site}} lon"},
        }

    def test_it_is_neither_circular_nor_undefined(self, warnings):
        # The literal names a defined variable and an undefined one, either
        # of which left unsubstituted would otherwise be reported
        data = {"a": "{{raw:site}}", "b": "{{raw:nope}}"}
        resolve_variables_insitu(data)
        assert warnings.call_count == 0

    def test_a_variable_holding_it_holds_it_marked(self):
        var_module.add_substitutions_without_overwriting({"keep": "{{raw:site}}"})
        assert var_module.get_user_variable("keep") == "{{site}}"
        marked = var_module.get_user_variable("keep", literal=False)
        assert marked is not None and "{{" not in marked
        assert var_module.get_all_user_variables()["keep"] == "{{site}}"
        data = {"a": "{{keep}}"}
        for _ in range(3):
            resolve_variables_insitu(data)
        assert literal_text(data) == {"a": "{{site}}"}

    def test_under_the_worker_pool_delimiters(self):
        # Plain '{{raw:site}}' in User Data is Mustache's business, not ours
        data = {"userData": "__{{raw:site}}__ __{{site}}__ {{raw:site}}"}
        resolve_variables_insitu(data)
        assert literal_text(data) == {"userData": "__{{site}}__ lon {{raw:site}}"}

    def test_in_file_contents(self, warnings):
        text = file_module.process_variable_substitutions_in_file_contents(
            "echo {{raw:site}} {{site}}\n", source="script.sh"
        )
        var_module.warn_of_undefined_variables({"script.sh": text})
        assert literal_text(text) == "echo {{site}} lon\n"
        assert warnings.call_count == 0

    def test_through_jsonnet_evaluation(self, tmp_path):
        pytest.importorskip("_jsonnet")
        spec = tmp_path / "spec.jsonnet"
        spec.write_text(
            "{ a: '{{raw:site}}', b: \"x {{raw:site}} {{site}}\" }\n",
            encoding="utf-8",
        )
        data = file_module.load_jsonnet_file_with_variable_substitutions(str(spec))
        assert literal_text(data) == {"a": "{{site}}", "b": "x {{site}} lon"}

    @pytest.mark.parametrize(
        "name, text",
        [
            ("spec.json", '{"a": "{{raw:site}}"}'),
            ("spec.toml", 'a = "{{raw:site}}"\n'),
        ],
    )
    def test_the_loaders_leave_it_marked(self, tmp_path, name, text):
        # A loader cannot know whether more passes follow
        spec = tmp_path / name
        spec.write_text(text, encoding="utf-8")
        loader = (
            file_module.load_json_file_with_variable_substitutions
            if name.endswith(".json")
            else file_module.load_toml_file_with_variable_substitutions
        )
        data = loader(str(spec))
        assert data["a"] != "{{site}}"
        assert literal_text(data) == {"a": "{{site}}"}


class TestLiteralText:
    def test_puts_it_back_at_any_depth_in_place(self):
        marked = cast(str, resolve_variables_in_string("{{raw:site}}"))
        data = {marked: [marked, {"k": marked}], "n": 1, "none": None}
        assert literal_text(data) is data
        assert data == {
            "{{site}}": ["{{site}}", {"k": "{{site}}"}],
            "n": 1,
            "none": None,
        }

    def test_in_a_dataclass(self):
        @dataclass
        class Spec:
            name: str
            args: list

        marked = cast(str, resolve_variables_in_string("{{raw:site}}"))
        spec = Spec(name=marked, args=[marked])
        assert literal_text(spec) is spec
        assert spec == Spec(name="{{site}}", args=["{{site}}"])

    def test_an_enum_is_left_as_it_is(self):
        class Kind(str, Enum):
            A = "a"

        assert literal_text(Kind.A) is Kind.A

    def test_a_string_without_markers_is_returned_as_it_is(self):
        text = "plain {{site}}"
        assert literal_text(text) is text


# ---------------------------------------------------------------------------
# Where a value leaves the CLI
# ---------------------------------------------------------------------------


CONFIG = """\
[common]
namespace = "ns"
tag = "t-{{raw:site}}"

[common.variables]
site = "lon"
keep = "{{raw:site}}"

[workRequirement]
taskType = "bash"
argumentsPostfix = ["cfg {{raw:site}} {{site}} {{raw:task_number}}"]
"""


def _yd(directory: Path, *args: str) -> str:
    """
    Run 'yd' in the directory, with its own configuration and dummy
    credentials, and return its standard output, having checked that no
    marker reached it or the standard error.
    """
    if not (directory / "config.toml").exists():
        (directory / "config.toml").write_text(CONFIG, encoding="utf-8")
    # The shell's own YD_* (credentials, YD_VAR_* variables) never reach it
    environment = {k: v for k, v in os.environ.items() if not k.startswith("YD_")}
    environment.update(YD_KEY="dummy-key", YD_SECRET="dummy-secret")
    completed = subprocess.run(
        [sys.executable, "-m", "yellowdog_cli.yd", *args],
        cwd=directory,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    for marker in MARKERS:
        assert marker not in completed.stdout + completed.stderr
    return completed.stdout


WORK_REQUIREMENT = {
    "name": "wr-{{site}}",
    # Inherited by the Task, and substituted again for it
    "arguments": ["wr {{raw:site}} {{raw:task_name}}"],
    "taskGroups": [
        {
            "name": "tg-{{site}}",
            "taskType": "bash",
            "tasks": [
                {
                    "name": "t{{task_number}}",
                    "environment": {
                        "A": "{{raw:site}}",
                        "B": "{{site}}",
                        "C": "{{keep}}",
                        "D": "{{raw:a_{{site}}}}",
                    },
                }
            ],
        }
    ],
}


class TestWorkRequirements:
    def test_submit(self, tmp_path):
        (tmp_path / "wr.json").write_text(
            json.dumps(WORK_REQUIREMENT), encoding="utf-8"
        )

        document = json.loads(
            _yd(tmp_path, "wr", "submit", "wr.json", "--dry-run", "--json", "--quiet")
        )

        assert document["tag"] == "t-{{site}}"
        (task,) = document["taskGroups"][0]["tasks"]
        assert task["arguments"] == [
            "wr {{site}} {{task_name}}",
            "cfg {{site}} lon {{task_number}}",
        ]
        assert task["environment"] == {
            "A": "{{site}}",
            "B": "lon",
            "C": "{{site}}",
            "D": "{{a_{{site}}}}",
        }

    def test_a_csv_cell(self, tmp_path):
        wr = {
            "name": "wr",
            "taskGroups": [
                {"name": "tg", "taskType": "bash", "tasks": [{"arguments": ["<<c>>"]}]}
            ],
        }
        (tmp_path / "wr.json").write_text(json.dumps(wr), encoding="utf-8")
        (tmp_path / "data.csv").write_text(
            "c\n{{raw:site}}\n{{site}}\n", encoding="utf-8"
        )

        document = json.loads(
            _yd(
                tmp_path,
                *("wr", "submit", "wr.json", "-V", "data.csv"),
                *("--dry-run", "--json", "--quiet"),
            )
        )

        tasks = document["taskGroups"][0]["tasks"]
        # Each followed by the configuration's argumentsPostfix
        assert [task["arguments"][0] for task in tasks] == ["{{site}}", "lon"]

    def test_json_raw(self, tmp_path):
        wr = {
            "name": "wr",
            "taskGroups": [
                {
                    "name": "tg",
                    "tasks": [{"taskType": "bash", "arguments": ["{{raw:site}}"]}],
                }
            ],
        }
        (tmp_path / "wr.json").write_text(json.dumps(wr), encoding="utf-8")

        document = json.loads(
            _yd(
                tmp_path,
                *("wr", "submit", "--json-raw", "wr.json"),
                *("--dry-run", "--json", "--quiet"),
            )
        )

        assert document["taskGroups"][0]["tasks"][0]["arguments"] == ["{{site}}"]


class TestResources:
    def test_a_specification_file(self, tmp_path):
        spec = [{"resource": "Keyring", "name": "k", "description": "{{raw:site}}"}]
        (tmp_path / "res.json").write_text(json.dumps(spec), encoding="utf-8")

        document = json.loads(
            _yd(
                tmp_path,
                *("resource", "create", "res.json", "--dry-run", "--json", "--quiet"),
            )
        )

        assert document[0]["description"] == "{{site}}"

    def test_inline(self, tmp_path):
        document = json.loads(
            _yd(
                tmp_path,
                *("resource", "create", "--type", "Keyring"),
                *("--set", "name=k", "--set", "description={{raw:site}}"),
                *("--dry-run", "--json", "--quiet"),
            )
        )

        assert document[0]["description"] == "{{site}}"


class TestWorkerPools:
    def test_provision(self, tmp_path):
        spec = {
            "requirementTemplateUsage": {
                "templateId": "ydid:crt:000000:00000000-0000-0000-0000-000000000000",
                "requirementName": "r",
                "targetInstanceCount": 1,
                "userData": "echo __{{raw:site}}__ __{{site}}__",
            },
            "provisionedProperties": {"workerTag": "w-__{{raw:site}}__"},
        }
        (tmp_path / "wp.json").write_text(json.dumps(spec), encoding="utf-8")

        document = json.loads(
            _yd(tmp_path, "wp", "provision", "wp.json", "--dry-run", "--quiet")
        )

        usage = document["requirementTemplateUsage"]
        assert usage["userData"] == "echo __{{site}}__ lon"
        assert document["provisionedProperties"]["workerTag"] == "w-__{{site}}__"

    def test_user_data_from_the_configuration(self, tmp_path):
        # Substituted as the configuration loads and again as it is provisioned
        (tmp_path / "config.toml").write_text(
            CONFIG.replace(
                "[workRequirement]",
                '[workerPool]\nuserData = "echo __{{raw:site}}__ __{{site}}__"\n\n'
                "[workRequirement]",
            ),
            encoding="utf-8",
        )
        spec = {
            "requirementTemplateUsage": {
                "templateId": "ydid:crt:000000:00000000-0000-0000-0000-000000000000",
                "requirementName": "r",
                "targetInstanceCount": 1,
            },
            "provisionedProperties": {},
        }
        (tmp_path / "wp.json").write_text(json.dumps(spec), encoding="utf-8")

        document = json.loads(
            _yd(tmp_path, "wp", "provision", "wp.json", "--dry-run", "--quiet")
        )

        usage = document["requirementTemplateUsage"]
        assert usage["userData"] == "echo __{{site}}__ lon"


class TestNodeActions:
    def test_the_specification_and_a_content_file(self, tmp_path):
        from types import SimpleNamespace

        from yellowdog_cli.nodeaction import _load_spec, _parse_actions

        (tmp_path / "payload.txt").write_text(
            "__{{raw:site}}__ __{{site}}__\n", encoding="utf-8"
        )
        spec_file = tmp_path / "na.json"
        spec_file.write_text(
            json.dumps(
                {
                    "nodeTypes": ["__{{raw:site}}__"],
                    "actions": [
                        {
                            "type": "writeFile",
                            "path": "/tmp/x",
                            "contentFile": "payload.txt",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        ctx = SimpleNamespace(
            args=SimpleNamespace(jsonnet_dry_run=False, validate=False)
        )

        spec = _load_spec(ctx, str(spec_file))  # type: ignore[arg-type]
        assert spec is not None
        assert spec["nodeTypes"] == ["__{{site}}__"]
        actions = _parse_actions(spec["actions"], str(tmp_path))
        assert actions is not None
        assert actions[0].content == "__{{site}}__ lon\n"  # type: ignore[attr-defined]


class TestDataClient:
    def test_a_path(self):
        path = resolve_remote_path(
            ConfigDataClient(remote="r"), relative_path="d-{{raw:site}}-{{site}}"
        )
        assert path.endswith("d-{{site}}-lon")

    def test_the_configured_destination(self, tmp_path):
        (tmp_path / "f.txt").write_text("hi\n", encoding="utf-8")
        (tmp_path / "dest").mkdir()

        records = json.loads(
            _yd(
                tmp_path,
                *("data", "upload", "f.txt", "--remote", str(tmp_path / "dest")),
                *("--bucket", "b-{{raw:site}}", "--prefix", "p-{{site}}"),
                *("--dry-run", "--json"),
            )
        )

        assert records[0]["destination"].endswith(":b-{{site}}/p-lon/f.txt")


class TestVariablesCommand:
    def test_reports_the_literal_and_warns_of_nothing(self, tmp_path):
        (tmp_path / "config.toml").write_text(
            CONFIG.replace('keep = "{{raw:site}}"', 'keep = "{{raw:nope}}"'),
            encoding="utf-8",
        )
        output = _yd(tmp_path, "variables", "site", "keep")

        assert "WARNING" not in output
        document = json.loads(output[output.index("{") : output.rindex("}") + 1])
        assert document == {"keep": "{{nope}}", "site": "lon"}
