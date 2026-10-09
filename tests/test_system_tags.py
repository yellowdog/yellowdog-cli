"""
The tags the live system tests submit under (conftest.py's system_tag): each
session's must be its own. Under 'pytest -n', every worker is a session, and
'pytest-<seconds>' alone was shared by workers starting in the same second,
so one test's yd-cancel or yd-finish, which select by tag, acted on another's
Work Requirement. The tag filters match a tag containing the text given, so
no tag may contain another, either.
"""

import re

import conftest


def test_a_session_tag_is_its_own():
    tags = [conftest._session_tag() for _ in range(50)]
    assert len(set(tags)) == len(tags)
    for tag in tags:
        assert re.fullmatch(r"pytest-\d+-[0-9a-f]{6}", tag), tag
        assert not any(tag in other for other in tags if other != tag)
