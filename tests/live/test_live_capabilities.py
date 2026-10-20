"""
The provider capability table, and 'perform', which holds a supported
action to success and an unsupported one to a clean refusal.
"""

from pathlib import Path

import pytest
from harness import capabilities, coverage
from harness.capabilities import (
    ACTIONS,
    CAPABILITIES,
    PROVIDERS,
    KnownFault,
    KnownFaultWarning,
    Unsupported,
    perform,
)
from harness.config import SCHEMA
from harness.yd import Result
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
            if isinstance(entry, KnownFault):
                assert entry.issue.startswith("https://"), (provider, action)
                assert entry.symptom.strip() and entry.wait_seconds > 0
            else:
                assert isinstance(entry, Unsupported) and entry.reason.strip(), (
                    provider,
                    action,
                )


def test_gcps_resize_down_is_a_known_fault():
    fault = capabilities.known_fault("gcp", "resize-down")
    assert fault is not None
    assert fault.issue.endswith("/YEL-15298")
    assert capabilities.unsupported("gcp", "resize-down") is None


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


@pytest.fixture
def covered(tmp_path):
    coverage.configure(tmp_path)
    yield lambda: coverage.recorded(tmp_path)
    coverage.configure(None)


def test_a_clean_refusal_counts_for_the_coverage_gate(stop_unsupported, covered):
    refused = [{"outcome": "failed", "error": "cannot stop this instance type"}]
    yd = FakeYd(lambda args: result(args, exit_code=1, document=refused))
    perform(yd, "aws", "stop", "instance", "stop", "x", "--json")
    assert covered() == {"yd instance stop"}


def test_a_refusal_for_another_reason_does_not_count(stop_unsupported, covered):
    refused = [{"outcome": "failed", "error": "quota exceeded"}]
    yd = FakeYd(lambda args: result(args, exit_code=1, document=refused))
    with pytest.raises(AssertionError):
        perform(yd, "aws", "stop", "instance", "stop", "x", "--json")
    assert covered() == set()


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


@pytest.fixture
def stop_faulty(monkeypatch):
    monkeypatch.setitem(
        CAPABILITIES,
        "aws",
        {"stop": KnownFault("https://example.com/BUG-1", "1 of 0 running", 60)},
    )


def _failing(stderr: str):
    return lambda args: Result(tuple(args), 1, "[]", stderr)


def test_a_known_fault_showing_its_symptom_warns_naming_the_issue(stop_faulty):
    yd = FakeYd(_failing("ERROR : Timed out: 'x' 1 of 0 running"))
    with pytest.warns(KnownFaultWarning, match="BUG-1"):
        assert perform(yd, "aws", "stop", "instance", "stop", "x", "--json") is False


def test_a_known_fault_counts_for_the_coverage_gate(stop_faulty, covered):
    yd = FakeYd(_failing("ERROR : Timed out: 'x' 1 of 0 running"))
    with pytest.warns(KnownFaultWarning):
        perform(yd, "aws", "stop", "instance", "stop", "x", "--json")
    assert covered() == {"yd instance stop"}


def test_a_known_fault_that_no_longer_occurs_fails(stop_faulty):
    yd = FakeYd(lambda args: result(args, document=[{"outcome": "stopped"}]))
    with pytest.raises(AssertionError, match=r"BUG-1.*update the capability table"):
        perform(yd, "aws", "stop", "instance", "stop", "x", "--json")


def test_a_known_fault_failing_some_other_way_fails(stop_faulty):
    # The failure is described as 'yd' describes it (the real one adds its
    # output, masked)
    yd = FakeYd(_failing("ERROR : quota exceeded"))
    with pytest.raises(AssertionError, match="exited 1"):
        perform(yd, "aws", "stop", "instance", "stop", "x", "--json")
