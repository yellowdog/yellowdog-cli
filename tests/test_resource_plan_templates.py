"""
'yd resource plan' for Compute Source and Compute Requirement Templates
(utils/resource_planners.py), against a fake Platform
(resource_plan_platform.py) on which any change fails the test.
"""

from copy import deepcopy
from json import loads as json_loads
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import yellowdog_cli.utils.results as results_module
import yellowdog_cli.utils.wrapper as wrapper_module
from tests.resource_plan_platform import (  # noqa: F401 (the fixture)
    PLAN_CHANGED_SOMETHING,
    FakePlatform,
    _clear_caches,
    platform,
)
from yellowdog_cli.utils import output_settings
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import RN_REQUIREMENT_TEMPLATE, RN_SOURCE_TEMPLATE
from yellowdog_cli.utils.exit_codes import NotFoundError, ReportedFailure
from yellowdog_cli.utils.resource_creation import (
    create_compute_requirement_template,
    create_compute_source_template,
    prepare_compute_requirement_template,
    prepare_compute_source_template,
)
from yellowdog_cli.utils.resource_plan import (
    Change,
    PlanOptions,
    ToBeCreated,
    plan_one,
    plan_resources,
)

AWS_INSTANCES = "co.yellowdog.platform.model.AwsInstancesComputeSource"
AWS_FLEET = "co.yellowdog.platform.model.AwsFleetComputeSource"
STATIC = "co.yellowdog.platform.model.ComputeRequirementStaticTemplate"
CST_ID = "ydid:cst:000000:11111111-1111-1111-1111-111111111111"


def _ctx(platform: FakePlatform) -> RunContext:
    return RunContext(SimpleNamespace(), wrapper_module.CONFIG_COMMON, platform.client)


def _source_template(namespace: str = "team-a", **source: object) -> dict:
    return {
        "namespace": namespace,
        "description": "Spot instances",
        "source": {
            "type": AWS_INSTANCES,
            "name": "aws-spot",
            "credential": "aws-keyring/aws-credential",
            "region": "eu-west-2",
            "securityGroupId": "sg-0123456789abcdef0",
            "instanceType": "t3.micro",
            "imageId": "ami-0123456789abcdef0",
            "limit": 10,
            **source,
        },
    }


def _requirement_template(source_template: str = "aws-spot", **extra: object) -> dict:
    return {
        "type": STATIC,
        "name": "mixed",
        "namespace": "team-a",
        "strategyType": "co.yellowdog.platform.model.SplitProvisionStrategy",
        "sources": [{"sourceTemplateId": source_template}],
        **extra,
    }


def _plan(platform: FakePlatform, resource_type: str, resource: dict, planned=None):
    return plan_one(_ctx(platform), resource_type, resource, None, planned or set())


def _hold_source_template(platform: FakePlatform, resource: dict):
    _, template = prepare_compute_source_template(_ctx(platform), resource, None)
    # As the Platform returns it: with what it assigns
    template.source.statusMessage = "Ready"
    template.source.id = "ydid:cs:000000:1"
    return platform.holding(RN_SOURCE_TEMPLATE, template)


# ---------------------------------------------------------------------------
# Compute Source Templates
# ---------------------------------------------------------------------------


def test_a_new_template_is_create(platform):
    entry = _plan(platform, RN_SOURCE_TEMPLATE, _source_template())
    assert (entry.action, entry.name, entry.id) == ("create", "team-a/aws-spot", None)
    assert entry.changes == ()


def test_the_same_template_is_unchanged(platform):
    held = _hold_source_template(platform, _source_template())
    entry = _plan(platform, RN_SOURCE_TEMPLATE, _source_template())
    assert (entry.action, entry.name, entry.id) == (
        "unchanged",
        "team-a/aws-spot",
        held.id,
    )
    assert entry.changes == ()


def test_one_changed_property_is_one_change(platform):
    _hold_source_template(platform, _source_template(limit=10))
    entry = _plan(platform, RN_SOURCE_TEMPLATE, _source_template(limit=20))
    assert entry.action == "update"
    assert entry.changes == (Change("source.limit", 10, 20, "changed"),)


def test_a_dropped_property_is_cleared(platform):
    _hold_source_template(platform, _source_template(subnetId="subnet-1"))
    entry = _plan(platform, RN_SOURCE_TEMPLATE, _source_template())
    assert entry.changes == (Change("source.subnetId", "subnet-1", None, "cleared"),)


def test_a_template_in_another_namespace_is_create(platform):
    _hold_source_template(platform, _source_template(namespace="team-b"))
    entry = _plan(platform, RN_SOURCE_TEMPLATE, _source_template())
    assert entry.action == "create"


def test_a_source_type_change_is_one_change(platform):
    _hold_source_template(platform, _source_template())
    fleet = _source_template()
    fleet["source"] = {
        "type": AWS_FLEET,
        "name": "aws-spot",
        "credential": "aws-keyring/aws-credential",
        "region": "eu-west-2",
        "securityGroupId": "sg-0123456789abcdef0",
        "instanceType": "t3.micro",
        "imageId": "ami-0123456789abcdef0",
        "purchaseOption": "SPOT_THEN_ON_DEMAND",
    }
    fleet["description"] = "Fleet"
    entry = _plan(platform, RN_SOURCE_TEMPLATE, fleet)
    assert entry.changes == (
        Change("source.type", AWS_INSTANCES, AWS_FLEET, "changed"),
        Change("description", "Spot instances", "Fleet", "changed"),
    )


def test_a_missing_property_fails_as_the_real_run_does(platform):
    with pytest.raises(ValueError, match="namespace"):
        _plan(platform, RN_SOURCE_TEMPLATE, {"source": _source_template()["source"]})


# ---------------------------------------------------------------------------
# Compute Requirement Templates
# ---------------------------------------------------------------------------


def _hold_requirement_template(platform: FakePlatform, resource: dict):
    _, template, _ = prepare_compute_requirement_template(
        _ctx(platform), resource, None
    )
    return platform.holding(RN_REQUIREMENT_TEMPLATE, template)


def test_a_new_requirement_template_is_create(platform):
    _hold_source_template(platform, _source_template())
    entry = _plan(platform, RN_REQUIREMENT_TEMPLATE, _requirement_template())
    assert (entry.action, entry.name) == ("create", "team-a/mixed")


def test_the_same_requirement_template_is_unchanged(platform):
    _hold_source_template(platform, _source_template())
    held = _hold_requirement_template(platform, _requirement_template())
    entry = _plan(platform, RN_REQUIREMENT_TEMPLATE, _requirement_template())
    assert (entry.action, entry.id, entry.changes) == ("unchanged", held.id, ())


def test_a_changed_requirement_template_names_the_change(platform):
    _hold_source_template(platform, _source_template())
    _hold_requirement_template(platform, _requirement_template(description="a"))
    entry = _plan(
        platform, RN_REQUIREMENT_TEMPLATE, _requirement_template(description="b")
    )
    assert entry.changes == (Change("description", "a", "b", "changed"),)


def test_instance_tags_held_empty_and_left_out_are_unchanged(platform):
    # The Platform sets an empty map when a template has none
    _hold_source_template(platform, _source_template())
    _hold_requirement_template(platform, _requirement_template(instanceTags={}))
    entry = _plan(platform, RN_REQUIREMENT_TEMPLATE, _requirement_template())
    assert (entry.action, entry.changes) == ("unchanged", ())


def test_instance_tags_held_with_a_value_and_left_out_are_cleared(platform):
    _hold_source_template(platform, _source_template())
    _hold_requirement_template(
        platform, _requirement_template(instanceTags={"team": "a"})
    )
    entry = _plan(platform, RN_REQUIREMENT_TEMPLATE, _requirement_template())
    assert entry.action == "update"
    assert entry.changes == (Change("instanceTags", {"team": "a"}, None, "cleared"),)


def test_a_source_template_name_is_resolved_to_its_id(platform):
    held = _hold_source_template(platform, _source_template())
    _, template, unresolved = prepare_compute_requirement_template(
        _ctx(platform), _requirement_template(), None, set()
    )
    assert template.sources[0].sourceTemplateId == held.id
    assert unresolved == []


def test_a_planned_source_template_is_left_unresolved(platform):
    planned = {(RN_SOURCE_TEMPLATE, "team-a/aws-spot")}
    _, template, unresolved = prepare_compute_requirement_template(
        _ctx(platform), _requirement_template(), None, planned
    )
    assert template.sources[0].sourceTemplateId == "aws-spot"
    assert unresolved == ["aws-spot"]


def test_a_planned_source_template_is_to_be_created_in_the_change(platform):
    _hold_source_template(platform, _source_template())
    _hold_requirement_template(platform, _requirement_template())
    planned = {(RN_SOURCE_TEMPLATE, "team-a/aws-spot-2")}
    entry = _plan(
        platform,
        RN_REQUIREMENT_TEMPLATE,
        _requirement_template("aws-spot-2"),
        planned,
    )
    assert entry.action == "update"
    (change,) = entry.changes
    assert change.path == "sources[0].sourceTemplateId"
    assert change.after == ToBeCreated("aws-spot-2")


def test_an_unknown_source_template_fails_the_requirement_template(platform):
    with pytest.raises(NotFoundError, match="aws-spot"):
        _plan(platform, RN_REQUIREMENT_TEMPLATE, _requirement_template())


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


@pytest.fixture
def configured():
    output_settings.configure_output(
        SimpleNamespace(json_output=False, no_format=True, quiet=False)
    )
    results_module.reset_results()
    yield
    results_module.reset_results()


def test_a_source_template_planned_earlier_is_to_be_created(
    platform, configured, capsys
):
    specifications = [
        {"resource": RN_SOURCE_TEMPLATE, **_source_template()},
        {"resource": RN_REQUIREMENT_TEMPLATE, **_requirement_template()},
    ]
    plan_resources(_ctx(platform), specifications, PlanOptions())
    out = capsys.readouterr().out
    assert "New        Compute Source Template 'team-a/aws-spot'" in out
    assert "New        Compute Requirement Template 'team-a/mixed'" in out
    assert "2 new" in out


def test_a_planned_source_template_shows_as_to_be_created(platform, configured, capsys):
    _hold_source_template(platform, _source_template())
    _hold_requirement_template(platform, _requirement_template())
    specifications = [
        {"resource": RN_SOURCE_TEMPLATE, **_source_template(name="aws-spot-2")},
        {"resource": RN_REQUIREMENT_TEMPLATE, **_requirement_template("aws-spot-2")},
    ]
    plan_resources(_ctx(platform), specifications, PlanOptions())
    out = capsys.readouterr().out
    assert "sources[0].sourceTemplateId: '" in out
    assert "→ 'aws-spot-2' (to be created)" in out


def test_the_plan_prints_no_name_resolution(platform, configured, capsys):
    _hold_source_template(platform, _source_template())
    _hold_requirement_template(platform, _requirement_template(description="a"))
    _clear_caches()  # So the plan's own lookups are made, not cached ones
    capsys.readouterr()
    specifications = [
        {"resource": RN_REQUIREMENT_TEMPLATE, **_requirement_template(description="b")}
    ]
    plan_resources(_ctx(platform), specifications, PlanOptions())
    out = capsys.readouterr().out
    assert "Changed    Compute Requirement Template 'team-a/mixed'" in out
    assert "-> ID" not in out
    assert "with ID" not in out


def test_an_unknown_source_template_fails_in_the_plan(platform, configured, capsys):
    specifications = [{"resource": RN_REQUIREMENT_TEMPLATE, **_requirement_template()}]
    with pytest.raises(ReportedFailure):
        plan_resources(_ctx(platform), specifications, PlanOptions())
    assert "1 failed" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The fake Platform
# ---------------------------------------------------------------------------


def test_the_fake_platform_refuses_a_change(platform):
    with pytest.raises(AssertionError, match=PLAN_CHANGED_SOMETHING):
        platform.client.compute_client.add_compute_source_template(object())
    with pytest.raises(AssertionError, match=PLAN_CHANGED_SOMETHING):
        platform.client.keyring_client.update_keyring("id", object())


def test_the_plan_changes_nothing(platform, configured):
    _hold_source_template(platform, _source_template(limit=1))
    _hold_requirement_template(platform, _requirement_template(description="a"))
    specifications = [
        {"resource": RN_SOURCE_TEMPLATE, **_source_template()},
        {"resource": RN_REQUIREMENT_TEMPLATE, **_requirement_template()},
    ]
    plan_resources(_ctx(platform), specifications, PlanOptions())


# ---------------------------------------------------------------------------
# The real run: preparing, then adding or updating, as before
# ---------------------------------------------------------------------------


def test_the_real_create_sends_what_the_plan_compares(platform, configured):
    _, planned = prepare_compute_source_template(
        _ctx(platform), _source_template(), None
    )
    add = MagicMock(return_value=SimpleNamespace(id=CST_ID))
    platform.client.compute_client.add_compute_source_template = add
    create_compute_source_template(_ctx(platform), _source_template())
    assert add.call_args.args[0] == planned


def test_the_real_update_sends_what_the_plan_compares(platform, configured):
    _hold_source_template(platform, _source_template())
    held = _hold_requirement_template(platform, _requirement_template())
    _, planned, _ = prepare_compute_requirement_template(
        _ctx(platform), _requirement_template(description="b"), None
    )
    update = MagicMock(return_value=SimpleNamespace(id=held.id))
    platform.client.compute_client.update_compute_requirement_template = update
    with output_settings.configured(
        SimpleNamespace(json_output=False, no_format=True, quiet=False, yes=True)
    ):
        create_compute_requirement_template(
            _ctx(platform), _requirement_template(description="b")
        )
    planned.id = held.id
    assert update.call_args.args[0] == planned


# ---------------------------------------------------------------------------
# A source added naming a Source Template to be created; the specifications
# ---------------------------------------------------------------------------


def _with_a_planned_second_source() -> list[dict]:
    second = _requirement_template()
    second["sources"].append({"sourceTemplateId": "aws-spot-2"})
    return [
        {"resource": RN_SOURCE_TEMPLATE, **_source_template(name="aws-spot-2")},
        {"resource": RN_REQUIREMENT_TEMPLATE, **second},
    ]


def test_a_source_added_naming_one_to_be_created_is_recorded(platform, capsys):
    _hold_source_template(platform, _source_template())
    _hold_requirement_template(platform, _requirement_template())
    output_settings.configure_output(
        SimpleNamespace(json_output=True, no_format=True, quiet=False)
    )
    results_module.reset_results()
    try:
        plan_resources(_ctx(platform), _with_a_planned_second_source(), PlanOptions())
        capsys.readouterr()
        results_module.flush_results()
        document = json_loads(capsys.readouterr().out)
    finally:
        results_module.reset_results()
    assert document[1]["action"] == "update"
    assert document[1]["changes"] == [
        {
            "path": "sources[1]",
            "from": None,
            "to": {"sourceTemplateId": "'aws-spot-2' (to be created)"},
        }
    ]


def test_a_source_added_naming_one_to_be_created_is_shown(platform, configured, capsys):
    _hold_source_template(platform, _source_template())
    _hold_requirement_template(platform, _requirement_template())
    plan_resources(_ctx(platform), _with_a_planned_second_source(), PlanOptions())
    assert (
        """sources[1]: + {"sourceTemplateId":"'aws-spot-2' (to be created)"}"""
        in capsys.readouterr().out
    )


def test_a_failed_specification_keeps_its_name_and_the_list_is_unchanged(
    platform, configured, capsys
):
    failing = _source_template()
    del failing["source"]["instanceType"]
    specifications = [{"resource": RN_SOURCE_TEMPLATE, **failing}]
    before = deepcopy(specifications)
    with pytest.raises(ReportedFailure):
        plan_resources(_ctx(platform), specifications, PlanOptions())
    assert (
        "Failed to plan ComputeSourceTemplate 'team-a/aws-spot': Missing expected"
        " property 'instanceType'" in capsys.readouterr().err
    )
    assert specifications == before
