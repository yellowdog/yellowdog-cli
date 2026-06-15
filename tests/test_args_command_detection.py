"""
CLIParser detects the command from sys.argv[0]. Detection must use the
basename only: a command name appearing in the *install path* (e.g.
~/Downloads/tools/) must not register that command's arguments.
"""

import sys
from unittest.mock import patch

import pytest

from yellowdog_cli.utils.args import CLIParser


def _make_parser(argv0: str, *args: str) -> CLIParser:
    with patch.object(sys, "argv", [argv0, *args]):
        return CLIParser()


class TestCommandDetectionUsesBasename:
    @pytest.mark.parametrize(
        "poisoned_path",
        [
            "/home/user/Downloads/tools/yd-version",
            "/opt/lists/created/yd-version",
            "/home/user/submit/yd-version",
        ],
    )
    def test_command_names_in_path_ignored(self, poisoned_path):
        # Would previously register download/list/create/submit arguments
        # (including conflicting positionals) and fail to parse
        parser = _make_parser(poisoned_path)
        assert parser.worker_pool_name is None

    def test_command_specific_args_still_registered(self):
        parser = _make_parser("/home/user/Downloads/yd-resize", "my-pool", "5")
        assert parser.worker_pool_name == "my-pool"

    def test_command_specific_args_not_leaked_by_path(self):
        # 'resize' in the path must not add the resize positionals
        with pytest.raises(SystemExit):
            _make_parser("/home/user/resize/yd-version", "my-pool", "5")
