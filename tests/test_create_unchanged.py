"""
'yd resource create' leaves an existing resource that 'yd resource plan'
finds unchanged as it is: not updated, not asked about, and reported and
recorded as 'unchanged'; '--force-update' updates it anyway. Run against
the fake Platform (resource_plan_platform.py), whose mutating methods fail
the test unless one is let through for a resource expected to be written.
"""

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from requests import Response
from requests.exceptions import HTTPError
from yellowdog_client.model import ApiKey, Application

import yellowdog_cli.utils.results as results_module
from tests.resource_plan_platform import (  # noqa: F401 (the fixture)
    MUTATING_PREFIXES,
    FakePlatform,
    corpus_ctx,
    hold,
    platform,
)
from yellowdog_cli.utils import output_settings, resource_creation, resource_plan
from yellowdog_cli.utils.entity_names import (
    RN_APPLICATION,
    RN_REQUIREMENT_TEMPLATE,
    RN_SOURCE_TEMPLATE,
)
from yellowdog_cli.utils.exit_codes import ExitCode, ReportedFailure, classify
from yellowdog_cli.utils.load_resources import RESOURCE_SOURCE_DIR
from yellowdog_cli.utils.resource_creation import CreateOptions, create_resources

AWS_INSTANCES = "co.yellowdog.platform.model.AwsInstancesComputeSource"
STATIC = "co.yellowdog.platform.model.ComputeRequirementStaticTemplate"
AWS_CREDENTIAL = "co.yellowdog.platform.model.AwsCredential"


@pytest.fixture(autouse=True)
def _results() -> Iterator[None]:
    results_module.reset_results()
    yield
    results_module.reset_results()


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """
    The prompts the run asks, each answered yes.
    """
    prompts: list[str] = []

    def _confirmed(prompt: str) -> bool:
        prompts.append(prompt)
        return True

    monkeypatch.setattr(resource_creation, "confirmed", _confirmed)
    return prompts


def _allowed(mock: Any, returning: Any = None) -> Any:
    """
    Let one guarded mutator through, returning 'returning'.
    """
    mock.side_effect = None
    mock.return_value = returning
    return mock


def _source_template(**source: object) -> dict:
    return {
        "resource": "ComputeSourceTemplate",
        "namespace": "team-a",
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


def _requirement_template() -> dict:
    return {
        "resource": "ComputeRequirementTemplate",
        "type": STATIC,
        "name": "mixed",
        "namespace": "team-a",
        "strategyType": "co.yellowdog.platform.model.SplitProvisionStrategy",
        "sources": [{"sourceTemplateId": "team-a/aws-spot"}],
    }


def _create(platform: FakePlatform, *specifications: dict, **options: Any) -> None:
    create_resources(
        corpus_ctx(platform), list(specifications), CreateOptions(**options)
    )


def _records() -> list[dict]:
    return list(results_module._ITEMS)


def _mutations(platform: FakePlatform) -> list[str]:
    return [
        name
        for name, _, _ in platform.client.mock_calls
        if name.rsplit(".", 1)[-1].startswith(MUTATING_PREFIXES)
    ]


# ---------------------------------------------------------------------------
# Unchanged: skipped
# ---------------------------------------------------------------------------


def test_an_unchanged_source_template_is_not_updated_or_asked_about(
    platform, asked, capsys
):
    hold(platform, _source_template())
    held = platform.held[RN_SOURCE_TEMPLATE][0]
    _create(platform, _source_template())
    assert asked == []
    assert _mutations(platform) == []
    assert (
        f"Unchanged Compute Source Template 'team-a/aws-spot' ({held.id}): not updated"
        in " ".join(capsys.readouterr().out.split())
    )
    assert _records() == [
        {
            "resource": RN_SOURCE_TEMPLATE,
            "name": "team-a/aws-spot",
            "id": held.id,
            "action": "unchanged",
        }
    ]


def test_an_unchanged_resource_prints_its_id_under_quiet(
    platform, asked, monkeypatch, capsys
):
    # As a created or updated one does, so 'ID=$(yd resource create -q ...)'
    # captures it on a rerun too
    monkeypatch.setattr(output_settings.OUTPUT, "quiet", True)
    hold(platform, _source_template())
    held = platform.held[RN_SOURCE_TEMPLATE][0]
    _create(platform, _source_template())
    assert capsys.readouterr().out.split() == [held.id]


def test_an_unchanged_resource_without_an_id_prints_nothing_under_quiet(
    platform, asked, monkeypatch, capsys
):
    monkeypatch.setattr(output_settings.OUTPUT, "quiet", True)
    namespace = {"resource": "Namespace", "name": "team-a"}
    hold(platform, namespace)
    _create(platform, namespace)
    assert [r["action"] for r in _records()] == ["unchanged"]
    assert capsys.readouterr().out == ""


_GROUP = {"resource": "Group", "name": "renderers", "description": "Renderers"}

UNCHANGED_CASES: dict[str, list[dict]] = {
    "Keyring": [{"resource": "Keyring", "name": "aws-keyring", "description": "AWS"}],
    "Namespace": [{"resource": "Namespace", "name": "team-a"}],
    "NamespacePolicy": [
        {"resource": "NamespacePolicy", "namespace": "team-a", "autoscalingMaxNodes": 5}
    ],
    "StringAttributeDefinition": [
        {
            "resource": "StringAttributeDefinition",
            "name": "user.colour",
            "title": "Colour",
            "options": ["red", "blue"],
        }
    ],
    "NumericAttributeDefinition": [
        {
            "resource": "NumericAttributeDefinition",
            "name": "user.speed",
            "title": "Speed",
            "defaultRankOrder": "PREFER_HIGHER",
            "range": {"min": 1, "max": 10},
        }
    ],
    "Group": [_GROUP],
    "Application": [
        _GROUP,
        {
            "resource": "Application",
            "name": "render-app",
            "description": "Renders",
            "groups": ["renderers"],
        },
    ],
    "InternalUser": [
        _GROUP,
        {
            "resource": "InternalUser",
            "username": "render-user",
            "groups": ["renderers"],
        },
    ],
    "ExternalUser": [
        _GROUP,
        {
            "resource": "ExternalUser",
            "name": "render-partner",
            "groups": ["renderers"],
        },
    ],
    "MachineImageFamily": [
        {
            "resource": "MachineImageFamily",
            "namespace": "team-a",
            "name": "render-images",
            "osType": "LINUX",
            "imageGroups": [
                {
                    "name": "v1",
                    "osType": "LINUX",
                    "images": [
                        {
                            "name": "image-1",
                            "provider": "AWS",
                            "providerImageId": "ami-0123456789abcdef0",
                            "osType": "LINUX",
                            "regions": ["eu-west-2"],
                        }
                    ],
                }
            ],
        }
    ],
    "ComputeRequirementTemplate": [_source_template(), _requirement_template()],
}


@pytest.mark.parametrize("case", UNCHANGED_CASES, ids=str)
def test_each_type_unchanged_is_skipped(platform, asked, case):
    specifications = UNCHANGED_CASES[case]
    for specification in specifications:
        hold(platform, specification)
    _create(platform, *specifications)
    records = _records()
    assert [r["action"] for r in records] == ["unchanged"] * len(specifications), (
        records
    )
    assert records[-1]["resource"] == case
    assert asked == []
    assert _mutations(platform) == []


# ---------------------------------------------------------------------------
# Changed, forced, dry runs: the creator runs as it always has
# ---------------------------------------------------------------------------


def test_a_changed_template_is_updated_as_before(platform, asked):
    hold(platform, _source_template(limit=10))
    held = platform.held[RN_SOURCE_TEMPLATE][0]
    update = _allowed(
        platform.client.compute_client.update_compute_source_template, held
    )
    _create(platform, _source_template(limit=20))
    assert update.call_count == 1
    assert asked == ["Update existing Compute Source Template 'team-a/aws-spot'?"]
    assert [r["action"] for r in _records()] == ["updated"]


def test_instance_tags_dropped_from_a_template_are_sent_cleared(platform, asked):
    # An empty map is the Platform's default for instanceTags; a value is not
    hold(platform, _source_template())
    hold(platform, {**_requirement_template(), "instanceTags": {"team": "a"}})
    held = platform.held[RN_REQUIREMENT_TEMPLATE][0]
    update = _allowed(
        platform.client.compute_client.update_compute_requirement_template, held
    )
    _create(platform, _requirement_template())
    assert update.call_count == 1
    assert update.call_args.args[0].instanceTags is None
    assert [r["action"] for r in _records()] == ["updated"]


def test_instance_tags_held_empty_are_unchanged(platform, asked):
    hold(platform, _source_template())
    hold(platform, {**_requirement_template(), "instanceTags": {}})
    _create(platform, _requirement_template())
    assert _mutations(platform) == []
    assert [r["action"] for r in _records()] == ["unchanged"]


def test_force_update_updates_an_unchanged_resource(platform, asked, monkeypatch):
    hold(platform, _source_template())
    held = platform.held[RN_SOURCE_TEMPLATE][0]
    update = _allowed(
        platform.client.compute_client.update_compute_source_template, held
    )

    def _no_plan(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("planned under --force-update")

    monkeypatch.setattr(resource_plan, "plan_one", _no_plan)
    _create(platform, _source_template(), force_update=True)
    assert update.call_count == 1
    assert len(asked) == 1
    assert [r["action"] for r in _records()] == ["updated"]


def test_dry_run_plans_nothing(platform, asked, monkeypatch):
    hold(platform, _source_template())

    def _no_plan(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("planned in a dry run")

    monkeypatch.setattr(resource_plan, "plan_one", _no_plan)
    _create(
        platform,
        _source_template(),
        {"resource": "Keyring", "name": "aws-keyring", "description": "AWS"},
        dry_run=True,
    )
    assert asked == []
    assert _mutations(platform) == []


def test_credentials_allowances_and_configured_pools_are_always_sent(
    platform, asked, monkeypatch
):
    # And not planned, since their plan is never 'unchanged'
    planned: list[str] = []
    plan_one = resource_plan.plan_one

    def _spied(ctx: Any, resource_type: str, *args: Any) -> Any:
        planned.append(resource_type)
        return plan_one(ctx, resource_type, *args)

    keyring = {"resource": "Keyring", "name": "aws-keyring", "description": "AWS"}
    credential = {
        "resource": "Credential",
        "keyringName": "aws-keyring",
        "credential": {
            "type": AWS_CREDENTIAL,
            "name": "aws-credential",
            "accessKeyId": "AKIA-TEST-ID",
            "secretAccessKey": "AKIA-TEST-SECRET",
        },
    }
    pool = {
        "resource": "ConfiguredWorkerPool",
        "name": "on-premise",
        "namespace": "team-a",
        "properties": {},
    }
    allowance = {
        "resource": "Allowance",
        "type": "SourcesAllowance",
        "description": "monthly",
        "effectiveFrom": "Now",
        "resetType": "NONE",
        "limitEnforcement": "SOFT",
        "monitoredStatuses": ["RUNNING"],
        "allowedHours": 10,
    }
    for specification in (keyring, credential):
        hold(platform, specification)
    put = _allowed(platform.client.keyring_client.put_credential_by_name)
    add_pool = _allowed(
        platform.client.worker_pool_client.add_configured_worker_pool,
        SimpleNamespace(
            workerPool=SimpleNamespace(id="ydid:wrkrpool:000000:new"), token=None
        ),
    )
    add_allowance = _allowed(
        platform.client.allowances_client.add_allowance,
        SimpleNamespace(id="ydid:allow:000000:new"),
    )
    monkeypatch.setattr(resource_plan, "plan_one", _spied)
    _create(platform, keyring, credential, pool, allowance)
    assert planned == ["Keyring"]
    assert put.call_count == 1
    assert add_pool.call_count == 1
    assert add_allowance.call_count == 1
    assert [r["action"] for r in _records()] == [
        "unchanged",
        "created",
        "created",
        "created",
    ]


# ---------------------------------------------------------------------------
# A plan that fails
# ---------------------------------------------------------------------------


def test_a_planning_failure_falls_back_to_the_creator(platform, asked, capsys):
    # The plan and the creator both fail for want of a description: the
    # creator's failure is the one reported, once
    _create_failing = {"resource": "Keyring", "name": "aws-keyring"}
    with pytest.raises(ReportedFailure):
        _create(platform, _create_failing)
    err = " ".join(capsys.readouterr().err.split())
    assert err.count("Expected property 'description' to be defined") == 1
    assert [r["action"] for r in _records()] == ["failed"]


def test_a_plans_own_failure_is_not_shown_and_the_creator_runs(
    platform, asked, monkeypatch, capsys
):
    hold(platform, _source_template())
    held = platform.held[RN_SOURCE_TEMPLATE][0]
    update = _allowed(
        platform.client.compute_client.update_compute_source_template, held
    )

    def _failing_plan(*args: Any, **kwargs: Any) -> None:
        raise ValueError("the plan's own words")

    monkeypatch.setattr(resource_plan, "plan_one", _failing_plan)
    _create(platform, _source_template())
    shown = capsys.readouterr()
    assert "the plan's own words" not in shown.out + shown.err
    assert update.call_count == 1
    assert [r["action"] for r in _records()] == ["updated"]


def _unauthorised() -> HTTPError:
    response = Response()
    response.status_code = 401
    return HTTPError("401 Unauthorized", response=response)


def test_a_session_failure_while_planning_stops_the_run(platform, asked, monkeypatch):
    hold(platform, _source_template())

    def _failing_plan(*args: Any, **kwargs: Any) -> None:
        raise _unauthorised()

    monkeypatch.setattr(resource_plan, "plan_one", _failing_plan)
    keyring = {"resource": "Keyring", "name": "aws-keyring", "description": "AWS"}
    with pytest.raises(ReportedFailure) as raised:
        _create(platform, _source_template(), keyring)
    assert classify(raised.value) == ExitCode.AUTHENTICATION
    assert [r["action"] for r in _records()] == ["failed", "skipped"]
    assert asked == []
    assert _mutations(platform) == []


# ---------------------------------------------------------------------------
# The review's cases
# ---------------------------------------------------------------------------


def _hold_application(platform: FakePlatform) -> Application:
    return platform.holding(
        RN_APPLICATION,
        Application(
            name="render-app",
            createdByUserId="ydid:user:000000:creator",
            description="Renders",
        ),
    )


def test_an_application_with_keyrings_is_never_skipped(platform, asked):
    _hold_application(platform)
    specification = {
        "resource": "Application",
        "name": "render-app",
        "description": "Renders",
        "keyrings": ["aws-keyring"],
    }
    with pytest.raises(ReportedFailure):
        _create(platform, specification)
    records = _records()
    assert [r["action"] for r in records] == ["failed"]
    assert "--regenerate-app-keys" in records[0]["error"]


def test_an_application_with_regenerated_keys_is_never_skipped(platform, asked):
    held = _hold_application(platform)
    update = _allowed(platform.client.account_client.update_application, held)
    regenerate = _allowed(
        platform.client.account_client.regenerate_application_api_key,
        ApiKey(id="a-key-id", secret="a-key-secret"),
    )
    specification = {
        "resource": "Application",
        "name": "render-app",
        "description": "Renders",
    }
    _create(platform, specification, regenerate_app_keys=True)
    assert update.call_count == 1
    assert regenerate.call_count == 1
    assert [r["action"] for r in _records()] == ["updated"]


def test_a_changed_user_data_file_is_an_update(platform, asked, tmp_path):
    hold(platform, _source_template(userData="#!/bin/bash\necho old\n"))
    held = platform.held[RN_SOURCE_TEMPLATE][0]
    (tmp_path / "user-data.sh").write_text("#!/bin/bash\necho new\n", encoding="utf-8")
    update = _allowed(
        platform.client.compute_client.update_compute_source_template, held
    )
    specification = _source_template(userDataFile="user-data.sh")
    specification[RESOURCE_SOURCE_DIR] = str(tmp_path)
    _create(platform, specification)
    assert update.call_count == 1
    assert [r["action"] for r in _records()] == ["updated"]


def test_the_same_resource_twice_is_skipped_the_second_time(platform, asked):
    def _added(template: Any) -> Any:
        return platform.holding(RN_SOURCE_TEMPLATE, template)

    add = _allowed(platform.client.compute_client.add_compute_source_template)
    add.side_effect = _added
    _create(platform, _source_template(), _source_template())
    assert add.call_count == 1
    assert [r["action"] for r in _records()] == ["created", "unchanged"]
    assert asked == []


def test_an_attribute_definitions_dropped_description_is_written(
    platform, asked, monkeypatch
):
    specification = {
        "resource": "StringAttributeDefinition",
        "name": "user.colour",
        "title": "Colour",
        "description": "What colour it is",
    }
    hold(platform, specification)
    del specification["description"]
    sent: list[dict] = []

    def _post(**kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(ok=False, text="Attribute already exists")

    def _put(**kwargs: Any) -> SimpleNamespace:
        sent.append(kwargs["json"])
        return SimpleNamespace(ok=True, text="")

    monkeypatch.setattr(resource_creation, "post", _post)
    monkeypatch.setattr(resource_creation, "put", _put)
    _create(platform, specification)
    assert [payload["description"] for payload in sent] == [None]
    assert [r["action"] for r in _records()] == ["updated"]


# ---------------------------------------------------------------------------
# The summary
# ---------------------------------------------------------------------------


def _summaries(out: str) -> list[str]:
    """
    The summary lines in a run's output.
    """
    words = ("created", "updated", "unchanged", "skipped", "failed")
    # Each line less the timestamp print_info() puts before it
    messages = [line.split(" : ", 1)[-1].strip() for line in out.splitlines()]
    return [
        message
        for message in messages
        if message
        and all(
            part.split(" ", 1)[0].replace(",", "").isdigit()
            and part.split(" ", 1)[-1] in words
            for part in message.split(", ")
        )
    ]


def test_the_summary_counts_each_outcome(platform, asked, capsys):
    hold(platform, _source_template(name="aws-changed", limit=10))
    hold(platform, _source_template(name="aws-unchanged"))
    changed = platform.held[RN_SOURCE_TEMPLATE][0]
    _allowed(platform.client.compute_client.update_compute_source_template, changed)
    add = _allowed(platform.client.compute_client.add_compute_source_template)
    add.side_effect = lambda template: platform.holding(RN_SOURCE_TEMPLATE, template)
    _create(
        platform,
        _source_template(name="aws-new"),
        _source_template(name="aws-changed", limit=20),
        _source_template(name="aws-unchanged"),
    )
    assert _summaries(capsys.readouterr().out) == ["1 created, 1 updated, 1 unchanged"]


def test_a_declined_update_is_counted_skipped(platform, monkeypatch, capsys):
    monkeypatch.setattr(resource_creation, "confirmed", lambda prompt: False)
    hold(platform, _source_template(name="aws-changed", limit=10))
    hold(platform, _source_template(name="aws-unchanged"))
    _create(
        platform,
        _source_template(name="aws-changed", limit=20),
        _source_template(name="aws-unchanged"),
    )
    assert _summaries(capsys.readouterr().out) == ["1 unchanged, 1 skipped"]
    assert _mutations(platform) == []


def test_the_summary_counts_this_runs_records_only(platform, asked, capsys):
    results_module.record_resource("Keyring", "earlier", None, "created")
    hold(platform, _source_template())
    _create(platform, _source_template())
    assert _summaries(capsys.readouterr().out) == ["1 unchanged"]


def test_the_summary_is_printed_before_a_failure_is_raised(platform, asked, capsys):
    hold(platform, _source_template())
    with pytest.raises(ReportedFailure):
        _create(
            platform,
            _source_template(),
            {"resource": "Keyring", "name": "aws-keyring"},
        )
    assert _summaries(capsys.readouterr().out) == ["1 unchanged, 1 failed"]


def test_no_summary_under_json_or_dry_run(platform, asked, monkeypatch):
    shown: list[str] = []
    monkeypatch.setattr(
        resource_creation, "print_info", lambda message="", **_: shown.append(message)
    )
    hold(platform, _source_template())
    monkeypatch.setattr(output_settings.OUTPUT, "json_output", True)
    _create(platform, _source_template())
    monkeypatch.setattr(output_settings.OUTPUT, "json_output", False)
    _create(platform, _source_template(), dry_run=True)
    assert _summaries("\n".join(shown)) == []
    assert any(message.startswith("Unchanged") for message in shown)
