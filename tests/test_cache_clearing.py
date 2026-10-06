"""
Every yd-create and yd-remove mutation clears the cached lookups it
invalidates, in the function that mutates: a specification later in the same
run must see the change (a name created earlier found, a name removed
earlier not found, an updated resource read back as updated). These tests
are about the mutating side.

Each case drives the real create_*/remove_* function against a MagicMock
client, with the name lookups it needs patched to reach the mutation, and
asserts the matching clear function was called.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import yellowdog_cli.utils.resource_creation as create_module
import yellowdog_cli.utils.resource_removal as remove_module
import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.ydid_utils import (
    TYPE_APP,
    TYPE_CRT,
    TYPE_CST,
    TYPE_GROUP,
    TYPE_IMAGE,
    TYPE_IMGFAM,
    TYPE_IMGGRP,
)


def _ctx() -> RunContext:
    """
    The context a command is given: the wrapper globals, as patched.
    """
    return RunContext(
        wrapper_module.ARGS_PARSER, wrapper_module.CONFIG_COMMON, wrapper_module.CLIENT
    )


def _ydid(type_token: str) -> str:
    return f"ydid:{type_token}:000000:00000000-0000-0000-0000-000000000000"


def _args() -> MagicMock:
    return MagicMock(
        dry_run=False,
        quiet=False,
        regenerate_app_keys=False,
        show_keyring_passwords=False,
        yes=True,
    )


def _spy(monkeypatch, module, name: str) -> MagicMock:
    """
    Replace module.<name> with a spy; the attribute must already exist.
    """
    spy = MagicMock(name=name)
    monkeypatch.setattr(module, name, spy)
    return spy


@pytest.fixture
def client() -> MagicMock:
    return MagicMock()


@pytest.fixture(autouse=True)
def _confirm_everything(monkeypatch):
    monkeypatch.setattr(create_module, "confirmed", lambda _: True)
    monkeypatch.setattr(remove_module, "confirmed", lambda _: True)
    monkeypatch.setattr(create_module, "_OPTIONS", _args())
    monkeypatch.setattr(remove_module, "_OPTIONS", _args())


# ---------------------------------------------------------------------------
# yd-remove by YDID
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "type_token, clear_name",
    [
        (TYPE_CST, "clear_compute_source_template_cache"),
        (TYPE_CRT, "clear_compute_requirement_template_cache"),
        (TYPE_IMGFAM, "clear_image_caches"),
        (TYPE_IMGGRP, "clear_image_caches"),
        (TYPE_IMAGE, "clear_image_caches"),
        (TYPE_GROUP, "clear_group_caches"),
        (TYPE_APP, "clear_application_caches"),
    ],
)
def test_removal_by_id_clears_its_cache(monkeypatch, client, type_token, clear_name):
    spy = _spy(monkeypatch, remove_module, clear_name)
    with patch.object(wrapper_module, "CLIENT", client):
        assert remove_module.remove_resource_by_id(_ctx(), _ydid(type_token)) is True
    spy.assert_called_once()


# ---------------------------------------------------------------------------
# yd-remove by specification
# ---------------------------------------------------------------------------


def test_removing_a_source_template_clears_its_cache(monkeypatch, client):
    spy = _spy(monkeypatch, remove_module, "clear_compute_source_template_cache")
    monkeypatch.setattr(
        remove_module, "get_compute_source_template_id_by_name", lambda *a: "cst-id"
    )
    with patch.object(wrapper_module, "CLIENT", client):
        remove_module.remove_compute_source_template(
            _ctx(), {"namespace": "n", "source": {"name": "s"}}
        )
    client.compute_client.delete_compute_source_template_by_id.assert_called_once()
    spy.assert_called_once()


def test_removing_a_requirement_template_clears_its_cache(monkeypatch, client):
    spy = _spy(monkeypatch, remove_module, "clear_compute_requirement_template_cache")
    monkeypatch.setattr(
        remove_module,
        "get_compute_requirement_template_id_by_name",
        lambda *a: "crt-id",
    )
    with patch.object(wrapper_module, "CLIENT", client):
        remove_module.remove_compute_requirement_template(
            _ctx(), {"name": "t", "namespace": "n"}
        )
    client.compute_client.delete_compute_requirement_template_by_id.assert_called_once()
    spy.assert_called_once()


def test_removing_an_image_family_clears_the_image_caches(monkeypatch, client):
    spy = _spy(monkeypatch, remove_module, "clear_image_caches")
    with patch.object(wrapper_module, "CLIENT", client):
        remove_module.remove_image_family(_ctx(), {"name": "f", "namespace": "n"})
    client.images_client.delete_image_family.assert_called_once()
    spy.assert_called_once()


# ---------------------------------------------------------------------------
# yd-create: the add and update paths of each cached resource
# ---------------------------------------------------------------------------


def _source_template_resource() -> dict:
    return {
        "namespace": "n",
        "source": {
            "type": "co.yellowdog.platform.model.AwsInstancesComputeSource",
            "name": "s",
        },
    }


def _patch_source_template_creation(monkeypatch, existing_id: str | None) -> None:
    monkeypatch.setattr(create_module, "_get_model_object", lambda *a, **k: MagicMock())
    monkeypatch.setattr(create_module, "get_image_name_or_id", lambda *a, **k: "img")
    monkeypatch.setattr(
        create_module, "resolve_user_data_in_spec", lambda *a, **k: None
    )
    monkeypatch.setattr(
        create_module,
        "get_compute_source_template_id_by_name",
        lambda *a, **k: existing_id,
    )


@pytest.mark.parametrize("existing_id", [None, "cst-id"], ids=["add", "update"])
def test_creating_a_source_template_clears_its_cache(monkeypatch, client, existing_id):
    _patch_source_template_creation(monkeypatch, existing_id)
    spy = _spy(monkeypatch, create_module, "clear_compute_source_template_cache")
    with patch.object(wrapper_module, "CLIENT", client):
        create_module.create_compute_source_template(
            _ctx(), _source_template_resource()
        )
    mutation = (
        client.compute_client.add_compute_source_template
        if existing_id is None
        else client.compute_client.update_compute_source_template
    )
    mutation.assert_called_once()
    spy.assert_called()


def _requirement_template_resource() -> dict:
    return {
        "name": "t",
        "namespace": "n",
        "type": "co.yellowdog.platform.model.ComputeRequirementDynamicTemplate",
        "strategyType": "co.yellowdog.platform.model.SingleSourceProvisionStrategy",
    }


@pytest.mark.parametrize("existing_id", [None, "crt-id"], ids=["add", "update"])
def test_creating_a_requirement_template_clears_its_cache(
    monkeypatch, client, existing_id
):
    monkeypatch.setattr(create_module, "_get_model_object", lambda *a, **k: MagicMock())
    monkeypatch.setattr(create_module, "get_image_name_or_id", lambda *a, **k: "img")
    monkeypatch.setattr(
        create_module,
        "get_compute_requirement_template_id_by_name",
        lambda *a, **k: existing_id,
    )
    spy = _spy(monkeypatch, create_module, "clear_compute_requirement_template_cache")
    with patch.object(wrapper_module, "CLIENT", client):
        create_module.create_compute_requirement_template(
            _ctx(), _requirement_template_resource()
        )
    mutation = (
        client.compute_client.add_compute_requirement_template
        if existing_id is None
        else client.compute_client.update_compute_requirement_template
    )
    mutation.assert_called_once()
    spy.assert_called()


def test_updating_an_image_family_clears_the_image_caches(monkeypatch, client):
    family = SimpleNamespace(id="if-id", name="f", imageGroups=[])
    monkeypatch.setattr(create_module, "_get_model_object", lambda *a, **k: family)
    client.images_client.get_image_family_by_name.return_value = family
    spy = _spy(monkeypatch, create_module, "clear_image_caches")
    with patch.object(wrapper_module, "CLIENT", client):
        create_module.create_image_family(
            _ctx(), {"name": "f", "namespace": "n", "osType": "LINUX"}
        )
    client.images_client.update_image_family.assert_called_once()
    spy.assert_called()


def test_updating_a_group_clears_the_group_caches(monkeypatch, client):
    monkeypatch.setattr(create_module, "get_group_id_by_name", lambda *a: "gid")
    client.account_client.update_group.return_value = MagicMock(roles=[])
    spy = _spy(monkeypatch, create_module, "clear_group_caches")
    with patch.object(wrapper_module, "CLIENT", client):
        create_module.create_group(
            _ctx(), {"name": "g", "description": "d", "roles": []}
        )
    client.account_client.update_group.assert_called_once()
    spy.assert_called()


def test_updating_an_application_clears_the_application_caches(monkeypatch, client):
    monkeypatch.setattr(create_module, "get_application_id_by_name", lambda *a: "aid")
    monkeypatch.setattr(create_module, "get_application_group_summaries", lambda *a: [])
    spy = _spy(monkeypatch, create_module, "clear_application_caches")
    with patch.object(wrapper_module, "CLIENT", client):
        create_module.create_application(_ctx(), {"name": "a"})
    client.account_client.update_application.assert_called_once()
    spy.assert_called()
