"""
'--hide-user-data': every 'userData' value in what yd-show, yd-list and the
dry runs of yd-provision, yd-instantiate and yd-create print is replaced by a
one-line summary, so a long boot script no longer swamps the output. Only the
copy shown is changed, never what is sent; and the three creators refuse the
option without '--dry-run', where they print no User Data at all.
"""

from json import loads
from types import SimpleNamespace

import pytest

import yellowdog_cli.utils.resource_creation as resource_creation
from yellowdog_cli.utils import output_settings
from yellowdog_cli.utils.args import CLIParser
from yellowdog_cli.utils.printing import (
    print_objects_as_json,
    print_yd_object,
    user_data_as_shown,
    user_data_hidden,
)
from yellowdog_cli.utils.results import flush_results, reset_results

SCRIPT = "#!/bin/sh\necho one\necho two\n"
SUMMARY = "<user data: 28 characters, 3 lines>"


def _settings(**overrides) -> SimpleNamespace:
    values = {"no_format": True, "hide_user_data": True}
    values.update(overrides)
    return SimpleNamespace(**values)


# ---------------------------------------------------------------------------
# The summary
# ---------------------------------------------------------------------------


class TestUserDataHidden:
    def test_a_script_is_summarised(self):
        assert user_data_hidden({"userData": SCRIPT}) == {"userData": SUMMARY}

    def test_one_line_is_singular(self):
        assert user_data_hidden({"userData": "#!/bin/sh"}) == {
            "userData": "<user data: 9 characters, 1 line>"
        }

    def test_it_is_found_at_any_depth(self):
        document = {
            "requirementTemplateUsage": {"userData": SCRIPT},
            "provisionStrategy": {
                "sources": [{"userData": SCRIPT}, {"name": "no user data"}]
            },
        }
        assert user_data_hidden(document) == {
            "requirementTemplateUsage": {"userData": SUMMARY},
            "provisionStrategy": {
                "sources": [{"userData": SUMMARY}, {"name": "no user data"}]
            },
        }

    def test_a_value_that_is_no_script_is_left_alone(self):
        # null, as the Platform returns it unset, says nothing a summary could
        assert user_data_hidden({"userData": None}) == {"userData": None}

    def test_the_original_is_unchanged(self):
        document = {"source": {"userData": SCRIPT}}
        user_data_hidden(document)
        assert document == {"source": {"userData": SCRIPT}}

    def test_as_shown_follows_the_option(self):
        document = {"userData": SCRIPT}
        with output_settings.configured(_settings(hide_user_data=False)):
            assert user_data_as_shown(document) is document
        with output_settings.configured(_settings()):
            assert user_data_as_shown(document) == {"userData": SUMMARY}


# ---------------------------------------------------------------------------
# yd-show and yd-list: the two places an SDK object is rendered
# ---------------------------------------------------------------------------


class TestRendering:
    def test_print_yd_object(self, capsys):
        with output_settings.configured(_settings()):
            print_yd_object({"name": "cst", "source": {"userData": SCRIPT}})
        assert loads(capsys.readouterr().out) == {
            "name": "cst",
            "source": {"userData": SUMMARY},
        }

    def test_print_yd_object_writes_the_summary_to_the_output_file(self, tmp_path):
        path = tmp_path / "out.json"
        with output_settings.configured(_settings(output_file=str(path))):
            print_yd_object({"userData": SCRIPT})
        assert loads(path.read_text(encoding="utf-8")) == {"userData": SUMMARY}

    def test_print_objects_as_json(self, capsys):
        with output_settings.configured(_settings()):
            print_objects_as_json([{"userData": SCRIPT}, {"userData": SCRIPT}])
        assert loads(capsys.readouterr().out) == [
            {"userData": SUMMARY},
            {"userData": SUMMARY},
        ]

    def test_with_strip_ids(self, capsys):
        with output_settings.configured(_settings(strip_ids=True)):
            print_objects_as_json([{"id": "ydid:crt:1", "userData": SCRIPT}])
        assert loads(capsys.readouterr().out) == [{"userData": SUMMARY}]

    def test_without_the_option_the_script_is_shown(self, capsys):
        with output_settings.configured(_settings(hide_user_data=False)):
            print_yd_object({"userData": SCRIPT})
        assert loads(capsys.readouterr().out) == {"userData": SCRIPT}


# ---------------------------------------------------------------------------
# yd-create's dry run
# ---------------------------------------------------------------------------


class TestCreateDryRun:
    @pytest.fixture(autouse=True)
    def _results(self):
        reset_results()
        yield
        reset_results()

    def _show(self, monkeypatch, json_output: bool) -> None:
        monkeypatch.setattr(
            resource_creation,
            "_OPTIONS",
            resource_creation.CreateOptions(dry_run=True, json_output=json_output),
        )
        resource_creation._show_dry_run_specification(
            "ComputeSourceTemplate", {"source": {"userData": SCRIPT}}
        )

    def test_printed(self, monkeypatch, capsys):
        with output_settings.configured(_settings()):
            self._show(monkeypatch, json_output=False)
        assert loads(capsys.readouterr().out) == {"source": {"userData": SUMMARY}}

    def test_recorded(self, monkeypatch, capsys):
        with output_settings.configured(_settings(json_output=True)):
            self._show(monkeypatch, json_output=True)
            flush_results()
        assert loads(capsys.readouterr().out) == [
            {"resource": "ComputeSourceTemplate", "source": {"userData": SUMMARY}}
        ]


# ---------------------------------------------------------------------------
# The option on the command line
# ---------------------------------------------------------------------------


class TestOption:
    @pytest.mark.parametrize("command", ["yd-provision", "yd-instantiate", "yd-create"])
    def test_refused_without_dry_run(self, command, capsys):
        with pytest.raises(SystemExit) as exit_info:
            CLIParser(command=command, argv=["--hide-user-data", "spec.json"])
        assert exit_info.value.code == 2
        assert "--hide-user-data applies only to --dry-run" in capsys.readouterr().err

    @pytest.mark.parametrize("command", ["yd-provision", "yd-instantiate", "yd-create"])
    def test_accepted_with_dry_run(self, command):
        parser = CLIParser(
            command=command, argv=["--dry-run", "--hide-user-data", "spec.json"]
        )
        assert parser.hide_user_data is True

    @pytest.mark.parametrize(
        "command, argv",
        [
            ("yd-show", ["ydid:cst:000000:1"]),
            ("yd-list", ["compute-source-templates"]),
        ],
    )
    def test_accepted_on_the_listing_commands(self, command, argv):
        parser = CLIParser(command=command, argv=["--hide-user-data", *argv])
        assert parser.hide_user_data is True
