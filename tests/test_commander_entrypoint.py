"""
Verify the yd-commander console script is registered, and that it exposes a
commander-specific command-line interface rather than the shared CLI parser.
"""

from importlib.metadata import entry_points

from cli_test_helpers import shell


def test_commander_entrypoint_registered():
    scripts = entry_points(group="console_scripts")
    names = {ep.name for ep in scripts}
    assert "yd-commander" in names


def test_commander_help_is_commander_specific():
    # `--help` must show Commander's own usage (an optional config-file
    # argument), NOT the shared CLI parser's options. It must also exit before
    # launching the GUI. Options like --secret/--pac/--print-pid belong to the
    # CLI parser and must not leak into the GUI's interface.
    result = shell("yd-commander --help")
    assert result.exit_code == 0
    out = result.stdout + result.stderr
    assert "yd-commander" in out
    assert "config_file" in out
    for cli_only in ("--secret", "--pac", "--print-pid", "--namespace"):
        assert cli_only not in out
