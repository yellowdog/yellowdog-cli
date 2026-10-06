"""
Keyrings through the SDK's own client calls -- get_keyrings(search),
get_keyring(id) and update_keyring(id, request) -- in place of the
deprecated find_all_keyrings() and the raw HTTP fetch that stood in for a
missing SDK call.

- entity_utils.get_keyring_summary_by_name() resolves a name to its summary
  with an exact match, the search's 'name' being a partial match.
- yd-create updates an existing Keyring's description in place; it no longer
  offers to delete and recreate it (which lost the credentials).
- yd-remove by YDID fetches the Keyring by ID rather than listing every one.
"""

from unittest.mock import MagicMock, patch

import pytest
from requests import HTTPError
from yellowdog_client.model import (
    CreateKeyringResponse,
    Keyring,
    KeyringSearch,
    KeyringSummary,
    UpdateKeyringRequest,
)

import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_utils import get_keyring_summary_by_name


def _ctx() -> RunContext:
    """
    The context a command is given: the wrapper globals, as patched.
    """
    return RunContext(
        wrapper_module.ARGS_PARSER, wrapper_module.CONFIG_COMMON, wrapper_module.CLIENT
    )


YDID = "ydid:keyring:000000:00000000-0000-0000-0000-000000000000"


def _summary(name: str, id: str = YDID) -> KeyringSummary:
    return KeyringSummary(id=id, name=name, description="d")


def _client(found: list[KeyringSummary]) -> MagicMock:
    client = MagicMock()
    client.keyring_client.get_keyrings.return_value.list_all.return_value = found
    client.keyring_client.find_all_keyrings.side_effect = AssertionError(
        "find_all_keyrings() is deprecated and must not be called"
    )
    return client


class TestLookupByName:
    def test_searches_by_name_and_matches_exactly(self):
        client = _client([_summary("proj-2", id="ydid:keyring:x"), _summary("proj")])
        assert get_keyring_summary_by_name(client, "proj") == _summary("proj")
        client.keyring_client.get_keyrings.assert_called_once_with(
            KeyringSearch(name="proj")
        )

    def test_none_when_no_exact_match(self):
        client = _client([_summary("proj-2")])
        assert get_keyring_summary_by_name(client, "proj") is None


# ---------------------------------------------------------------------------
# yd-create
# ---------------------------------------------------------------------------


@pytest.fixture
def create_module():
    import yellowdog_cli.utils.resource_creation as create_module

    return create_module


def _run_create(create_module, client, confirm: bool, resource: dict, capsys):
    args = MagicMock(quiet=False, show_keyring_passwords=False)
    with (
        patch.object(wrapper_module, "CLIENT", client),
        patch.object(create_module, "_OPTIONS", args),
        patch.object(create_module, "confirmed", lambda _: confirm),
    ):
        create_module.create_keyring(_ctx(), resource)
    return capsys.readouterr().out


RESOURCE = {"resource": "Keyring", "name": "proj", "description": "new text"}


class TestCreateUpdatesInPlace:
    def test_existing_keyring_gets_its_description_updated(self, create_module, capsys):
        client = _client([_summary("proj")])
        client.keyring_client.update_keyring.return_value = Keyring(
            id=YDID, name="proj", description="new text"
        )

        out = _run_create(create_module, client, True, RESOURCE, capsys)

        client.keyring_client.update_keyring.assert_called_once_with(
            YDID, UpdateKeyringRequest(description="new text")
        )
        client.keyring_client.add_keyring.assert_not_called()
        client.keyring_client.delete_keyring_by_name.assert_not_called()
        assert "Updated Keyring 'proj'" in out

    def test_a_declined_update_changes_nothing(self, create_module, capsys):
        client = _client([_summary("proj")])

        _run_create(create_module, client, False, RESOURCE, capsys)

        client.keyring_client.update_keyring.assert_not_called()
        client.keyring_client.add_keyring.assert_not_called()
        client.keyring_client.delete_keyring_by_name.assert_not_called()

    def test_a_new_keyring_is_added(self, create_module, capsys):
        client = _client([])
        client.keyring_client.add_keyring.return_value = CreateKeyringResponse(
            keyring=Keyring(id=YDID, name="proj", description="new text"),
            keyringPassword="pw",
        )

        out = _run_create(create_module, client, True, RESOURCE, capsys)

        client.keyring_client.add_keyring.assert_called_once_with("proj", "new text")
        client.keyring_client.update_keyring.assert_not_called()
        assert "Created Keyring 'proj'" in out
        assert "pw" not in out  # the password stays redacted by default

    def test_a_keyring_added_earlier_in_the_run_is_found_afterwards(
        self, create_module, capsys
    ):
        # The lookup is cached, as the other name lookups are, so creation
        # must clear it: a second specification with the same name in one
        # run is an update, not a second add that the Platform rejects
        client = _client([])
        client.keyring_client.add_keyring.return_value = CreateKeyringResponse(
            keyring=Keyring(id=YDID, name="proj", description="new text"),
            keyringPassword="pw",
        )
        _run_create(create_module, client, True, RESOURCE, capsys)
        client.keyring_client.get_keyrings.return_value.list_all.return_value = [
            _summary("proj")
        ]

        _run_create(create_module, client, True, RESOURCE, capsys)

        client.keyring_client.add_keyring.assert_called_once()
        client.keyring_client.update_keyring.assert_called_once()


# ---------------------------------------------------------------------------
# yd-remove by YDID
# ---------------------------------------------------------------------------


@pytest.fixture
def remove_module():
    import yellowdog_cli.utils.resource_removal as remove_module

    return remove_module


def _run_remove(remove_module, client, ydid: str, capsys) -> tuple[bool, str]:
    with (
        patch.object(wrapper_module, "CLIENT", client),
        patch.object(remove_module, "confirmed", lambda _: True),
    ):
        result = remove_module.remove_resource_by_id(_ctx(), ydid)
    captured = capsys.readouterr()
    return result, " ".join((captured.out + captured.err).split())


class TestRemoveById:
    def test_fetches_by_id_and_deletes(self, remove_module, capsys):
        client = _client([])
        client.keyring_client.get_keyring.return_value = Keyring(
            id=YDID, name="proj", description="d"
        )

        result, out = _run_remove(remove_module, client, YDID, capsys)

        client.keyring_client.get_keyring.assert_called_once_with(YDID)
        client.keyring_client.delete_keyring_by_name.assert_called_once_with("proj")
        assert result is True
        assert "Removed Keyring" in out and YDID in out.replace("\n", "")

    def test_removal_by_id_clears_the_name_lookup(self, remove_module, capsys):
        # A Keyring removed by YDID must not be found by name afterwards in
        # the same run: the lookup is cached, and removal must clear it
        client = _client([_summary("proj")])
        client.keyring_client.get_keyring.return_value = Keyring(
            id=YDID, name="proj", description="d"
        )
        assert get_keyring_summary_by_name(client, "proj") is not None
        client.keyring_client.get_keyrings.return_value.list_all.return_value = []

        _run_remove(remove_module, client, YDID, capsys)

        assert get_keyring_summary_by_name(client, "proj") is None

    def test_an_unknown_id_is_not_found(self, remove_module, capsys):
        client = _client([])
        client.keyring_client.get_keyring.side_effect = HTTPError(
            response=MagicMock(status_code=404)
        )

        result, out = _run_remove(remove_module, client, YDID, capsys)

        client.keyring_client.delete_keyring_by_name.assert_not_called()
        assert result is not True
        assert "Cannot find Keyring" in out
