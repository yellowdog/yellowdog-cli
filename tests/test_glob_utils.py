"""
Unit tests for the shared glob helpers in glob_utils.
"""

from types import SimpleNamespace

import pytest

from yellowdog_cli.utils.dataclient.operations import is_glob
from yellowdog_cli.utils.entity_utils import (
    describe_glob_scope,
    expand_name_globs,
    filter_phrase,
    filter_summaries_by_name_glob,
    namespace_scope,
    resolve_name_glob,
)
from yellowdog_cli.utils.glob_utils import contains_glob_chars, glob_search_prefix

# A client the scope phrases are given; what the Application can read comes
# from the 'readable' fixture's stand-in for its details
CLIENT = object()


@pytest.fixture
def readable(monkeypatch):
    """
    Set the namespaces the Application can read: None for all of them, else
    the list of those it can.
    """
    import yellowdog_cli.utils.entity_utils as eu

    def set_readable(namespaces: list[str] | None):
        details = SimpleNamespace(
            allNamespacesReadable=namespaces is None,
            readableNamespaces=namespaces or [],
        )
        monkeypatch.setattr(eu, "get_application_details", lambda client: details)

    return set_readable


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
        # No namespace searches them all, which the phrase must say rather
        # than quoting an empty namespace.
        (["wp-*"], "", "in all namespaces matching 'wp-*'"),
        (
            ["wp-*", "otherns/prod-*"],
            "",
            "matching 'wp-*' in all namespaces, 'otherns/prod-*'",
        ),
    ],
)
def test_describe_glob_scope(patterns, default_namespace, expected, readable):
    readable(None)  # the Application can read every namespace
    assert describe_glob_scope(CLIENT, patterns, default_namespace) == expected


def test_describe_glob_scope_names_the_namespaces_readable(readable):
    readable(["a", "b"])
    assert describe_glob_scope(CLIENT, ["wp-*"], "") == (
        "in namespaces 'a', 'b' matching 'wp-*'"
    )
    assert describe_glob_scope(CLIENT, ["wp-*", "c/x-*"], "") == (
        "matching 'wp-*' in namespaces 'a', 'b', 'c/x-*'"
    )


def test_describe_glob_scope_rejects_wildcard_namespace():
    with pytest.raises(ValueError, match="namespace"):
        describe_glob_scope(CLIENT, ["*/proj-1"], "yd-demo")


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


@pytest.mark.parametrize(
    "namespace, readable_namespaces, expected",
    [
        ("yd-demo", ["a", "b"], "in namespace 'yd-demo'"),
        # No namespace is every namespace the Application can read, as
        # search_namespaces() scopes the search: all of them, or those named
        ("", None, "in all namespaces"),
        (None, None, "in all namespaces"),
        ("", ["a", "b"], "in namespaces 'a', 'b'"),
        ("", ["a"], "in namespace 'a'"),
    ],
)
def test_namespace_scope(namespace, readable_namespaces, expected, readable):
    readable(readable_namespaces)
    assert namespace_scope(CLIENT, namespace) == expected


def test_namespace_scope_with_none_readable_is_unscoped(readable):
    # The search is then unscoped, for the Platform's 403 to name the
    # permission missing
    readable([])
    assert namespace_scope(CLIENT, "") == "in all namespaces"


@pytest.mark.parametrize(
    "value, expected",
    [("pwt", " with 'pwt' in tag"), ("", ""), (None, "")],
)
def test_filter_phrase_is_empty_for_an_empty_filter(value, expected):
    assert filter_phrase("with '{}' in tag", value) == expected
