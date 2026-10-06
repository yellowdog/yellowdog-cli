"""
Helper utilities for YDIDs.
"""

import re
from enum import Enum

# YDID scheme and type-token constants
YDID = "ydid"

TYPE_ALLOW = "allow"
TYPE_APP = "app"
TYPE_COMPREQ = "compreq"
TYPE_COMPSRC = "compsrc"
TYPE_CRT = "crt"
TYPE_CST = "cst"
TYPE_GROUP = "group"
TYPE_IMAGE = "image"
TYPE_IMGFAM = "imgfam"
TYPE_IMGGRP = "imggrp"
TYPE_KEYRING = "keyring"
TYPE_NODE = "node"
TYPE_ROLE = "role"
TYPE_TASK = "task"
TYPE_TASKGRP = "taskgrp"
TYPE_USER = "user"
TYPE_WORKREQ = "workreq"
TYPE_WRKR = "wrkr"
TYPE_WRKRPOOL = "wrkrpool"


class YDIDType(Enum):
    ALLOWANCE = "Allowance"
    APPLICATION = "Application"
    COMPUTE_REQUIREMENT = "Compute Requirement"
    COMPUTE_REQUIREMENT_TEMPLATE = "Compute Requirement Template"
    COMPUTE_SOURCE = "Compute Source"
    COMPUTE_SOURCE_TEMPLATE = "Compute Source Template"
    GROUP = "Group"
    IMAGE = "Machine Image"
    IMAGE_FAMILY = "Machine Image Family"
    IMAGE_GROUP = "Machine Image Group"
    KEYRING = "Keyring"
    NODE = "Node"
    ROLE = "Role"
    TASK = "Task"
    TASK_GROUP = "Task Group"
    USER = "User"
    WORKER = "Worker"
    WORKER_POOL = "Worker Pool"
    WORK_REQUIREMENT = "Work Requirement"


# The YellowDog IDs 'yd-remove --ids' removes (a Worker Pool's is shut down);
# tests/test_remove.py holds each one to a removal in resource_removal.py's
# _removable_by_id()
REMOVABLE_YDID_TYPES = frozenset(
    {
        YDIDType.ALLOWANCE,
        YDIDType.APPLICATION,
        YDIDType.COMPUTE_REQUIREMENT_TEMPLATE,
        YDIDType.COMPUTE_SOURCE_TEMPLATE,
        YDIDType.GROUP,
        YDIDType.IMAGE,
        YDIDType.IMAGE_FAMILY,
        YDIDType.IMAGE_GROUP,
        YDIDType.KEYRING,
        YDIDType.WORKER_POOL,
    }
)


def get_ydid_type(ydid: str | None) -> YDIDType | None:
    """
    Validate and find the type of a YellowDog ID.
    """
    if ydid is None or not is_valid_ydid(ydid):
        return None
    # A valid YDID's type token is one of _TYPE_TOKENS
    return _TYPE_TOKENS[ydid.split(":", 2)[1]]


def split_instance_specification(name_or_id: str) -> tuple[str, str] | None:
    """
    Split an Instance specification of the form 'cr_id.instance_id' into its
    Compute Requirement ID and its provider-assigned instance ID, or return
    None if the string is not an Instance specification.

    Only the first '.' is the separator: instance IDs can themselves contain
    dots (e.g. OCI's 'ocid1.instance.oc1.uk-london-1.anwgi...'), while a
    Compute Requirement YDID never does. The prefix must be a Compute
    Requirement YDID, otherwise a Compute Requirement *name* containing a '.'
    would be misclassified.
    """
    cr_id, separator, instance_id = name_or_id.partition(".")
    if (
        separator == ""
        or instance_id == ""
        or get_ydid_type(cr_id) != YDIDType.COMPUTE_REQUIREMENT
    ):
        return None
    return cr_id, instance_id


def work_requirement_id_of_task_group(task_group_id: str) -> str:
    """
    The ID of the Work Requirement a Task Group belongs to: a Task Group's
    YDID is its Work Requirement's, retyped, with the group's index appended.
    """
    return task_group_id.rsplit(":", 1)[0].replace(TYPE_TASKGRP, TYPE_WORKREQ, 1)


_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_HEX = r"[0-9a-fA-F]+"

# Pre-compiled pattern for highlighting YDIDs embedded in output text.
YDID_HIGHLIGHT_RE = re.compile(
    rf"(?P<ydid>{YDID}:[a-z]+:{_HEX}(?::{_HEX})?:{_UUID}(?::\d+)*)"
)

# Each YDID type token and the type it names: the only tokens a valid YDID
# can have, held to every YDIDType by tests/test_ydid_utils.py
_TYPE_TOKENS: dict[str, YDIDType] = {
    TYPE_WORKREQ: YDIDType.WORK_REQUIREMENT,
    TYPE_TASKGRP: YDIDType.TASK_GROUP,
    TYPE_TASK: YDIDType.TASK,
    TYPE_WRKRPOOL: YDIDType.WORKER_POOL,
    TYPE_WRKR: YDIDType.WORKER,
    TYPE_COMPREQ: YDIDType.COMPUTE_REQUIREMENT,
    TYPE_COMPSRC: YDIDType.COMPUTE_SOURCE,
    TYPE_NODE: YDIDType.NODE,
    TYPE_CRT: YDIDType.COMPUTE_REQUIREMENT_TEMPLATE,
    TYPE_CST: YDIDType.COMPUTE_SOURCE_TEMPLATE,
    TYPE_IMGFAM: YDIDType.IMAGE_FAMILY,
    TYPE_IMGGRP: YDIDType.IMAGE_GROUP,
    TYPE_IMAGE: YDIDType.IMAGE,
    TYPE_KEYRING: YDIDType.KEYRING,
    TYPE_ALLOW: YDIDType.ALLOWANCE,
    TYPE_APP: YDIDType.APPLICATION,
    TYPE_USER: YDIDType.USER,
    TYPE_GROUP: YDIDType.GROUP,
    TYPE_ROLE: YDIDType.ROLE,
}
_YDID_RE = re.compile(
    rf"^{YDID}:(?:{'|'.join(_TYPE_TOKENS)}):{_HEX}(?::{_HEX})?:{_UUID}(?::\d+)*$"
)


def is_valid_ydid(ydid: str | None) -> bool:
    """
    Return True if the YDID is well-formed.
    """
    if ydid is None:
        return False
    return bool(_YDID_RE.match(ydid))
