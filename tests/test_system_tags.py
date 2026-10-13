"""
The tags the live system tests submit under (conftest.py's system_tag): each
session's must be its own. Under 'pytest -n', every worker is a session, and
'pytest-<seconds>' alone was shared by workers starting in the same second,
so one test's yd workrequirement cancel or finish, which select by tag, acted
on another's Work Requirement. The tag filters match a tag containing the text
given, so no tag may contain another, either.
"""

import importlib.util
import re
from pathlib import Path


def _root_conftest():
    """
    The repository's conftest.py, loaded by its path: 'import conftest'
    finds whichever conftest pytest imported last, tests/live/conftest.py
    included, since neither directory is a package.
    """
    path = Path(__file__).resolve().parents[1] / "conftest.py"
    spec = importlib.util.spec_from_file_location("root_conftest", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_session_tag_is_its_own():
    session_tag = _root_conftest()._session_tag
    tags = [session_tag() for _ in range(50)]
    assert len(set(tags)) == len(tags)
    for tag in tags:
        assert re.fullmatch(r"pytest-\d+-[0-9a-f]{6}", tag), tag
        assert not any(tag in other for other in tags if other != tag)
