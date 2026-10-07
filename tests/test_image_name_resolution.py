"""
utils/entity_utils.py's get_image_name_or_id(): an Images ID given as a name,
in any of its forms, resolved to its YDID (always, for a PUBLIC family) or to
its 'yd/' name; an ambiguous name refused; a name matching nothing passed on
unchanged, being a provider's own image ID; and the replacement reported only
when it changes what was given.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from yellowdog_client.model import ImageAccess

from yellowdog_cli.utils import entity_utils

FAMILY_ID = "ydid:imgfam:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_FAMILY_ID = "ydid:imgfam:000000:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
GROUP_ID = "ydid:imggrp:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_GROUP_ID = "ydid:imggrp:000000:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
IMAGE_ID = "ydid:image:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _family(id, namespace, name, access=ImageAccess.PRIVATE):
    return SimpleNamespace(id=id, namespace=namespace, name=name, access=access)


class _Images:
    """
    The two lookups get_image_name_or_id() makes, over fixed families and
    groups, recording the namespaced listings asked for.
    """

    def __init__(self, families, groups=None, namespaced=None):
        self.families = families
        self.groups = groups or {}
        self.namespaced = namespaced or {}
        self.namespaces_asked = []

    def summaries(self, _client, namespace=None):
        if namespace is None:
            return list(self.families)
        self.namespaces_asked.append(namespace)
        return list(self.namespaced.get(namespace, []))

    def family_groups(self, _client, family_id):
        return [
            SimpleNamespace(id=id, name=name)
            for id, name in self.groups.get(family_id, [])
        ]


@pytest.fixture
def resolve(monkeypatch):
    """
    Resolve an Images ID over the given families and groups, returning the
    result and the messages printed. Uncached, so each test sees its own.
    """
    messages: list[str] = []
    monkeypatch.setattr(entity_utils, "print_info", messages.append)

    def _resolve(images: _Images, value, always_return_ydid=True):
        monkeypatch.setattr(
            entity_utils, "get_image_family_summaries", images.summaries
        )
        monkeypatch.setattr(
            entity_utils, "get_image_family_groups", images.family_groups
        )
        result = entity_utils.get_image_name_or_id.__wrapped__(
            MagicMock(), value, always_return_ydid
        )
        return result, messages

    return _resolve


ONE_FAMILY = _Images([_family(FAMILY_ID, "ns", "fam")])
WITH_GROUP = _Images(
    [_family(FAMILY_ID, "ns", "fam")], groups={FAMILY_ID: [(GROUP_ID, "grp")]}
)


def test_none_is_none(resolve):
    assert resolve(ONE_FAMILY, None) == (None, [])


@pytest.mark.parametrize("ydid", [FAMILY_ID, GROUP_ID, IMAGE_ID])
def test_an_image_ydid_is_returned_unchanged(resolve, ydid):
    assert resolve(ONE_FAMILY, ydid) == (ydid, [])


class TestFamilyName:
    def test_resolves_to_its_ydid(self, resolve):
        result, messages = resolve(ONE_FAMILY, "fam")
        assert result == FAMILY_ID
        assert messages == [f"Images ID 'fam' -> {FAMILY_ID}"]

    def test_resolves_to_its_name_if_no_ydid_is_required(self, resolve):
        result, messages = resolve(ONE_FAMILY, "fam", always_return_ydid=False)
        assert result == "yd/ns/fam"
        assert messages == ["Images ID 'fam' -> 'yd/ns/fam'"]

    def test_a_public_family_always_resolves_to_its_ydid(self, resolve):
        images = _Images([_family(FAMILY_ID, "ns", "fam", ImageAccess.PUBLIC)])
        result, _ = resolve(images, "fam", always_return_ydid=False)
        assert result == FAMILY_ID

    def test_one_in_several_namespaces_is_ambiguous(self, resolve):
        images = _Images(
            [_family(FAMILY_ID, "ns1", "fam"), _family(OTHER_FAMILY_ID, "ns2", "fam")]
        )
        with pytest.raises(ValueError, match=r"Ambiguous Images ID 'fam'.*ns1, ns2"):
            resolve(images, "fam")


class TestNamespaceAndFamily:
    def test_resolves_to_its_ydid(self, resolve):
        assert resolve(ONE_FAMILY, "ns/fam")[0] == FAMILY_ID

    def test_the_prefix_and_latest_are_ignored(self, resolve):
        assert resolve(ONE_FAMILY, "yd/ns/fam/latest")[0] == FAMILY_ID

    def test_its_own_name_is_not_reported_as_a_replacement(self, resolve):
        result, messages = resolve(ONE_FAMILY, "yd/ns/fam", always_return_ydid=False)
        assert result == "yd/ns/fam"
        assert messages == []

    def test_the_namespace_is_listed_when_the_global_listing_is_empty(self, resolve):
        images = _Images([], namespaced={"ns": [_family(FAMILY_ID, "ns", "fam")]})
        assert resolve(images, "ns/fam")[0] == FAMILY_ID
        assert images.namespaces_asked == ["ns"]


class TestFamilyAndGroup:
    def test_resolves_to_the_groups_ydid(self, resolve):
        result, messages = resolve(WITH_GROUP, "fam/grp")
        assert result == GROUP_ID
        assert messages == [f"Images ID 'fam/grp' -> {GROUP_ID}"]

    def test_resolves_to_its_name_if_no_ydid_is_required(self, resolve):
        assert resolve(WITH_GROUP, "fam/grp", always_return_ydid=False)[0] == (
            "yd/ns/fam/grp"
        )

    def test_one_in_several_namespaces_is_ambiguous(self, resolve):
        images = _Images(
            [_family(FAMILY_ID, "ns1", "fam"), _family(OTHER_FAMILY_ID, "ns2", "fam")],
            groups={
                FAMILY_ID: [(GROUP_ID, "grp")],
                OTHER_FAMILY_ID: [(OTHER_GROUP_ID, "grp")],
            },
        )
        with pytest.raises(
            ValueError, match=r"Ambiguous image-family/image-group 'fam/grp'.*ns1, ns2"
        ):
            resolve(images, "fam/grp")

    def test_a_namespace_and_family_match_comes_first(self, resolve):
        # 'ns/fam' names a family; a family called 'ns' with a group called
        # 'fam' is not looked for
        images = _Images(
            [_family(FAMILY_ID, "ns", "fam"), _family(OTHER_FAMILY_ID, "x", "ns")],
            groups={OTHER_FAMILY_ID: [(GROUP_ID, "fam")]},
        )
        assert resolve(images, "ns/fam")[0] == FAMILY_ID


class TestNamespaceFamilyAndGroup:
    def test_resolves_to_the_groups_ydid(self, resolve):
        assert resolve(WITH_GROUP, "ns/fam/grp")[0] == GROUP_ID

    def test_resolves_to_its_name_if_no_ydid_is_required(self, resolve):
        result, messages = resolve(WITH_GROUP, "ns/fam/grp", always_return_ydid=False)
        assert result == "yd/ns/fam/grp"
        assert messages == ["Images ID 'ns/fam/grp' -> 'yd/ns/fam/grp'"]

    def test_a_missing_group_is_an_error(self, resolve):
        with pytest.raises(ValueError, match="no matching image group for 'ns/fam/x'"):
            resolve(WITH_GROUP, "ns/fam/x")

    def test_the_namespace_is_listed_when_the_global_listing_is_empty(self, resolve):
        images = _Images(
            [],
            groups={FAMILY_ID: [(GROUP_ID, "grp")]},
            namespaced={"ns": [_family(FAMILY_ID, "ns", "fam")]},
        )
        assert resolve(images, "ns/fam/grp")[0] == GROUP_ID


@pytest.mark.parametrize("value", ["ami-0123456789", "a/b", "ns/fam/grp/extra"])
def test_a_name_matching_nothing_is_passed_on_unchanged(resolve, value):
    result, messages = resolve(WITH_GROUP, value)
    assert result == value
    assert messages == [f"No Images ID substitution possible for '{value}'"]
