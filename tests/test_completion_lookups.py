"""
Tests for Tab completion's Platform lookups (utils/completion_lookups.py):
what is searched for, what is offered and how it is described, the cache,
and that every failure offers nothing rather than raising.
"""

from datetime import datetime, timezone
from itertools import count
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from yellowdog_cli.utils import completion_cache, completion_lookups
from yellowdog_cli.utils import entity_utils as entity_utils_module
from yellowdog_cli.utils.completion import LookupRequest
from yellowdog_cli.utils.completion_targets import LOOKUPS, Lookup
from yellowdog_cli.utils.config_types import ConfigCommon
from yellowdog_cli.utils.entity_names import (
    ET_COMPUTE_REQUIREMENTS,
    ET_WORK_REQUIREMENTS,
    ET_WORKER_POOLS,
)
from yellowdog_cli.utils.limits import LOOKUP_MAX_ITEMS

COMMON = ConfigCommon(
    key="key-id",
    secret="secret",
    namespace="ns",
    name_tag="pwt",
    url="https://api.example",
    use_pac=False,
)
_CREATED = count(1)


def _summary(name, status, *, type_=None, id_=None):
    created = next(_CREATED)
    return SimpleNamespace(
        id=id_ or f"ydid:x:000000:{name}",
        name=name,
        status=SimpleNamespace(name=status),
        type=type_,
        createdTime=datetime.fromtimestamp(created, tz=timezone.utc),
    )


def _client(summaries):
    """
    A client whose searches all yield 'summaries', recording the search.
    """
    client = MagicMock()
    for search in (
        client.work_client.get_work_requirements,
        client.worker_pool_client.get_worker_pools,
        client.compute_client.get_compute_requirement_summaries,
    ):
        search.return_value.slice.side_effect = lambda reference: SimpleNamespace(
            items=list(summaries), nextSliceId=None
        )
        search.return_value.iterate.side_effect = AssertionError("one page only")
    return client


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """
    A cache of the test's own, every namespace readable, and the
    configuration loaded as COMMON, unless a test says otherwise.
    """
    monkeypatch.setattr(completion_cache, "_temp_root", lambda: tmp_path)
    monkeypatch.setattr(
        entity_utils_module,
        "get_application_details",
        lambda client: SimpleNamespace(allNamespacesReadable=True),
    )
    monkeypatch.setattr(completion_lookups, "_load_common", lambda settings: COMMON)


def _request(
    lookup: Lookup, current: str = "", given: tuple[str, ...] = ()
) -> LookupRequest:
    return LookupRequest(lookup, current, {}, given)


def _offered(monkeypatch, lookup, summaries, current=""):
    client = _client(summaries)
    monkeypatch.setattr(completion_lookups, "_client", lambda common: client)
    return completion_lookups.candidates(_request(lookup, current)), client


CANCEL = LOOKUPS[("yd workrequirement cancel", "work_requirements")]
# IDs described by name and status, as an Allowance is offered: no verb of
# this type offers them, so the lookup is made here
SHOW = Lookup(ET_WORK_REQUIREMENTS, ids=True, statuses=None)
SHUTDOWN = LOOKUPS[("yd workerpool shutdown", "worker_pool_nodes_list")]
TOKEN = LOOKUPS[("yd workerpool token", "worker_pools")]
TERMINATE = LOOKUPS[
    ("yd computerequirement terminate", "compute_reqs_instances_or_nodes")
]


def test_names_are_offered_with_their_status_newest_first(monkeypatch):
    offered, _ = _offered(
        monkeypatch, CANCEL, [_summary("older", "RUNNING"), _summary("newer", "HELD")]
    )

    assert [(c.value, c.description) for c in offered] == [
        ("newer", "HELD"),
        ("older", "RUNNING"),
    ]


def test_only_names_beginning_with_the_word_are_offered(monkeypatch):
    offered, _ = _offered(
        monkeypatch,
        CANCEL,
        [_summary("pwt-a", "RUNNING"), _summary("other", "RUNNING")],
        "pw",
    )

    assert [c.value for c in offered] == ["pwt-a"]


def test_ids_are_offered_described_by_name_and_status(monkeypatch):
    offered, _ = _offered(
        monkeypatch, SHOW, [_summary("run", "COMPLETED", id_="ydid:wrkreq:000000:a")]
    )

    assert [(c.value, c.description) for c in offered] == [
        ("ydid:wrkreq:000000:a", "run (COMPLETED)")
    ]


def test_ids_are_matched_on_the_id(monkeypatch):
    offered, _ = _offered(
        monkeypatch,
        SHOW,
        [_summary("a", "RUNNING", id_="ydid:wrkreq:000000:a")],
        "ydid:wrkreq:000000:b",
    )

    assert offered == ()


def test_a_name_used_twice_is_offered_once(monkeypatch):
    offered, _ = _offered(
        monkeypatch, CANCEL, [_summary("same", "RUNNING"), _summary("same", "HELD")]
    )

    assert [c.value for c in offered] == ["same"]


def test_the_search_is_scoped_as_the_command_scopes_it(monkeypatch):
    _, client = _offered(monkeypatch, CANCEL, [])

    (search,), _ = client.work_client.get_work_requirements.call_args
    assert search.namespaces == ["ns"]
    assert search.tag == "pwt"
    assert sorted(status.name for status in search.statuses) == [
        "FINISHING",
        "HELD",
        "RUNNING",
    ]


def test_any_status_searches_without_a_status_filter(monkeypatch):
    _, client = _offered(monkeypatch, SHOW, [])

    (search,), _ = client.work_client.get_work_requirements.call_args
    assert search.statuses is None


def test_compute_requirements_are_searched_by_tag(monkeypatch):
    _, client = _offered(monkeypatch, TERMINATE, [])

    (search,), _ = client.compute_client.get_compute_requirement_summaries.call_args
    assert search.tag == "pwt"
    assert "TERMINATED" not in {status.name for status in search.statuses}


def test_worker_pools_are_those_with_the_tag_in_their_name(monkeypatch):
    # As 'yd-workerpool list' and a no-names 'shutdown' select them
    offered, client = _offered(
        monkeypatch,
        SHUTDOWN,
        [_summary("pwt-pool", "RUNNING"), _summary("on-premise", "EMPTY")],
    )

    assert [c.value for c in offered] == ["pwt-pool"]
    (search,), _ = client.worker_pool_client.get_worker_pools.call_args
    assert search.name == "pwt"
    assert search.namespaces == ["ns"]


def test_worker_pools_with_another_tag_are_another_cache_entry(monkeypatch):
    _offered(monkeypatch, SHUTDOWN, [_summary("pwt-pool", "RUNNING")])
    monkeypatch.setattr(
        completion_lookups,
        "_load_common",
        lambda settings: ConfigCommon(
            key="key-id",
            secret="secret",
            namespace="ns",
            name_tag="",
            url="https://api.example",
            use_pac=False,
        ),
    )

    offered, client = _offered(
        monkeypatch,
        SHUTDOWN,
        [_summary("pwt-pool", "RUNNING"), _summary("on-premise", "EMPTY")],
    )

    assert client.worker_pool_client.get_worker_pools.called
    assert sorted(c.value for c in offered) == ["on-premise", "pwt-pool"]


def test_token_offers_configured_worker_pools_only(monkeypatch):
    offered, _ = _offered(
        monkeypatch,
        TOKEN,
        [
            _summary("pwt-c", "RUNNING", type_="co.yellowdog.ConfiguredWorkerPool"),
            _summary("pwt-p", "RUNNING", type_="co.yellowdog.ProvisionedWorkerPool"),
        ],
    )

    assert [c.value for c in offered] == ["pwt-c"]


def test_one_page_of_the_cap_is_requested(monkeypatch):
    # One request, however small the server's default page: a page at a
    # time could cost several round trips inside the Tab's two seconds
    _, client = _offered(monkeypatch, CANCEL, [])

    search = client.work_client.get_work_requirements.return_value
    ((reference,), _) = search.slice.call_args
    assert search.slice.call_count == 1
    assert reference.size == LOOKUP_MAX_ITEMS
    assert reference.sliceId is None


def test_a_page_with_no_items_offers_nothing(monkeypatch):
    client = MagicMock()
    client.work_client.get_work_requirements.return_value.slice.return_value = (
        SimpleNamespace(items=None, nextSliceId=None)
    )
    monkeypatch.setattr(completion_lookups, "_client", lambda common: client)

    assert completion_lookups.candidates(_request(CANCEL)) == ()


def test_a_second_lookup_is_answered_from_the_cache(monkeypatch):
    first, _ = _offered(monkeypatch, CANCEL, [_summary("cached", "RUNNING")])

    def no_client(common):
        raise AssertionError("the Platform was asked again")

    monkeypatch.setattr(completion_lookups, "_client", no_client)
    second = completion_lookups.candidates(_request(CANCEL))

    assert [c.value for c in second] == [c.value for c in first] == ["cached"]


def test_another_status_set_is_another_cache_entry(monkeypatch):
    _offered(monkeypatch, CANCEL, [_summary("running", "RUNNING")])

    offered, client = _offered(monkeypatch, SHOW, [_summary("done", "COMPLETED")])

    assert client.work_client.get_work_requirements.called
    assert [c.description for c in offered] == ["done (COMPLETED)"]


def test_the_client_is_closed(monkeypatch):
    _, client = _offered(monkeypatch, CANCEL, [])

    client.close.assert_called_once()


def test_a_failing_search_offers_nothing(monkeypatch):
    client = MagicMock()
    client.work_client.get_work_requirements.side_effect = RuntimeError("401")
    monkeypatch.setattr(completion_lookups, "_client", lambda common: client)

    assert completion_lookups.candidates(_request(CANCEL)) == ()


def test_no_configuration_offers_nothing(monkeypatch):
    monkeypatch.setattr(completion_lookups, "_load_common", lambda settings: None)

    def no_client(common):
        raise AssertionError("no client without a configuration")

    monkeypatch.setattr(completion_lookups, "_client", no_client)

    assert completion_lookups.candidates(_request(CANCEL)) == ()


@pytest.mark.parametrize(
    "entity",
    [ET_WORK_REQUIREMENTS, ET_WORKER_POOLS, ET_COMPUTE_REQUIREMENTS],
)
def test_every_entity_can_be_looked_up(monkeypatch, entity):
    offered, _ = _offered(
        monkeypatch,
        Lookup(entity, ids=False, statuses=None),
        [_summary("pwt-x", "RUNNING")],
    )

    assert [c.value for c in offered] == ["pwt-x"]


# The configuration, loaded for real: load_config keeps the first command line
# it is given, which in the test process is pytest's, so each runs in a fresh
# interpreter, in a directory of its own.

_LOAD = """
import json, sys
from yellowdog_cli.utils.completion import complete
from yellowdog_cli.utils.completion_lookups import _load_common
request = complete(json.loads(sys.argv[1]), "").lookup
common = _load_common(request.settings)
print(json.dumps(None if common is None else [common.namespace, common.name_tag, common.key]))
"""


def _load_in(directory, words, monkeypatch):
    import json
    import subprocess
    import sys

    for name in ("YD_KEY", "YD_SECRET", "YD_NAMESPACE", "YD_TAG", "YD_URL"):
        monkeypatch.delenv(name, raising=False)
    result = subprocess.run(
        [sys.executable, "-c", _LOAD, json.dumps(words)],
        cwd=directory,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_configuration_file_and_typed_options_are_used(tmp_path, monkeypatch):
    (tmp_path / "config.toml").write_text(
        '[common]\nkey = "file-key"\nsecret = "s"\nnamespace = "file-ns"\ntag = "file-tag"\n',
        encoding="utf-8",
    )

    assert _load_in(tmp_path, ["yd", "wr", "cancel"], monkeypatch) == [
        "file-ns",
        "file-tag",
        "file-key",
    ]
    assert _load_in(tmp_path, ["yd", "wr", "cancel", "-n", "typed"], monkeypatch) == [
        "typed",
        "file-tag",
        "file-key",
    ]


def test_a_missing_configuration_file_offers_nothing(tmp_path, monkeypatch):
    words = ["yd", "wr", "cancel", "-c", "missing.toml"]

    assert _load_in(tmp_path, words, monkeypatch) is None


def test_no_credentials_offers_nothing(tmp_path, monkeypatch):
    (tmp_path / "config.toml").write_text(
        '[common]\nnamespace = "ns"\n', encoding="utf-8"
    )

    assert _load_in(tmp_path, ["yd", "wr", "cancel"], monkeypatch) is None


def test_a_name_typed_already_is_not_offered_again(monkeypatch):
    client = _client([_summary("one", "RUNNING"), _summary("two", "RUNNING")])
    monkeypatch.setattr(completion_lookups, "_client", lambda common: client)

    offered = completion_lookups.candidates(_request(CANCEL, given=("one",)))

    assert [c.value for c in offered] == ["two"]


def test_an_id_with_no_status_is_described_by_its_name_alone(monkeypatch):
    summary = _summary("unknown", "RUNNING", id_="ydid:wrkreq:000000:u")
    summary.status = None
    offered, _ = _offered(monkeypatch, SHOW, [summary])

    assert [c.description for c in offered] == ["unknown"]


@pytest.mark.parametrize("items", [[1, "x"], [None], [{"id": 1, "name": ["a"]}]])
def test_cached_items_of_the_wrong_shape_offer_nothing(monkeypatch, items):
    monkeypatch.setattr(completion_cache, "read", lambda key: items)

    assert completion_lookups.candidates(_request(CANCEL)) == ()


def test_finding_nothing_is_not_cached(monkeypatch):
    # Nothing found is the answer likeliest to be stale a moment later (a
    # Work Requirement just submitted), so the next Tab asks again
    _offered(monkeypatch, CANCEL, [])

    offered, client = _offered(monkeypatch, CANCEL, [_summary("submitted", "RUNNING")])

    assert client.work_client.get_work_requirements.called
    assert [c.value for c in offered] == ["submitted"]


WITHIN_TASKS = LOOKUPS[("yd task list", "--within")]
WITHIN_NODES = LOOKUPS[("yd node list", "--within")]


def test_within_offers_names_in_the_namespace_whatever_their_tag(monkeypatch):
    # '--within' resolves a name in the namespace; the tag plays no part
    offered, client = _offered(
        monkeypatch, WITHIN_TASKS, [_summary("untagged-wr", "COMPLETED")]
    )
    assert [c.value for c in offered] == ["untagged-wr"]
    (search,), _ = client.work_client.get_work_requirements.call_args
    assert search.tag is None
    assert search.statuses is None


def test_within_offers_worker_pools_whatever_their_name(monkeypatch):
    offered, client = _offered(
        monkeypatch, WITHIN_NODES, [_summary("on-premise", "RUNNING")]
    )
    assert [c.value for c in offered] == ["on-premise"]
    (search,), _ = client.worker_pool_client.get_worker_pools.call_args
    assert search.name is None


def test_within_after_a_slash_offers_the_work_requirements_task_groups(monkeypatch):
    client = _client([])
    monkeypatch.setattr(completion_lookups, "_client", lambda common: client)
    found = []

    def find(client, name, namespace, statuses):
        found.append((name, namespace))
        return SimpleNamespace(id="ydid:workreq:000000:w")

    monkeypatch.setattr(entity_utils_module, "find_work_requirement_by_name", find)
    monkeypatch.setattr(
        entity_utils_module,
        "get_task_groups_from_wr_by_id",
        lambda client, wr_id: [
            SimpleNamespace(
                id=f"{wr_id}:{i}", name=name, status=SimpleNamespace(name="RUNNING")
            )
            for i, name in enumerate(["tg-1", "tg-2", "other"], 1)
        ],
    )
    offered = completion_lookups.candidates(_request(WITHIN_TASKS, "ns2/my-wr/tg"))
    assert [(c.value, c.description) for c in offered] == [
        ("ns2/my-wr/tg-1", "RUNNING"),
        ("ns2/my-wr/tg-2", "RUNNING"),
    ]
    assert found == [("ns2/my-wr", "ns")]


def test_within_after_a_slash_naming_nothing_offers_nothing(monkeypatch):
    from yellowdog_cli.utils.exit_codes import NotFoundError

    def find(*args, **kwargs):
        raise NotFoundError("no")

    monkeypatch.setattr(completion_lookups, "_client", lambda common: _client([]))
    monkeypatch.setattr(entity_utils_module, "find_work_requirement_by_name", find)
    assert completion_lookups.candidates(_request(WITHIN_TASKS, "nope/")) == ()


def test_a_slash_is_only_a_task_group_for_a_lookup_that_has_them(monkeypatch):
    # A Worker Pool's 'namespace/name' is matched on the names found
    offered, _ = _offered(
        monkeypatch, WITHIN_NODES, [_summary("pool", "RUNNING")], "ns/po"
    )
    assert offered == ()


# Resources, after 'yd resource remove/show --type <type>'


def _resource(resource_type, monkeypatch, current="", **patches):
    from yellowdog_cli.utils.completion_targets import RESOURCE_LOOKUPS

    client = MagicMock()
    for attribute, value in patches.items():
        monkeypatch.setattr(entity_utils_module, attribute, value)
    monkeypatch.setattr(completion_lookups, "_client", lambda common: client)
    return client, lambda: completion_lookups.candidates(
        _request(RESOURCE_LOOKUPS[resource_type], current)
    )


def _named(name, **values):
    return SimpleNamespace(name=name, id=f"ydid:x:000000:{name}", **values)


def test_keyrings_are_offered_by_name(monkeypatch):
    client, offer = _resource("Keyring", monkeypatch, "te")
    client.keyring_client.get_keyrings.return_value.iterate.return_value = [
        _named("team-keys"),
        _named("other"),
    ]
    assert [c.value for c in offer()] == ["team-keys"]


def test_namespaces_and_their_policies_by_namespace(monkeypatch):
    client, offer = _resource("Namespace", monkeypatch)
    client.namespaces_client.get_namespaces.return_value.iterate.return_value = [
        SimpleNamespace(namespace="dev", id="n1")
    ]
    assert [c.value for c in offer()] == ["dev"]
    client, offer = _resource("NamespacePolicy", monkeypatch)
    client.namespaces_client.get_namespace_policies.return_value.iterate.return_value = [
        SimpleNamespace(namespace="dev")
    ]
    assert [c.value for c in offer()] == ["dev"]


def test_templates_in_the_configured_namespace(monkeypatch):
    _, offer = _resource(
        "ComputeSourceTemplate",
        monkeypatch,
        get_compute_source_templates=lambda client, namespace: [
            _named("here", namespace="ns"),
            _named("there", namespace="other"),
        ],
    )
    assert [c.value for c in offer()] == ["here"]


def test_attribute_definitions_of_the_type(monkeypatch):
    _, offer = _resource(
        "NumericAttributeDefinition",
        monkeypatch,
        get_user_attribute_definitions=lambda config: [
            {"name": "cores", "type": "co.yellowdog.NumericAttributeDefinition"},
            {"name": "gpu", "type": "co.yellowdog.StringAttributeDefinition"},
        ],
    )
    assert [c.value for c in offer()] == ["cores"]


def test_users_by_username_or_name(monkeypatch):
    from yellowdog_client.model import ExternalUser, InternalUser

    internal = InternalUser(username="pwt", name="Peter")
    external = ExternalUser(name="someone")
    _, offer = _resource(
        "InternalUser", monkeypatch, get_all_users=lambda client: [internal, external]
    )
    assert [c.value for c in offer()] == ["pwt", "someone"]


def test_allowances_by_id_described_by_description(monkeypatch):
    client, offer = _resource("Allowance", monkeypatch, "ydid:")
    client.allowances_client.get_allowances.return_value.iterate.return_value = [
        SimpleNamespace(id="ydid:allow:000000:a", description="gpu-hours")
    ]
    assert [(c.value, c.description) for c in offer()] == [
        ("ydid:allow:000000:a", "gpu-hours")
    ]


def test_credentials_after_their_keyring(monkeypatch):
    client, offer = _resource(
        "Credential",
        monkeypatch,
        "kr/a",
        get_keyring_summary_by_name=lambda client, name: (
            SimpleNamespace(id="k") if name == "kr" else None
        ),
    )
    client.keyring_client.get_keyring.return_value = SimpleNamespace(
        credentials=[SimpleNamespace(name="aws"), SimpleNamespace(name="gcp")]
    )
    assert [c.value for c in offer()] == ["kr/aws"]


def test_a_credential_before_its_slash_offers_keyrings(monkeypatch):
    client, offer = _resource("Credential", monkeypatch, "k")
    client.keyring_client.get_keyrings.return_value.iterate.return_value = [
        _named("kr")
    ]
    assert [c.value for c in offer()] == ["kr"]


def test_configured_worker_pools_whatever_their_name(monkeypatch):
    client, offer = _resource("ConfiguredWorkerPool", monkeypatch)
    pools = [
        _summary("on-premise", "RUNNING", type_="co.yellowdog.ConfiguredWorkerPool"),
        _summary("provisioned", "RUNNING", type_="co.yellowdog.ProvisionedWorkerPool"),
    ]
    client.worker_pool_client.get_worker_pools.return_value.slice.side_effect = (
        lambda reference: SimpleNamespace(items=pools, nextSliceId=None)
    )
    assert [c.value for c in offer()] == ["on-premise"]
