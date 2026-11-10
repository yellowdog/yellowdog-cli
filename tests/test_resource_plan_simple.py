"""
'yd resource plan' for Keyrings, Credentials, Namespaces, Namespace Policies
and Attribute Definitions (utils/resource_planners.py), against the fake
Platform (resource_plan_platform.py) on which any change fails the test.
"""

import logging
from copy import deepcopy
from json import loads as json_loads
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from yellowdog_client.model import Keyring, Namespace, NamespacePolicy

import yellowdog_cli.utils.results as results_module
import yellowdog_cli.utils.wrapper as wrapper_module
from tests.resource_plan_platform import (  # noqa: F401 (the fixture)
    FakePlatform,
    platform,
)
from yellowdog_cli.utils import output_settings
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    RN_CREDENTIAL,
    RN_KEYRING,
    RN_NAMESPACE,
    RN_NAMESPACE_POLICY,
    RN_NUMERIC_ATTRIBUTE_DEFINITION,
    RN_STRING_ATTRIBUTE_DEFINITION,
)
from yellowdog_cli.utils.entity_utils import clear_keyring_cache
from yellowdog_cli.utils.exit_codes import NotFoundError, ReportedFailure
from yellowdog_cli.utils.resource_creation import (
    create_credential,
    create_keyring,
    prepare_attribute_definition,
)
from yellowdog_cli.utils.resource_plan import (
    Change,
    PlanOptions,
    plan_one,
    plan_resources,
)

SECRET = "AKIA-TEST-SECRET"
AWS_CREDENTIAL = "co.yellowdog.platform.model.AwsCredential"
REASON = "its secrets can't be read back, so it would be replaced"


def _ctx(platform: FakePlatform) -> RunContext:
    return RunContext(SimpleNamespace(), wrapper_module.CONFIG_COMMON, platform.client)


def _plan(platform: FakePlatform, resource_type: str, resource: dict, planned=None):
    return plan_one(_ctx(platform), resource_type, resource, None, planned or set())


def _credential(name: str = "aws-credential", keyring: str = "aws-keyring") -> dict:
    return {
        "keyringName": keyring,
        "credential": {
            "type": AWS_CREDENTIAL,
            "name": name,
            "accessKeyId": "AKIA-TEST-ID",
            "secretAccessKey": SECRET,
        },
    }


def test_a_keyring_compares_its_description_alone(platform):
    spec = {"name": "aws-keyring", "description": "AWS"}
    entry = _plan(platform, RN_KEYRING, dict(spec))
    assert (entry.action, entry.name, entry.id) == ("create", "aws-keyring", None)

    clear_keyring_cache()  # the lookup above is cached
    held = platform.holding(RN_KEYRING, Keyring(name="aws-keyring", description="AWS"))
    entry = _plan(platform, RN_KEYRING, dict(spec))
    assert (entry.action, entry.id, entry.changes) == ("unchanged", held.id, ())

    entry = _plan(platform, RN_KEYRING, {**spec, "description": "AWS keys"})
    assert entry.action == "update"
    assert entry.changes == (Change("description", "AWS", "AWS keys", "changed"),)


def test_an_existing_credential_is_unknown_and_shows_nothing_of_it(platform, capsys):
    platform.holding(
        RN_KEYRING,
        Keyring(
            name="aws-keyring",
            description="AWS",
            credentials=[
                SimpleNamespace(name="aws-credential"),
            ],
        ),
    )
    entry = _plan(platform, RN_CREDENTIAL, _credential())
    assert (entry.action, entry.reason) == ("unknown", REASON)
    assert entry.changes == ()
    assert entry.name == "aws-credential"
    shown = capsys.readouterr()
    assert SECRET not in shown.out + shown.err + repr(entry)


def test_a_credential_missing_from_its_keyring_is_create(platform):
    platform.holding(
        RN_KEYRING,
        Keyring(name="aws-keyring", description="AWS", credentials=[]),
    )
    entry = _plan(platform, RN_CREDENTIAL, _credential())
    assert entry.action == "create"
    assert SECRET not in repr(entry)


def test_a_credential_for_a_keyring_planned_earlier_is_create(platform):
    entry = _plan(platform, RN_CREDENTIAL, _credential(), {(RN_KEYRING, "aws-keyring")})
    assert entry.action == "create"


def test_a_credential_for_no_keyring_fails(platform):
    with pytest.raises(NotFoundError, match="Keyring 'aws-keyring' not found"):
        _plan(platform, RN_CREDENTIAL, _credential())


def test_a_keyring_without_a_description_fails_as_the_real_run_does(platform):
    with pytest.raises(ValueError) as real:
        create_keyring(_ctx(platform), {"name": "aws-keyring"})
    with pytest.raises(ValueError) as planned:
        _plan(platform, RN_KEYRING, {"name": "aws-keyring"})
    assert str(planned.value) == str(real.value)
    assert "'description'" in str(planned.value)

    # Not a clean update clearing it, against one that exists
    platform.holding(RN_KEYRING, Keyring(name="aws-keyring", description="AWS"))
    with pytest.raises(ValueError, match="'description'"):
        _plan(platform, RN_KEYRING, {"name": "aws-keyring"})


def _without(key: str) -> dict:
    spec = _credential()
    del spec["credential"][key]
    return spec


def _bad_type() -> dict:
    spec = _credential()
    spec["credential"]["type"] = "co.yellowdog.platform.model.NoSuchCredential"
    return spec


BROKEN_CREDENTIALS = {
    "no type": (_without("type"), "'type'"),
    "a bad type": (_bad_type(), "Unknown type 'NoSuchCredential'"),
    "no secretAccessKey": (_without("secretAccessKey"), "'secretAccessKey'"),
}


@pytest.mark.parametrize("case", BROKEN_CREDENTIALS)
def test_a_credential_the_real_run_refuses_fails_with_its_error(platform, case, capsys):
    # Its Keyring held, so only the credential itself can fail
    platform.holding(
        RN_KEYRING, Keyring(name="aws-keyring", description="AWS", credentials=[])
    )
    spec, expected = BROKEN_CREDENTIALS[case]
    with pytest.raises(ValueError) as real:
        create_credential(_ctx(platform), deepcopy(spec))
    with pytest.raises(ValueError) as planned:
        _plan(platform, RN_CREDENTIAL, deepcopy(spec))
    assert str(planned.value) == str(real.value)
    assert expected in str(planned.value)
    shown = capsys.readouterr()
    assert SECRET not in shown.out + shown.err + str(planned.value)


@pytest.mark.parametrize("case", BROKEN_CREDENTIALS)
def test_a_refused_credential_is_failed_with_no_secret(platform, case, capsys, caplog):
    platform.holding(
        RN_KEYRING, Keyring(name="aws-keyring", description="AWS", credentials=[])
    )
    spec, expected = BROKEN_CREDENTIALS[case]
    caplog.set_level(logging.DEBUG)
    results_module.reset_results()
    try:
        with output_settings.configured(
            SimpleNamespace(json_output=True, no_format=True, quiet=False)
        ):
            with pytest.raises(ReportedFailure):
                plan_resources(
                    _ctx(platform),
                    [{"resource": RN_CREDENTIAL, **deepcopy(spec)}],
                    PlanOptions(json_output=True),
                )
            results_module.flush_results()
        shown = capsys.readouterr()
        (record,) = json_loads(shown.out)
        assert record["action"] == "failed"
        assert expected in record["error"]
        assert SECRET not in shown.out + shown.err + caplog.text
    finally:
        results_module.reset_results()


def test_a_credential_names_its_keyring(platform):
    entry = _plan(platform, RN_CREDENTIAL, _credential(), {(RN_KEYRING, "aws-keyring")})
    assert entry.keyring == "aws-keyring"


def test_namespace_and_policy(platform):
    entry = _plan(platform, RN_NAMESPACE, {"name": "team-a"})
    assert (entry.action, entry.name) == ("create", "team-a")
    platform.holding(
        RN_NAMESPACE,
        Namespace(id="ydid:ns:000000:1", namespace="team-a", deletable=True),
    )
    assert _plan(platform, RN_NAMESPACE, {"name": "team-a"}).action == "unchanged"

    spec = {"namespace": "team-a", "autoscalingMaxNodes": 10}
    entry = _plan(platform, RN_NAMESPACE_POLICY, dict(spec))
    assert (entry.action, entry.name) == ("create", "team-a")
    platform.holding(
        RN_NAMESPACE_POLICY, NamespacePolicy(namespace="team-a", autoscalingMaxNodes=10)
    )
    assert _plan(platform, RN_NAMESPACE_POLICY, dict(spec)).action == "unchanged"
    entry = _plan(platform, RN_NAMESPACE_POLICY, {**spec, "autoscalingMaxNodes": 20})
    assert entry.action == "update"
    assert entry.changes == (Change("autoscalingMaxNodes", 10, 20, "changed"),)


def _attribute(**extra) -> dict:
    return {"name": "region", "title": "Region", "options": ["a", "b"], **extra}


def _patch_get(monkeypatch, platform, definitions):
    get = MagicMock(
        return_value=SimpleNamespace(
            ok=True, status_code=200, json=lambda: definitions, text=""
        )
    )
    monkeypatch.setattr("yellowdog_cli.utils.resource_planners.get", get)
    return get


def test_an_attribute_definition_title_change(platform, monkeypatch):
    held = prepare_attribute_definition(
        _ctx(platform), _attribute(), RN_STRING_ATTRIBUTE_DEFINITION
    )
    get = _patch_get(monkeypatch, platform, [held, {"name": "other", "title": "O"}])
    entry = _plan(platform, RN_STRING_ATTRIBUTE_DEFINITION, _attribute(title="Area"))
    assert (entry.action, entry.name) == ("update", "region")
    assert entry.changes == (Change("title", "Region", "Area", "changed"),)
    assert get.call_args.kwargs["url"].endswith("/compute/attributes/user")

    assert (
        _plan(platform, RN_STRING_ATTRIBUTE_DEFINITION, _attribute()).action
        == "unchanged"
    )


def test_a_new_attribute_definition_is_create(platform, monkeypatch):
    _patch_get(monkeypatch, platform, [])
    entry = _plan(
        platform,
        RN_NUMERIC_ATTRIBUTE_DEFINITION,
        {"name": "speed", "title": "Speed", "defaultRankOrder": "DESC"},
    )
    assert (entry.action, entry.name) == ("create", "speed")


def test_what_the_platform_adds_to_an_attribute_definition_is_no_change(
    platform, monkeypatch
):
    held = prepare_attribute_definition(
        _ctx(platform), _attribute(), RN_STRING_ATTRIBUTE_DEFINITION
    )
    _patch_get(
        monkeypatch,
        platform,
        [{**held, "id": "ydid:attr:1", "createdTime": "2026-01-01T00:00:00Z"}],
    )
    entry = _plan(platform, RN_STRING_ATTRIBUTE_DEFINITION, _attribute())
    assert (entry.action, entry.changes) == ("unchanged", ())


# A user Attribute Definition as GET /compute/attributes/user lists it: a
# JSON list of definitions, each with its 'type', an unset description as ""
# and unset options as [] (live run ydst-2611091206-mxng)
_LISTED_DEFINITION = {
    "type": "co.yellowdog.platform.model.StringAttributeDefinition",
    "description": "",
    "name": "user.owner",
    "options": [],
    "title": "Owner of this Source Template",
}


def test_an_attribute_definition_as_the_platform_lists_it(platform, monkeypatch):
    _patch_get(monkeypatch, platform, [dict(_LISTED_DEFINITION)])
    spec = {"name": "user.owner", "title": "Owner of this Source Template"}
    entry = _plan(platform, RN_STRING_ATTRIBUTE_DEFINITION, dict(spec))
    assert (entry.action, entry.changes) == ("unchanged", ())

    entry = _plan(
        platform, RN_STRING_ATTRIBUTE_DEFINITION, {**spec, "options": ["team-a"]}
    )
    assert entry.action == "update"
    assert entry.changes == (Change("options[0]", None, "team-a", "added"),)


def test_a_property_the_specification_leaves_out_is_cleared(platform, monkeypatch):
    """
    'yd resource create' sends the property as null, so the plan must not
    find it unchanged.
    """
    held = prepare_attribute_definition(
        _ctx(platform),
        _attribute(description="Where it runs"),
        RN_STRING_ATTRIBUTE_DEFINITION,
    )
    _patch_get(monkeypatch, platform, [held])
    entry = _plan(platform, RN_STRING_ATTRIBUTE_DEFINITION, _attribute())
    assert entry.action == "update"
    assert entry.changes == (Change("description", "Where it runs", None, "cleared"),)

    entry = _plan(
        platform,
        RN_STRING_ATTRIBUTE_DEFINITION,
        _attribute(description="Where it runs"),
    )
    assert (entry.action, entry.changes) == ("unchanged", ())


def test_a_numeric_definitions_dropped_units_and_range_are_cleared(
    platform, monkeypatch
):
    spec = {"name": "speed", "title": "Speed", "defaultRankOrder": "PREFER_HIGHER"}
    held = prepare_attribute_definition(
        _ctx(platform),
        {**spec, "units": "GHz", "range": {"min": 1, "max": 10}},
        RN_NUMERIC_ATTRIBUTE_DEFINITION,
    )
    _patch_get(monkeypatch, platform, [held])
    entry = _plan(platform, RN_NUMERIC_ATTRIBUTE_DEFINITION, dict(spec))
    assert entry.action == "update"
    assert sorted(entry.changes, key=lambda change: change.path) == [
        Change("range", {"min": 1, "max": 10}, None, "cleared"),
        Change("units", "GHz", None, "cleared"),
    ]


@pytest.mark.parametrize(
    "resource_type, resource",
    [
        (RN_KEYRING, {"description": "AWS"}),
        (RN_NAMESPACE, {}),
        (RN_NAMESPACE_POLICY, {"autoscalingMaxNodes": 1}),
        (RN_CREDENTIAL, {"keyringName": "k"}),
    ],
)
def test_a_missing_required_property_is_reported_by_name(
    platform, resource_type, resource
):
    with pytest.raises(ValueError, match=r"Expected property '.+' to be defined"):
        _plan(platform, resource_type, resource)
