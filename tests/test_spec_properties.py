"""
utils/spec_properties.py against README.md: the Work Requirement dictionary's
rows, levels and descriptions are the registry's, and the shipped
descriptions.json is a fresh extraction. Needs no SDK call and no network.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

from yellowdog_cli.utils import spec_properties
from yellowdog_cli.utils.spec_properties import (
    WORK_REQUIREMENT_PROPERTIES,
    Level,
    load_descriptions,
    properties_at,
)

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"
DESCRIPTIONS = REPO / "yellowdog_cli" / "spec_data" / "descriptions.json"


def _dictionary_rows() -> dict[str, tuple[set[Level], str]]:
    """
    {property: (levels marked, description)} from the README's dictionary table.
    """
    lines = README.read_text().splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.startswith("| Property Name")
    )
    headings = [c.strip() for c in lines[start].strip().strip("|").split("|")]
    level_names = {level.value for level in Level}
    columns = {Level(h): headings.index(h) for h in headings if h in level_names}
    rows = {}
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        name = cells[0].strip("`")
        levels = {level for level, index in columns.items() if cells[index]}
        rows[name] = (levels, cells[1])
    return rows


class TestDictionaryAgreesWithRegistry:
    def test_every_row_is_a_registered_property_and_vice_versa(self):
        rows = _dictionary_rows()
        assert set(rows) == {p.name for p in WORK_REQUIREMENT_PROPERTIES}

    def test_levels_agree(self):
        rows = _dictionary_rows()
        for prop in WORK_REQUIREMENT_PROPERTIES:
            assert prop.levels == rows[prop.name][0], prop.name

    def test_no_row_is_duplicated(self):
        # Other README tables share names ('name', 'tag'): only the
        # dictionary's own rows are counted
        lines = README.read_text().splitlines()
        start = next(
            i for i, line in enumerate(lines) if line.startswith("| Property Name")
        )
        names = []
        for line in lines[start + 2 :]:
            if not line.startswith("|"):
                break
            names.append(line.strip().strip("|").split("|")[0].strip().strip("`"))
        assert len(names) == len(set(names)), "a property has two rows"

    def test_no_property_is_registered_twice(self):
        names = [p.name for p in WORK_REQUIREMENT_PROPERTIES]
        assert len(names) == len(set(names))


class TestDescriptions:
    def test_the_shipped_file_is_a_fresh_extraction(self):
        fresh = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "extract_schema_descriptions.py")],
            capture_output=True,
            text=True,
            check=True,
            cwd=REPO,
        ).stdout
        assert json.loads(fresh) == json.loads(DESCRIPTIONS.read_text()), (
            "run `make schema_descriptions`"
        )

    def test_every_dictionary_property_has_a_description(self):
        descriptions = load_descriptions()
        for prop in WORK_REQUIREMENT_PROPERTIES:
            assert descriptions.get(prop.name), prop.name

    def test_descriptions_are_plain_text(self):
        # Markdown links and code spans are unwrapped for an editor's hover
        for text in load_descriptions().values():
            assert "](#" not in text and "**" not in text and "`" not in text

    def test_nested_and_shell_properties_carry_their_own(self):
        def walk(fragment):
            if isinstance(fragment, dict):
                for key, value in fragment.items():
                    if key in ("if", "then", "else"):
                        # A condition or a constraint on properties declared
                        # beside it, where their descriptions are
                        continue
                    if key == "properties":
                        for name, sub in value.items():
                            assert (
                                isinstance(sub, spec_properties.SdkRef)
                                or "description" in sub
                                or "$ref" in sub
                            ), name
                    walk(value)
            elif isinstance(fragment, (list, tuple)):
                for item in fragment:
                    walk(item)

        for prop in WORK_REQUIREMENT_PROPERTIES:
            assert isinstance(prop.schema, (dict, spec_properties.SdkRef)), prop.name
            walk(prop.schema)
        for shell in (
            spec_properties.WORKER_POOL_SHELL,
            spec_properties.COMPUTE_REQUIREMENT_SHELL,
            spec_properties.NODE_ACTION_SHELL,
            spec_properties.COMPUTE_SOURCE_SHELL,
            *spec_properties.RESOURCE_SHELL.values(),
        ):
            for prop in shell:
                assert prop.description, prop.name
                assert isinstance(prop.schema, (dict, spec_properties.SdkRef)), (
                    prop.name
                )
                walk(prop.schema)


class TestLevels:
    def test_properties_at_each_level(self):
        wr = {p.name for p in properties_at(Level.WORK_REQUIREMENT)}
        tg = {p.name for p in properties_at(Level.TASK_GROUP)}
        task = {p.name for p in properties_at(Level.TASK)}
        assert {"taskGroups", "taskGroupCount", "name", "tag"} <= wr
        assert "taskGroups" not in tg and {"tasks", "dependencies"} <= tg
        assert {"taskType", "timeout", "arguments"} <= task and "tasks" not in task
        assert "csvFiles" not in wr | tg | task  # TOML only

    def test_the_comment_column_agrees_with_the_fragments(self):
        # property_names.py's '# Type' comments stay as documentation and
        # must not contradict the registry
        source = (REPO / "yellowdog_cli" / "utils" / "property_names.py").read_text()
        comments = dict(
            re.findall(r'^[A-Z_0-9]+ = "([^"]+)"\s*#\s*(\w+)', source, flags=re.M)
        )
        kinds = {
            "String": "string",
            "Boolean": "boolean",
            "Bool": "boolean",
            "Integer": "integer",
            "Float": "number",
            "List": "array",
            "Dict": "object",
            "Dictionary": "object",
        }
        for prop in WORK_REQUIREMENT_PROPERTIES:
            expected = kinds.get(comments.get(prop.name, ""))
            if expected and isinstance(prop.schema, dict) and "type" in prop.schema:
                assert prop.schema["type"] == expected, prop.name


class TestDescriptionsStandAlone:
    """
    The descriptions ship as editor hover text, away from the table.
    """

    def test_no_description_points_elsewhere_in_the_table(self):
        for name, text in load_descriptions().items():
            assert not re.search(r"\b(above|below)\b", text, re.I), name

    def test_quotes_are_balanced(self):
        for name, text in load_descriptions().items():
            assert text.count('"') % 2 == 0, name


def _registered(name: str) -> spec_properties.Property:
    return next(p for p in WORK_REQUIREMENT_PROPERTIES if p.name == name)


class TestFragments:
    def test_task_template_is_its_own_closed_object(self):
        # submit.py builds the SDK's TaskTemplate from these, after reading
        # taskDataFile(s) into taskData; anything else raises at submit
        schema = _registered("taskTemplate").schema
        assert isinstance(schema, dict)
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert set(schema["properties"]) == {
            "taskType",
            "taskData",
            "taskDataFile",
            "taskDataFiles",
            "environment",
        }

    def test_tasks_and_task_groups_are_required(self):
        assert _registered("tasks").required
        assert _registered("taskGroups").required

    def test_a_group_role_names_its_role(self):
        roles = next(
            p for p in spec_properties.RESOURCE_SHELL["Group"] if p.name == "roles"
        )
        assert isinstance(roles.schema, dict)
        role = roles.schema["items"]["properties"]["role"]
        assert role["anyOf"] == [{"required": ["id"]}, {"required": ["name"]}]

    def test_users_are_identified_by_one_of_their_keys(self):
        assert spec_properties.ONE_OF_REQUIRED == {
            "InternalUser": ("name", "username", "id"),
            "ExternalUser": ("name", "id"),
        }
        for resource, keys in spec_properties.ONE_OF_REQUIRED.items():
            shell = {p.name for p in spec_properties.RESOURCE_SHELL[resource]}
            assert set(keys) <= shell, resource


class TestTaskTypeLevels:
    def test_task_type_is_accepted_at_every_level(self):
        # submit.py turns a Work Requirement or Task Group 'taskType' into a
        # single-entry 'taskTypes'
        assert _registered("taskType").levels == frozenset(Level)
