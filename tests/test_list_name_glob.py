"""
Tests for yd-list --name glob filtering.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    ET_APPLICATIONS,
    ET_COMPUTE_REQUIREMENT_TEMPLATES,
    ET_COMPUTE_REQUIREMENTS,
    ET_COMPUTE_SOURCE_TEMPLATES,
    ET_GROUPS,
    ET_IMAGE_FAMILIES,
    ET_KEYRINGS,
    ET_PERMISSIONS,
    ET_ROLES,
    ET_USERS,
    ET_WORK_REQUIREMENTS,
    ET_WORKER_POOLS,
)


def _ctx() -> RunContext:
    """
    The context a command is given: the wrapper's values, as patched.
    """
    return RunContext(
        wrapper_module.ARGS_PARSER, wrapper_module.CONFIG_COMMON, wrapper_module.CLIENT
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
        # The listing filters, unset as parsed: a MagicMock's would be truthy
        unhealthy=False,
        provisioned=False,
        configured=False,
        provider=None,
        description_glob=None,
        deletable=False,
        with_errors=False,
        within_targets=None,
        list_limit=0,
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
        patch.object(wrapper_module, "CLIENT", MagicMock()),
        patch.object(
            wrapper_module,
            "CONFIG_COMMON",
            MagicMock(namespace="default", name_tag="tag"),
        ),
        patch.object(wrapper_module, "ARGS_PARSER", _args()),
        patch.object(
            yd_list, "get_filtered_work_requirement_summaries", side_effect=fake_fetch
        ),
        patch.object(yd_list, "sorted_objects", side_effect=lambda o: o) as mock_sorted,
        patch.object(yd_list, "_apply_status_filter", side_effect=lambda _ctx, o: o),
        patch.object(yd_list, "print_info"),
        patch.object(yd_list, "_print_empty"),
        patch.object(yd_list, "select", side_effect=lambda client, o: o),
        patch.object(yd_list, "print_numbered_object_list"),
    ):
        yd_list.list_work_requirements(_ctx())

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
        patch.object(wrapper_module, "CLIENT", MagicMock()),
        patch.object(
            wrapper_module, "CONFIG_COMMON", MagicMock(namespace="myns", name_tag="tag")
        ),
        patch.object(wrapper_module, "ARGS_PARSER", _args(name_glob="")),
        patch.object(yd_list, "get_worker_pool_summaries", return_value=fetched),
        patch.object(yd_list, "sorted_objects", side_effect=lambda o: o) as mock_sorted,
        patch.object(yd_list, "_apply_status_filter", side_effect=lambda _ctx, o: o),
        patch.object(yd_list, "print_info"),
        patch.object(yd_list, "_print_empty"),
        patch.object(yd_list, "print_numbered_object_list"),
    ):
        yd_list.list_worker_pools(_ctx())

    # Only the summary in the exact/matching namespace survives.
    assert [s.id for s in mock_sorted.call_args.args[0]] == ["a"]


def test_name_glob_filters_worker_pools():
    import yellowdog_cli.list as yd_list

    fetched = [
        _summary("wp-1", "a", namespace="default"),
        _summary("other", "b", namespace="default"),
    ]

    with (
        patch.object(wrapper_module, "CLIENT", MagicMock()),
        patch.object(
            wrapper_module,
            "CONFIG_COMMON",
            MagicMock(namespace="default", name_tag="tag"),
        ),
        patch.object(
            wrapper_module,
            "ARGS_PARSER",
            _args(entity_type=ET_WORKER_POOLS, name_glob="wp-*"),
        ),
        patch.object(
            yd_list, "get_worker_pool_summaries", return_value=fetched
        ) as mock_fetch,
        patch.object(yd_list, "sorted_objects", side_effect=lambda o: o) as mock_sorted,
        patch.object(yd_list, "_apply_status_filter", side_effect=lambda _ctx, o: o),
        patch.object(yd_list, "print_info"),
        patch.object(yd_list, "_print_empty"),
        patch.object(yd_list, "select", side_effect=lambda client, o: o),
        patch.object(yd_list, "print_numbered_object_list"),
    ):
        yd_list.list_worker_pools(_ctx())

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
        patch.object(wrapper_module, "CLIENT", MagicMock()),
        patch.object(
            wrapper_module, "CONFIG_COMMON", MagicMock(namespace="default", name_tag="")
        ),
        patch.object(wrapper_module, "ARGS_PARSER", _args(name_glob="proj-*")),
        patch.object(
            yd_list, "get_filtered_work_requirement_summaries", return_value=fetched
        ),
        patch.object(yd_list, "sorted_objects", side_effect=lambda o: o),
        patch.object(yd_list, "_apply_status_filter", side_effect=lambda _ctx, o: o),
        patch.object(yd_list, "print_info") as mock_print_info,
        patch.object(yd_list, "_print_empty"),
        patch.object(yd_list, "select", side_effect=lambda client, o: o),
        patch.object(yd_list, "print_numbered_object_list"),
    ):
        yd_list.list_work_requirements(_ctx())

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
        patch.object(wrapper_module, "CLIENT", MagicMock()),
        patch.object(
            wrapper_module, "CONFIG_COMMON", MagicMock(namespace="default", name_tag="")
        ),
        patch.object(
            wrapper_module,
            "ARGS_PARSER",
            _args(entity_type=ET_WORKER_POOLS, name_glob="wp-*"),
        ),
        patch.object(yd_list, "get_worker_pool_summaries", return_value=fetched),
        patch.object(yd_list, "sorted_objects", side_effect=lambda o: o),
        patch.object(yd_list, "_apply_status_filter", side_effect=lambda _ctx, o: o),
        patch.object(yd_list, "print_info") as mock_print_info,
        patch.object(yd_list, "_print_empty"),
        patch.object(yd_list, "select", side_effect=lambda client, o: o),
        patch.object(yd_list, "print_numbered_object_list"),
    ):
        yd_list.list_worker_pools(_ctx())

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
        patch.object(wrapper_module, "CLIENT", MagicMock()),
        patch.object(
            wrapper_module, "CONFIG_COMMON", MagicMock(namespace="default", name_tag="")
        ),
        patch.object(
            wrapper_module,
            "ARGS_PARSER",
            _args(entity_type=ET_COMPUTE_REQUIREMENTS, name_glob="cr-*"),
        ),
        patch.object(
            yd_list, "get_compute_requirement_summaries", return_value=fetched
        ),
        patch.object(yd_list, "sorted_objects", side_effect=lambda o: o),
        patch.object(yd_list, "_apply_status_filter", side_effect=lambda _ctx, o: o),
        patch.object(yd_list, "print_info") as mock_print_info,
        patch.object(yd_list, "_print_empty"),
        patch.object(yd_list, "select", side_effect=lambda client, o: o),
        patch.object(yd_list, "print_numbered_object_list"),
    ):
        yd_list.list_compute_requirements(_ctx())

    texts = _info_texts(mock_print_info)
    assert any("matching name pattern 'cr-*'" in t for t in texts)
    assert not any("names containing" in t for t in texts)


def test_name_glob_filters_compute_requirements():
    import yellowdog_cli.list as yd_list

    fetched = [_summary("cr-1", "a"), _summary("other", "b")]

    with (
        patch.object(wrapper_module, "CLIENT", MagicMock()),
        patch.object(
            wrapper_module,
            "CONFIG_COMMON",
            MagicMock(namespace="default", name_tag="tag"),
        ),
        patch.object(
            wrapper_module,
            "ARGS_PARSER",
            _args(entity_type=ET_COMPUTE_REQUIREMENTS, name_glob="cr-*"),
        ),
        patch.object(
            yd_list, "get_compute_requirement_summaries", return_value=fetched
        ) as mock_fetch,
        patch.object(yd_list, "sorted_objects", side_effect=lambda o: o) as mock_sorted,
        patch.object(yd_list, "_apply_status_filter", side_effect=lambda _ctx, o: o),
        patch.object(yd_list, "print_info"),
        patch.object(yd_list, "_print_empty"),
        patch.object(yd_list, "select", side_effect=lambda client, o: o),
        patch.object(yd_list, "print_numbered_object_list"),
    ):
        yd_list.list_compute_requirements(_ctx())

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
        patch.object(wrapper_module, "CLIENT", MagicMock()),
        patch.object(
            wrapper_module,
            "CONFIG_COMMON",
            MagicMock(namespace="default", name_tag="tag"),
        ),
        patch.object(
            wrapper_module,
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
        yd_list.list_compute_requirement_templates(_ctx())

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
        patch.object(wrapper_module, "CLIENT", MagicMock()),
        patch.object(
            wrapper_module,
            "CONFIG_COMMON",
            MagicMock(namespace="default", name_tag="tag"),
        ),
        patch.object(
            wrapper_module,
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
        yd_list.list_compute_source_templates(_ctx())

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
        patch.object(wrapper_module, "CLIENT", client),
        patch.object(
            wrapper_module,
            "CONFIG_COMMON",
            MagicMock(namespace="default", name_tag="tag"),
        ),
        patch.object(
            wrapper_module,
            "ARGS_PARSER",
            _args(entity_type=ET_IMAGE_FAMILIES, name_glob="img-*", ids_only=True),
        ),
        patch.object(yd_list, "print_info"),
        patch.object(yd_list, "_print_empty"),
    ):
        yd_list.list_image_families(_ctx())

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
        patch.object(wrapper_module, "CLIENT", MagicMock()),
        patch.object(wrapper_module, "CONFIG_COMMON", MagicMock()),
        patch.object(
            wrapper_module,
            "ARGS_PARSER",
            _args(entity_type=ET_USERS, name_glob="al*", count_only=True),
        ),
        patch.object(yd_list, "get_all_users", return_value=fetched),
    ):
        yd_list.list_users(_ctx())

    # only the matching user survives the glob filter
    assert capsys.readouterr().out.strip() == "1"


def test_name_glob_filters_applications(capsys):
    import yellowdog_cli.list as yd_list

    fetched = [_summary("app-alpha", "a"), _summary("app-beta", "b")]

    with (
        patch.object(wrapper_module, "CLIENT", MagicMock()),
        patch.object(wrapper_module, "CONFIG_COMMON", MagicMock()),
        patch.object(
            wrapper_module,
            "ARGS_PARSER",
            _args(entity_type=ET_APPLICATIONS, name_glob="app-alpha", count_only=True),
        ),
        patch.object(yd_list, "get_all_applications", return_value=fetched),
    ):
        yd_list.list_applications(_ctx())

    # only the exactly-matching application survives the glob filter
    assert capsys.readouterr().out.strip() == "1"


def test_name_glob_filters_groups(capsys):
    import yellowdog_cli.list as yd_list

    fetched = [_summary("group-1", "a"), _summary("other", "b")]

    with (
        patch.object(wrapper_module, "CLIENT", MagicMock()),
        patch.object(wrapper_module, "CONFIG_COMMON", MagicMock()),
        patch.object(
            wrapper_module,
            "ARGS_PARSER",
            _args(entity_type=ET_GROUPS, name_glob="group-*", count_only=True),
        ),
        patch.object(yd_list, "get_all_groups", return_value=fetched),
    ):
        yd_list.list_groups(_ctx())

    # only the matching group survives the glob filter (count path skips the
    # per-group detail fetch, so CLIENT.account_client.get_group is not hit)
    assert capsys.readouterr().out.strip() == "1"


def test_name_glob_filters_roles(capsys):
    import yellowdog_cli.list as yd_list

    fetched = [_summary("role-1", "a"), _summary("other", "b")]

    with (
        patch.object(wrapper_module, "CLIENT", MagicMock()),
        patch.object(wrapper_module, "CONFIG_COMMON", MagicMock()),
        patch.object(
            wrapper_module,
            "ARGS_PARSER",
            _args(entity_type=ET_ROLES, name_glob="role-*", count_only=True),
        ),
        patch.object(yd_list, "get_all_roles", return_value=fetched),
    ):
        yd_list.list_roles(_ctx())

    # only the matching role survives the glob filter (count path skips the
    # per-role permission fetch, so CLIENT.account_client.get_role is not hit)
    assert capsys.readouterr().out.strip() == "1"


def test_name_glob_rejected_for_unsupported_entity_type(capsys):
    """
    '--name' is refused, as the command line is parsed, for an entity type
    that does not support it, e.g. 'nodes' (which would otherwise route
    through the Worker-Pool-supporting list_worker_pools()).
    """
    from yellowdog_cli.utils.args import CLIParser

    with pytest.raises(SystemExit) as raised:
        CLIParser(command="yd-list", argv=["nodes", "--name", "x*"])
    assert raised.value.code == 2
    assert "--name does not apply to nodes" in capsys.readouterr().err


def test_name_glob_accepted_for_a_supported_type():
    from yellowdog_cli.utils.args import CLIParser

    assert (
        CLIParser(command="yd-list", argv=["users", "--name", "x*"]).name_glob == "x*"
    )


def test_name_glob_filters_keyrings_and_warns_on_unnamed():
    import yellowdog_cli.list as yd_list

    keyrings = [_summary("proj-1", "a"), _summary("other", "b"), _summary(None, "c")]
    with (
        patch.object(wrapper_module, "CLIENT", MagicMock()) as mock_client,
        patch.object(
            wrapper_module,
            "ARGS_PARSER",
            _args(entity_type=ET_KEYRINGS, name_glob="proj-*"),
        ),
        patch.object(yd_list, "sorted_objects", side_effect=lambda o: o),
        patch.object(yd_list, "print_numbered_object_list") as mock_print,
        patch.object(yd_list, "print_warning") as mock_warning,
    ):
        mock_client.keyring_client.get_keyrings.return_value.list_all.return_value = (
            keyrings
        )
        yd_list.list_keyrings(_ctx())

    assert [k.id for k in mock_print.call_args.args[1]] == ["a"]
    mock_warning.assert_called_once()
    assert "no name" in mock_warning.call_args.args[0]


def test_name_glob_filters_permissions_and_warns_on_unnamed():
    import yellowdog_cli.list as yd_list

    perms = [_summary("read-x", "a"), _summary("write-y", "b"), _summary(None, "c")]
    with (
        patch.object(wrapper_module, "CLIENT", MagicMock()) as mock_client,
        patch.object(
            wrapper_module,
            "ARGS_PARSER",
            _args(entity_type=ET_PERMISSIONS, name_glob="read-*"),
        ),
        patch.object(yd_list, "print_numbered_object_list") as mock_print,
        patch.object(yd_list, "print_warning") as mock_warning,
    ):
        mock_client.account_client.list_permissions.return_value = perms
        yd_list.list_permissions(_ctx())

    assert [p.id for p in mock_print.call_args.args[1]] == ["a"]
    mock_warning.assert_called_once()


def test_name_glob_keyrings_no_warning_when_all_named():
    import yellowdog_cli.list as yd_list

    keyrings = [_summary("proj-1", "a"), _summary("proj-2", "b")]
    with (
        patch.object(wrapper_module, "CLIENT", MagicMock()) as mock_client,
        patch.object(
            wrapper_module,
            "ARGS_PARSER",
            _args(entity_type=ET_KEYRINGS, name_glob="proj-*"),
        ),
        patch.object(yd_list, "sorted_objects", side_effect=lambda o: o),
        patch.object(yd_list, "print_numbered_object_list") as mock_print,
        patch.object(yd_list, "print_warning") as mock_warning,
    ):
        mock_client.keyring_client.get_keyrings.return_value.list_all.return_value = (
            keyrings
        )
        yd_list.list_keyrings(_ctx())

    assert [k.id for k in mock_print.call_args.args[1]] == ["a", "b"]
    mock_warning.assert_not_called()


def test_name_glob_groups_warns_on_unnamed(capsys):
    import yellowdog_cli.list as yd_list

    fetched = [_summary("group-1", "a"), _summary("other", "b"), _summary(None, "c")]
    with (
        patch.object(wrapper_module, "CLIENT", MagicMock()),
        patch.object(wrapper_module, "CONFIG_COMMON", MagicMock()),
        patch.object(
            wrapper_module,
            "ARGS_PARSER",
            _args(entity_type=ET_GROUPS, name_glob="group-*", count_only=True),
        ),
        patch.object(yd_list, "get_all_groups", return_value=fetched),
        patch.object(yd_list, "print_warning") as mock_warning,
    ):
        yd_list.list_groups(_ctx())

    assert capsys.readouterr().out.strip() == "1"
    mock_warning.assert_called_once()
    assert "no name" in mock_warning.call_args.args[0]


def test_name_glob_roles_warns_on_unnamed(capsys):
    import yellowdog_cli.list as yd_list

    fetched = [_summary("role-1", "a"), _summary("other", "b"), _summary(None, "c")]
    with (
        patch.object(wrapper_module, "CLIENT", MagicMock()),
        patch.object(wrapper_module, "CONFIG_COMMON", MagicMock()),
        patch.object(
            wrapper_module,
            "ARGS_PARSER",
            _args(entity_type=ET_ROLES, name_glob="role-*", count_only=True),
        ),
        patch.object(yd_list, "get_all_roles", return_value=fetched),
        patch.object(yd_list, "print_warning") as mock_warning,
    ):
        yd_list.list_roles(_ctx())

    assert capsys.readouterr().out.strip() == "1"
    mock_warning.assert_called_once()
    assert "no name" in mock_warning.call_args.args[0]


@pytest.mark.parametrize(
    "namespace, name_tag, expected",
    [
        (
            "default",
            "pwt",
            "Listing Worker Pools in namespace 'default' with 'pwt' in name",
        ),
        ("", "pwt", "Listing Worker Pools in all namespaces with 'pwt' in name"),
        ("", "", "Listing Worker Pools in all namespaces"),
    ],
)
def test_an_empty_namespace_or_tag_is_not_quoted(namespace, name_tag, expected):
    """
    '' searches every namespace and filters on no name, so the message says
    so rather than "in namespace '' with '' in name".
    """
    import yellowdog_cli.list as yd_list

    with (
        patch.object(wrapper_module, "CLIENT", MagicMock()),
        patch.object(
            wrapper_module,
            "CONFIG_COMMON",
            MagicMock(namespace=namespace, name_tag=name_tag),
        ),
        patch.object(
            wrapper_module,
            "ARGS_PARSER",
            _args(entity_type=ET_WORKER_POOLS, name_glob=None),
        ),
        patch.object(yd_list, "get_worker_pool_summaries", return_value=[]),
        patch.object(yd_list, "print_info") as mock_print_info,
        patch.object(yd_list, "_print_empty"),
    ):
        yd_list.list_worker_pools(_ctx())

    assert _info_texts(mock_print_info)[0] == expected


@pytest.mark.parametrize(
    "flag, name_glob, expected",
    [
        ("configured", None, "Listing Configured Worker Pools in all namespaces"),
        (
            "provisioned",
            "gpu-*",
            "Listing Provisioned Worker Pools in all namespaces matching name"
            " pattern 'gpu-*'",
        ),
    ],
)
def test_the_message_names_the_kind_of_worker_pool(flag, name_glob, expected):
    import yellowdog_cli.list as yd_list

    with (
        patch.object(wrapper_module, "CLIENT", MagicMock()),
        patch.object(
            wrapper_module, "CONFIG_COMMON", MagicMock(namespace="", name_tag="")
        ),
        patch.object(
            wrapper_module,
            "ARGS_PARSER",
            _args(entity_type=ET_WORKER_POOLS, name_glob=name_glob, **{flag: True}),
        ),
        patch.object(yd_list, "get_worker_pool_summaries", return_value=[]),
        patch.object(yd_list, "print_info") as mock_print_info,
        patch.object(yd_list, "_print_empty"),
    ):
        yd_list.list_worker_pools(_ctx())

    assert _info_texts(mock_print_info)[0] == expected


def test_an_empty_namespace_names_those_the_application_can_read():
    """
    An Application without global read access searches only the namespaces
    it can read, so those are what the message names.
    """
    import yellowdog_cli.list as yd_list
    import yellowdog_cli.utils.entity_utils as entity_utils

    details = SimpleNamespace(
        allNamespacesReadable=False, readableNamespaces=["a", "b"]
    )
    with (
        patch.object(wrapper_module, "CLIENT", MagicMock()),
        patch.object(
            wrapper_module, "CONFIG_COMMON", MagicMock(namespace="", name_tag="")
        ),
        patch.object(
            wrapper_module,
            "ARGS_PARSER",
            _args(entity_type=ET_WORKER_POOLS, name_glob=None),
        ),
        patch.object(entity_utils, "get_application_details", return_value=details),
        patch.object(yd_list, "get_worker_pool_summaries", return_value=[]),
        patch.object(yd_list, "print_info") as mock_print_info,
        patch.object(yd_list, "_print_empty"),
    ):
        yd_list.list_worker_pools(_ctx())

    assert _info_texts(mock_print_info)[0] == (
        "Listing Worker Pools in namespaces 'a', 'b'"
    )


# The default scope: the entities the actions select by tag (Work Requirements,
# Worker Pools, Compute Requirements) are listed with the configured tag, as
# those actions select them, so a list previews them; the shared resources
# (templates, Image Families) are listed whatever their names, unless '--tag'
# is given.


@pytest.mark.parametrize(
    "command_name, entity_type",
    [
        ("yd-list", "work-requirements"),
        ("yd workrequirement list", "work-requirements"),
        ("yd workerpool list", "worker-pools"),
        ("yd computerequirement list", "compute-requirements"),
    ],
)
def test_the_tag_is_not_defaulted_away(command_name, entity_type):
    # Left unset, the configured tag applies, as it does for every other
    # command; '-t' with no value still means ''
    from yellowdog_cli.utils.command_registry import build_parser
    from yellowdog_cli.utils.noun_registry import command_named

    command = command_named(command_name)
    assert command is not None
    parser = build_parser(command, prog="x")
    # A noun's verb is given its entity type by the dispatcher, as here
    arguments = [entity_type]
    assert parser.parse_args(arguments).tag is None
    assert parser.parse_args([*arguments, "-t"]).tag == ""


def _template_fetch(function_name, ctx_tag, configured_tag="pwt"):
    import yellowdog_cli.list as yd_list

    captured = {}

    def fake_fetch(client, namespace=None, name=None, *args, **kwargs):
        captured["name"] = name
        return []

    with (
        patch.object(wrapper_module, "CLIENT", MagicMock()),
        patch.object(
            wrapper_module,
            "CONFIG_COMMON",
            MagicMock(namespace="default", name_tag=configured_tag),
        ),
        patch.object(wrapper_module, "ARGS_PARSER", _args(name_glob=None, tag=ctx_tag)),
        patch.object(yd_list, function_name, side_effect=fake_fetch),
        patch.object(yd_list, "print_info"),
        patch.object(yd_list, "_print_empty"),
    ):
        lister = {
            "get_compute_requirement_templates": yd_list.list_compute_requirement_templates,
            "get_compute_source_templates": yd_list.list_compute_source_templates,
        }[function_name]
        lister(_ctx())
    return captured["name"]


@pytest.mark.parametrize(
    "function_name",
    ["get_compute_requirement_templates", "get_compute_source_templates"],
)
def test_templates_are_listed_whatever_the_configured_tag(function_name):
    assert _template_fetch(function_name, ctx_tag=None) == ""


@pytest.mark.parametrize(
    "function_name",
    ["get_compute_requirement_templates", "get_compute_source_templates"],
)
def test_a_tag_given_still_narrows_the_templates(function_name):
    assert (
        _template_fetch(function_name, ctx_tag="demo", configured_tag="demo") == "demo"
    )


def test_image_families_are_listed_whatever_the_configured_tag():
    import yellowdog_cli.list as yd_list

    client = MagicMock()
    client.images_client.get_image_families.return_value.list_all.return_value = []
    with (
        patch.object(wrapper_module, "CLIENT", client),
        patch.object(
            wrapper_module,
            "CONFIG_COMMON",
            MagicMock(namespace="default", name_tag="pwt"),
        ),
        patch.object(wrapper_module, "ARGS_PARSER", _args(name_glob=None, tag=None)),
        patch.object(yd_list, "search_namespaces", return_value=["default"]),
        patch.object(yd_list, "print_info"),
        patch.object(yd_list, "_print_empty"),
    ):
        yd_list.list_image_families(_ctx())

    ((search,), _) = client.images_client.get_image_families.call_args
    assert not search.familyName


@pytest.mark.parametrize(
    "entity_type, lister, search, expected",
    [
        (
            ET_WORK_REQUIREMENTS,
            "list_work_requirements",
            "get_filtered_work_requirement_summaries",
            "Listing active Work Requirements in namespace 'ns' with 'pwt' in tag",
        ),
        (
            "compute-requirements",
            "list_compute_requirements",
            "get_compute_requirement_summaries",
            "Listing active Compute Requirements in namespace 'ns' with tags"
            " including 'pwt'",
        ),
        (
            ET_WORKER_POOLS,
            "list_worker_pools",
            "get_worker_pool_summaries",
            "Listing active Worker Pools in namespace 'ns' with 'pwt' in name",
        ),
    ],
)
def test_active_only_is_said_in_the_one_line(entity_type, lister, search, expected):
    """
    '--active-only' is part of the line saying what is listed, never a line
    of its own.
    """
    import yellowdog_cli.list as yd_list

    with (
        patch.object(wrapper_module, "CLIENT", MagicMock()),
        patch.object(
            wrapper_module, "CONFIG_COMMON", MagicMock(namespace="ns", name_tag="pwt")
        ),
        patch.object(
            wrapper_module,
            "ARGS_PARSER",
            _args(entity_type=entity_type, name_glob=None, active_only=True),
        ),
        patch.object(yd_list, search, return_value=[]),
        patch.object(yd_list, "print_info") as mock_print_info,
        patch.object(yd_list, "_print_empty"),
    ):
        getattr(yd_list, lister)(_ctx())

    assert _info_texts(mock_print_info) == [expected]
