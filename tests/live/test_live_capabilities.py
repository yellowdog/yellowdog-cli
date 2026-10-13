"""
The provider capability table, and 'perform', which holds a supported
action to success and an unsupported one to a clean refusal.
"""

from pathlib import Path

import pytest
from harness import capabilities
from harness.capabilities import ACTIONS, CAPABILITIES, PROVIDERS, Unsupported, perform
from harness.config import SCHEMA
from live_fake_yd import FakeYd, result

PROVIDERS_MODULE = Path(__file__).with_name("test_live_providers.py")


def test_every_provider_in_the_table_is_one_the_configuration_knows():
    assert (
        set(CAPABILITIES) == set(PROVIDERS) == set(SCHEMA) - {"platform", "run", "data"}
    )


def test_every_entry_is_an_action_the_chain_runs_with_a_reason():
    for provider, entries in CAPABILITIES.items():
        for action, entry in entries.items():
            assert action in ACTIONS, (provider, action)
            assert isinstance(entry, Unsupported) and entry.reason.strip(), (
                provider,
                action,
            )


def test_every_action_is_performed_by_the_provider_chain():
    source = PROVIDERS_MODULE.read_text(encoding="utf-8")
    for action in ACTIONS:
        assert f'"{action}"' in source, action


def test_a_supported_action_must_succeed():
    yd = FakeYd(lambda args: result(args, document=[{"outcome": "stopped"}]))
    assert perform(yd, "aws", "stop", "instance", "stop", "x", "--json") is True


def test_a_supported_action_with_a_failed_record_fails():
    yd = FakeYd(
        lambda args: result(args, document=[{"outcome": "failed", "error": "no"}])
    )
    with pytest.raises(AssertionError):
        perform(yd, "aws", "stop", "instance", "stop", "x", "--json")


@pytest.fixture
def stop_unsupported(monkeypatch):
    monkeypatch.setitem(
        CAPABILITIES, "aws", {"stop": Unsupported("cannot stop this instance")}
    )


def test_an_unsupported_action_must_be_refused_cleanly(stop_unsupported):
    refused = [
        {"outcome": "failed", "error": "Platform: cannot stop this instance type"}
    ]
    yd = FakeYd(lambda args: result(args, exit_code=1, document=refused))
    assert perform(yd, "aws", "stop", "instance", "stop", "x", "--json") is False
    assert capabilities.unsupported("aws", "stop").reason == "cannot stop this instance"


def test_an_unsupported_action_that_succeeds_fails(stop_unsupported):
    yd = FakeYd(lambda args: result(args, document=[{"outcome": "stopped"}]))
    with pytest.raises(AssertionError, match="update the capability table"):
        perform(yd, "aws", "stop", "instance", "stop", "x", "--json")


def test_an_unsupported_action_refused_for_another_reason_fails(stop_unsupported):
    refused = [{"outcome": "failed", "error": "quota exceeded"}]
    yd = FakeYd(lambda args: result(args, exit_code=1, document=refused))
    with pytest.raises(AssertionError, match="quota exceeded"):
        perform(yd, "aws", "stop", "instance", "stop", "x", "--json")


def test_a_supported_action_that_was_skipped_fails():
    # yd records an Instance in the wrong state as skipped, and exits 0
    skipped = [{"outcome": "skipped", "error": "Instance is STOPPING"}]
    yd = FakeYd(lambda args: result(args, document=skipped))
    with pytest.raises(AssertionError):
        perform(yd, "aws", "stop", "instance", "stop", "x", "--json")


def test_a_supported_action_that_recorded_nothing_fails():
    yd = FakeYd(lambda args: result(args, document=[]))
    with pytest.raises(AssertionError):
        perform(yd, "aws", "stop", "instance", "stop", "x", "--json")
