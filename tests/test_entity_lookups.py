"""
Unit tests for the lookups in utils/entity_utils.py that tolerate some
failures and not others: the Image Family listing behind image name
resolution, the Compute Requirement Template name lookup, the
'--substitute-ids' name lookups and the Group name shown in yd-create's
messages.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

import yellowdog_cli.create as yd_create
from yellowdog_cli.utils import entity_utils
from yellowdog_cli.utils.entity_utils import AmbiguousNameError

CST_ID = "ydid:cst:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class MissingPermission(Exception):
    def __str__(self) -> str:
        return "MissingPermissionException: IMAGE_READ"


@pytest.fixture(autouse=True)
def _fresh_caches():
    entity_utils.clear_image_caches()
    entity_utils.get_compute_requirement_templates.cache_clear()
    entity_utils._get_source_template_name_from_id.cache_clear()
    entity_utils.clear_group_caches()
    yield
    entity_utils.clear_image_caches()
    entity_utils.get_compute_requirement_templates.cache_clear()
    entity_utils._get_source_template_name_from_id.cache_clear()
    entity_utils.clear_group_caches()


def _image_client(families_side_effect) -> MagicMock:
    client = MagicMock()
    client.application_client.get_application_details.return_value = SimpleNamespace(
        allNamespacesReadable=True, readableNamespaces=None
    )
    client.images_client.get_image_families.side_effect = families_side_effect
    return client


# ---------------------------------------------------------------------------
# Image Families
# ---------------------------------------------------------------------------


def test_a_failed_image_family_listing_is_raised_not_passed_through():
    client = _image_client(requests.ConnectionError("refused"))
    with pytest.raises(requests.ConnectionError):
        entity_utils.get_image_name_or_id(client, "yd/ns/ubuntu")


def test_a_failed_image_family_listing_is_not_cached():
    family = SimpleNamespace(
        id="ydid:imgfam:000000:x", namespace="ns", name="ubuntu", access=None
    )
    listing = MagicMock()
    listing.list_all.return_value = [family]
    client = _image_client([requests.ConnectionError("refused"), listing])
    with pytest.raises(requests.ConnectionError):
        entity_utils.get_image_family_summaries(client)
    assert entity_utils.get_image_family_summaries(client) == [family]


def test_a_missing_permission_for_every_namespace_falls_back_quietly(capsys):
    client = _image_client(MissingPermission())
    assert entity_utils.get_image_family_summaries(client) == []
    assert "IMAGE_READ" not in capsys.readouterr().out


def test_a_missing_permission_for_a_namespace_is_warned_of(capsys):
    client = _image_client(MissingPermission())
    assert entity_utils.get_image_family_summaries(client, "ns") == []
    assert "IMAGE_READ" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Compute Requirement Templates
# ---------------------------------------------------------------------------


def _templates(*namespaces: str) -> MagicMock:
    client = MagicMock()
    client.compute_client.get_compute_requirement_templates.return_value.list_all.return_value = [
        SimpleNamespace(id=f"crt-{ns}", namespace=ns, name="gpu") for ns in namespaces
    ]
    return client


def test_a_template_name_in_two_namespaces_is_ambiguous():
    with pytest.raises(AmbiguousNameError, match="ns1, ns2"):
        entity_utils.get_compute_requirement_template_id_by_name(
            _templates("ns2", "ns1"), "gpu"
        )


def test_a_template_name_in_one_namespace_is_found():
    assert (
        entity_utils.get_compute_requirement_template_id_by_name(
            _templates("ns1"), "gpu"
        )
        == "crt-ns1"
    )


# ---------------------------------------------------------------------------
# Names shown in place of IDs
# ---------------------------------------------------------------------------


def test_a_session_failure_naming_a_template_is_raised():
    client = MagicMock()
    client.compute_client.get_compute_source_template.side_effect = (
        requests.ConnectionError("refused")
    )
    with pytest.raises(requests.ConnectionError):
        entity_utils._get_source_template_name_from_id(client, CST_ID)


def test_any_other_failure_naming_a_template_shows_the_id():
    client = MagicMock()
    client.compute_client.get_compute_source_template.side_effect = ValueError("gone")
    assert entity_utils._get_source_template_name_from_id(client, CST_ID) == CST_ID


def test_a_group_whose_name_cannot_be_fetched_is_shown_by_its_id(monkeypatch):
    client = MagicMock()
    client.account_client.get_group.side_effect = ValueError("gone")
    monkeypatch.setattr(yd_create, "CLIENT", client)
    assert yd_create._group_shown("ydid:grp:000000:x") == "ydid:grp:000000:x"


def test_a_group_is_shown_by_name_and_id(monkeypatch):
    client = MagicMock()
    client.account_client.get_group.return_value = SimpleNamespace(name="admins")
    monkeypatch.setattr(yd_create, "CLIENT", client)
    assert yd_create._group_shown("ydid:grp:000000:y") == "'admins' (ydid:grp:000000:y)"


def test_split_namespace_and_name_strips_alike():
    assert entity_utils.split_namespace_and_name(" name ") == (None, "name")
    assert entity_utils.split_namespace_and_name(" ns/name ") == ("ns", "name")
