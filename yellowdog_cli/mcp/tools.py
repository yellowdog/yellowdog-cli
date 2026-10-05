"""
The MCP tool catalogue, built from the command registry: one tool per
command whose ToolKind is not NONE, its input schema from the command's
options less MCP_EXCLUDED_OPTIONS, and the mapping from a call's arguments
back to the child's command line. Imports nothing from the 'mcp' package,
so the catalogue is testable without the extra, and nothing from the SDK,
wrapper.py, args.py or printing.py.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from yellowdog_cli.utils.command_registry import (
    COMMANDS,
    ENTITY_TYPES,
    MCP_EXCLUDED_OPTIONS,
    Command,
    Exclusive,
    Option,
    ToolKind,
    non_negative_int,
    positive_int,
    resolve_entity_type,
)
from yellowdog_cli.utils.settings import (
    MCP_FOLLOW_TIMEOUT_SECONDS,
    MCP_TOOL_TIMEOUT_SECONDS,
)

TIMEOUT_ARGUMENT = "timeout_seconds"

# The specification-taking commands: the argument that replaces their file
# option(s), and whether it takes several
SPECIFICATION_ARGUMENTS: dict[str, tuple[str, bool]] = {
    "yd-submit": ("specification", False),
    "yd-provision": ("specification", False),
    "yd-instantiate": ("specification", False),
    "yd-create": ("specifications", True),
    "yd-remove": ("specifications", True),
}
# The positional each replaces, which is where its value goes on the
# command line
SPECIFICATION_POSITIONALS: dict[str, str] = {
    "yd-submit": "work_requirement_file_positional",
    "yd-provision": "worker_pool_file_positional",
    "yd-instantiate": "compute_requirement_file_positional",
    "yd-create": "resource_specifications",
    "yd-remove": "resource_specifications",
}
SPECIFICATION_ITEM_SCHEMA: dict[str, Any] = {
    "oneOf": [{"type": "string"}, {"type": "object"}]
}
# The commands that print their own JSON document (printing.print_json(),
# which printing.json_document_printed() records) with no --json option to
# silence the rest of their output: only --quiet keeps the wrapper's 'Done'
# off stdout after the document, which otherwise does not parse
SELF_PRINTING_COMMANDS = frozenset({"yd-show", "yd-variables"})
INLINE_SPECIFICATION_PREFIX = ".yd-mcp-"
# The entity_type description, in place of the argparse help, which offers
# prefixes and single-letter synonyms the schema's enum refuses
ENTITY_TYPE_DESCRIPTION = "the type of entity: one of the full names in the enum"

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "result": {"description": "the command's --json document (see the CLI README)"},
        "exitCode": {"type": "integer"},
        "stopped": {
            "type": "boolean",
            "description": "true when the command was stopped at timeout_seconds",
        },
        "stderr": {
            "type": "string",
            "description": "the command's error output, on a failure",
        },
    },
    "required": ["exitCode"],
}


class ToolArgumentError(Exception):
    """A tool call's arguments cannot be turned into a command line."""


@dataclass(frozen=True)
class ServerSettings:
    """The server's launch options (launcher.py), read by every tool call."""

    config_file: str | None  # absolute, or None for '--nc'
    namespace: str | None
    tag: str | None
    variables: tuple[str, ...]
    transport: str = "stdio"

    @property
    def working_dir(self) -> str:
        # The config file's directory, as Commander runs its children, so
        # that the file's relative paths resolve as the CLI resolves them
        if self.config_file is not None:
            return os.path.dirname(self.config_file)
        return os.getcwd()


@dataclass(frozen=True)
class ToolSpec:
    name: str
    command: Command
    title: str
    description: str
    input_schema: dict[str, Any]
    annotations: dict[str, bool]
    specification_argument: str | None
    timeout_default: int
    # property name -> (option, item schema), for to_argv()
    properties: dict[str, tuple[Option | None, dict[str, Any]]] = field(
        default_factory=dict, repr=False
    )
    exclusive_pairs: tuple[tuple[str, ...], ...] = ()


def tool_name(command: Command) -> str:
    return command.name.replace("-", "_")


def property_name(option: Option) -> str:
    kwargs = option.kwargs
    if "dest" in kwargs:
        return kwargs["dest"]
    if option.positional:
        return option.flags[0]
    return option.name[2:].replace("-", "_")


def _item_schema(option: Option) -> dict[str, Any]:
    kwargs = option.kwargs
    schema: dict[str, Any] = {}
    kind = kwargs.get("type")
    if kind is int:
        schema["type"] = "integer"
    elif kind is positive_int:
        schema["type"] = "integer"
        schema["minimum"] = 1
    elif kind is non_negative_int:
        schema["type"] = "integer"
        schema["minimum"] = 0
    elif kind is resolve_entity_type:
        schema["type"] = "string"
        schema["enum"] = list(ENTITY_TYPES)
    elif kind in (None, str):
        schema["type"] = "string"
    else:
        # A new type has to be mapped on purpose, not passed off as a string
        raise ValueError(
            f"option '{option.name}' has type {getattr(kind, '__name__', kind)!r},"
            " which the MCP tool catalogue does not map"
        )
    if "choices" in kwargs:
        schema["enum"] = list(kwargs["choices"])
    return schema


def _property_schema(option: Option) -> tuple[dict[str, Any], bool]:
    """The JSON Schema of one option, and whether it is required."""
    kwargs = option.kwargs
    schema: dict[str, Any] = {}
    action = kwargs.get("action")
    if action not in (None, "store_true", "append"):
        # 'store_false', 'store_const', 'count' and the rest would otherwise
        # be emitted as 'flag value'; a new kind has to be handled on purpose
        raise ValueError(
            f"option '{option.name}' has action {action!r},"
            " which the MCP tool catalogue does not map"
        )
    if not option.positional and kwargs.get("nargs") in ("*", "+"):
        # to_argv() gives a value as one '--long-flag=value' entry, which
        # could carry only one of such an option's values
        raise ValueError(
            f"option '{option.name}' has nargs {kwargs['nargs']!r},"
            " which the MCP tool catalogue does not map"
        )
    if action == "store_true":
        schema["type"] = "boolean"
    else:
        nargs = kwargs.get("nargs")
        item = _item_schema(option)
        if kwargs.get("action") == "append" or nargs in ("*", "+"):
            schema["type"] = "array"
            schema["items"] = item
        else:
            schema.update(item)
        default = kwargs.get("default")
        if default not in (None, "", []):
            schema["default"] = default
    if kwargs.get("type") is resolve_entity_type:
        schema["description"] = ENTITY_TYPE_DESCRIPTION
    elif kwargs.get("help"):
        schema["description"] = kwargs["help"]
    required = (
        bool(kwargs.get("required"))
        or option.tool_required
        or (option.positional and kwargs.get("nargs") in (None, "+"))
    )
    return schema, required


def _description(command: Command) -> str:
    if command.tool_description:
        return command.tool_description
    return (
        f"{command.summary}. Runs `{command.name}`; see the {command.name} section"
        " of the CLI README for its options and its --json result."
    )


def _annotations(kind: ToolKind) -> dict[str, bool]:
    annotations: dict[str, bool] = {}
    if kind is ToolKind.READ_ONLY:
        annotations["readOnlyHint"] = True
    else:
        # The protocol's default is destructive, so an acting tool says no
        annotations["destructiveHint"] = kind is ToolKind.DESTRUCTIVE
    annotations["openWorldHint"] = True
    return annotations


def _build_tool(command: Command) -> ToolSpec:
    properties: dict[str, tuple[Option | None, dict[str, Any]]] = {}
    schema_properties: dict[str, Any] = {}
    required: list[str] = []
    exclusive_pairs: list[tuple[str, ...]] = []
    spec_argument, spec_plural = SPECIFICATION_ARGUMENTS.get(
        command.name, (None, False)
    )

    for item in command.all_options():
        options = item.options if isinstance(item, Exclusive) else (item,)
        names: list[str] = []
        for option in options:
            if option.name in MCP_EXCLUDED_OPTIONS:
                continue
            name = property_name(option)
            schema, is_required = _property_schema(option)
            properties[name] = (option, schema)
            schema_properties[name] = schema
            if is_required:
                required.append(name)
            names.append(name)
        if isinstance(item, Exclusive) and len(names) > 1:
            exclusive_pairs.append(tuple(names))

    if spec_argument is not None:
        if spec_plural:
            schema = {
                "type": "array",
                "items": SPECIFICATION_ITEM_SCHEMA,
                "description": "resource specifications: each a file path, or the specification itself",
            }
            required.append(spec_argument)
        else:
            schema = {
                **SPECIFICATION_ITEM_SCHEMA,
                "description": "the specification: a file path (JSON, TOML or Jsonnet), or the specification itself",
            }
        properties[spec_argument] = (None, schema)
        schema_properties[spec_argument] = schema

    timeout_default = (
        MCP_FOLLOW_TIMEOUT_SECONDS
        if command.name == "yd-follow"
        else MCP_TOOL_TIMEOUT_SECONDS
    )
    timeout_schema = {
        "type": "integer",
        "minimum": 1,
        "default": timeout_default,
        "description": "stop the command after this many seconds and return what it produced",
    }
    properties[TIMEOUT_ARGUMENT] = (None, timeout_schema)
    schema_properties[TIMEOUT_ARGUMENT] = timeout_schema

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": schema_properties,
        "additionalProperties": False,
    }
    if required:
        input_schema["required"] = required
    if exclusive_pairs:
        input_schema["allOf"] = [
            {"not": {"required": list(pair)}} for pair in exclusive_pairs
        ]

    return ToolSpec(
        name=tool_name(command),
        command=command,
        title=command.summary,
        description=_description(command),
        input_schema=input_schema,
        annotations=_annotations(command.tool),
        specification_argument=spec_argument,
        timeout_default=timeout_default,
        properties=properties,
        exclusive_pairs=tuple(exclusive_pairs),
    )


@cache
def build_tools() -> tuple[ToolSpec, ...]:
    # Built once: the registry is fixed at import, and tool_named() hands out
    # the same ToolSpec objects every caller of build_tools() sees
    tools = [
        _build_tool(command)
        for command in COMMANDS.values()
        if command.tool is not ToolKind.NONE
    ]
    return tuple(sorted(tools, key=lambda t: t.name))


@cache
def _tools_by_name() -> dict[str, ToolSpec]:
    return {t.name: t for t in build_tools()}


def tool_named(name: str) -> ToolSpec | None:
    return _tools_by_name().get(name)


def fixed_args(command: Command, settings: ServerSettings) -> list[str]:
    """
    The arguments the server adds ahead of a tool's own, each only where
    the command has the option: the config source, no formatting, the JSON
    result (or, for SELF_PRINTING_COMMANDS, quiet), no prompts, and the launch-time namespace, tag and variables
    (first, so a tool's own come later and win).
    """
    args: list[str] = []
    if command.option_named("--config") is not None:
        args += (
            ["-c", os.path.basename(settings.config_file)]
            if settings.config_file is not None
            else ["--nc"]
        )
    if command.option_named("--no-format") is not None:
        args.append("--nf")
    if command.option_named("--json") is not None or command.name == "yd-version":
        # yd-version's parser is its own and not in the registry
        args.append("--json")
    if command.name in SELF_PRINTING_COMMANDS:
        args.append("--quiet")
    if command.option_named("--yes") is not None:
        args.append("--yes")
    # Joined, as a tool's own values are (see _joined()): a launch-time value
    # beginning with '-' is a value, never a flag
    if settings.namespace and command.option_named("--namespace") is not None:
        args.append(f"--namespace={settings.namespace}")
    if settings.tag and command.option_named("--tag") is not None:
        args.append(f"--tag={settings.tag}")
    if command.option_named("--variable") is not None:
        args += [f"--variable={variable}" for variable in settings.variables]
    return args


def timeout_of(tool: ToolSpec, arguments: dict[str, Any]) -> int:
    value = arguments.get(TIMEOUT_ARGUMENT, tool.timeout_default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ToolArgumentError(
            f"{TIMEOUT_ARGUMENT} must be a whole number of seconds, at least 1"
        )
    return value


def _check(name: str, value: Any, schema: dict[str, Any]) -> None:
    kind = schema.get("type")
    if "oneOf" in schema:
        if not isinstance(value, (str, dict)):
            raise ToolArgumentError(
                f"{name} must be a file path or a specification object"
            )
        return
    if kind == "boolean":
        if not isinstance(value, bool):
            raise ToolArgumentError(f"{name} must be true or false")
    elif kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ToolArgumentError(f"{name} must be an integer")
        if "minimum" in schema and value < schema["minimum"]:
            raise ToolArgumentError(f"{name} must be at least {schema['minimum']}")
    elif kind == "array":
        if not isinstance(value, list):
            raise ToolArgumentError(f"{name} must be a list")
        for item in value:
            _check(name, item, schema["items"])
    elif kind == "string":
        if not isinstance(value, str):
            raise ToolArgumentError(f"{name} must be a string")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolArgumentError(f"{name} must be one of {', '.join(schema['enum'])}")


def _validate(tool: ToolSpec, arguments: dict[str, Any]) -> None:
    for name in arguments:
        if name not in tool.properties:
            raise ToolArgumentError(f"{tool.name} has no argument '{name}'")
    for name in tool.input_schema.get("required", ()):
        if name not in arguments:
            raise ToolArgumentError(f"{tool.name} needs '{name}'")
    for name, value in arguments.items():
        _check(name, value, tool.properties[name][1])
    for pair in tool.exclusive_pairs:
        given = [name for name in pair if name in arguments]
        if len(given) > 1:
            raise ToolArgumentError(f"give one of {' and '.join(pair)}, not both")


def _write_specification(specification: dict[str, Any], working_dir: str) -> Path:
    # A random name created exclusively (O_EXCL, so a symlink pre-placed at
    # the name is never followed) and readable by the owner only (0600):
    # concurrent calls never share a file, and nobody else reads it
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=working_dir,
        prefix=INLINE_SPECIFICATION_PREFIX,
        suffix=".json",
        delete=False,
    ) as file:
        path = Path(file.name)
        try:
            file.write(json.dumps(specification, indent=2))
        except BaseException:
            file.close()
            path.unlink(missing_ok=True)
            raise
    return path


def _joined(option: Option, value: Any) -> str:
    """
    A value-taking option and its value as ONE argv entry, '--long-flag=value'.
    Load-bearing for security, not style: given as two entries, a value that
    looks like a flag ('--show-secrets', '--debug', '--yes') is taken by
    argparse as that flag wherever the option has nargs='?' ('--namespace',
    '--tag'), which would switch on exactly the options MCP_EXCLUDED_OPTIONS
    withholds. Joined, argparse can only read it as the value.
    """
    return f"{option.name}={value}"


def to_argv(
    tool: ToolSpec, arguments: dict[str, Any], working_dir: str
) -> tuple[list[str], list[Path]]:
    """
    A tool call's arguments as the child's own arguments: options in
    registry order (a true boolean as its flag, a value as one
    '--long-flag=value' entry (_joined(), which says why), a list as that
    entry repeated for 'append'), then
    '--' and the positionals in registry order, so that a positional
    starting with '-' (a glob, a remote path) is not read as an option. An inline specification is written to
    a uniquely named JSON file in the working directory, so that relative
    file references inside it resolve as from a file the user wrote there;
    the files written are returned for the caller to remove. Nothing is
    written unless every argument is acceptable, and if a write fails the
    files already written are removed before the error is raised.
    """
    _validate(tool, arguments)
    written: list[Path] = []
    try:
        return _to_argv(tool, arguments, working_dir, written), written
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise


def _to_argv(
    tool: ToolSpec, arguments: dict[str, Any], working_dir: str, written: list[Path]
) -> list[str]:
    options: list[str] = []
    positionals: list[str] = []
    spec_positional = SPECIFICATION_POSITIONALS.get(tool.command.name)

    for option in tool.command.flat_options():
        if (
            option.positional
            and option.flags[0] == spec_positional
            and tool.specification_argument
        ):
            values = arguments.get(tool.specification_argument)
            if values is None:
                continue
            for item in values if isinstance(values, list) else [values]:
                if isinstance(item, dict):
                    written.append(_write_specification(item, working_dir))
                    positionals.append(written[-1].name)
                else:
                    positionals.append(item)
            continue
        if option.name in MCP_EXCLUDED_OPTIONS:
            continue
        name = property_name(option)
        if name not in arguments:
            continue
        value = arguments[name]
        if option.positional:
            positionals += (
                [str(v) for v in value] if isinstance(value, list) else [str(value)]
            )
            continue
        if isinstance(value, bool):
            # The option's last flag: its short form, or its alias
            # (Option.flags lists the long flag first), or the long flag
            if value:
                options.append(option.flags[-1])
        elif isinstance(value, list):
            # An array is an 'append' option: the flag repeated, one per item
            options += [_joined(option, item) for item in value]
        else:
            options.append(_joined(option, value))
    return [*options, "--", *positionals] if positionals else options
