"""
'yd resource plan' over the whole resource corpus (tests/resources/), on
the fake Platform (resource_plan_platform.py) on which any change fails the
test: against a Platform holding nothing, every specification is 'create'
or fails as 'yd resource create' would; against a Platform holding what
each specification would make (the noise check), nothing is an update; and
neither changes anything.
"""

from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from resource_corpus import (
    CORPUS_DIR,
    corpus_files,
    install_variables,
    load_corpus_file,
    remove_variables,
    require_jsonnet,
)
from yellowdog_client.model import (
    RoleSummary,
)

import yellowdog_cli.utils.results as results_module
from tests.resource_plan_platform import (  # noqa: F401 (the fixture)
    CONFIG_KEY,
    CONFIG_SECRET,
    MUTATING_PREFIXES,
    PLAN_CHANGED_SOMETHING,
    FakePlatform,
    _clear_caches,
    _not_found,
    corpus_ctx,
    fails_for_want_of_a_namespace,
    hold,
    holding_all,
    platform,
)
from yellowdog_cli.utils import resource_creation, resource_planners
from yellowdog_cli.utils.debug_log import set_debug_logging
from yellowdog_cli.utils.entity_names import (
    RN_ALLOWANCE,
    RN_APPLICATION,
    RN_CONFIGURED_POOL,
    RN_CREDENTIAL,
    RN_EXTERNAL_USER,
    RN_GROUP,
    RN_IMAGE_FAMILY,
    RN_INTERNAL_USER,
    RN_REQUIREMENT_TEMPLATE,
    RN_SOURCE_TEMPLATE,
)
from yellowdog_cli.utils.exit_codes import ReportedFailure
from yellowdog_cli.utils.load_resources import RESOURCE_SOURCE_DIR
from yellowdog_cli.utils.resource_plan import PlanOptions, plan_resources
from yellowdog_cli.utils.resource_planners import CONFIGURED_POOL_EXISTS

require_jsonnet()

# The Platform's built-in roles the corpus's Groups name: there on any
# Platform, so held on the empty one too
BUILT_IN_ROLES = ("work-viewer", "work-manager")

# The types 'yd resource create' fails on a Platform holding nothing: a User
# is never created, and a Credential's Keyring is in another file
FAIL_AGAINST_NOTHING = {RN_CREDENTIAL, RN_INTERNAL_USER, RN_EXTERNAL_USER}

# What each type is planned as against itself, where not 'unchanged'
AGAINST_ITSELF = {
    RN_CREDENTIAL: "unknown",
    RN_ALLOWANCE: "create",
}

# A specification 'yd resource create' fails for want of a 'namespace'
# (resource_live.py), as the plan does, against nothing or itself
MISSING_NAMESPACE = "Expected property 'namespace' to be defined"

# An existing Application granted Keyrings is refused by the real run
# without '--regenerate-app-keys' (check_keyring_grants()), so the plan
# fails it too: the creator's own refusal, not a difference
KEYRING_GRANT_REFUSED = "granting it access to Keyring(s) needs its API key"


@pytest.fixture(autouse=True)
def _corpus_variables() -> Iterator[None]:
    previous = install_variables()
    try:
        yield
    finally:
        remove_variables(previous)


@pytest.fixture(autouse=True)
def _results() -> Iterator[None]:
    results_module.reset_results()
    yield
    results_module.reset_results()


def _hold_built_in_roles(platform: FakePlatform) -> None:
    for name in BUILT_IN_ROLES:
        platform.holding("Role", RoleSummary(name=name))


def _shown(record: dict) -> str:
    """
    A record in full, for a failed assertion's message.
    """
    return repr(record)


def _plan(
    platform: FakePlatform,
    specifications: list[dict],
    options: PlanOptions = PlanOptions(),
) -> list[dict]:
    """
    The plan's record of each specification, failures included (the
    ReportedFailure they end the plan with is what the records say).
    """
    results_module.reset_results()
    try:
        plan_resources(corpus_ctx(platform), specifications, options)
    except ReportedFailure:
        pass
    records = list(results_module._ITEMS)
    assert len(records) == len(specifications), records
    return records


# ---------------------------------------------------------------------------
# The tests
# ---------------------------------------------------------------------------


def _creators_error(specification: dict) -> str:
    """
    What 'yd resource create' fails a specification with, on a Platform
    holding only the built-in roles, which refuses a Credential's Keyring
    as not found.
    """
    empty = FakePlatform()
    _hold_built_in_roles(empty)
    _clear_caches()
    empty.client.keyring_client.put_credential_by_name.side_effect = _not_found()
    resource = deepcopy(specification)
    resource_type = resource.pop("resource")
    source_dir = resource.pop(RESOURCE_SOURCE_DIR, None)
    try:
        resource_creation._create_resource(
            corpus_ctx(empty), resource_type, resource, source_dir, False
        )
    except AssertionError:
        # The creator reached a change: it does not fail as the plan does
        raise
    except Exception as e:
        return str(e)
    finally:
        _clear_caches()
    raise AssertionError(f"'yd resource create' does not fail {specification}")


@pytest.mark.parametrize("path", corpus_files(), ids=lambda p: p.stem)
def test_against_nothing_everything_is_create_or_fails_as_create_would(
    path: Path, platform: FakePlatform
):
    _hold_built_in_roles(platform)
    specifications = load_corpus_file(path)
    records = _plan(platform, specifications)
    for specification, record in zip(specifications, records):
        if specification["resource"] in FAIL_AGAINST_NOTHING or (
            fails_for_want_of_a_namespace(path, specification)
        ):
            assert record["action"] == "failed", _shown(record)
            assert record["error"] == _creators_error(specification), _shown(record)
        else:
            assert record["action"] == "create", _shown(record)


@pytest.mark.parametrize("path", corpus_files(), ids=lambda p: p.stem)
def test_against_itself_everything_is_unchanged_or_unknown(
    path: Path, platform: FakePlatform
):
    _hold_built_in_roles(platform)
    specifications = holding_all(platform, path)
    records = _plan(platform, specifications)
    for specification, record in zip(specifications, records):
        resource_type = specification["resource"]
        if fails_for_want_of_a_namespace(path, specification):
            assert record["error"] == MISSING_NAMESPACE, _shown(record)
            continue
        if resource_type == RN_APPLICATION and specification.get("keyrings"):
            assert record["action"] == "failed", _shown(record)
            assert KEYRING_GRANT_REFUSED in record["error"], _shown(record)
            continue
        if resource_type == RN_CONFIGURED_POOL:
            # The Platform refuses a second pool of the name, as the real run
            # finds
            assert record["action"] == "failed", _shown(record)
            assert record["error"] == CONFIGURED_POOL_EXISTS, _shown(record)
            continue
        expected = AGAINST_ITSELF.get(resource_type, "unchanged")
        assert record["action"] == expected, _shown(record)
        assert "changes" not in record, _shown(record)


def test_the_plan_writes_nothing(
    platform: FakePlatform, monkeypatch: pytest.MonkeyPatch
):
    posted: list[tuple] = []

    def _recorded(*args: Any, **kwargs: Any) -> None:
        posted.append((args, kwargs))
        raise AssertionError(PLAN_CHANGED_SOMETHING)

    for module in (resource_creation, resource_planners):
        for name in ("post", "put"):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, _recorded)

    _hold_built_in_roles(platform)
    records: list[dict] = []
    for path in corpus_files():
        records += _plan(platform, load_corpus_file(path))
    for path in corpus_files():
        records += _plan(platform, holding_all(platform, path))

    mutations = [
        name
        for name, _, _ in platform.client.mock_calls
        if name.rsplit(".", 1)[-1].startswith(MUTATING_PREFIXES)
    ]
    assert mutations == []
    assert posted == []
    assert not [r for r in records if PLAN_CHANGED_SOMETHING in r.get("error", "")]


def _first(platform: FakePlatform, resource_type: str, wanted=lambda _: True) -> Any:
    return next(held for held in platform.held[resource_type] if wanted(held))


def _source_template_description(platform: FakePlatform) -> str:
    _first(platform, RN_SOURCE_TEMPLATE).description = "changed on the Platform"
    return "description"


def _requirement_template_user_data(platform: FakePlatform) -> str:
    template = _first(platform, RN_REQUIREMENT_TEMPLATE, lambda t: t.userData)
    template.userData = "#!/bin/sh\necho changed on the Platform"
    return "userData"


def _image_provider_id(platform: FakePlatform) -> str:
    family = _first(platform, RN_IMAGE_FAMILY, lambda f: f.imageGroups)
    group = next(g for g in family.imageGroups if g.images)
    image = group.images[0]
    image.providerImageId = "changed-on-the-platform"
    return f"imageGroups[name={group.name}].images[name={image.name}].providerImageId"


def _group_role_dropped(platform: FakePlatform) -> str:
    group = _first(platform, RN_GROUP, lambda g: g.roles)
    group.roles = group.roles[1:]
    return "roles"


@pytest.mark.parametrize(
    "file_name, change",
    [
        ("source-templates.jsonnet", _source_template_description),
        ("requirement-templates.jsonnet", _requirement_template_user_data),
        ("image-families.jsonnet", _image_provider_id),
        ("groups.jsonnet", _group_role_dropped),
    ],
    ids=lambda value: getattr(value, "__name__", value),
)
def test_one_property_changed_on_the_platform_is_one_update(
    file_name: str, change, platform: FakePlatform
):
    """
    The noise check is not vacuous: one held resource with one settable
    property changed is the plan's one 'update', with that one change.
    """
    _hold_built_in_roles(platform)
    specifications = holding_all(platform, CORPUS_DIR / file_name)
    path = change(platform)
    _clear_caches()
    updates = [r for r in _plan(platform, specifications) if r["action"] == "update"]
    assert len(updates) == 1, updates
    assert [c["path"] for c in updates[0]["changes"]] == [path], _shown(updates[0])


# The Credential fields that hold a secret, or a key's identity
SECRET_FIELDS = {
    "accessKeyId",
    "secretAccessKey",
    "sessionToken",
    "externalId",
    "key",
    "adminPassword",
    "accountKey",
    "serviceAccountKeyJson",
    "privateKey",
    "passphrase",
}


def _credential_secrets(specifications: list[dict]) -> set[str]:
    """
    The values of the corpus's Credentials' secret fields.
    """
    return {
        str(value)
        for specification in specifications
        if specification["resource"] == RN_CREDENTIAL
        for key, value in specification["credential"].items()
        if key in SECRET_FIELDS
    }


def test_the_debug_trace_of_a_plan_holds_no_secret(
    platform: FakePlatform, capsys: pytest.CaptureFixture[str]
):
    """
    The Credential and Application planners under '--debug', in process on
    the fake Platform: existing Credentials 'unknown', an existing
    Application granted a Keyring with its key regenerated, and a new one;
    neither the output nor the trace holds a credential's secret or the
    configured key and secret.
    """
    credentials = holding_all(platform, CORPUS_DIR / "credentials.jsonnet")
    applications = load_corpus_file(CORPUS_DIR / "applications.jsonnet")
    for specification in applications:
        if not specification["name"].endswith("-application-min"):
            hold(platform, specification)
    _clear_caches()
    secrets = _credential_secrets(credentials) | {CONFIG_KEY, CONFIG_SECRET}
    assert len(secrets) == len(SECRET_FIELDS) + 2  # each field's value, found

    set_debug_logging(True)
    try:
        records = _plan(platform, credentials) + _plan(
            platform, applications, PlanOptions(regenerate_app_keys=True)
        )
    finally:
        set_debug_logging(False)
    shown = capsys.readouterr()

    assert {r["action"] for r in records[: len(credentials)]} == {"unknown"}
    by_name = {r["name"]: r for r in records[len(credentials) :]}
    application_max = next(r for n, r in by_name.items() if n.endswith("-max"))
    application_min = next(r for n, r in by_name.items() if n.endswith("-min"))
    assert application_min["action"] == "create"
    assert application_max["action"] == "update"
    assert "apiKey" in [c["path"] for c in application_max["changes"]]
    assert " : DEBUG : " in shown.err, shown.err
    for secret in secrets:
        for where in (shown.out, shown.err, repr(records)):
            assert secret not in where, secret
