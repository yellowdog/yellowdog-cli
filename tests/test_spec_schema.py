"""
utils/spec_schema.py: the five families' schemas, built from the registry and
the installed SDK, compile under fastjsonschema; the SDK type mapping follows
the spec's table row by row on real SDK fields; anything unmapped raises; the
corpus and the README's examples validate.
"""

import dataclasses
import gc
import json
import re
import subprocess
import sys
import typing
from pathlib import Path

import fastjsonschema
import pytest
from resource_live import MISSING_NAMESPACE_FAILURE_NAMES

from yellowdog_cli.utils import sdk_models
from yellowdog_cli.utils.spec_schema import (
    FAMILY_COMMANDS,
    FULLY_QUALIFIED_PREFIX,
    UNSET_TOKEN,
    VARIABLE_TOKEN,
    Family,
    SchemaGenerationError,
    annotation_schema,
    build_schema,
    compile_schema,
    model_schema,
    polymorphic_members,
)

REPO = Path(__file__).resolve().parent.parent


def _unwrapped(schema: dict) -> dict:
    """A schema less the {{variable}} wrapping the generator adds."""
    if schema.get("if") == {"$ref": "#/$defs/variable"}:
        return schema["else"]
    return schema


def _non_null(schema: dict) -> dict:
    """A schema less the null an Optional field admits."""
    if schema.get("if") == {"type": "null"}:
        return schema["else"]
    if isinstance(schema.get("type"), list) and "null" in schema["type"]:
        kinds = [k for k in schema["type"] if k != "null"]
        return {**schema, "type": kinds[0] if len(kinds) == 1 else kinds}
    if schema.get("anyOf", [None])[-1] == {"type": "null"}:
        rest = schema["anyOf"][:-1]
        return rest[0] if len(rest) == 1 else {"anyOf": rest}
    if None in schema.get("enum", ()):
        return {**schema, "enum": [v for v in schema["enum"] if v is not None]}
    return schema


def _dispatched(schema: dict) -> dict[str, list]:
    """A polymorphic dispatch's cases: each member's $def name, and its values."""
    key = schema["required"][0]
    return {
        case["then"]["$ref"].rsplit("/", 1)[-1]: case["if"]["properties"][key]["enum"]
        for case in schema["allOf"]
    }


def _field_type(cls, name):
    return typing.get_type_hints(cls)[name]


def _rejects(validate, document, match: str | None = None) -> None:
    with pytest.raises(fastjsonschema.JsonSchemaException, match=match):
        validate(document)


class TestEveryFamily:
    @pytest.mark.parametrize("family", list(Family))
    def test_builds_and_compiles(self, family):
        schema = build_schema(family)
        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert schema["$id"].endswith(f"/{family.value}.schema.json")
        assert FAMILY_COMMANDS[family] in schema["description"]
        assert schema["$defs"]["variable"] == VARIABLE_TOKEN
        json.dumps(schema)  # serialisable as it stands
        fastjsonschema.compile(schema)
        assert compile_schema(family) is compile_schema(family)  # cached

    @pytest.mark.parametrize("family", list(Family))
    def test_the_schema_key_is_permitted_at_the_root(self, family):
        document = {
            Family.WORK_REQUIREMENT: {"taskGroups": [{"tasks": [{}]}]},
            Family.WORKER_POOL: {
                "requirementTemplateUsage": {},
                "provisionedProperties": {},
            },
            Family.COMPUTE_REQUIREMENT: {"templateId": "t"},
            Family.RESOURCES: {"resource": "Namespace", "name": "n"},
            Family.NODE_ACTIONS: {"actions": []},
            Family.CONFIG: {"common": {}},
        }[family]
        compile_schema(family)({"$schema": "x", **document})


class TestFamiliesMatchTheRegistry:
    # command_registry.py cannot import Family (that would pull the SDK and
    # fastjsonschema into every command's parse, and into mcp/tools.py, which
    # must stay SDK-free -- see tests/test_mcp_tools.py's
    # TestSdkFreeImport), so it carries its own SCHEMA_FAMILIES tuple in
    # settings.py; this is what holds the two in step.
    def test_same_values_as_the_registry_tuple(self):
        from yellowdog_cli.utils.settings import SCHEMA_FAMILIES

        assert {f.value for f in Family} == set(SCHEMA_FAMILIES)

    def test_same_order_as_the_registry_tuple(self):
        from yellowdog_cli.utils.settings import SCHEMA_FAMILIES

        assert tuple(f.value for f in Family) == SCHEMA_FAMILIES


class TestTypeMapping:
    def test_scalars_and_containers(self):
        from yellowdog_client.model import ComputeRequirementTemplateUsage as C
        from yellowdog_client.model import MachineImage

        defs: dict = {}

        def mapped(cls, name):
            return _non_null(annotation_schema(_field_type(cls, name), defs, owner="x"))

        assert mapped(C, "requirementName") == {"type": "string"}
        assert mapped(C, "targetInstanceCount") == {"type": "integer"}
        assert mapped(C, "maintainInstanceCount") == {"type": "boolean"}
        tags = mapped(C, "instanceTags")
        assert tags == {"type": "object", "additionalProperties": {"type": "string"}}
        regions = mapped(MachineImage, "regions")
        assert regions == {"type": "array", "items": {"type": "string"}}

    def test_an_optional_field_admits_null_and_a_required_one_does_not(self):
        from yellowdog_client.model import ComputeRequirementTemplateUsage as C

        defs: dict = {}
        assert annotation_schema(_field_type(C, "templateId"), defs, owner="x") == {
            "type": "string"
        }
        tag = annotation_schema(_field_type(C, "requirementTag"), defs, owner="x")
        assert tag == {"type": ["string", "null"]}
        validate = compile_schema(Family.COMPUTE_REQUIREMENT)
        validate({"templateId": "t", "requirementTag": None})
        _rejects(validate, {"templateId": None})

    def test_float_and_set(self):
        from yellowdog_client.model import NodeWorkerTarget, StringAttributeConstraint

        defs: dict = {}
        count = _non_null(
            annotation_schema(
                _field_type(NodeWorkerTarget, "targetCount"), defs, owner="x"
            )
        )
        assert count == {"type": "number"}
        any_of = _non_null(
            annotation_schema(
                _field_type(StringAttributeConstraint, "anyOf"), defs, owner="x"
            )
        )
        assert any_of == {"type": "array", "items": {"type": "string"}}

    def test_enum_timedelta_datetime(self):
        from yellowdog_client.model import (
            AutoShutdown,
            MachineImage,
            MachineImageFamily,
        )

        defs: dict = {}
        os_type = _non_null(
            annotation_schema(_field_type(MachineImage, "osType"), defs, owner="x")
        )
        assert set(os_type["enum"]) >= {"LINUX", "WINDOWS"}
        timeout = _non_null(
            annotation_schema(_field_type(AutoShutdown, "timeout"), defs, owner="x")
        )
        assert timeout["type"] == "string"
        for good in ("PT10M", "PT1H30M", "P1D", "PT0.5S"):
            assert re.match(timeout["pattern"], good), good
        for bad in ("P", "PT", "10M", "PT10"):
            assert not re.match(timeout["pattern"], bad), bad
        created = _non_null(
            annotation_schema(
                _field_type(MachineImageFamily, "createdTime"), defs, owner="x"
            )
        )
        assert created == {"type": "string", "format": "date-time"}

    def test_an_enum_keyed_mapping_names_its_keys(self):
        from yellowdog_client.model import NodeEvent, WorkerPoolNodeConfiguration

        defs: dict = {}
        events = _non_null(
            annotation_schema(
                _field_type(WorkerPoolNodeConfiguration, "nodeEvents"), defs, owner="x"
            )
        )
        assert events["propertyNames"] == {"enum": [e.value for e in NodeEvent]}
        assert events["additionalProperties"]["items"] == {
            "$ref": "#/$defs/NodeActionGroup"
        }

    def test_nested_dataclass_is_a_ref(self):
        from yellowdog_client.model import MachineImageFamily

        defs: dict = {}
        groups = _non_null(
            annotation_schema(
                _field_type(MachineImageFamily, "imageGroups"), defs, owner="x"
            )
        )
        assert groups["items"] == {"$ref": "#/$defs/MachineImageGroup"}
        assert "MachineImageGroup" in defs and "MachineImage" in defs  # transitively

    def test_generic_selection_is_expanded_inline(self):
        from yellowdog_client.model import RetryPolicy, TaskErrorSelector

        defs: dict = {}
        errors = _non_null(
            annotation_schema(_field_type(RetryPolicy, "retryErrors"), defs, owner="x")
        )
        assert errors["type"] == "object" and errors["additionalProperties"] is False
        assert set(errors["properties"]) == {"includes", "excludes"}
        assert _non_null(errors["properties"]["includes"])["items"] == {
            "$ref": "#/$defs/TaskErrorSelector"
        }
        codes = _non_null(defs["TaskErrorSelector"]["properties"]["processExitCodes"])
        includes = _non_null(codes["properties"]["includes"])
        assert includes["items"] == {"type": "integer"}
        assert TaskErrorSelector.__name__ in defs

    def test_required_follows_the_sdk(self):
        from yellowdog_client.model import AddApplicationRequest

        schema = model_schema(AddApplicationRequest, {})
        assert (
            schema["required"] == ["name"] and schema["additionalProperties"] is False
        )

    def test_a_model_allows_exactly_its_settable_properties(self):
        from yellowdog_client.model import AwsInstancesComputeSource

        schema = model_schema(AwsInstancesComputeSource, {})
        assert set(schema["properties"]) == sdk_models.settable_properties(
            "AwsInstancesComputeSource"
        ) | {"userDataFile", "userDataFiles"}

    def test_polymorphic_base_is_dispatched_over_the_family(self):
        from yellowdog_client.model import ComputeSourceTemplate

        defs: dict = {}
        source = annotation_schema(
            _field_type(ComputeSourceTemplate, "source"), defs, owner="x"
        )
        cases = _dispatched(source)
        refs = set(cases)
        assert refs == set(sdk_models.POLYMORPHIC_FAMILIES["ComputeSource"])
        assert source["required"] == ["type"]
        # Every accepted value, so an unknown type is named against them all
        assert source["properties"]["type"]["enum"] == [
            value for values in cases.values() for value in values
        ]
        for name in refs:
            discriminator = defs[name]["properties"]["type"]
            assert set(discriminator["enum"]) == {name, FULLY_QUALIFIED_PREFIX + name}
            assert "type" in defs[name]["required"]
            assert {"userDataFile", "userDataFiles"} <= set(defs[name]["properties"])

    def test_a_credential_discriminator_is_its_declared_name(self):
        from yellowdog_client.model import AwsCredential, Credential

        defs: dict = {}
        annotation_schema(Credential, defs, owner="x")
        assert set(defs["AwsCredential"]["properties"]["type"]["enum"]) == {
            "AwsCredential",
            AwsCredential.type,
        }

    def test_a_nested_polymorphic_base_takes_only_the_declared_name(self):
        """The CLI does not read these; the SDK dispatches on the exact value."""
        from yellowdog_client.model import ComputeRequirementDynamicTemplate

        defs: dict = {}
        constraints = _non_null(
            annotation_schema(
                _field_type(ComputeRequirementDynamicTemplate, "constraints"),
                defs,
                owner="x",
            )
        )
        cases = _dispatched(constraints["items"])
        assert set(cases) == {"NumericAttributeConstraint", "StringAttributeConstraint"}
        assert cases["StringAttributeConstraint"] == [
            FULLY_QUALIFIED_PREFIX + "StringAttributeConstraint"
        ]
        assert defs["StringAttributeConstraint"]["properties"]["type"] == {
            "const": FULLY_QUALIFIED_PREFIX + "StringAttributeConstraint"
        }

    def test_a_worker_pool_node_action_takes_the_sdk_action(self):
        """A Worker Pool file is posted as written: 'action', and 'nodeIdFilter'."""
        defs = build_schema(Family.WORKER_POOL)["$defs"]
        run = defs["NodeRunCommandAction"]
        assert _unwrapped(run["properties"]["action"]) == {"const": "RUN_COMMAND"}
        assert "nodeIdFilter" in run["properties"]

    def test_an_unmappable_annotation_raises_naming_the_owner(self):
        with pytest.raises(SchemaGenerationError, match=r"Widget\.gizmo.*complex"):
            annotation_schema(complex, {}, owner="Widget.gizmo")

    def test_an_unbound_type_variable_raises(self):
        with pytest.raises(SchemaGenerationError, match=r"Widget\.gizmo"):
            annotation_schema(typing.TypeVar("X"), {}, owner="Widget.gizmo")

    def test_an_unmappable_sdk_field_raises_naming_model_and_field(self, monkeypatch):
        from yellowdog_client.model import AddApplicationRequest

        original = typing.get_type_hints

        def hints(cls, *args, **kwargs):
            found = original(cls, *args, **kwargs)
            return {**found, "name": complex} if cls is AddApplicationRequest else found

        monkeypatch.setattr(typing, "get_type_hints", hints)
        with pytest.raises(SchemaGenerationError, match=r"AddApplicationRequest\.name"):
            model_schema(AddApplicationRequest, {})


class TestPolymorphicFamilies:
    # The classes these two define join Credential.__subclasses__(), which the
    # SDK's own dispatch reads too, so each is a direct subclass of the base
    # (no SDK leaf stops being one) and is collected before the test ends

    def test_a_subclass_defined_outside_the_sdk_is_not_a_member(self):
        from yellowdog_client.model import Credential

        @dataclasses.dataclass
        class ForeignCredential(Credential):
            type: str = dataclasses.field(default="elsewhere.Foreign", init=False)

        try:
            names = {m.__name__ for m in polymorphic_members(Credential)}
            assert names == sdk_models.POLYMORPHIC_FAMILIES["Credential"]
        finally:
            del ForeignCredential
            gc.collect()
        assert all(
            c.__module__.startswith("yellowdog_client")
            for c in Credential.__subclasses__()
        )

    def test_a_non_dataclass_member_raises(self):
        from yellowdog_client.model import Credential

        class Loose(Credential):
            __module__ = "yellowdog_client.model.loose"

        try:
            with pytest.raises(SchemaGenerationError, match="Loose is not a dataclass"):
                polymorphic_members(Credential)
        finally:
            del Loose
            gc.collect()
        assert "Loose" not in {c.__name__ for c in Credential.__subclasses__()}

    @pytest.mark.parametrize("base", sorted(sdk_models.POLYMORPHIC_FAMILIES))
    def test_the_registry_matches_the_sdks_own_dispatch(self, base):
        members = polymorphic_members(sdk_models.model_class(base))
        assert {m.__name__ for m in members} == sdk_models.POLYMORPHIC_FAMILIES[base]

    def test_the_families_are_the_dynamic_models(self):
        union = set().union(
            *(
                members
                for base, members in sdk_models.POLYMORPHIC_FAMILIES.items()
                if base != "NodeAction"
            )
        )
        assert union == sdk_models.DYNAMIC_MODELS - {"ComputeSourceTemplate"}


class TestWrapping:
    def test_a_variable_token_passes_where_an_integer_is_expected(self):
        validate = compile_schema(Family.WORK_REQUIREMENT)
        validate({"taskGroups": [{"tasks": [{}], "maxWorkers": "{{num:workers}}"}]})
        _rejects(validate, {"taskGroups": [{"tasks": [{}], "maxWorkers": "ten"}]})

    def test_a_variable_token_passes_where_an_array_or_object_is_expected(self):
        validate = compile_schema(Family.WORK_REQUIREMENT)
        validate(
            {
                "arguments": "{{array:args}}",
                "environment": "{{table:env}}",
                "taskGroups": [{"tasks": [{}], "retryPolicy": "{{table:retry}}"}],
            }
        )

    def test_a_variable_token_passes_inside_an_sdk_model(self):
        validate = compile_schema(Family.WORK_REQUIREMENT)
        policy = {
            "maxRetries": "{{num:retries}}",
            "retryErrors": {
                "includes": [{"processExitCodes": {"includes": ["{{num:c}}"]}}]
            },
        }
        validate({"taskGroups": [{"tasks": [{}], "retryPolicy": policy}]})
        _rejects(
            validate,
            {"taskGroups": [{"tasks": [{}], "retryPolicy": {"maxRetries": "two"}}]},
        )

    def test_the_unset_token_passes_anywhere(self):
        assert re.match(VARIABLE_TOKEN["pattern"], UNSET_TOKEN["const"])
        validate = compile_schema(Family.WORK_REQUIREMENT)
        validate({"taskGroups": [{"tasks": [{}], "retryPolicy": "{{::}}"}]})
        validate({"taskGroups": [{"tasks": [{"timeout": "{{t::}}"}]}]})

    def test_a_failure_inside_the_wrapping_keeps_its_path(self):
        validate = compile_schema(Family.WORKER_POOL)
        _rejects(
            validate,
            {
                "requirementTemplateUsage": {"templateId": "t", "bogus": 1},
                "provisionedProperties": {},
            },
            r"data\.requirementTemplateUsage must not contain .*bogus",
        )

    def test_a_failure_inside_a_polymorphic_member_keeps_its_path(self):
        validate = compile_schema(Family.RESOURCES)
        source = {"type": "SimulatorComputeSource", "name": "s", "limit": "ten"}
        _rejects(
            validate,
            {"resource": "ComputeSourceTemplate", "namespace": "n", "source": source},
            r"data\.source\.limit must be integer",
        )

    def test_an_unknown_polymorphic_type_is_named(self):
        validate = compile_schema(Family.RESOURCES)
        _rejects(
            validate,
            {
                "resource": "ComputeSourceTemplate",
                "namespace": "n",
                "source": {"type": "NoSuchComputeSource", "name": "s"},
            },
            r"data\.source\.type must be one of",
        )

    def test_a_failure_inside_an_optional_model_keeps_its_path(self):
        validate = compile_schema(Family.WORKER_POOL)
        _rejects(
            validate,
            {
                "requirementTemplateUsage": {"templateId": "t"},
                "provisionedProperties": {"idleNodeShutdown": {"enabled": "yes"}},
            },
            r"data\.provisionedProperties\.idleNodeShutdown\.enabled must be",
        )

    def test_an_optional_model_admits_null_and_a_variable(self):
        validate = compile_schema(Family.WORKER_POOL)
        for value in (None, "{{shutdown}}", {"enabled": True}):
            validate(
                {
                    "requirementTemplateUsage": {"templateId": "t"},
                    "provisionedProperties": {"idleNodeShutdown": value},
                }
            )

    def test_schema_key_is_allowed_and_unknown_keys_are_not(self):
        validate = compile_schema(Family.WORK_REQUIREMENT)
        validate({"$schema": "x", "taskGroups": [{"tasks": [{}]}]})
        _rejects(validate, {"taskGroups": [{"tasks": [{}]}], "nope": 1}, "nope")
        _rejects(
            validate, {"$schema": "x", "taskGroups": [{"$schema": "x", "tasks": [{}]}]}
        )

    def test_levels_are_enforced(self):
        validate = compile_schema(Family.WORK_REQUIREMENT)
        _rejects(
            validate,
            {"dependencies": ["a"], "taskGroups": [{"tasks": [{}]}]},
            "dependencies",
        )
        validate({"taskGroups": [{"dependencies": ["a"], "tasks": [{"timeout": 5}]}]})
        _rejects(validate, {"taskGroups": [{"tasks": [{"csvFile": "x.csv"}]}]})

    def test_task_groups_and_tasks_are_required(self):
        validate = compile_schema(Family.WORK_REQUIREMENT)
        _rejects(validate, {})
        _rejects(validate, {"taskGroups": [{}]})

    def test_descriptions_sit_beside_the_wrapping(self):
        schema = build_schema(Family.WORK_REQUIREMENT)
        retry = schema["properties"]["retryPolicy"]
        assert retry["description"] and "description" not in _unwrapped(retry)
        assert _unwrapped(retry) == {"$ref": "#/$defs/RetryPolicy"}
        assert schema["$defs"]["taskGroup"]["properties"]["dependentOn"]["deprecated"]


class TestFamilies:
    def test_a_worker_pool_leaves_what_the_toml_file_supplies_optional(self):
        validate = compile_schema(Family.WORKER_POOL)
        validate({"requirementTemplateUsage": {}, "provisionedProperties": {}})
        _rejects(validate, {"requirementTemplateUsage": {}})
        _rejects(
            validate,
            {
                "requirementTemplateUsage": {"templateId": "t", "bogus": 1},
                "provisionedProperties": {},
            },
            "bogus",
        )

    def test_a_compute_requirement_failure_names_its_path(self):
        _rejects(
            compile_schema(Family.COMPUTE_REQUIREMENT),
            {"requirementTemplateUsage": {"templateId": "x", "bogus": 1}},
            r"data\.requirementTemplateUsage must not contain .*bogus",
        )
        _rejects(
            compile_schema(Family.COMPUTE_REQUIREMENT),
            {"templateId": "x", "bogus": 1},
            r"data must not contain .*bogus",
        )

    def test_environment_values_are_strings(self):
        validate = compile_schema(Family.WORK_REQUIREMENT)
        _rejects(
            validate,
            {"taskGroups": [{"tasks": [{"environment": {"A": 100}}]}]},
            r"data\.taskGroups\[0\]\.tasks\[0\]\.environment\.A must be string",
        )
        validate({"taskGroups": [{"tasks": [{"environment": {"A": "{{num:x}}"}}]}]})

    def test_a_compute_requirement_is_wrapped_or_flat(self):
        validate = compile_schema(Family.COMPUTE_REQUIREMENT)
        validate({"templateId": "t", "targetInstanceCount": 2})
        validate({"requirementTemplateUsage": {"templateId": "t"}})
        # A Worker Pool file is accepted, its provisionedProperties ignored
        validate(
            {
                "requirementTemplateUsage": {"templateId": "t"},
                "provisionedProperties": {"maxNodes": 2},
            }
        )
        _rejects(validate, {"templateId": "t", "maxNodes": 2})

    def test_a_resource_takes_its_models_properties_and_its_shell(self):
        validate = compile_schema(Family.RESOURCES)
        validate({"resource": "Keyring", "name": "k", "description": "d"})
        validate([{"resource": "Namespace", "name": "n"}])
        validate(
            {
                "resource": "Application",
                "name": "a",
                "groups": ["g"],
                "keyrings": ["k"],
            }
        )
        _rejects(validate, {"resource": "Keyring", "name": "k"})
        _rejects(validate, {"resource": "Nonsense", "name": "k"})
        _rejects(validate, {"resource": "Application", "name": "a", "bogus": 1})

    def test_namespace_is_required_where_yd_create_demands_it(self):
        validate = compile_schema(Family.RESOURCES)
        source = {
            "type": "SimulatorComputeSource",
            "name": "s",
            "credential": "k/c",
            "region": "r",
            "instanceType": "t",
            "imageId": "i",
        }
        validate(
            {"resource": "ComputeSourceTemplate", "namespace": "n", "source": source}
        )
        _rejects(
            validate,
            {"resource": "ComputeSourceTemplate", "source": source},
            r"data must contain \['namespace'\]",
        )
        _rejects(
            validate,
            {"resource": "ConfiguredWorkerPool", "name": "p"},
            r"must contain \['namespace'\]",
        )
        _rejects(
            validate,
            {
                "resource": "ComputeRequirementTemplate",
                "type": "ComputeRequirementStaticTemplate",
                "name": "t",
                "strategyType": "s",
                "sources": [],
            },
            r"must contain \['namespace'\]",
        )

    def test_a_user_needs_one_of_its_identities(self):
        validate = compile_schema(Family.RESOURCES)
        validate({"resource": "InternalUser", "username": "u", "groups": ["g"]})
        validate({"resource": "ExternalUser", "id": "ydid:user:x"})
        _rejects(validate, {"resource": "InternalUser", "groups": ["g"]})
        _rejects(validate, {"resource": "ExternalUser", "username": "u"})

    def test_a_credential_is_one_of_the_credential_classes(self):
        validate = compile_schema(Family.RESOURCES)
        credential = {"name": "c", "accessKeyId": "a", "secretAccessKey": "s"}
        for kind in (
            "AwsCredential",
            "co.yellowdog.platform.account.credentials.AwsCredential",
        ):
            validate(
                {
                    "resource": "Credential",
                    "keyringName": "k",
                    "credential": {"type": kind, **credential},
                }
            )
        _rejects(
            validate,
            {
                "resource": "Credential",
                "keyringName": "k",
                "credential": {"type": "AwsCredential", "name": "c"},
            },
        )

    def test_an_allowance_date_is_a_dateparser_string(self):
        validate = compile_schema(Family.RESOURCES)
        validate(
            {
                "resource": "Allowance",
                "type": "AccountAllowance",
                "effectiveFrom": "Now",
                "resetType": "NONE",
                "limitEnforcement": "HARD",
                "monitoredStatuses": ["RUNNING"],
                "allowedHours": 10,
            }
        )

    def test_a_node_action_takes_only_its_own_types_properties(self):
        validate = compile_schema(Family.NODE_ACTIONS)
        _rejects(
            validate,
            {"actions": [{"type": "runCommand", "content": "x", "path": "/p"}]},
        )
        _rejects(validate, {"actions": [{"type": "runCommand"}]})  # path is required
        _rejects(validate, {"actions": [{"type": "rm", "path": "/p"}]})
        _rejects(
            validate,
            {
                "actions": [
                    {
                        "type": "writeFile",
                        "path": "/p",
                        "content": "x",
                        "contentFile": "f",
                    }
                ]
            },
        )
        _rejects(
            validate,
            {
                "actions": [
                    {"type": "runCommand", "path": "/p", "nodeIdFilter": "EVENT"}
                ]
            },
        )
        _rejects(validate, {"actions": [], "actionGroups": []})
        _rejects(validate, {})


def _known_partial_failure(file_name: str, resource_name: str) -> bool:
    """A corpus specification the live layer expects yd-create to reject."""
    return any(
        resource_name.endswith(f"-{suffix}")
        for suffix in MISSING_NAMESPACE_FAILURE_NAMES.get(file_name, ())
    )


class TestCorpusAndExamples:
    def test_every_corpus_specification_validates(self):
        import resource_corpus

        resource_corpus.require_jsonnet()
        validate = compile_schema(Family.RESOURCES)
        previous = resource_corpus.install_variables()
        try:
            count = exempted = 0
            for path in resource_corpus.corpus_files():
                for resource in resource_corpus.load_corpus_file(path):
                    resource = {k: v for k, v in resource.items() if k != "_sourceDir"}
                    name = str(resource.get("name", ""))
                    if _known_partial_failure(path.name, name):
                        # yd-create itself rejects these (no 'namespace'): the
                        # schema must too, and for that reason alone
                        _rejects(validate, resource, r"must contain \['namespace'\]")
                        exempted += 1
                        continue
                    try:
                        validate(resource)
                    except fastjsonschema.JsonSchemaException as e:
                        pytest.fail(f"{path.name}: {name}: {e}")
                    count += 1
        finally:
            resource_corpus.remove_variables(previous)
        assert count > 20
        assert exempted == sum(map(len, MISSING_NAMESPACE_FAILURE_NAMES.values()))

    def _json_blocks(self, start: str, end: str) -> list:
        """The README's parseable JSON blocks from the line starting 'start' to
        the one starting 'end', or to the end of the file if none does."""
        lines = (REPO / "README.md").read_text().splitlines()
        s = next(i for i, line in enumerate(lines) if line.startswith(start))
        e = next(
            (i for i, line in enumerate(lines) if line.startswith(end)), len(lines)
        )
        blocks, i = [], s
        while i < e:
            if lines[i].strip() == "```json":
                j = i + 1
                while lines[j].strip() != "```":
                    j += 1
                try:
                    blocks.append(json.loads("\n".join(lines[i + 1 : j])))
                except json.JSONDecodeError:
                    pass  # an elided example
                i = j
            i += 1
        assert blocks
        return blocks

    def test_the_readme_work_requirement_examples_validate(self):
        validate = compile_schema(Family.WORK_REQUIREMENT)
        schema = build_schema(Family.WORK_REQUIREMENT)
        task_group = schema["$defs"]["taskGroup"]
        fragment = fastjsonschema.compile(
            {
                **{k: v for k, v in schema.items() if k != "required"},
                "properties": task_group["properties"],
            }
        )
        whole = fragments = 0
        # Up to the dry-run section, whose example is the processed output
        # sent to the Platform, not a specification
        for block in self._json_blocks(
            "## Work Requirement JSON File Structure",
            "## Dry-Running Work Requirement Submissions",
        ):
            if isinstance(block, dict) and "taskGroups" in block:
                validate(block)
                whole += 1
            elif isinstance(block, dict):
                fragment(block)  # a Task Group excerpt
                fragments += 1
        assert whole >= 5 and fragments  # a floor against losing the extraction

    def test_the_readme_worker_pool_examples_validate(self):
        validate = compile_schema(Family.WORKER_POOL)
        for block in self._json_blocks(
            "## Worker Pool Specification Using JSON Documents",
            "## Variable Substitutions in Worker Pool Properties",
        ):
            validate(block)

    def test_the_readme_resource_examples_validate(self):
        validate = compile_schema(Family.RESOURCES)
        lines = (REPO / "README.md").read_text().splitlines()
        count, failures = 0, []
        for block in self._json_blocks(lines[0], "\x00"):
            items = block if isinstance(block, list) else [block]
            if not any(isinstance(i, dict) and "resource" in i for i in items):
                continue
            count += 1
            try:
                validate(block)
            except fastjsonschema.JsonSchemaException as e:
                failures.append(f"{json.dumps(block)[:80]}...: {e}")
        assert not failures, "\n".join(failures)
        assert count >= 19  # a floor against losing the extraction

    def test_the_node_action_examples_validate(self):
        validate = compile_schema(Family.NODE_ACTIONS)
        for name in ("node-actions-min.json", "node-actions-max.json"):
            validate(json.loads((REPO / "tests" / "spec_examples" / name).read_text()))
        count = 0
        for block in self._json_blocks(
            "## Node Actions", "## Worker Pool and Compute Commands"
        ):
            if isinstance(block, dict) and (
                "actions" in block or "actionGroups" in block
            ):
                validate(block)
                count += 1
        assert count


def test_the_generator_loads_no_command_machinery():
    """Building a schema needs no command line, configuration or client."""
    code = (
        "import sys\n"
        "import yellowdog_cli.utils.spec_schema, yellowdog_cli.utils.spec_properties,"
        " yellowdog_cli.utils.sdk_models\n"
        "banned = ['yellowdog_cli.utils.wrapper', 'yellowdog_cli.utils.args',"
        " 'yellowdog_cli.utils.printing', 'yellowdog_cli.create']\n"
        "print([m for m in banned if m in sys.modules])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"


def test_fastjsonschema_is_a_core_dependency():
    if sys.version_info >= (3, 11):
        import tomllib
    else:  # Python 3.10: tomli, which the CLI already depends on
        import tomli as tomllib

    project = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]
    assert any(re.match(r"fastjsonschema\b", d) for d in project["dependencies"])
