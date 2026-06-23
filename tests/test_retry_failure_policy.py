"""
Tests for the new RetryPolicy / FailurePolicy / TaskErrorSelector / Selection
builders in submit_utils.py, and the conflict-and-deprecation handling in
submit.py.
"""

from unittest.mock import patch

import pytest
from yellowdog_client.model import (
    FailurePolicy,
    ResubmissionDestination,
    RetryPolicy,
    Selection,
    TaskStatus,
)

import yellowdog_cli.submit as submit_module
from yellowdog_cli.utils.config_types import ConfigWorkRequirement
from yellowdog_cli.utils.submit_utils import (
    _generate_resubmission_destination,
    _generate_selection,
    _generate_task_error_selector,
    _to_int,
    _to_str,
    _to_task_status,
    generate_failure_policy,
    generate_retry_policy,
)


def _config(**kw) -> ConfigWorkRequirement:
    """Return a ConfigWorkRequirement with sensible defaults overridable by kw."""
    return ConfigWorkRequirement(**kw)


# ---------------------------------------------------------------------------
# _generate_selection
# ---------------------------------------------------------------------------


class TestGenerateSelection:
    def test_none_returns_none(self):
        assert _generate_selection(None, _to_str, field_name="x") is None

    def test_bare_list_rejected_with_guidance(self):
        with pytest.raises(ValueError, match="not a bare list"):
            _generate_selection(["a"], _to_str, field_name="x")  # type: ignore[arg-type]

    def test_non_dict_rejected(self):
        with pytest.raises(ValueError, match="must be a dict"):
            _generate_selection("hello", _to_str, field_name="x")  # type: ignore[arg-type]

    def test_unknown_key_rejected(self):
        with pytest.raises(ValueError, match=r"Unknown key\(s\)"):
            _generate_selection(
                {"includes": ["a"], "junk": []}, _to_str, field_name="x"
            )

    def test_empty_dict_rejected(self):
        with pytest.raises(ValueError, match="at least one of"):
            _generate_selection({}, _to_str, field_name="x")

    def test_includes_only(self):
        sel = _generate_selection({"includes": ["a", "b"]}, _to_str, field_name="x")
        assert sel == Selection(includes=["a", "b"], excludes=None)

    def test_excludes_only(self):
        sel = _generate_selection({"excludes": ["a"]}, _to_str, field_name="x")
        assert sel == Selection(includes=None, excludes=["a"])

    def test_both(self):
        sel = _generate_selection(
            {"includes": ["a"], "excludes": ["b"]}, _to_str, field_name="x"
        )
        assert sel == Selection(includes=["a"], excludes=["b"])

    def test_item_converter_applied(self):
        sel = _generate_selection({"includes": ["1", "2"]}, _to_int, field_name="x")
        assert sel == Selection(includes=[1, 2], excludes=None)


# ---------------------------------------------------------------------------
# _generate_task_error_selector
# ---------------------------------------------------------------------------


class TestGenerateTaskErrorSelector:
    def test_all_three_fields(self):
        sel = _generate_task_error_selector(
            {
                "errorTypes": {"includes": ["ALLOCATION_LOST"]},
                "statusesAtFailure": {"includes": ["FAILED"]},
                "processExitCodes": {"includes": [137, 143]},
            }
        )
        assert sel.errorTypes == Selection(includes=["ALLOCATION_LOST"], excludes=None)
        assert sel.statusesAtFailure == Selection(
            includes=[TaskStatus.FAILED], excludes=None
        )
        assert sel.processExitCodes == Selection(includes=[137, 143], excludes=None)

    def test_partial_fields(self):
        sel = _generate_task_error_selector({"processExitCodes": {"includes": [137]}})
        assert sel.errorTypes is None
        assert sel.statusesAtFailure is None
        assert sel.processExitCodes == Selection(includes=[137], excludes=None)

    def test_unknown_field_rejected(self):
        with pytest.raises(ValueError, match=r"Unknown key\(s\)"):
            _generate_task_error_selector({"junk": {"includes": [1]}})

    def test_invalid_status_rejected(self):
        with pytest.raises(ValueError):
            _to_task_status("NOT_A_STATUS")

    def test_non_string_in_error_types_rejected(self):
        with pytest.raises(ValueError, match="Expected a string"):
            _generate_task_error_selector({"errorTypes": {"includes": [123]}})

    def test_non_dict_rejected(self):
        with pytest.raises(ValueError, match="must be a dict"):
            _generate_task_error_selector("hello")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# generate_retry_policy
# ---------------------------------------------------------------------------


class TestGenerateRetryPolicy:
    def test_absent_returns_none(self):
        assert generate_retry_policy(_config(), {}, {}) is None

    def test_basic_max_retries_only(self):
        policy = generate_retry_policy(
            _config(), {}, {"retryPolicy": {"maxRetries": 3}}
        )
        assert policy == RetryPolicy(maxRetries=3, retryErrors=None)

    def test_with_retry_errors(self):
        policy = generate_retry_policy(
            _config(),
            {},
            {
                "retryPolicy": {
                    "maxRetries": 2,
                    "retryErrors": {
                        "includes": [{"processExitCodes": {"includes": [137]}}]
                    },
                }
            },
        )
        assert policy is not None
        assert policy.maxRetries == 2
        assert policy.retryErrors is not None
        assert policy.retryErrors.excludes is None
        includes = policy.retryErrors.includes
        assert includes is not None and len(includes) == 1
        assert includes[0].processExitCodes == Selection(includes=[137], excludes=None)

    def test_max_retries_required(self):
        with pytest.raises(ValueError, match="required"):
            generate_retry_policy(_config(), {}, {"retryPolicy": {}})

    def test_max_retries_negative_rejected(self):
        with pytest.raises(ValueError, match=">= 0"):
            generate_retry_policy(_config(), {}, {"retryPolicy": {"maxRetries": -1}})

    def test_unknown_key_rejected(self):
        with pytest.raises(ValueError, match=r"Unknown key\(s\)"):
            generate_retry_policy(
                _config(), {}, {"retryPolicy": {"maxRetries": 1, "junk": "x"}}
            )

    def test_tg_overrides_wr(self):
        policy = generate_retry_policy(
            _config(),
            {"retryPolicy": {"maxRetries": 1}},
            {"retryPolicy": {"maxRetries": 5}},
        )
        assert policy is not None
        assert policy.maxRetries == 5

    def test_wr_overrides_config(self):
        policy = generate_retry_policy(
            _config(retry_policy={"maxRetries": 1}),
            {"retryPolicy": {"maxRetries": 5}},
            {},
        )
        assert policy is not None
        assert policy.maxRetries == 5

    def test_config_used_when_nothing_else(self):
        policy = generate_retry_policy(_config(retry_policy={"maxRetries": 7}), {}, {})
        assert policy is not None
        assert policy.maxRetries == 7


# ---------------------------------------------------------------------------
# generate_failure_policy
# ---------------------------------------------------------------------------


class TestGenerateFailurePolicy:
    def test_absent_returns_none(self):
        assert generate_failure_policy(_config(), {}, {}) is None

    def test_basic(self):
        policy = generate_failure_policy(
            _config(),
            {},
            {
                "failurePolicy": {
                    "resubmissionDestinations": [
                        {"destinationTaskGroup": "tg-on-demand"}
                    ]
                }
            },
        )
        assert policy == FailurePolicy(
            resubmissionDestinations=[
                ResubmissionDestination(
                    destinationTaskGroup="tg-on-demand", resubmitErrors=None
                )
            ]
        )

    def test_destinations_order_preserved(self):
        policy = generate_failure_policy(
            _config(),
            {},
            {
                "failurePolicy": {
                    "resubmissionDestinations": [
                        {"destinationTaskGroup": "tg-a"},
                        {"destinationTaskGroup": "tg-b"},
                        {"destinationTaskGroup": "tg-c"},
                    ]
                }
            },
        )
        assert policy is not None
        assert [d.destinationTaskGroup for d in policy.resubmissionDestinations] == [
            "tg-a",
            "tg-b",
            "tg-c",
        ]

    def test_missing_destinations_rejected(self):
        with pytest.raises(ValueError, match="at least one entry"):
            generate_failure_policy(
                _config(), {}, {"failurePolicy": {"resubmissionDestinations": []}}
            )

    def test_destination_without_taskgroup_rejected(self):
        with pytest.raises(ValueError, match="destinationTaskGroup"):
            generate_failure_policy(
                _config(),
                {},
                {"failurePolicy": {"resubmissionDestinations": [{}]}},
            )

    def test_destination_with_unknown_key_rejected(self):
        with pytest.raises(ValueError, match=r"Unknown key\(s\)"):
            generate_failure_policy(
                _config(),
                {},
                {
                    "failurePolicy": {
                        "resubmissionDestinations": [
                            {"destinationTaskGroup": "x", "junk": "y"}
                        ]
                    }
                },
            )

    def test_with_resubmit_errors(self):
        policy = generate_failure_policy(
            _config(),
            {},
            {
                "failurePolicy": {
                    "resubmissionDestinations": [
                        {
                            "destinationTaskGroup": "tg-on-demand",
                            "resubmitErrors": {
                                "includes": [
                                    {"errorTypes": {"includes": ["ALLOCATION_LOST"]}}
                                ]
                            },
                        }
                    ]
                }
            },
        )
        assert policy is not None
        dest = policy.resubmissionDestinations[0]
        assert dest.destinationTaskGroup == "tg-on-demand"
        assert dest.resubmitErrors is not None
        includes = dest.resubmitErrors.includes
        assert includes is not None and len(includes) == 1
        assert includes[0].errorTypes == Selection(
            includes=["ALLOCATION_LOST"], excludes=None
        )


# ---------------------------------------------------------------------------
# Conflict detection between legacy and new mechanisms in create_task_group
# ---------------------------------------------------------------------------


class TestRetryConflictDetection:
    """
    The new retryPolicy/failurePolicy mechanism is mutually exclusive with the
    legacy maximumTaskRetries/retryableErrors fields on the same Task Group.
    """

    def _run_conflict_check(self, wr_data: dict, tg_data: dict, config_wr=None):
        """
        Replicate the conflict-detection logic in submit.py's create_task_group
        without invoking the full Task Group creation pipeline.
        """
        config_wr = config_wr or _config()
        retry_policy = generate_retry_policy(config_wr, wr_data, tg_data)
        failure_policy = generate_failure_policy(config_wr, wr_data, tg_data)

        legacy_retries_set = (
            tg_data.get("maximumTaskRetries") is not None
            or wr_data.get("maximumTaskRetries") is not None
            or config_wr.max_retries is not None
        )
        legacy_errors_set = (
            tg_data.get("retryableErrors") is not None
            or wr_data.get("retryableErrors") is not None
            or config_wr.retryable_errors is not None
        )
        legacy_in_use = legacy_retries_set or legacy_errors_set

        if (retry_policy is not None or failure_policy is not None) and legacy_in_use:
            raise ValueError("conflict")
        return retry_policy, failure_policy, legacy_in_use

    def test_new_alone_no_conflict(self):
        retry_policy, _, legacy = self._run_conflict_check(
            {}, {"retryPolicy": {"maxRetries": 3}}
        )
        assert retry_policy is not None
        assert legacy is False

    def test_legacy_alone_no_conflict(self):
        retry_policy, _, legacy = self._run_conflict_check(
            {}, {"maximumTaskRetries": 5}
        )
        assert retry_policy is None
        assert legacy is True

    def test_new_and_legacy_on_same_tg_conflicts(self):
        with pytest.raises(ValueError, match="conflict"):
            self._run_conflict_check(
                {},
                {"maximumTaskRetries": 5, "retryPolicy": {"maxRetries": 3}},
            )

    def test_legacy_on_wr_with_new_on_tg_conflicts(self):
        with pytest.raises(ValueError, match="conflict"):
            self._run_conflict_check(
                {"maximumTaskRetries": 5},
                {"retryPolicy": {"maxRetries": 3}},
            )

    def test_legacy_retryable_errors_with_new_conflicts(self):
        with pytest.raises(ValueError, match="conflict"):
            self._run_conflict_check(
                {},
                {
                    "retryableErrors": [{"errorTypes": ["TIMED_OUT"]}],
                    "retryPolicy": {"maxRetries": 1},
                },
            )

    def test_failure_policy_alone_with_legacy_retries_conflicts(self):
        with pytest.raises(ValueError, match="conflict"):
            self._run_conflict_check(
                {},
                {
                    "maximumTaskRetries": 5,
                    "failurePolicy": {
                        "resubmissionDestinations": [
                            {"destinationTaskGroup": "tg-on-demand"}
                        ]
                    },
                },
            )

    def test_config_level_legacy_with_new_at_tg_conflicts(self):
        with pytest.raises(ValueError, match="conflict"):
            self._run_conflict_check(
                {},
                {"retryPolicy": {"maxRetries": 1}},
                config_wr=_config(max_retries=2),
            )


# ---------------------------------------------------------------------------
# Deprecation warning fires once per invocation
# ---------------------------------------------------------------------------


class TestDeprecationWarning:
    def setup_method(self):
        # Reset the per-invocation flag so each test starts clean
        submit_module._LEGACY_RETRY_WARNED = False

    def test_warning_fires_first_time(self):
        with patch.object(submit_module, "print_warning") as mock:
            submit_module._warn_legacy_retry_mechanism_once()
        assert mock.call_count == 1
        assert "deprecated" in mock.call_args.args[0]

    def test_warning_does_not_fire_second_time(self):
        with patch.object(submit_module, "print_warning") as mock:
            submit_module._warn_legacy_retry_mechanism_once()
            submit_module._warn_legacy_retry_mechanism_once()
            submit_module._warn_legacy_retry_mechanism_once()
        assert mock.call_count == 1


# ---------------------------------------------------------------------------
# _generate_resubmission_destination
# ---------------------------------------------------------------------------


class TestGenerateResubmissionDestination:
    def test_non_dict_rejected(self):
        with pytest.raises(ValueError, match="must be a dict"):
            _generate_resubmission_destination("hello")  # type: ignore[arg-type]

    def test_empty_destination_rejected(self):
        with pytest.raises(ValueError, match="non-empty"):
            _generate_resubmission_destination({"destinationTaskGroup": ""})
