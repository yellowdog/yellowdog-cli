"""
Unit tests for yellowdog_cli.utils.ydid_utils
"""

import pytest

from yellowdog_cli.utils.ydid_utils import (
    TYPE_ALLOW,
    TYPE_APP,
    TYPE_COMPREQ,
    TYPE_COMPSRC,
    TYPE_CRT,
    TYPE_CST,
    TYPE_GROUP,
    TYPE_IMAGE,
    TYPE_IMGFAM,
    TYPE_IMGGRP,
    TYPE_KEYRING,
    TYPE_NODE,
    TYPE_ROLE,
    TYPE_TASK,
    TYPE_TASKGRP,
    TYPE_USER,
    TYPE_WORKREQ,
    TYPE_WRKR,
    TYPE_WRKRPOOL,
    YDID,
    YDIDType,
    get_ydid_type,
    split_instance_specification,
)

_UUID = "00000000-0000-0000-0000-000000000000"
_HEX = "abc123"


def _ydid(type_token: str) -> str:
    return f"{YDID}:{type_token}:{_HEX}:{_UUID}"


class TestGetYdidType:
    @pytest.mark.parametrize(
        "ydid, expected",
        [
            (_ydid(TYPE_WORKREQ), YDIDType.WORK_REQUIREMENT),
            (_ydid(TYPE_TASKGRP), YDIDType.TASK_GROUP),
            (_ydid(TYPE_TASK), YDIDType.TASK),
            (_ydid(TYPE_WRKRPOOL), YDIDType.WORKER_POOL),
            (_ydid(TYPE_WRKR), YDIDType.WORKER),
            (_ydid(TYPE_COMPREQ), YDIDType.COMPUTE_REQUIREMENT),
            (_ydid(TYPE_COMPSRC), YDIDType.COMPUTE_SOURCE),
            (_ydid(TYPE_NODE), YDIDType.NODE),
            (_ydid(TYPE_CRT), YDIDType.COMPUTE_REQUIREMENT_TEMPLATE),
            (_ydid(TYPE_CST), YDIDType.COMPUTE_SOURCE_TEMPLATE),
            (_ydid(TYPE_IMGFAM), YDIDType.IMAGE_FAMILY),
            (_ydid(TYPE_IMGGRP), YDIDType.IMAGE_GROUP),
            (_ydid(TYPE_IMAGE), YDIDType.IMAGE),
            (_ydid(TYPE_KEYRING), YDIDType.KEYRING),
            (_ydid(TYPE_ALLOW), YDIDType.ALLOWANCE),
            (_ydid(TYPE_APP), YDIDType.APPLICATION),
            (_ydid(TYPE_USER), YDIDType.USER),
            (_ydid(TYPE_GROUP), YDIDType.GROUP),
            (_ydid(TYPE_ROLE), YDIDType.ROLE),
        ],
    )
    def test_known_prefix_returns_correct_type(self, ydid, expected):
        assert get_ydid_type(ydid) == expected

    def test_none_returns_none(self):
        assert get_ydid_type(None) is None

    def test_empty_string_returns_none(self):
        assert get_ydid_type("") is None

    def test_no_ydid_prefix_returns_none(self):
        assert get_ydid_type("not-a-ydid") is None

    def test_ydid_prefix_only_unknown_type_returns_none(self):
        assert get_ydid_type(f"{YDID}:unknown:{_HEX}:{_UUID}") is None

    def test_ydid_prefix_with_no_type_returns_none(self):
        assert get_ydid_type(f"{YDID}:") is None

    def test_partial_prefix_not_matching_returns_none(self):
        # TYPE_TASK is a prefix of TYPE_TASKGRP — ensure no false match
        assert get_ydid_type(_ydid(TYPE_TASKGRP)) == YDIDType.TASK_GROUP
        assert get_ydid_type(_ydid(TYPE_TASK)) == YDIDType.TASK

    def test_enum_values_are_human_readable_strings(self):
        assert YDIDType.WORK_REQUIREMENT.value == "Work Requirement"
        assert YDIDType.TASK_GROUP.value == "Task Group"
        assert (
            YDIDType.COMPUTE_REQUIREMENT_TEMPLATE.value
            == "Compute Requirement Template"
        )


class TestSplitInstanceSpecification:
    CR_ID = _ydid(TYPE_COMPREQ)
    # OCI instance IDs (OCIDs) contain dots of their own
    OCID = (
        "ocid1.instance.oc1.uk-london-1."
        "anwgiljtbfkcyvycib2ubsewuwqqffx2jzyp7dolkhxanfvdsgvjzjrytepa"
    )

    @pytest.mark.parametrize(
        "instance_id",
        [
            "i-0123456789abcdef0",  # AWS
            OCID,  # OCI
            "my.dotted.instance.name",
        ],
    )
    def test_instance_id_may_contain_dots(self, instance_id):
        assert split_instance_specification(f"{self.CR_ID}.{instance_id}") == (
            self.CR_ID,
            instance_id,
        )

    def test_bare_compute_requirement_id_is_not_an_instance_specification(self):
        assert split_instance_specification(self.CR_ID) is None

    def test_trailing_dot_is_not_an_instance_specification(self):
        assert split_instance_specification(f"{self.CR_ID}.") is None

    @pytest.mark.parametrize("prefix", [_ydid(TYPE_NODE), "cr-name", ""])
    def test_non_compute_requirement_prefix_returns_none(self, prefix):
        assert split_instance_specification(f"{prefix}.i-0123456789abcdef0") is None

    def test_compute_requirement_name_containing_dots_returns_none(self):
        assert split_instance_specification("my.compute.requirement") is None
