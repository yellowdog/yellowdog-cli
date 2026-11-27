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
from json import dumps, loads
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
    usage_cost,
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
from yellowdog_cli.utils.usage_text import cost_text_of, duration_text

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
    monkeypatch.setattr(usage_report.direct_http, "put", fake)
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
        "usage_cost": False,
        "usage_top": None,
        "usage_sort": ("total",),
        "reverse": False,
        "csv_output": False,
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

    @pytest.mark.parametrize("key", ["requirement", "requirement-id", "instance"])
    def test_requirement_is_no_key(self, key):
        # The Compute Requirement's keys are cr and cr-id
        with pytest.raises(ArgumentTypeError, match=f"invalid grouping '{key}'"):
            usage_group_keys(key)

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

        monkeypatch.setattr(usage_report.direct_http, "put", timed_out)
        with pytest.raises(ReadTimeout, match=r"5 minutes.*requestTimeout") as raised:
            _report(_ctx())
        assert classify(raised.value) == ExitCode.CONNECTION

    def test_a_connect_timeout_is_not_called_a_wait_for_the_report(
        self, platform, monkeypatch
    ):
        def unreachable(**kwargs):
            raise ConnectTimeout("connect timed out")

        monkeypatch.setattr(usage_report.direct_http, "put", unreachable)
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

        monkeypatch.setattr(usage_report.direct_http, "put", stalls)
        with pytest.raises(
            ConnectionError, match=r"5 minutes.*requestTimeout"
        ) as raised:
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

        monkeypatch.setattr(usage_report.direct_http, "put", lost)
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

        monkeypatch.setattr(usage_report.direct_http, "put", broken)
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
        groups = usage_report.grouped_usage(_report(_ctx()), ["cr", "tag"])
        assert {tuple(group.keys.values()) for group in groups} == {
            ("render-1", "nightly"),
            ("train-1", "-"),
        }

    def test_an_instance_whose_requirement_is_not_listed(self, platform):
        platform.content = _zip(
            instances=[INSTANCES_HEADER, _instance(CR_GONE, "t3a.small", 60)]
        )
        report = _report(_ctx())
        (group,) = usage_report.grouped_usage(report, ["namespace", "cr", "cr-id"])
        assert group.keys == {"namespace": "-", "cr": CR_GONE, "cr-id": CR_GONE}

    def test_by_cr_id_separates_requirements_sharing_a_name(self, platform):
        # A name reused, here in two namespaces: one row by cr, two by cr-id
        platform.content = _zip(
            requirements=[
                *REQUIREMENTS[:2],
                f"team-train,render-1,,2026-11-02T00:00:00Z,,{USER_ALICE},{CR_TRAIN}",
            ]
        )
        report = _report(_ctx())
        by_name = usage_report.grouped_usage(report, ["cr"])
        by_id = usage_report.grouped_usage(report, ["cr-id"])
        assert [(g.keys["cr"], g.instances) for g in by_name] == [("render-1", 4)]
        assert {g.keys["cr-id"]: g.instances for g in by_id} == {
            CR_RENDER: 1,
            CR_TRAIN: 3,
        }

    def test_by_instance_is_one_row_per_instance(self, platform):
        groups = usage_report.grouped_usage(_report(_ctx()), ["instance-id"])
        assert {g.keys["instance-id"]: g.instances for g in groups} == {
            "i-1": 1,
            "i-2": 1,
            "i-3": 1,
            "i-4": 1,
        }

    def test_by_creator_id_is_the_id_without_names(self, platform):
        groups = usage_report.grouped_usage(
            _report(_ctx()), ["creator-id"], creators=NAMES
        )
        assert {g.keys["creator-id"]: g.instances for g in groups} == {
            APP_RENDER: 1,
            USER_ALICE: 3,
        }


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

    def test_creator_id_looks_nothing_up(self, platform, monkeypatch, capsys):
        calls = _listings(monkeypatch)
        out, _ = _show(
            capsys,
            usage_by=("creator-id",),
            usage_where=[("creator-id", APP_RENDER)],
        )
        assert calls == []
        assert APP_RENDER in out and USER_ALICE not in out

    def test_where_creator_id_does_not_match_a_name(
        self, platform, monkeypatch, capsys
    ):
        _listings(monkeypatch)
        out, err = _show(capsys, usage_where=[("creator-id", "render-*")])
        assert "No Instances in the window match the filters" in out + err

    def test_no_lookup_without_creator(self, platform, monkeypatch, capsys):
        calls = _listings(monkeypatch)
        _show(capsys, usage_by=("namespace", "tag"))
        assert calls == []


class TestTheCommand:
    def test_the_new_keys_are_headed_in_full(self, platform, monkeypatch, capsys):
        _listings(monkeypatch)
        out, _ = _show(capsys, usage_by=("cr", "cr-id", "creator-id", "instance-id"))
        for heading in (
            "Compute Requirement",
            "Compute Requirement ID",
            "Creator ID",
            "Instance ID",
        ):
            assert heading in out

    def test_json_names_the_new_keys_as_given(self, platform, monkeypatch, capsys):
        out, _ = _show(
            capsys,
            usage_by=("cr", "cr-id", "creator-id", "instance-id"),
            json_output=True,
            json=True,
        )
        group = loads(out)["groups"][0]
        assert list(group)[:4] == ["cr", "cr-id", "creator-id", "instance-id"]

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
                None,
                refresh=False,
                now=KEPT_UNTIL + elapsed,
            )

        run(timedelta(0))
        assert run(timedelta(minutes=9)).from_cache
        assert len(platform.calls) == 1
        assert not run(timedelta(minutes=11)).from_cache
        assert len(platform.calls) == 2

    @staticmethod
    def _run(
        from_time: datetime,
        until_time: datetime,
        now: datetime,
        refresh: bool = False,
        namespace: str | None = None,
    ) -> usage_report.Report:
        return usage_report.usage_report(
            _ctx(), from_time, until_time, namespace, refresh=refresh, now=now
        )

    def test_a_window_ending_now_is_found_again_by_the_dates_it_shows(self, platform):
        # Fetched as '--from 7d --until now' 39 seconds past the minute, then
        # asked for days later by the minutes its summary showed
        fetched = KEPT_UNTIL + timedelta(seconds=39)
        first = self._run(KEPT_FROM + timedelta(seconds=39), fetched, fetched)
        later = self._run(KEPT_FROM, KEPT_UNTIL, fetched + timedelta(days=2))
        assert later.from_cache and later.directory == first.directory
        assert len(platform.calls) == 1

    def test_of_several_that_match_the_last_fetched_is_used(self, platform):
        self._run(KEPT_FROM, KEPT_UNTIL, KEPT_UNTIL)
        refreshed = self._run(
            KEPT_FROM + timedelta(minutes=1), KEPT_UNTIL, KEPT_UNTIL, refresh=True
        )
        assert self._run(KEPT_FROM, KEPT_UNTIL, KEPT_UNTIL).directory == (
            refreshed.directory
        )
        assert len(platform.calls) == 2

    def test_a_matching_window_of_another_namespace_is_not_used(self, platform):
        self._run(KEPT_FROM, KEPT_UNTIL, KEPT_UNTIL)
        assert not self._run(
            KEPT_FROM, KEPT_UNTIL, KEPT_UNTIL, namespace="team-render"
        ).from_cache

    def test_a_report_kept_without_its_scope_is_not_used(self, platform):
        report = self._run(KEPT_FROM, KEPT_UNTIL, KEPT_UNTIL)
        (report.directory / "fetched.json").write_text(
            dumps({"fetched": 1795000000.0}), encoding="utf-8"
        )
        assert not self._run(KEPT_FROM, KEPT_UNTIL, KEPT_UNTIL).from_cache


def test_a_report_kept_without_its_size_is_shown_without_it(platform, capsys):
    report = _report(_ctx())
    kept = report.directory / "fetched.json"
    scope = loads(kept.read_text(encoding="utf-8"))["scope"]
    kept.write_text(dumps({"fetched": 1795000000.0, "scope": scope}), encoding="utf-8")
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


class TestExactFilters:
    """
    '--where key==value': the value after '=' exactly, with its case.
    """

    @pytest.fixture
    def rows(self, platform):
        platform.content = _zip(
            instances=[
                INSTANCES_HEADER,
                _instance(CR_RENDER, "g4dn.xlarge", 60, instance_id="i-1"),
                _instance(CR_TRAIN, "t3a.small", 60, instance_id="i-2"),
                _instance(CR_GONE, "t3a.small", 60, instance_id="i-3"),
            ],
            requirements=[
                REQUIREMENTS[0],
                f"team-a,Render,team[1],2026-11-01T00:00:00Z,,{APP_RENDER},{CR_RENDER}",
                f"team-b,render,=odd,2026-11-01T00:00:00Z,,{USER_ALICE},{CR_TRAIN}",
                f"team-c,other,,2026-11-01T00:00:00Z,,,{CR_GONE}",
            ],
        )

    def _keys(self, by, where, creators=NAMES):
        groups = usage_report.grouped_usage(
            _report(_ctx()),
            by,
            usage_report.filter_of(where),
            creators=creators,
        )
        return sorted(next(iter(g.keys.values())) for g in groups)

    def test_exact_matches_with_case(self, rows):
        assert self._keys(["cr"], [("cr", "=Render")]) == ["Render"]

    def test_exact_takes_glob_characters_literally(self, rows):
        assert self._keys(["tag"], [("tag", "=team[1]")]) == ["team[1]"]
        assert self._keys(["tag"], [("tag", "=team?1?")]) == []

    def test_exact_dash_is_the_missing_value(self, rows):
        assert self._keys(["namespace"], [("tag", "=-")]) == ["team-c"]

    def test_exact_creator_by_id_and_by_shown_name(self, rows):
        by_id = self._keys(["namespace"], [("creator", f"={APP_RENDER}")])
        by_shown = self._keys(
            ["namespace"], [("creator", "=render-farm (Application)")]
        )
        by_name = self._keys(["namespace"], [("creator", "=render-farm")])
        assert by_id == by_shown == by_name == ["team-a"]

    def test_exact_and_glob_mix(self, rows):
        assert self._keys(["namespace"], [("cr", "=Render"), ("provider", "aws")]) == [
            "team-a"
        ]
        assert (
            self._keys(["namespace"], [("cr", "=Render"), ("provider", "azure")]) == []
        )

    def test_glob_is_unchanged(self, rows):
        assert self._keys(["cr"], [("cr", "render")]) == ["Render", "render"]

    def test_a_leading_equals_value(self, rows):
        assert self._keys(["tag"], [("tag", "==odd")]) == ["=odd"]

    def test_the_summary_and_json_name_the_exact_filter(self, rows, capsys):
        where = [("cr", "=Render")]
        out, _ = _show(capsys, usage_where=where)
        assert "where cr==Render" in out
        document = loads(
            _show(capsys, usage_where=where, json_output=True, json=True)[0]
        )
        assert document["where"] == {"cr": ["=Render"]}


@pytest.mark.parametrize(
    "text, parsed",
    [("cr==Render", ("cr", "=Render")), ("tag===odd", ("tag", "==odd"))],
)
def test_usage_filter_keeps_the_exact_form(text, parsed):
    assert usage_filter(text) == parsed


def test_usage_filter_refuses_an_empty_exact_value():
    with pytest.raises(ArgumentTypeError, match="has no value after '=='"):
        usage_filter("cr==")


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
            monkeypatch.setattr(usage_report.direct_http, "put", fake)
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
    assert duration_text(seconds) == text


@pytest.mark.parametrize(
    "cost, partial, text",
    [(None, False, "-"), (1234.5, False, "1,234.50"), (1.0, True, "1.00+")],
)
def test_cost_text_of(cost, partial, text):
    assert cost_text_of(cost, partial) == text


def test_json_seconds_are_exact_where_hours_round(platform, capsys):
    platform.content = _zip(
        instances=[INSTANCES_HEADER, _instance(CR_TRAIN, "t3a.small", running=1)]
    )
    (group,) = loads(_show(capsys, json_output=True, json=True)[0])["groups"]
    assert group["hours"]["running"] == 0.0
    assert group["seconds"]["running"] == 1


def _price(
    instance_type,
    usage_type,
    value,
    currency="USD",
    provider="AWS",
    region="eu-west-2",
    licence="NONE",
):
    """
    A Cloud Info price row as the SDK gives one.
    """
    from yellowdog_client.model import (
        CloudProvider,
        Currency,
        OperatingSystemLicence,
        UsageType,
    )

    return SimpleNamespace(
        provider=CloudProvider[provider],
        region=region,
        subRegion="N/A",
        instanceType=instance_type,
        usageType=UsageType[usage_type],
        operatingSystemLicence=OperatingSystemLicence[licence],
        price=SimpleNamespace(currency=Currency[currency], value=value),
    )


def _priced(ctx: RunContext, rows) -> MagicMock:
    """
    The price search answering with these rows (or raising this exception).
    """
    search = ctx.client.cloud_info_client.get_instance_type_prices
    if isinstance(rows, BaseException):
        search.return_value.list_all.side_effect = rows
    else:
        search.return_value.list_all.return_value = rows
    return search


# The fixture's Instances: i-1 g4dn.xlarge, no running time; i-2 t3a.small,
# 3600s on-demand; i-3 t3a.small, 1800s spot; i-4 t2.small, 900s on-demand
PRICES = [
    _price("t2.small", "ON_DEMAND", 0.04),
    _price("t3a.small", "ON_DEMAND", 0.02),
    _price("t3a.small", "SPOT", 0.01),
    _price("t3a.small", "SPOT", 0.03),
]


class TestCost:
    def _costed(self, platform, rows=PRICES, by=("instance-id",), where=None):
        ctx = _ctx()
        _priced(ctx, rows)
        report = _report(ctx)
        found = usage_cost.list_prices(ctx, {("AWS", "eu-west-2")})
        assert found.unreadable == [] and not found.refused
        costing = usage_cost.Costing(found.prices)
        groups = usage_report.grouped_usage(
            report, list(by), usage_report.filter_of(where), costing=costing
        )
        return {g.keys[by[0]]: g for g in groups}, costing

    def test_on_demand_is_running_hours_times_the_price(self, platform):
        groups, _ = self._costed(platform)
        assert groups["i-4"].cost == pytest.approx(0.25 * 0.04)
        assert groups["i-2"].cost == pytest.approx(1.0 * 0.02)

    def test_spot_is_the_mean_of_the_sub_region_prices(self, platform):
        groups, _ = self._costed(platform)
        assert groups["i-3"].cost == pytest.approx(0.5 * 0.02)

    def test_an_unpriced_instance_is_noted_with_its_hours(self, platform):
        rows = [_price("t2.small", "ON_DEMAND", 0.04)]
        groups, costing = self._costed(platform, rows)
        assert costing.unpriced == {
            ("AWS", "eu-west-2", "t3a.small", "on-demand"): 3600,
            ("AWS", "eu-west-2", "t3a.small", "spot"): 1800,
        }
        assert groups["i-2"].unpriced_seconds == 3600
        assert groups["i-2"].cost == 0

    def test_a_spot_instance_is_not_priced_on_demand(self, platform):
        rows = [_price("t3a.small", "ON_DEMAND", 0.02)]
        groups, costing = self._costed(platform, rows)
        assert groups["i-3"].unpriced_seconds == 1800
        assert ("AWS", "eu-west-2", "t3a.small", "spot") in costing.unpriced

    def test_no_running_time_is_never_unpriced(self, platform):
        groups, costing = self._costed(platform)
        assert groups["i-1"].unpriced_seconds == 0
        assert groups["i-1"].priced_seconds == 0
        assert not any(key[2] == "g4dn.xlarge" for key in costing.unpriced)
        assert usage_cost.cost_text(groups["i-1"]) == "0.00"

    def test_cost_text(self, platform):
        rows = [_price("t2.small", "ON_DEMAND", 0.04)]
        groups, _ = self._costed(platform, rows, by=("pricing",))
        on_demand, spot = groups["on-demand"], groups["spot"]
        assert usage_cost.cost_text(on_demand) == "0.01+"  # t3a.small unpriced
        assert usage_cost.cost_text(spot) == "-"
        assert usage_cost.estimated_cost(spot) is None
        assert usage_cost.estimated_cost(on_demand) == pytest.approx(0.01)
        full, _ = self._costed(platform, by=("instance-id",))
        assert usage_cost.cost_text(full["i-4"]) == "0.01"

    def test_one_search_per_place_counted(self, platform):
        ctx = _ctx()
        search = _priced(ctx, PRICES)
        report = _report(ctx)
        places = usage_report.counted_places(
            report, usage_report.filter_of([("provider", "aws")])
        )
        assert places == {("AWS", "eu-west-2")}
        assert not usage_report.counted_places(
            report, usage_report.filter_of([("provider", "oci")])
        )
        usage_cost.list_prices(ctx, places)
        (call,) = search.call_args_list
        sent = call.args[0]
        assert [p.name for p in sent.providers] == ["AWS"]
        assert sent.region == "eu-west-2"
        assert [o.name for o in sent.operatingSystemLicences] == ["NONE"]

    def test_an_unknown_provider_is_not_searched(self, platform):
        ctx = _ctx()
        search = _priced(ctx, PRICES)
        assert usage_cost.list_prices(ctx, {("NEWCLOUD", "x")}) == usage_cost.Prices()
        search.assert_not_called()

    def test_a_failed_search_leaves_its_place_unreadable(self, platform):
        ctx = _ctx()
        _priced(ctx, HTTPError(response=SimpleNamespace(status_code=500)))
        assert usage_cost.list_prices(ctx, {("AWS", "eu-west-2")}) == (
            usage_cost.Prices(unreadable=[("AWS", "eu-west-2")])
        )

    def test_a_refusal_stops_the_searches(self, platform):
        # Refused once is refused everywhere: no search of the other places
        ctx = _ctx()
        search = _priced(ctx, _refused())
        found = usage_cost.list_prices(
            ctx, {("AWS", "eu-west-2"), ("AZURE", "northeurope"), ("OCI", "x")}
        )
        assert search.call_count == 1
        assert found.refused
        assert found.unreadable == [
            ("AWS", "eu-west-2"),
            ("AZURE", "northeurope"),
            ("OCI", "x"),
        ]
        assert found.prices == {}

    def test_one_failed_place_leaves_the_others_priced(self, platform):
        ctx = _ctx()
        search = ctx.client.cloud_info_client.get_instance_type_prices
        search.return_value.list_all.side_effect = [
            HTTPError(response=SimpleNamespace(status_code=500)),
            [
                _price(
                    "Standard_B2s",
                    "ON_DEMAND",
                    0.05,
                    provider="AZURE",
                    region="northeurope",
                )
            ],
        ]
        found = usage_cost.list_prices(
            ctx, {("AWS", "eu-west-2"), ("AZURE", "northeurope")}
        )
        assert found.unreadable == [("AWS", "eu-west-2")] and not found.refused
        assert found.prices == {
            ("AZURE", "northeurope", "Standard_B2s", "on-demand"): 0.05
        }

    def test_a_session_failure_propagates(self, platform):
        ctx = _ctx()
        _priced(ctx, ConnectionError("down"))
        with pytest.raises(ConnectionError):
            usage_cost.list_prices(ctx, {("AWS", "eu-west-2")})

    def test_a_non_usd_row_is_unpriced(self, platform):
        rows = [_price("t2.small", "ON_DEMAND", 0.04, currency="GBP")]
        groups, costing = self._costed(platform, rows)
        assert groups["i-4"].unpriced_seconds == 900
        assert ("AWS", "eu-west-2", "t2.small", "on-demand") in costing.unpriced


def _show_priced(capsys, rows=PRICES, **args) -> tuple[str, str, MagicMock]:
    """
    _show() with the price search answering with these rows.
    """
    ctx = _ctx(**args)
    search = _priced(ctx, rows)
    with output_settings.configured(ctx.args):
        usage.show_usage(ctx)
    captured = capsys.readouterr()
    return captured.out, captured.err, search


class TestTheCommandWithCost:
    def test_cost_adds_a_column_and_the_total(self, platform, capsys):
        out, _, _ = _show_priced(capsys, usage_cost=True)
        assert "Est. cost (USD)" in out
        # 0.25h at 0.04, 1h at 0.02, 0.5h at 0.02 (the spot mean)
        assert "est. $0.04 at list prices" in out

    def test_unpriced_are_noted_under_the_table(self, platform, capsys):
        rows = [_price("t2.small", "ON_DEMAND", 0.04)]
        out, _, _ = _show_priced(capsys, rows, usage_cost=True)
        lines = [line for line in out.splitlines() if "No list price" in line]
        # Warnings, the most running time first
        assert len(lines) == 2 and all("WARNING" in line for line in lines)
        assert "AWS eu-west-2 t3a.small (on-demand): 1:00" in lines[0]
        assert "AWS eu-west-2 t3a.small (spot): 0:30" in lines[1]
        assert "est. $0.01+ at list prices" in out

    def test_a_refusal_is_one_warning(self, platform, capsys):
        out, err, _ = _show_priced(capsys, _refused(), usage_cost=True)
        assert (out + err).count(
            "This Application may not read cloud prices; no cost is estimated"
        ) == 1
        assert "Could not read the list prices in" not in out + err

    def test_unreadable_prices_warn_and_leave_their_instances_unpriced(
        self, platform, capsys
    ):
        failed = HTTPError(response=SimpleNamespace(status_code=500))
        out, err, _ = _show_priced(capsys, failed, usage_cost=True)
        assert (
            "Could not read the list prices in AWS eu-west-2; its Instances are"
            " not costed" in out + err
        )
        assert "Est. cost" in out
        (row,) = [line for line in out.splitlines() if "team-train" in line]
        assert row.rstrip().rstrip("│").rstrip().endswith("-")
        # Nothing priced at all: the total says so rather than '$0.00+'
        assert "est. $" not in out
        assert "no running time priced" in out

    def test_json_names_the_unreadable_places(self, platform, capsys):
        out, _, _ = _show_priced(
            capsys, _refused(), usage_cost=True, json_output=True, json=True
        )
        document = loads(out)
        assert document["currency"] == "USD"
        assert document["unreadablePrices"] == [
            {"provider": "AWS", "region": "eu-west-2"}
        ]
        assert document["pricesRefused"] is True
        assert {g["estimatedCost"] for g in document["groups"]} == {None, 0.0}

    def test_json_with_cost(self, platform, capsys):
        rows = [_price("t2.small", "ON_DEMAND", 0.04)]
        out, _, _ = _show_priced(
            capsys,
            rows,
            usage_cost=True,
            usage_by=("pricing",),
            json_output=True,
            json=True,
        )
        document = loads(out)
        assert document["currency"] == "USD"
        assert document["unreadablePrices"] == []
        assert document["pricesRefused"] is False
        groups = {g["pricing"]: g for g in document["groups"]}
        assert groups["on-demand"]["estimatedCost"] == 0.01
        assert groups["on-demand"]["unpricedRunningHours"] == 1.0
        assert groups["spot"]["estimatedCost"] is None
        assert {
            "provider": "AWS",
            "region": "eu-west-2",
            "instanceType": "t3a.small",
            "pricing": "spot",
            "runningHours": 0.5,
        } in document["unpriced"]

    def test_no_cost_keys_without_cost(self, platform, capsys):
        out, _ = _show(capsys, json_output=True, json=True)
        document = loads(out)
        assert "currency" not in document and "unpriced" not in document
        assert "estimatedCost" not in document["groups"][0]

    def test_no_price_search_without_cost(self, platform, capsys):
        _, _, search = _show_priced(capsys)
        search.assert_not_called()


class TestTop:
    def test_top_keeps_the_largest_and_sums_the_rest(self, platform):
        groups = usage_report.grouped_usage(_report(_ctx()), ["instance-id"])
        kept, rest = usage.top_groups(groups, 2)
        assert [g.keys["instance-id"] for g in kept] == ["i-1", "i-2"]
        assert rest is not None
        assert rest.keys == {"instance-id": "(2 more)"}
        assert rest.instances == 2
        assert rest.total_seconds == 1800 + 900

    def test_the_remainder_leaves_the_other_keys_blank(self, platform):
        groups = usage_report.grouped_usage(_report(_ctx()), ["instance-id", "cr"])
        _, rest = usage.top_groups(groups, 1)
        assert rest is not None
        assert rest.keys == {"instance-id": "(3 more)", "cr": ""}

    def test_top_beyond_the_groups_cuts_nothing(self, platform, capsys):
        groups = usage_report.grouped_usage(_report(_ctx()), ["namespace"])
        assert usage.top_groups(groups, 5) == (groups, None)
        assert usage.top_groups(groups, None) == (groups, None)
        capsys.readouterr()  # the fetch's own lines
        out, _ = _show(capsys, usage_top=5, json_output=True, json=True)
        assert loads(out)["more"] is None

    def test_no_more_key_without_top(self, platform, capsys):
        out, _ = _show(capsys, json_output=True, json=True)
        assert "more" not in loads(out)

    def test_the_table_and_total_line(self, platform, capsys):
        whole, _ = _show(capsys, usage_by=("instance-id",))
        cut, _ = _show(capsys, usage_by=("instance-id",), usage_top=1)
        assert "(3 more)" in cut and "i-2" not in cut
        # The text from 'Total:' on: the timestamps before it may differ
        totals = [
            [
                line[line.index("Total:") :]
                for line in out.splitlines()
                if "Total:" in line
            ]
            for out in (whole, cut)
        ]
        assert totals[0] and totals[0] == totals[1]

    def test_json_more(self, platform, capsys):
        out, _ = _show(
            capsys, usage_by=("instance-id",), usage_top=2, json_output=True, json=True
        )
        document = loads(out)
        assert [g["instance-id"] for g in document["groups"]] == ["i-1", "i-2"]
        assert document["more"]["groups"] == 2
        assert document["more"]["instances"] == 2
        assert document["more"]["hours"]["total"] == 0.75

    def test_a_partial_remainder_cost_shows_plus(self, platform, capsys):
        rows = [_price("t2.small", "ON_DEMAND", 0.04)]
        out, _, _ = _show_priced(
            capsys, rows, usage_by=("instance-id",), usage_top=1, usage_cost=True
        )
        (line,) = [line for line in out.splitlines() if "(3 more)" in line]
        assert "0.01+" in line


def _parsed_usage(*argv: str):
    from yellowdog_cli.utils.args import CLIParser

    return CLIParser("yd-usage", list(argv))


class TestTheJsonTotals:
    def test_reused_is_false_then_true(self, platform, capsys):
        assert loads(_show(capsys, json_output=True, json=True)[0])["reused"] is False
        assert loads(_show(capsys, json_output=True, json=True)[0])["reused"] is True

    def test_total_sums_every_group(self, platform, capsys):
        whole = loads(
            _show(capsys, usage_by=("instance-id",), json_output=True, json=True)[0]
        )
        cut = loads(
            _show(
                capsys,
                usage_by=("instance-id",),
                usage_top=1,
                json_output=True,
                json=True,
            )[0]
        )
        assert cut["total"]["groups"] == len(cut["groups"]) + cut["more"]["groups"]
        assert cut["total"] == whole["total"]
        assert whole["total"]["groups"] == len(whole["groups"])
        assert whole["total"]["instances"] == sum(
            g["instances"] for g in whole["groups"]
        )
        assert whole["total"]["seconds"]["total"] == sum(
            g["seconds"]["total"] for g in whole["groups"]
        )
        assert "creator" not in whole["total"] and "instance-id" not in whole["total"]

    def test_no_cost_keys_in_the_total_without_cost(self, platform, capsys):
        total = loads(_show(capsys, json_output=True, json=True)[0])["total"]
        assert "estimatedCost" not in total

    def test_total_cost_matches_the_total_line(self, platform, capsys):
        text, _, _ = _show_priced(capsys, usage_cost=True)
        total = loads(
            _show_priced(capsys, usage_cost=True, json_output=True, json=True)[0]
        )["total"]
        assert f"est. ${total['estimatedCost']:,.2f} at list prices" in text
        assert total["unpricedRunningHours"] == 0.0

    def test_partial_total_cost(self, platform, capsys):
        rows = [_price("t2.small", "ON_DEMAND", 0.04)]
        text, _, _ = _show_priced(capsys, rows, usage_cost=True)
        total = loads(
            _show_priced(capsys, rows, usage_cost=True, json_output=True, json=True)[0]
        )["total"]
        assert f"est. ${total['estimatedCost']:,.2f}+ at list prices" in text
        assert total["unpricedRunningHours"] == 1.5

    def test_total_cost_is_null_when_nothing_is_priced(self, platform, capsys):
        total = loads(
            _show_priced(
                capsys, _refused(), usage_cost=True, json_output=True, json=True
            )[0]
        )["total"]
        assert total["estimatedCost"] is None


class TestSort:
    def _ids(self, groups) -> list[str]:
        return [group.keys["instance-id"] for group in groups]

    def _groups(self, by=("instance-id",)):
        return usage_report.grouped_usage(_report(_ctx()), list(by))

    def test_total_is_grouped_usages_order(self, platform):
        groups = self._groups()
        assert usage.sorted_groups(groups, ("total",), False) == groups

    def test_a_by_key_sorts_alphabetically(self, platform):
        groups = self._groups(("instance-type", "instance-id"))
        ordered = usage.sorted_groups(groups, ("instance-type",), False)
        assert [g.keys["instance-type"] for g in ordered] == [
            "g4dn.xlarge",
            "t2.small",
            "t3a.small",
            "t3a.small",
        ]
        # Ties keep grouped_usage()'s order, the most total time first
        assert self._ids(ordered)[2:] == ["i-2", "i-3"]

    def test_values_sort_the_most_first(self, platform):
        groups = self._groups()
        assert self._ids(usage.sorted_groups(groups, ("running",), False)) == [
            "i-2",
            "i-3",
            "i-4",
            "i-1",
        ]
        assert self._ids(usage.sorted_groups(groups, ("stopped",), False))[0] == "i-1"

    def test_reverse_inverts_both_directions(self, platform):
        groups = self._groups()
        assert self._ids(usage.sorted_groups(groups, ("total",), True)) == [
            "i-4",
            "i-3",
            "i-2",
            "i-1",
        ]
        assert self._ids(usage.sorted_groups(groups, ("instance-id",), True)) == [
            "i-4",
            "i-3",
            "i-2",
            "i-1",
        ]

    def test_several_keys_the_first_most_significant(self, platform):
        groups = self._groups(("pricing", "instance-id"))
        ordered = usage.sorted_groups(groups, ("pricing", "running"), False)
        assert [(g.keys["pricing"], g.keys["instance-id"]) for g in ordered] == [
            ("on-demand", "i-2"),
            ("on-demand", "i-4"),
            ("on-demand", "i-1"),
            ("spot", "i-3"),
        ]

    @pytest.mark.parametrize("reverse", [False, True])
    def test_a_cost_with_nothing_priced_goes_last(self, platform, reverse):
        groups = self._groups()
        for group in groups:
            if group.keys["instance-id"] == "i-2":
                group.unpriced_seconds = 3600
            else:
                group.cost = {"i-1": 0.0, "i-3": 2.0, "i-4": 1.0}[
                    group.keys["instance-id"]
                ]
                group.priced_seconds = 1
        ordered = self._ids(usage.sorted_groups(groups, ("cost",), reverse))
        assert ordered == (
            ["i-1", "i-4", "i-3", "i-2"] if reverse else ["i-3", "i-4", "i-1", "i-2"]
        )

    def test_the_registry_offers_every_value_key(self):
        from yellowdog_cli.utils.command_registry import USAGE_SORT_VALUE_KEYS

        assert tuple(usage._SORT_VALUES) == USAGE_SORT_VALUE_KEYS

    def test_the_command_sorts_and_top_takes_the_first(self, platform, capsys):
        out, _ = _show(
            capsys,
            usage_by=("instance-id",),
            usage_sort=("instance-id",),
            reverse=True,
            usage_top=2,
            json_output=True,
            json=True,
        )
        document = loads(out)
        assert [g["instance-id"] for g in document["groups"]] == ["i-4", "i-3"]
        assert document["more"]["groups"] == 2

    def test_the_parser_reads_sort_and_reverse(self):
        parsed = _parsed_usage(
            "--by", "provider,instance-id", "--sort", "provider", "--reverse"
        )
        assert parsed.usage_sort == ("provider",)
        assert parsed.reverse is True

    @pytest.mark.parametrize(
        "argv, message",
        [
            (
                ["--sort", "provider"],
                "--sort provider needs provider in --by (the groups are by: namespace)",
            ),
            (
                ["--by", "region", "--sort", "namespace"],
                "--sort namespace needs namespace in --by (the groups are by: region)",
            ),
            (["--sort", "cost"], "--sort cost needs --cost"),
            (["--sort", "hours"], "invalid sort key 'hours'"),
        ],
    )
    def test_a_sort_key_the_groups_lack_is_refused(self, argv, message, capsys):
        with pytest.raises(SystemExit) as raised:
            _parsed_usage(*argv)
        assert raised.value.code == 2
        assert message in capsys.readouterr().err

    def test_cost_with_cost_is_accepted(self):
        assert _parsed_usage("--cost", "--sort", "cost,namespace").usage_sort == (
            "cost",
            "namespace",
        )


_CSV_HOURS = [
    "pending_hours",
    "running_hours",
    "stopping_hours",
    "stopped_hours",
    "terminating_hours",
    "unknown_hours",
    "total_hours",
]


class TestCsv:
    def _rows(self, out: str) -> list[list[str]]:
        import csv

        return list(csv.reader(io.StringIO(out)))

    def test_csv_is_the_rows_alone(self, platform, capsys):
        capsys.readouterr()
        out, _ = _show(capsys, csv_output=True)
        rows = self._rows(out)
        assert rows[0] == ["namespace", "instances", *_CSV_HOURS]
        assert rows[1][0] == "team-render"  # most total time first
        assert rows[2] == [
            "team-train",
            "3",
            "0.1",
            "1.75",
            "0.0",
            "0.0",
            "0.0",
            "0.0",
            "1.85",
        ]
        assert len(rows) == 3  # no info lines on stdout

    def test_csv_with_cost_and_top(self, platform, capsys):
        rows = [_price("t2.small", "ON_DEMAND", 0.04)]
        out, _, _ = _show_priced(
            capsys,
            rows,
            usage_by=("instance-id",),
            usage_top=1,
            usage_cost=True,
            csv_output=True,
        )
        table = self._rows(out)
        assert table[0][-1] == "estimated_cost"
        assert table[1][0] == "i-1" and table[1][-1] == "0.0"
        assert table[2][0] == "(3 more)" and table[2][-1] == "0.01"
        assert len(table) == 3

    def test_csv_leaves_an_unpriced_cost_empty(self, platform, capsys):
        out, _, _ = _show_priced(
            capsys, [], usage_by=("pricing",), usage_cost=True, csv_output=True
        )
        assert [row[-1] for row in self._rows(out)[1:]] == ["", ""]

    def test_csv_quotes_a_comma(self, platform, capsys):
        platform.content = _zip(
            requirements=[
                REQUIREMENTS[0],
                f'team-render,"render, nightly",nightly,2026-11-01T00:00:00Z,,{APP_RENDER},{CR_RENDER}',
                REQUIREMENTS[2],
            ]
        )
        out, _ = _show(capsys, usage_by=("cr",), csv_output=True)
        assert ["render, nightly"] == [
            row[0] for row in self._rows(out) if row[0].startswith("render")
        ]

    def test_csv_refused_with_json(self, capsys):
        from yellowdog_cli.utils.args import CLIParser

        with pytest.raises(SystemExit) as raised:
            CLIParser("yd-usage", ["--csv", "--json"])
        assert raised.value.code == 2
        assert "--csv cannot be combined with --json" in capsys.readouterr().err

    def test_warnings_go_to_stderr_under_csv(self, platform, capsys):
        out, err, _ = _show_priced(capsys, _refused(), usage_cost=True, csv_output=True)
        assert "This Application may not read cloud prices" in err
        assert "This Application may not read cloud prices" not in out
        assert self._rows(out)[0][0] == "namespace"

    def test_csv_is_not_an_mcp_argument(self):
        from yellowdog_cli.mcp.tools import tool_named

        tool = tool_named("yd_usage")
        assert tool is not None
        properties = tool.input_schema["properties"]
        assert "csv_output" not in properties
        assert {"usage_cost", "usage_top"} <= set(properties)


class TestReviewFixes:
    def test_another_regions_rows_are_ignored(self, platform):
        # The search matches the region as a substring: eu-west-2 also finds
        # its Wavelength zones' rows, which must not price eu-west-2's
        ctx = _ctx()
        _priced(
            ctx,
            [
                _price("t2.small", "ON_DEMAND", 0.04),
                _price("t2.small", "ON_DEMAND", 0.09, region="eu-west-2-wl1-lon1"),
                _price("t3a.small", "SPOT", 0.01),
                _price("t3a.small", "SPOT", 0.05, region="eu-west-2-wl1-lon1"),
                _price("t3a.small", "ON_DEMAND", 0.5, licence="WINDOWS"),
            ],
        )
        prices = usage_cost.list_prices(ctx, {("AWS", "eu-west-2")}).prices
        assert prices == {
            ("AWS", "eu-west-2", "t2.small", "on-demand"): 0.04,
            ("AWS", "eu-west-2", "t3a.small", "spot"): 0.01,
        }

    def test_places_are_only_those_with_running_time_and_a_region(self, platform):
        platform.content = _zip(
            instances=[
                INSTANCES_HEADER,
                _instance(CR_TRAIN, "t3a.small", running=0, pending=60),
                _instance(CR_TRAIN, "t3a.small", running=60).replace(
                    "AWS,eu-west-2,", "AWS,,"
                ),
            ]
        )
        assert usage_report.counted_places(_report(_ctx())) == set()

    def test_csv_warns_of_unpriced_on_stderr(self, platform, capsys):
        rows = [_price("t2.small", "ON_DEMAND", 0.04)]
        out, err, _ = _show_priced(capsys, rows, usage_cost=True, csv_output=True)
        assert "No list price for AWS eu-west-2 t3a.small (on-demand)" in err
        assert "No list price" not in out

    def test_csv_gives_the_creator_id_beside_the_creator(
        self, platform, monkeypatch, capsys
    ):
        _listings(monkeypatch)
        out, _ = _show(capsys, usage_by=("creator",), csv_output=True)
        import csv

        rows = list(csv.reader(io.StringIO(out)))
        assert rows[0][:2] == ["creator", "creatorId"]
        assert {(row[0], row[1]) for row in rows[1:]} == {
            ("render-farm (Application)", APP_RENDER),
            ("alice (User)", USER_ALICE),
        }


class TestPricesRefused:
    def test_a_regional_failure_is_not_a_refusal(self, platform, capsys):
        failed = HTTPError(response=SimpleNamespace(status_code=500))
        out, _, _ = _show_priced(
            capsys, failed, usage_cost=True, json_output=True, json=True
        )
        document = loads(out)
        assert document["pricesRefused"] is False
        assert document["unreadablePrices"] == [
            {"provider": "AWS", "region": "eu-west-2"}
        ]


class TestPriceFetchIsSaid:
    def test_the_price_searches_are_announced(self, platform, capsys):
        out, _, _ = _show_priced(capsys, usage_cost=True)
        assert "Fetching list prices for 1 region (AWS eu-west-2)" in out

    def test_not_announced_without_cost(self, platform, capsys):
        out, _, _ = _show_priced(capsys)
        assert "Fetching list prices" not in out

    def test_not_announced_under_json(self, platform, capsys):
        out, err, _ = _show_priced(capsys, usage_cost=True, json_output=True, json=True)
        assert "Fetching list prices" not in out + err


class TestKeptPrices:
    def test_prices_are_kept_and_reused(self, platform, capsys):
        _, _, first = _show_priced(capsys, usage_cost=True)
        assert first.call_count == 1
        out, _, second = _show_priced(capsys, usage_cost=True)
        second.assert_not_called()
        assert "Reusing list prices for 1 region (AWS eu-west-2)" in out
        assert "Fetching list prices" not in out
        assert "est. $0.04 at list prices" in out

    def test_refresh_fetches_prices_again(self, platform, capsys):
        _show_priced(capsys, usage_cost=True)
        out, _, again = _show_priced(capsys, usage_cost=True, usage_refresh=True)
        assert again.call_count == 1
        assert "Fetching list prices for 1 region" in out

    def test_kept_prices_last_24_hours(self, platform):
        ctx = _ctx()
        _priced(ctx, PRICES)
        place = ("AWS", "eu-west-2")
        usage_cost.list_prices(ctx, {place})
        now = time.time()
        kept, missing = usage_cost.kept_prices(ctx, {place}, now=now + 24 * 3600 - 60)
        assert (
            missing == set()
            and kept[("AWS", "eu-west-2", "t2.small", "on-demand")] == 0.04
        )
        kept, missing = usage_cost.kept_prices(ctx, {place}, now=now + 24 * 3600 + 60)
        assert missing == {place} and kept == {}

    def test_a_failed_search_is_not_kept(self, platform, capsys):
        failed = HTTPError(response=SimpleNamespace(status_code=500))
        _show_priced(capsys, failed, usage_cost=True)
        _, _, again = _show_priced(capsys, usage_cost=True)
        assert again.call_count == 1

    def test_a_place_with_no_prices_is_kept(self, platform, capsys):
        # A region the Platform has no prices for is asked about once a day
        _show_priced(capsys, [], usage_cost=True)
        _, _, again = _show_priced(capsys, [], usage_cost=True)
        again.assert_not_called()

    def test_kept_per_application(self, platform):
        ctx = _ctx()
        _priced(ctx, PRICES)
        usage_cost.list_prices(ctx, {("AWS", "eu-west-2")})
        other = _ctx()
        other.config.key = "another-key"
        _, missing = usage_cost.kept_prices(other, {("AWS", "eu-west-2")})
        assert missing == {("AWS", "eu-west-2")}


class TestUnpricedWarnings:
    def _costing(self, count: int) -> usage_cost.Costing:
        costing = usage_cost.Costing({})
        for n in range(count):
            # Type n ran n+1 minutes
            costing.unpriced[("AWS", "eu-west-2", f"type-{n}", "on-demand")] = 60.0 * (
                n + 1
            )
        return costing

    def test_all_are_named_up_to_the_limit(self):
        lines = usage._unpriced_lines(self._costing(5))
        assert len(lines) == 5
        assert lines[0].startswith("No list price for AWS eu-west-2 type-4 (on-demand)")

    def test_beyond_the_limit_the_rest_are_one_line(self):
        lines = usage._unpriced_lines(self._costing(8))
        assert len(lines) == 6
        assert "type-7" in lines[0] and "type-3" in lines[4]
        # type-0 to type-2: 1 + 2 + 3 minutes
        assert lines[5] == (
            "No list price for 3 more instance types: 0:06 running not costed;"
            " '--json' lists them all"
        )


def _reports(capsys, **args) -> tuple[str, str]:
    capsys.readouterr()  # what fetching the reports printed
    ctx = _ctx(usage_reports=True, **args)
    with output_settings.configured(ctx.args):
        usage.show_reports(ctx)
    captured = capsys.readouterr()
    return captured.out, captured.err


def _kept_two(platform) -> None:
    """
    Two reports kept for the account: every namespace's, then team-a's.
    """
    _report(_ctx())
    time.sleep(0.02)
    _report(_ctx(namespace="team-a"))
    assert len(platform.calls) == 2


class TestTheReportsKept:
    def test_none_kept_is_said(self, platform, capsys):
        out, _ = _reports(capsys)
        assert "No usage reports are kept for this account and Application" in out
        assert loads(_reports(capsys, json_output=True, json=True)[0]) == []

    def test_the_last_fetched_first_each_with_its_window_and_namespace(
        self, platform, capsys
    ):
        _kept_two(platform)
        listed = loads(_reports(capsys, json_output=True, json=True)[0])
        assert [item["namespace"] for item in listed] == ["team-a", None]
        first = listed[0]
        assert (first["from"], first["until"]) == (
            "2026-11-01T00:00:00Z",
            "2026-11-08T00:00:00Z",
        )
        assert first["command"] == (
            "yd usage --from 2026-11-01T00:00:00Z --until 2026-11-08T00:00:00Z"
            " -n team-a"
        )
        assert listed[1]["command"].endswith("--until 2026-11-08T00:00:00Z")
        assert set(first) >= {"fetched", "lastUsed", "bytes", "reportFile"}

    def test_its_command_uses_it_again(self, platform, capsys):
        _kept_two(platform)
        listed = loads(_reports(capsys, json_output=True, json=True)[0])
        for item in listed:
            words = item["command"].split()
            report = _report(
                _ctx(
                    usage_from=words[words.index("--from") + 1],
                    usage_until=words[words.index("--until") + 1],
                    namespace=item["namespace"],
                )
            )
            assert report.from_cache
        assert len(platform.calls) == 2

    def test_listing_marks_none_used(self, platform, capsys):
        _kept_two(platform)
        directories = [p for p in platform_root(platform).iterdir() if p.is_dir()]
        before = {p: p.stat().st_mtime for p in directories}
        time.sleep(0.02)
        _reports(capsys, json_output=True, json=True)
        assert {p: p.stat().st_mtime for p in directories} == before

    def test_another_accounts_reports_are_not_listed(self, platform, capsys):
        _kept_two(platform)
        capsys.readouterr()
        ctx = _ctx(usage_reports=True, json_output=True, json=True)
        ctx.config.key = "another-key"
        with output_settings.configured(ctx.args):
            usage.show_reports(ctx)
        assert loads(capsys.readouterr().out) == []

    def test_a_report_kept_without_its_account_is_not_listed(self, platform, capsys):
        _report(_ctx())
        [directory] = [p for p in platform_root(platform).iterdir() if p.is_dir()]
        fetched = directory / usage_report.FETCHED_JSON
        record = loads(fetched.read_text(encoding="utf-8"))
        del record["account"]
        fetched.write_text(dumps(record), encoding="utf-8")
        assert loads(_reports(capsys, json_output=True, json=True)[0]) == []

    def test_the_table_and_the_commands(self, platform, capsys):
        _kept_two(platform)
        out, _ = _reports(capsys)
        assert "2 usage reports kept for this account and Application" in out
        assert "Last Used" in out and "(all)" in out and "team-a" in out
        assert "1: yd usage --from 2026-11-01T00:00:00Z" in out
        assert "-n team-a" in out


def platform_root(platform) -> Path:
    """
    The cache directory the reports are kept in, under the test's own.
    """
    root = completion_cache.cache_directory(usage_report.USAGE_CACHE_DIRECTORY_NAME)
    assert root is not None
    return root


@pytest.mark.parametrize(
    "extra, flag",
    [
        (["--cost"], "--cost"),
        (["--from", "3 days ago"], "--from"),
        (["--by", "region"], "--by"),
        (["-n", "team-a"], "--namespace"),
        (["--csv"], "--csv"),
        (["--refresh"], "--refresh"),
    ],
)
def test_reports_takes_no_report_option(extra, flag, capsys):
    with pytest.raises(SystemExit):
        _parsed_usage("--reports", *extra)
    assert f"--reports lists the kept reports: it takes no {flag}" in (
        capsys.readouterr().err
    )


def test_reports_takes_the_output_options():
    assert _parsed_usage("--reports", "--json").usage_reports
