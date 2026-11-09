"""
yd resource export (resource_export.py): the command, its options and its
verb; the work is utils/resource_export.py's.
"""

from types import SimpleNamespace

import pytest

import yellowdog_cli.resource_export as export_command
from yellowdog_cli.utils import output_settings
from yellowdog_cli.utils.args import CLIParser
from yellowdog_cli.utils.command_registry import COMMANDS, ToolKind
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import ET_CREDENTIALS
from yellowdog_cli.utils.exit_codes import ExitCode
from yellowdog_cli.utils.noun_registry import NOUN_COMMANDS, NOUNS_BY_NAME
from yellowdog_cli.utils.resource_export import ExportOptions, chosen_types
from yellowdog_cli.utils.resource_exporters import ALL_TYPES, DEFAULT_TYPES


def _parse(*argv: str) -> CLIParser:
    return CLIParser(command="yd resource export", argv=list(argv))


def _error(capsys, *argv: str) -> str:
    with pytest.raises(SystemExit) as exit_:
        _parse(*argv)
    assert exit_.value.code == ExitCode.USAGE
    return capsys.readouterr().err


def test_export_is_a_resource_verb_and_read_only():
    command = COMMANDS["yd-resource-export"]
    assert command.script is False and command.tool is ToolKind.READ_ONLY
    assert not command.requires_namespace_and_tag
    assert NOUN_COMMANDS["yd resource export"].runs == "yd-resource-export"
    assert NOUNS_BY_NAME["resource"].verb("export") is not None


def test_a_type_prefix_is_resolved():
    assert _parse("image").args.export_types == ["image-families"]


def test_a_full_type_that_prefixes_another_is_taken_whole():
    assert _parse("users").args.export_types == ["users"]


@pytest.mark.parametrize(
    "singular, plural",
    [
        ("namespace", "namespaces"),
        ("keyring", "keyrings"),
        ("credential", "credentials"),
        ("image-family", "image-families"),
        ("namespace-policy", "namespace-policies"),
        ("user", "users"),
    ],
)
def test_a_singular_type_is_taken_as_its_plural(singular, plural):
    assert _parse(singular).args.export_types == [plural]


def test_an_ambiguous_prefix_is_refused(capsys):
    assert "ambiguous" in _error(capsys, "compute")


def test_an_unknown_type_is_refused_with_a_suggestion(capsys):
    assert "did you mean 'keyrings'" in _error(capsys, "keyrngs")


def test_all_with_types_is_refused(capsys):
    assert "--all" in _error(capsys, "--all", "keyrings")


def test_a_namespace_in_name_is_refused(capsys):
    assert "-n" in _error(capsys, "--name", "render/*")


@pytest.mark.parametrize("argv", [["-n", ""], ["-n"], ["--namespace="]])
def test_an_empty_namespace_is_refused(capsys, argv):
    assert "empty" in _error(capsys, *argv)


def test_the_options_are_read():
    parser = _parse(
        "-o", "out.json", "--name", "r-*", "--with-dependencies", "--json", "keyrings"
    )
    assert parser.export_file == "out.json" and parser.name_glob == "r-*"
    assert parser.with_dependencies and parser.json_output
    assert not parser.all_types and not parser.include_credentials


def test_the_export_file_is_not_where_the_json_records_go():
    # The universal '--output-file' sends what the command prints (the
    # '--json' records) to a file: the export's own '-o' must not, or the
    # records would replace the specifications written there
    parser = _parse("-o", "out.json", "--json", "keyrings")
    with output_settings.configured(parser):
        assert output_settings.OUTPUT.output_file is None


def test_with_no_types_the_default_types_are_chosen():
    assert chosen_types(ExportOptions(types=())) == DEFAULT_TYPES


def test_all_chooses_every_type_but_credentials():
    assert chosen_types(ExportOptions(types=(), all_types=True)) == ALL_TYPES
    assert ET_CREDENTIALS not in ALL_TYPES


def test_include_credentials_adds_credentials():
    options = ExportOptions(types=(), all_types=True, include_credentials=True)
    assert ET_CREDENTIALS in chosen_types(options)


def test_chosen_types_are_in_order_without_duplicates():
    chosen = chosen_types(ExportOptions(types=("users", "keyrings", "users")))
    assert chosen == ("keyrings", "users")


def test_main_hands_the_options_to_export_resources(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        export_command, "export_resources", lambda ctx, options: seen.update(o=options)
    )
    args = SimpleNamespace(
        export_types=["keyrings"],
        all_types=False,
        name_glob="k*",
        interactive=None,
        with_dependencies=True,
        include_credentials=None,
        export_file="x.json",
    )
    inner = next(
        c.cell_contents
        for c in export_command.main.__closure__
        if callable(c.cell_contents) and c.cell_contents.__name__ == "main"
    )
    inner(RunContext(args=args, config=None, client=None))
    assert seen["o"] == ExportOptions(
        types=("keyrings",),
        name_glob="k*",
        with_dependencies=True,
        output_file="x.json",
    )
