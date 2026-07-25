"""Tests for yd-list --name glob filtering."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from yellowdog_cli.utils.settings import (
    ET_COMPUTE_REQUIREMENTS,
    ET_WORK_REQUIREMENTS,
    ET_WORKER_POOLS,
)


def _summary(name, id_, *, namespace=None, status=None):
    return SimpleNamespace(name=name, id=id_, namespace=namespace, status=status)


def _args(**overrides):
    defaults = dict(
        count_only=False,
        json_output=False,
        details=False,
        ids_only=False,
        quiet=True,
        status_filter=None,
        active_only=False,
        entity_type=ET_WORK_REQUIREMENTS,
        name_glob="proj-*",
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def test_name_glob_filters_work_requirements():
    import yellowdog_cli.list as yd_list

    fetched = [_summary("proj-1", "a"), _summary("other", "b")]
    captured = {}

    def fake_fetch(client, **kwargs):
        captured.update(kwargs)
        return fetched

    with (
        patch.object(yd_list, "CLIENT", MagicMock()),
        patch.object(
            yd_list, "CONFIG_COMMON", MagicMock(namespace="default", name_tag="tag")
        ),
        patch.object(yd_list, "ARGS_PARSER", _args()),
        patch.object(
            yd_list, "get_filtered_work_requirement_summaries", side_effect=fake_fetch
        ),
        patch.object(yd_list, "sorted_objects", side_effect=lambda o: o) as mock_sorted,
        patch.object(yd_list, "_apply_status_filter", side_effect=lambda o: o),
        patch.object(yd_list, "print_info"),
        patch.object(yd_list, "_print_empty"),
        patch.object(yd_list, "select", side_effect=lambda client, o: o),
        patch.object(yd_list, "print_numbered_object_list"),
    ):
        yd_list.list_work_requirements()

    # fetched by name prefix, not tag
    assert captured.get("name") == "proj-"
    assert captured.get("tag") is None
    # only the matching summary survives the glob filter
    assert [s.id for s in mock_sorted.call_args.args[0]] == ["a"]


def _wp_summary(namespace, id_):
    return SimpleNamespace(namespace=namespace, status=None, name="wp", id=id_)


def test_empty_name_glob_keeps_namespace_filter_for_worker_pools():
    """
    '--name ""' must behave exactly like no '--name' at all: it should take
    the tag-based fetch path (ARGS_PARSER.name_glob is falsy) AND keep the
    CONFIG_COMMON.namespace-in-namespace substring filter in force. Before the
    fix, the namespace filter was relaxed for any non-None name_glob
    (including ""), leaking Worker Pools from other substring-matching
    namespaces into the listing.
    """
    import yellowdog_cli.list as yd_list

    # 'myns' is an exact match for the first summary's namespace; the second
    # summary's namespace does not contain 'myns' at all and must be excluded.
    fetched = [_wp_summary("myns", "a"), _wp_summary("othernamespace", "b")]

    with (
        patch.object(yd_list, "CLIENT", MagicMock()),
        patch.object(
            yd_list, "CONFIG_COMMON", MagicMock(namespace="myns", name_tag="tag")
        ),
        patch.object(yd_list, "ARGS_PARSER", _args(name_glob="")),
        patch.object(yd_list, "get_worker_pool_summaries", return_value=fetched),
        patch.object(yd_list, "sorted_objects", side_effect=lambda o: o) as mock_sorted,
        patch.object(yd_list, "_apply_status_filter", side_effect=lambda o: o),
        patch.object(yd_list, "print_info"),
        patch.object(yd_list, "_print_empty"),
        patch.object(yd_list, "print_numbered_object_list"),
    ):
        yd_list.list_worker_pools()

    # Only the summary in the exact/matching namespace survives.
    assert [s.id for s in mock_sorted.call_args.args[0]] == ["a"]


def test_name_glob_filters_worker_pools():
    import yellowdog_cli.list as yd_list

    fetched = [
        _summary("wp-1", "a", namespace="default"),
        _summary("other", "b", namespace="default"),
    ]

    with (
        patch.object(yd_list, "CLIENT", MagicMock()),
        patch.object(
            yd_list, "CONFIG_COMMON", MagicMock(namespace="default", name_tag="tag")
        ),
        patch.object(
            yd_list,
            "ARGS_PARSER",
            _args(entity_type=ET_WORKER_POOLS, name_glob="wp-*"),
        ),
        patch.object(
            yd_list, "get_worker_pool_summaries", return_value=fetched
        ) as mock_fetch,
        patch.object(yd_list, "sorted_objects", side_effect=lambda o: o) as mock_sorted,
        patch.object(yd_list, "_apply_status_filter", side_effect=lambda o: o),
        patch.object(yd_list, "print_info"),
        patch.object(yd_list, "_print_empty"),
        patch.object(yd_list, "select", side_effect=lambda client, o: o),
        patch.object(yd_list, "print_numbered_object_list"),
    ):
        yd_list.list_worker_pools()

    # fetched by name prefix (positional), not by CONFIG_COMMON.name_tag
    assert mock_fetch.call_args.args[2] == "wp-"
    # only the matching summary survives the glob filter
    assert [s.id for s in mock_sorted.call_args.args[0]] == ["a"]


def _info_texts(mock_print_info: MagicMock) -> list[str]:
    return [
        call.args[0] if call.args else "" for call in mock_print_info.call_args_list
    ]


def test_name_glob_reports_pattern_not_tag_for_work_requirements():
    """
    When '--name' is used, the info line must report the resolved namespace
    and the name pattern, and must NOT mention the (irrelevant, empty) tag.
    """
    import yellowdog_cli.list as yd_list

    fetched = [_summary("proj-1", "a"), _summary("other", "b")]

    with (
        patch.object(yd_list, "CLIENT", MagicMock()),
        patch.object(
            yd_list, "CONFIG_COMMON", MagicMock(namespace="default", name_tag="")
        ),
        patch.object(yd_list, "ARGS_PARSER", _args(name_glob="proj-*")),
        patch.object(
            yd_list, "get_filtered_work_requirement_summaries", return_value=fetched
        ),
        patch.object(yd_list, "sorted_objects", side_effect=lambda o: o),
        patch.object(yd_list, "_apply_status_filter", side_effect=lambda o: o),
        patch.object(yd_list, "print_info") as mock_print_info,
        patch.object(yd_list, "_print_empty"),
        patch.object(yd_list, "select", side_effect=lambda client, o: o),
        patch.object(yd_list, "print_numbered_object_list"),
    ):
        yd_list.list_work_requirements()

    texts = _info_texts(mock_print_info)
    assert any("matching name pattern 'proj-*'" in t for t in texts)
    assert not any("in tag" in t for t in texts)


def test_name_glob_reports_pattern_not_tag_for_worker_pools():
    """
    Same as above but for Worker Pools: the tag phrasing is "in name", and it
    must be suppressed when '--name' is set.
    """
    import yellowdog_cli.list as yd_list

    fetched = [_wp_summary("default", "a")]

    with (
        patch.object(yd_list, "CLIENT", MagicMock()),
        patch.object(
            yd_list, "CONFIG_COMMON", MagicMock(namespace="default", name_tag="")
        ),
        patch.object(
            yd_list,
            "ARGS_PARSER",
            _args(entity_type=ET_WORKER_POOLS, name_glob="wp-*"),
        ),
        patch.object(yd_list, "get_worker_pool_summaries", return_value=fetched),
        patch.object(yd_list, "sorted_objects", side_effect=lambda o: o),
        patch.object(yd_list, "_apply_status_filter", side_effect=lambda o: o),
        patch.object(yd_list, "print_info") as mock_print_info,
        patch.object(yd_list, "_print_empty"),
        patch.object(yd_list, "select", side_effect=lambda client, o: o),
        patch.object(yd_list, "print_numbered_object_list"),
    ):
        yd_list.list_worker_pools()

    texts = _info_texts(mock_print_info)
    assert any("matching name pattern 'wp-*'" in t for t in texts)
    # NB: "in name" alone is a substring of "in namespace"; check the tag
    # message's distinctive quote-adjacent phrasing instead.
    assert not any("' in name" in t for t in texts)


def test_name_glob_reports_pattern_not_tag_for_compute_requirements():
    """
    Same as above but for Compute Requirements: the tag phrasing mentions
    "names containing", and it must be suppressed when '--name' is set.
    """
    import yellowdog_cli.list as yd_list

    fetched = [_summary("cr-1", "a")]

    with (
        patch.object(yd_list, "CLIENT", MagicMock()),
        patch.object(
            yd_list, "CONFIG_COMMON", MagicMock(namespace="default", name_tag="")
        ),
        patch.object(
            yd_list,
            "ARGS_PARSER",
            _args(entity_type=ET_COMPUTE_REQUIREMENTS, name_glob="cr-*"),
        ),
        patch.object(
            yd_list, "get_compute_requirement_summaries", return_value=fetched
        ),
        patch.object(yd_list, "sorted_objects", side_effect=lambda o: o),
        patch.object(yd_list, "_apply_status_filter", side_effect=lambda o: o),
        patch.object(yd_list, "print_info") as mock_print_info,
        patch.object(yd_list, "_print_empty"),
        patch.object(yd_list, "select", side_effect=lambda client, o: o),
        patch.object(yd_list, "print_numbered_object_list"),
    ):
        yd_list.list_compute_requirements()

    texts = _info_texts(mock_print_info)
    assert any("matching name pattern 'cr-*'" in t for t in texts)
    assert not any("names containing" in t for t in texts)


def test_name_glob_filters_compute_requirements():
    import yellowdog_cli.list as yd_list

    fetched = [_summary("cr-1", "a"), _summary("other", "b")]

    with (
        patch.object(yd_list, "CLIENT", MagicMock()),
        patch.object(
            yd_list, "CONFIG_COMMON", MagicMock(namespace="default", name_tag="tag")
        ),
        patch.object(
            yd_list,
            "ARGS_PARSER",
            _args(entity_type=ET_COMPUTE_REQUIREMENTS, name_glob="cr-*"),
        ),
        patch.object(
            yd_list, "get_compute_requirement_summaries", return_value=fetched
        ) as mock_fetch,
        patch.object(yd_list, "sorted_objects", side_effect=lambda o: o) as mock_sorted,
        patch.object(yd_list, "_apply_status_filter", side_effect=lambda o: o),
        patch.object(yd_list, "print_info"),
        patch.object(yd_list, "_print_empty"),
        patch.object(yd_list, "select", side_effect=lambda client, o: o),
        patch.object(yd_list, "print_numbered_object_list"),
    ):
        yd_list.list_compute_requirements()

    # fetched by tag=None (positional) and name prefix (kwarg), not by tag
    assert mock_fetch.call_args.args[2] is None
    assert mock_fetch.call_args.kwargs.get("name") == "cr-"
    # only the matching summary survives the glob filter
    assert [s.id for s in mock_sorted.call_args.args[0]] == ["a"]
