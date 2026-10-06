"""
The specification schemas, built when asked: the CLI's own properties from
specs/properties.py, the SDK's models from the installed SDK's dataclasses,
so a newer SDK is described the moment it is installed. Every annotation is
mapped by annotation_schema()'s table or raises SchemaGenerationError naming
the model and field -- nothing falls through to an open schema.

The mapping and the assembly produce plain schemas; _wrap() is applied once,
to the assembled document, to let a {{variable}} string -- the {{::}} unset
token among them -- stand wherever the value is not already a plain string
(a type-tagged substitution, such as {{num:x}} or {{array:x}}, is still a
string when a file is validated).

Imports nothing from args.py, wrapper.py or printing.py: building a schema
needs no command line, configuration or Platform client.
"""

from __future__ import annotations

import copy
import dataclasses
import keyword
import types
import typing
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import Enum
from functools import cache
from typing import Any

from yellowdog_cli._version import __version__
from yellowdog_cli.utils.specs import sdk_models
from yellowdog_cli.utils.specs.properties import (
    ALL_CONFIG_SECTIONS,
    COMPUTE_REQUIREMENT_SHELL,
    COMPUTE_SOURCE_SHELL,
    CONFIG_SECTIONS,
    NODE_ACTION_SHELL,
    ONE_OF_REQUIRED,
    RESOURCE_SHELL,
    WORKER_POOL_SHELL,
    Level,
    Property,
    SdkRef,
    load_descriptions,
    properties_at,
)
from yellowdog_cli.utils.specs.schema_cache import compile_validator

DRAFT = "http://json-schema.org/draft-07/schema#"
ID_BASE = "https://yellowdog.ai/schemas/yellowdog-cli/"
VARIABLE_TOKEN: dict[str, Any] = {
    "type": "string",
    "pattern": r"^\{\{.*\}\}$",
    "description": "a {{variable}} substitution",
}
UNSET_TOKEN: dict[str, Any] = {"const": "{{::}}"}
VARIABLE_REF: dict[str, Any] = {"$ref": "#/$defs/variable"}
DURATION_PATTERN = (
    r"^P(?!$)(\d+Y)?(\d+M)?(\d+W)?(\d+D)?(T(?=\d)(\d+H)?(\d+M)?(\d+(\.\d+)?S)?)?$"
)
FULLY_QUALIFIED_PREFIX = "co.yellowdog.platform.model."

# The fields the SDK's own deserialiser dispatches a polymorphic base on
# (yellowdog_client/common/json: 'type' or 'action', else 'errorType')
DISCRIMINATORS = ("type", "action", "errorType")

# The polymorphic families whose discriminator the CLI reads itself and
# reduces to the class's short name (create.py's '.split(".")[-1]), so the
# short name is accepted as well as the fully qualified one the SDK declares.
# Every other family's discriminator reaches the SDK or the Platform as
# written, so only the declared value is accepted.
CLI_READ_DISCRIMINATORS = frozenset(
    {"ComputeSource", "ComputeRequirementTemplate", "Allowance", "Credential"}
)

# CLI-only properties a polymorphic family's members take beside the SDK's
MEMBER_SHELL: dict[str, tuple[Property, ...]] = {
    "ComputeSource": COMPUTE_SOURCE_SHELL,
}

# Where the CLI reads an SDK field in a form other than the SDK's own: the
# Allowance dates go through dateparser (create_allowance()), which accepts
# natural language such as 'Now' as well as an ISO date-time
_DATEPARSER_STRING: dict[str, Any] = {
    "type": "string",
    "description": (
        "a date and time in any form the dateparser library reads, e.g. 'Now'"
        " or 'After six months', as well as ISO 8601"
    ),
}
FIELD_OVERRIDES: dict[tuple[str, str], dict[str, Any]] = {
    (allowance, field): _DATEPARSER_STRING
    for allowance in sdk_models.ALLOWANCE_CLASSES
    for field in ("effectiveFrom", "effectiveUntil")
}

# Properties create.py demands (it indexes resource["namespace"], with no
# default) though the SDK model leaves them optional: the schema describes
# what yd-create accepts
CLI_REQUIRED: dict[str, tuple[str, ...]] = {
    "ComputeSourceTemplate": ("namespace",),
    "ComputeRequirementStaticTemplate": ("namespace",),
    "ComputeRequirementDynamicTemplate": ("namespace",),
    "AddConfiguredWorkerPoolRequest": ("namespace",),
}

# The SDK-required properties of a Worker Pool or Compute Requirement file's
# usage that the TOML file's [workerPool] section, or a generated default,
# supplies when the file leaves them out (provision.py, instantiate.py)
SUPPLIED_BY_CONFIGURATION: dict[str, frozenset[str]] = {
    "ComputeRequirementTemplateUsage": frozenset({"templateId", "requirementName"}),
}

# yd-nodeaction's 'type' for each Node Action class, and the SDK properties
# its parser does not pass on: 'action' is the SDK's own discriminator, set by
# the class, and '_parse_action()' never passes 'nodeIdFilter'. They are
# dropped in the node-actions family only: a Worker Pool file's 'nodeEvents'
# is posted to the Platform as written, where both are meaningful.
NODE_ACTION_TYPES: dict[str, str] = {
    "runCommand": "NodeRunCommandAction",
    "writeFile": "NodeWriteFileAction",
    "createWorkers": "NodeCreateWorkersAction",
}
NODE_ACTION_NOT_PASSED = frozenset({"action", "nodeIdFilter"})
_WRITE_FILE_ONLY = frozenset({"contentFile", "contentFiles"})


class Family(Enum):
    WORK_REQUIREMENT = "work-requirement"
    WORKER_POOL = "worker-pool"
    COMPUTE_REQUIREMENT = "compute-requirement"
    RESOURCES = "resources"
    NODE_ACTIONS = "node-actions"
    CONFIG = "config"


FAMILY_COMMANDS: dict[Family, str] = {
    Family.WORK_REQUIREMENT: "yd-submit",
    Family.WORKER_POOL: "yd-provision",
    Family.COMPUTE_REQUIREMENT: "yd-instantiate",
    Family.RESOURCES: "yd-create",
    Family.NODE_ACTIONS: "yd-nodeaction",
    Family.CONFIG: "every yd-* command",
}


class SchemaGenerationError(Exception):
    """
    An SDK annotation the mapping does not know, named with its owner.
    """


# --- polymorphism, as the SDK's deserialiser sees it ------------------------


def _leaf_subclasses(cls: type) -> list[type]:
    """
    The leaf subclasses of 'cls', as the SDK's dispatch collects them.
    """
    leaves: set[type] = set()

    def _recurse(parent: type) -> None:
        for subclass in parent.__subclasses__():
            if subclass.__subclasses__():
                _recurse(subclass)
            else:
                leaves.add(subclass)

    _recurse(cls)
    return sorted(leaves, key=lambda c: c.__name__)


def _discriminator_field(cls: type) -> str | None:
    """
    The discriminator 'cls' (a base or a member) declares, if any.
    """
    hints = typing.get_type_hints(cls)
    return next((d for d in DISCRIMINATORS if d in hints), None)


def polymorphic_members(base: type) -> list[type]:
    """
    The concrete classes a polymorphic base resolves to: its leaf subclasses
    with a discriminator, as the SDK's deserialiser dispatches them. Empty
    for a class that is not a polymorphic base.
    """
    if not base.__subclasses__() or _discriminator_field(base) is None:
        return []
    members = []
    for leaf in _leaf_subclasses(base):
        if not leaf.__module__.startswith("yellowdog_client"):
            continue  # a subclass defined outside the SDK is not the SDK's
        if sdk_models.as_dataclass_type(leaf) is None:
            raise SchemaGenerationError(
                f"{base.__name__}: the member {leaf.__name__} is not a dataclass"
            )
        members.append(leaf)
    return members


def _polymorphic_base(cls: type) -> type | None:
    """
    The polymorphic base whose member 'cls' is, if any: the outermost SDK
    ancestor with a discriminator (ComputeSource, not the AwsComputeSource
    between it and AwsInstancesComputeSource).
    """
    if cls.__subclasses__():
        return None
    for ancestor in reversed(cls.__mro__[1:]):
        if (
            ancestor.__module__.startswith("yellowdog_client")
            and _discriminator_field(ancestor) is not None
        ):
            return ancestor
    return None


def _declared_discriminator(cls: type, field_name: str) -> str:
    value = next(
        (f.default for f in dataclasses.fields(cls) if f.name == field_name),
        dataclasses.MISSING,
    )
    if not isinstance(value, str):
        # errorType is an Enum member
        value = getattr(value, "value", value)
    if not isinstance(value, str):
        raise SchemaGenerationError(
            f"{cls.__name__}.{field_name}: a discriminator with no declared value"
        )
    return value


def discriminator_schema(cls: type) -> tuple[str, dict[str, Any]] | None:
    """
    A polymorphic member's discriminator field and its schema: the value the
    class declares, and for the families the CLI reads itself, the short class
    name as well.
    """
    base = _polymorphic_base(cls)
    if base is None:
        return None
    field_name = _discriminator_field(base)
    assert field_name is not None
    declared = _declared_discriminator(cls, field_name)
    if base.__name__ in CLI_READ_DISCRIMINATORS:
        return field_name, {
            "enum": [cls.__name__, declared],
            "description": (
                f"the {base.__name__}'s concrete type, by its short or its fully"
                " qualified name"
            ),
        }
    return field_name, {"const": declared}


# --- the SDK type mapping ---------------------------------------------------


def annotation_schema(
    annotation: Any, defs: dict[str, Any], *, owner: str
) -> dict[str, Any]:
    """
    One field's annotation as a JSON Schema fragment; nested models go into 'defs'.
    """
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin in (types.UnionType, typing.Union):
        members = [a for a in args if a is not type(None)]
        if len(members) == 1:
            schema = annotation_schema(members[0], defs, owner=owner)
        else:
            schema = {
                "anyOf": [annotation_schema(a, defs, owner=owner) for a in members]
            }
        return _nullable(schema) if len(members) < len(args) else schema
    if annotation is str:
        return {"type": "string"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is timedelta:
        return {
            "type": "string",
            "pattern": DURATION_PATTERN,
            "description": "an ISO 8601 duration, e.g. PT10M",
        }
    if annotation is datetime:
        return {"type": "string", "format": "date-time"}
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return {"enum": [member.value for member in annotation]}
    if origin in (list, set, frozenset):
        if len(args) != 1:
            raise SchemaGenerationError(f"{owner}: an unparameterised {annotation!r}")
        return {"type": "array", "items": annotation_schema(args[0], defs, owner=owner)}
    if origin is dict:
        if len(args) != 2:
            raise SchemaGenerationError(f"{owner}: an unparameterised {annotation!r}")
        key, value = args
        schema: dict[str, Any] = {
            "type": "object",
            "additionalProperties": annotation_schema(value, defs, owner=owner),
        }
        if isinstance(key, type) and issubclass(key, Enum):
            schema["propertyNames"] = {"enum": [member.value for member in key]}
        elif key is not str:
            raise SchemaGenerationError(f"{owner}: a mapping keyed by {key!r}")
        return schema
    if isinstance(annotation, typing.TypeVar):
        raise SchemaGenerationError(f"{owner}: an unbound type variable {annotation}")
    base = origin if isinstance(origin, type) else annotation
    if isinstance(base, type) and base.__module__.startswith("yellowdog_client"):
        members = polymorphic_members(base)
        if members:
            # A polymorphic base (an ABC, possibly generic, as AttributeValue[Any]
            # is): each member binds its own type parameters. Dispatched on the
            # discriminator, as a resource is, rather than a 'oneOf', so a
            # violation inside the member keeps its path
            return _polymorphic_dispatch(base, members, defs)
        if origin is not None and sdk_models.as_dataclass_type(origin) is not None:
            # A generic dataclass (Selection[TaskErrorSelector]): expanded inline
            # with its type parameter substituted, since a $def cannot carry it
            return _generic_model_schema(origin, args, defs, owner=owner)
        if sdk_models.as_dataclass_type(annotation) is not None:
            return _ref(annotation, defs)
    raise SchemaGenerationError(f"{owner}: no JSON Schema mapping for {annotation!r}")


def _polymorphic_dispatch(
    base: type, members: list[type], defs: dict[str, Any]
) -> dict[str, Any]:
    """
    A polymorphic base's members, dispatched on its discriminator: each
    member's accepted values (the declared one, and for the families the CLI
    reads itself the short class name too) select its $ref, and an unknown
    value is named against the enum of them all.
    """
    field_name = _discriminator_field(base)
    assert field_name is not None
    cases = []
    for member in members:
        discriminator = discriminator_schema(member)
        assert discriminator is not None
        rule = discriminator[1]
        values = rule["enum"] if "enum" in rule else [rule["const"]]
        cases.append((list(values), _ref(member, defs, discriminated=True)))
    return _dispatch(field_name, cases, f"the {base.__name__}'s concrete type")


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    """
    An Optional field's schema, admitting null: the SDK structures a null as
    the field's None, so a specification may write one (the README's own
    Compute Source Template example does), as a yd-list-generated one may.

    A $ref or a combinator (a dispatch's 'allOf' among them) admits null by
    'if' null 'else' the schema, not an 'anyOf' of the two, for the reason
    the {{variable}} wrapping is written that way: fastjsonschema reports an
    'anyOf' failure without the path inside it.
    """
    kind = schema.get("type")
    if "$ref" in schema or any(k in schema for k in _COMBINATORS):
        return {"if": {"type": "null"}, "else": schema}
    if isinstance(kind, str) and not any(k in schema for k in ("enum", "const")):
        return {**schema, "type": [kind, "null"]}
    if "enum" in schema and "type" not in schema:
        return {**schema, "enum": [*schema["enum"], None]}
    return {"if": {"type": "null"}, "else": schema}


def _ref(
    cls: type, defs: dict[str, Any], *, discriminated: bool = False
) -> dict[str, Any]:
    if cls.__name__ not in defs:
        defs[cls.__name__] = {}  # a placeholder against recursion
        defs[cls.__name__] = model_schema(cls, defs, discriminated=discriminated)
    return {"$ref": f"#/$defs/{cls.__name__}"}


def _json_key(field_name: str) -> str:
    """
    A field's JSON name: the SDK renames 'global_' and the like.
    """
    if field_name.endswith("_") and keyword.iskeyword(field_name[:-1]):
        return field_name[:-1]
    return field_name


def _generic_model_schema(
    origin: type, args: tuple, defs: dict[str, Any], *, owner: str
) -> dict[str, Any]:
    binding = dict(zip(getattr(origin, "__parameters__", ()), args))
    hints = typing.get_type_hints(origin)
    sdk_required = sdk_models.required_properties(origin.__name__)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in dataclasses.fields(origin):
        annotation = _substitute(hints[field.name], binding)
        name = _json_key(field.name)
        properties[name] = annotation_schema(
            annotation, defs, owner=f"{owner} ({origin.__name__}.{field.name})"
        )
        if field.name in sdk_required:
            required.append(name)
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


def _substitute(annotation: Any, binding: dict) -> Any:
    if isinstance(annotation, typing.TypeVar):
        return binding.get(annotation, annotation)
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if origin is None or not args:
        return annotation
    substituted = tuple(_substitute(a, binding) for a in args)
    if origin in (types.UnionType, typing.Union):
        return typing.Union[substituted]  # noqa: UP007 -- built at run time
    return origin[substituted]


def model_schema(
    cls: type,
    defs: dict[str, Any],
    *,
    exclude: frozenset[str] = frozenset(),
    extra: tuple[Property, ...] = (),
    discriminated: bool = False,
) -> dict[str, Any]:
    """
    A dataclass model as a closed object schema: exactly the properties
    sdk_models.settable_properties() allows (less 'exclude'), plus 'extra',
    the CLI-only properties beside them. 'discriminated' is for a class
    reached as a member of its polymorphic base, whose discriminator is then
    added and required; a class the CLI builds directly (a String Attribute
    Definition) takes none.
    """
    name = cls.__name__
    settable = sdk_models.settable_properties(name) - exclude
    required = set(sdk_models.required_properties(name)) - exclude
    required |= set(CLI_REQUIRED.get(name, ()))
    hints = typing.get_type_hints(cls)
    properties: dict[str, Any] = {}
    discriminator = discriminator_schema(cls) if discriminated else None
    if discriminator is not None and discriminator[0] not in exclude:
        properties[discriminator[0]] = discriminator[1]
        required.add(discriminator[0])
    for field in dataclasses.fields(cls):
        if field.name not in settable or field.name in properties:
            continue
        key = _json_key(field.name)
        override = FIELD_OVERRIDES.get((name, field.name))
        properties[key] = (
            dict(override)
            if override is not None
            else annotation_schema(
                hints[field.name], defs, owner=f"{name}.{field.name}"
            )
        )
    base = _polymorphic_base(cls)
    member_shell = MEMBER_SHELL.get(base.__name__, ()) if base is not None else ()
    for prop in (*member_shell, *extra):
        properties[prop.name] = _property_schema(prop, defs, None)
        if prop.required:
            required.add(prop.name)
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
    }
    if required:
        schema["required"] = sorted(required)
    return schema


# --- the CLI's own properties -----------------------------------------------


def _resolve(fragment: Any, defs: dict[str, Any], *, owner: str) -> Any:
    """
    A registry fragment with every SdkRef inside it resolved against the SDK.
    """
    if isinstance(fragment, SdkRef):
        return annotation_schema(
            sdk_models.model_class(fragment.model), defs, owner=owner
        )
    if isinstance(fragment, dict):
        return {k: _resolve(v, defs, owner=owner) for k, v in fragment.items()}
    if isinstance(fragment, list):
        return [_resolve(item, defs, owner=owner) for item in fragment]
    return fragment


def _property_schema(
    prop: Property, defs: dict[str, Any], descriptions: dict[str, str] | None
) -> dict[str, Any]:
    schema = dict(_resolve(prop.schema, defs, owner=prop.name))
    description = prop.description or (descriptions or {}).get(prop.name)
    if description:
        schema["description"] = description  # hoisted beside any $ref by _wrap()
    if prop.deprecated:
        # 'deprecated' is a 2019-09 annotation in a draft-07 document: draft-07
        # validators ignore an unknown keyword, and editors that know it
        # (VS Code's, JetBrains') strike the property through
        schema["deprecated"] = True
    return schema


SCHEMA_PROPERTY: dict[str, Any] = {
    "type": "string",
    "description": "the JSON Schema this document follows; ignored by the CLI",
}


def _object_schema(
    props: tuple[Property, ...],
    defs: dict[str, Any],
    descriptions: dict[str, str] | None,
    *,
    root: bool,
) -> dict[str, Any]:
    properties: dict[str, Any] = {"$schema": SCHEMA_PROPERTY} if root else {}
    required: list[str] = []
    for prop in props:
        properties[prop.name] = _property_schema(prop, defs, descriptions)
        if prop.required:
            required.append(prop.name)
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


def _with_resource(resource_type: str, schema: dict[str, Any]) -> dict[str, Any]:
    """
    A resource branch: 'schema' with the 'resource' key and '$schema' added.
    """
    return {
        **schema,
        "properties": {
            "resource": {"const": resource_type},
            "$schema": SCHEMA_PROPERTY,
            **schema["properties"],
        },
        "required": sorted({"resource", *schema.get("required", ())}),
    }


def _polymorphic_family(base_name: str, defs: dict[str, Any]) -> dict[str, Any]:
    return annotation_schema(
        sdk_models.model_class(base_name), defs, owner=f"the {base_name} family"
    )


def _dispatch(
    key: str, cases: list[tuple[list[str], dict[str, Any]]], description: str
) -> dict[str, Any]:
    """
    An object whose 'key' names which of 'cases' it is: each case's values
    and schema. Written as 'if'/'then' rather than a 'oneOf', so a failure
    is reported against the one case the key names, with its path, not as
    'cannot be validated by any definition' against all of them.

    A {{variable}} in the key itself is admitted by the wrapping, matches no
    case, and so leaves the rest of the object unchecked. That cannot be
    helped: which case applies is not known until the variable is substituted.
    """
    values = [value for case_values, _ in cases for value in case_values]
    return {
        "type": "object",
        "required": [key],
        "properties": {key: {"enum": values, "description": description}},
        "allOf": [
            {
                "if": {"properties": {key: {"enum": case_values}}, "required": [key]},
                "then": schema,
            }
            for case_values, schema in cases
        ],
    }


def _resource_schema(resource_type: str, defs: dict[str, Any]) -> dict[str, Any]:
    """
    The schema one resource type's specification takes.
    """
    shell = RESOURCE_SHELL.get(resource_type, ())
    if resource_type == "Credential":
        props = tuple(p for p in shell if p.name != "credential")
        schema = _object_schema(props, defs, None, root=False)
        schema["properties"]["credential"] = {
            **_polymorphic_family("Credential", defs),
            "description": next(p.description for p in shell if p.name == "credential"),
        }
        schema["required"] = sorted({*schema.get("required", ()), "credential"})
        return _with_resource(resource_type, schema)
    if resource_type in ("ComputeRequirementTemplate", "Allowance"):
        cases = []
        for member in polymorphic_members(sdk_models.model_class(resource_type)):
            discriminator = discriminator_schema(member)
            assert discriminator is not None
            schema = model_schema(member, defs, extra=shell, discriminated=True)
            cases.append(
                (discriminator[1]["enum"], _with_resource(resource_type, schema))
            )
        return _dispatch("type", cases, f"the {resource_type}'s concrete type")
    model_name = sdk_models.MODEL_FOR_RESOURCE.get(resource_type)
    if resource_type == "ComputeSourceTemplate":
        model_name = "ComputeSourceTemplate"
    elif resource_type == "Group":
        model_name = "AddGroupRequest"
    elif resource_type == "NamespacePolicy":
        model_name = "NamespacePolicy"
    if model_name is not None and model_name != sdk_models.DYNAMIC:
        model = sdk_models.model_class(model_name)
        return _with_resource(resource_type, model_schema(model, defs, extra=shell))
    schema = _object_schema(shell, defs, None, root=False)
    if resource_type in ONE_OF_REQUIRED:
        schema["anyOf"] = [
            {"required": [key]} for key in ONE_OF_REQUIRED[resource_type]
        ]
    return _with_resource(resource_type, schema)


def _action_schema(defs: dict[str, Any]) -> dict[str, Any]:
    """
    One yd-nodeaction action: one of the three Node Action classes, by 'type'.
    """
    shell_type = next(p for p in NODE_ACTION_SHELL if p.name == "type")
    cases = []
    for action_type, class_name in NODE_ACTION_TYPES.items():
        extra = tuple(
            p
            for p in NODE_ACTION_SHELL
            if p.name != "type"
            and (p.name not in _WRITE_FILE_ONLY or action_type == "writeFile")
        )
        schema = model_schema(
            sdk_models.model_class(class_name),
            defs,
            exclude=NODE_ACTION_NOT_PASSED,
            extra=extra,
        )
        schema["properties"] = {"type": {"const": action_type}, **schema["properties"]}
        schema["required"] = sorted({"type", *schema.get("required", ())})
        if action_type == "writeFile":
            sources = ("content", "contentFile", "contentFiles")
            schema["not"] = {
                "anyOf": [
                    {"required": [a, b]}
                    for i, a in enumerate(sources)
                    for b in sources[i + 1 :]
                ],
                "description": "only one of content, contentFile, contentFiles",
            }
        cases.append(([action_type], schema))
    return _dispatch("type", cases, shell_type.description or "the kind of action")


def _relax(defs: dict[str, Any], model_name: str) -> None:
    """
    Drop from a $def the required properties the configuration can supply.
    """
    schema = defs[model_name]
    supplied = SUPPLIED_BY_CONFIGURATION[model_name]
    required = [r for r in schema.get("required", ()) if r not in supplied]
    if required:
        schema["required"] = required
    else:
        schema.pop("required", None)


# --- the wrapping ------------------------------------------------------------
#
# A value that is not a plain string -- a number, a Boolean, an enum, an
# array, an object, a model -- also accepts a {{variable}} string, since a
# type-tagged substitution ({{num:x}}, {{bool:x}}, {{array:x}}, {{table:x}})
# is still a string when a file is validated, before it is substituted. The
# {{::}} unset token is such a string too, so it passes for every property.
#
# The wrapping is 'if' a variable 'else' the schema, not an 'anyOf' of the
# two: fastjsonschema reports an 'anyOf' failure as 'cannot be validated by
# any definition' at the wrapper, whereas an 'else' failure is the schema's
# own, with its path ('data.requirementTemplateUsage must not contain
# {'bogus'} properties').

_COMBINATORS = ("anyOf", "oneOf", "allOf")
_HOISTED = ("description", "deprecated")


def _admits_variable(schema: dict[str, Any]) -> bool:
    """
    True where a {{variable}} string already passes: a plain string, or anything.
    """
    if not schema:
        return True
    if any(k in schema for k in ("pattern", "format", "enum", "const", "$ref")):
        return False
    kind = schema.get("type")
    if kind == "string" or (isinstance(kind, list) and "string" in kind):
        return True
    return any(_admits_variable(m) for m in schema.get("anyOf", ()))


def _wrap_node(schema: Any, *, admit: bool = True) -> Any:
    if not isinstance(schema, dict):
        return schema
    wrapped = dict(schema)
    if "properties" in schema:
        wrapped["properties"] = {
            name: _wrap_node(sub) for name, sub in schema["properties"].items()
        }
    if isinstance(schema.get("items"), dict):
        wrapped["items"] = _wrap_node(schema["items"])
    if isinstance(schema.get("additionalProperties"), dict):
        wrapped["additionalProperties"] = _wrap_node(schema["additionalProperties"])
    for key in ("then", "else"):
        # An 'if' is a condition, never a value, and is left alone
        if isinstance(schema.get(key), dict):
            wrapped[key] = _wrap_node(schema[key], admit=False)
    for key in _COMBINATORS:
        if key in schema:
            # Members are left bare: the combinator as a whole admits a
            # variable, which matching every member of a 'oneOf' would fail
            wrapped[key] = [_wrap_node(m, admit=False) for m in schema[key]]
    if admit and not _admits_variable(schema):
        # Hoisted beside the 'if' for an editor, and the description kept on
        # the schema too, which is where a validation failure finds it to
        # word the violation by (specs.validation._message()) -- except beside
        # a '$ref', where draft-07 ignores it and the $def words its own
        meta = {k: wrapped.pop(k) for k in _HOISTED if k in wrapped}
        if "description" in meta and "$ref" not in wrapped:
            wrapped["description"] = meta["description"]
        return {"if": VARIABLE_REF, "else": wrapped, **meta}
    return wrapped


def _wrap(document: dict[str, Any]) -> dict[str, Any]:
    """
    Every value that is not a plain string also accepts a {{variable}} string.
    """
    defs = document.pop("$defs")
    wrapped = _wrap_node(document, admit=False)
    wrapped["$defs"] = {
        name: sub if name == "variable" else _wrap_node(sub, admit=False)
        for name, sub in defs.items()
    }
    return wrapped


# --- assembly ------------------------------------------------------------------


def _config_root(sections: frozenset[str], defs: dict[str, Any]) -> dict[str, Any]:
    """
    The configuration file: the named sections, closed, and any other
    section left to whichever command reads it ('additionalProperties'
    true) when only some are named. A [dataClient] section's table values
    are profiles, carrying the section's own properties.
    """
    descriptions = load_descriptions()
    properties: dict[str, Any] = {"$schema": SCHEMA_PROPERTY}
    for name in sorted(sections):
        section = _object_schema(CONFIG_SECTIONS[name], defs, descriptions, root=False)
        if name == "dataClient":
            section["additionalProperties"] = dict(section)
        properties[name] = section
    return {
        "type": "object",
        "additionalProperties": sections != ALL_CONFIG_SECTIONS,
        "properties": properties,
    }


def build_schema(family: Family) -> dict[str, Any]:
    """
    One family's JSON Schema, wrapped, as a JSON-serialisable dict.
    """
    defs: dict[str, Any] = {}
    root: dict[str, Any]
    if family is Family.WORK_REQUIREMENT:
        descriptions = load_descriptions()
        defs["task"] = _object_schema(
            properties_at(Level.TASK), defs, descriptions, root=False
        )
        defs["taskGroup"] = _object_schema(
            properties_at(Level.TASK_GROUP), defs, descriptions, root=False
        )
        root = _object_schema(
            properties_at(Level.WORK_REQUIREMENT), defs, descriptions, root=True
        )
    elif family is Family.WORKER_POOL:
        root = _object_schema(WORKER_POOL_SHELL, defs, None, root=True)
        _relax(defs, "ComputeRequirementTemplateUsage")
    elif family is Family.COMPUTE_REQUIREMENT:
        # Either wrapped in 'requirementTemplateUsage' -- a Worker Pool file
        # is accepted, its 'provisionedProperties' ignored -- or the usage's
        # own properties at the top level (instantiate.py)
        pool = {p.name: p for p in WORKER_POOL_SHELL}
        wrapped_form = _object_schema(
            (
                *COMPUTE_REQUIREMENT_SHELL,
                dataclasses.replace(
                    pool["provisionedProperties"],
                    required=False,
                    description="a Worker Pool file's; ignored by yd-instantiate",
                ),
            ),
            defs,
            None,
            root=True,
        )
        wrapped_form["required"] = ["requirementTemplateUsage"]
        usage = sdk_models.model_class("ComputeRequirementTemplateUsage")
        _ref(usage, defs)
        _relax(defs, "ComputeRequirementTemplateUsage")
        flat_usage = defs["ComputeRequirementTemplateUsage"]
        flat_form = {
            **flat_usage,
            "properties": {"$schema": SCHEMA_PROPERTY, **flat_usage["properties"]},
        }
        # Dispatched by shape, as instantiate.py does, so a failure is
        # reported against the form the file takes, with its path
        root = {
            "if": {"required": ["requirementTemplateUsage"]},
            "then": wrapped_form,
            "else": flat_form,
        }
    elif family is Family.RESOURCES:
        defs["resource"] = _dispatch(
            "resource",
            [
                ([resource_type], _resource_schema(resource_type, defs))
                for resource_type in sdk_models.RESOURCE_TYPES
            ],
            "the kind of resource",
        )
        resource = {"$ref": "#/$defs/resource"}
        # One resource, or an array of them
        root = {
            "if": {"type": "array"},
            "then": {"items": resource},
            "else": resource,
        }
    elif family is Family.CONFIG:
        root = _config_root(ALL_CONFIG_SECTIONS, defs)
    else:
        defs["action"] = _action_schema(defs)
        actions = {"type": "array", "items": {"$ref": "#/$defs/action"}}
        root = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "$schema": SCHEMA_PROPERTY,
                "actions": {**actions, "description": "actions sent to every node"},
                "actionGroups": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["actions"],
                        "properties": {"actions": actions},
                    },
                    "description": "groups of actions, each group run in turn",
                },
            },
            "oneOf": [{"required": ["actions"]}, {"required": ["actionGroups"]}],
        }
    defs["variable"] = VARIABLE_TOKEN
    title, description = (
        (
            "YellowDog CLI configuration file",
            f"What every yd-* command reads from config.toml; generated by"
            f" yellowdog-cli {__version__} from the installed YellowDog SDK",
        )
        if family is Family.CONFIG
        else (
            f"YellowDog CLI {family.value} specification",
            f"What {FAMILY_COMMANDS[family]} accepts; generated by yellowdog-cli"
            f" {__version__} from the installed YellowDog SDK",
        )
    )
    document = {
        "$schema": DRAFT,
        "$id": f"{ID_BASE}{family.value}.schema.json",
        "title": title,
        "description": description,
        **root,
        "$defs": defs,
    }
    # A copy sharing nothing with the registry's fragments or this module's
    # constants: fastjsonschema rewrites every '$ref' it compiles in place, to
    # an absolute URI against the '$id', and a shared {"$ref": ...} rewritten
    # for one family then sends the next family's compile to fetch the first
    # family's '$id' over the network
    return copy.deepcopy(_wrap(document))


@cache
def compile_schema(family: Family) -> Callable[[Any], Any]:
    """
    The family's schema compiled by fastjsonschema, once per process, and
    kept between processes by specs/schema_cache.py.
    """
    return compile_validator(build_schema(family), family.value)


def build_config_schema(sections: frozenset[str]) -> dict[str, Any]:
    """
    The configuration file's schema over 'sections' only, the rest of the
    file admitted as it is: what a command that reads only those sections
    checks. All of them is exactly build_schema(Family.CONFIG).
    """
    if sections == ALL_CONFIG_SECTIONS:
        return build_schema(Family.CONFIG)
    defs: dict[str, Any] = {"variable": VARIABLE_TOKEN}
    document = {
        "$schema": DRAFT,
        "$id": f"{ID_BASE}{Family.CONFIG.value}-{'-'.join(sorted(sections)) or 'none'}"
        ".schema.json",
        **_config_root(sections, defs),
        "$defs": defs,
    }
    return copy.deepcopy(_wrap(document))


@cache
def compile_config_schema(sections: frozenset[str]) -> Callable[[Any], Any]:
    """
    build_config_schema(sections) compiled, once per process per subset,
    and kept between processes by specs/schema_cache.py.
    """
    stem = (
        Family.CONFIG.value
        if sections == ALL_CONFIG_SECTIONS
        else f"{Family.CONFIG.value}-{'-'.join(sorted(sections)) or 'none'}"
    )
    return compile_validator(build_config_schema(sections), stem)
