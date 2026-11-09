"""
A fake Platform for the 'yd resource plan' tests: a MagicMock client holding
the resources a test puts there, which the creators' own lookups find, and
on which anything that would change the Platform fails the test.

Every client method whose name starts with one of MUTATING_PREFIXES, and
requests' post() and put() as the resource libraries call them, raise
AssertionError("the plan changed something"). A resource type is supported
by a lookup wiring in FakePlatform (_wire_templates() for the Compute
Source and Requirement Templates, _wire_keyrings(), _wire_namespaces(),
_wire_image_families(), _wire_accounts()) and, where it is searched, an entry in _NAME_OF;
another type is added the same way.
"""

from collections.abc import Callable, Iterator
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests
from requests.exceptions import HTTPError
from yellowdog_client.model import GroupSummary

from yellowdog_cli.utils import entity_utils, resource_creation, resource_planners
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

PLAN_CHANGED_SOMETHING = "the plan changed something"
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
        self._next_id = 0
        # No Image Families: an image name is passed on as it is
        self.client.images_client.get_image_families.return_value = _Search([])
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
            held.id = f"ydid:{resource_type.lower()}:000000:{self._next_id:08d}"
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
        An Image Family is found by its namespace and name, with its Image
        Groups and their Images, a 404 where none is held.
        """

        def _family(namespace: str, family_name: str) -> Any:
            for held in self.held.get(RN_IMAGE_FAMILY, []):
                if (held.namespace, held.name) == (namespace, family_name):
                    return deepcopy(held)
            raise _not_found()

        self.client.images_client.get_image_family_by_name.side_effect = _family

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
        Worker Pool summaries (held as RN_CONFIGURED_POOL, found by name and
        namespace) and Allowances (held as RN_ALLOWANCE, found by
        description as a substring, as the Platform matches it).
        """
        self.client.worker_pool_client.get_worker_pools.side_effect = lambda search: (
            _Search(
                [
                    held
                    for held in self.held.get(RN_CONFIGURED_POOL, [])
                    if (
                        search.namespaces is None or held.namespace in search.namespaces
                    )
                    and (search.name is None or search.name in held.name)
                ]
            )
        )
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


def _clear_caches() -> None:
    entity_utils.clear_compute_source_template_cache()
    entity_utils.clear_compute_requirement_template_cache()
    entity_utils.clear_keyring_cache()
    entity_utils.get_image_name_or_id.cache_clear()
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
    the test wherever the resource libraries call them.
    """
    for module in (resource_creation, resource_planners):
        for name in ("post", "put"):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, _changed_something)
    _clear_caches()
    yield FakePlatform()
    _clear_caches()
