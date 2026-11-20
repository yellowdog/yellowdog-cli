"""
yd usage (usage.py, utils/usage_report.py): the Platform's compute usage
report for a window, fetched once and kept as CSV files in a private
temporary directory until '--refresh', its Instances totalled by the keys
'--by' names; the '--by' parsing (command_registry.usage_group_keys());
a report that cannot be read leaving nothing kept; the table, its total
and the JSON document.
"""

import io
import os
import time
import zipfile
from argparse import ArgumentTypeError
from datetime import datetime, timedelta, timezone
from json import loads
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from requests import ConnectionError, ConnectTimeout, HTTPError, ReadTimeout

import yellowdog_cli.usage as usage
from yellowdog_cli.utils import (
    completion_cache,
    entity_utils,
    output_settings,
    usage_report,
)
from yellowdog_cli.utils.command_registry import (
    USAGE_GROUP_KEYS,
    usage_filter,
    usage_group_keys,
)
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.exit_codes import ExitCode, NotFoundError, classify
from yellowdog_cli.utils.limits import RAW_CONNECT_TIMEOUT

URL = "https://api.example.com"
KEY = "key-id"
SECRET = "key-secret"
CR_RENDER = "ydid:compreq:000000:AAAAAA:00000000-0000-0000-0000-000000000001"
CR_TRAIN = "ydid:compreq:000000:BBBBBB:00000000-0000-0000-0000-000000000002"
CR_GONE = "ydid:compreq:000000:CCCCCC:00000000-0000-0000-0000-000000000003"
APP_RENDER = "ydid:app:000000:aaaaaaaa-0000-0000-0000-000000000001"
USER_ALICE = "ydid:user:000000:bbbbbbbb-0000-0000-0000-000000000002"

REQUIREMENTS = [
    "Namespace,Name,Tag,Created Time,Terminated Time,Created by ID,Compute Requirement ID",
    f"team-render,render-1,nightly,2026-11-01T00:00:00Z,,{APP_RENDER},{CR_RENDER}",
    f"team-train,train-1,,2026-11-02T00:00:00Z,2026-11-03T00:00:00Z,{USER_ALICE},{CR_TRAIN}",
]
INSTANCES_HEADER = (
    "Host Name,Provider,Region,Instance Type,Source Name,From Time,Until Time,"
    "Pending (s),Running (s),Stopping (s),Stopped (s),Terminating (s),Unknown (s),"
    "Total (s),Compute Requirement ID,Instance ID,Spot"
)


def _instance(
    requirement: str,
    instance_type: str,
    running: int,
    stopped: int = 0,
    pending: int = 0,
    spot: bool = False,
    instance_id: str = "i-1",
) -> str:
    total = running + stopped + pending
    return (
        f"host,AWS,eu-west-2,{instance_type},source-a,2026-11-01T00:00:00Z,"
        f"2026-11-08T00:00:00Z,{pending},{running},0,{stopped},0,0,{total}.0,"
        f"{requirement},{instance_id},{'true' if spot else 'false'}"
    )


INSTANCES = [
    INSTANCES_HEADER,
    _instance(CR_RENDER, "g4dn.xlarge", running=0, stopped=7200, instance_id="i-1"),
    _instance(CR_TRAIN, "t3a.small", running=3600, pending=360, instance_id="i-2"),
    _instance(CR_TRAIN, "t3a.small", running=1800, spot=True, instance_id="i-3"),
    _instance(CR_TRAIN, "t2.small", running=900, instance_id="i-4"),
]


_ZIP_TIME = (2026, 11, 8, 0, 0, 0)


def _zip(
    instances: list[str] = INSTANCES,
    leave_out: str | None = None,
    requirements: list[str] = REQUIREMENTS,
) -> bytes:
    """
    A report zip as the Platform names its files.
    """
    files = {
        "summary_000000_20261108_0000.csv": (
            "Account ID,000000\n"
            "From Time,2026-11-01T00:00:00Z\n"
            "Until Time,2026-11-08T00:00:00Z\n"
        ),
        "compute-requirements_000000_20261108_0000.csv": "\n".join(requirements) + "\n",
        "instances_000000_20261108_0000.csv": "\n".join(instances) + "\n",
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            if leave_out is None or not name.startswith(leave_out):
                # A fixed time, so the same report is the same bytes: one
                # stamped now would differ between xdist workers' collections
                archive.writestr(zipfile.ZipInfo(name, _ZIP_TIME), text)
    return buffer.getvalue()


def _answer(status_code: int, content: bytes = b"", text: str = "") -> SimpleNamespace:
    """
    A response as requests gives a streamed one: its body also readable in
    chunks (iter_content), three of them for anything longer than a few bytes.
    """
    size = max(1, len(content) // 3)

    def iter_content(chunk_size=1):
        for start in range(0, len(content), size):
            yield content[start : start + size]

    return SimpleNamespace(
        status_code=status_code, content=content, text=text, iter_content=iter_content
    )


class _Platform:
    """
    requests.put as the report endpoint answers it, recording each call.
    """

    def __init__(self, content: bytes = b"", status_code: int = 200):
        self.content = content or _zip()
        self.status_code = status_code
        self.calls: list[dict] = []

    def __call__(self, url, headers, json, timeout, stream=False):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
                "stream": stream,
            }
        )
        return _answer(
            self.status_code,
            self.content,
            '{"errorType": "MissingPermissionException"}',
        )


@pytest.fixture
def platform(monkeypatch, tmp_path) -> _Platform:
    """
    The report endpoint, and the cache under the test's own directory.
    """
    monkeypatch.setattr(completion_cache, "_temp_root", lambda: tmp_path)
    fake = _Platform()
    monkeypatch.setattr(usage_report.requests, "put", fake)
    return fake


def _ctx(**args) -> RunContext:
    values = {
        "json_output": False,
        "json": False,
        "quiet": False,
        "no_format": True,
        "usage_from": "2026-11-01",
        "usage_until": "2026-11-08",
        "usage_by": ("namespace",),
        "usage_refresh": False,
        "usage_where": None,
        "namespace": None,
        **args,
    }
    return RunContext(
        args=SimpleNamespace(**values),
        config=SimpleNamespace(
            url=URL, key=KEY, secret=SECRET, request_timeout=(10, 90), read_timeout=90.0
        ),
        client=MagicMock(),
    )


def _show(capsys, **args) -> tuple[str, str]:
    ctx = _ctx(**args)
    with output_settings.configured(ctx.args):
        usage.show_usage(ctx)
    captured = capsys.readouterr()
    return captured.out, captured.err


def _report(ctx: RunContext, refresh: bool = False) -> usage_report.Report:
    from_time = usage._parsed("--from", ctx.args.usage_from)
    until_time = usage._parsed("--until", ctx.args.usage_until)
    return usage_report.usage_report(
        ctx,
        from_time,
        until_time,
        ctx.args.usage_from,
        ctx.args.usage_until,
        ctx.args.namespace,
        refresh=refresh,
    )


class TestGroupKeys:
    def test_one_key_or_several(self):
        assert usage_group_keys("namespace") == ("namespace",)
        assert usage_group_keys("namespace, instance-type") == (
            "namespace",
            "instance-type",
        )

    def test_an_unknown_key_is_refused_with_a_suggestion(self):
        with pytest.raises(ArgumentTypeError, match="did you mean 'namespace'"):
            usage_group_keys("namespcae")

    def test_a_key_given_twice_is_refused(self):
        with pytest.raises(ArgumentTypeError, match="more than once: pricing"):
            usage_group_keys("pricing,namespace,pricing")

    def test_the_registry_offers_the_keys_the_report_reads(self):
        assert usage_report.GROUP_KEYS == USAGE_GROUP_KEYS
        assert "creator" in USAGE_GROUP_KEYS

    def test_spot_is_no_key(self):
        # Spot or on-demand is the pricing key's value, not a key of its own
        with pytest.raises(ArgumentTypeError, match="invalid grouping 'spot'"):
            usage_group_keys("spot")


class TestTheReportsWait:
    @pytest.mark.parametrize(
        "read_timeout, expected", [(90.0, 300.0), (600.0, 600.0), (None, None)]
    )
    def test_the_report_waits_at_least_five_minutes(self, read_timeout, expected):
        assert usage_report._report_timeout(read_timeout) == (
            RAW_CONNECT_TIMEOUT,
            expected,
        )

    def test_the_request_is_streamed_with_the_reports_timeout(self, platform):
        _report(_ctx())
        assert platform.calls[0]["timeout"] == (RAW_CONNECT_TIMEOUT, 300.0)
        assert platform.calls[0]["stream"] is True

    def test_a_timed_out_report_says_how_to_wait_longer(self, platform, monkeypatch):
        def timed_out(**kwargs):
            raise ReadTimeout("read timed out")

        monkeypatch.setattr(usage_report.requests, "put", timed_out)
        with pytest.raises(ReadTimeout, match=r"5 minutes.*readTimeout") as raised:
            _report(_ctx())
        assert classify(raised.value) == ExitCode.CONNECTION

    def test_a_connect_timeout_is_not_called_a_wait_for_the_report(
        self, platform, monkeypatch
    ):
        def unreachable(**kwargs):
            raise ConnectTimeout("connect timed out")

        monkeypatch.setattr(usage_report.requests, "put", unreachable)
        with pytest.raises(ConnectTimeout, match=r"^connect timed out$") as raised:
            _report(_ctx())
        assert classify(raised.value) == ExitCode.CONNECTION

    def test_a_download_that_stalls_says_how_to_wait_longer(
        self, platform, monkeypatch
    ):
        from urllib3.exceptions import ReadTimeoutError

        def stalls(**kwargs):
            def iter_content(chunk_size=1):
                yield b"PK"
                raise ConnectionError(ReadTimeoutError(None, None, "Read timed out."))

            return SimpleNamespace(status_code=200, text="", iter_content=iter_content)

        monkeypatch.setattr(usage_report.requests, "put", stalls)
        with pytest.raises(ConnectionError, match=r"5 minutes.*readTimeout") as raised:
            _report(_ctx())
        assert classify(raised.value) == ExitCode.CONNECTION

    def test_a_lost_connection_while_downloading_keeps_its_message(
        self, platform, monkeypatch
    ):
        def lost(**kwargs):
            def iter_content(chunk_size=1):
                yield b"PK"
                raise ConnectionError("connection reset")

            return SimpleNamespace(status_code=200, text="", iter_content=iter_content)

        monkeypatch.setattr(usage_report.requests, "put", lost)
        with pytest.raises(ConnectionError, match=r"^connection reset$"):
            _report(_ctx())


@pytest.fixture
def terminal(monkeypatch) -> io.StringIO:
    """
    Standard error as a terminal, its output kept to be read.
    """
    from rich.console import Console

    from yellowdog_cli.utils import printing

    written = io.StringIO()
    console = Console(file=written, force_terminal=True, width=100)
    monkeypatch.setattr(printing, "CONSOLE_ERR", console)
    return written


def _fetch_shown(**args) -> usage_report.Report:
    ctx = _ctx(no_format=False, **args)
    with output_settings.configured(ctx.args):
        return _report(ctx, refresh=True)


class TestFetchProgress:
    def test_the_report_arrives_whole_from_its_chunks(self, platform, terminal):
        report = _fetch_shown()
        assert report.path.read_bytes() == _zip()
        assert report.fetched_bytes == len(_zip())

    def test_progress_shows_the_wait_then_the_download(self, platform, terminal):
        _fetch_shown()
        shown = terminal.getvalue()
        assert "Waiting for the Platform to build the report" in shown
        assert "Downloading the report" in shown

    @pytest.mark.parametrize("setting", ["json_output", "quiet", "no_format"])
    def test_no_progress_under(self, setting, platform, terminal):
        args = {setting: True}
        if setting == "json_output":
            args["json"] = True
        ctx = _ctx(**{"no_format": False, **args})
        with output_settings.configured(ctx.args):
            _report(ctx, refresh=True)
        assert "Waiting for the Platform" not in terminal.getvalue()

    def test_no_progress_off_a_terminal(self, platform, monkeypatch):
        from rich.console import Console

        from yellowdog_cli.utils import printing

        written = io.StringIO()
        monkeypatch.setattr(printing, "CONSOLE_ERR", Console(file=written))
        _fetch_shown()
        assert written.getvalue() == ""

    def test_a_failed_download_removes_the_display(
        self, platform, terminal, monkeypatch
    ):
        def broken(**kwargs):
            def iter_content(chunk_size=1):
                yield b"PK"
                raise ConnectionError("connection lost")

            return SimpleNamespace(status_code=200, text="", iter_content=iter_content)

        monkeypatch.setattr(usage_report.requests, "put", broken)
        with pytest.raises(ConnectionError, match="connection lost"):
            _fetch_shown()
        assert not list(
            Path(
                completion_cache.cache_directory(
                    usage_report.USAGE_CACHE_DIRECTORY_NAME
                )
            ).glob("*/report.zip")
        )

    def test_an_empty_report_breaks_no_rate(self, platform, terminal):
        platform.content = b""
        with pytest.raises(usage_report.UsageReportError):
            _fetch_shown()


class TestTheReportIsFetchedAndKept:
    def test_the_request(self, platform):
        _report(_ctx(namespace="team-render"))
        (call,) = platform.calls
        assert call["url"] == f"{URL}/usage/compute/report"
        assert call["headers"] == {"Authorization": f"yd-key {KEY}:{SECRET}"}
        assert call["json"]["fromTime"].endswith("Z")
        assert call["json"]["untilTime"].endswith("Z")
        assert call["json"]["namespaces"] == ["team-render"]

    def test_every_namespace_without_one(self, platform):
        _report(_ctx())
        assert "namespaces" not in platform.calls[0]["json"]

    def test_the_zip_is_kept_as_it_arrived(self, platform, tmp_path):
        report = _report(_ctx())
        assert not report.from_cache
        assert report.directory.parent.parent == tmp_path
        assert {path.name for path in report.directory.iterdir()} == {
            "report.zip",
            "fetched.json",
        }
        assert report.path.read_bytes() == platform.content
        assert report.from_time == "2026-11-01T00:00:00Z"
        assert report.until_time == "2026-11-08T00:00:00Z"

    def test_a_second_run_uses_the_kept_report(self, platform):
        first = _report(_ctx())
        second = _report(_ctx())
        assert len(platform.calls) == 1
        assert second.from_cache and second.directory == first.directory

    def test_refresh_fetches_it_again(self, platform):
        _report(_ctx())
        report = _report(_ctx(), refresh=True)
        assert len(platform.calls) == 2
        assert not report.from_cache

    def test_another_window_or_namespace_is_another_report(self, platform):
        _report(_ctx())
        _report(_ctx(usage_from="2026-10-01"))
        _report(_ctx(namespace="team-render"))
        assert len(platform.calls) == 3

    def test_the_directory_name_holds_no_credential(self, platform):
        report = _report(_ctx())
        assert KEY not in str(report.directory)
        assert SECRET not in str(report.directory)

    def test_a_refused_request_keeps_its_exit_code(self, platform):
        platform.status_code = 403
        with pytest.raises(HTTPError) as raised:
            _report(_ctx())
        assert classify(raised.value) == ExitCode.PERMISSION

    @pytest.mark.parametrize(
        "content, message",
        [
            (b"not a zip", "not a zip file"),
            (_zip(leave_out="instances"), "has no instances file"),
        ],
        ids=["not a zip", "no instances file"],
    )
    def test_a_report_that_cannot_be_read_leaves_nothing_kept(
        self, platform, tmp_path, content, message
    ):
        platform.content = content
        with pytest.raises(usage_report.UsageReportError, match=message):
            _report(_ctx())
        (cache,) = tmp_path.iterdir()
        assert list(cache.iterdir()) == []


class TestGrouping:
    def test_by_namespace_most_time_first(self, platform):
        groups = usage_report.grouped_usage(_report(_ctx()), ["namespace"])
        assert [group.keys for group in groups] == [
            {"namespace": "team-render"},  # 2.0 hours, all stopped
            {"namespace": "team-train"},  # 1.85 hours
        ]
        render, train = groups
        assert train.instances == 3
        assert train.seconds["running"] == 3600 + 1800 + 900
        assert train.seconds["pending"] == 360
        assert train.total_seconds == 3600 + 1800 + 900 + 360
        assert render.seconds["stopped"] == 7200

    def test_by_several_keys(self, platform):
        groups = usage_report.grouped_usage(
            _report(_ctx()), ["namespace", "instance-type", "pricing"]
        )
        assert {tuple(group.keys.values()): group.instances for group in groups} == {
            ("team-render", "g4dn.xlarge", "on-demand"): 1,
            ("team-train", "t3a.small", "on-demand"): 1,
            ("team-train", "t3a.small", "spot"): 1,
            ("team-train", "t2.small", "on-demand"): 1,
        }

    def test_the_requirement_and_tag_come_from_its_row(self, platform):
        groups = usage_report.grouped_usage(_report(_ctx()), ["requirement", "tag"])
        assert {tuple(group.keys.values()) for group in groups} == {
            ("render-1", "nightly"),
            ("train-1", "-"),
        }

    def test_an_instance_whose_requirement_is_not_listed(self, platform):
        platform.content = _zip(
            instances=[INSTANCES_HEADER, _instance(CR_GONE, "t3a.small", 60)]
        )
        report = _report(_ctx())
        (group,) = usage_report.grouped_usage(report, ["namespace", "requirement"])
        assert group.keys == {"namespace": "-", "requirement": CR_GONE}


NAMES = usage_report.CreatorNames(
    names={APP_RENDER: "render-farm", USER_ALICE: "alice"}
)


class TestCreator:
    def _groups(self, platform, by, where=None, creators=NAMES):
        return usage_report.grouped_usage(
            _report(_ctx()),
            by,
            usage_report.filter_of(where),
            creators=creators,
        )

    def test_grouped_by_creator_shows_name_and_kind(self, platform):
        groups = self._groups(platform, ["creator"])
        assert {g.keys["creator"]: g.creator_id for g in groups} == {
            "render-farm (Application)": APP_RENDER,
            "alice (User)": USER_ALICE,
        }

    def test_an_unresolved_creator_is_its_id(self, platform):
        groups = self._groups(
            platform, ["creator"], creators=usage_report.CreatorNames()
        )
        assert {g.keys["creator"] for g in groups} == {
            f"{APP_RENDER} (?)",
            f"{USER_ALICE} (?)",
        }

    def test_no_creators_given_is_every_creator_unresolved(self, platform):
        groups = self._groups(platform, ["creator"], creators=None)
        assert {g.keys["creator"] for g in groups} == {
            f"{APP_RENDER} (?)",
            f"{USER_ALICE} (?)",
        }

    def test_no_creator_is_a_dash(self, platform):
        # One Instance whose requirement is not in the report, and one whose
        # requirement's row names no creator
        platform.content = _zip(
            instances=[
                INSTANCES_HEADER,
                _instance(CR_GONE, "t3a.small", 60, instance_id="i-1"),
                _instance(CR_TRAIN, "t3a.small", 60, instance_id="i-2"),
            ],
            requirements=[
                REQUIREMENTS[0],
                f"team-train,train-1,,2026-11-02T00:00:00Z,,,{CR_TRAIN}",
            ],
        )
        (group,) = self._groups(platform, ["creator"])
        assert group.keys == {"creator": "-"}
        assert group.creator_id is None
        assert group.instances == 2

    def test_creators_sharing_a_name_stay_apart(self, platform):
        other = "ydid:app:000000:cccccccc-0000-0000-0000-000000000003"
        platform.content = _zip(
            requirements=[
                REQUIREMENTS[0],
                f"team-render,render-1,,2026-11-01T00:00:00Z,,{APP_RENDER},{CR_RENDER}",
                f"team-train,train-1,,2026-11-02T00:00:00Z,,{other},{CR_TRAIN}",
            ]
        )
        names = usage_report.CreatorNames(names={APP_RENDER: "same", other: "same"})
        groups = self._groups(platform, ["creator"], creators=names)
        assert [g.keys["creator"] for g in groups] == ["same (Application)"] * 2
        assert {g.creator_id: g.instances for g in groups} == {
            APP_RENDER: 1,
            other: 3,
        }

    @pytest.mark.parametrize(
        "pattern, expected",
        [
            ("render-*", {"render-farm (Application)"}),
            ("ALICE", {"alice (User)"}),
            (f"{USER_ALICE[:24]}*", {"alice (User)"}),
            ("render-farm (Application)", {"render-farm (Application)"}),
            ("*(User)", {"alice (User)"}),
            ("*(Group)", set()),
        ],
    )
    def test_where_creator_matches_name_id_or_shown(self, platform, pattern, expected):
        groups = self._groups(platform, ["creator"], [("creator", pattern)])
        assert {g.keys["creator"] for g in groups} == expected

    def test_where_creator_matches_an_unresolved_creator_as_shown(self, platform):
        groups = self._groups(
            platform,
            ["namespace"],
            [("creator", f"{APP_RENDER} (?)")],
            creators=usage_report.CreatorNames(),
        )
        assert [g.keys for g in groups] == [{"namespace": "team-render"}]

    def test_where_creator_matches_an_unresolved_creators_id(self, platform):
        groups = self._groups(
            platform,
            ["namespace"],
            [("creator", f"{APP_RENDER[:24]}*")],
            creators=usage_report.CreatorNames(),
        )
        assert [g.keys for g in groups] == [{"namespace": "team-render"}]


def _listings(monkeypatch, applications=None, users=None) -> list[str]:
    """
    The account's Applications and Users as entity_utils lists them, each a
    list of objects or an exception the listing raises; the listings made
    are noted in the list returned.
    """
    if applications is None:
        applications = [SimpleNamespace(id=APP_RENDER, name="render-farm")]
    if users is None:
        users = [SimpleNamespace(id=USER_ALICE, name="alice", username="alice.s")]
    calls: list[str] = []

    def listing(kind, result):
        def lister(client):
            calls.append(kind)
            if isinstance(result, BaseException):
                raise result
            return result

        return lister

    monkeypatch.setattr(
        entity_utils, "get_all_applications", listing("applications", applications)
    )
    monkeypatch.setattr(entity_utils, "get_all_users", listing("users", users))
    return calls


def _refused() -> HTTPError:
    return HTTPError(response=SimpleNamespace(status_code=403))


class TestCreatorNames:
    def test_creator_names_come_from_both_listings(self, monkeypatch):
        _listings(monkeypatch)
        creators = usage_report.creator_names(_ctx())
        assert creators.names == {APP_RENDER: "render-farm", USER_ALICE: "alice"}
        assert creators.unreadable == []

    def test_creator_names_a_user_without_a_name_by_username(self, monkeypatch):
        _listings(
            monkeypatch,
            users=[SimpleNamespace(id=USER_ALICE, name=None, username="alice.s")],
        )
        assert usage_report.creator_names(_ctx()).names[USER_ALICE] == "alice.s"

    def test_creator_names_leaves_a_refused_listing_unresolved(self, monkeypatch):
        _listings(monkeypatch, users=_refused())
        creators = usage_report.creator_names(_ctx())
        assert creators.names == {APP_RENDER: "render-farm"}
        assert creators.unreadable == ["Users"]

    def test_creator_names_raises_a_session_failure(self, monkeypatch):
        _listings(monkeypatch, applications=ConnectionError("lost"))
        with pytest.raises(ConnectionError):
            usage_report.creator_names(_ctx())

    def test_creator_names_raises_any_other_failure(self, monkeypatch):
        _listings(
            monkeypatch, users=HTTPError(response=SimpleNamespace(status_code=500))
        )
        with pytest.raises(HTTPError):
            usage_report.creator_names(_ctx())


class TestTheCommandByCreator:
    def test_by_creator_prints_a_creator_column(self, platform, monkeypatch, capsys):
        _listings(monkeypatch)
        out, _ = _show(capsys, usage_by=("creator",))
        assert "Creator" in out
        assert "render-farm (Application)" in out
        assert "alice (User)" in out

    def test_json_carries_the_creator_id(self, platform, monkeypatch, capsys):
        _listings(monkeypatch)
        out, _ = _show(capsys, usage_by=("creator",), json_output=True, json=True)
        groups = loads(out)["groups"]
        assert {(g["creator"], g["creatorId"]) for g in groups} == {
            ("render-farm (Application)", APP_RENDER),
            ("alice (User)", USER_ALICE),
        }
        assert list(groups[0])[:2] == ["creator", "creatorId"]

    def test_a_refused_listing_is_warned_of_once(self, platform, monkeypatch, capsys):
        _listings(monkeypatch, users=_refused())
        out, err = _show(capsys, usage_by=("creator",))
        warning = "Could not read the account's Users; their creators are shown by ID"
        assert (out + err).count(warning) == 1
        assert f"{USER_ALICE} (?)" in out

    def test_where_creator_alone_looks_creators_up(self, platform, monkeypatch, capsys):
        calls = _listings(monkeypatch)
        out, _ = _show(capsys, usage_where=[("creator", "render-*")])
        assert calls == ["applications", "users"]
        assert "team-render" in out and "team-train" not in out

    def test_no_lookup_without_creator(self, platform, monkeypatch, capsys):
        calls = _listings(monkeypatch)
        _show(capsys, usage_by=("namespace", "tag"))
        assert calls == []


class TestTheCommand:
    def test_the_table_and_its_total(self, platform, capsys):
        out, err = _show(capsys)
        assert err == ""
        assert (
            "Instance usage from 2026-11-01 00:00 UTC until 2026-11-08 00:00 UTC,"
            " by namespace" in out
        )
        assert "Fetching the usage report from the Platform" in out
        # Where the report came from, then the table's heading above it
        assert (
            out.index("Fetching the usage report")
            < out.index("Report fetched now")
            < out.index("Instance usage from")
            < out.index("Namespace")
        )
        assert "Report fetched now" in out and "--refresh" not in out
        assert f", {usage_report.size_text(len(platform.content))})" in out
        header = next(line for line in out.splitlines() if "Namespace" in line)
        for column in ("Instances", "Running (h:mm)", "Stopped (h:mm)", "Total (h:mm)"):
            assert column in header
        row = next(line for line in out.splitlines() if "team-render" in line)
        assert "2:00" in row  # the stopped hours
        # 6,300 seconds running; 13,860 in all
        assert "Total: 4 Instances, 1:45 running of 3:51 in all statuses" in out

    def test_a_kept_report_says_so_and_how_to_refresh(self, platform, capsys):
        _show(capsys)
        out, _ = _show(capsys)
        assert "Fetching" not in out
        size = usage_report.size_text(len(platform.content))
        assert "Reusing report from an earlier run (2026-" in out
        assert f", {size}), in '" in out
        assert "'--refresh' fetches it again" in out

    def test_json(self, platform, capsys):
        out, _ = _show(capsys, json_output=True, json=True)
        document = loads(out)
        assert document["from"] == "2026-11-01T00:00:00Z"
        assert document["by"] == ["namespace"]
        assert document["namespace"] is None
        assert document["groups"][0] == {
            "namespace": "team-render",
            "instances": 1,
            "hours": {
                "pending": 0.0,
                "running": 0.0,
                "stopping": 0.0,
                "stopped": 2.0,
                "terminating": 0.0,
                "unknown": 0.0,
                "total": 2.0,
            },
            "seconds": {
                "pending": 0,
                "running": 0,
                "stopping": 0,
                "stopped": 7200,
                "terminating": 0,
                "unknown": 0,
                "total": 7200,
            },
        }

    def test_no_instances_is_a_warning(self, platform, capsys):
        platform.content = _zip(instances=[INSTANCES_HEADER])
        out, err = _show(capsys)
        assert "No Instances ran in the window" in out + err
        assert "Total:" not in out

    @pytest.mark.parametrize(
        "args, message",
        [
            ({"usage_from": "not a date at all"}, "Unable to read --from"),
            (
                {"usage_from": "2026-11-08", "usage_until": "2026-11-01"},
                "is not before its end",
            ),
        ],
    )
    def test_a_window_that_cannot_be_used(self, platform, capsys, args, message):
        with pytest.raises(ValueError, match=message):
            _show(capsys, **args)
        assert platform.calls == []


@pytest.mark.parametrize(
    "size, text",
    [
        (1, "1 byte"),
        (999, "999 bytes"),
        (48_213, "48.2 kB"),
        (3_500_000, "3.5 MB"),
        (2_000_000_000, "2.0 GB"),
    ],
)
def test_size_text(size, text):
    assert usage_report.size_text(size) == text


# The fake report's window (_zip()'s summary)
KEPT_FROM = datetime(2026, 11, 1, tzinfo=timezone.utc)
KEPT_UNTIL = datetime(2026, 11, 8, tzinfo=timezone.utc)


def _kept() -> usage_report.Report:
    return usage_report.Report(
        directory=Path("."),
        from_time="2026-11-01T00:00:00Z",
        until_time="2026-11-08T00:00:00.000000Z",
        fetched=KEPT_UNTIL,
        from_cache=True,
    )


class TestWhenAKeptReportIsUsed:
    @pytest.mark.parametrize(
        "shift, now, matches",
        [
            # Fixed past dates, asked again any time later: the same window
            (timedelta(0), KEPT_UNTIL + timedelta(days=30), True),
            # A window ending now: moved on by under, or over, ten minutes
            (timedelta(minutes=9), KEPT_UNTIL + timedelta(minutes=9), True),
            (timedelta(minutes=11), KEPT_UNTIL + timedelta(minutes=11), False),
        ],
    )
    def test_each_end_within_ten_minutes(self, shift, now, matches):
        assert (
            usage_report.window_matches(
                _kept(), KEPT_FROM + shift, KEPT_UNTIL + shift, now
            )
            is matches
        )

    def test_an_end_in_the_future_is_taken_as_now(self):
        later = KEPT_UNTIL + timedelta(days=30)
        assert usage_report.window_matches(
            _kept(), KEPT_FROM, later, KEPT_UNTIL + timedelta(minutes=5)
        )
        assert not usage_report.window_matches(
            _kept(), KEPT_FROM, later, KEPT_UNTIL + timedelta(minutes=15)
        )

    def test_a_kept_window_that_cannot_be_read_is_not_used(self):
        kept = _kept()
        kept.until_time = "not a time"
        assert not usage_report.window_matches(kept, KEPT_FROM, KEPT_UNTIL, KEPT_UNTIL)

    def test_a_window_ending_now_is_fetched_again_after_ten_minutes(self, platform):
        def run(elapsed: timedelta) -> usage_report.Report:
            return usage_report.usage_report(
                _ctx(),
                KEPT_FROM + elapsed,
                KEPT_UNTIL + elapsed,
                "7 days ago",
                "now",
                None,
                refresh=False,
                now=KEPT_UNTIL + elapsed,
            )

        run(timedelta(0))
        assert run(timedelta(minutes=9)).from_cache
        assert len(platform.calls) == 1
        assert not run(timedelta(minutes=11)).from_cache
        assert len(platform.calls) == 2


def test_a_report_kept_without_its_size_is_shown_without_it(platform, capsys):
    report = _report(_ctx())
    (report.directory / "fetched.json").write_text(
        '{"fetched": 1795000000.0}', encoding="utf-8"
    )
    out, _ = _show(capsys)
    line = next(line for line in out.splitlines() if "Reusing report" in line)
    assert "UTC), in '" in line and "kB" not in line and "bytes" not in line


class TestPruning:
    NOW = 1_800_000_000.0
    DAY = 24 * 60 * 60

    def _report_dir(self, root: Path, name: str, age_days: float) -> Path:
        path = root / name
        path.mkdir()
        (path / "instances.csv").write_text("x", encoding="utf-8")
        when = self.NOW - age_days * self.DAY
        os.utime(path, (when, when))
        return path

    def test_reports_unused_for_a_week_are_removed(self, tmp_path):
        old = self._report_dir(tmp_path, "old", 8)
        recent = self._report_dir(tmp_path, "recent", 6)
        just = self._report_dir(tmp_path, "just", 30)  # the one just fetched
        usage_report.prune(tmp_path, keep=just, now=self.NOW)
        assert not old.exists()
        assert recent.exists() and just.exists()

    def test_beyond_twenty_the_least_recently_used_are_removed(self, tmp_path):
        kept = [self._report_dir(tmp_path, f"r{n:02}", n / 10) for n in range(25)]
        just = self._report_dir(tmp_path, "just", 1)
        usage_report.prune(tmp_path, keep=just, now=self.NOW)
        remaining = sorted(path.name for path in tmp_path.iterdir())
        # The 19 most recently used, and the one just fetched
        assert remaining == sorted([p.name for p in kept[:19]] + ["just"])

    def test_a_partial_directory_is_removed_only_once_old(self, tmp_path):
        stale = self._report_dir(tmp_path, "abc.part-123", 8)
        live = self._report_dir(tmp_path, "def.part-456", 0)
        just = self._report_dir(tmp_path, "just", 0)
        usage_report.prune(tmp_path, keep=just, now=self.NOW)
        assert not stale.exists() and live.exists()

    def test_a_removal_that_fails_is_logged_and_left(
        self, tmp_path, monkeypatch, caplog
    ):
        old = self._report_dir(tmp_path, "old", 8)
        just = self._report_dir(tmp_path, "just", 0)

        def refuse(path, *args, **kwargs):
            raise PermissionError(13, "in use", str(path))

        monkeypatch.setattr(usage_report.shutil, "rmtree", refuse)
        with caplog.at_level("DEBUG", logger=usage_report.__name__):
            usage_report.prune(tmp_path, keep=just, now=self.NOW)
        assert old.exists()
        (failure,) = [r for r in caplog.records if "Could not remove" in r.message]
        assert str(old) in failure.message and failure.exc_info is not None

    def test_a_report_read_again_is_kept_as_recently_used(self, platform, tmp_path):
        report = _report(_ctx())
        week_ago = time.time() - 8 * self.DAY
        os.utime(report.directory, (week_ago, week_ago))
        assert _report(_ctx()).from_cache  # read, so touched
        _report(_ctx(namespace="team-render"))  # a fetch, which prunes
        assert report.directory.exists()

    def test_a_fetch_prunes_the_kept_reports(self, platform, tmp_path):
        first = _report(_ctx())
        week_ago = time.time() - 8 * self.DAY
        os.utime(first.directory, (week_ago, week_ago))
        _report(_ctx(namespace="team-render"))
        assert not first.directory.exists()


def test_a_kept_zip_that_cannot_be_read_is_fetched_again(platform):
    report = _report(_ctx())
    report.path.write_bytes(b"damaged")
    assert not _report(_ctx()).from_cache
    assert len(platform.calls) == 2


class TestTheShownPath:
    def test_the_temporary_directory_is_written_as_its_variable(
        self, monkeypatch, tmp_path
    ):
        for variable in ("TMPDIR", "TEMP", "TMP"):
            monkeypatch.delenv(variable, raising=False)
        monkeypatch.setenv("TMPDIR", str(tmp_path) + os.sep)
        path = tmp_path / "yellowdog-cli-usage-501" / "0123456789abcdef" / "report.zip"
        assert usage_report.shown_path(path) == "$TMPDIR" + os.sep + os.path.join(
            "yellowdog-cli-usage-501", "0123456789abcdef", "report.zip"
        )

    def test_windows_temp_is_written_as_cmd_writes_it(self, monkeypatch, tmp_path):
        for variable in ("TMPDIR", "TEMP", "TMP"):
            monkeypatch.delenv(variable, raising=False)
        monkeypatch.setenv("TEMP", str(tmp_path))
        shown = usage_report.shown_path(tmp_path / "x" / "report.zip")
        assert shown == "%TEMP%" + os.sep + os.path.join("x", "report.zip")

    def test_a_path_elsewhere_is_shown_in_full(self, monkeypatch, tmp_path):
        for variable in ("TMPDIR", "TEMP", "TMP"):
            monkeypatch.delenv(variable, raising=False)
        monkeypatch.setenv("TMPDIR", str(tmp_path / "other"))
        path = tmp_path / "otherwise" / "report.zip"
        assert usage_report.shown_path(path) == str(path)

    def test_the_directory_name_is_sixteen_hex_digits(self, platform):
        name = _report(_ctx()).directory.name
        assert len(name) == 16 and int(name, 16) >= 0

    def test_json_keeps_the_full_path(self, platform, capsys, monkeypatch):
        monkeypatch.setenv("TMPDIR", str(usage_report.Path(".").resolve()))
        out, _ = _show(capsys, json_output=True, json=True)
        assert os.path.isabs(loads(out)["reportFile"])


class TestFilters:
    def test_a_filter_is_a_key_and_a_pattern(self):
        assert usage_filter("provider=aws") == ("provider", "aws")
        assert usage_filter("instance-type=g4dn.*") == ("instance-type", "g4dn.*")
        assert usage_filter("tag=a=b") == ("tag", "a=b")  # the first '=' splits

    @pytest.mark.parametrize(
        "value, message",
        [
            ("provider", "is not 'key=pattern'"),
            ("providr=aws", "did you mean 'provider'"),
            ("provider=", "has no pattern"),
        ],
    )
    def test_a_filter_that_cannot_be_used_is_refused(self, value, message):
        with pytest.raises(ArgumentTypeError, match=message):
            usage_filter(value)

    def _groups(self, platform, by, *where):
        report = _report(_ctx())
        return {
            tuple(group.keys.values()): group.instances
            for group in usage_report.grouped_usage(
                report, by, usage_report.filter_of(list(where))
            )
        }

    def test_a_filter_matches_in_any_case(self, platform):
        assert self._groups(platform, ["provider"], ("provider", "aws")) == {
            ("AWS",): 4
        }

    def test_a_glob(self, platform):
        assert self._groups(
            platform, ["instance-type"], ("instance-type", "t3a.*")
        ) == {("t3a.small",): 2}

    def test_different_keys_must_all_match(self, platform):
        assert self._groups(
            platform,
            ["namespace", "pricing"],
            ("namespace", "team-train"),
            ("pricing", "on-demand"),
        ) == {("team-train", "on-demand"): 2}

    def test_the_same_key_again_matches_either(self, platform):
        assert self._groups(
            platform,
            ["instance-type"],
            ("instance-type", "g4dn.xlarge"),
            ("instance-type", "t2.*"),
        ) == {("g4dn.xlarge",): 1, ("t2.small",): 1}

    def test_a_key_need_not_be_grouped_by(self, platform):
        assert self._groups(platform, ["namespace"], ("pricing", "spot")) == {
            ("team-train",): 1
        }

    def test_the_summary_and_json_name_the_filters(self, platform, capsys):
        where = [("provider", "aws"), ("instance-type", "t3a.*"), ("provider", "oci")]
        out, _ = _show(capsys, usage_where=where)
        assert ", by namespace, where provider=aws or oci, instance-type=t3a.*" in out
        assert "Total: 2 Instances" in out
        document = loads(
            _show(capsys, usage_where=where, json_output=True, json=True)[0]
        )
        assert document["where"] == {
            "provider": ["aws", "oci"],
            "instance-type": ["t3a.*"],
        }
        assert [g["instances"] for g in document["groups"]] == [2]

    def test_no_filters_is_an_empty_where(self, platform, capsys):
        document = loads(_show(capsys, json_output=True, json=True)[0])
        assert document["where"] == {}

    def test_nothing_matching_says_so(self, platform, capsys):
        out, err = _show(capsys, usage_where=[("provider", "azure")])
        assert "No Instances in the window match the filters" in out + err


class _ScopedPlatform(_Platform):
    """
    The report endpoint as it answers an Application that may read usage in
    'usable' alone: refusing an unscoped request, and naming the namespaces
    it may not read in one that asks for them.
    """

    def __init__(self, usable: set[str]):
        super().__init__()
        self.usable = usable

    def __call__(self, url, headers, json, timeout, stream=False):
        self.calls.append(
            {"url": url, "headers": headers, "json": json, "stream": stream}
        )
        namespaces = json.get("namespaces")
        if namespaces is None:
            text = (
                '{"errorType": "MissingPermissionException", "message": "Missing'
                ' required permissions: COMPUTE_USAGE_READ with global scope."}'
            )
            return _answer(403, text=text)
        refused = sorted(set(namespaces) - self.usable)
        if refused:
            text = (
                '{"errorType": "MissingPermissionException", "message": "Missing'
                f" required permissions: COMPUTE_USAGE_READ (namespaces:"
                f' [{", ".join(refused)}], namespaceIds: [])"}}'
            )
            return _answer(403, text=text)
        return _answer(200, self.content)


class TestANamespaceScopedApplication:
    @pytest.fixture
    def scoped(self, monkeypatch, tmp_path):
        """
        Install a scoped Platform: readable is what search_namespaces()
        gives (None: every namespace), usable where usage may be read.
        """
        from yellowdog_cli.utils import entity_utils

        monkeypatch.setattr(completion_cache, "_temp_root", lambda: tmp_path)

        def install(readable, usable, every=("team-render", "team-train")):
            fake = _ScopedPlatform(set(usable))
            monkeypatch.setattr(usage_report.requests, "put", fake)
            monkeypatch.setattr(
                entity_utils, "search_namespaces", lambda client, namespace: readable
            )
            monkeypatch.setattr(
                entity_utils,
                "get_application_details",
                lambda client: SimpleNamespace(allNamespacesReadable=readable is None),
            )
            monkeypatch.setattr(
                usage_report, "_all_namespaces", lambda ctx: list(every)
            )
            return fake

        return install

    def _asked(self, fake) -> list:
        return [call["json"].get("namespaces") for call in fake.calls]

    def test_its_readable_namespaces_are_asked_for(self, scoped, capsys):
        fake = scoped(["team-render", "team-train"], {"team-render", "team-train"})
        out, _ = _show(capsys)
        assert self._asked(fake) == [["team-render", "team-train"]]
        assert (
            "Reporting on the 2 namespaces this Application can read usage in:"
            " team-render, team-train" in out
        )
        assert "not on" not in out

    def test_a_narrowed_retry_streams_both_requests(self, scoped, terminal):
        fake = scoped(["team-render", "team-train", "team-x"], {"team-train"})
        report = _fetch_shown()
        assert [call["stream"] for call in fake.calls] == [True, True]
        assert report.refused == ["team-render", "team-x"]
        assert "Downloading the report" in terminal.getvalue()

    def test_a_namespace_it_cannot_read_usage_in_is_dropped(self, scoped, capsys):
        fake = scoped(["team-render", "team-train", "team-x"], {"team-train"})
        out, _ = _show(capsys)
        assert self._asked(fake) == [
            ["team-render", "team-train", "team-x"],
            ["team-train"],
        ]
        assert (
            "Reporting on the 1 namespace this Application can read usage in:"
            " team-train; not on team-render, team-x, where it cannot" in out
        )
        document = loads(_show(capsys, json_output=True, json=True)[0])
        assert document["namespaces"] == ["team-train"]

    def test_every_namespace_readable_but_not_usage_in_all(self, scoped, capsys):
        fake = scoped(None, {"team-train"})
        out, _ = _show(capsys)
        assert self._asked(fake) == [
            None,
            ["team-render", "team-train"],
            ["team-train"],
        ]
        assert "this Application can read usage in: team-train" in out

    def test_usage_readable_nowhere_is_refused(self, scoped, capsys):
        fake = scoped(["team-x"], set())
        with pytest.raises(HTTPError) as raised:
            _show(capsys)
        assert classify(raised.value) == ExitCode.PERMISSION
        assert self._asked(fake) == [["team-x"]]

    def test_a_namespace_given_is_not_second_guessed(self, scoped, capsys):
        fake = scoped(["team-render"], {"team-render"})
        with pytest.raises(HTTPError):
            _show(capsys, namespace="team-x")
        assert self._asked(fake) == [["team-x"]]

    def test_an_application_reading_everything_asks_once_unscoped(
        self, platform, capsys, monkeypatch
    ):
        from yellowdog_cli.utils import entity_utils

        monkeypatch.setattr(entity_utils, "search_namespaces", lambda c, n: None)
        out, _ = _show(capsys)
        assert [call["json"].get("namespaces") for call in platform.calls] == [None]
        assert "Reporting on the" not in out
        assert (
            loads(_show(capsys, json_output=True, json=True)[0])["namespaces"] is None
        )

    def test_a_kept_report_remembers_its_namespaces(self, scoped, capsys):
        scoped(["team-render", "team-train"], {"team-train"})
        _show(capsys)
        out, _ = _show(capsys)
        assert "Reusing report" in out
        assert "can read usage in: team-train; not on team-render" in out

    def test_the_refused_namespaces_are_read_from_the_message(self):
        text = (
            "Missing required permissions: COMPUTE_USAGE_READ (namespaces:"
            " [ray-test, yd-demo], namespaceIds: [])"
        )
        assert usage_report._refused_namespaces(text) == ["ray-test", "yd-demo"]
        assert usage_report._refused_namespaces("Something else") == []


class TestANamespaceThatDoesNotExist:
    def _ctx_with_namespaces(self, *existing, fails=None, **args) -> RunContext:
        ctx = _ctx(**args)
        search = ctx.client.namespaces_client.get_namespaces.return_value
        if fails is not None:
            search.list_all.side_effect = fails
        else:
            search.list_all.return_value = [
                SimpleNamespace(namespace=name) for name in existing
            ]
        return ctx

    def _show_ctx(self, capsys, ctx) -> str:
        with output_settings.configured(ctx.args):
            usage.show_usage(ctx)
        return capsys.readouterr().out

    def test_an_empty_report_for_a_namespace_that_does_not_exist(
        self, platform, capsys
    ):
        platform.content = _zip(instances=[INSTANCES_HEADER])
        # The search matches a substring: a longer name is not the one given
        ctx = self._ctx_with_namespaces("team-xx", namespace="team-x")
        with pytest.raises(
            NotFoundError, match="No namespace 'team-x' exists"
        ) as raised:
            self._show_ctx(capsys, ctx)
        assert classify(raised.value) == ExitCode.NOT_FOUND

    def test_a_missing_namespace_is_found_before_any_creator_lookup(
        self, platform, monkeypatch, capsys
    ):
        platform.content = _zip(instances=[INSTANCES_HEADER])
        calls = _listings(monkeypatch, users=_refused())
        ctx = self._ctx_with_namespaces(namespace="team-x", usage_by=("creator",))
        with pytest.raises(NotFoundError, match="No namespace 'team-x' exists"):
            self._show_ctx(capsys, ctx)
        assert calls == []
        assert "Could not read" not in capsys.readouterr().err

    def test_an_empty_report_for_a_namespace_that_exists(self, platform, capsys):
        platform.content = _zip(instances=[INSTANCES_HEADER])
        ctx = self._ctx_with_namespaces("team-x", namespace="team-x")
        out = self._show_ctx(capsys, ctx)
        assert "No Instances ran in the window" in out + capsys.readouterr().err

    def test_a_report_with_instances_looks_nothing_up(self, platform, capsys):
        ctx = self._ctx_with_namespaces(namespace="team-render")
        self._show_ctx(capsys, ctx)
        ctx.client.namespaces_client.get_namespaces.assert_not_called()

    def test_filters_matching_nothing_are_not_a_missing_namespace(
        self, platform, capsys
    ):
        ctx = self._ctx_with_namespaces(
            namespace="team-render", usage_where=[("provider", "azure")]
        )
        out = self._show_ctx(capsys, ctx)
        assert "match the filters" in out + capsys.readouterr().err
        ctx.client.namespaces_client.get_namespaces.assert_not_called()

    def test_a_search_that_cannot_say_is_taken_as_existing(self, platform, capsys):
        platform.content = _zip(instances=[INSTANCES_HEADER])
        refused = HTTPError("403 MissingPermissionException")
        refused.response = SimpleNamespace(status_code=403)
        ctx = self._ctx_with_namespaces(fails=refused, namespace="team-x")
        out = self._show_ctx(capsys, ctx)
        assert "No Instances ran in the window" in out + capsys.readouterr().err

    def test_a_session_failure_in_the_search_is_raised(self, platform, capsys):
        from requests import ConnectionError as RequestsConnectionError

        platform.content = _zip(instances=[INSTANCES_HEADER])
        ctx = self._ctx_with_namespaces(
            fails=RequestsConnectionError("unreachable"), namespace="team-x"
        )
        with pytest.raises(RequestsConnectionError):
            self._show_ctx(capsys, ctx)


@pytest.mark.parametrize(
    "seconds, text",
    [
        (0, "0:00"),
        (1, "<0:01"),
        (59, "<0:01"),
        (60, "0:01"),
        (89, "0:01"),
        (90, "0:02"),  # to the nearest minute, a half rounding up
        (150, "0:03"),
        (3600, "1:00"),
        (351 * 3600 + 24 * 60, "351:24"),
        (1234 * 3600 + 5 * 60, "1,234:05"),
    ],
)
def test_duration_text(seconds, text):
    assert usage.duration_text(seconds) == text


def test_json_seconds_are_exact_where_hours_round(platform, capsys):
    platform.content = _zip(
        instances=[INSTANCES_HEADER, _instance(CR_TRAIN, "t3a.small", running=1)]
    )
    (group,) = loads(_show(capsys, json_output=True, json=True)[0])["groups"]
    assert group["hours"]["running"] == 0.0
    assert group["seconds"]["running"] == 1
