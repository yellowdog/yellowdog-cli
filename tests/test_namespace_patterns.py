"""
Tests for namespace patterns: '-n team-*' taken by 'yd list' and the 'list'
verbs alone, refused by every other command from any source, and expanded
into the readable namespaces it matches.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from yellowdog_cli.utils import entity_utils, load_config, work_targets
from yellowdog_cli.utils.args import CLIParser
from yellowdog_cli.utils.command_registry import COMMANDS, NAMESPACE
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    ET_COMPUTE_REQUIREMENT_TEMPLATES,
    ET_COMPUTE_REQUIREMENTS,
    ET_COMPUTE_SOURCE_TEMPLATES,
    ET_COMPUTE_SOURCES,
    ET_IMAGE_FAMILIES,
    ET_INSTANCES,
    ET_NAMESPACE_POLICIES,
    ET_NODES,
    ET_TASK_GROUPS,
    ET_TASKS,
    ET_WORK_REQUIREMENTS,
    ET_WORKER_POOLS,
    ET_WORKERS,
)
from yellowdog_cli.utils.exit_codes import ExitCode, NotFoundError
from yellowdog_cli.utils.limits import NAMESPACE_PATTERN_MAX_MATCHES
from yellowdog_cli.utils.noun_registry import NOUN_COMMANDS, command_named
from yellowdog_cli.utils.output_style import NAMESPACE_SCOPE_SHOWN
from yellowdog_cli.utils.settings import YD_KEY, YD_NAMESPACE, YD_SECRET

_REFUSAL = (
    "--namespace 'team-*' is a pattern: only 'yd list' and the 'list' verbs take one"
)


@pytest.mark.parametrize("name", sorted({*COMMANDS, *NOUN_COMMANDS}))
def test_only_the_list_commands_take_a_namespace_pattern(name):
    command = command_named(name)
    assert command is not None
    if not command.has(NAMESPACE):  # by name: NAME_NAMESPACE, LIST_NAMESPACE too
        pytest.skip("no --namespace")
    assert command.namespace_patterns is (command.internal_name == "yd-list")


@pytest.mark.parametrize(
    "command, argv",
    [
        ("yd-cancel", ["-n", "team-*"]),
        ("yd workrequirement cancel", ["-n", "team-*"]),
        ("yd-show", ["-n", "team-*", "some-name"]),
        ("yd workrequirement submit", ["-n", "team-*"]),
    ],
)
def test_a_pattern_is_refused_on_the_command_line(command, argv, capsys):
    with pytest.raises(SystemExit) as excinfo:
        CLIParser(command=command, argv=argv)
    assert excinfo.value.code == 2
    assert _REFUSAL in capsys.readouterr().err


@pytest.mark.parametrize(
    "command, argv",
    [
        ("yd-list", ["work-requirements", "-n", "team-*"]),
        # The fixed entity type, which noun_dispatch puts first
        ("yd workrequirement list", ["work-requirements", "-n", "team-*"]),
        ("yd workerpool list", ["worker-pools", "-n", "team-[ab]"]),
    ],
)
def test_the_list_commands_take_a_pattern(command, argv):
    parser = CLIParser(command=command, argv=argv)
    assert parser.namespace_patterns_allowed is True
    assert parser.args.namespace == argv[argv.index("-n") + 1]


def test_a_plain_namespace_is_taken_by_every_command():
    assert (
        CLIParser(command="yd-cancel", argv=["-n", "team-a"]).args.namespace == "team-a"
    )
    assert CLIParser(command="yd-cancel", argv=[]).namespace_patterns_allowed is False


# --- A configured pattern (Task 2) -------------------------------------------


def _config_args(allowed: bool, **values) -> MagicMock:
    args = MagicMock()
    for name in ("key", "secret", "namespace", "tag", "url", "use_pac", "config_file"):
        setattr(args, name, values.get(name))
    args.namespace_required = False
    args.tag_required = False
    args.property_overrides = values.get("property_overrides")
    # As CLIParser.namespace_pattern_refused gives it
    args.namespace_pattern_refused = not allowed
    return args


@pytest.fixture
def isolated_config(monkeypatch):
    monkeypatch.setattr(
        load_config, "CONFIG_TOML", {"common": {"key": "k", "secret": "s"}}
    )
    monkeypatch.setattr(load_config, "CONFIG_FILE", "my.toml")
    monkeypatch.setattr(load_config, "CONFIG_SOURCES", {})
    for var in (YD_KEY, YD_SECRET, YD_NAMESPACE, "YD_TAG", "YD_URL", "YD_READ_TIMEOUT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(load_config, "config_file_explicitly_selected", lambda: False)
    monkeypatch.setattr(
        load_config, "add_substitutions_without_overwriting", lambda subs: None
    )
    monkeypatch.setattr(load_config, "register_dc_substitutions", lambda: None)


def _configure(monkeypatch, source: str) -> None:
    if source == "environment":
        monkeypatch.setenv(YD_NAMESPACE, "team-*")
    else:
        monkeypatch.setattr(
            load_config,
            "CONFIG_TOML",
            {"common": {"key": "k", "secret": "s", "namespace": "team-*"}},
        )


@pytest.mark.parametrize(
    "source, named",
    [("environment", "environment (YD_NAMESPACE)"), ("file", "config file (my.toml)")],
)
def test_a_configured_pattern_is_refused_by_other_commands(
    source, named, isolated_config, monkeypatch, capsys
):
    _configure(monkeypatch, source)
    monkeypatch.setattr(load_config, "_ARGS", _config_args(allowed=False))
    with pytest.raises(SystemExit) as excinfo:
        load_config.load_config_common()
    assert excinfo.value.code == ExitCode.CONFIGURATION
    captured = capsys.readouterr()
    output = " ".join((captured.out + captured.err).split())
    assert (
        f"The namespace 'team-*' ({named}) is a pattern: only 'yd list' and the"
        " 'list' verbs take one" in output
    )


def test_a_property_override_pattern_is_refused(isolated_config, monkeypatch):
    # The override as applied to the file's values as it loaded
    _configure(monkeypatch, "file")
    monkeypatch.setattr(
        load_config,
        "_ARGS",
        _config_args(allowed=False, property_overrides=["common.namespace=team-*"]),
    )
    with pytest.raises(SystemExit) as excinfo:
        load_config.load_config_common()
    assert excinfo.value.code == ExitCode.CONFIGURATION


@pytest.mark.parametrize("source", ["environment", "file"])
def test_a_configured_pattern_is_kept_for_yd_list(source, isolated_config, monkeypatch):
    _configure(monkeypatch, source)
    monkeypatch.setattr(load_config, "_ARGS", _config_args(allowed=True))
    assert load_config.load_config_common().namespace == "team-*"


def test_a_reporting_command_is_given_the_pattern_rather_than_an_exit(
    isolated_config, monkeypatch
):
    # yd-doctor and yd-variables report the configuration and act on nothing
    _configure(monkeypatch, "environment")
    monkeypatch.setattr(load_config, "_ARGS", _config_args(allowed=True))
    assert load_config.load_config_common(strict=False).namespace == "team-*"


def test_a_pattern_is_refused_without_credentials_required_too(
    isolated_config, monkeypatch
):
    # '--validate' loads [common] non-strictly; it must refuse what the real
    # run refuses, not pass it
    _configure(monkeypatch, "environment")
    monkeypatch.setattr(load_config, "_ARGS", _config_args(allowed=False))
    with pytest.raises(SystemExit) as excinfo:
        load_config.load_config_common(strict=False)
    assert excinfo.value.code == ExitCode.CONFIGURATION


def test_the_namespace_variable_alone_is_refused_too(
    isolated_config, monkeypatch, capsys
):
    # The data client commands register {{namespace}} without loading
    # [common]: a pattern there would build a literal 'team-*/...' path
    _configure(monkeypatch, "environment")
    monkeypatch.setattr(load_config, "_ARGS", _config_args(allowed=False))
    with pytest.raises(SystemExit) as excinfo:
        load_config._load_namespace_and_tag()
    assert excinfo.value.code == ExitCode.CONFIGURATION
    captured = capsys.readouterr()
    assert (
        "The namespace 'team-*' (environment (YD_NAMESPACE)) is a pattern"
        in " ".join((captured.out + captured.err).split())
    )


@pytest.mark.parametrize(
    "command, argv, refused",
    [
        ("yd-cancel", [], True),
        ("yd workrequirement submit", ["--validate", "wr.json"], True),
        ("yd data upload", ["f.txt"], True),
        ("yd-list", ["work-requirements"], False),
        ("yd workerpool list", ["worker-pools"], False),
        ("yd-doctor", [], False),
        ("yd-variables", [], False),
    ],
)
def test_which_commands_refuse_a_configured_pattern(command, argv, refused):
    assert CLIParser(command=command, argv=argv).namespace_pattern_refused is refused


# --- Expansion (Task 3) ------------------------------------------------------


def _client(
    all_readable: bool = False,
    readable: list[str] | None = None,
    listed: list[str] | None = None,
) -> MagicMock:
    client = MagicMock()
    client.application_client.get_application_details.return_value = SimpleNamespace(
        allNamespacesReadable=all_readable, readableNamespaces=readable or []
    )
    client.namespaces_client.get_namespaces.return_value.list_all.return_value = [
        SimpleNamespace(namespace=n) for n in listed or []
    ]
    return client


@pytest.fixture(autouse=True)
def _fresh_caches():
    entity_utils.get_application_details.cache_clear()
    entity_utils.clear_namespace_cache()
    yield
    entity_utils.get_application_details.cache_clear()
    entity_utils.clear_namespace_cache()


def test_a_pattern_is_matched_against_the_readable_namespaces_without_a_search():
    client = _client(readable=["team-b", "team-a", "other"])
    assert entity_utils.search_namespaces(client, "team-*") == ["team-a", "team-b"]
    client.namespaces_client.get_namespaces.assert_not_called()


def test_a_global_reader_searches_the_namespaces_once():
    client = _client(all_readable=True, listed=["team-c", "xteam-b", "team-a"])
    assert entity_utils.search_namespaces(client, "team-*") == ["team-a", "team-c"]
    entity_utils.search_namespaces(client, "team-*")
    assert client.namespaces_client.get_namespaces.call_count == 1
    search = client.namespaces_client.get_namespaces.call_args.args[0]
    assert search.namespaceContains == "team-"


def test_a_pattern_without_literals_sends_no_namespace_contains():
    client = _client(all_readable=True, listed=["b-1", "a-1", "c"])
    assert entity_utils.search_namespaces(client, "[ab]*") == ["a-1", "b-1"]
    search = client.namespaces_client.get_namespaces.call_args.args[0]
    assert search.namespaceContains is None


@pytest.mark.parametrize("all_readable", [True, False])
def test_a_pattern_matching_nothing_raises(all_readable):
    client = _client(all_readable=all_readable, readable=["a"], listed=["a"])
    with pytest.raises(entity_utils.NoMatchingNamespaces) as excinfo:
        entity_utils.search_namespaces(client, "zz-*")
    assert str(excinfo.value) == "No namespaces match 'zz-*'"
    assert excinfo.value.pattern == "zz-*"
    assert not isinstance(excinfo.value, NotFoundError)


def test_a_plain_namespace_is_unchanged():
    client = _client(all_readable=True, listed=["dev", "dev-team"])
    assert entity_utils.search_namespaces(client, "dev") == ["dev"]
    client.namespaces_client.get_namespaces.assert_not_called()


def test_the_scope_phrase_names_the_matches_and_the_pattern():
    client = _client(readable=["team-a", "team-b", "other"])
    assert (
        entity_utils.namespace_scope(client, "team-*")
        == "in namespaces 'team-a', 'team-b' (matching 'team-*')"
    )
    assert (
        entity_utils.namespace_scope(client, "team-a*")
        == "in namespace 'team-a' (matching 'team-a*')"
    )


def test_the_scope_phrase_is_capped():
    names = [f"team-{i:02}" for i in range(NAMESPACE_SCOPE_SHOWN + 2)]
    phrase = entity_utils.namespace_scope(_client(readable=names), "team-*")
    assert phrase.startswith("in namespaces 'team-00', ")
    assert (
        f"'team-{NAMESPACE_SCOPE_SHOWN - 1:02}' and 2 more (matching 'team-*')"
        in phrase
    )
    assert f"'team-{NAMESPACE_SCOPE_SHOWN:02}'" not in phrase


@pytest.mark.parametrize(
    "namespace, item, expected",
    [
        (None, "anything", True),
        ("", "anything", True),
        ("dev", "dev", True),
        ("dev", "dev-team", False),
        ("dev*", "dev-team", True),
        ("dev*", "prod", False),
        ("dev*", None, False),
    ],
)
def test_in_namespace_scope(namespace, item, expected):
    client = _client(readable=["dev", "dev-team", "prod"])
    assert entity_utils.in_namespace_scope(client, namespace, item) is expected


def test_a_pattern_matching_too_many_namespaces_is_refused():
    names = [f"team-{i:03}" for i in range(NAMESPACE_PATTERN_MAX_MATCHES + 1)]
    client = _client(readable=[*names, "other"])
    with pytest.raises(entity_utils.TooManyNamespaces) as excinfo:
        entity_utils.search_namespaces(client, "team-*")
    assert str(excinfo.value) == (
        f"The namespace pattern 'team-*' matches {NAMESPACE_PATTERN_MAX_MATCHES + 1}"
        f" namespaces, more than the {NAMESPACE_PATTERN_MAX_MATCHES} a search can"
        " name: narrow the pattern, or give -n '' for every namespace"
    )


def test_the_limit_itself_is_allowed():
    names = [f"team-{i:03}" for i in range(NAMESPACE_PATTERN_MAX_MATCHES)]
    assert entity_utils.search_namespaces(_client(readable=names), "team-*") == names


def test_a_global_reader_matching_every_namespace_searches_unscoped():
    names = [f"ns-{i:03}" for i in range(NAMESPACE_PATTERN_MAX_MATCHES + 5)]
    client = _client(all_readable=True, listed=names)
    assert entity_utils.search_namespaces(client, "*") is None
    assert (
        entity_utils.namespace_scope(client, "*") == "in all namespaces (matching '*')"
    )
    assert entity_utils.in_namespace_scope(client, "*", "ns-000") is True


def test_a_limited_reader_matching_every_namespace_is_still_scoped():
    client = _client(readable=["a", "b"])
    assert entity_utils.search_namespaces(client, "*") == ["a", "b"]


# --- The listers (Task 4) ----------------------------------------------------


def _list_args(entity_type: str, **overrides) -> MagicMock:
    values = dict(
        count_only=False,
        json_output=False,
        details=False,
        ids_only=False,
        quiet=True,
        status_filter=None,
        active_only=False,
        entity_type=entity_type,
        name_glob=None,
        namespace="zz-*",
        tag=None,
        auto_select_all=False,
        strip_ids=False,
        substitute_ids=False,
        output_file=None,
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
    values.update(overrides)
    return MagicMock(**values)


def _list_ctx(args, client, namespace: str) -> RunContext:
    return RunContext(
        args=args, config=MagicMock(namespace=namespace, name_tag=""), client=client
    )


@pytest.mark.parametrize(
    "entity_type",
    [
        ET_WORK_REQUIREMENTS,
        ET_TASK_GROUPS,
        ET_TASKS,
        ET_WORKER_POOLS,
        ET_NODES,
        ET_WORKERS,
        ET_COMPUTE_REQUIREMENTS,
        ET_INSTANCES,
        ET_COMPUTE_SOURCES,
        ET_COMPUTE_REQUIREMENT_TEMPLATES,
        ET_COMPUTE_SOURCE_TEMPLATES,
        ET_IMAGE_FAMILIES,
        ET_NAMESPACE_POLICIES,
    ],
)
@pytest.mark.parametrize("name_glob", [None, "x*", "zz-*/x*"])
def test_a_pattern_matching_nothing_is_an_empty_listing(entity_type, name_glob):
    import yellowdog_cli.list as yd_list

    client = _client(readable=["a"])
    ctx = _list_ctx(_list_args(entity_type, name_glob=name_glob), client, "zz-*")
    with patch.object(yd_list, "_print_empty") as empty:
        yd_list.list_entities(ctx)
    empty.assert_called_once_with(ctx, "No namespaces match 'zz-*'")
    # Nothing but the Application's details was asked of the Platform
    asked = {
        call[0].split(".")[0]
        for call in client.mock_calls
        if not call[0].startswith("__")  # the lru_caches hash the client
    }
    assert asked <= {"application_client"}


def _wp(namespace: str, id_: str) -> SimpleNamespace:
    return SimpleNamespace(namespace=namespace, status=None, name="wp", id=id_)


def _listed_worker_pools(namespace: str, readable: list[str], found: list) -> list[str]:
    import yellowdog_cli.list as yd_list

    ctx = _list_ctx(
        _list_args(ET_WORKER_POOLS, namespace=namespace, json_output=True),
        _client(readable=readable),
        namespace,
    )
    with (
        patch.object(yd_list, "get_worker_pool_summaries", return_value=found),
        patch.object(yd_list, "sorted_objects", side_effect=lambda o: o),
        patch.object(yd_list, "_print_json_or_count") as printed,
        patch.object(yd_list, "print_info"),
        patch.object(yd_list, "_print_empty"),
    ):
        yd_list.list_entities(ctx)
    return [wp.id for wp in printed.call_args.args[1]] if printed.called else []


def test_worker_pools_in_a_plain_namespace_are_not_its_namesakes():
    found = [_wp("dev", "a"), _wp("dev-team", "b")]
    assert _listed_worker_pools("dev", ["dev", "dev-team"], found) == ["a"]


def test_worker_pools_in_a_pattern_are_those_in_the_matched_namespaces():
    found = [_wp("dev", "a"), _wp("dev-team", "b"), _wp("prod", "c")]
    assert _listed_worker_pools("dev*", ["dev", "dev-team", "prod"], found) == [
        "a",
        "b",
    ]


@pytest.mark.parametrize(
    "given, searched",
    [
        (None, ["a", "team-a", "team-b"]),
        ("team-a", ["team-a"]),
        ("team-*", ["team-a", "team-b"]),
    ],
)
def test_namespace_policies_honour_the_namespace_option(given, searched):
    import yellowdog_cli.list as yd_list

    client = _client(readable=["a", "team-a", "team-b"])
    client.namespaces_client.get_namespace_policies.return_value.list_all.return_value = []
    # The configured namespace alone (no '-n') scopes nothing, as before
    ctx = _list_ctx(
        _list_args(ET_NAMESPACE_POLICIES, namespace=given), client, given or "default"
    )
    with (
        patch.object(yd_list, "configure_output"),
        patch.object(yd_list, "_print_empty"),
    ):
        yd_list.list_entities(ctx)
    search = client.namespaces_client.get_namespace_policies.call_args.args[0]
    assert search.namespaces == searched


# --- '--name ns-*/name-*' (Task 5) -------------------------------------------


def test_resolve_name_glob_still_refuses_a_namespace_pattern_by_default():
    with pytest.raises(
        ValueError, match="Wildcards are not allowed in the namespace part"
    ):
        entity_utils.resolve_name_glob("team-*/x", None)
    with pytest.raises(
        ValueError, match="Wildcards are not allowed in the namespace part"
    ):
        entity_utils.resolve_name_glob("x", "team-*")


def test_resolve_name_glob_takes_one_when_allowed():
    assert entity_utils.resolve_name_glob(
        "team-*/nightly-*", None, allow_namespace_pattern=True
    ) == ("team-*", "nightly-*")
    assert entity_utils.resolve_name_glob(
        "nightly-*", "team-*", allow_namespace_pattern=True
    ) == ("team-*", "nightly-*")


def test_yd_list_takes_a_pattern_in_the_namespace_part_of_its_name():
    import yellowdog_cli.list as yd_list

    found = [
        SimpleNamespace(name="nightly-1", id="a", namespace="team-a", status=None),
        SimpleNamespace(name="other", id="b", namespace="team-b", status=None),
    ]
    captured = {}

    def fetch(client, **kwargs):
        captured.update(kwargs)
        return found

    args = _list_args(
        ET_WORK_REQUIREMENTS,
        name_glob="team-*/nightly-*",
        namespace=None,
        json_output=True,
    )
    ctx = _list_ctx(args, _client(readable=["team-a", "team-b", "x"]), "default")
    with (
        patch.object(
            yd_list, "get_filtered_work_requirement_summaries", side_effect=fetch
        ),
        patch.object(yd_list, "sorted_objects", side_effect=lambda o: o),
        patch.object(yd_list, "_apply_status_filter", side_effect=lambda _ctx, o: o),
        patch.object(yd_list, "_print_json_or_count") as printed,
        patch.object(yd_list, "print_info") as info,
    ):
        yd_list.list_entities(ctx)
    assert captured["namespace"] == "team-*"
    assert [w.id for w in printed.call_args.args[1]] == ["a"]
    assert (
        "in namespaces 'team-a', 'team-b' (matching 'team-*')"
        in info.call_args_list[0].args[0]
    )


# --- '--within' under a namespace pattern (Task 6) ---------------------------

_WR_ID = "ydid:workreq:000000:11111111-2222-3333-4444-555555555555"


@pytest.mark.parametrize("target", ["wr1", "/wr1"])
@pytest.mark.parametrize("entity_type", [ET_TASK_GROUPS, ET_NODES, ET_INSTANCES])
def test_a_within_target_naming_no_namespace_is_refused(target, entity_type, capsys):
    import yellowdog_cli.list as yd_list

    client = _client(readable=["team-a"])
    args = _list_args(entity_type, namespace="team-*", within_targets=[target])
    with pytest.raises(SystemExit) as excinfo:
        yd_list.list_entities(_list_ctx(args, client, "team-*"))
    assert excinfo.value.code == ExitCode.USAGE
    captured = capsys.readouterr()
    assert (
        f"--within '{target}' names no namespace: with the namespace pattern"
        " 'team-*', give 'namespace/name' or an ID"
    ) in " ".join((captured.out + captured.err).split())
    assert not [c for c in client.mock_calls if not c[0].startswith("__")]


def test_a_qualified_within_target_is_read_as_namespace_and_name():
    found = SimpleNamespace(id=_WR_ID, name="wr1")
    with patch.object(
        work_targets,
        "_work_requirement_named",
        side_effect=lambda c, name, ns: (
            found if (name, ns) == ("wr1", "team-a") else None
        ),
    ) as named:
        target = work_targets.resolve_named_target(
            MagicMock(), "team-a/wr1", "team-*", qualified_only=True
        )
    assert target.work_requirement is found and target.task_group is None
    # Never Work Requirement 'team-a' in the pattern's namespaces
    assert all(call.args[1:] != ("team-a", "team-*") for call in named.call_args_list)


def test_a_qualified_reading_of_a_bare_name_is_malformed():
    with pytest.raises(work_targets.MalformedTarget):
        work_targets.resolve_named_target(
            MagicMock(), "wr1", "team-*", qualified_only=True
        )


def test_without_qualified_only_wr_slash_tg_is_still_a_task_group():
    wr = SimpleNamespace(id=_WR_ID, name="wr1")
    tg = SimpleNamespace(name="tg1")
    with (
        patch.object(work_targets, "_work_requirement_named", return_value=wr),
        patch.object(work_targets, "_task_group_named", return_value=tg),
    ):
        target = work_targets.resolve_named_target(MagicMock(), "wr1/tg1", "default")
    assert target.task_group is tg


def test_an_id_within_target_is_taken_under_a_pattern():
    import yellowdog_cli.list as yd_list

    args = _list_args(
        ET_TASK_GROUPS, namespace="team-*", within_targets=[_WR_ID], json_output=True
    )
    ctx = _list_ctx(args, _client(readable=["team-a"]), "team-*")
    with (
        patch.object(
            yd_list, "get_task_groups_from_wr_by_id", return_value=[]
        ) as fetched,
        patch.object(yd_list, "print_info"),
        patch.object(yd_list, "_print_empty"),
        patch.object(yd_list, "_print_json_or_count"),
    ):
        yd_list.list_entities(ctx)
    fetched.assert_called()


# --- Listings held to the namespaces a pattern matched (final review) --------


@pytest.mark.parametrize(
    "entity_type, fetch",
    [
        (ET_WORK_REQUIREMENTS, "get_filtered_work_requirement_summaries"),
        (ET_COMPUTE_REQUIREMENTS, "get_compute_requirement_summaries"),
        (ET_COMPUTE_REQUIREMENT_TEMPLATES, "get_compute_requirement_templates"),
        (ET_COMPUTE_SOURCE_TEMPLATES, "get_compute_source_templates"),
    ],
)
@pytest.mark.parametrize("namespace, kept", [("team-?", ["a"]), ("team-a", ["a", "b"])])
def test_a_pattern_listing_keeps_only_the_matched_namespaces(
    entity_type, fetch, namespace, kept
):
    import yellowdog_cli.list as yd_list

    found = [
        SimpleNamespace(
            name="x", id="a", namespace="team-a", status=None, provider=None
        ),
        # A search matching the namespace as a substring would send this too
        SimpleNamespace(
            name="y", id="b", namespace="team-ab", status=None, provider=None
        ),
    ]
    args = _list_args(entity_type, namespace=namespace, json_output=True)
    ctx = _list_ctx(args, _client(readable=["team-a", "team-ab"]), namespace)
    with (
        patch.object(yd_list, fetch, return_value=found),
        patch.object(yd_list, "sorted_objects", side_effect=lambda o: o),
        patch.object(yd_list, "_apply_status_filter", side_effect=lambda _ctx, o: o),
        patch.object(yd_list, "_emit") as emit,
        patch.object(yd_list, "_print_json_or_count") as printed,
        patch.object(yd_list, "print_info"),
        patch.object(yd_list, "_print_empty"),
    ):
        yd_list.list_entities(ctx)
    shown = (emit.call_args or printed.call_args).args[1]
    assert [item.id for item in shown] == kept


def test_a_limited_reader_matching_every_readable_namespace_is_searched_as_with_none():
    # As '-n ""' scopes it: every readable namespace, however many, never
    # refused for matching more than the limit
    names = [f"ns-{i:03}" for i in range(NAMESPACE_PATTERN_MAX_MATCHES + 50)]
    client = _client(readable=names)
    assert entity_utils.search_namespaces(client, "*") == names
    assert entity_utils.search_namespaces(client, "") == names


def test_a_limited_reader_matching_too_many_but_not_all_is_still_refused():
    names = [f"ns-{i:03}" for i in range(NAMESPACE_PATTERN_MAX_MATCHES + 50)]
    client = _client(readable=[*names, "other"])
    with pytest.raises(entity_utils.TooManyNamespaces):
        entity_utils.search_namespaces(client, "ns-*")
