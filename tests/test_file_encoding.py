"""
Every text file the CLI reads or writes is opened as UTF-8. Without an
encoding, Python uses the locale's, which on Windows is cp1252: a UTF-8
specification, User Data script or Task Data file holding a non-ASCII
character would fail to decode, or arrive mangled. This test finds, in the
package's source, any text-mode open(), Path.read_text() or Path.write_text()
call that names no encoding.
"""

import ast
from pathlib import Path

import yellowdog_cli

PACKAGE = Path(yellowdog_cli.__file__).parent


def _mode(call: ast.Call) -> str:
    """
    The mode an open() call gives, if it is a literal; 'r' otherwise.
    """
    for keyword in call.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
            return str(keyword.value.value)
    if len(call.args) > 1:
        mode = call.args[1]
        if isinstance(mode, ast.Constant):
            return str(mode.value)
        if isinstance(mode, ast.IfExp):  # e.g. "w" if first else "a"
            return "w"
    return "r"


def _unencoded_lines(source: str) -> list[int]:
    """
    The lines of text-mode file calls in 'source' that name no encoding.
    """
    lines = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if any(keyword.arg == "encoding" for keyword in node.keywords):
            continue
        function = node.func
        is_open = isinstance(function, ast.Name) and function.id == "open"
        is_path_text = isinstance(function, ast.Attribute) and function.attr in (
            "read_text",
            "write_text",
        )
        if (is_open and "b" not in _mode(node)) or is_path_text:
            lines.append(node.lineno)
    return sorted(lines)


def test_every_text_file_is_opened_as_utf_8():
    unencoded = [
        f"{path.relative_to(PACKAGE.parent)}:{line}"
        for path in sorted(PACKAGE.rglob("*.py"))
        for line in _unencoded_lines(path.read_text(encoding="utf-8"))
    ]
    assert unencoded == []


def test_the_check_finds_what_it_looks_for():
    # The control: an unencoded text-mode call is found, the rest are not
    source = (
        "open('a')\n"
        "open('b', 'rb')\n"
        "open('c', encoding='utf-8')\n"
        "p.read_text()\n"
        "p.write_text('x', encoding='utf-8')\n"
        "open('d', 'w' if first else 'a')\n"
    )
    assert _unencoded_lines(source) == [1, 4, 6]


def test_a_specification_with_non_ascii_text_loads(tmp_path):
    from yellowdog_cli.utils.file_substitution import (
        load_json_file_with_variable_substitutions,
    )

    spec = tmp_path / "wr.json"
    spec.write_bytes('{"name": "café ✓"}'.encode())
    assert load_json_file_with_variable_substitutions(str(spec)) == {"name": "café ✓"}
