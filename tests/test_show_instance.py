"""
Unit tests for the Instance ('cr_id.instance_id') support in show.py.

Covers:
  - show_details              (routing of the dotted instance form)
  - _show_instance_details    (lookup, error paths, JSON-list indentation)
"""

from unittest.mock import MagicMock, patch

import pytest

import yellowdog_cli.show as show_module
from yellowdog_cli.show import _show_instance_details, show_details

CR_ID = "ydid:compreq:d9c548:98879b5a-9192-4a56-ad25-fc1330e49185"
NODE_ID = "ydid:node:d9c548:f9d5a10e-5b0e-4b76-b50f-d2bbac0a5cb8"
INSTANCE_ID = "i-0123456789abcdef0"
INSTANCE_SPEC = f"{CR_ID}.{INSTANCE_ID}"


def _make_args() -> MagicMock:
    mock_args = MagicMock()
    mock_args.strip_ids = False
    mock_args.substitute_ids = False
    mock_args.show_token = False
    return mock_args


# ---------------------------------------------------------------------------
# show_details: routing
# ---------------------------------------------------------------------------


class TestRouting:
    def test_instance_spec_routes_to_instance_details(self):
        with (
            patch.object(show_module, "ARGS_PARSER", _make_args()),
            patch.object(show_module, "_show_instance_details") as mock_instance,
        ):
            show_details(INSTANCE_SPEC, initial_indent=2, with_final_comma=True)

        mock_instance.assert_called_once_with(
            CR_ID, INSTANCE_ID, initial_indent=2, with_final_comma=True
        )

    @pytest.mark.parametrize("ydid", [CR_ID, NODE_ID])
    def test_plain_ydid_does_not_route_to_instance_details(self, ydid):
        with (
            patch.object(show_module, "ARGS_PARSER", _make_args()),
            patch.object(show_module, "CLIENT", MagicMock()),
            patch.object(show_module, "_show_instance_details") as mock_instance,
            patch.object(show_module, "print_yd_object"),
            patch.object(show_module, "print_info"),
        ):
            show_details(ydid)

        mock_instance.assert_not_called()

    def test_non_cr_prefix_with_dot_is_not_an_instance_spec(self):
        # A Node YDID with a dotted suffix is not an instance specification
        with (
            patch.object(show_module, "ARGS_PARSER", _make_args()),
            patch.object(show_module, "_show_instance_details") as mock_instance,
            patch.object(show_module, "print_error") as mock_error,
        ):
            show_details(f"{NODE_ID}.{INSTANCE_ID}")

        mock_instance.assert_not_called()
        mock_error.assert_called_once()


# ---------------------------------------------------------------------------
# _show_instance_details
# ---------------------------------------------------------------------------


class TestShowInstanceDetails:
    def _call(
        self,
        instance: MagicMock | None = None,
        lookup_raises: Exception | None = None,
        initial_indent: int = 0,
        with_final_comma: bool = False,
    ) -> tuple:
        mock_lookup = MagicMock()
        if lookup_raises is not None:
            mock_lookup.side_effect = lookup_raises
        else:
            mock_lookup.return_value = instance

        with (
            patch.object(show_module, "ARGS_PARSER", _make_args()),
            patch.object(show_module, "CLIENT", MagicMock()),
            patch.object(show_module, "get_instance_by_id", mock_lookup),
            patch.object(show_module, "print_yd_object") as mock_print_object,
            patch.object(show_module, "print_error") as mock_error,
            patch.object(show_module, "print_info"),
        ):
            _show_instance_details(
                CR_ID,
                INSTANCE_ID,
                initial_indent=initial_indent,
                with_final_comma=with_final_comma,
            )

        return mock_lookup, mock_print_object, mock_error

    def test_instance_found_is_printed(self):
        instance = MagicMock()
        mock_lookup, mock_print_object, mock_error = self._call(instance=instance)

        assert mock_lookup.call_args.args[1:] == (CR_ID, INSTANCE_ID)
        mock_print_object.assert_called_once_with(
            instance, initial_indent=0, with_final_comma=False
        )
        mock_error.assert_not_called()

    def test_json_list_indentation_passed_through(self):
        _, mock_print_object, _ = self._call(
            instance=MagicMock(), initial_indent=2, with_final_comma=True
        )
        assert mock_print_object.call_args.kwargs == {
            "initial_indent": 2,
            "with_final_comma": True,
        }

    def test_instance_not_found_prints_error(self):
        _, mock_print_object, mock_error = self._call(instance=None)
        mock_print_object.assert_not_called()
        mock_error.assert_called_once()
        assert INSTANCE_ID in mock_error.call_args.args[0]

    def test_compute_requirement_not_found_prints_error(self):
        with patch.object(show_module, "is_http_not_found", return_value=True):
            _, mock_print_object, mock_error = self._call(
                lookup_raises=RuntimeError("404 not found")
            )
        mock_print_object.assert_not_called()
        mock_error.assert_called_once()
        assert CR_ID in mock_error.call_args.args[0]

    def test_other_lookup_exception_prints_error(self):
        with patch.object(show_module, "is_http_not_found", return_value=False):
            _, mock_print_object, mock_error = self._call(
                lookup_raises=RuntimeError("API failure")
            )
        mock_print_object.assert_not_called()
        mock_error.assert_called_once()
        assert "API failure" in mock_error.call_args.args[0]
