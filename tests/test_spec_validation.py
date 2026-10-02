"""
utils/spec_validation.py: every violation in a document is reported with
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
from yellowdog_cli.utils.property_names import ALL_KEYS, SCHEMA_KEY
from yellowdog_cli.utils.results import reset_results
from yellowdog_cli.utils.spec_schema import Family, compile_schema
from yellowdog_cli.utils.spec_validation import (
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
        import yellowdog_cli.utils.spec_validation as spec_validation_module

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
        for target in (printing_module, results_module):
            monkeypatch.setattr(target, "ARGS_PARSER", args)
        return args

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

        import yellowdog_cli.utils.spec_validation as spec_validation_module

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
    run(module, client=None, also=(), **args): patch ARGS_PARSER in the
    command module, the modules it prints and records through, and those in
    'also'; run module.main() through the wrapper; return (stdout, stderr,
    client), stdout parsed as JSON under json_output. The exit code is left
    in run.exit_code.
    """
    reset_results()

    def _run(module, client=None, also=(), **values):
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
            monkeypatch.setattr(target, "ARGS_PARSER", args)
        monkeypatch.setattr(module, "CLIENT", client)
        monkeypatch.setattr(wrapper_module, "CLIENT", MagicMock())
        config = MagicMock(namespace="ns", name_tag="tag", url="https://u")
        monkeypatch.setattr(module, "CONFIG_COMMON", config)
        with pytest.raises(SystemExit) as exit_info:
            module.main()
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
                yd_submit.CONFIG_WR,
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
        monkeypatch.setattr(
            yd_submit,
            "WR_SNAPSHOT",
            printing_module.WorkRequirementSnapshot(),
            raising=False,
        )

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

    def test_validate_with_json_raw_is_refused(self, submit, tmp_path, monkeypatch):
        import yellowdog_cli.submit as yd_submit

        submit_json_raw = MagicMock()
        monkeypatch.setattr(yd_submit, "submit_json_raw", submit_json_raw)
        _, err, client = submit(
            None, json_raw=_write(tmp_path, "raw.json", {"x": 1}), validate=True
        )
        assert submit.run.exit_code == 1 and "'--json-raw'" in err
        submit_json_raw.assert_not_called()
        client.work_client.add_work_requirement.assert_not_called()

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
                yd_provision.CONFIG_WP,
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


class TestInstantiate:
    @pytest.fixture()
    def instantiate(self, run, monkeypatch):
        import yellowdog_cli.instantiate as yd_instantiate

        monkeypatch.setattr(
            yd_instantiate,
            "CONFIG_WP",
            dataclasses.replace(
                yd_instantiate.CONFIG_WP,
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
        import yellowdog_cli.create as yd_create

        def _run(files: list[str], **values):
            return run(
                yd_create,
                also=(load_resources_module,),
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
        for target in (load_resources_module, printing_module):
            monkeypatch.setattr(target, "ARGS_PARSER", args)
        resources = load_resources_module.load_resource_specifications(
            creation_or_update=creation
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

    def test_validate_without_actions_is_refused(self, nodeaction):
        _, err, client = nodeaction(None, validate=True, json_output=True)
        assert nodeaction.run.exit_code == 1 and "'--validate' needs" in err
        client.worker_pool_client.get_worker_pool_by_id.assert_not_called()

    def test_validate_with_status_is_refused(self, nodeaction, tmp_path):
        spec = _write(tmp_path, "a.json", {"actions": [{"type": "runCommand"}]})
        _, err, client = nodeaction(spec, status=True, validate=True, json_output=True)
        assert nodeaction.run.exit_code == 1 and "'--status'" in err
        client.worker_pool_client.get_worker_pool_by_id.assert_not_called()

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
