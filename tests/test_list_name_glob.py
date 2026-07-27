"""Tests for yd-list --name glob filtering."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from yellowdog_cli.utils.settings import (
    ET_APPLICATIONS,
    ET_COMPUTE_REQUIREMENT_TEMPLATES,
    ET_COMPUTE_REQUIREMENTS,
    ET_COMPUTE_SOURCE_TEMPLATES,
    ET_GROUPS,
    ET_IMAGE_FAMILIES,
    ET_KEYRINGS,
    ET_NODES,
    ET_PERMISSIONS,
    ET_ROLES,
    ET_USERS,
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
        # Consulted by main() itself (not just the list_* functions); pinned
        # to falsy values so a MagicMock's default truthiness doesn't trip
        # main()'s auto-'--details'/output-file branches when tests exercise
        # main() directly (e.g. the dispatch-level rejection test below).
        auto_select_all=False,
        strip_ids=False,
        substitute_ids=False,
        output_file=None,
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


# ---------------------------------------------------------------------------
# Tier-1 extension: Compute Requirement / Source Templates, Image Families
# (namespaced), and Users / Applications / Groups / Roles (account-global)
# ---------------------------------------------------------------------------


def test_name_glob_filters_compute_requirement_templates(capsys):
    import yellowdog_cli.list as yd_list

    fetched = [_summary("crt-1", "a"), _summary("other", "b")]
    captured = {}

    def fake_fetch(client, namespace, name=None, **kwargs):
        captured["namespace"] = namespace
        captured["name"] = name
        return fetched

    with (
        patch.object(yd_list, "CLIENT", MagicMock()),
        patch.object(
            yd_list, "CONFIG_COMMON", MagicMock(namespace="default", name_tag="tag")
        ),
        patch.object(
            yd_list,
            "ARGS_PARSER",
            _args(
                entity_type=ET_COMPUTE_REQUIREMENT_TEMPLATES,
                name_glob="crt-*",
                ids_only=True,
            ),
        ),
        patch.object(
            yd_list, "get_compute_requirement_templates", side_effect=fake_fetch
        ),
        patch.object(yd_list, "print_info"),
        patch.object(yd_list, "_print_empty"),
    ):
        yd_list.list_compute_requirement_templates()

    # fetched by name prefix (positional), not by CONFIG_COMMON.name_tag
    assert captured.get("name") == "crt-"
    assert captured.get("namespace") == "default"
    # only the matching summary survives the glob filter
    assert capsys.readouterr().out.strip() == "a"


def test_name_glob_filters_compute_source_templates(capsys):
    import yellowdog_cli.list as yd_list

    fetched = [_summary("cst-1", "a"), _summary("other", "b")]
    captured = {}

    def fake_fetch(client, namespace=None, name=None):
        captured["namespace"] = namespace
        captured["name"] = name
        return fetched

    with (
        patch.object(yd_list, "CLIENT", MagicMock()),
        patch.object(
            yd_list, "CONFIG_COMMON", MagicMock(namespace="default", name_tag="tag")
        ),
        patch.object(
            yd_list,
            "ARGS_PARSER",
            _args(
                entity_type=ET_COMPUTE_SOURCE_TEMPLATES,
                name_glob="cst-*",
                ids_only=True,
            ),
        ),
        patch.object(yd_list, "get_compute_source_templates", side_effect=fake_fetch),
        patch.object(yd_list, "print_info"),
        patch.object(yd_list, "_print_empty"),
    ):
        yd_list.list_compute_source_templates()

    # fetched by name prefix (kwarg), not by CONFIG_COMMON.name_tag
    assert captured.get("name") == "cst-"
    assert captured.get("namespace") == "default"
    # only the matching summary survives the glob filter
    assert capsys.readouterr().out.strip() == "a"


def test_name_glob_filters_image_families(capsys):
    import yellowdog_cli.list as yd_list

    fetched = [_summary("img-1", "a"), _summary("other", "b")]
    client = MagicMock()
    client.images_client.get_image_families.return_value.list_all.return_value = fetched

    with (
        patch.object(yd_list, "CLIENT", client),
        patch.object(
            yd_list, "CONFIG_COMMON", MagicMock(namespace="default", name_tag="tag")
        ),
        patch.object(
            yd_list,
            "ARGS_PARSER",
            _args(entity_type=ET_IMAGE_FAMILIES, name_glob="img-*", ids_only=True),
        ),
        patch.object(yd_list, "print_info"),
        patch.object(yd_list, "_print_empty"),
    ):
        yd_list.list_image_families()

    # fetched by a familyName prefix, not by CONFIG_COMMON.name_tag
    search_arg = client.images_client.get_image_families.call_args.args[0]
    assert search_arg.familyName == "img-"
    assert search_arg.namespaces == ["default"]
    # only the matching summary survives the glob filter
    assert capsys.readouterr().out.strip() == "a"


def test_name_glob_filters_users(capsys):
    import yellowdog_cli.list as yd_list

    fetched = [_summary("alice", "a"), _summary("bob", "b")]

    with (
        patch.object(yd_list, "CLIENT", MagicMock()),
        patch.object(yd_list, "CONFIG_COMMON", MagicMock()),
        patch.object(
            yd_list,
            "ARGS_PARSER",
            _args(entity_type=ET_USERS, name_glob="al*", count_only=True),
        ),
        patch.object(yd_list, "get_all_users", return_value=fetched),
    ):
        yd_list.list_users()

    # only the matching user survives the glob filter
    assert capsys.readouterr().out.strip() == "1"


def test_name_glob_filters_applications(capsys):
    import yellowdog_cli.list as yd_list

    fetched = [_summary("app-alpha", "a"), _summary("app-beta", "b")]

    with (
        patch.object(yd_list, "CLIENT", MagicMock()),
        patch.object(yd_list, "CONFIG_COMMON", MagicMock()),
        patch.object(
            yd_list,
            "ARGS_PARSER",
            _args(entity_type=ET_APPLICATIONS, name_glob="app-alpha", count_only=True),
        ),
        patch.object(yd_list, "get_all_applications", return_value=fetched),
    ):
        yd_list.list_applications()

    # only the exactly-matching application survives the glob filter
    assert capsys.readouterr().out.strip() == "1"


def test_name_glob_filters_groups(capsys):
    import yellowdog_cli.list as yd_list

    fetched = [_summary("group-1", "a"), _summary("other", "b")]

    with (
        patch.object(yd_list, "CLIENT", MagicMock()),
        patch.object(yd_list, "CONFIG_COMMON", MagicMock()),
        patch.object(
            yd_list,
            "ARGS_PARSER",
            _args(entity_type=ET_GROUPS, name_glob="group-*", count_only=True),
        ),
        patch.object(yd_list, "get_all_groups", return_value=fetched),
    ):
        yd_list.list_groups()

    # only the matching group survives the glob filter (count path skips the
    # per-group detail fetch, so CLIENT.account_client.get_group is not hit)
    assert capsys.readouterr().out.strip() == "1"


def test_name_glob_filters_roles(capsys):
    import yellowdog_cli.list as yd_list

    fetched = [_summary("role-1", "a"), _summary("other", "b")]

    with (
        patch.object(yd_list, "CLIENT", MagicMock()),
        patch.object(yd_list, "CONFIG_COMMON", MagicMock()),
        patch.object(
            yd_list,
            "ARGS_PARSER",
            _args(entity_type=ET_ROLES, name_glob="role-*", count_only=True),
        ),
        patch.object(yd_list, "get_all_roles", return_value=fetched),
    ):
        yd_list.list_roles()

    # only the matching role survives the glob filter (count path skips the
    # per-role permission fetch, so CLIENT.account_client.get_role is not hit)
    assert capsys.readouterr().out.strip() == "1"


def test_name_glob_rejected_for_unsupported_entity_type():
    """
    '--name' must be rejected for entity types outside
    NAME_GLOB_SUPPORTED_ENTITY_TYPES, e.g. 'nodes' (which would otherwise route
    through the Worker-Pool-supporting list_worker_pools()). The helper returns
    False and logs the error; main() then stops before dispatching.
    """
    import yellowdog_cli.list as yd_list

    with (
        patch.object(yd_list, "ARGS_PARSER", _args(name_glob="x*")),
        patch.object(yd_list, "print_error") as mock_print_error,
    ):
        assert yd_list._name_glob_supported(ET_NODES) is False

    mock_print_error.assert_called_once()
    assert "not supported" in mock_print_error.call_args.args[0]
    assert "nodes" in mock_print_error.call_args.args[0]


def test_name_glob_supported_for_supported_type_and_when_unset():
    import yellowdog_cli.list as yd_list

    # A supported entity type with a glob is allowed, with no error logged.
    with (
        patch.object(yd_list, "ARGS_PARSER", _args(name_glob="x*")),
        patch.object(yd_list, "print_error") as mock_print_error,
    ):
        assert yd_list._name_glob_supported(ET_USERS) is True
    mock_print_error.assert_not_called()

    # With no glob, any entity type is allowed.
    with (
        patch.object(yd_list, "ARGS_PARSER", _args(name_glob=None)),
        patch.object(yd_list, "print_error") as mock_print_error,
    ):
        assert yd_list._name_glob_supported(ET_NODES) is True
    mock_print_error.assert_not_called()


def test_name_glob_filters_keyrings_and_warns_on_unnamed():
    import yellowdog_cli.list as yd_list

    keyrings = [_summary("proj-1", "a"), _summary("other", "b"), _summary(None, "c")]
    with (
        patch.object(yd_list, "CLIENT", MagicMock()) as mock_client,
        patch.object(
            yd_list, "ARGS_PARSER", _args(entity_type=ET_KEYRINGS, name_glob="proj-*")
        ),
        patch.object(yd_list, "sorted_objects", side_effect=lambda o: o),
        patch.object(yd_list, "print_numbered_object_list") as mock_print,
        patch.object(yd_list, "print_warning") as mock_warning,
    ):
        mock_client.keyring_client.find_all_keyrings.return_value = keyrings
        yd_list.list_keyrings()

    assert [k.id for k in mock_print.call_args.args[1]] == ["a"]
    mock_warning.assert_called_once()
    assert "no name" in mock_warning.call_args.args[0]


def test_name_glob_filters_permissions_and_warns_on_unnamed():
    import yellowdog_cli.list as yd_list

    perms = [_summary("read-x", "a"), _summary("write-y", "b"), _summary(None, "c")]
    with (
        patch.object(yd_list, "CLIENT", MagicMock()) as mock_client,
        patch.object(
            yd_list,
            "ARGS_PARSER",
            _args(entity_type=ET_PERMISSIONS, name_glob="read-*"),
        ),
        patch.object(yd_list, "print_numbered_object_list") as mock_print,
        patch.object(yd_list, "print_warning") as mock_warning,
    ):
        mock_client.account_client.list_permissions.return_value = perms
        yd_list.list_permissions()

    assert [p.id for p in mock_print.call_args.args[1]] == ["a"]
    mock_warning.assert_called_once()


def test_name_glob_keyrings_no_warning_when_all_named():
    import yellowdog_cli.list as yd_list

    keyrings = [_summary("proj-1", "a"), _summary("proj-2", "b")]
    with (
        patch.object(yd_list, "CLIENT", MagicMock()) as mock_client,
        patch.object(
            yd_list, "ARGS_PARSER", _args(entity_type=ET_KEYRINGS, name_glob="proj-*")
        ),
        patch.object(yd_list, "sorted_objects", side_effect=lambda o: o),
        patch.object(yd_list, "print_numbered_object_list") as mock_print,
        patch.object(yd_list, "print_warning") as mock_warning,
    ):
        mock_client.keyring_client.find_all_keyrings.return_value = keyrings
        yd_list.list_keyrings()

    assert [k.id for k in mock_print.call_args.args[1]] == ["a", "b"]
    mock_warning.assert_not_called()


def test_name_glob_groups_warns_on_unnamed(capsys):
    import yellowdog_cli.list as yd_list

    fetched = [_summary("group-1", "a"), _summary("other", "b"), _summary(None, "c")]
    with (
        patch.object(yd_list, "CLIENT", MagicMock()),
        patch.object(yd_list, "CONFIG_COMMON", MagicMock()),
        patch.object(
            yd_list,
            "ARGS_PARSER",
            _args(entity_type=ET_GROUPS, name_glob="group-*", count_only=True),
        ),
        patch.object(yd_list, "get_all_groups", return_value=fetched),
        patch.object(yd_list, "print_warning") as mock_warning,
    ):
        yd_list.list_groups()

    assert capsys.readouterr().out.strip() == "1"
    mock_warning.assert_called_once()
    assert "no name" in mock_warning.call_args.args[0]


def test_name_glob_roles_warns_on_unnamed(capsys):
    import yellowdog_cli.list as yd_list

    fetched = [_summary("role-1", "a"), _summary("other", "b"), _summary(None, "c")]
    with (
        patch.object(yd_list, "CLIENT", MagicMock()),
        patch.object(yd_list, "CONFIG_COMMON", MagicMock()),
        patch.object(
            yd_list,
            "ARGS_PARSER",
            _args(entity_type=ET_ROLES, name_glob="role-*", count_only=True),
        ),
        patch.object(yd_list, "get_all_roles", return_value=fetched),
        patch.object(yd_list, "print_warning") as mock_warning,
    ):
        yd_list.list_roles()

    assert capsys.readouterr().out.strip() == "1"
    mock_warning.assert_called_once()
    assert "no name" in mock_warning.call_args.args[0]
