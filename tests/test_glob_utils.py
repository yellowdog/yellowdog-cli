"""Unit tests for the shared glob helpers in glob_utils."""

from types import SimpleNamespace

import pytest

from yellowdog_cli.utils.dataclient_utils import is_glob
from yellowdog_cli.utils.entity_utils import (
    describe_glob_scope,
    expand_name_globs,
    filter_summaries_by_name_glob,
    resolve_name_glob,
)
from yellowdog_cli.utils.glob_utils import contains_glob_chars, glob_search_prefix


@pytest.mark.parametrize(
    "value,expected",
    [
        ("proj-*", True),
        ("a?b", True),
        ("a[0-9]", True),
        ("plain-name", False),
        ("ns/proj-*", True),
        ("ns/plain", False),
        ("ydid:workreq:0123:00000000-0000-0000-0000-000000000000", False),
    ],
)
def test_contains_glob_chars(value, expected):
    assert contains_glob_chars(value) is expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("S3:bucket/xxx*", True),
        ("ydid:workreq:abc", False),
        # A glob char before the colon is stripped along with the remote
        # prefix — rclone's is_glob only inspects the path component after
        # 'remote:', unlike the whole-string contains_glob_chars.
        ("*weird:name", False),
    ],
)
def test_rclone_is_glob(value, expected):
    assert is_glob(value) is expected


@pytest.mark.parametrize(
    "pattern,expected",
    [
        ("proj-*", "proj-"),
        ("*-prod", ""),
        ("plain", "plain"),
        ("a?b", "a"),
        ("a[0-9]", "a"),
    ],
)
def test_glob_search_prefix(pattern, expected):
    assert glob_search_prefix(pattern) == expected


def _summary(name, id_):
    return SimpleNamespace(name=name, id=id_)


def test_filter_summaries_by_name_glob():
    summaries = [_summary("proj-1", "a"), _summary("other", "b"), _summary(None, "c")]
    result = filter_summaries_by_name_glob(summaries, "proj-*")
    assert [s.id for s in result] == ["a"]


def test_resolve_name_glob_default_namespace():
    assert resolve_name_glob("proj-*", "default") == ("default", "proj-*")


def test_resolve_name_glob_explicit_namespace():
    assert resolve_name_glob("myns/proj-*", "default") == ("myns", "proj-*")


def test_resolve_name_glob_rejects_wildcard_namespace():
    with pytest.raises(ValueError, match="namespace"):
        resolve_name_glob("*/proj-1", "default")


def test_expand_name_globs_dedupes_and_filters():
    calls = []

    def fetch(namespace, name_prefix):
        calls.append((namespace, name_prefix))
        return [_summary("proj-1", "a"), _summary("proj-2", "b"), _summary("nope", "c")]

    result = expand_name_globs(["proj-*", "proj-1*"], "default", fetch)
    # 'proj-*' matches a,b; 'proj-1*' matches a again (deduped)
    assert [s.id for s in result] == ["a", "b"]
    # server hint is the non-glob prefix
    assert calls == [("default", "proj-"), ("default", "proj-1")]


@pytest.mark.parametrize(
    "patterns,default_namespace,expected",
    [
        # Single pattern, default namespace.
        (["*"], "yd-demo", "in namespace 'yd-demo' matching '*'"),
        # Multiple patterns sharing the default namespace collapse.
        (
            ["proj-*", "test-*"],
            "yd-demo",
            "in namespace 'yd-demo' matching 'proj-*', 'test-*'",
        ),
        # Inline namespace override is resolved per-pattern.
        (["prod/wp-*"], "yd-demo", "in namespace 'prod' matching 'wp-*'"),
        # An inline namespace equal to the default still collapses.
        (
            ["yd-demo/a-*", "b-*"],
            "yd-demo",
            "in namespace 'yd-demo' matching 'a-*', 'b-*'",
        ),
        # Patterns spanning namespaces qualify each pattern.
        (
            ["wp-*", "otherns/prod-*"],
            "yd-demo",
            "matching 'yd-demo/wp-*', 'otherns/prod-*'",
        ),
    ],
)
def test_describe_glob_scope(patterns, default_namespace, expected):
    assert describe_glob_scope(patterns, default_namespace) == expected


def test_describe_glob_scope_rejects_wildcard_namespace():
    with pytest.raises(ValueError, match="namespace"):
        describe_glob_scope(["*/proj-1"], "yd-demo")


def test_get_compute_requirement_summaries_passes_name():
    from unittest.mock import MagicMock, patch

    import yellowdog_cli.utils.entity_utils as eu

    captured = {}

    def fake_search(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    client = MagicMock()
    client.compute_client.get_compute_requirement_summaries.return_value.list_all.return_value = []
    with patch.object(eu, "ComputeRequirementSummarySearch", side_effect=fake_search):
        eu.get_compute_requirement_summaries(client, namespace="ns", name="proj-")
    assert captured["name"] == "proj-"
    assert captured["namespaces"] == ["ns"]
