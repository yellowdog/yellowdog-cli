"""
Unit tests for the Work Requirement lookups in utils/entity_utils.py:
find_work_requirement_by_name() and get_work_requirement_summary_by_name_or_id(),
shared by yd-cancel, yd-start, yd-hold, yd-finish, yd-abort and
yd-submit --add-to.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from requests import HTTPError, Response
from yellowdog_client.model import WorkRequirement, WorkRequirementStatus

from yellowdog_cli.utils import entity_utils
from yellowdog_cli.utils.entity_utils import (
    AmbiguousNameError,
    find_work_requirement_by_name,
    get_work_requirement_summary_by_name_or_id,
)
from yellowdog_cli.utils.exit_codes import NotFoundError

WR_A = "ydid:workreq:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
WR_B = "ydid:workreq:000000:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

RUNNING = WorkRequirementStatus.RUNNING
HELD = WorkRequirementStatus.HELD
COMPLETED = WorkRequirementStatus.COMPLETED


def _wr(id_: str, name: str, status=RUNNING, namespace: str = "ns") -> Any:
    return SimpleNamespace(id=id_, name=name, status=status, namespace=namespace)


@pytest.fixture
def searches(monkeypatch):
    """
    Stub the name search: 'searches.wrs' are what exists, and every search
    made is appended to 'searches.made'.
    """
    state = SimpleNamespace(wrs=[], made=[])

    def search(client, name=None, namespace=None, **kwargs):
        state.made.append({"name": name, "namespace": namespace, **kwargs})
        return [
            wr
            for wr in state.wrs
            if wr.namespace == namespace and (name is None or name in wr.name)
        ]

    monkeypatch.setattr(entity_utils, "get_filtered_work_requirement_summaries", search)
    return state


class TestFindByName:
    def test_searches_for_the_name_in_the_namespace(self, searches):
        searches.wrs = [_wr(WR_A, "wr-a")]
        found = find_work_requirement_by_name(MagicMock(), "wr-a", "ns", [RUNNING])
        assert found.id == WR_A
        assert searches.made == [{"name": "wr-a", "namespace": "ns"}]

    def test_a_namespace_prefix(self, searches):
        searches.wrs = [_wr(WR_A, "wr-a", namespace="other")]
        found = find_work_requirement_by_name(
            MagicMock(), "other/wr-a", "ns", [RUNNING]
        )
        assert found.id == WR_A

    def test_only_an_exact_name_matches(self, searches):
        searches.wrs = [_wr(WR_A, "wr-a-2")]
        with pytest.raises(NotFoundError, match="Cannot find Work Requirement"):
            find_work_requirement_by_name(MagicMock(), "wr-a", "ns", [RUNNING])

    def test_prefers_the_one_in_the_statuses_given(self, searches):
        searches.wrs = [_wr(WR_B, "wr-a", COMPLETED), _wr(WR_A, "wr-a", RUNNING)]
        found = find_work_requirement_by_name(MagicMock(), "wr-a", "ns", [RUNNING])
        assert found.id == WR_A

    def test_else_one_in_another_state_for_the_caller_to_report(self, searches):
        searches.wrs = [_wr(WR_B, "wr-a", COMPLETED)]
        found = find_work_requirement_by_name(MagicMock(), "wr-a", "ns", [RUNNING])
        assert found.id == WR_B

    def test_two_in_the_statuses_given_are_ambiguous(self, searches):
        searches.wrs = [_wr(WR_A, "wr-a", RUNNING), _wr(WR_B, "wr-a", HELD)]
        with pytest.raises(AmbiguousNameError, match="please supply the ID"):
            find_work_requirement_by_name(MagicMock(), "wr-a", "ns", [RUNNING, HELD])


class TestByNameOrId:
    def test_an_id_is_fetched_whatever_its_namespace(self, searches):
        client = MagicMock()
        work_requirement = WorkRequirement(namespace="elsewhere", name="wr-a")
        work_requirement.id = WR_A  # assigned by the Platform: not an argument
        work_requirement.status = RUNNING
        client.work_client.get_work_requirement_by_id.return_value = work_requirement
        found = get_work_requirement_summary_by_name_or_id(client, WR_A, "ns")
        assert (found.id, found.namespace, found.status) == (
            WR_A,
            "elsewhere",
            RUNNING,
        )
        assert searches.made == []

    def test_a_missing_id_is_none(self, searches):
        response = Response()
        response.status_code = 404
        client = MagicMock()
        client.work_client.get_work_requirement_by_id.side_effect = HTTPError(
            "404", response=response
        )
        assert get_work_requirement_summary_by_name_or_id(client, WR_A, "ns") is None

    def test_a_missing_name_is_none(self, searches):
        assert (
            get_work_requirement_summary_by_name_or_id(MagicMock(), "wr-a", "ns")
            is None
        )

    def test_a_reused_name_prefers_an_unfinished_one(self, searches):
        searches.wrs = [_wr(WR_B, "wr-a", COMPLETED), _wr(WR_A, "wr-a", HELD)]
        found = get_work_requirement_summary_by_name_or_id(MagicMock(), "wr-a", "ns")
        assert found is not None and found.id == WR_A
