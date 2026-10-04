"""
The MCP tool catalogue (yellowdog_cli/mcp/tools.py): every tool command has
one tool built from its registry options, the option kinds map to JSON
Schema as the spec's table says, and a call's arguments become the child's
command line deterministically. Needs neither the 'mcp' extra nor the SDK.
"""

import json
import os
import stat
import subprocess
import sys

import pytest

from yellowdog_cli.mcp import tools as tools_module
from yellowdog_cli.mcp.tools import (
    OUTPUT_SCHEMA,
    ServerSettings,
    ToolArgumentError,
    build_tools,
    fixed_args,
    timeout_of,
    to_argv,
    tool_named,
)
from yellowdog_cli.utils.command_registry import (
    COMMANDS,
    MCP_EXCLUDED_OPTIONS,
    ToolKind,
)
from yellowdog_cli.utils.settings import (
    MCP_FOLLOW_TIMEOUT_SECONDS,
    MCP_TOOL_TIMEOUT_SECONDS,
)

TOOLS = {t.name: t for t in build_tools()}


class TestCatalogue:
    def test_one_tool_per_tool_command(self):
        expected = {
            n.replace("-", "_")
            for n, c in COMMANDS.items()
            if c.tool is not ToolKind.NONE and n != "yd-rm"
        }
        assert set(TOOLS) == expected
        assert "yd_rm" not in TOOLS and "yd_help" not in TOOLS

    def test_names_follow_the_sdk_rule(self):
        import re

        for name in TOOLS:
            assert re.fullmatch(r"[A-Za-z0-9._-]{1,128}", name), name

    def test_every_option_is_in_a_schema_or_excluded(self):
        # A new option is placed on purpose, one way or the other
        for tool in TOOLS.values():
            properties = tool.input_schema["properties"]
            for option in tool.command.flat_options():
                if option.name in MCP_EXCLUDED_OPTIONS:
                    continue
                assert _property_name(option) in properties, (tool.name, option.name)

    def test_excluded_options_are_in_no_schema(self):
        for tool in TOOLS.values():
            for option in tool.command.flat_options():
                if option.name in MCP_EXCLUDED_OPTIONS:
                    assert (
                        _property_name(option) not in tool.input_schema["properties"]
                    ), (
                        tool.name,
                        option.name,
                    )

    def test_annotations_follow_the_kind(self):
        assert TOOLS["yd_list"].annotations == {
            "readOnlyHint": True,
            "openWorldHint": True,
        }
        assert TOOLS["yd_submit"].annotations == {
            "destructiveHint": False,
            "openWorldHint": True,
        }
        assert TOOLS["yd_cancel"].annotations == {
            "destructiveHint": True,
            "openWorldHint": True,
        }

    def test_descriptions(self):
        assert TOOLS["yd_submit"].description == COMMANDS["yd-submit"].tool_description
        assert TOOLS["yd_abort"].description.startswith("Abort running Tasks")
        assert "yd-abort" in TOOLS["yd_abort"].description
        assert TOOLS["yd_abort"].title == "Abort running Tasks"

    def test_the_download_description_names_the_prefix(self):
        # remote_paths are resolved under the prefix, which defaults to
        # '<namespace>/<tag>' (load_config_data_client()), and no_prefix (a
        # real property of the tool) drops it, leaving the bucket root
        description = TOOLS["yd_download"].description
        assert "defaults to '<namespace>/<tag>'" in description
        assert "bucket root" in description
        assert "no_prefix" in description
        assert "no_prefix" in TOOLS["yd_download"].input_schema["properties"]
        assert "'<tag>*'" not in description

    def test_every_schema_is_closed_and_has_a_timeout(self):
        for tool in TOOLS.values():
            schema = tool.input_schema
            assert schema["type"] == "object"
            assert schema["additionalProperties"] is False
            timeout = schema["properties"]["timeout_seconds"]
            assert timeout["type"] == "integer" and timeout["minimum"] == 1
            assert timeout["default"] == tool.timeout_default

    def test_follow_has_the_shorter_timeout(self):
        assert TOOLS["yd_follow"].timeout_default == MCP_FOLLOW_TIMEOUT_SECONDS
        assert TOOLS["yd_list"].timeout_default == MCP_TOOL_TIMEOUT_SECONDS

    def test_output_schema(self):
        assert OUTPUT_SCHEMA["required"] == ["exitCode"]
        assert set(OUTPUT_SCHEMA["properties"]) == {
            "result",
            "exitCode",
            "stopped",
            "stderr",
        }

    def test_tool_named(self):
        assert tool_named("yd_list") is TOOLS["yd_list"]
        assert tool_named("nope") is None


class TestSchemaMapping:
    def _prop(self, tool: str, name: str) -> dict:
        return TOOLS[tool].input_schema["properties"][name]

    def test_store_true_is_a_boolean(self):
        assert self._prop("yd_cancel", "abort") == {
            "type": "boolean",
            "description": COMMANDS["yd-cancel"].option_named("--abort").kwargs["help"],
        }
        assert "abort" not in TOOLS["yd_cancel"].input_schema.get("required", [])

    def test_int_is_an_integer_and_positive_int_has_a_minimum(self):
        assert self._prop("yd_doctor", "timeout")["type"] == "integer"
        assert self._prop("yd_resize", "worker_pool_size")["type"] == "integer"
        positive = next(
            (t, o)
            for t in TOOLS.values()
            for o in t.command.flat_options()
            if getattr(o.kwargs.get("type"), "__name__", "") == "positive_int"
        )
        tool, option = positive
        assert tool.input_schema["properties"][_property_name(option)]["minimum"] == 1

    def test_non_negative_int_has_a_minimum_of_zero(self):
        # A Worker Pool or Compute Requirement can be resized to nothing
        assert self._prop("yd_resize", "worker_pool_size")["minimum"] == 0

    def test_strings_lists_and_appends(self):
        assert self._prop("yd_cancel", "namespace")["type"] == "string"
        assert self._prop("yd_cancel", "work_requirements") == {
            "type": "array",
            "items": {"type": "string"},
            "description": COMMANDS["yd-cancel"]
            .option_named("work_requirements")
            .kwargs["help"],
        }
        assert self._prop("yd_cancel", "variable")["type"] == "array"  # action='append'

    def test_choices_and_defaults(self):
        sort = self._prop("yd_cancel", "sort")
        assert sort["enum"] == ["name", "created", "status", "namespace"]
        assert sort["default"] == "name"

    def test_dest_names_the_property(self):
        assert "status_filter" in TOOLS["yd_list"].input_schema["properties"]
        assert "name_glob" in TOOLS["yd_list"].input_schema["properties"]

    def test_entity_type_is_an_enum_of_full_names(self):
        from yellowdog_cli.utils.command_registry import ENTITY_TYPES

        prop = self._prop("yd_list", "entity_type")
        assert prop["enum"] == list(ENTITY_TYPES)
        assert "entity_type" in TOOLS["yd_list"].input_schema["required"]

    def test_required_positionals(self):
        assert (
            "remote_paths" in TOOLS["yd_download"].input_schema["required"]
        )  # nargs='+'
        assert "entity_type" in TOOLS["yd_list"].input_schema["required"]  # nargs=None
        assert "yellowdog_ids" in TOOLS["yd_show"].input_schema["required"]  # '+'
        assert "yellowdog_ids" in TOOLS["yd_wait"].input_schema["required"]  # '+'
        # nargs='?' for --which-rclone alone, which no tool offers
        assert "src_path" in TOOLS["yd_copy"].input_schema["required"]
        assert "dst_path" in TOOLS["yd_copy"].input_schema["required"]

    def test_exclusive_pair_is_refused_by_schema(self):
        assert {"not": {"required": ["destination", "into"]}} in TOOLS[
            "yd_download"
        ].input_schema["allOf"]

    def test_specification_arguments(self):
        for name in ("yd_submit", "yd_provision", "yd_instantiate"):
            prop = TOOLS[name].input_schema["properties"]["specification"]
            assert prop["oneOf"] == [{"type": "string"}, {"type": "object"}]
            assert TOOLS[name].specification_argument == "specification"
            assert (
                "work_requirement_file_positional"
                not in TOOLS[name].input_schema["properties"]
            )
        for name in ("yd_create", "yd_remove"):
            prop = TOOLS[name].input_schema["properties"]["specifications"]
            assert prop["type"] == "array"
            assert prop["items"]["oneOf"] == [{"type": "string"}, {"type": "object"}]
            assert "specifications" in TOOLS[name].input_schema["required"]
        assert TOOLS["yd_list"].specification_argument is None


class TestFixedArgs:
    def test_with_a_config_file(self, tmp_path):
        settings = ServerSettings(
            config_file=str(tmp_path / "config.toml"),
            namespace="ns",
            tag="t",
            variables=("a=1",),
        )
        assert fixed_args(COMMANDS["yd-cancel"], settings) == [
            "-c",
            "config.toml",
            "--nf",
            "--json",
            "--yes",
            "-n",
            "ns",
            "-t",
            "t",
            "-v",
            "a=1",
        ]
        assert settings.working_dir == str(tmp_path)

    def test_without_a_config_file(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        settings = ServerSettings(
            config_file=None, namespace=None, tag=None, variables=()
        )
        assert fixed_args(COMMANDS["yd-cancel"], settings) == [
            "--nc",
            "--nf",
            "--json",
            "--yes",
        ]
        assert settings.working_dir == str(tmp_path)

    def test_only_the_options_the_command_has(self):
        settings = ServerSettings(
            config_file=None, namespace="ns", tag="t", variables=("a=1",)
        )
        # yd-show has no --yes; yd-show and yd-variables print JSON without
        # a flag; yd-wait has no namespace or tag; yd-version parses its own
        # command line and takes --json alone
        assert "--yes" not in fixed_args(COMMANDS["yd-show"], settings)
        assert "--json" not in fixed_args(COMMANDS["yd-show"], settings)
        assert "--json" not in fixed_args(COMMANDS["yd-variables"], settings)
        assert "-n" not in fixed_args(COMMANDS["yd-wait"], settings)
        assert fixed_args(COMMANDS["yd-version"], settings) == ["--json"]

    def test_the_self_printing_commands_are_quiet(self):
        # yd-show and yd-variables print their own JSON with no --json option,
        # so only --quiet keeps the wrapper's 'Done' off their stdout
        settings = ServerSettings(
            config_file=None, namespace=None, tag=None, variables=()
        )
        assert "--quiet" in fixed_args(COMMANDS["yd-show"], settings)
        assert "--quiet" in fixed_args(COMMANDS["yd-variables"], settings)
        assert "--quiet" not in fixed_args(COMMANDS["yd-list"], settings)


class TestToArgv:
    def test_every_argument_kind(self, tmp_path):
        argv, files = to_argv(
            TOOLS["yd_cancel"],
            {
                "abort": True,
                "sort": "created",
                "variable": ["a=1", "b=2"],
                "work_requirements": ["wr-1", "wr-*"],
                "timeout_seconds": 10,
            },
            str(tmp_path),
        )
        # Options in registry order, then '--' and the positionals;
        # timeout_seconds is the server's, not the command's
        assert argv == [
            "--sort=created",
            "--variable=a=1",
            "--variable=b=2",
            "-a",
            "--",
            "wr-1",
            "wr-*",
        ]
        assert files == []

    def test_a_false_boolean_and_an_absent_argument_add_nothing(self, tmp_path):
        argv, _ = to_argv(TOOLS["yd_cancel"], {"abort": False}, str(tmp_path))
        assert argv == []

    def test_integers_and_appends(self, tmp_path):
        argv, _ = to_argv(TOOLS["yd_doctor"], {"timeout": 30}, str(tmp_path))
        assert argv == ["--timeout=30"]
        argv, _ = to_argv(
            TOOLS["yd_wait"],
            {"variable": ["a=1"], "yellowdog_ids": ["ydid:x"]},
            str(tmp_path),
        )
        assert argv == ["--variable=a=1", "--", "ydid:x"]

    def test_a_flag_as_a_value_stays_a_value(self, tmp_path):
        # A value is one argv entry joined to its long flag, so argparse
        # cannot take a value that looks like a flag as that flag: as two
        # entries, '--tag --debug' on a nargs='?' option turned --debug on
        argv, _ = to_argv(TOOLS["yd_cancel"], {"tag": "--debug"}, str(tmp_path))
        assert argv == ["--tag=--debug"]
        argv, _ = to_argv(TOOLS["yd_cancel"], {"variable": ["--yes"]}, str(tmp_path))
        assert argv == ["--variable=--yes"]

    def test_a_specification_path_is_passed_as_given(self, tmp_path):
        argv, files = to_argv(
            TOOLS["yd_submit"], {"specification": "wr.json"}, str(tmp_path)
        )
        assert argv == ["--", "wr.json"] and files == []

    def test_an_inline_specification_is_written_to_the_working_directory(
        self, tmp_path
    ):
        spec = {"name": "wr", "taskGroups": []}
        argv, files = to_argv(
            TOOLS["yd_submit"], {"specification": spec}, str(tmp_path)
        )
        assert len(files) == 1 and files[0].parent == tmp_path
        assert files[0].name.startswith(".yd-mcp-") and files[0].suffix == ".json"
        assert argv == ["--", files[0].name]
        assert json.loads(files[0].read_text()) == spec

    def test_several_specifications_mixed(self, tmp_path):
        argv, files = to_argv(
            TOOLS["yd_create"],
            {"specifications": ["a.json", {"resource": "Keyring", "name": "k"}]},
            str(tmp_path),
        )
        assert len(files) == 1
        assert argv == ["--", "a.json", files[0].name]

    def test_an_unknown_argument_is_refused(self, tmp_path):
        with pytest.raises(ToolArgumentError, match="nope"):
            to_argv(TOOLS["yd_cancel"], {"nope": 1}, str(tmp_path))

    def test_a_wrong_type_is_refused(self, tmp_path):
        with pytest.raises(ToolArgumentError, match="abort"):
            to_argv(TOOLS["yd_cancel"], {"abort": "yes"}, str(tmp_path))
        with pytest.raises(ToolArgumentError, match="work_requirements"):
            to_argv(TOOLS["yd_cancel"], {"work_requirements": "wr-1"}, str(tmp_path))
        with pytest.raises(ToolArgumentError, match="sort"):
            to_argv(TOOLS["yd_cancel"], {"sort": "size"}, str(tmp_path))

    def test_a_missing_required_argument_is_refused(self, tmp_path):
        with pytest.raises(ToolArgumentError, match="remote_paths"):
            to_argv(TOOLS["yd_download"], {}, str(tmp_path))

    def test_both_of_an_exclusive_pair_are_refused(self, tmp_path):
        with pytest.raises(
            ToolArgumentError, match=r"destination.*into|into.*destination"
        ):
            to_argv(
                TOOLS["yd_download"],
                {"remote_paths": ["x"], "destination": "a", "into": "b"},
                str(tmp_path),
            )

    def test_nothing_is_written_when_refused(self, tmp_path):
        with pytest.raises(ToolArgumentError):
            to_argv(
                TOOLS["yd_create"],
                {"specifications": [{"resource": "Keyring"}], "nope": 1},
                str(tmp_path),
            )
        assert list(tmp_path.iterdir()) == []


class TestTimeout:
    def test_default_and_given(self):
        assert timeout_of(TOOLS["yd_list"], {}) == MCP_TOOL_TIMEOUT_SECONDS
        assert timeout_of(TOOLS["yd_follow"], {}) == MCP_FOLLOW_TIMEOUT_SECONDS
        assert timeout_of(TOOLS["yd_list"], {"timeout_seconds": 7}) == 7

    def test_a_bad_timeout_is_refused(self):
        with pytest.raises(ToolArgumentError, match="timeout_seconds"):
            timeout_of(TOOLS["yd_list"], {"timeout_seconds": 0})


def _property_name(option) -> str:
    kwargs = option.kwargs
    if "dest" in kwargs:
        return kwargs["dest"]
    if option.positional:
        return option.flags[0]
    return option.name[2:].replace("-", "_")


class TestUnknownOptionKinds:
    # A kind the mapping does not know must be handled on purpose, not
    # emitted as 'flag value'
    @pytest.mark.parametrize(
        "kwargs, named",
        [
            ({"action": "count"}, "count"),
            ({"type": float}, "float"),
            # Its values could not all follow one '--novel=value' entry
            ({"nargs": "+"}, "nargs"),
            ({"nargs": "*"}, "nargs"),
        ],
    )
    def test_an_unknown_kind_is_refused(self, kwargs, named):
        from yellowdog_cli.utils.command_registry import Option

        option = Option(("--novel", "-N"), {"required": False, **kwargs})
        with pytest.raises(ValueError, match=f"--novel.*{named}"):
            tools_module._property_schema(option)


class TestPositionalSeparator:
    def test_a_dash_led_positional_follows_the_separator(self, tmp_path):
        argv, _ = to_argv(
            TOOLS["yd_download"], {"remote_paths": ["-weird"]}, str(tmp_path)
        )
        assert argv == ["--", "-weird"]

    def test_no_positionals_no_separator(self, tmp_path):
        argv, _ = to_argv(TOOLS["yd_cancel"], {"abort": True}, str(tmp_path))
        assert argv == ["-a"]


class TestEntityTypeDescription:
    def test_the_description_offers_only_the_full_names(self):
        description = TOOLS["yd_list"].input_schema["properties"]["entity_type"][
            "description"
        ]
        help_text = COMMANDS["yd-list"].option_named("entity_type").kwargs["help"]
        assert description != help_text
        assert "synonym" not in description.lower()
        assert "prefix" not in description.lower()


class TestInlineSpecificationFiles:
    def test_two_calls_write_distinct_files(self, tmp_path):
        _, first = to_argv(
            TOOLS["yd_submit"], {"specification": {"name": "a"}}, str(tmp_path)
        )
        _, second = to_argv(
            TOOLS["yd_submit"], {"specification": {"name": "b"}}, str(tmp_path)
        )
        assert first[0] != second[0]
        assert json.loads(first[0].read_text()) == {"name": "a"}
        assert json.loads(second[0].read_text()) == {"name": "b"}

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks and modes")
    def test_a_pre_placed_symlink_is_not_followed(self, tmp_path):
        # Symlinks at every name the old '<pid>-<n>' scheme could have chosen
        # in this run: an exclusive create at a random name follows none
        target = tmp_path / "target.txt"
        target.write_text("untouched")
        for index in range(1, 500):
            link = tmp_path / f".yd-mcp-{os.getpid()}-{index}.json"
            link.symlink_to(target)
        _, files = to_argv(
            TOOLS["yd_submit"], {"specification": {"name": "a"}}, str(tmp_path)
        )
        assert not files[0].is_symlink()
        assert json.loads(files[0].read_text()) == {"name": "a"}
        assert target.read_text() == "untouched"

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
    def test_the_file_is_readable_by_the_owner_only(self, tmp_path):
        _, files = to_argv(
            TOOLS["yd_submit"], {"specification": {"name": "a"}}, str(tmp_path)
        )
        assert stat.S_IMODE(files[0].stat().st_mode) & 0o077 == 0

    def test_a_failed_write_removes_the_files_already_written(
        self, tmp_path, monkeypatch
    ):
        real = tools_module._write_specification
        calls = []

        def failing(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise OSError("disk full")
            return real(*args, **kwargs)

        monkeypatch.setattr(tools_module, "_write_specification", failing)
        with pytest.raises(OSError, match="disk full"):
            to_argv(
                TOOLS["yd_create"],
                {"specifications": [{"resource": "Keyring"}, {"resource": "Keyring"}]},
                str(tmp_path),
            )
        assert len(calls) == 2
        assert list(tmp_path.iterdir()) == []


class TestSdkFreeImport:
    def test_importing_the_catalogue_pulls_in_neither_the_sdk_nor_fastjsonschema(self):
        # yellowdog_cli/mcp/tools.py's own docstring, and CLAUDE.md's MCP
        # section, both say this module (and command_registry.py beneath it)
        # is SDK-free; a subprocess is the only honest way to check what a
        # fresh interpreter loads, since this test file's own process has
        # almost certainly already imported both by the time it runs
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import yellowdog_cli.mcp.tools\n"
                "import sys\n"
                "assert 'yellowdog_client' not in sys.modules, 'yellowdog_client'\n"
                "assert 'fastjsonschema' not in sys.modules, 'fastjsonschema'\n",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_importing_the_command_registry_alone_is_also_sdk_free(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import yellowdog_cli.utils.command_registry\n"
                "import sys\n"
                "assert 'yellowdog_client' not in sys.modules, 'yellowdog_client'\n"
                "assert 'fastjsonschema' not in sys.modules, 'fastjsonschema'\n",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
