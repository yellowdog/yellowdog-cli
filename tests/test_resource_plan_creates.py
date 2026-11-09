"""
'yd resource plan' for the two types the plan always shows as 'create':
Configured Worker Pools and Allowances (utils/resource_planners.py), against
the fake Platform (resource_plan_platform.py) on which any change fails the
test: an existing pool of the name said, an Allowance's template resolved
or "(to be created)", and the Allowances '--match-allowances-by-description'
replaces listed without a prompt.
"""

import io
import sys
from types import SimpleNamespace

import pytest
from yellowdog_client.model import WorkerPoolStatus, WorkerPoolSummary

import yellowdog_cli.utils.wrapper as wrapper_module
from tests.resource_plan_platform import (  # noqa: F401 (the fixture)
    FakePlatform,
    platform,
)
from yellowdog_cli.utils import resource_creation
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    RN_ALLOWANCE,
    RN_CONFIGURED_POOL,
    RN_SOURCE_TEMPLATE,
)
from yellowdog_cli.utils.exit_codes import ExitCode, NotFoundError, classify
from yellowdog_cli.utils.resource_creation import CreateOptions
from yellowdog_cli.utils.resource_plan import Change, plan_one
from yellowdog_cli.utils.resource_planners import CONFIGURED_POOL_EXISTS


def _ctx(platform: FakePlatform) -> RunContext:
    return RunContext(SimpleNamespace(), wrapper_module.CONFIG_COMMON, platform.client)


def _plan(platform, resource_type, resource, planned=None):
    return plan_one(_ctx(platform), resource_type, resource, None, planned or set())


def _allowance(**values) -> dict:
    return {
        "type": "SourcesAllowance",
        "description": "monthly",
        "effectiveFrom": "Now",
        "resetType": "NONE",
        "limitEnforcement": "SOFT",
        "monitoredStatuses": ["RUNNING"],
        "allowedHours": 10,
        **values,
    }


def _held_allowance(platform, description: str) -> SimpleNamespace:
    return platform.holding(RN_ALLOWANCE, SimpleNamespace(description=description))


# ---------------------------------------------------------------------------
# Configured Worker Pools
# ---------------------------------------------------------------------------


def test_a_configured_pool_is_always_create(platform):
    entry = _plan(platform, RN_CONFIGURED_POOL, {"name": "pool", "namespace": "ns"})
    assert (entry.action, entry.name, entry.id) == ("create", "ns/pool", None)
    assert entry.reason is None


def test_a_configured_pool_without_a_name_fails(platform):
    with pytest.raises(Exception, match="name"):
        _plan(platform, RN_CONFIGURED_POOL, {"namespace": "ns"})


def test_an_existing_pool_of_that_name_fails_as_the_platform_refuses_it(platform):
    """
    A shut-down pool holds its name too (live run ydst-2611091218-3ux5).
    """
    platform.holding(
        RN_CONFIGURED_POOL,
        WorkerPoolSummary(
            name="render", namespace="ns", status=WorkerPoolStatus.SHUTDOWN
        ),
    )
    with pytest.raises(ValueError) as raised:
        _plan(platform, RN_CONFIGURED_POOL, {"name": "render", "namespace": "ns"})
    assert str(raised.value) == CONFIGURED_POOL_EXISTS
    assert classify(raised.value) == ExitCode.FAILURE


def test_a_pool_whose_name_only_contains_it_is_no_match(platform):
    platform.holding(
        RN_CONFIGURED_POOL, WorkerPoolSummary(name="render-2", namespace="ns")
    )
    entry = _plan(platform, RN_CONFIGURED_POOL, {"name": "render", "namespace": "ns"})
    assert (entry.action, entry.reason) == ("create", None)


# ---------------------------------------------------------------------------
# Allowances
# ---------------------------------------------------------------------------


def test_an_allowance_is_create(platform):
    entry = _plan(platform, RN_ALLOWANCE, _allowance())
    assert (entry.action, entry.name, entry.id) == ("create", "monthly", None)
    assert entry.changes == ()


def test_an_allowance_with_dates_parses_them(platform):
    entry = _plan(platform, RN_ALLOWANCE, _allowance(effectiveFrom="2030-01-01"))
    assert entry.action == "create"


def test_an_allowance_for_a_template_not_found_fails(platform):
    with pytest.raises(NotFoundError):
        _plan(platform, RN_ALLOWANCE, _allowance(sourceCreatedFromId="missing"))


def test_an_allowance_for_a_template_planned_earlier(platform):
    entry = _plan(
        platform,
        RN_ALLOWANCE,
        _allowance(sourceCreatedFromId="tmpl"),
        {(RN_SOURCE_TEMPLATE, "tmpl")},
    )
    assert entry.action == "create"


def test_a_namespaced_planned_template_counts(platform, monkeypatch):
    ctx = _ctx(platform)
    monkeypatch.setattr(ctx.config, "namespace", "ns", raising=False)
    entry = plan_one(
        ctx,
        RN_ALLOWANCE,
        _allowance(sourceCreatedFromId="tmpl"),
        None,
        {(RN_SOURCE_TEMPLATE, "ns/tmpl")},
    )
    assert entry.action == "create"


def test_allowances_matched_by_description_are_listed_without_a_prompt(
    platform, monkeypatch
):
    old = _held_allowance(platform, "monthly")
    _held_allowance(platform, "monthly extra")  # a partial match: not replaced
    other = _held_allowance(platform, "monthly")
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("the plan prompted"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    with resource_creation.options_in_effect(
        CreateOptions(match_allowances_by_description=True)
    ):
        entry = _plan(platform, RN_ALLOWANCE, _allowance())
    assert entry.changes == (
        Change("replaces", old.id, None, "removed"),
        Change("replaces", other.id, None, "removed"),
    )


def test_allowances_are_not_listed_without_the_option(platform):
    _held_allowance(platform, "monthly")
    assert _plan(platform, RN_ALLOWANCE, _allowance()).changes == ()
