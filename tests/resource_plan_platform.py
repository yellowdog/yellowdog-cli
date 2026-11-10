"""
A fake Platform for the 'yd resource plan' tests: a MagicMock client holding
the resources a test puts there, which the creators' own lookups find, and
on which anything that would change the Platform fails the test.

Every client method whose name starts with one of MUTATING_PREFIXES, and
requests' post() and put() as the resource libraries call them, raise
AssertionError("the plan changed something"). A resource type is supported by a
lookup wiring in FakePlatform (_wire_templates() for the Compute Source and
Requirement Templates, _wire_keyrings(), _wire_namespaces(),
_wire_image_families(), _wire_accounts()) and, where it is searched, an entry
in _NAME_OF; another type is added the same way. User Attribute Definitions,
which the CLI reads with requests' get() rather than the SDK, are the dicts in
'attribute_definitions', which the fixture's get() serves as the Platform's GET
/compute/attributes/user lists them. A resource held without an ID is given a
well-formed YellowDog ID of its type (_TYPE_TOKENS), so the CLI's lookups
recognise it as one.

hold() puts on it what 'yd resource create' would make of a specification
of the resource corpus (tests/resources/), and holding_all() every
specification of a corpus file, for the corpus's plan and export tests;
corpus_ctx() is the context the corpus's test-config.toml configures.
"""

import json
from collections.abc import Callable, Iterator
from copy import deepcopy
from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests
from requests.exceptions import HTTPError
from resource_corpus import dummy_variables, load_corpus_file
from resource_live import MISSING_NAMESPACE_FAILURE_NAMES
from yellowdog_client.model import (
    Application,
    ConfiguredWorkerPool,
    ExternalUser,
    GrantedPermissionScope,
    Group,
    GroupRole,
    GroupSummary,
    InternalUser,
    Keyring,
    KeyringCredential,
    MachineImageFamilySummary,
    Namespace,
    NamespacePolicy,
    NamespaceRef,
    RoleSummary,
)

import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli.utils import (
    entity_utils,
    lazy,
    resource_creation,
    resource_planners,
)
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    RN_ALLOWANCE,
    RN_APPLICATION,
    RN_CONFIGURED_POOL,
    RN_EXTERNAL_USER,
    RN_GROUP,
    RN_IMAGE_FAMILY,
    RN_INTERNAL_USER,
    RN_KEYRING,
    RN_NAMESPACE,
    RN_NAMESPACE_POLICY,
    RN_REQUIREMENT_TEMPLATE,
    RN_SOURCE_TEMPLATE,
)
from yellowdog_cli.utils.load_resources import RESOURCE_SOURCE_DIR
from yellowdog_cli.utils.specs.sdk_models import SERVER_ASSIGNED_COVERAGE

PLAN_CHANGED_SOMETHING = "the plan changed something"
ATTRIBUTE_DEFINITIONS_PATH = "/compute/attributes/user"
MUTATING_PREFIXES = (
    "add_",
    "update_",
    "delete_",
    "put_",
    "save_",
    "create_",
    "remove_",
    "regenerate_",
)

# Resource type -> the type token of the IDs held resources are given
_TYPE_TOKENS: dict[str, str] = {
    RN_SOURCE_TEMPLATE: "cst",
    RN_REQUIREMENT_TEMPLATE: "crt",
    RN_IMAGE_FAMILY: "imgfam",
    RN_KEYRING: "keyring",
    RN_GROUP: "group",
    RN_APPLICATION: "app",
    RN_INTERNAL_USER: "user",
    RN_EXTERNAL_USER: "user",
    RN_ALLOWANCE: "allow",
    RN_CONFIGURED_POOL: "wrkrpool",
    "Role": "role",
}

# Resource type -> the name a held resource is found by
_NAME_OF: dict[str, Callable[[Any], str | None]] = {
    RN_SOURCE_TEMPLATE: lambda template: template.source.name,
    RN_REQUIREMENT_TEMPLATE: lambda template: template.name,
    RN_KEYRING: lambda keyring: keyring.name,
}


def _not_found() -> HTTPError:
    """
    The error the SDK raises for a resource the Platform does not have.
    """
    response = requests.Response()
    response.status_code = 404
    return HTTPError("not found", response=response)


def _forbidden() -> HTTPError:
    """
    The error the SDK raises for a search the Application may not make.
    """
    response = requests.Response()
    response.status_code = 403
    return HTTPError("forbidden", response=response)


def _changed_something(*args: Any, **kwargs: Any) -> None:
    raise AssertionError(PLAN_CHANGED_SOMETHING)


class _GuardedMock(MagicMock):
    """
    A MagicMock whose mutating methods, at any depth, fail the test.
    """

    def _get_child_mock(self, **kwargs: Any) -> MagicMock:
        child = super()._get_child_mock(**kwargs)
        name = kwargs.get("name")
        if isinstance(name, str) and name.startswith(MUTATING_PREFIXES):
            child.side_effect = _changed_something
        return child


class _Search:
    """
    What a client's search returns: list_all() gives the matches.
    """

    def __init__(self, items: list[Any]):
        self._items = items

    def list_all(self) -> list[Any]:
        return list(self._items)

    def iterate(self) -> Iterator[Any]:
        return iter(self._items)


class FakePlatform:
    """
    The Platform as a test holds it: 'client' for a RunContext, holding()
    to put an existing resource there.
    """

    def __init__(self) -> None:
        self.client = _GuardedMock()
        self.held: dict[str, list[Any]] = {}
        # An Application's or User's ID -> the IDs of the Groups it is in
        self.memberships: dict[str, list[str]] = {}
        # Namespaces an Image Family search scoped to any of refuses (403),
        # as the Platform does for an Application that cannot read them
        self.refused_image_namespaces: set[str] = set()
        # The user Attribute Definitions, as GET /compute/attributes/user
        # lists them
        self.attribute_definitions: list[dict] = []
        self._next_id = 0
        self._wire_templates()
        self._wire_keyrings()
        self._wire_namespaces()
        self._wire_image_families()
        self._wire_accounts()
        self._wire_pools_and_allowances()

    def holding(self, resource_type: str, model: Any) -> Any:
        """
        Hold a copy of 'model' as an existing resource of this type, given
        an ID if it has none, and return the copy.
        """
        held = deepcopy(model)
        if getattr(held, "id", None) is None:
            self._next_id += 1
            token = _TYPE_TOKENS.get(resource_type, resource_type.lower())
            # A UUID no test gives its own resources: '...-ffff-...'
            held.id = (
                f"ydid:{token}:000000:00000000-0000-0000-ffff-{self._next_id:012d}"
            )
        self.held.setdefault(resource_type, []).append(held)
        return held

    def member_of(self, member_id: str, *groups: Any) -> None:
        """
        Make the held Application or User 'member_id' a member of 'groups'.
        """
        self.memberships.setdefault(member_id, []).extend(g.id for g in groups)

    def _matching(self, resource_type: str, search: Any) -> list[Any]:
        """
        The held resources a search finds: by namespace, when it names any,
        and by name as a substring, as the Platform matches it.
        """
        name_of = _NAME_OF[resource_type]
        return [
            held
            for held in self.held.get(resource_type, [])
            if (search.namespaces is None or held.namespace in search.namespaces)
            and (search.name is None or search.name in (name_of(held) or ""))
        ]

    def _by_id(self, resource_type: str) -> Callable[[str], Any]:
        def _get(ydid: str) -> Any:
            for held in self.held.get(resource_type, []):
                if held.id == ydid:
                    return deepcopy(held)
            raise AssertionError(f"no {resource_type} '{ydid}' is held")

        return _get

    def _wire_templates(self) -> None:
        compute = self.client.compute_client

        def _summaries(resource_type: str) -> Callable[[Any], _Search]:
            def _search(search: Any) -> _Search:
                return _Search(
                    [
                        SimpleNamespace(
                            id=held.id,
                            name=_NAME_OF[resource_type](held),
                            namespace=held.namespace,
                        )
                        for held in self._matching(resource_type, search)
                    ]
                )

            return _search

        compute.get_compute_source_templates.side_effect = _summaries(
            RN_SOURCE_TEMPLATE
        )
        compute.get_compute_source_template.side_effect = self._by_id(
            RN_SOURCE_TEMPLATE
        )
        compute.get_compute_requirement_templates.side_effect = _summaries(
            RN_REQUIREMENT_TEMPLATE
        )
        compute.get_compute_requirement_template_by_id.side_effect = self._by_id(
            RN_REQUIREMENT_TEMPLATE
        )

        def _requirement_template(ydid: str) -> Any:
            # As an Allowance's template is named: a 404 for one not held
            for held in self.held.get(RN_REQUIREMENT_TEMPLATE, []):
                if held.id == ydid:
                    return deepcopy(held)
            raise _not_found()

        compute.get_compute_requirement_template.side_effect = _requirement_template

    def _wire_keyrings(self) -> None:
        keyrings = self.client.keyring_client

        def _summaries(search: Any) -> _Search:
            return _Search(
                [
                    SimpleNamespace(
                        id=held.id, name=held.name, description=held.description
                    )
                    for held in self.held.get(RN_KEYRING, [])
                    if search.name is None or search.name in held.name
                ]
            )

        keyrings.get_keyrings.side_effect = _summaries
        keyrings.find_all_keyrings.side_effect = lambda: [
            SimpleNamespace(id=held.id, name=held.name, description=held.description)
            for held in self.held.get(RN_KEYRING, [])
        ]
        keyrings.get_keyring.side_effect = self._by_id(RN_KEYRING)

    def _wire_namespaces(self) -> None:
        """
        Namespaces are found by listing; a Namespace Policy by its namespace,
        a 404 where none is held.
        """
        namespaces = self.client.namespaces_client
        namespaces.get_namespaces.side_effect = lambda search: _Search(
            self.held.get(RN_NAMESPACE, [])
        )

        def _policy(namespace: str) -> Any:
            for held in self.held.get(RN_NAMESPACE_POLICY, []):
                if held.namespace == namespace:
                    return deepcopy(held)
            raise _not_found()

        namespaces.get_namespace_policy.side_effect = _policy

    def _wire_image_families(self) -> None:
        """
        An Image Family is found by its namespace and name, or by its ID,
        with its Image Groups and their Images and its 'access', a 404 where
        none is held; an Image Group by its ID. A search finds the families
        in its namespaces whose name holds its 'familyName', a public one
        (access PUBLIC) only when its own namespace is searched, as the
        Platform does ('includePublic' brings none into another namespace's
        search, live run ydst-2611091551-7dw7). A search scoped to, or a
        family fetched by name from, a namespace in
        'refused_image_namespaces' is refused (403).
        """
        images = self.client.images_client

        def _family(namespace: str, family_name: str) -> Any:
            if namespace in self.refused_image_namespaces:
                raise _forbidden()
            for held in self.held.get(RN_IMAGE_FAMILY, []):
                if (held.namespace, held.name) == (namespace, family_name):
                    return deepcopy(held)
            raise _not_found()

        def _family_by_id(ydid: str) -> Any:
            for held in self.held.get(RN_IMAGE_FAMILY, []):
                if held.id == ydid:
                    return deepcopy(held)
            raise _not_found()

        def _group_by_id(ydid: str) -> Any:
            for held in self.held.get(RN_IMAGE_FAMILY, []):
                for group in held.imageGroups or []:
                    if group.id == ydid:
                        return deepcopy(group)
            raise _not_found()

        def _summaries(search: Any) -> _Search:
            if self.refused_image_namespaces.intersection(search.namespaces or ()):
                raise _forbidden()
            return _Search(
                [
                    MachineImageFamilySummary(
                        id=held.id,
                        namespace=held.namespace,
                        name=held.name,
                        access=held.access,
                        osType=held.osType,
                    )
                    for held in self.held.get(RN_IMAGE_FAMILY, [])
                    if (
                        search.namespaces is None or held.namespace in search.namespaces
                    )
                    and (search.familyName is None or search.familyName in held.name)
                ]
            )

        images.get_image_family_by_name.side_effect = _family
        images.get_image_family_by_id.side_effect = _family_by_id
        images.get_image_group_by_id.side_effect = _group_by_id
        images.get_image_families.side_effect = _summaries

    def _wire_accounts(self) -> None:
        """
        Roles (held as "Role") and Groups found by a search on their name as
        a substring, Applications and Users by listing them all, each
        fetched by its ID, and an Application's or User's Groups from
        member_of().
        """
        account = self.client.account_client

        def _group_summary(group: Any) -> GroupSummary:
            return GroupSummary(
                id=group.id,
                name=group.name,
                description=group.description,
                adminGroup=False,
            )

        def _named(resource_type: str, search: Any) -> list[Any]:
            return [
                held
                for held in self.held.get(resource_type, [])
                if search.name is None or search.name in held.name
            ]

        def _groups_of(member_id: str) -> _Search:
            return _Search(
                [
                    _group_summary(self._by_id(RN_GROUP)(group_id))
                    for group_id in self.memberships.get(member_id, [])
                ]
            )

        account.get_roles.side_effect = lambda search: _Search(_named("Role", search))
        account.get_groups.side_effect = lambda search: _Search(
            [_group_summary(group) for group in _named(RN_GROUP, search)]
        )
        account.get_group.side_effect = self._by_id(RN_GROUP)
        account.get_applications.side_effect = lambda search: _Search(
            self.held.get(RN_APPLICATION, [])
        )
        account.get_application.side_effect = self._by_id(RN_APPLICATION)
        account.get_application_groups.side_effect = _groups_of
        account.get_users.side_effect = lambda search: _Search(
            self.held.get(RN_INTERNAL_USER, []) + self.held.get(RN_EXTERNAL_USER, [])
        )
        account.get_user_groups.side_effect = _groups_of

    def _wire_pools_and_allowances(self) -> None:
        """
        Worker Pools (held as RN_CONFIGURED_POOL, a WorkerPoolSummary or a
        ConfiguredWorkerPool, found by name as a substring, namespace and,
        where both the search and the pool give one, type, and fetched by
        ID) and Allowances (held as RN_ALLOWANCE, found by description as a
        substring, as the Platform matches it).
        """
        pools = self.client.worker_pool_client
        pools.get_worker_pools.side_effect = lambda search: _Search(
            [
                held
                for held in self.held.get(RN_CONFIGURED_POOL, [])
                if (search.namespaces is None or held.namespace in search.namespaces)
                and (search.name is None or search.name in held.name)
                and (search.type is None or held.type in (None, search.type))
            ]
        )
        pools.get_worker_pool_by_id.side_effect = self._by_id(RN_CONFIGURED_POOL)
        self.client.allowances_client.get_allowances.side_effect = lambda search: (
            _Search(
                [
                    held
                    for held in self.held.get(RN_ALLOWANCE, [])
                    if search.description is None
                    or search.description in (held.description or "")
                ]
            )
        )


# ---------------------------------------------------------------------------
# The corpus as the Platform holds it
# ---------------------------------------------------------------------------

# The configured key and secret: never in a plan's output or trace
CONFIG_KEY = "KEY-7e2b9c4a1d"
CONFIG_SECRET = "SECRET-3f8a6d0c2e"

_CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def corpus_ctx(platform: FakePlatform) -> RunContext:
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


def fails_for_want_of_a_namespace(path: Path, specification: dict) -> bool:
    return any(
        specification.get("name", "").endswith(f"-{suffix}")
        for suffix in MISSING_NAMESPACE_FAILURE_NAMES.get(path.name, ())
    )


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


def hold(platform: FakePlatform, specification: dict) -> None:
    """
    Hold what 'yd resource create' would make of 'specification', prepared
    as the planner prepares it, with the values the Platform assigns.
    """
    ctx = corpus_ctx(platform)
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
            platform.attribute_definitions.append(
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
                # The Platform gives every Internal User a username: one
                # found by its name alone has its name as its username here
                user = InternalUser(
                    name=resource.get("name"),
                    username=resource.get("username") or resource.get("name"),
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
            request = resource_creation._get_model_object(
                "AddConfiguredWorkerPoolRequest", resource
            )
            _with_server_values(
                platform.holding(
                    RN_CONFIGURED_POOL,
                    ConfiguredWorkerPool(
                        name=request.name,
                        namespace=request.namespace,
                        properties=request.properties,
                    ),
                )
            )
        case "Allowance":
            _, allowance = resource_creation.prepare_allowance(ctx, resource)
            _with_server_values(platform.holding(RN_ALLOWANCE, allowance))
        case _:
            raise AssertionError(f"no way to hold a '{resource_type}'")


def holding_all(platform: FakePlatform, path: Path) -> list[dict]:
    """
    Hold every specification's resource in 'path', in the order the plan
    takes them, so a reference to an earlier one resolves to it, bar those
    'yd resource create' cannot make; the lookups made before each, which
    may have missed one held since, and on the way, are forgotten. Gives
    the specifications.
    """
    specifications = load_corpus_file(path)
    for specification in specifications:
        if not fails_for_want_of_a_namespace(path, specification):
            _clear_caches()
            hold(platform, specification)
    _clear_caches()
    return specifications


def _clear_caches() -> None:
    entity_utils.clear_compute_source_template_cache()
    entity_utils.clear_compute_requirement_template_cache()
    entity_utils.clear_keyring_cache()
    entity_utils.clear_image_caches()
    entity_utils._get_source_template_name_from_id.cache_clear()
    entity_utils._get_requirement_template_name_from_id.cache_clear()
    entity_utils._get_image_family_or_group_name_from_id.cache_clear()
    entity_utils.clear_group_caches()
    entity_utils.clear_application_caches()
    entity_utils.get_role_id_by_name.cache_clear()
    entity_utils.get_role_name_by_id.cache_clear()
    entity_utils.get_all_roles.cache_clear()
    entity_utils.get_user_by_name_or_id.cache_clear()
    entity_utils.get_all_users.cache_clear()


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakePlatform]:
    """
    A FakePlatform holding nothing, with requests' post() and put() failing
    the test wherever the resource libraries call them, and their get()
    serving its 'attribute_definitions' alone.
    """
    for module in (resource_creation, resource_planners):
        for name in ("post", "put"):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, _changed_something)
    _clear_caches()
    fake = FakePlatform()

    def _get(url: str, **kwargs: Any) -> Any:
        if not url.endswith(ATTRIBUTE_DEFINITIONS_PATH):
            raise AssertionError(f"no GET of '{url}' is served")
        return SimpleNamespace(
            ok=True,
            status_code=200,
            json=lambda: deepcopy(fake.attribute_definitions),
            text=json.dumps(fake.attribute_definitions),
        )

    for module in (entity_utils, resource_planners):
        monkeypatch.setattr(module, "get", _get)
    yield fake
    _clear_caches()
