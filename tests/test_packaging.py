"""
pyproject.toml's package list against the package's directories. Setuptools
ships only the packages it lists, so a subpackage left off the list is
missing from the wheel, while every test, run from the checkout, still
passes.
"""

from pathlib import Path

import tomli

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "yellowdog_cli"


def _listed() -> set[str]:
    with open(REPO / "pyproject.toml", "rb") as file:
        return set(tomli.load(file)["tool"]["setuptools"]["packages"])


def _directories_with_modules() -> set[Path]:
    return {
        path.parent for path in PACKAGE.rglob("*.py") if "__pycache__" not in path.parts
    }


def test_every_package_is_listed_and_every_listed_package_exists():
    found = {
        ".".join(directory.relative_to(REPO).parts)
        for directory in _directories_with_modules()
    }
    assert _listed() == found


def test_every_directory_of_modules_is_a_package():
    # Without an __init__.py a directory is a namespace package, which the
    # list above would name but setuptools would not find in the same way
    assert [
        str(directory.relative_to(REPO))
        for directory in sorted(_directories_with_modules())
        if not (directory / "__init__.py").exists()
    ] == []
