"""
utils/specs/validation.py: every violation in a document is reported with
its JSON path; the five commands warn and proceed on an ordinary run and stop
under --validate; under --json the warnings go to stderr and --validate's
document is the array of violations. A '$schema' key is accepted and removed
before the document is used.

The command-level tests drive each command's real main() through
main_wrapper with the client mocked, as tests/test_json_output.py does; its
'run' fixture parses stdout as JSON always, and these tests need the text of
an ordinary run too, so a local equivalent is used.
"""

import dataclasses
import json
from json import loads as json_loads
from unittest.mock import MagicMock

import pytest

import yellowdog_cli.utils.interactive as interactive_module
import yellowdog_cli.utils.load_resources as load_resources_module
import yellowdog_cli.utils.printing as printing_module
import yellowdog_cli.utils.results as results_module
import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli.utils import output_settings
from yellowdog_cli.utils.lazy import value as lazy_value
from yellowdog_cli.utils.property_names import ALL_KEYS, SCHEMA_KEY
from yellowdog_cli.utils.results import reset_results
from yellowdog_cli.utils.specs.schema import Family, compile_schema
from yellowdog_cli.utils.specs.validation import (
    DOCUMENT_PATH,
    Violation,
    strip_schema_key,
    validate_specification,
    warn_of_violations,
)

GOOD = {"taskGroups": [{"tasks": [{"taskType": "bash", "arguments": ["-c", "true"]}]}]}
BAD = {
    "taskGroups": [
        {"tasks": [{"taskType": 3}], "maxWorkers": "ten"},
        {"tasks": [{}], "nope": 1},
    ]
}
# A violation yd-submit itself tolerates (a Task Group property at Task
# level, which it ignores there), so an ordinary run goes on to completion
TOLERATED = {"taskGroups": [{"tasks": [{"taskType": "bash", "maxWorkers": 2}]}]}

WR_ID = "ydid:workreq:000000:11111111-1111-1111-1111-111111111111"


# --- the function -------------------------------------------------------------


class TestValidateSpecification:
    def test_a_good_document_has_no_violations(self):
        assert validate_specification(Family.WORK_REQUIREMENT, GOOD, "wr.json") == []

    def test_every_violation_is_reported_with_its_path(self):
        violations = validate_specification(Family.WORK_REQUIREMENT, BAD, "wr.json")
        assert violations == [
            Violation("taskGroups[0].maxWorkers", "must be integer"),
            Violation("taskGroups[0].tasks[0].taskType", "must be string"),
            Violation("taskGroups[1]", "unknown property 'nope'"),
        ]

    def test_the_document_is_not_changed(self):
        document = json.loads(json.dumps(BAD))
        validate_specification(Family.WORK_REQUIREMENT, document, "wr.json")
        assert document == BAD

    def test_a_missing_property_and_an_extra_one_on_one_object(self):
        violations = validate_specification(Family.WORK_REQUIREMENT, {"x": 1}, "s")
        assert violations == [
            Violation(DOCUMENT_PATH, "missing required property 'taskGroups'"),
            Violation(DOCUMENT_PATH, "unknown property 'x'"),
        ]

    def test_several_unknown_properties_are_named_in_order(self):
        doc = {**GOOD, "zeta": 1, "alpha": 2, "mu": 3}
        assert validate_specification(Family.WORK_REQUIREMENT, doc, "s") == [
            Violation(DOCUMENT_PATH, "unknown properties 'alpha', 'mu', 'zeta'")
        ]

    def test_several_missing_properties_are_named(self):
        doc = {"resource": "Keyring"}
        violations = validate_specification(Family.RESOURCES, doc, "s")
        assert violations == [
            Violation(
                DOCUMENT_PATH, "missing required properties 'description', 'name'"
            )
        ]

    def test_a_key_containing_a_dot_is_followed(self):
        doc = {**GOOD, "environment": {"A.B": 1, "C": 2}}
        paths = {
            v.path for v in validate_specification(Family.WORK_REQUIREMENT, doc, "s")
        }
        assert paths == {"environment.A.B", "environment.C"}

    def test_a_wrong_document_is_one_violation(self):
        assert validate_specification(Family.WORK_REQUIREMENT, [], "s") == [
            Violation(DOCUMENT_PATH, "must be object")
        ]

    def test_a_variable_token_is_not_a_violation(self):
        doc = {"taskGroups": [{"tasks": [{}], "maxWorkers": "{{num:n}}"}]}
        assert validate_specification(Family.WORK_REQUIREMENT, doc, "x") == []

    def test_each_resource_in_a_list_is_checked(self):
        doc = [
            {"resource": "Keyring", "name": 3, "description": "d"},
            {"resource": "Nope"},
            {"resource": "{{r}}", "anything": 1},  # Unchecked: the key is a variable
            5,
        ]
        paths = [v.path for v in validate_specification(Family.RESOURCES, doc, "s")]
        assert paths == ["[0].name", "[1].resource", "[3]"]

    def test_each_node_action_is_checked(self):
        doc = {
            "actions": [
                {"type": "runCommand"},
                {"type": "writeFile", "path": "p", "content": "a", "contentFile": "b"},
            ]
        }
        paths = [v.path for v in validate_specification(Family.NODE_ACTIONS, doc, "s")]
        assert paths == ["actions[0]", "actions[1]"]

    def test_a_one_of_rule_is_named_and_the_object_still_checked(self):
        doc = {"resource": "InternalUser", "bogus": 1, "groups": 5}
        assert validate_specification(Family.RESOURCES, doc, "s") == [
            Violation(DOCUMENT_PATH, "must contain one of name, username, id"),
            Violation("groups", "must be array"),
            Violation(DOCUMENT_PATH, "unknown property 'bogus'"),
        ]

    def test_a_not_rule_is_named_and_the_object_still_checked(self):
        doc = {
            "actions": [
                {
                    "type": "writeFile",
                    "path": "p",
                    "content": "a",
                    "contentFile": "b",
                    "nodeTypes": 5,
                }
            ]
        }
        assert validate_specification(Family.NODE_ACTIONS, doc, "s") == [
            Violation("actions[0]", "must not have both content and contentFile"),
            Violation("actions[0].nodeTypes", "must be array or null"),
        ]

    def test_the_limit_says_there_are_more(self, monkeypatch):
        import yellowdog_cli.utils.specs.validation as spec_validation_module

        monkeypatch.setattr(spec_validation_module, "MAX_VIOLATIONS", 2)
        doc = {"taskGroups": [{"tasks": [{"taskType": i} for i in range(5)]}]}
        violations = validate_specification(Family.WORK_REQUIREMENT, doc, "s")
        assert len(violations) == 3
        assert violations[-1] == Violation(
            DOCUMENT_PATH, "...and more: stopped after 2 violations"
        )

    def test_every_violation_inside_a_polymorphic_member_is_reported(self):
        doc = {
            "resource": "ComputeSourceTemplate",
            "namespace": "n",
            "source": {
                "type": "SimulatorComputeSource",
                "name": "s",
                "bogus": 1,
                "limit": "ten",
            },
        }
        violations = validate_specification(Family.RESOURCES, doc, "s")
        assert Violation("source.limit", "must be integer") in violations
        assert any(v.path == "source" and "bogus" in v.message for v in violations), (
            violations
        )

    def test_a_compute_requirement_violation_names_its_path(self):
        doc = {
            "requirementTemplateUsage": {"templateId": "t", "targetInstanceCount": "x"}
        }
        assert validate_specification(Family.COMPUTE_REQUIREMENT, doc, "s") == [
            Violation("requirementTemplateUsage.targetInstanceCount", "must be integer")
        ]


class TestSchemaKey:
    def test_the_key_is_a_known_property(self):
        assert SCHEMA_KEY == "$schema" and SCHEMA_KEY in ALL_KEYS

    def test_stripped_from_a_document_and_each_resource(self):
        assert strip_schema_key({"$schema": "s", "a": 1}) == {"a": 1}
        assert strip_schema_key([{"$schema": "s", "a": 1}, 3]) == [{"a": 1}, 3]


class TestWarnings:
    @pytest.fixture
    def args(self, monkeypatch):
        args = MagicMock(
            json_output=None,
            quiet=False,
            count_only=False,
            print_pid=False,
            no_format=True,
            debug=False,
        )
        # The output settings themselves, for a test to change
        output_settings.configure_output(args)
        return output_settings.OUTPUT

    def test_each_violation_is_one_warning_naming_the_file(self, args, capsys):
        warn_of_violations(Family.WORK_REQUIREMENT, BAD, "wr.json")
        out = " ".join(capsys.readouterr().out.split())  # Unwrapped
        assert out.count("WARNING") == 3
        assert "'wr.json': taskGroups[0].maxWorkers: must be integer" in out
        assert "yd-schema work-requirement" in out

    def test_under_json_the_warnings_go_to_stderr(self, args, capsys):
        args.json_output = True
        warn_of_violations(Family.WORK_REQUIREMENT, BAD, "wr.json")
        out, err = capsys.readouterr()
        assert out == "" and "taskGroups[0].maxWorkers" in err

    def test_a_schema_fastjsonschema_cannot_compile_is_one_warning(
        self, args, capsys, monkeypatch
    ):
        import fastjsonschema

        import yellowdog_cli.utils.specs.validation as spec_validation_module

        def refuse(family):
            raise fastjsonschema.JsonSchemaDefinitionException("bad definition")

        monkeypatch.setattr(spec_validation_module, "compile_schema", refuse)
        assert warn_of_violations(Family.WORK_REQUIREMENT, BAD, "wr.json") == []
        out = " ".join(capsys.readouterr().out.split())
        assert out.count("WARNING") == 1
        assert (
            "cannot check 'wr.json' against the work-requirement schema:"
            " bad definition; run 'yd-schema work-requirement' to see why"
        ) in out

    def test_a_fault_in_the_check_is_one_warning_not_a_refusal(
        self, args, capsys, monkeypatch
    ):
        import yellowdog_cli.utils.specs.validation as spec_validation_module

        def fault(family, document, source):
            raise KeyError("a repair bug")

        monkeypatch.setattr(spec_validation_module, "validate_specification", fault)
        assert warn_of_violations(Family.WORK_REQUIREMENT, BAD, "wr.json") == []
        out = " ".join(capsys.readouterr().out.split())
        assert out.count("WARNING") == 1
        assert "cannot check 'wr.json'" in out and "KeyError" in out

    def test_under_debug_a_fault_in_the_check_is_raised(self, args, monkeypatch):
        import yellowdog_cli.utils.specs.validation as spec_validation_module

        def fault(family, document, source):
            raise KeyError("a repair bug")

        args.debug = True
        monkeypatch.setattr(spec_validation_module, "validate_specification", fault)
        with pytest.raises(KeyError):
            warn_of_violations(Family.WORK_REQUIREMENT, BAD, "wr.json")


class TestWording:
    """
    No violation reaches the user in fastjsonschema's own words: a pattern
    or a choice between shapes is worded by the schema's description, an
    exactly-one-of-these-keys rule as such, and an enum as a plain list.
    """

    @staticmethod
    def _messages(family: Family, document) -> list[str]:
        return [
            f"{v.path}: {v.message}"
            for v in validate_specification(family, document, "x")
        ]

    def test_a_duration_is_named_not_its_regex(self):
        messages = self._messages(
            Family.WORKER_POOL,
            {
                "requirementTemplateUsage": {"templateId": "t"},
                "provisionedProperties": {"nodeBootTimeout": "5m"},
            },
        )
        assert messages == [
            "provisionedProperties.nodeBootTimeout: must be an ISO 8601"
            " duration, e.g. PT10M"
        ]

    def test_a_range_bound_is_named(self):
        messages = self._messages(
            Family.WORK_REQUIREMENT,
            {"ram": ["lots", 4], "taskGroups": [{"tasks": [{}]}]},
        )
        assert messages == ['ram[0]: must be a number, or null or "none" for no limit']

    @pytest.mark.parametrize("document", [{}, {"actions": [], "actionGroups": []}])
    def test_actions_or_action_groups_exactly(self, document):
        assert self._messages(Family.NODE_ACTIONS, document) == [
            f"{DOCUMENT_PATH}: must contain exactly one of actions, actionGroups"
        ]

    def test_both_actions_and_groups_are_repaired_so_the_rest_is_checked(self):
        messages = self._messages(
            Family.NODE_ACTIONS,
            {"actions": [{"type": "runCommand"}], "actionGroups": []},
        )
        assert messages == [
            f"{DOCUMENT_PATH}: must contain exactly one of actions, actionGroups",
            "actions[0]: missing required property 'path'",
        ]

    def test_an_enum_is_a_plain_list(self):
        assert self._messages(
            Family.NODE_ACTIONS, {"actions": [{"type": "bogus"}]}
        ) == ["actions[0].type: must be one of runCommand, writeFile, createWorkers"]

    def test_no_message_is_fastjsonschemas_own(self):
        for family, document in [
            (
                Family.WORK_REQUIREMENT,
                {"ram": [[], 4], "taskGroups": [{"tasks": [{}]}]},
            ),
            (Family.NODE_ACTIONS, {"actions": [], "actionGroups": []}),
        ]:
            for message in self._messages(family, document):
                assert "cannot be validated" not in message
                assert "exactly by one definition" not in message
                assert "must match pattern" not in message


@pytest.mark.parametrize(
    "scope, expected",
    [
        ({}, ["roles[0].scope: missing required property 'namespaces'"]),
        ({"global": False}, ["roles[0].scope: missing required property 'namespaces'"]),
        (
            {"namespaces": []},
            ["roles[0].scope.namespaces: must contain at least 1 items"],
        ),
        ({"global": True}, []),
        ({"global": "{{everywhere}}"}, []),
        ({"namespaces": [{"namespace": "n"}]}, []),
    ],
)
def test_a_group_role_scope_is_global_or_names_a_namespace(scope, expected):
    # As create.py demands: a scope without 'global' true names a namespace
    group = {
        "resource": "Group",
        "name": "g",
        "roles": [{"role": {"name": "r"}, "scope": scope}],
    }
    assert [
        f"{v.path}: {v.message}"
        for v in validate_specification(Family.RESOURCES, group, "x")
    ] == expected


# --- through the real commands ------------------------------------------------

_DEFAULTS = {
    "json_output": False,
    "dry_run": False,
    "quiet": False,
    "yes": True,
    "no_format": True,
    "count_only": False,
    "print_pid": False,
    "debug": False,
    "validate": False,
    "jsonnet_dry_run": False,
    "content_path": None,
    "target": None,
}


@pytest.fixture()
def run(monkeypatch, capsys):
    """
    run(module, client=None, also=(), main_module=None, **args): patch
    ARGS_PARSER in the command module, the modules it prints and records
    through, and those in 'also'; run main_module.main() (default: module)
    through the wrapper; return (stdout, stderr,
    client), stdout parsed as JSON under json_output. The exit code is left
    in run.exit_code.
    """
    reset_results()

    def _run(module, client=None, also=(), main_module=None, **values):
        args = MagicMock(**{**_DEFAULTS, **values})
        client = client or MagicMock()
        for target in (
            module,
            results_module,
            printing_module,
            interactive_module,
            wrapper_module,
            *also,
        ):
            # A library module (utils/resource_creation.py) reads no ARGS_PARSER
            if hasattr(target, "ARGS_PARSER"):
                monkeypatch.setattr(target, "ARGS_PARSER", args)
        output_settings.configure_output(args)
        # A command taking a RunContext gets these from the wrapper's own
        if hasattr(module, "CLIENT"):
            monkeypatch.setattr(module, "CLIENT", client)
            monkeypatch.setattr(wrapper_module, "CLIENT", MagicMock())
        else:
            monkeypatch.setattr(wrapper_module, "CLIENT", client)
        config = MagicMock(namespace="ns", name_tag="tag", url="https://u")
        monkeypatch.setattr(wrapper_module, "CONFIG_COMMON", config)
        if hasattr(module, "CONFIG_COMMON"):
            monkeypatch.setattr(module, "CONFIG_COMMON", config)
        with pytest.raises(SystemExit) as exit_info:
            (main_module or module).main()
        _run.exit_code = exit_info.value.code  # type: ignore[attr-defined]
        out, err = capsys.readouterr()
        return (json_loads(out) if values.get("json_output") else out), err, client

    yield _run
    reset_results()


@pytest.fixture()
def unbuildable(monkeypatch):
    """
    The work-requirement schema cannot be built: RetryPolicy.maxRetries is
    given an annotation the mapping does not describe, as a future SDK's
    field might be. compile_schema()'s cache is cleared before and after, so
    neither this test nor the next sees the other's schema.
    """
    import typing

    from yellowdog_client.model import RetryPolicy

    original = typing.get_type_hints

    def hints(cls, *args, **kwargs):
        found = original(cls, *args, **kwargs)
        if cls is RetryPolicy:
            return {**found, "maxRetries": dict[str, typing.Any]}
        return found

    compile_schema.cache_clear()
    monkeypatch.setattr(typing, "get_type_hints", hints)
    yield
    monkeypatch.undo()
    compile_schema.cache_clear()


def _write(tmp_path, name: str, document) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(document))
    return str(path)


class TestSubmit:
    @pytest.fixture()
    def submit(self, run, monkeypatch):
        import yellowdog_cli.submit as yd_submit

        monkeypatch.setattr(
            yd_submit,
            "CONFIG_WR",
            dataclasses.replace(
                lazy_value(yd_submit.CONFIG_WR),
                wr_data_file=None,
                csv_files=None,
                wr_name=None,
                task_data_inputs=None,
                task_data_outputs=None,
            ),
        )
        monkeypatch.setattr(yd_submit, "RcloneUploadedFiles", MagicMock())
        monkeypatch.setattr(
            yd_submit, "update_config_work_requirement_object", lambda c: c
        )
        monkeypatch.setattr(yd_submit, "link_entity", lambda *a: "[link]")

        def _run(wr_file: str | None, **values):
            client = MagicMock()

            def _add(work_requirement):
                work_requirement.id = WR_ID
                return work_requirement

            client.work_client.add_work_requirement.side_effect = _add
            return run(
                yd_submit,
                client=client,
                **{
                    "upgrade_rclone": False,
                    "which_rclone": False,
                    "json_raw": None,
                    "work_req_file": None,
                    "work_requirement_file_positional": wr_file,
                    "csv_files": None,
                    "process_csv_only": False,
                    "add_to": None,
                    "empty": False,
                    "hold": False,
                    "progress": False,
                    "follow": False,
                    **values,
                },
            )

        _run.run = run  # type: ignore[attr-defined]
        return _run

    def test_validate_stops_with_the_violations(self, submit, tmp_path):
        out, err, client = submit(
            _write(tmp_path, "wr.json", BAD), validate=True, json_output=True
        )
        assert submit.run.exit_code == 1
        assert [v["path"] for v in out] == [
            "taskGroups[0].maxWorkers",
            "taskGroups[0].tasks[0].taskType",
            "taskGroups[1]",
        ]
        assert all(v["source"].endswith("wr.json") and v["message"] for v in out)
        assert "must be integer" in err  # The errors, on stderr
        client.work_client.add_work_requirement.assert_not_called()

    @pytest.mark.parametrize("absolute", [False, True])
    def test_content_path_holds_the_files_not_the_specification(
        self, submit, tmp_path, monkeypatch, absolute
    ):
        # The specification is named from the current directory and its
        # taskDataFile found in --content-path, wherever each of them is
        monkeypatch.chdir(tmp_path)
        (tmp_path / "specs").mkdir()
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "input.txt").write_text("hello")
        spec = {
            "taskGroups": [
                {"tasks": [{"taskType": "bash", "taskDataFile": "input.txt"}]}
            ]
        }
        wr_file = _write(tmp_path / "specs", "wr.json", spec)
        _, err, client = submit(
            wr_file if absolute else "specs/wr.json", content_path="data"
        )
        assert submit.run.exit_code == 0, err
        [call] = client.work_client.add_tasks_to_task_group_by_name.call_args_list
        assert [task.taskData for task in call.args[3]] == ["hello"]

    def test_task_data_file_is_found_beside_the_specification(
        self, submit, tmp_path, monkeypatch
    ):
        # In a directory named as the specification's: the file it names
        # there, not the one the same name finds from the current directory
        monkeypatch.chdir(tmp_path)
        (tmp_path / "specs" / "specs").mkdir(parents=True)
        (tmp_path / "specs" / "input.json").write_text("from the current directory")
        (tmp_path / "specs" / "specs" / "input.json").write_text("beside the spec")
        spec = {
            "taskGroups": [
                {"tasks": [{"taskType": "bash", "taskDataFile": "specs/input.json"}]}
            ]
        }
        _write(tmp_path / "specs", "wr.json", spec)
        _, err, client = submit("specs/wr.json")
        assert submit.run.exit_code == 0, err
        [call] = client.work_client.add_tasks_to_task_group_by_name.call_args_list
        assert [task.taskData for task in call.args[3]] == ["beside the spec"]

    def test_validate_ok(self, submit, tmp_path):
        out, _, client = submit(_write(tmp_path, "wr.json", GOOD), validate=True)
        assert submit.run.exit_code == 0
        assert "valid against the work-requirement schema" in out
        client.work_client.add_work_requirement.assert_not_called()

    def test_validate_ok_under_json_is_an_empty_array(self, submit, tmp_path):
        out, _, _ = submit(
            _write(tmp_path, "wr.json", GOOD), validate=True, json_output=True
        )
        assert submit.run.exit_code == 0 and out == []

    def test_an_ordinary_run_warns_and_proceeds(self, submit, tmp_path):
        out, _, client = submit(_write(tmp_path, "wr.json", TOLERATED))
        assert submit.run.exit_code == 0
        assert "WARNING" in out and "taskGroups[0].tasks[0]" in out
        client.work_client.add_work_requirement.assert_called_once()

    def test_under_json_the_warnings_are_on_stderr(self, submit, tmp_path):
        out, err, _ = submit(_write(tmp_path, "wr.json", TOLERATED), json_output=True)
        assert submit.run.exit_code == 0
        assert out["id"] == WR_ID and "taskGroups[0].tasks[0]" in err

    def test_the_toml_branch_is_checked(self, submit, tmp_path):
        path = tmp_path / "wr.toml"
        path.write_text('[[taskGroups]]\nmaxWorkers = "ten"\n[[taskGroups.tasks]]\n')
        out, _, _ = submit(str(path), validate=True, json_output=True)
        assert submit.run.exit_code == 1
        assert [v["path"] for v in out] == ["taskGroups[0].maxWorkers"]

    def test_the_csv_expanded_document_is_checked(self, submit, tmp_path):
        wr = {
            "taskGroups": [{"maxWorkers": "ten", "tasks": [{"arguments": ["<<a>>"]}]}]
        }
        csv = tmp_path / "t.csv"
        csv.write_text("a\n1\n2\n")
        out, _, _ = submit(
            _write(tmp_path, "wr.json", wr),
            csv_files=[str(csv)],
            validate=True,
            json_output=True,
        )
        assert submit.run.exit_code == 1
        assert [v["path"] for v in out] == ["taskGroups[0].maxWorkers"]

    def test_validate_without_a_file_is_refused(self, submit):
        _, err, _ = submit(None, validate=True)
        assert submit.run.exit_code == 1 and "'--validate' needs" in err

    def test_jsonnet_dry_run_without_a_file_is_refused(self, submit):
        # It was ignored, and the Work Requirement the configuration
        # describes was submitted
        _, err, client = submit(None, jsonnet_dry_run=True)
        assert submit.run.exit_code == 1
        assert "'--jsonnet-dry-run' needs a Jsonnet Work Requirement" in err
        client.work_client.add_work_requirement.assert_not_called()

    def test_jsonnet_dry_run_with_only_a_csv_file_is_refused(self, submit, tmp_path):
        csv = tmp_path / "tasks.csv"
        csv.write_text("a\n1\n", encoding="utf-8")
        _, err, client = submit(None, csv_files=[str(csv)], jsonnet_dry_run=True)
        assert submit.run.exit_code == 1
        assert "'--jsonnet-dry-run' needs" in err
        client.work_client.add_work_requirement.assert_not_called()

    def test_validate_with_json_raw_is_refused(self, capsys):
        # As the command line is parsed (exit 2): a raw Platform document has
        # no schema to check it against
        from yellowdog_cli.utils.args import CLIParser

        with pytest.raises(SystemExit) as raised:
            CLIParser(
                command="yd-submit", argv=["--json-raw", "raw.json", "--validate"]
            )
        assert raised.value.code == 2
        assert "--json-raw cannot be used with --validate" in capsys.readouterr().err

    def test_an_unbuildable_schema_warns_once_and_proceeds(
        self, submit, tmp_path, unbuildable
    ):
        out, _, client = submit(_write(tmp_path, "wr.json", GOOD))
        assert submit.run.exit_code == 0
        text = " ".join(out.split())  # Unwrapped
        assert text.count("WARNING") == 1
        assert "cannot check" in text and "RetryPolicy.maxRetries" in text
        assert "run 'yd-schema work-requirement' to see why" in text
        client.work_client.add_work_requirement.assert_called_once()

    def test_an_unbuildable_schema_stops_validate(self, submit, tmp_path, unbuildable):
        _, err, client = submit(_write(tmp_path, "wr.json", GOOD), validate=True)
        assert submit.run.exit_code == 1
        assert "RetryPolicy.maxRetries" in " ".join(err.split())
        client.work_client.add_work_requirement.assert_not_called()

    def test_the_schema_key_is_accepted_and_removed(self, submit, tmp_path):
        out, err, _ = submit(
            _write(tmp_path, "wr.json", {"$schema": "x.json", **GOOD}),
            dry_run=True,
            json_output=True,
        )
        assert submit.run.exit_code == 0
        assert "$schema" not in out and "WARNING" not in err


class TestProvision:
    @pytest.fixture()
    def provision(self, run, monkeypatch):
        import yellowdog_cli.provision as yd_provision

        monkeypatch.setattr(
            yd_provision,
            "CONFIG_WP",
            dataclasses.replace(
                lazy_value(yd_provision.CONFIG_WP),
                worker_pool_data_file=None,
                template_id="crt-id",
                name="wp-name",
                target_instance_count=1,
            ),
        )
        monkeypatch.setattr(
            yd_provision, "warn_of_undefined_worker_pool_variables", lambda: None
        )
        monkeypatch.setattr(yd_provision, "link_entity", lambda *a: "[link]")
        monkeypatch.setattr(yd_provision, "get_template_id", lambda *a, **k: "crt-id")
        monkeypatch.setattr(yd_provision, "get_user_data_property", lambda *a: None)

        def _run(wp_file: str | None, **values):
            return run(
                yd_provision,
                **{
                    "worker_pool_file": None,
                    "worker_pool_file_positional": wp_file,
                    **values,
                },
            )

        _run.run = run  # type: ignore[attr-defined]
        return _run

    def test_content_path_does_not_hold_the_specification(
        self, provision, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "specs").mkdir()
        (tmp_path / "data").mkdir()
        spec = {
            "requirementTemplateUsage": {"templateId": "t", "targetInstanceCount": 1},
            "provisionedProperties": {},
        }
        _write(tmp_path / "specs", "wp.json", spec)
        out, err, _ = provision("specs/wp.json", content_path="data", validate=True)
        assert provision.run.exit_code == 0, err
        assert "valid against the worker-pool schema" in out

    def test_validate_stops_with_the_violations(self, provision, tmp_path):
        spec = {
            "requirementTemplateUsage": {"templateId": "t", "targetInstanceCount": "x"},
            "provisionedProperties": {},
        }
        out, _, _ = provision(
            _write(tmp_path, "wp.json", spec), validate=True, json_output=True
        )
        assert provision.run.exit_code == 1
        assert [v["path"] for v in out] == [
            "requirementTemplateUsage.targetInstanceCount"
        ]

    def test_the_schema_key_is_not_posted(self, provision, tmp_path):
        spec = {
            "$schema": "worker-pool.schema.json",
            "requirementTemplateUsage": {"templateId": "t"},
            "provisionedProperties": {},
        }
        out, err, _ = provision(
            _write(tmp_path, "wp.json", spec), dry_run=True, json_output=True
        )
        assert provision.run.exit_code == 0
        assert "$schema" not in out and "WARNING" not in err

    def test_validate_without_a_file_is_refused(self, provision):
        _, err, _ = provision(None, validate=True)
        assert provision.run.exit_code == 1 and "'--validate' needs" in err

    def test_jsonnet_dry_run_without_a_file_is_refused(self, provision):
        _, err, client = provision(None, jsonnet_dry_run=True)
        assert provision.run.exit_code == 1
        assert "'--jsonnet-dry-run' needs a Jsonnet Worker Pool" in err
        client.worker_pool_client.provision_worker_pool.assert_not_called()


class TestInstantiate:
    @pytest.fixture()
    def instantiate(self, run, monkeypatch):
        import yellowdog_cli.instantiate as yd_instantiate

        monkeypatch.setattr(
            yd_instantiate,
            "CONFIG_WP",
            dataclasses.replace(
                lazy_value(yd_instantiate.CONFIG_WP),
                worker_pool_data_file=None,
                compute_requirement_data_file=None,
                template_id="crt-id",
                name="cr-name",
                target_instance_count=1,
            ),
        )
        monkeypatch.setattr(
            yd_instantiate, "warn_of_undefined_worker_pool_variables", lambda: None
        )

        def _run(cr_file: str, **values):
            return run(
                yd_instantiate,
                **{
                    "worker_pool_file": None,
                    "compute_requirement": None,
                    "compute_requirement_file_positional": cr_file,
                    "report": False,
                    **values,
                },
            )

        _run.run = run  # type: ignore[attr-defined]
        return _run

    def test_validate_without_a_file_is_refused(self, instantiate):
        _, err, client = instantiate(None, validate=True)
        assert instantiate.run.exit_code == 1 and "'--validate' needs" in err
        client.compute_client.provision_compute_requirement_template.assert_not_called()

    def test_jsonnet_dry_run_without_a_file_is_refused(self, instantiate):
        _, err, client = instantiate(None, jsonnet_dry_run=True)
        assert instantiate.run.exit_code == 1
        assert "'--jsonnet-dry-run' needs a Jsonnet Compute Requirement" in err
        client.compute_client.provision_compute_requirement_template.assert_not_called()

    def test_validate_the_flat_form(self, instantiate, tmp_path):
        out, _, client = instantiate(
            _write(tmp_path, "cr.json", {"templateId": "t", "bogus": 1}),
            validate=True,
            json_output=True,
        )
        assert instantiate.run.exit_code == 1
        assert out == [
            {
                "source": str(tmp_path / "cr.json"),
                "path": DOCUMENT_PATH,
                "message": "unknown property 'bogus'",
            }
        ]
        client.compute_client.provision_compute_requirement_template.assert_not_called()

    def test_validate_a_worker_pool_file_ok(self, instantiate, tmp_path):
        spec = {
            "requirementTemplateUsage": {"templateId": "t"},
            "provisionedProperties": {},
        }
        out, _, _ = instantiate(_write(tmp_path, "wp.json", spec), validate=True)
        assert instantiate.run.exit_code == 0
        assert "valid against the compute-requirement schema" in out


class TestCreate:
    @pytest.fixture()
    def create(self, run):
        import yellowdog_cli.create as create_command
        import yellowdog_cli.utils.resource_creation as resource_creation

        def _run(files: list[str], **values):
            return run(
                resource_creation,
                main_module=create_command,
                also=(load_resources_module, create_command),
                **{
                    "resource_specifications": files,
                    "no_resequence": False,
                    "show_keyring_passwords": False,
                    "regenerate_app_keys": False,
                    "match_allowances_by_description": False,
                    **values,
                },
            )

        _run.run = run  # type: ignore[attr-defined]
        return _run

    def test_validate_reports_every_file(self, create, tmp_path):
        one = _write(
            tmp_path, "one.json", {"resource": "Keyring", "name": 3, "description": "d"}
        )
        two = _write(
            tmp_path,
            "two.json",
            [
                {"resource": "Keyring", "name": "k", "description": "d"},
                {"resource": "Nope"},
            ],
        )
        out, _, client = create([one, two], validate=True, json_output=True)
        assert create.run.exit_code == 1
        assert [(v["source"], v["path"]) for v in out] == [
            (one, "name"),
            (two, "[1].resource"),
        ]
        client.keyring_client.add_keyring.assert_not_called()

    def test_validate_ok(self, create, tmp_path):
        one = _write(
            tmp_path,
            "one.json",
            {"resource": "Keyring", "name": "k", "description": "d"},
        )
        out, _, _ = create([one], validate=True)
        assert create.run.exit_code == 0 and "valid against the resources schema" in out

    def test_an_ordinary_run_warns_and_the_schema_key_is_removed(
        self, create, tmp_path
    ):
        one = _write(
            tmp_path,
            "one.json",
            [
                {
                    "$schema": "r.json",
                    "resource": "Keyring",
                    "name": "k",
                    "description": "d",
                },
                {"resource": "Keyring", "name": "k2", "description": "d", "bogus": 1},
            ],
        )
        out, err, _ = create([one], dry_run=True, json_output=True)
        assert create.run.exit_code == 0
        assert all("$schema" not in spec for spec in out)
        assert "[1]: unknown property 'bogus'" in err

    @pytest.mark.parametrize("creation", [True, False])
    def test_only_creation_warns(self, monkeypatch, tmp_path, capsys, creation):
        # yd-remove reads only the names: the schema is yd-create's. A
        # Keyring with no description is a violation for yd-create, so the
        # creation case shows the warning would be seen if it were printed
        one = _write(tmp_path, "one.json", {"resource": "Keyring", "name": "k"})
        args = MagicMock(
            resource_specifications=[one],
            jsonnet_dry_run=False,
            no_resequence=False,
            validate=None,
            json_output=False,
            quiet=False,
            count_only=False,
            print_pid=False,
            no_format=True,
        )
        output_settings.configure_output(args)
        resources = load_resources_module.load_resource_specifications(
            args, creation_or_update=creation
        )
        assert resources[0]["name"] == "k"
        assert ("WARNING" in capsys.readouterr().out) is creation


class TestNodeAction:
    @pytest.fixture()
    def nodeaction(self, run):
        import yellowdog_cli.nodeaction as yd_nodeaction

        def _run(spec_file: str | None, **values):
            return run(
                yd_nodeaction,
                **{"status": False, "node_action_spec": spec_file, **values},
            )

        _run.run = run  # type: ignore[attr-defined]
        return _run

    @pytest.mark.parametrize(
        "argv, message",
        [
            (["--validate"], "--actions is required"),
            (["--status", "--validate"], "--validate cannot be used with --status"),
        ],
    )
    def test_validate_is_refused_where_it_checks_nothing(self, argv, message, capsys):
        # As the command line is parsed (exit 2), before anything is looked up
        from yellowdog_cli.utils.args import CLIParser

        with pytest.raises(SystemExit) as raised:
            CLIParser(command="yd-nodeaction", argv=argv)
        assert raised.value.code == 2
        assert message in capsys.readouterr().err

    def test_validate_stops_with_the_violations(self, nodeaction, tmp_path):
        out, _, client = nodeaction(
            _write(tmp_path, "a.json", {"actions": [{"type": "runCommand"}]}),
            validate=True,
            json_output=True,
        )
        assert nodeaction.run.exit_code == 1
        assert [v["path"] for v in out] == ["actions[0]"]
        client.worker_pool_client.get_worker_pool_by_id.assert_not_called()

    def test_validate_ok(self, nodeaction, tmp_path):
        spec = {
            "$schema": "n.json",
            "actions": [{"type": "runCommand", "path": "/bin/true"}],
        }
        out, _, _ = nodeaction(_write(tmp_path, "a.json", spec), validate=True)
        assert nodeaction.run.exit_code == 0
        assert "valid against the node-actions schema" in out


def test_jsonnet_is_checked_after_evaluation(run, tmp_path, monkeypatch):
    pytest.importorskip("_jsonnet")
    import yellowdog_cli.nodeaction as yd_nodeaction

    path = tmp_path / "a.jsonnet"
    path.write_text("{ actions: [{ type: 'run' + 'Command' }] }")
    out, _, _ = run(
        yd_nodeaction,
        status=False,
        node_action_spec=str(path),
        validate=True,
        json_output=True,
    )
    assert run.exit_code == 1
    assert [v["path"] for v in out] == ["actions[0]"]
