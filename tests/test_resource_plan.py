"""
utils/resource_plan.py, the engine of 'yd resource plan': an SDK model
reduced to what a specification can set, two such models compared property
by property, and each specification's outcome printed, recorded under
'--json' and counted, with '--fail-on-changes' applied after the plan.

The planners are stubs registered in PLANNERS: the per-type planners have
tests of their own.
"""

from datetime import datetime, timezone
from json import loads as json_loads
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from requests import HTTPError, Response
from yellowdog_client.model import (
    ComputeRequirementStaticTemplate,
    ImageAccess,
    ImageOsType,
    MachineImageFamily,
    MachineImageGroup,
)

import yellowdog_cli.resource_plan as resource_plan_command
import yellowdog_cli.utils.results as results_module
import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli.utils import output_settings
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.exit_codes import ExitCode, ReportedFailure, classify
from yellowdog_cli.utils.load_resources import RESOURCE_SOURCE_DIR
from yellowdog_cli.utils.resource_plan import (
    PLANNERS,
    PLATFORM_DEFAULTS,
    UNORDERED_LISTS,
    Change,
    PlanEntry,
    PlanOptions,
    comparable,
    differences,
    plan_one,
    plan_resources,
    resource_differences,
    shown_value,
)

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
CRT_ID = "ydid:crt:000000:11111111-1111-1111-1111-111111111111"


# ---------------------------------------------------------------------------
# comparable()
# ---------------------------------------------------------------------------


def test_only_settable_properties_are_compared():
    template = ComputeRequirementStaticTemplate(
        name="mixed", namespace="team-a", sources=[], strategyType="SPLIT"
    )
    template.id = CRT_ID
    shown = comparable(template)
    assert "id" not in shown
    assert shown["name"] == "mixed"
    assert shown["namespace"] == "team-a"


def test_server_assigned_properties_are_left_out_at_every_level():
    family = MachineImageFamily(
        namespace="team-a",
        name="fam",
        osType=ImageOsType.LINUX,
        access=ImageAccess.PRIVATE,
        imageGroups=[MachineImageGroup(name="g", osType=ImageOsType.LINUX)],
    )
    family.id = "ydid:imgfam:1"
    family.createdTime = NOW
    family.imageGroups[0].createdTime = NOW  # type: ignore[index]
    shown = comparable(family)
    assert "id" not in shown and "createdTime" not in shown
    assert shown["osType"] == "LINUX"  # an enum as its value
    assert shown["imageGroups"] == [{"name": "g", "osType": "LINUX"}]


def test_the_discriminator_is_kept():
    template = ComputeRequirementStaticTemplate(
        name="t", namespace="ns", strategyType="SPLIT", sources=[]
    )
    assert comparable(template)["type"] == template.type


def test_plain_values_dicts_and_datetimes():
    assert comparable({"a": ImageOsType.LINUX, "b": [NOW]}) == {
        "a": "LINUX",
        "b": [NOW.isoformat()],
    }
    assert comparable(None) is None


def test_an_enum_key_is_its_value():
    # A Worker Pool's 'nodeEvents' is keyed by NodeEvent as the SDK reads it;
    # as plain data it is keyed by name, so it can be written as JSON
    assert comparable({ImageOsType.LINUX: [ImageOsType.WINDOWS]}) == {
        "LINUX": ["WINDOWS"]
    }


def test_a_class_settable_properties_knows_nothing_of_keeps_all_its_fields():
    shown = comparable(SimpleNamespace(x=1))  # not a dataclass: kept as it is
    assert shown.x == 1

    from dataclasses import dataclass

    @dataclass
    class NotAnSdkModel:
        id: str
        value: int

    assert comparable(NotAnSdkModel("i", 3)) == {"value": 3}


# ---------------------------------------------------------------------------
# differences()
# ---------------------------------------------------------------------------


def test_a_changed_leaf():
    assert differences({"maximumInstanceCount": 10}, {"maximumInstanceCount": 20}) == [
        Change("maximumInstanceCount", 10, 20, "changed")
    ]


def test_nothing_changed():
    assert differences({"a": {"b": [1, 2]}}, {"a": {"b": [1, 2]}}) == []


def test_a_property_the_specification_drops_is_cleared():
    assert differences({"imagesId": "x"}, {}) == [
        Change("imagesId", "x", None, "cleared")
    ]
    assert differences({"imagesId": "x"}, {"imagesId": None}) == [
        Change("imagesId", "x", None, "cleared")
    ]


def test_a_property_the_specification_adds():
    assert differences({}, {"imagesId": "x"}) == [
        Change("imagesId", None, "x", "added")
    ]


def test_a_platform_default_is_not_cleared():
    assert (
        differences({"strategyType": "SPLIT"}, {}, defaults=frozenset({"strategyType"}))
        == []
    )


def test_a_platform_default_is_matched_with_list_indices_as_brackets():
    assert (
        differences(
            {"sources": [{"instanceType": "t3"}]},
            {"sources": [{}]},
            defaults=frozenset({"sources[].instanceType"}),
        )
        == []
    )


def test_nested_paths():
    assert differences(
        {"source": {"region": "eu"}, "sources": [{"t": "a"}]},
        {"source": {"region": "us"}, "sources": [{"t": "b"}]},
    ) == [
        Change("source.region", "eu", "us", "changed"),
        Change("sources[0].t", "a", "b", "changed"),
    ]


def test_lists_by_position():
    assert differences({"s": [1, 2]}, {"s": [2, 1]}) == [
        Change("s[0]", 1, 2, "changed"),
        Change("s[1]", 2, 1, "changed"),
    ]
    assert differences({"s": [1, 2]}, {"s": [1]}) == [
        Change("s[1]", 2, None, "removed")
    ]
    assert differences({"s": [1]}, {"s": [1, 3]}) == [Change("s[1]", None, 3, "added")]


def test_lists_by_name():
    assert differences(
        {"g": [{"name": "a"}, {"name": "b"}]},
        {"g": [{"name": "b"}]},
        by_name=frozenset({"g"}),
    ) == [Change("g", {"name": "a"}, None, "removed")]
    assert differences(
        {"g": [{"name": "b", "x": 1}]},
        {"g": [{"name": "c"}, {"name": "b", "x": 2}]},
        by_name=frozenset({"g"}),
    ) == [
        Change("g", None, {"name": "c"}, "added"),
        Change("g[name=b].x", 1, 2, "changed"),
    ]


def test_lists_by_name_two_levels_deep():
    before = {
        "imageGroups": [
            {"name": "g1", "images": [{"name": "i1", "id": "a"}, {"name": "i2"}]}
        ]
    }
    after = {
        "imageGroups": [
            {"name": "g1", "images": [{"name": "i3"}, {"name": "i1", "id": "b"}]}
        ]
    }
    assert differences(
        before,
        after,
        by_name=frozenset({"imageGroups", "imageGroups[].images"}),
    ) == [
        Change("imageGroups[name=g1].images", {"name": "i2"}, None, "removed"),
        Change("imageGroups[name=g1].images", None, {"name": "i3"}, "added"),
        Change("imageGroups[name=g1].images[name=i1].id", "a", "b", "changed"),
    ]


def test_an_unordered_list_compares_as_a_multiset():
    unordered = frozenset({"sources[].tags"})
    assert (
        differences(
            {"sources": [{"tags": ["a", "b", "a"]}]},
            {"sources": [{"tags": ["a", "a", "b"]}]},
            unordered=unordered,
        )
        == []
    )
    assert differences(
        {"sources": [{"tags": ["a", "b", "a"]}]},
        {"sources": [{"tags": ["a", "c"]}]},
        unordered=unordered,
    ) == [
        Change("sources[0].tags", "b", None, "removed"),
        Change("sources[0].tags", "a", None, "removed"),
        Change("sources[0].tags", None, "c", "added"),
    ]


def test_resource_differences_reads_the_type_tables(monkeypatch):
    monkeypatch.setitem(PLATFORM_DEFAULTS, "Thing", {"strategyType": "test"})
    monkeypatch.setitem(UNORDERED_LISTS, "Thing", {"tags": "test"})
    assert (
        resource_differences(
            "Thing", {"strategyType": "SPLIT", "tags": [1, 2]}, {"tags": [2, 1]}
        )
        == []
    )
    assert resource_differences("Other", {"strategyType": "SPLIT"}, {}) == [
        Change("strategyType", "SPLIT", None, "cleared")
    ]


def test_booleans_are_not_numbers():
    assert differences({"a": 1}, {"a": True}) == [Change("a", 1, True, "changed")]


# ---------------------------------------------------------------------------
# shown_value()
# ---------------------------------------------------------------------------


def test_user_data_is_summarised():
    assert shown_value("source.userData", "x" * 1204) == "1,204 characters"
    assert shown_value("userData", "x") == "1 character"


def test_a_long_string_is_cut():
    assert shown_value("description", "x" * 61) == "'" + "x" * 57 + "...'"
    assert shown_value("description", "x" * 60) == "'" + "x" * 60 + "'"


def test_a_string_change_is_single_quoted(monkeypatch, configured, capsys):
    configured()
    entry = PlanEntry(
        "ComputeRequirementTemplate",
        "team-a:mixed",
        None,
        "update",
        (Change("sources[1].instanceType", "t3.small", "t3.medium", "changed"),),
    )
    monkeypatch.setitem(PLANNERS, entry.resource_type, _planner(entry))
    plan_resources(_ctx(), [_spec(entry.resource_type, "m")], PlanOptions())
    assert (
        "           sources[1].instanceType: 't3.small' → 't3.medium'\n"
        in capsys.readouterr().out
    )


def test_other_values_are_compact_json():
    assert shown_value("a", {"b": [1, None]}) == '{"b":[1,null]}'
    assert shown_value("a", "t3.small") == "'t3.small'"


# ---------------------------------------------------------------------------
# plan_one() and plan_resources()
# ---------------------------------------------------------------------------


def _ctx() -> RunContext:
    return RunContext(
        wrapper_module.ARGS_PARSER, wrapper_module.CONFIG_COMMON, MagicMock()
    )


@pytest.fixture
def configured():
    """
    Configure the output for 'json_output', the text printed without
    colouring, and empty the results before and after.
    """

    def _configure(json_output: bool = False) -> None:
        output_settings.configure_output(
            SimpleNamespace(json_output=json_output, no_format=True, quiet=False)
        )

    results_module.reset_results()
    yield _configure
    results_module.reset_results()


def _planner(entry: PlanEntry | Exception):
    def _plan(ctx, resource, source_dir, planned):
        if isinstance(entry, Exception):
            raise entry
        return entry

    return _plan


def _http_error(status: int, text: str = "error") -> HTTPError:
    response = Response()
    response.status_code = status
    response._content = text.encode()
    return HTTPError(f"HTTP {status}", response=response)


def _spec(resource_type: str, name: str) -> dict:
    return {"resource": resource_type, "name": name}


UPDATE = PlanEntry(
    "ComputeRequirementTemplate",
    "team-a:mixed",
    CRT_ID,
    "update",
    (
        Change("maximumInstanceCount", 10, 20, "changed"),
        Change("imagesId", "ydid:imgfam:1", None, "cleared"),
        Change("source.userData", "x" * 1204, "x" * 1310, "changed"),
    ),
)
CREATE = PlanEntry("ComputeSourceTemplate", "team-a:aws-spot-eu", None, "create")
UNCHANGED = PlanEntry("Keyring", "cloud-credentials", "ydid:keyring:1", "unchanged")
UNKNOWN = PlanEntry(
    "Credential",
    "cloud-credentials/aws",
    None,
    "unknown",
    reason="its secrets can't be read back, so it would be replaced",
)


@pytest.fixture
def four_planners(monkeypatch):
    for entry in (CREATE, UPDATE, UNCHANGED, UNKNOWN):
        monkeypatch.setitem(PLANNERS, entry.resource_type, _planner(entry))
    return [
        _spec(e.resource_type, e.name or "")
        for e in (CREATE, UPDATE, UNCHANGED, UNKNOWN)
    ]


def test_an_unknown_resource_type_is_refused():
    with pytest.raises(ValueError, match="Unknown resource type 'Nope'"):
        plan_one(_ctx(), "Nope", {}, None, set())


def test_the_planner_is_given_the_source_directory_and_what_is_planned(
    monkeypatch, configured
):
    configured()
    seen: list = []

    def _plan(ctx, resource, source_dir, planned):
        seen.append((dict(resource), source_dir, set(planned)))
        return PlanEntry("Keyring", resource["name"], None, "create")

    monkeypatch.setitem(PLANNERS, "Keyring", _plan)
    plan_resources(
        _ctx(),
        [
            {"resource": "Keyring", "name": "a", RESOURCE_SOURCE_DIR: "/specs"},
            {"resource": "Keyring", "name": "b"},
        ],
        PlanOptions(),
    )
    assert seen == [
        ({"name": "a"}, "/specs", set()),
        ({"name": "b"}, None, {("Keyring", "a")}),
    ]


def test_the_text_plan(four_planners, configured, capsys):
    configured()
    plan_resources(_ctx(), four_planners, PlanOptions())
    lines = [
        line.split(" : ", 1)[-1] if " : " in line else line
        for line in capsys.readouterr().out.splitlines()
    ]
    assert lines == [
        "Plan for 4 resource specifications",
        "New        Compute Source Template 'team-a:aws-spot-eu'",
        f"Changed    Compute Requirement Template 'team-a:mixed' ({CRT_ID})",
        "           maximumInstanceCount: 10 → 20",
        "           imagesId: (cleared; was 'ydid:imgfam:1')",
        "           source.userData: changed (1,204 → 1,310 characters)",
        "Unchanged  Keyring 'cloud-credentials' (ydid:keyring:1)",
        "Unknown    Credential 'cloud-credentials/aws': its secrets can't be"
        " read back, so it would be replaced",
        "1 new, 1 changed, 1 unchanged, 1 unknown",
    ]


def test_added_and_removed_lines(monkeypatch, configured, capsys):
    configured()
    entry = PlanEntry(
        "Group",
        "renderers",
        None,
        "update",
        (
            Change("roles", None, "compute-viewer", "added"),
            Change("roles", "work-admin", None, "removed"),
        ),
    )
    monkeypatch.setitem(PLANNERS, "Group", _planner(entry))
    plan_resources(_ctx(), [_spec("Group", "renderers")], PlanOptions())
    out = capsys.readouterr().out
    assert "           roles: + 'compute-viewer'\n" in out
    assert "           roles: - 'work-admin'\n" in out
    assert out.rstrip().endswith("1 changed")


def test_nothing_to_change(monkeypatch, configured, capsys):
    configured()
    monkeypatch.setitem(PLANNERS, "Keyring", _planner(UNCHANGED))
    plan_resources(_ctx(), [_spec("Keyring", "k")], PlanOptions())
    out = capsys.readouterr().out
    assert "Plan for 1 resource specification" in out
    assert out.rstrip().endswith("1 unchanged")


def test_no_specifications_is_nothing_to_change(configured, capsys):
    configured()
    plan_resources(_ctx(), [], PlanOptions())
    assert capsys.readouterr().out.rstrip().endswith("Nothing to change")


def test_the_json_records(four_planners, configured, capsys):
    configured(json_output=True)
    plan_resources(_ctx(), four_planners, PlanOptions(json_output=True))
    results_module.flush_results()
    assert json_loads(capsys.readouterr().out) == [
        {
            "resource": "ComputeSourceTemplate",
            "name": "team-a:aws-spot-eu",
            "id": None,
            "action": "create",
        },
        {
            "resource": "ComputeRequirementTemplate",
            "name": "team-a:mixed",
            "id": CRT_ID,
            "action": "update",
            "changes": [
                {"path": "maximumInstanceCount", "from": 10, "to": 20},
                {"path": "imagesId", "from": "ydid:imgfam:1", "to": None},
                {
                    "path": "source.userData",
                    "from": "1,204 characters",
                    "to": "1,310 characters",
                },
            ],
        },
        {
            "resource": "Keyring",
            "name": "cloud-credentials",
            "id": "ydid:keyring:1",
            "action": "unchanged",
        },
        {
            "resource": "Credential",
            "name": "cloud-credentials/aws",
            "id": None,
            "action": "unknown",
            "reason": "its secrets can't be read back, so it would be replaced",
        },
    ]


@pytest.mark.parametrize("entry", [CREATE, UPDATE, UNKNOWN])
def test_fail_on_changes_exits_1_after_the_plan(entry, monkeypatch, configured, capsys):
    configured()
    monkeypatch.setitem(PLANNERS, entry.resource_type, _planner(entry))
    with pytest.raises(SystemExit) as raised:
        plan_resources(
            _ctx(),
            [_spec(entry.resource_type, entry.name or "")],
            PlanOptions(fail_on_changes=True),
        )
    assert raised.value.code == int(ExitCode.FAILURE)
    assert "Plan for 1 resource specification" in capsys.readouterr().out


def test_fail_on_changes_leaves_nothing_to_change_at_0(monkeypatch, configured, capsys):
    configured()
    monkeypatch.setitem(PLANNERS, "Keyring", _planner(UNCHANGED))
    plan_resources(_ctx(), [_spec("Keyring", "k")], PlanOptions(fail_on_changes=True))
    assert capsys.readouterr().out.rstrip().endswith("1 unchanged")


def test_a_failed_specification_leaves_the_rest_planned(
    monkeypatch, configured, capsys
):
    configured()
    monkeypatch.setitem(PLANNERS, "Group", _planner(ValueError("no such role")))
    monkeypatch.setitem(PLANNERS, "Keyring", _planner(CREATE))
    with pytest.raises(ReportedFailure) as raised:
        plan_resources(
            _ctx(),
            [_spec("Group", "g"), _spec("Keyring", "k")],
            PlanOptions(fail_on_changes=True),  # the failure's code wins
        )
    assert classify(raised.value) == ExitCode.FAILURE
    captured = capsys.readouterr()
    assert "Failed to plan Group 'g': no such role" in captured.err + captured.out
    assert "New        Compute Source Template" in captured.out
    assert captured.out.rstrip().endswith("1 new, 1 failed")


def test_a_create_records_the_allowances_it_replaces(monkeypatch, configured, capsys):
    configured(json_output=True)
    replacing = PlanEntry(
        "Allowance",
        "monthly",
        None,
        "create",
        (Change("replaces", "ydid:allow:1", None, "removed"),),
    )
    monkeypatch.setitem(PLANNERS, "Allowance", _planner(replacing))
    plan_resources(_ctx(), [_spec("Allowance", "a")], PlanOptions(json_output=True))
    results_module.flush_results()
    (record,) = json_loads(capsys.readouterr().out)
    assert record["action"] == "create"
    assert record["changes"] == [
        {"path": "replaces", "from": "ydid:allow:1", "to": None}
    ]


def test_a_failed_specification_is_recorded(monkeypatch, configured, capsys):
    configured(json_output=True)
    monkeypatch.setitem(PLANNERS, "Group", _planner(ValueError("no such role")))
    with pytest.raises(ReportedFailure):
        plan_resources(_ctx(), [_spec("Group", "g")], PlanOptions())
    results_module.flush_results()
    assert json_loads(capsys.readouterr().out) == [
        {
            "resource": "Group",
            "name": "g",
            "id": None,
            "action": "failed",
            "error": "no such role",
        }
    ]


def test_a_missing_read_permission_exits_5(monkeypatch, configured):
    configured()
    monkeypatch.setitem(
        PLANNERS,
        "Keyring",
        _planner(_http_error(403, "MissingPermissionException")),
    )
    with pytest.raises(ReportedFailure) as raised:
        plan_resources(_ctx(), [_spec("Keyring", "k")], PlanOptions())
    assert classify(raised.value) == ExitCode.PERMISSION


def test_a_session_failure_stops_the_plan(monkeypatch, configured, capsys):
    configured(json_output=True)
    calls: list[str] = []

    def _plan(ctx, resource, source_dir, planned):
        calls.append(resource["name"])
        raise _http_error(401, "Unauthorized")

    monkeypatch.setitem(PLANNERS, "Keyring", _plan)
    with pytest.raises(ReportedFailure) as raised:
        plan_resources(
            _ctx(), [_spec("Keyring", "a"), _spec("Keyring", "b")], PlanOptions()
        )
    assert classify(raised.value) == ExitCode.AUTHENTICATION
    assert calls == ["a"]
    results_module.flush_results()
    assert [r["action"] for r in json_loads(capsys.readouterr().out)] == [
        "failed",
        "skipped",
    ]


def test_fail_on_changes_under_json_still_prints_the_records(monkeypatch, capsys):
    """
    Through the command's wrapper: the exit is 1, and the document printed.
    """
    args = MagicMock(
        json_output=True,
        fail_on_changes=True,
        match_allowances_by_description=False,
        regenerate_app_keys=False,
        no_format=True,
        quiet=False,
        debug=False,
        dry_run=False,
        validate=False,
        jsonnet_dry_run=False,
        print_pid=False,
        output_file=None,
        count_only=False,
        ids_only=False,
        strip_ids=False,
        hide_user_data=False,
        events_as_json=False,
    )
    monkeypatch.setattr(wrapper_module, "ARGS_PARSER", args)
    monkeypatch.setattr(wrapper_module, "CLIENT", MagicMock())
    monkeypatch.setattr(
        wrapper_module, "CONFIG_COMMON", MagicMock(url="https://u", use_pac=False)
    )
    output_settings.configure_output(args)
    monkeypatch.setattr(
        resource_plan_command,
        "load_resource_specifications",
        lambda *a, **k: [_spec("Keyring", "k")],
    )
    monkeypatch.setitem(PLANNERS, "Keyring", _planner(CREATE))
    results_module.reset_results()
    try:
        with pytest.raises(SystemExit) as raised:
            resource_plan_command.main()
        assert raised.value.code == int(ExitCode.FAILURE)
        assert json_loads(capsys.readouterr().out) == [
            {
                "resource": "ComputeSourceTemplate",
                "name": "team-a:aws-spot-eu",
                "id": None,
                "action": "create",
            }
        ]
    finally:
        results_module.reset_results()


def test_a_credential_names_its_keyring(monkeypatch, configured, capsys):
    configured(json_output=True)
    entry = PlanEntry("Credential", "aws", None, "create", keyring="cloud-credentials")
    monkeypatch.setitem(PLANNERS, "Credential", _planner(entry))
    plan_resources(_ctx(), [_spec("Credential", "aws")], PlanOptions(json_output=True))
    results_module.flush_results()
    assert json_loads(capsys.readouterr().out) == [
        {
            "resource": "Credential",
            "name": "aws",
            "id": None,
            "action": "create",
            "keyring": "cloud-credentials",
        }
    ]

    configured()
    plan_resources(_ctx(), [_spec("Credential", "aws")], PlanOptions())
    assert (
        "New        Credential 'aws' in Keyring 'cloud-credentials'\n"
        in capsys.readouterr().out
    )
