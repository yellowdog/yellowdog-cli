"""
Tests for yd-nodeaction argument parsing.

CLIParser gates nodeaction-specific arguments on 'nodeaction' being present
in sys.argv[0], so tests set sys.argv[0] = 'yd-nodeaction' and control
sys.argv[1:] for each case.
"""

import sys
from unittest.mock import patch

import pytest

from yellowdog_cli.utils.args import CLIParser


def _make_parser(*args: str) -> CLIParser:
    """
    Instantiate CLIParser with sys.argv faked to ['yd-nodeaction', *args].
    """
    with patch.object(sys, "argv", ["yd-nodeaction", *args]):
        return CLIParser()


class TestNodeActionActionsArg:
    """
    --actions / -S sets node_action_spec; absent → None.
    """

    def test_actions_long_form(self):
        p = _make_parser("--actions", "my_actions.json")
        assert p.node_action_spec == "my_actions.json"

    def test_actions_short_form(self):
        p = _make_parser("-S", "my_actions.json")
        assert p.node_action_spec == "my_actions.json"

    def test_actions_absent_with_status_returns_none(self):
        p = _make_parser("--status")
        assert p.node_action_spec is None

    def test_actions_absent_without_status_is_a_usage_error(self):
        with pytest.raises(SystemExit) as raised:
            _make_parser()
        assert raised.value.code == 2

    def test_actions_accepts_jsonnet_extension(self):
        p = _make_parser("--actions", "actions.jsonnet")
        assert p.node_action_spec == "actions.jsonnet"

    def test_spec_flag_not_recognised(self):
        """--spec must no longer be a valid flag."""
        with pytest.raises(SystemExit):
            _make_parser("--spec", "actions.json")
