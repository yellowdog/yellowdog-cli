"""
The typed registry of the CLI's own specification properties -- the ones no
SDK dataclass describes: the Work Requirement dictionary, and the shells the
Worker Pool, Compute Requirement, resource and Node Action files put around
their SDK models. utils/spec_schema.py builds the schemas from it; tests/
test_spec_properties.py holds it to README.md's dictionary table. A new
Work Requirement property is added here and given a dictionary row, or the
tests fail; its description is the row's, extracted by `make
schema_descriptions` into spec_data/descriptions.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from importlib.resources import files
from typing import Any


class Level(Enum):
    """Where a Work Requirement property may be set: the dictionary's columns."""

    TOML = "TOML"
    WORK_REQUIREMENT = "WR"
    TASK_GROUP = "TGrp"
    TASK = "Task"


@dataclass(frozen=True)
class SdkRef:
    """A fragment the generator resolves against the installed SDK."""

    model: str  # a dataclass name ("RetryPolicy") or an Enum name


@dataclass(frozen=True)
class Property:
    """
    One specification property. 'schema' is a JSON Schema fragment, or an
    SdkRef; nested fragments may contain SdkRef values and the marker
    {"$ref": "#/$defs/task"}. 'description' is None for a dictionary
    property, whose description comes from descriptions.json.
    """

    name: str
    schema: dict[str, Any] | SdkRef
    levels: frozenset[Level] = frozenset()
    description: str | None = None
    deprecated: bool = False
    required: bool = False


T, W, G, K = Level.TOML, Level.WORK_REQUIREMENT, Level.TASK_GROUP, Level.TASK


def _levels(*levels: Level) -> frozenset[Level]:
    return frozenset(levels)


STR: dict[str, Any] = {"type": "string"}
BOOL: dict[str, Any] = {"type": "boolean"}
INT: dict[str, Any] = {"type": "integer"}
NUM: dict[str, Any] = {"type": "number"}
STRS: dict[str, Any] = {"type": "array", "items": STR}
# Arguments may be numbers or booleans as well as strings
SCALARS: dict[str, Any] = {
    "type": "array",
    "items": {"type": ["string", "number", "boolean"]},
}
STR_MAP: dict[str, Any] = {"type": "object", "additionalProperties": STR}
# A [minimum, maximum] range; either bound may be unset, as null or (which
# TOML needs, having no null) the string "none" or "null"
RANGE: dict[str, Any] = {
    "type": "array",
    "items": {
        "anyOf": [
            {"type": ["number", "null"]},
            {
                "type": "string",
                "pattern": "^\\s*([Nn][Oo][Nn][Ee]|[Nn][Uu][Ll][Ll])\\s*$",
            },
        ]
    },
    "minItems": 2,
    "maxItems": 2,
}
TASK: dict[str, Any] = {"$ref": "#/$defs/task"}

TASK_DATA_INPUT: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["source", "destination"],
    "properties": {
        "source": {
            **STR,
            "description": "the object path to download, relative to the namespace",
        },
        "destination": {
            **STR,
            "description": (
                "where the object is placed on the node, relative to the Task's"
                " working directory"
            ),
        },
        "localPath": {
            **STR,
            "description": (
                "a local file yd-submit uploads to 'uploadPath' (or 'source')"
                " before the Work Requirement is submitted"
            ),
        },
        "uploadPath": {
            **STR,
            "description": (
                "the object path 'localPath' is uploaded to; defaults to 'source'"
            ),
        },
    },
}
TASK_DATA_OUTPUT: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["source", "destination"],
    "properties": {
        "source": {
            **STR,
            "description": (
                "the file on the node to upload, relative to the Task's working"
                " directory"
            ),
        },
        "destination": {
            **STR,
            "description": "the object path to upload it to, relative to the namespace",
        },
        "alwaysUpload": {
            **BOOL,
            "description": "upload the output even when the Task fails",
        },
    },
}

# What submit.py builds the SDK's TaskTemplate from, having read
# 'taskDataFile' or 'taskDataFiles' into 'taskData'; anything else raises
TASK_TEMPLATE: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "taskType": {**STR, "description": "the default Task Type of the Tasks"},
        "taskData": {**STR, "description": "the default Task data of the Tasks"},
        "taskDataFile": {
            **STR,
            "description": (
                "a file whose contents become the default Task data; one of"
                " taskData, taskDataFile, taskDataFiles"
            ),
        },
        "taskDataFiles": {
            **STRS,
            "description": (
                "files concatenated into the default Task data; one of taskData,"
                " taskDataFile, taskDataFiles"
            ),
        },
        "environment": {
            **STR_MAP,
            "description": "the default environment variables of the Tasks",
        },
    },
}

WORK_REQUIREMENT_PROPERTIES: tuple[Property, ...] = (
    Property("addEnvironment", STR_MAP, _levels(T, W, G)),
    Property("addYDEnvironment", BOOL, _levels(T, W, G, K)),
    Property("argumentsPostfix", SCALARS, _levels(T, W, G)),
    Property("argumentsPrefix", SCALARS, _levels(T, W, G)),
    Property("arguments", SCALARS, _levels(T, W, G, K)),
    Property("completedTaskTtl", NUM, _levels(T, W, G)),
    Property("csvFile", STR, _levels(T)),
    Property("csvFiles", STRS, _levels(T)),
    Property("dependencies", STRS, _levels(G)),
    Property("dependentOn", STR, _levels(G), deprecated=True),
    Property("disablePreallocation", BOOL, _levels(T, W, G)),
    Property("environment", STR_MAP, _levels(T, W, G, K)),
    Property("failurePolicy", SdkRef("FailurePolicy"), _levels(T, W, G)),
    Property("finishIfAllTasksFinished", BOOL, _levels(T, W, G)),
    Property("finishIfAnyTaskFailed", BOOL, _levels(T, W, G)),
    Property(
        "instancePricingPreference",
        SdkRef("InstancePricingPreference"),
        _levels(T, W, G),
    ),
    Property("instanceTypes", STRS, _levels(T, W, G)),
    Property("maxWorkers", INT, _levels(T, W, G)),
    Property("maximumTaskRetries", INT, _levels(T, W, G), deprecated=True),
    Property("minWorkers", INT, _levels(T, W, G)),
    Property("name", STR, _levels(T, W, G, K)),
    Property("namespaces", STRS, _levels(T, W, G)),
    Property("parallelBatches", INT, _levels(T)),
    Property("priority", NUM, _levels(T, W, G)),
    Property(
        "providers",
        {"type": "array", "items": SdkRef("CloudProvider")},
        _levels(T, W, G),
    ),
    Property("ram", RANGE, _levels(T, W, G)),
    Property("regions", STRS, _levels(T, W, G)),
    Property("retryPolicy", SdkRef("RetryPolicy"), _levels(T, W, G)),
    Property(
        "retryableErrors",
        {"type": "array", "items": SdkRef("TaskErrorMatcher")},
        _levels(T, W, G),
        deprecated=True,
    ),
    Property("setTaskNames", BOOL, _levels(T, W, G, K)),
    Property("tag", STR, _levels(T, W, G, K)),
    Property("taskBatchSize", INT, _levels(T)),
    Property("taskCount", INT, _levels(T, W, G)),
    Property("taskDataFile", STR, _levels(T, W, G, K)),
    Property("taskDataFiles", STRS, _levels(T, W, G, K)),
    Property(
        "taskDataInputs",
        {"type": "array", "items": TASK_DATA_INPUT},
        _levels(T, W, G, K),
    ),
    Property(
        "taskDataOutputs",
        {"type": "array", "items": TASK_DATA_OUTPUT},
        _levels(T, W, G, K),
    ),
    Property("taskData", STR, _levels(T, W, G, K)),
    Property("taskGroupCount", INT, _levels(T, W)),
    Property("taskGroupName", STR, _levels(T)),
    Property(
        "taskGroups",
        {"type": "array", "items": {"$ref": "#/$defs/taskGroup"}},
        _levels(W),
        required=True,
    ),
    Property("taskName", STR, _levels(T)),
    Property("taskTemplate", TASK_TEMPLATE, _levels(T, W, G)),
    Property("taskTimeout", NUM, _levels(T, W, G)),
    Property("taskType", STR, _levels(T, W, G, K)),
    Property("taskTypes", STRS, _levels(W, G)),
    Property("tasks", {"type": "array", "items": TASK}, _levels(G), required=True),
    Property("tasksPerWorker", INT, _levels(T, W, G)),
    Property("timeout", NUM, _levels(T, K)),
    Property("vcpus", RANGE, _levels(T, W, G)),
    Property("workRequirementData", STR, _levels(T)),
    Property("workerTags", STRS, _levels(T, W, G)),
)

# 'userDataFile' and 'userDataFiles' are not in the two shells below: in a
# Worker Pool or Compute Requirement specification only 'userData' is read,
# the file forms being inherited from the TOML file's [workerPool] section
WORKER_POOL_SHELL: tuple[Property, ...] = (
    Property(
        "requirementTemplateUsage",
        SdkRef("ComputeRequirementTemplateUsage"),
        description=(
            "the Compute Requirement the pool is provisioned on; 'templateId' may"
            " be a Compute Requirement Template name, and 'imagesId' an Image"
            " Family name"
        ),
        required=True,
    ),
    Property(
        "provisionedProperties",
        SdkRef("ProvisionedWorkerPoolProperties"),
        description="how the pool is sized, shut down and configured",
        required=True,
    ),
)
COMPUTE_REQUIREMENT_SHELL: tuple[Property, ...] = (
    Property(
        "requirementTemplateUsage",
        SdkRef("ComputeRequirementTemplateUsage"),
        description=(
            "the Compute Requirement to instantiate; 'templateId' may be a"
            " template name, 'imagesId' an Image Family name. The same properties"
            " may instead be given at the top level"
        ),
    ),
)

_USER_DATA_FILE = Property(
    "userDataFile",
    STR,
    description=(
        "a file whose contents become the instances' user data, after variable"
        " substitution; one of userData, userDataFile, userDataFiles"
    ),
)
_USER_DATA_FILES = Property(
    "userDataFiles",
    STRS,
    description=(
        "files concatenated into the instances' user data, after variable"
        " substitution; one of userData, userDataFile, userDataFiles"
    ),
)

_ROLE_SCOPE: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "global": {**BOOL, "description": "grant the Role in every namespace"},
        "namespaces": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["namespace"],
                "properties": {
                    "namespace": {**STR, "description": "the namespace's name"},
                },
            },
            "description": "the namespaces the Role is granted in, unless global",
        },
    },
}
_GROUP_ROLE: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["role", "scope"],
    "properties": {
        "role": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "id": {**STR, "description": "the Role's YDID"},
                "name": {**STR, "description": "the Role's name"},
            },
            "anyOf": [{"required": ["id"]}, {"required": ["name"]}],
            "description": "a Role, by id or by name",
        },
        "scope": {**_ROLE_SCOPE, "description": "where the Role is granted"},
    },
}

# The CLI-only keys each resource type takes beside its SDK model's
RESOURCE_SHELL: dict[str, tuple[Property, ...]] = {
    "Credential": (
        Property(
            "keyringName",
            STR,
            description="the Keyring to add the credential to",
            required=True,
        ),
        Property(
            "credential",
            {"type": "object", "required": ["type", "name"]},
            description=(
                "the Credential itself; 'type' names its kind, e.g."
                " 'co.yellowdog.platform.account.credentials.AwsCredential'"
            ),
            required=True,
        ),
    ),
    "Application": (
        Property(
            "groups", STRS, description="the Groups the Application belongs to, by name"
        ),
        Property(
            "keyrings",
            STRS,
            description="the Keyrings the Application may access, by name",
        ),
    ),
    "Group": (
        Property(
            "roles",
            {"type": "array", "items": _GROUP_ROLE},
            description="the Roles granted to the Group",
        ),
    ),
    "Keyring": (
        Property("name", STR, description="the Keyring's name", required=True),
        Property(
            "description", STR, description="the Keyring's description", required=True
        ),
    ),
    "Namespace": (
        Property("name", STR, description="the namespace to create", required=True),
    ),
    "InternalUser": (
        Property(
            "name", STR, description="the user's name (one of name, username, id)"
        ),
        Property(
            "username",
            STR,
            description="the user's username (one of name, username, id)",
        ),
        Property("id", STR, description="the user's YDID (one of name, username, id)"),
        Property("groups", STRS, description="the Groups to add the user to, by name"),
    ),
    "ExternalUser": (
        Property("name", STR, description="the user's name (one of name, id)"),
        Property("id", STR, description="the user's YDID (one of name, id)"),
        Property("groups", STRS, description="the Groups to add the user to, by name"),
    ),
    "ComputeRequirementTemplate": (_USER_DATA_FILE, _USER_DATA_FILES),
}

# A Compute Source Template takes the same two inside its 'source', beside
# the compute source class's own properties (create.py resolves them there)
COMPUTE_SOURCE_SHELL: tuple[Property, ...] = (_USER_DATA_FILE, _USER_DATA_FILES)

# Resource types whose shell must carry at least one of these keys: the
# identity a user is found by. The schema generator expresses each as an
# 'anyOf' of single 'required' lists on the resource's object
ONE_OF_REQUIRED: dict[str, tuple[str, ...]] = {
    "InternalUser": ("name", "username", "id"),
    "ExternalUser": ("name", "id"),
}

NODE_ACTION_SHELL: tuple[Property, ...] = (
    Property(
        "type",
        {"enum": ["runCommand", "writeFile", "createWorkers"]},
        description="the kind of action",
        required=True,
    ),
    Property(
        "contentFile",
        STR,
        description=(
            "a file whose contents are written (writeFile), after variable"
            " substitution; one of content, contentFile, contentFiles"
        ),
    ),
    Property(
        "contentFiles",
        STRS,
        description=(
            "files concatenated into the content written (writeFile); one of"
            " content, contentFile, contentFiles"
        ),
    ),
)


def properties_at(level: Level) -> tuple[Property, ...]:
    """The Work Requirement properties that may be set at 'level'."""
    return tuple(p for p in WORK_REQUIREMENT_PROPERTIES if level in p.levels)


def load_descriptions() -> dict[str, str]:
    """The dictionary properties' descriptions, extracted from the README at build time."""
    text = (
        files("yellowdog_cli.spec_data")
        .joinpath("descriptions.json")
        .read_text(encoding="utf-8")
    )
    return json.loads(text)
