"""
Basic check that all the entrypoints are present, and can be invoked.
"""

import pytest
from cli_test_helpers import shell


@pytest.mark.parametrize(
    "cmd,expected",
    [
        ("yd-abort --help", 0),
        ("yd-boost --help", 0),
        ("yd-cloudwizard --help", 0),
        ("yd-copy --help", 0),
        ("yd-create --help", 0),
        ("yd-delete --help", 0),
        ("yd-download --help", 0),
        ("yd-finish --help", 0),
        ("yd-follow --help", 0),
        ("yd-format-json", 0),
        ("yd-help", 0),
        ("yd-hold --help", 0),
        ("yd-instantiate --help", 0),
        ("yd-jsonnet2json", 1),
        ("yd-list --help", 0),
        ("yd-nodeaction --help", 0),
        ("yd-ls --help", 0),
        ("yd-provision --help", 0),
        ("yd-remove --help", 0),
        ("yd-resize --help", 0),
        ("yd-show --help", 0),
        ("yd-shutdown --help", 0),
        ("yd-start --help", 0),
        ("yd-submit --help", 0),
        ("yd-terminate --help", 0),
        ("yd-upload --help", 0),
        ("yd-version", 0),
        ("yd-wait --help", 0),
    ],
)
def test_entrypoint(cmd, expected):
    assert shell(cmd).exit_code == expected
