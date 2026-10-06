"""
utils/specs/loading.py: the loader yd-submit (with '--json-raw'),
yd-provision, yd-instantiate and yd-nodeaction share -- the loader chosen by
extension, '--jsonnet-dry-run' refused for a file that is not Jsonnet before
anything is read, an extension refused or read as JSON as the command
allows, CSV expansion where asked for, and the schema check made unless
there is no family.
"""

from unittest.mock import MagicMock, patch

import pytest

import yellowdog_cli.utils.specs.loading as spec_loading
from yellowdog_cli.utils.specs.loading import CsvExpansion, load_specification
from yellowdog_cli.utils.specs.schema import Family

LOADERS = (
    "load_json_file_with_variable_substitutions",
    "load_jsonnet_file_with_variable_substitutions",
    "load_toml_file_with_variable_substitutions",
    "load_json_file_with_csv_task_expansion",
    "load_jsonnet_file_with_csv_task_expansion",
    "load_toml_file_with_csv_task_expansion",
)


@pytest.fixture
def loaders(monkeypatch) -> dict[str, MagicMock]:
    """
    Every loader replaced by a mock returning its own name, and the schema
    check by one returning what it is given.
    """
    mocks = {name: MagicMock(return_value={"loader": name}) for name in LOADERS}
    for name, mock in mocks.items():
        monkeypatch.setattr(spec_loading, name, mock)
    check = MagicMock(side_effect=lambda family, data, path, validate: data)
    monkeypatch.setattr(spec_loading, "check_specification", check)
    mocks["check_specification"] = check
    return mocks


def _loaded(path: str, **kwargs) -> str:
    kwargs.setdefault("family", Family.WORK_REQUIREMENT)
    return load_specification(path, "Work Requirement", **kwargs)["loader"]


class TestByExtension:
    @pytest.mark.parametrize(
        "path, loader",
        [
            ("wr.json", "load_json_file_with_variable_substitutions"),
            ("wr.JSON", "load_json_file_with_variable_substitutions"),
            ("wr.jsonnet", "load_jsonnet_file_with_variable_substitutions"),
            ("wr.Jsonnet", "load_jsonnet_file_with_variable_substitutions"),
        ],
    )
    def test_json_and_jsonnet(self, loaders, path, loader):
        assert _loaded(path) == loader

    def test_toml_only_where_the_command_takes_it(self, loaders):
        assert _loaded("wr.toml", toml=True) == (
            "load_toml_file_with_variable_substitutions"
        )
        with pytest.raises(ValueError, match=r"must end with '\.json' or '\.jsonnet'"):
            _loaded("wr.toml")

    def test_another_extension_is_refused_naming_those_taken(self, loaders):
        with pytest.raises(
            ValueError,
            match=(
                r"Work Requirement data file 'wr\.yaml' must end with"
                r" '\.json', '\.jsonnet', or '\.toml'"
            ),
        ):
            _loaded("wr.yaml", toml=True)
        for loader in LOADERS:
            loaders[loader].assert_not_called()

    def test_or_read_as_json_where_the_command_allows(self, loaders):
        # yd-provision, yd-instantiate and yd-nodeaction always have
        assert _loaded("wp.spec", other_extensions_as_json=True) == (
            "load_json_file_with_variable_substitutions"
        )

    def test_the_delimiters_are_passed_on(self, loaders):
        _loaded("wp.json", prefix="<<", postfix=">>")
        loaders["load_json_file_with_variable_substitutions"].assert_called_once_with(
            "wp.json", prefix="<<", postfix=">>"
        )


class TestJsonnetDryRun:
    def test_it_is_passed_to_the_jsonnet_loader(self, loaders):
        _loaded("wr.jsonnet", jsonnet_dry_run=True)
        call = loaders["load_jsonnet_file_with_variable_substitutions"].call_args
        assert call.kwargs["dry_run"] is True

    @pytest.mark.parametrize("path", ["wr.json", "wp.spec"])
    def test_a_file_that_is_not_jsonnet_is_refused_unread(self, loaders, path, capsys):
        # '--json-raw' used to ignore it for a JSON file; '-r' refused it
        with pytest.raises(ValueError, match="'--jsonnet-dry-run' can only be used"):
            _loaded(path, jsonnet_dry_run=True, other_extensions_as_json=True)
        for loader in LOADERS:
            loaders[loader].assert_not_called()
        assert "Loading" not in capsys.readouterr().out


class TestCsvExpansion:
    @pytest.mark.parametrize(
        "path, loader",
        [
            ("wr.json", "load_json_file_with_csv_task_expansion"),
            ("wr.jsonnet", "load_jsonnet_file_with_csv_task_expansion"),
            ("wr.toml", "load_toml_file_with_csv_task_expansion"),
        ],
    )
    def test_the_csv_loader_is_used(self, loaders, path, loader):
        csv = CsvExpansion(["a.csv"], "files", csv_only=True)
        assert _loaded(path, toml=True, csv=csv) == loader
        call = loaders[loader].call_args
        assert call.kwargs["csv_files"] == ["a.csv"]
        assert call.kwargs["files_directory"] == "files"
        assert call.kwargs["csv_only"] is True


class TestSchemaCheck:
    def test_the_document_is_checked_against_its_family(self, loaders):
        _loaded("wp.json", family=Family.WORKER_POOL, validate=True)
        loaders["check_specification"].assert_called_once_with(
            Family.WORKER_POOL,
            {"loader": "load_json_file_with_variable_substitutions"},
            "wp.json",
            True,
        )

    def test_no_family_no_check(self, loaders):
        # '--json-raw': Platform JSON, not a specification
        _loaded("raw.json", family=None)
        loaders["check_specification"].assert_not_called()


def test_it_says_what_it_is_loading(loaders, capsys):
    with patch.object(spec_loading, "print_info") as print_info:
        load_specification("na.json", "Node Action", family=Family.NODE_ACTIONS)
    print_info.assert_called_once_with("Loading Node Action data from: 'na.json'")
