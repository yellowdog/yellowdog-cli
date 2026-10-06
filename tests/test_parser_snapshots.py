"""
Every command's option shapes, held to a snapshot: the keyword arguments
of each argparse action (nargs, const, default, type, choices, ...), which
help text cannot show. Wording is deliberately excluded, so a help edit
never fails here; a shape change always does, naming the command and the
action. Regenerate with --update-parser-snapshots when the change is meant.
"""

import json
from argparse import Action, _HelpAction
from pathlib import Path
from typing import Any

import pytest

from yellowdog_cli.utils.command_registry import COMMANDS, build_parser

SNAPSHOT_FILE = Path(__file__).parent / "parser_snapshots.json"
UPDATE_COMMAND = "pytest tests/test_parser_snapshots.py --update-parser-snapshots"
UPDATE_HINT = f"If the change is intended, run: {UPDATE_COMMAND}"


_SCALARS = (bool, int, float, str, type(None))


def _json_value(value: Any) -> Any:
    """
    The value itself if JSON can hold it exactly, else its repr().
    """
    if isinstance(value, _SCALARS):
        return value
    if isinstance(value, list) and all(isinstance(v, _SCALARS) for v in value):
        return value
    return repr(value)


def _action_shape(action: Action) -> dict[str, Any]:
    t = action.type
    return {
        "dest": action.dest,
        "kind": type(action).__name__,
        "option_strings": list(action.option_strings),
        "nargs": _json_value(action.nargs),
        "const": _json_value(action.const),
        "default": _json_value(action.default),
        "type": None if t is None else getattr(t, "__name__", repr(t)),
        "choices": (
            None if action.choices is None else [_json_value(c) for c in action.choices]
        ),
        # A positional's requiredness is argparse's derivation from nargs,
        # which is recorded already, and it derives it differently before
        # Python 3.12 ('*' with no default is required there, not after).
        "required": action.required if action.option_strings else None,
    }


def parser_shapes() -> dict[str, list[dict[str, Any]]]:
    """
    Per command, its actions in registration order.
    """
    return {
        name: [
            _action_shape(a)
            for a in build_parser(command, prog=name)._actions
            if not isinstance(a, _HelpAction)
        ]
        for name, command in COMMANDS.items()
    }


def _serialise(shapes: dict[str, Any]) -> str:
    return json.dumps(shapes, indent=2, sort_keys=True) + "\n"


def _differences(
    name: str, expected: list[dict[str, Any]], actual: list[dict[str, Any]]
) -> list[str]:
    def key(a: dict[str, Any]) -> str:
        return a["option_strings"][0] if a["option_strings"] else a["dest"]

    lines: list[str] = []
    exp = {key(a): a for a in expected}
    act = {key(a): a for a in actual}
    for k in sorted(exp.keys() - act.keys()):
        lines.append(f"{name}: action {k} removed")
    for k in sorted(act.keys() - exp.keys()):
        lines.append(f"{name}: action {k} added")
    for k in sorted(exp.keys() & act.keys()):
        for field in sorted(exp[k].keys() | act[k].keys()):
            if exp[k].get(field) != act[k].get(field):
                lines.append(
                    f"{name}: action {k}: {field} was {exp[k].get(field)!r},"
                    f" now {act[k].get(field)!r}"
                )
    if not lines and [key(a) for a in expected] != [key(a) for a in actual]:
        lines.append(f"{name}: actions reordered")
    return lines


def test_parser_shapes_match_snapshot(request: pytest.FixtureRequest) -> None:
    actual = json.loads(_serialise(parser_shapes()))  # as the file would hold it

    if request.config.getoption("--update-parser-snapshots"):
        SNAPSHOT_FILE.write_text(_serialise(actual), encoding="utf-8")
        return

    assert SNAPSHOT_FILE.exists(), (
        f"{SNAPSHOT_FILE.name} is missing. Generate it with: {UPDATE_COMMAND}"
    )
    expected = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))

    problems: list[str] = []
    for name in sorted(expected.keys() - actual.keys()):
        problems.append(f"{name}: command removed")
    for name in sorted(actual.keys() - expected.keys()):
        problems.append(f"{name}: command added")
    for name in sorted(expected.keys() & actual.keys()):
        problems += _differences(name, expected[name], actual[name])

    assert not problems, "\n".join(problems) + "\n" + UPDATE_HINT


def _shape(dest: str, **overrides: Any) -> dict[str, Any]:
    shape: dict[str, Any] = {
        "dest": dest,
        "kind": "_StoreAction",
        "option_strings": [f"--{dest}"],
        "nargs": None,
        "const": None,
        "default": None,
        "type": None,
        "choices": None,
        "required": None,
    }
    shape.update(overrides)
    return shape


def test_differences_are_reported_in_a_fixed_order() -> None:
    """
    Removed, added and changed actions each in sorted order, whatever the
    order the sets holding them iterate in (string hashing varies by run).
    """
    expected = [_shape(d) for d in ("kilo", "alpha", "mike", "delta", "echo", "golf")]
    actual = [_shape(d) for d in ("zulu", "bravo", "lima")] + [
        _shape(d, nargs="+") for d in ("golf", "delta", "echo")
    ]
    assert _differences("yd-x", expected, actual) == [
        "yd-x: action --alpha removed",
        "yd-x: action --kilo removed",
        "yd-x: action --mike removed",
        "yd-x: action --bravo added",
        "yd-x: action --lima added",
        "yd-x: action --zulu added",
        "yd-x: action --delta: nargs was None, now '+'",
        "yd-x: action --echo: nargs was None, now '+'",
        "yd-x: action --golf: nargs was None, now '+'",
    ]
