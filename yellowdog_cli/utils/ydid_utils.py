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


def get_ydid_type(ydid: str | None) -> YDIDType | None:
    """
    Validate and find the type of a YellowDog ID.
    """
    if ydid is None or not is_valid_ydid(ydid):
        return None

    if ydid.startswith(f"{YDID}:{TYPE_WORKREQ}:"):
        return YDIDType.WORK_REQUIREMENT
    if ydid.startswith(f"{YDID}:{TYPE_TASKGRP}:"):
        return YDIDType.TASK_GROUP
    if ydid.startswith(f"{YDID}:{TYPE_TASK}:"):
        return YDIDType.TASK
    if ydid.startswith(f"{YDID}:{TYPE_WRKRPOOL}:"):
        return YDIDType.WORKER_POOL
    if ydid.startswith(f"{YDID}:{TYPE_WRKR}:"):
        return YDIDType.WORKER
    if ydid.startswith(f"{YDID}:{TYPE_COMPREQ}:"):
        return YDIDType.COMPUTE_REQUIREMENT
    if ydid.startswith(f"{YDID}:{TYPE_COMPSRC}:"):
        return YDIDType.COMPUTE_SOURCE
    if ydid.startswith(f"{YDID}:{TYPE_NODE}:"):
        return YDIDType.NODE
    if ydid.startswith(f"{YDID}:{TYPE_CRT}:"):
        return YDIDType.COMPUTE_REQUIREMENT_TEMPLATE
    if ydid.startswith(f"{YDID}:{TYPE_CST}:"):
        return YDIDType.COMPUTE_SOURCE_TEMPLATE
    if ydid.startswith(f"{YDID}:{TYPE_IMGFAM}:"):
        return YDIDType.IMAGE_FAMILY
    if ydid.startswith(f"{YDID}:{TYPE_IMGGRP}:"):
        return YDIDType.IMAGE_GROUP
    if ydid.startswith(f"{YDID}:{TYPE_IMAGE}:"):
        return YDIDType.IMAGE
    if ydid.startswith(f"{YDID}:{TYPE_KEYRING}:"):
        return YDIDType.KEYRING
    if ydid.startswith(f"{YDID}:{TYPE_ALLOW}:"):
        return YDIDType.ALLOWANCE
    if ydid.startswith(f"{YDID}:{TYPE_APP}:"):
        return YDIDType.APPLICATION
    if ydid.startswith(f"{YDID}:{TYPE_USER}:"):
        return YDIDType.USER
    if ydid.startswith(f"{YDID}:{TYPE_GROUP}:"):
        return YDIDType.GROUP
    if ydid.startswith(f"{YDID}:{TYPE_ROLE}:"):
        return YDIDType.ROLE

    return None


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


_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_HEX = r"[0-9a-fA-F]+"

# Pre-compiled pattern for highlighting YDIDs embedded in output text.
YDID_HIGHLIGHT_RE = re.compile(
    rf"(?P<ydid>{YDID}:[a-z]+:{_HEX}(?::{_HEX})?:{_UUID}(?::\d+)*)"
)

_TYPES = (
    TYPE_WORKREQ,
    TYPE_TASKGRP,
    TYPE_TASK,
    TYPE_WRKRPOOL,
    TYPE_WRKR,
    TYPE_COMPREQ,
    TYPE_COMPSRC,
    TYPE_NODE,
    TYPE_CRT,
    TYPE_CST,
    TYPE_IMGFAM,
    TYPE_IMGGRP,
    TYPE_IMAGE,
    TYPE_KEYRING,
    TYPE_ALLOW,
    TYPE_APP,
    TYPE_USER,
    TYPE_GROUP,
    TYPE_ROLE,
)
_YDID_RE = re.compile(
    rf"^{YDID}:(?:{'|'.join(_TYPES)}):{_HEX}(?::{_HEX})?:{_UUID}(?::\d+)*$"
)


def is_valid_ydid(ydid: str | None) -> bool:
    """
    Return True if the YDID is well-formed.
    """
    if ydid is None:
        return False
    return bool(_YDID_RE.match(ydid))
