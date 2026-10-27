"""
Where the Platform's own Mustache runs -- User Data, and a Worker Pool's Node
Actions ('nodeEvents', all of it) -- only '__{{x}}__' is substituted, in any
pass, so that the Platform's '{{provider}}' or '{{node.details.nodeSlot}}' is
left for it: in a Worker Pool or Compute Requirement specification, which
takes the plain '{{x}}' too everywhere else, and in a resource specification
(a Configured Worker Pool's 'nodeEvents'), which takes the plain form. A Node
Action specification keeps to the '__' form throughout.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import yellowdog_cli.utils.file_substitution as file_module
import yellowdog_cli.utils.variable_substitution as var_module
from yellowdog_cli.utils.file_substitution import resolve_plain_variables_too
from yellowdog_cli.utils.variable_substitution import resolve_variables_insitu
from yellowdog_cli.utils.variable_syntax import (
    WP_VARIABLES_POSTFIX,
    WP_VARIABLES_PREFIX,
)

TEMPLATE_ID = "ydid:crt:000000:00000000-0000-0000-0000-000000000000"

# Plain '{{x}}' where it is substituted and where it is left for the Platform
SPECIFICATION = {
    "requirementTemplateUsage": {
        "templateId": TEMPLATE_ID,
        "requirementName": "r-{{site}}-__{{site}}__",
        "targetInstanceCount": 1,
        "userData": "echo __{{site}}__ {{provider}} {{site}}",
    },
    "provisionedProperties": {
        "workerTag": "w-{{site}}",
        "nodeConfiguration": {
            "nodeTypes": [{"name": "a", "count": 1}],
            "nodeEvents": {
                "STARTUP_NODES_ADDED": [
                    {
                        "actions": [
                            {
                                "action": "RUN_COMMAND",
                                "path": "x",
                                "arguments": [
                                    "{{node.details.nodeSlot}}",
                                    "{{site}}",
                                    "__{{site}}__",
                                ],
                            }
                        ]
                    }
                ]
            },
        },
    },
}

EXPECTED_USAGE = {
    "requirementName": "r-lon-lon",
    "userData": "echo lon {{provider}} {{site}}",
}
EXPECTED_ARGUMENTS = ["{{node.details.nodeSlot}}", "{{site}}", "lon"]


@pytest.fixture(autouse=True)
def table(monkeypatch):
    monkeypatch.setattr(var_module, "VARIABLE_SUBSTITUTIONS", {"site": "lon"})


@pytest.fixture()
def warnings(monkeypatch) -> MagicMock:
    monkeypatch.setattr(var_module, "_UNDEFINED_VARIABLE_WARNINGS", True)
    monkeypatch.setattr(var_module, "_UNDEFINED_VARIABLES_REPORTED", set())
    warning = MagicMock()
    monkeypatch.setattr(var_module, "print_warning", warning)
    return warning


def _messages(warning: MagicMock) -> list[str]:
    return [str(call.args[0]) for call in warning.call_args_list]


def _loaded(data: dict) -> dict:
    """
    'data' as the Worker Pool loaders leave it: the '__' pass, then the plain.
    """
    data = json.loads(json.dumps(data))
    resolve_variables_insitu(
        data, prefix=WP_VARIABLES_PREFIX, postfix=WP_VARIABLES_POSTFIX
    )
    resolve_plain_variables_too(data)
    return data


def _arguments(data: dict) -> list:
    events = data["provisionedProperties"]["nodeConfiguration"]["nodeEvents"]
    return events["STARTUP_NODES_ADDED"][0]["actions"][0]["arguments"]


class TestBothForms:
    def test_plain_and_underscored_alike_outside_mustache(self):
        data = _loaded(SPECIFICATION)
        usage = data["requirementTemplateUsage"]
        assert usage["requirementName"] == EXPECTED_USAGE["requirementName"]
        assert data["provisionedProperties"]["workerTag"] == "w-lon"

    def test_user_data_keeps_to_the_underscored_form(self):
        usage = _loaded(SPECIFICATION)["requirementTemplateUsage"]
        assert usage["userData"] == EXPECTED_USAGE["userData"]

    def test_node_actions_keep_to_the_underscored_form(self):
        assert _arguments(_loaded(SPECIFICATION)) == EXPECTED_ARGUMENTS

    def test_mustache_is_not_reported(self, warnings):
        _loaded(SPECIFICATION)
        assert _messages(warnings) == []

    def test_an_undefined_plain_variable_is_reported(self, warnings):
        _loaded({"provisionedProperties": {"workerTag": "w-{{nope}}"}})
        [message] = _messages(warnings)
        assert (
            "'{{nope}}'" in message and "'provisionedProperties.workerTag'" in message
        )

    def test_a_raw_literal_in_either_form(self):
        data = _loaded(
            {
                "a": "{{raw:site}}",
                "b": "__{{raw:site}}__",
                "userData": "__{{raw:site}}__",
            }
        )
        assert var_module.literal_text(data) == {
            "a": "{{site}}",
            "b": "__{{site}}__",
            "userData": "__{{site}}__",
        }


class TestPlatformMustache:
    def test_node_events_take_the_underscored_form_in_a_plain_pass(self, warnings):
        # A resource specification's way: plain delimiters, bar the Mustache
        data = {
            "a": "{{site}}",
            "nodeEvents": {"E": [{"args": ["{{site}}", "__{{site}}__", "{{nope}}"]}]},
        }
        resolve_variables_insitu(data)
        assert data == {
            "a": "lon",
            "nodeEvents": {"E": [{"args": ["{{site}}", "lon", "{{nope}}"]}]},
        }
        assert _messages(warnings) == []

    def test_an_undefined_underscored_variable_in_node_events_is_reported(
        self, warnings
    ):
        resolve_variables_insitu({"nodeEvents": {"E": ["__{{nope}}__"]}})
        [message] = _messages(warnings)
        assert "'__{{nope}}__'" in message and "'nodeEvents.E[0]'" in message


class TestJsonnetResources:
    """
    A Jsonnet resource file's text pass, before evaluation, is in the plain
    delimiters and cannot tell which property an expression is in: it leaves
    '__{{x}}__' for the pass after evaluation, which can.
    """

    @pytest.fixture(autouse=True)
    def jsonnet(self):
        pytest.importorskip("_jsonnet")

    def _load(self, tmp_path, data: object) -> object:
        spec = tmp_path / "res.jsonnet"
        spec.write_text(json.dumps(data), encoding="utf-8")
        return file_module.load_jsonnet_file_with_variable_substitutions(str(spec))

    def test_underscored_in_user_data_and_node_events(self, tmp_path):
        data = self._load(
            tmp_path,
            {
                "userData": "echo __{{site}}__ {{provider}}",
                "nodeEvents": {"E": ["__{{site}}__", "{{node.details.nodeSlot}}"]},
            },
        )
        assert data == {
            "userData": "echo lon {{provider}}",
            "nodeEvents": {"E": ["lon", "{{node.details.nodeSlot}}"]},
        }

    def test_underscored_elsewhere_as_a_json_file_has_it(self, tmp_path):
        assert self._load(tmp_path, {"a": "__{{site}}__ {{site}}"}) == {
            "a": "__lon__ lon"
        }

    def test_a_defined_variable_underscored_is_not_circular(self, tmp_path):
        assert self._load(tmp_path, {"userData": "__{{site}}__"}) == {"userData": "lon"}

    def test_the_plain_form_still_feeds_the_code(self, tmp_path):
        spec = tmp_path / "res.jsonnet"
        spec.write_text('{ n: std.length("{{site}}") }', encoding="utf-8")
        data = file_module.load_jsonnet_file_with_variable_substitutions(str(spec))
        assert data == {"n": 3}


class TestLoaders:
    def test_json(self, tmp_path):
        spec = tmp_path / "wp.json"
        spec.write_text(json.dumps(SPECIFICATION), encoding="utf-8")
        data = file_module.load_json_file_with_variable_substitutions(
            str(spec), WP_VARIABLES_PREFIX, WP_VARIABLES_POSTFIX, also_plain=True
        )
        assert data == _loaded(SPECIFICATION)

    def test_json_without_also_plain_keeps_to_the_underscored_form(self, tmp_path):
        # A Node Action specification's way
        spec = tmp_path / "na.json"
        spec.write_text('{"a": "{{site}} __{{site}}__"}', encoding="utf-8")
        data = file_module.load_json_file_with_variable_substitutions(
            str(spec), WP_VARIABLES_PREFIX, WP_VARIABLES_POSTFIX
        )
        assert data == {"a": "{{site}} lon"}

    def test_jsonnet(self, tmp_path):
        pytest.importorskip("_jsonnet")
        spec = tmp_path / "wp.jsonnet"
        spec.write_text(json.dumps(SPECIFICATION), encoding="utf-8")
        data = file_module.load_jsonnet_file_with_variable_substitutions(
            str(spec), WP_VARIABLES_PREFIX, WP_VARIABLES_POSTFIX, also_plain=True
        )
        assert data == _loaded(SPECIFICATION)


def _yd(directory: Path, *args: str) -> dict:
    """
    Run 'yd' in the directory, with its own configuration and dummy
    credentials, and return the JSON document it prints.
    """
    (directory / "config.toml").write_text(
        '[common]\nnamespace = "ns"\ntag = "tg"\n\n[common.variables]\nsite = "lon"\n',
        encoding="utf-8",
    )
    # The shell's own YD_* (credentials, YD_VAR_* variables) never reach it
    environment = {k: v for k, v in os.environ.items() if not k.startswith("YD_")}
    environment.update(YD_KEY="dummy-key", YD_SECRET="dummy-secret")
    completed = subprocess.run(
        [sys.executable, "-m", "yellowdog_cli.yd", *args, "--dry-run", "--quiet"],
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


class TestCommands:
    def test_provision(self, tmp_path):
        (tmp_path / "wp.json").write_text(json.dumps(SPECIFICATION), encoding="utf-8")

        document = _yd(tmp_path, "wp", "provision", "wp.json")

        usage = document["requirementTemplateUsage"]
        assert {key: usage[key] for key in EXPECTED_USAGE} == EXPECTED_USAGE
        assert document["provisionedProperties"]["workerTag"] == "w-lon"
        assert _arguments(document) == EXPECTED_ARGUMENTS

    def test_a_configured_worker_pool_resource(self, tmp_path):
        resource = {
            "resource": "ConfiguredWorkerPool",
            "name": "p-{{site}}",
            "namespace": "ns",
            "properties": {
                "nodeConfiguration": {
                    "nodeTypes": [{"name": "a", "min": 1}],
                    "nodeEvents": SPECIFICATION["provisionedProperties"][
                        "nodeConfiguration"
                    ]["nodeEvents"],
                },
                "targetNodeCount": 0,
            },
        }
        (tmp_path / "res.json").write_text(json.dumps([resource]), encoding="utf-8")

        (document,) = _yd(tmp_path, "resource", "create", "res.json", "--json")

        assert document["name"] == "p-lon"
        events = document["properties"]["nodeConfiguration"]["nodeEvents"]
        actions = events["STARTUP_NODES_ADDED"][0]["actions"]
        assert actions[0]["arguments"] == EXPECTED_ARGUMENTS

    def test_instantiate(self, tmp_path):
        spec = {"requirementTemplateUsage": SPECIFICATION["requirementTemplateUsage"]}
        (tmp_path / "cr.json").write_text(json.dumps(spec), encoding="utf-8")

        document = _yd(tmp_path, "cr", "instantiate", "cr.json")

        assert {key: document[key] for key in EXPECTED_USAGE} == EXPECTED_USAGE
