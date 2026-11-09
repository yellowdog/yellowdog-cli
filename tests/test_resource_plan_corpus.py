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
from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from resource_corpus import (
    CORPUS_DIR,
    corpus_files,
    dummy_variables,
    install_variables,
    load_corpus_file,
    remove_variables,
    require_jsonnet,
)
from resource_live import MISSING_NAMESPACE_FAILURE_NAMES
from yellowdog_client.model import (
    Application,
    ExternalUser,
    GrantedPermissionScope,
    Group,
    GroupRole,
    InternalUser,
    Keyring,
    KeyringCredential,
    Namespace,
    NamespacePolicy,
    NamespaceRef,
    RoleSummary,
)

import yellowdog_cli.utils.results as results_module
import yellowdog_cli.utils.wrapper as wrapper_module
from tests.resource_plan_platform import (  # noqa: F401 (the fixture)
    MUTATING_PREFIXES,
    PLAN_CHANGED_SOMETHING,
    FakePlatform,
    _clear_caches,
    _not_found,
    platform,
)
from yellowdog_cli.utils import lazy, resource_creation, resource_planners
from yellowdog_cli.utils.context import RunContext
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
    RN_KEYRING,
    RN_NAMESPACE,
    RN_NAMESPACE_POLICY,
    RN_NUMERIC_ATTRIBUTE_DEFINITION,
    RN_REQUIREMENT_TEMPLATE,
    RN_SOURCE_TEMPLATE,
    RN_STRING_ATTRIBUTE_DEFINITION,
)
from yellowdog_cli.utils.exit_codes import ReportedFailure
from yellowdog_cli.utils.load_resources import RESOURCE_SOURCE_DIR
from yellowdog_cli.utils.resource_plan import PlanOptions, plan_resources
from yellowdog_cli.utils.resource_planners import CONFIGURED_POOL_EXISTS
from yellowdog_cli.utils.specs.sdk_models import SERVER_ASSIGNED_COVERAGE

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

# The configured key and secret: never in a plan's output or trace
CONFIG_KEY = "KEY-7e2b9c4a1d"
CONFIG_SECRET = "SECRET-3f8a6d0c2e"

_ATTRIBUTE_TYPES = (RN_STRING_ATTRIBUTE_DEFINITION, RN_NUMERIC_ATTRIBUTE_DEFINITION)
_CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)


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


@pytest.fixture(autouse=True)
def _attribute_definitions(
    platform: FakePlatform,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    The user Attribute Definitions the Platform lists: those held.
    """
    response = MagicMock(ok=True, status_code=200, text="")
    response.json.side_effect = lambda: [
        definition
        for resource_type in _ATTRIBUTE_TYPES
        for definition in platform.held.get(resource_type, [])
    ]
    monkeypatch.setattr(resource_planners, "get", MagicMock(return_value=response))


def _ctx(platform: FakePlatform) -> RunContext:
    """
    A context configured as the corpus's test-config.toml configures one:
    its namespace and tag, in which an unqualified template name is found,
    with a key and secret of the test's own.
    """
    variables = dummy_variables()
    config = replace(
        lazy.value(wrapper_module.CONFIG_COMMON),
        namespace=variables["namespace"],
        name_tag=variables["tag"],
        key=CONFIG_KEY,
        secret=CONFIG_SECRET,
    )
    return RunContext(SimpleNamespace(), config, platform.client)


def _fails_for_want_of_a_namespace(path: Path, specification: dict) -> bool:
    return any(
        specification.get("name", "").endswith(f"-{suffix}")
        for suffix in MISSING_NAMESPACE_FAILURE_NAMES.get(path.name, ())
    )


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
        plan_resources(_ctx(platform), specifications, options)
    except ReportedFailure:
        pass
    records = list(results_module._ITEMS)
    assert len(records) == len(specifications), records
    return records


# ---------------------------------------------------------------------------
# Holding what each specification would make
# ---------------------------------------------------------------------------


def _with_server_values(model: Any) -> None:
    """
    Give a held model, at every level, the values the Platform assigns
    (SERVER_ASSIGNED_COVERAGE) that it lacks, which the comparison must
    ignore.
    """
    if isinstance(model, list):
        for item in model:
            _with_server_values(item)
        return
    if not is_dataclass(model) or isinstance(model, type):
        return
    name = type(model).__name__
    for field in fields(model):
        value = getattr(model, field.name)
        if value is None and name in SERVER_ASSIGNED_COVERAGE.get(field.name, ()):
            setattr(
                model,
                field.name,
                _CREATED
                if field.name == "createdTime"
                else f"server-assigned-{field.name}",
            )
        else:
            _with_server_values(value)


def _group_id(platform: FakePlatform) -> str:
    # Well-formed, since a Group may be named by its ID
    number = len(platform.held.get(RN_GROUP, [])) + 1
    return f"ydid:group:000000:00000000-0000-0000-0000-{number:012d}"


def _held_group(platform: FakePlatform, name: str, description: str | None = None):
    for group in platform.held.get(RN_GROUP, []):
        if group.name == name:
            return group
    group = Group(name=name, description=description, roles=[], adminGroup=False)
    group.id = _group_id(platform)
    return platform.holding(RN_GROUP, group)


def _group_role(platform: FakePlatform, spec) -> GroupRole:
    role = next(r for r in platform.held["Role"] if r.id == spec.id)
    return GroupRole(
        role=RoleSummary(id=role.id, name=role.name),
        scope=GrantedPermissionScope(
            global_=bool(spec.global_),
            namespaces=(
                [
                    NamespaceRef(id=f"ydid:ns:000000:{namespace}", namespace=namespace)
                    for namespace in sorted(spec.namespaces)
                ]
                if spec.namespaces
                else None
            ),
        ),
    )


def _held_keyring(platform: FakePlatform, name: str, description: str | None):
    for keyring in platform.held.get(RN_KEYRING, []):
        if keyring.name == name:
            return keyring
    return platform.holding(
        RN_KEYRING, Keyring(name=name, description=description, credentials=[])
    )


def _hold(platform: FakePlatform, specification: dict) -> None:
    """
    Hold what 'yd resource create' would make of 'specification', prepared
    as the planner prepares it, with the values the Platform assigns.
    """
    ctx = _ctx(platform)
    resource = deepcopy(specification)
    resource_type = resource.pop("resource")
    source_dir = resource.pop(RESOURCE_SOURCE_DIR, None)
    match resource_type:
        case "ComputeSourceTemplate":
            _, model = resource_creation.prepare_compute_source_template(
                ctx, resource, source_dir
            )
            _with_server_values(platform.holding(RN_SOURCE_TEMPLATE, model))
        case "ComputeRequirementTemplate":
            _, model, _ = resource_creation.prepare_compute_requirement_template(
                ctx, resource, source_dir
            )
            _with_server_values(platform.holding(RN_REQUIREMENT_TEMPLATE, model))
        case "MachineImageFamily":
            _, model = resource_creation.prepare_image_family(ctx, resource)
            _with_server_values(platform.holding(RN_IMAGE_FAMILY, model))
        case "Keyring":
            _held_keyring(platform, resource["name"], resource.get("description"))
        case "Credential":
            keyring = _held_keyring(platform, resource["keyringName"], "a Keyring")
            keyring.credentials.append(
                KeyringCredential(
                    name=resource["credential"]["name"],
                    type=resource["credential"]["type"],
                )
            )
        case "Namespace":
            platform.holding(
                RN_NAMESPACE,
                Namespace(id=None, namespace=resource["name"], deletable=True),
            )
        case "NamespacePolicy":
            platform.holding(
                RN_NAMESPACE_POLICY,
                NamespacePolicy(
                    namespace=resource["namespace"],
                    autoscalingMaxNodes=resource.get("autoscalingMaxNodes"),
                ),
            )
        case "StringAttributeDefinition" | "NumericAttributeDefinition":
            payload = resource_creation.prepare_attribute_definition(
                ctx, resource, resource_type
            )
            platform.held.setdefault(resource_type, []).append(
                {
                    **payload,
                    "id": f"ydid:attr:000000:{payload['name']}",
                    "createdTime": _CREATED.isoformat(),
                }
            )
        case "Group":
            name, description, roles = resource_creation.prepare_group(ctx, resource)
            group = _held_group(platform, name, description)
            group.roles = [_group_role(platform, role) for role in roles or []]
        case "Application":
            application = Application(
                name=resource["name"],
                createdByUserId="ydid:user:000000:creator",
                description=resource.get("description"),
            )
            held = platform.holding(RN_APPLICATION, application)
            platform.member_of(
                held.id,
                *(_held_group(platform, name) for name in resource.get("groups", [])),
            )
        case "InternalUser" | "ExternalUser":
            user: Any
            if resource_type == "InternalUser":
                user = InternalUser(
                    name=resource.get("name"),
                    username=resource.get("username"),
                )
            else:
                user = ExternalUser(name=resource.get("name") or "an external user")
            if resource.get("id") is not None:
                user.id = resource["id"]
            held = platform.holding(resource_type, user)
            platform.member_of(
                held.id,
                *(_held_group(platform, name) for name in resource.get("groups", [])),
            )
        case "ConfiguredWorkerPool":
            platform.holding(
                RN_CONFIGURED_POOL,
                SimpleNamespace(name=resource["name"], namespace=resource["namespace"]),
            )
        case "Allowance":
            platform.holding(
                RN_ALLOWANCE, SimpleNamespace(description=resource.get("description"))
            )
        case _:
            raise AssertionError(f"no way to hold a '{resource_type}'")


def _holding_all(platform: FakePlatform, path: Path) -> list[dict]:
    """
    Hold every specification's resource in 'path', in the order the plan
    takes them, so a reference to an earlier one resolves to it, bar those
    'yd resource create' cannot make, and forget the lookups made on the
    way. Gives the specifications.
    """
    specifications = load_corpus_file(path)
    for specification in specifications:
        if not _fails_for_want_of_a_namespace(path, specification):
            _hold(platform, specification)
    _clear_caches()
    return specifications


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
            _ctx(empty), resource_type, resource, source_dir, False
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
            _fails_for_want_of_a_namespace(path, specification)
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
    specifications = _holding_all(platform, path)
    records = _plan(platform, specifications)
    for specification, record in zip(specifications, records):
        resource_type = specification["resource"]
        if _fails_for_want_of_a_namespace(path, specification):
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
        records += _plan(platform, _holding_all(platform, path))

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
    specifications = _holding_all(platform, CORPUS_DIR / file_name)
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
    credentials = _holding_all(platform, CORPUS_DIR / "credentials.jsonnet")
    applications = load_corpus_file(CORPUS_DIR / "applications.jsonnet")
    for specification in applications:
        if not specification["name"].endswith("-application-min"):
            _hold(platform, specification)
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
