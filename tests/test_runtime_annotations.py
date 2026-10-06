"""
No module uses a name it imports only under 'if TYPE_CHECKING:' in an
annotation that Python evaluates as the module loads, unless the module has
'from __future__ import annotations'. Python 3.14 defers evaluating
annotations, so such a module imports cleanly there, which is what the suite
runs on, while on 3.10 to 3.13 it raises NameError as it is imported:
yd-cloudwizard failed that way on every run.
"""

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "yellowdog_cli"


def _type_checking_names(tree: ast.Module) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and (
            (isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING")
            or (
                isinstance(node.test, ast.Attribute)
                and node.test.attr == "TYPE_CHECKING"
            )
        ):
            for statement in node.body:
                if isinstance(statement, (ast.Import, ast.ImportFrom)):
                    for alias in statement.names:
                        names.add(alias.asname or alias.name.split(".")[0])
    return names


def _evaluated_annotations(tree: ast.Module) -> list[ast.expr]:
    """
    A function's parameter and return annotations, evaluated when it is
    defined, and every variable annotation (a superset of those evaluated).
    """
    annotations: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            arguments = node.args
            for argument in [
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
                arguments.vararg,
                arguments.kwarg,
            ]:
                if argument is not None and argument.annotation is not None:
                    annotations.append(argument.annotation)
            if node.returns is not None:
                annotations.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            annotations.append(node.annotation)
    return annotations


def _defers_annotations(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )


def test_no_type_checking_name_is_evaluated_at_import():
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if _defers_annotations(tree):
            continue
        type_checking = _type_checking_names(tree)
        for annotation in _evaluated_annotations(tree):
            for node in ast.walk(annotation):
                if isinstance(node, ast.Name) and node.id in type_checking:
                    found.append(
                        f"{path.relative_to(PACKAGE)}:{node.lineno}: {node.id}"
                    )
    assert found == []
