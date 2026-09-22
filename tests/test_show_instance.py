"""
Unit tests for the Instance ('cr_id.instance_id') support in show.py.

Covers:
  - resolve_details            (routing of the dotted instance form)
  - _resolve_instance_details  (lookup and error paths)
"""

from unittest.mock import MagicMock, patch

import pytest

import yellowdog_cli.show as show_module
from yellowdog_cli.show import _resolve_instance_details, resolve_details

CR_ID = "ydid:compreq:d9c548:98879b5a-9192-4a56-ad25-fc1330e49185"
NODE_ID = "ydid:node:d9c548:f9d5a10e-5b0e-4b76-b50f-d2bbac0a5cb8"
INSTANCE_ID = "i-0123456789abcdef0"
INSTANCE_SPEC = f"{CR_ID}.{INSTANCE_ID}"
# OCI instance IDs (OCIDs) contain dots of their own
OCI_INSTANCE_ID = (
    "ocid1.instance.oc1.uk-london-1."
    "anwgiljtbfkcyvycib2ubsewuwqqffx2jzyp7dolkhxanfvdsgvjzjrytepa"
)


def _make_args() -> MagicMock:
    mock_args = MagicMock()
    mock_args.strip_ids = False
    mock_args.substitute_ids = False
    mock_args.show_token = False
    return mock_args


# ---------------------------------------------------------------------------
# resolve_details: routing
# ---------------------------------------------------------------------------


class TestRouting:
    @pytest.mark.parametrize("instance_id", [INSTANCE_ID, OCI_INSTANCE_ID])
    def test_instance_spec_routes_to_instance_details(self, instance_id):
        with (
            patch.object(show_module, "ARGS_PARSER", _make_args()),
            patch.object(show_module, "_resolve_instance_details") as mock_instance,
        ):
            resolve_details(f"{CR_ID}.{instance_id}")

        mock_instance.assert_called_once_with(CR_ID, instance_id)

    @pytest.mark.parametrize("ydid", [CR_ID, NODE_ID])
    def test_plain_ydid_does_not_route_to_instance_details(self, ydid):
        with (
            patch.object(show_module, "ARGS_PARSER", _make_args()),
            patch.object(show_module, "CLIENT", MagicMock()),
            patch.object(show_module, "_resolve_instance_details") as mock_instance,
            patch.object(show_module, "print_info"),
        ):
            resolve_details(ydid)

        mock_instance.assert_not_called()

    def test_non_cr_prefix_with_dot_is_not_an_instance_spec(self):
        # A Node YDID with a dotted suffix is not an instance specification
        with (
            patch.object(show_module, "ARGS_PARSER", _make_args()),
            patch.object(show_module, "_resolve_instance_details") as mock_instance,
            patch.object(show_module, "print_error") as mock_error,
        ):
            assert resolve_details(f"{NODE_ID}.{INSTANCE_ID}") is None

        mock_instance.assert_not_called()
        mock_error.assert_called_once()


# ---------------------------------------------------------------------------
# _resolve_instance_details
# ---------------------------------------------------------------------------


class TestResolveInstanceDetails:
    def _call(
        self,
        instance: MagicMock | None = None,
        lookup_raises: Exception | None = None,
        get_cr_raises: Exception | None = None,
    ) -> tuple:
        mock_lookup = MagicMock()
        if lookup_raises is not None:
            mock_lookup.side_effect = lookup_raises
        else:
            mock_lookup.return_value = instance

        mock_client = MagicMock()
        if get_cr_raises is not None:
            mock_client.compute_client.get_compute_requirement_by_id.side_effect = (
                get_cr_raises
            )

        with (
            patch.object(show_module, "ARGS_PARSER", _make_args()),
            patch.object(show_module, "CLIENT", mock_client),
            patch.object(show_module, "get_instance_by_id", mock_lookup),
            patch.object(show_module, "print_error") as mock_error,
            patch.object(show_module, "print_info"),
        ):
            resolved = _resolve_instance_details(CR_ID, INSTANCE_ID)

        return mock_lookup, resolved, mock_error

    def test_instance_found_is_returned(self):
        instance = MagicMock()
        mock_lookup, resolved, mock_error = self._call(instance=instance)

        assert mock_lookup.call_args.args[1:] == (CR_ID, INSTANCE_ID)
        assert resolved == [(instance, None)]
        mock_error.assert_not_called()

    def test_instance_not_found_in_existing_cr_reports_instance_error(self):
        # An existing Compute Requirement without this Instance: the search
        # returns nothing, which must not be reported as a missing CR
        mock_lookup, resolved, mock_error = self._call(instance=None)
        mock_lookup.assert_called_once()
        assert resolved is None
        mock_error.assert_called_once()
        message = mock_error.call_args.args[0]
        assert f"Instance ID '{INSTANCE_ID}' not found" in message

    def test_compute_requirement_not_found_reports_cr_error_without_lookup(self):
        with patch.object(show_module, "is_http_not_found", return_value=True):
            mock_lookup, resolved, mock_error = self._call(
                get_cr_raises=RuntimeError("404 not found")
            )
        mock_lookup.assert_not_called()
        assert resolved is None
        mock_error.assert_called_once()
        message = mock_error.call_args.args[0]
        assert f"Compute Requirement ID '{CR_ID}' not found" in message
        assert INSTANCE_ID not in message

    def test_other_cr_exception_reports_error(self):
        with patch.object(show_module, "is_http_not_found", return_value=False):
            _, resolved, mock_error = self._call(
                get_cr_raises=RuntimeError("API failure")
            )
        assert resolved is None
        mock_error.assert_called_once()
        assert "API failure" in mock_error.call_args.args[0]

    def test_instance_lookup_exception_reports_error(self):
        _, resolved, mock_error = self._call(
            lookup_raises=RuntimeError("search failure")
        )
        assert resolved is None
        mock_error.assert_called_once()
        assert "search failure" in mock_error.call_args.args[0]
