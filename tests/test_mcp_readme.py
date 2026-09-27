"""
yd-mcp's README ships with the package and lists every tool. Needs neither
the 'mcp' extra nor the SDK.
"""

import re
from fnmatch import fnmatch
from pathlib import Path

import tomli

from yellowdog_cli.mcp.tools import build_tools

REPO = Path(__file__).resolve().parent.parent
README = REPO / "yellowdog_cli" / "mcp" / "README.md"


def test_the_readme_is_declared_as_package_data():
    with open(REPO / "pyproject.toml", "rb") as file:
        pyproject = tomli.load(file)
    globs = pyproject["tool"]["setuptools"]["package-data"]["yellowdog_cli.mcp"]
    assert any(fnmatch("README.md", pattern) for pattern in globs)


def test_every_tool_is_documented():
    text = README.read_text()
    for tool in build_tools():
        assert re.search(rf"`{tool.name}`", text), tool.name


def test_the_table_of_contents_is_current():
    # gh-md-toc's markers are present, and every '## ' heading has an entry
    text = README.read_text()
    assert "<!--ts-->" in text and "<!--te-->" in text
    toc = text.split("<!--ts-->")[1].split("<!--te-->")[0]
    for heading in re.findall(r"^## (.+)$", text, flags=re.MULTILINE):
        anchor = re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-")
        assert f"(#{anchor})" in toc, heading
