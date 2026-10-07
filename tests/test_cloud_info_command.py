"""
Unit tests for cloud_info.py (yd-cloud-info) and its tables, against the
fake Cloud Info service in cloud_info_fixtures.py.

Covers:
  - the command line parsed: parse_range(), the type's prefixes, every
    refusal of check_cloud_info_options, and the sort keys held to the
    library's; the read-only MCP tool with the types as an enum
  - the command line turned into a CloudInfoQuery
  - the output modes: a table, '--json' records (an SDK object, or a dict
    for an instance type with prices), '--count' (which overrides '--json'),
    and the message for no matches
  - each table's columns: providers' display names, RAM in GiB, GPUs,
    sub-regions in the region, '-' for what the service does not give
"""

from argparse import ArgumentTypeError
from types import SimpleNamespace
from typing import Any

import pytest
from yellowdog_client.model import Price

import yellowdog_cli.cloud_info as yd_cloud_info
from tests.cloud_info_fixtures import FakeCloudInfo
from yellowdog_cli.utils import tables
from yellowdog_cli.utils.args import CLIParser
from yellowdog_cli.utils.cloud_info import (
    PRICED_SORT_KEYS,
    SORT_KEYS,
    CloudInfoQuery,
    PricedInstanceType,
    instance_types,
    prices,
)
from yellowdog_cli.utils.command_registry import (
    CLOUD_INFO_PRICED_SORT_KEYS,
    CLOUD_INFO_SORT_KEYS,
    parse_range,
    resolve_cloud_info_type,
)
from yellowdog_cli.utils.context import RunContext


def _args(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "cloud_info_type": "regions",
        "providers": None,
        "region": None,
        "sub_region": None,
        "name_glob": None,
        "vcpus_range": None,
        "ram_range": None,
        "arch": None,
        "usage": None,
        "os_licence": None,
        "prices": False,
        "sort": "name",
        "reverse": False,
        "count_only": False,
        "json_output": False,
        "quiet": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class Output:
    def __init__(self) -> None:
        self.tables: list[tuple[list[str], list[list]]] = []
        self.records: list[Any] = []
        self.simple: list[str] = []
        self.info: list[str] = []


@pytest.fixture
def output(monkeypatch) -> Output:
    captured = Output()
    monkeypatch.setattr(
        yd_cloud_info,
        "print_table",
        lambda headers, rows: captured.tables.append((headers, rows)),
    )
    monkeypatch.setattr(yd_cloud_info, "record", captured.records.append)
    monkeypatch.setattr(
        yd_cloud_info,
        "print_simple",
        lambda message, override_quiet=False: captured.simple.append(message),
    )
    monkeypatch.setattr(
        yd_cloud_info,
        "print_info",
        lambda message, override_quiet=False: captured.info.append(message),
    )
    return captured


def _run(**overrides: Any) -> SimpleNamespace:
    args = _args(**overrides)
    fake = FakeCloudInfo()
    yd_cloud_info.list_cloud_info(
        RunContext(args=args, config=fake.ctx.config, client=fake.ctx.client)  # type: ignore[arg-type]
    )
    return args


class TestQueryFromArgs:
    def test_the_command_line_becomes_a_query(self):
        query = yd_cloud_info.query_from_args(
            _args(
                providers=["aws"],
                region="eu-west-2",
                name_glob="t3*",
                vcpus_range=(4.0, None),
                arch="arm64",
                sort="vcpus",
                reverse=True,
            )
        )
        assert query == CloudInfoQuery(
            providers=("aws",),
            region="eu-west-2",
            name_glob="t3*",
            vcpus=(4.0, None),
            arch="arm64",
            os_licence="none",
            sort="vcpus",
            reverse=True,
        )

    def test_the_os_licence_given_is_kept(self):
        query = yd_cloud_info.query_from_args(_args(os_licence="windows"))
        assert query.os_licence == "windows"


class TestOutput:
    def test_a_table_is_printed(self, output):
        _run(cloud_info_type="regions", providers=["azure"])
        assert output.tables == [(["Provider", "Region"], [["Azure", "uksouth"]])]

    def test_json_records_the_sdk_objects(self, output):
        _run(cloud_info_type="sub-regions", region="eu-west-2", json_output=True)
        assert [s.name for s in output.records] == ["eu-west-2a", "eu-west-2b"]
        assert output.tables == []

    def test_json_records_a_priced_type_as_a_dict(self, output):
        _run(
            cloud_info_type="instance-types",
            region="eu-west-2",
            name_glob="t3.xlarge",
            prices=True,
            json_output=True,
        )
        assert len(output.records) == 1
        assert output.records[0]["spotPrice"] == {"currency": "USD", "value": 0.05}

    def test_count_prints_the_number_alone(self, output):
        _run(cloud_info_type="instance-types", region="eu-west-2", count_only=True)
        assert output.simple == ["5"]
        assert output.tables == [] and output.records == []

    def test_count_overrides_json(self, output):
        args = _run(cloud_info_type="regions", count_only=True, json_output=True)
        assert output.simple == ["4"]
        assert output.records == []
        # So that the results flush prints no '[]' after the count
        assert args.json_output is False

    def test_no_matches_says_so(self, output):
        _run(cloud_info_type="regions", name_glob="nowhere")
        assert output.info == ["No matching Regions found"]
        assert output.tables == []

    def test_a_priced_table_is_printed(self, output):
        _run(
            cloud_info_type="instance-types",
            region="eu-west-2",
            name_glob="t3.xlarge",
            prices=True,
        )
        [(headers, rows)] = output.tables
        assert headers[-5:] == [
            "Sub-regions",
            "On-demand",
            "Spot (lowest)",
            "Spot Zone",
            "Currency",
        ]
        assert rows == [
            [
                "AWS",
                "t3.xlarge",
                "X86_64",
                "4",
                "16",
                "-",
                "eu-west-2a, eu-west-2b, eu-west-2c",
                "0.1880",
                "0.0500",
                "eu-west-2b",
                "USD",
            ]
        ]


class TestTables:
    def test_an_instance_type_without_a_region_shows_its_region_count(self):
        fake = FakeCloudInfo()
        found = instance_types(fake.ctx, CloudInfoQuery(name_glob="g4dn.xlarge"))
        headers, rows = tables.instance_types_table(found, None)
        assert headers[-1] == "Regions"
        assert rows == [["AWS", "g4dn.xlarge", "X86_64", "4", "16", "1 (T4)", "1"]]

    def test_a_type_the_service_says_little_about_shows_dashes(self):
        fake = FakeCloudInfo()
        found = instance_types(fake.ctx, CloudInfoQuery(name_glob="u-unknown"))
        _, rows = tables.instance_types_table(found, None)
        assert rows == [["AWS", "u-unknown", "-", "-", "-", "-", "0"]]

    def test_a_region_wide_price_has_no_sub_region_and_a_missing_value_a_dash(self):
        fake = FakeCloudInfo()
        found = prices(
            fake.ctx, CloudInfoQuery(region="eu-west-2", name_glob="t3*.micro")
        )
        headers, rows = tables.instance_type_prices_table(found)
        assert headers == [
            "Provider",
            "Region",
            "Sub-region",
            "Instance Type",
            "Usage",
            "OS Licence",
            "Price",
            "Currency",
        ]
        assert rows == [
            [
                "AWS",
                "eu-west-2",
                "eu-west-2a",
                "t3.micro",
                "Spot",
                "No licence",
                "-",
                "USD",
            ],
            [
                "AWS",
                "eu-west-2",
                "-",
                "t3a.micro",
                "On Demand",
                "No licence",
                "0.0118",
                "USD",
            ],
        ]

    def test_a_priced_type_without_prices_shows_dashes(self):
        fake = FakeCloudInfo()
        [g4dn] = instance_types(fake.ctx, CloudInfoQuery(name_glob="g4dn.xlarge"))
        _, rows = tables.priced_instance_types_table(
            [PricedInstanceType(g4dn, None, None, None)], "eu-west-2"
        )
        assert rows[0][-5:] == ["eu-west-2a, eu-west-2b", "-", "-", "-", "-"]


def _parse(*argv: str) -> CLIParser:
    return CLIParser("yd-cloud-info", argv=list(argv))


def _refused(capsys, *argv: str) -> str:
    with pytest.raises(SystemExit) as stopped:
        _parse(*argv)
    assert stopped.value.code == 2
    return capsys.readouterr().err


class TestParseRange:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("4", (4.0, 4.0)),
            ("48", (48.0, 48.0)),
            ("4-8", (4.0, 8.0)),
            ("4-", (4.0, None)),
            ("-8", (None, 8.0)),
            ("0.5-2", (0.5, 2.0)),
            (" 4-8 ", (4.0, 8.0)),
        ],
    )
    def test_the_forms(self, text, expected):
        assert parse_range(text) == expected

    @pytest.mark.parametrize("text", ["", "-", "x", "4 8", "8-4", "4--8", "4-8-"])
    def test_refusals(self, text):
        with pytest.raises(ValueError):
            parse_range(text)


class TestResolveType:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("regions", "regions"),
            ("r", "regions"),
            ("sub", "sub-regions"),
            ("inst", "instance-types"),
            ("p", "prices"),
        ],
    )
    def test_a_name_or_a_prefix(self, value, expected):
        assert resolve_cloud_info_type(value) == expected

    @pytest.mark.parametrize("value", ["", "x", "regionsx"])
    def test_anything_else_is_refused(self, value):
        with pytest.raises(ArgumentTypeError):
            resolve_cloud_info_type(value)


class TestParsing:
    def test_the_full_priced_query_parses(self):
        parsed = _parse(
            "inst",
            "--region",
            "eu-west-2",
            "--prices",
            "--sort",
            "spot",
            "--vcpus",
            "4-8",
            "--ram",
            "16-",
            "-p",
            "aws",
            "--provider",
            "google",
        )
        assert parsed.cloud_info_type == "instance-types"
        assert parsed.vcpus_range == (4.0, 8.0)
        assert parsed.ram_range == (16.0, None)
        assert parsed.providers == ["aws", "google"]
        assert parsed.prices is True

    def test_an_open_lower_bound_is_accepted(self):
        assert _parse("instance-types", "--vcpus", "-8").vcpus_range == (None, 8.0)

    @pytest.mark.parametrize(
        "argv", [["prices", "--region", "r"], ["prices", "--name", "t3.micro"]]
    )
    def test_prices_are_bounded_by_a_region_or_a_name(self, argv):
        assert _parse(*argv).cloud_info_type == "prices"

    def test_no_range_is_none(self):
        parsed = _parse("instance-types")
        assert (parsed.vcpus_range, parsed.ram_range) == (None, None)

    @pytest.mark.parametrize(
        "argv, message",
        [
            (["regions", "--vcpus", "4"], "--vcpus does not apply to regions"),
            (["regions", "--region", "r"], "--region does not apply to regions"),
            (["prices", "--arch", "arm64"], "--arch does not apply to prices"),
            (["instance-types", "--usage", "spot"], "--usage does not apply"),
            (["prices", "--prices", "--region", "r"], "--prices does not apply"),
            (["instance-types", "--prices"], "--prices needs --region"),
            (["prices", "--sub-region", "z"], "--sub-region needs --region"),
            (
                ["instance-types", "--region", "r", "--os", "windows"],
                "--os applies to instance-types only with --prices",
            ),
            (["instance-types", "--sort", "price"], "--sort price does not apply"),
            (
                ["instance-types", "--region", "r", "--sort", "spot"],
                "--sort spot does not apply",
            ),
            (
                ["prices", "--region", "r", "--sort", "vcpus"],
                "--sort vcpus does not apply",
            ),
            (["prices"], "prices needs --region or --name"),
            (["prices", "--provider", "aws"], "prices needs --region or --name"),
            (["instance-types", "--vcpus", "8-4"], "--vcpus:"),
            (["instance-types", "--ram", "lots"], "--ram:"),
            (["regions", "--provider", "AWS"], "invalid choice"),
            (["everything"], "unknown type"),
        ],
    )
    def test_refusals(self, capsys, argv, message):
        assert message in _refused(capsys, *argv)


class TestRegistry:
    def test_the_sort_keys_match_the_librarys(self):
        assert {k: set(v) for k, v in CLOUD_INFO_SORT_KEYS.items()} == {
            k: set(v) for k, v in SORT_KEYS.items()
        }
        assert set(CLOUD_INFO_PRICED_SORT_KEYS) == set(PRICED_SORT_KEYS)

    def test_it_is_a_read_only_mcp_tool_with_the_types_as_an_enum(self):
        from yellowdog_cli.mcp.tools import build_tools

        tool = {t.name: t for t in build_tools()}["yd_cloud_info"]
        assert tool.annotations.get("readOnlyHint") is True
        schema = tool.input_schema
        assert schema["properties"]["cloud_info_type"]["enum"] == [
            "regions",
            "sub-regions",
            "instance-types",
            "prices",
        ]
        assert "cloud_info_type" in schema["required"]

    def test_the_tool_description_names_only_the_tools_arguments(self):
        from yellowdog_cli.mcp.tools import build_tools

        tool = {t.name: t for t in build_tools()}["yd_cloud_info"]
        properties = set(tool.input_schema["properties"])
        # Each argument the description tells a client to pass
        for argument in ("name_glob", "os_licence", "providers", "sub_region"):
            assert argument in tool.description
            assert argument in properties
        for wrong in (" name (", " os ("):
            assert wrong not in tool.description


class TestPrintTable:
    def test_formatted_numbers_are_printed_as_given(self, monkeypatch):
        # tabulate reformats a column it can read as numbers, dropping the
        # trailing zeros the builders wrote ('0.3450' printed as '0.345')
        printed: list[str] = []
        monkeypatch.setattr(tables, "print_table_core", printed.append)
        tables.print_table(
            ["On-demand", "RAM (GiB)"], [["0.3450", "16"], ["0.1504", "0.5"]]
        )
        assert "0.3450" in printed[0]
        assert "0.1504" in printed[0]


class TestMinors:
    def test_a_region_wide_spot_price_shows_no_spot_zone(self):
        fake = FakeCloudInfo()
        [t3] = instance_types(fake.ctx, CloudInfoQuery(name_glob="t3.xlarge"))
        _, rows = tables.priced_instance_types_table(
            [PricedInstanceType(t3, None, Price(value=0.05), "N/A")], "eu-west-2"
        )
        assert rows[0][-2] == "-"

    def test_no_os_licence_does_not_read_as_a_missing_value(self):
        fake = FakeCloudInfo()
        found = prices(
            fake.ctx, CloudInfoQuery(region="eu-west-2", name_glob="t3a.micro")
        )
        headers, rows = tables.instance_type_prices_table(found)
        assert headers[5] == "OS Licence"
        assert rows[0][5] == "No licence"

    def test_the_count_help_names_only_this_commands_options(self):
        from yellowdog_cli.utils.command_registry import COMMANDS

        count = COMMANDS["yd-cloud-info"].option_named("--count")
        assert count is not None
        assert "--details" not in count.kwargs["help"]
        assert "--ids-only" not in count.kwargs["help"]


class TestMain:
    def test_count_with_json_prints_the_count_alone(self, monkeypatch, capsys):
        # Through main() and the real wrapper, whose results flush would print
        # '[]' after the count if '--json' were still set
        from yellowdog_cli.utils import wrapper
        from yellowdog_cli.utils.results import reset_results

        reset_results()
        monkeypatch.setattr(
            wrapper,
            "ARGS_PARSER",
            CLIParser("yd-cloud-info", argv=["regions", "--count", "--json"]),
        )
        monkeypatch.setattr(wrapper, "CLIENT", FakeCloudInfo().ctx.client)
        try:
            with pytest.raises(SystemExit) as stopped:
                yd_cloud_info.main()
        finally:
            reset_results()
        assert stopped.value.code == 0
        assert capsys.readouterr().out == "4\n"
