"""
The configuration file's schema: the registry held to config-template.toml,
the 'config' family, validate_config()'s wording, the warnings a command
prints as it starts, and the yd-doctor row.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import fastjsonschema
import pytest

from yellowdog_cli.utils import load_config
from yellowdog_cli.utils import property_names as pn
from yellowdog_cli.utils.settings import VARIABLE_NAME_PATTERN
from yellowdog_cli.utils.spec_properties import (
    ALL_CONFIG_SECTIONS,
    CONFIG_COMMON,
    CONFIG_SECTIONS,
    DATA_CLIENT_CONFIG_SECTIONS,
    Level,
    properties_at,
)

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib

from yellowdog_cli.utils.spec_schema import (
    Family,
    SchemaGenerationError,
    build_config_schema,
    build_schema,
    compile_config_schema,
    compile_schema,
)
from yellowdog_cli.utils.spec_validation import Violation, validate_config

TEMPLATE = Path(__file__).parent.parent / "config-template.toml"


def _template_keys() -> dict[str, set[str]]:
    """Each section's keys in the template, commented-out examples included."""
    keys: dict[str, set[str]] = {}
    section = None
    for line in TEMPLATE.read_text().splitlines():
        header = re.match(r"^\[(\w+)\]", line)
        if header:
            section = header.group(1)
            keys[section] = set()
            continue
        # Properties are indented four spaces; prose comments never match
        # 'name =' at that indent
        entry = re.match(r"^    #?\s*([A-Za-z][A-Za-z0-9]*)\s*=", line)
        if entry and section:
            keys[section].add(entry.group(1))
    return keys


def _names(section: str) -> set[str]:
    return {p.name for p in CONFIG_SECTIONS[section]}


class TestRegistry:
    def test_the_sections_are_property_names_own(self):
        assert set(CONFIG_SECTIONS) == {
            pn.COMMON_SECTION,
            pn.WORK_REQUIREMENT_SECTION,
            pn.DATA_CLIENT_SECTION,
            pn.WORKER_POOL_SECTION,
            pn.COMPUTE_REQUIREMENT_SECTION,
        }
        assert ALL_CONFIG_SECTIONS == frozenset(CONFIG_SECTIONS)
        assert DATA_CLIENT_CONFIG_SECTIONS == {"common", "dataClient"}

    @pytest.mark.parametrize("section", ["common", "dataClient", "workerPool"])
    def test_each_section_matches_the_template(self, section):
        names = _names(section)
        if section == "common":
            # [common.variables] is a sub-table header, not a 'key =' line
            names = names - {pn.VARIABLES}
        assert names == _template_keys()[section]

    def test_work_requirement_is_the_dictionarys_toml_level(self):
        # plus workerTag, which the loader reads there and no dictionary row has
        assert _names("workRequirement") == {
            p.name for p in properties_at(Level.TOML)
        } | {"workerTag"}
        assert _names("workRequirement") == _template_keys()["workRequirement"]

    def test_compute_requirement_is_a_synonym(self):
        assert CONFIG_SECTIONS["computeRequirement"] is CONFIG_SECTIONS["workerPool"]

    def test_every_config_property_has_a_description(self):
        for section in ("common", "dataClient", "workerPool"):
            for prop in CONFIG_SECTIONS[section]:
                assert prop.description, f"{section}.{prop.name}"

    def test_no_config_property_is_required(self):
        for props in CONFIG_SECTIONS.values():
            assert not any(p.required for p in props)

    def test_the_variable_name_pattern_is_settings_own(self):
        variables = next(p for p in CONFIG_COMMON if p.name == "variables")
        assert isinstance(variables.schema, dict)
        assert variables.schema["propertyNames"]["pattern"] == (
            f"^{VARIABLE_NAME_PATTERN}$"
        )


def _passes(document: dict, sections=ALL_CONFIG_SECTIONS) -> bool:
    try:
        compile_config_schema(frozenset(sections))(document)
        return True
    except fastjsonschema.JsonSchemaValueException:
        return False


class TestFamily:
    def test_the_family_builds_and_compiles(self):
        schema = build_schema(Family.CONFIG)
        assert set(schema["properties"]) == set(ALL_CONFIG_SECTIONS) | {"$schema"}
        assert schema["additionalProperties"] is False
        assert schema["title"] == "YellowDog CLI configuration file"
        compile_schema(Family.CONFIG)({})

    def test_a_subset_leaves_the_other_sections_alone(self):
        schema = build_config_schema(DATA_CLIENT_CONFIG_SECTIONS)
        assert set(schema["properties"]) == {"common", "dataClient", "$schema"}
        assert schema["additionalProperties"] is True
        assert _passes(
            {"workRequirement": {"taskCount": "many"}}, DATA_CLIENT_CONFIG_SECTIONS
        )

    def test_the_data_client_subset_needs_no_sdk_definitions(self):
        schema = build_config_schema(DATA_CLIENT_CONFIG_SECTIONS)
        assert set(schema["$defs"]) == {"variable"}

    def test_a_good_file_passes(self):
        assert _passes(
            {
                "common": {
                    "key": "k",
                    "namespace": "ns",
                    "usePAC": True,
                    "variables": {"a": 1, "b.c": [1, 2]},
                },
                "workRequirement": {"taskType": "bash", "taskCount": 3},
                "dataClient": {"remote": "r", "prod": {"bucket": "b"}},
                "workerPool": {"minNodes": 0, "instanceTags": {"a": "b"}},
                "computeRequirement": {"targetInstanceCount": 2},
            }
        )

    def test_the_templates_policy_examples_pass(self):
        text = TEMPLATE.read_text()
        section = text[text.index("[workRequirement]") : text.index("[dataClient]")]
        examples: list[str] = []
        taking = False
        for line in section.splitlines():
            if re.match(r"^    # (retryPolicy|failurePolicy) =", line):
                taking = True
            elif taking and not line.startswith("    #     ") and "]}" not in line:
                taking = False
            if taking:
                examples.append(line.replace("    # ", "", 1))
        document = tomllib.loads("\n".join(examples))
        assert set(document) == {"retryPolicy", "failurePolicy"}
        assert _passes({"workRequirement": document})

    @pytest.mark.parametrize(
        "document",
        [
            {"common": {"usePAC": "yes"}},
            {"workerPool": {"maxNodes": "ten"}},
            {"workRequirement": {"taskCount": "three"}},
            {"dataClient": {"prod": {"bucket": 3}}},
            {"common": {"variables": {"-bad": 1}}},
        ],
    )
    def test_a_wrong_type_fails(self, document):
        assert not _passes(document)

    @pytest.mark.parametrize(
        "section, key, value",
        [
            ("workerPool", "idleNodeTimeout", "5"),
            ("workerPool", "idleNodeTimeout", "2.5"),
            ("workerPool", "targetInstanceCount", "3"),
            ("workerPool", "minNodes", "1"),
        ],
    )
    def test_cast_properties_admit_numeric_strings(self, section, key, value):
        assert _passes({section: {key: value}})

    def test_a_non_numeric_string_is_still_refused_where_cast(self):
        assert not _passes({"workerPool": {"idleNodeTimeout": "soon"}})


def _check(document, sections=ALL_CONFIG_SECTIONS) -> list[Violation]:
    return validate_config(document, frozenset(sections))


class TestValidateConfig:
    def test_a_good_file_has_no_violations(self):
        assert _check({"common": {"key": "k"}, "workerPool": {"minNodes": 1}}) == []

    def test_a_wrong_type_is_named_with_its_path(self):
        assert _check({"workerPool": {"maxNodes": "ten"}}) == [
            Violation("workerPool.maxNodes", "must be integer")
        ]

    def test_a_misplaced_key_says_so(self):
        assert _check({"workRequirement": {"minNodes": 1}}) == [
            Violation("workRequirement", "'minNodes' is not read in this section")
        ]

    def test_an_unknown_key_is_unknown(self):
        assert _check({"workerPool": {"noSuchThing": 1}}) == [
            Violation("workerPool", "unknown property 'noSuchThing'")
        ]

    def test_an_unknown_section_is_unknown(self):
        assert _check({"workPool": {}}) == [
            Violation("(document)", "unknown section 'workPool'")
        ]

    def test_the_schema_key_is_not_a_section(self):
        assert _check({"$schema": "x", "common": {}}) == []

    def test_every_violation_is_found(self):
        violations = _check(
            {
                "common": {"usePAC": "yes", "minNodes": 1},
                "workerPool": {"maxNodes": "ten"},
            }
        )
        assert set(violations) == {
            Violation("common", "'minNodes' is not read in this section"),
            Violation("common.usePAC", "must be boolean"),
            Violation("workerPool.maxNodes", "must be integer"),
        }

    def test_unresolved_variables_pass(self):
        assert (
            _check(
                {
                    "common": {"usePAC": "{{bool:pac}}", "namespace": "{{ns}}"},
                    "workerPool": {"minNodes": "{{num:n}}", "maxNodes": "{{::}}"},
                    "workRequirement": {"taskCount": "{{num:count}}"},
                }
            )
            == []
        )

    def test_only_the_named_sections_are_checked(self):
        document = {
            "dataClient": {"bucket": 3},
            "workRequirement": {"minNodes": 1, "taskCount": "x"},
        }
        assert _check(document, DATA_CLIENT_CONFIG_SECTIONS) == [
            Violation("dataClient.bucket", "must be string")
        ]

    def test_the_document_is_not_changed(self):
        document = {"workRequirement": {"minNodes": 1}}
        _check(document)
        assert document == {"workRequirement": {"minNodes": 1}}


class TestDataClientProfiles:
    def test_a_profile_with_the_sections_keys_passes(self):
        assert _check({"dataClient": {"remote": "r", "prod": {"bucket": "b"}}}) == []

    def test_a_misplaced_key_in_a_profile_names_the_profile(self):
        assert _check({"dataClient": {"prod": {"namespace": "x"}}}) == [
            Violation("dataClient.prod", "'namespace' is not read in this section")
        ]

    def test_a_wrong_type_in_a_profile(self):
        assert _check({"dataClient": {"prod": {"prefix": 7}}}) == [
            Violation("dataClient.prod.prefix", "must be string")
        ]


@pytest.fixture
def warnings(monkeypatch) -> list[str]:
    printed: list[str] = []
    monkeypatch.setattr(load_config, "print_warning", printed.append)
    monkeypatch.setattr(load_config, "CONFIG_FILE", "config.toml")
    return printed


class TestWarnOfConfigViolations:
    def test_each_violation_is_one_warning(self, monkeypatch, warnings):
        monkeypatch.setattr(
            load_config,
            "_CONFIG_AS_WRITTEN",
            {"workRequirement": {"minNodes": 1}, "workerPool": {"maxNodes": "x"}},
        )
        load_config.warn_of_config_violations(ALL_CONFIG_SECTIONS)
        assert warnings == [
            "'config.toml': workRequirement: 'minNodes' is not read in this"
            " section (see yd-schema config)",
            "'config.toml': workerPool.maxNodes: must be integer"
            " (see yd-schema config)",
        ]

    def test_no_file_no_warnings(self, monkeypatch, warnings):
        monkeypatch.setattr(load_config, "_CONFIG_AS_WRITTEN", None)
        load_config.warn_of_config_violations(ALL_CONFIG_SECTIONS)
        assert warnings == []

    def test_an_unbuildable_schema_is_one_warning(self, monkeypatch, warnings):
        def fail(document, sections):
            raise SchemaGenerationError("Thing.field: unknown annotation")

        monkeypatch.setattr(load_config, "validate_config", fail)
        monkeypatch.setattr(load_config, "_CONFIG_AS_WRITTEN", {"common": {}})
        load_config.warn_of_config_violations(ALL_CONFIG_SECTIONS)
        assert len(warnings) == 1
        assert "cannot check 'config.toml' against the config schema" in warnings[0]
        assert "Thing.field" in warnings[0] and "yd-schema config" in warnings[0]


def test_the_suite_sees_no_config_snapshot():
    # conftest's autouse fixture: the developer's own config.toml, loaded at
    # import, must not make wrapped commands run in-process warn
    assert load_config.config_as_written() is None


def _run(command: list[str], config: str, cwd) -> subprocess.CompletedProcess:
    (cwd / "config.toml").write_text(config)
    env = {k: v for k, v in os.environ.items() if not k.startswith("YD_")}
    env.update({"YD_KEY": "a-key", "YD_SECRET": "a-secret"})
    return subprocess.run(
        command, capture_output=True, text=True, env=env, cwd=cwd, timeout=120
    )


GOOD_COMMON = '[common]\nnamespace = "ns"\ntag = "tg"\n'
BAD_POOL = '[workerPool]\nmaxNodes = "ten"\n'


class TestAtCommandStart:
    def test_an_api_command_warns_of_every_section(self, tmp_path):
        result = _run(
            ["yd-variables", "--nf", "namespace"], GOOD_COMMON + BAD_POOL, tmp_path
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "workerPool.maxNodes: must be integer" in result.stdout

    def test_quiet_suppresses_the_warnings_and_the_json_parses(self, tmp_path):
        result = _run(
            ["yd-variables", "--quiet", "namespace"], GOOD_COMMON + BAD_POOL, tmp_path
        )
        assert result.returncode == 0, result.stdout + result.stderr
        json.loads(result.stdout)  # nothing ahead of the document
        assert "maxNodes" not in result.stdout

    def test_a_property_override_is_checked(self, tmp_path):
        result = _run(
            ["yd-variables", "--nf", "--property", "workerPool.nope=1", "namespace"],
            GOOD_COMMON,
            tmp_path,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "workerPool: unknown property 'nope'" in result.stdout

    def test_an_unknown_key_in_the_file_still_exits_3(self, tmp_path):
        result = _run(["yd-variables", "--nf"], GOOD_COMMON + "bogus = 1\n", tmp_path)
        assert result.returncode == 3

    def test_a_data_client_command_checks_only_its_sections(self, tmp_path):
        result = _run(
            ["yd-ls", "--nf"],
            # A misplaced key, not a wrong type: load_config_data_client()
            # runs at import and may exit on a value it cannot use, before
            # the wrapper has a chance to warn
            GOOD_COMMON
            + '[dataClient]\nremote = ":local:"\nnamespace = "x"\n'
            + BAD_POOL,
            tmp_path,
        )
        # yd-ls may fail on its own account; the warnings come first
        output = result.stdout + result.stderr
        assert "dataClient: 'namespace' is not read in this section" in output
        assert "workerPool" not in output

    def test_nothing_is_printed_at_import(self, tmp_path):
        (tmp_path / "config.toml").write_text(GOOD_COMMON + BAD_POOL)
        result = subprocess.run(
            [sys.executable, "-c", "import yellowdog_cli.utils.load_config"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            timeout=120,
            env={**os.environ, "YD_KEY": "k", "YD_SECRET": "s"},
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "maxNodes" not in result.stdout + result.stderr


class TestReviewFindings:
    def test_every_key_the_loaders_read_is_in_its_section(self):
        # The template parity above cannot see a key read but undocumented:
        # each '<x>_section.get(CONSTANT)' or '<x>_section[CONSTANT]' in
        # load_config.py must name a property of that section
        import ast

        tree = ast.parse(Path(load_config.__file__).read_text())
        sections = {
            "common_section": "common",
            "wr_section": "workRequirement",
            "wp_section": "workerPool",
        }
        read: dict[str, set[str]] = {name: set() for name in sections.values()}
        for node in ast.walk(tree):
            target = key = None
            if isinstance(node, ast.Subscript):
                target, key = node.value, node.slice
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("get", "pop")
                and node.args
            ):
                target, key = node.func.value, node.args[0]
            if (
                isinstance(target, ast.Name)
                and target.id in sections
                and isinstance(key, ast.Name)
                and hasattr(pn, key.id)
            ):
                read[sections[target.id]].add(getattr(pn, key.id))
        assert read["workRequirement"], "the scan found nothing: is it broken?"
        for section, names in read.items():
            assert names <= _names(section), (section, names - _names(section))

    def test_worker_tag_is_read_under_work_requirement(self):
        assert _check({"workRequirement": {"workerTag": "w"}}) == []

    @pytest.mark.parametrize(
        "key, value, message",
        [
            ("minNodes", "ten", "must be an integer"),
            ("minNodes", [2], "must be an integer"),
            ("idleNodeTimeout", "soon", "must be a number"),
            ("idleNodeTimeout", {}, "must be a number"),
        ],
    )
    def test_a_cast_property_says_what_it_must_be(self, key, value, message):
        assert _check({"workerPool": {key: value}}) == [
            Violation(f"workerPool.{key}", message)
        ]

    def test_a_null_override_unsets_without_a_warning(self, tmp_path):
        result = _run(
            [
                "yd-variables",
                "--nf",
                "--property",
                "workerPool.name=null",
                "--property",
                "workerPool.templateId=null",
                "namespace",
            ],
            GOOD_COMMON,
            tmp_path,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "see yd-schema config" not in result.stdout


class TestDeferredMinors:
    @pytest.mark.parametrize(
        "key, value",
        [
            # What int() accepts: a bool, a float (truncated), underscores
            ("minNodes", True),
            ("minNodes", 2.5),
            ("targetInstanceCount", "1_000"),
            ("workersPerNode", " +3 "),
            # What float() accepts besides: inf, nan, underscores, exponents
            ("idleNodeTimeout", "inf"),
            ("idleNodeTimeout", " -Infinity "),
            ("idlePoolTimeout", "NaN"),
            ("nodeBootTimeout", "1_0.5"),
            ("nodeBootTimeout", "1e3"),
            ("nodeBootTimeout", False),
        ],
    )
    def test_a_cast_property_takes_what_the_cast_takes(self, key, value):
        assert _check({"workerPool": {key: value}}) == []

    @pytest.mark.parametrize(
        "key, value, message",
        [
            ("minNodes", "1.5", "must be an integer"),  # int("1.5") fails
            ("minNodes", [1], "must be an integer"),
            ("idleNodeTimeout", "infinite", "must be a number"),
            ("idleNodeTimeout", {}, "must be a number"),
        ],
    )
    def test_what_the_cast_refuses_is_still_named(self, key, value, message):
        assert _check({"workerPool": {key: value}}) == [
            Violation(f"workerPool.{key}", message)
        ]

    def test_a_key_outside_every_section_says_so(self):
        assert _check({"minNodes": 1, "common": {}}) == [
            Violation("(document)", "'minNodes' is not in a section")
        ]

    def test_an_unexpected_failure_is_one_warning(self, monkeypatch, warnings):
        def fail(document, sections):
            raise RuntimeError("a bug in the check")

        monkeypatch.setattr(load_config, "validate_config", fail)
        monkeypatch.setattr(load_config, "_CONFIG_AS_WRITTEN", {"common": {}})
        monkeypatch.setattr(load_config.ARGS_PARSER.args, "debug", False, raising=False)
        load_config.warn_of_config_violations(ALL_CONFIG_SECTIONS)
        assert len(warnings) == 1
        assert "cannot check 'config.toml'" in warnings[0]
        assert "a bug in the check" in warnings[0]

    def test_an_unexpected_failure_is_raised_under_debug(self, monkeypatch, warnings):
        def fail(document, sections):
            raise RuntimeError("a bug in the check")

        monkeypatch.setattr(load_config, "validate_config", fail)
        monkeypatch.setattr(load_config, "_CONFIG_AS_WRITTEN", {"common": {}})
        monkeypatch.setattr(load_config.ARGS_PARSER.args, "debug", True, raising=False)
        with pytest.raises(RuntimeError):
            load_config.warn_of_config_violations(ALL_CONFIG_SECTIONS)

    def test_a_deprecated_key_in_the_file_still_exits_3(self, tmp_path):
        result = _run(
            ["yd-variables", "--nf"],
            GOOD_COMMON + "[workerPool]\nautoShutdown = true\n",
            tmp_path,
        )
        assert result.returncode == 3
        assert "no longer supported" in result.stdout + result.stderr
