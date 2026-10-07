"""
A resource specification lacking a property its creator or remover needs:
yd-create and yd-remove report and record it as that resource's failure,
naming the property ("Expected property 'name' to be defined"), change
nothing on the Platform, and exit 1. One case per resource type, each with a
specification holding nothing but its 'resource', so that every creator's and
remover's own lookup of its first required property is the one that fails.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from yellowdog_cli.utils import results
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    RN_ALLOWANCE,
    RN_APPLICATION,
    RN_CONFIGURED_POOL,
    RN_CREDENTIAL,
    RN_GROUP,
    RN_IMAGE_FAMILY,
    RN_KEYRING,
    RN_NAMESPACE,
    RN_NAMESPACE_POLICY,
    RN_NUMERIC_ATTRIBUTE_DEFINITION,
    RN_REQUIREMENT_TEMPLATE,
    RN_SOURCE_TEMPLATE,
    RN_STRING_ATTRIBUTE_DEFINITION,
)
from yellowdog_cli.utils.exit_codes import ExitCode, ReportedFailure, classify
from yellowdog_cli.utils.resource_creation import create_resources
from yellowdog_cli.utils.resource_removal import remove_resources

CREATABLE = [
    RN_SOURCE_TEMPLATE,
    RN_REQUIREMENT_TEMPLATE,
    RN_KEYRING,
    RN_CREDENTIAL,
    RN_IMAGE_FAMILY,
    RN_CONFIGURED_POOL,
    RN_ALLOWANCE,
    RN_STRING_ATTRIBUTE_DEFINITION,
    RN_NUMERIC_ATTRIBUTE_DEFINITION,
    RN_NAMESPACE_POLICY,
    RN_GROUP,
    RN_APPLICATION,
    RN_NAMESPACE,
]

REMOVABLE = [
    RN_SOURCE_TEMPLATE,
    RN_REQUIREMENT_TEMPLATE,
    RN_KEYRING,
    RN_CREDENTIAL,
    RN_IMAGE_FAMILY,
    RN_CONFIGURED_POOL,
    RN_STRING_ATTRIBUTE_DEFINITION,
    RN_NUMERIC_ATTRIBUTE_DEFINITION,
    RN_NAMESPACE_POLICY,
    RN_GROUP,
    RN_APPLICATION,
    RN_NAMESPACE,
]


@pytest.fixture
def platform(monkeypatch):
    """
    A client that records every call made of it, and the context of a
    command with no options set; the errors printed are returned with it.
    """
    from yellowdog_cli.utils import resource_processing

    errors: list[str] = []
    monkeypatch.setattr(resource_processing, "print_error", errors.append)
    results.reset_results()
    client = MagicMock()
    ctx = RunContext(
        args=SimpleNamespace(),  # type: ignore[arg-type]
        config=SimpleNamespace(namespace="ns", name_tag="tag", url="https://api.x"),  # type: ignore[arg-type]
        client=client,
    )
    yield SimpleNamespace(ctx=ctx, client=client, errors=errors)
    results.reset_results()


def _mutations(client: MagicMock) -> list[str]:
    """
    The calls made of the client that would change something: any but the
    lookups (get_*, search, list).
    """
    return [
        name
        for name, *_ in client.mock_calls
        if not any(
            part.startswith(("get_", "search", "list", "find"))
            for part in name.split(".")
        )
    ]


def _expect_missing_property(platform, raised, resource_type: str) -> None:
    assert classify(raised.value) == ExitCode.FAILURE
    records = [r for r in results._ITEMS if r.get("action") == "failed"]
    assert len(records) == 1, records
    assert records[0]["resource"] == resource_type
    assert records[0]["error"].startswith("Expected property '")
    assert records[0]["error"].endswith("' to be defined")
    assert len(platform.errors) >= 1
    assert "Expected property '" in platform.errors[0]
    assert _mutations(platform.client) == []


@pytest.mark.parametrize("resource_type", CREATABLE)
def test_creating_a_resource_missing_a_property_fails_it(platform, resource_type):
    with pytest.raises(ReportedFailure) as raised:
        create_resources(platform.ctx, [{"resource": resource_type}])
    _expect_missing_property(platform, raised, resource_type)


@pytest.mark.parametrize("resource_type", REMOVABLE)
def test_removing_a_resource_missing_a_property_fails_it(platform, resource_type):
    with pytest.raises(ReportedFailure) as raised:
        remove_resources(platform.ctx, [{"resource": resource_type}])
    _expect_missing_property(platform, raised, resource_type)


def test_an_image_family_with_an_unknown_os_type_fails_naming_the_valid_ones(
    platform,
):
    spec = {
        "resource": RN_IMAGE_FAMILY,
        "name": "f",
        "namespace": "ns",
        "osType": "BEOS",
    }
    with pytest.raises(ReportedFailure) as raised:
        create_resources(platform.ctx, [spec])
    assert classify(raised.value) == ExitCode.FAILURE
    [record] = [r for r in results._ITEMS if r.get("action") == "failed"]
    assert "'osType' has invalid value 'BEOS'" in record["error"]
    assert "LINUX" in record["error"]
    assert _mutations(platform.client) == []
