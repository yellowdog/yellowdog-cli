"""
Unit tests for yellowdog_cli.utils.dataclient.operations
"""

import json
import logging
import re
import shutil
import subprocess
import sys
import threading
import time
import warnings
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import yellowdog_cli.download as yd_download
import yellowdog_cli.utils.dataclient.operations as dcu_module
import yellowdog_cli.utils.dataclient.rclone as rclone_utils_module
import yellowdog_cli.utils.dataclient.wrapper as dcw_module
import yellowdog_cli.utils.interactive as interactive_module
import yellowdog_cli.utils.printing as printing_module
import yellowdog_cli.utils.results as results_module
from yellowdog_cli.utils import output_settings
from yellowdog_cli.utils.config_types import ConfigDataClient
from yellowdog_cli.utils.dataclient.operations import (
    resolve_remote_path,
    upload_directory,
    upload_files,
)
from yellowdog_cli.utils.dataclient.rclone_version import find_rclone
from yellowdog_cli.utils.results import reset_results
from yellowdog_cli.utils.variable_substitution import VARIABLE_SUBSTITUTIONS


class TestResolveRemotePath:
    def _config(
        self,
        remote: str = "myremote",
        bucket: str | None = None,
        prefix: str | None = None,
    ) -> ConfigDataClient:
        return ConfigDataClient(remote=remote, bucket=bucket, prefix=prefix)

    def test_no_remote_raises(self):
        config = ConfigDataClient()
        with pytest.raises(Exception, match="No rclone remote"):
            resolve_remote_path(config)

    def test_remote_only_no_bucket_no_prefix(self):
        config = self._config(remote="r")
        assert resolve_remote_path(config) == "r:"

    def test_bucket_only(self):
        config = self._config(bucket="mybucket")
        assert resolve_remote_path(config) == "myremote:mybucket"

    def test_prefix_only(self):
        config = self._config(prefix="mypfx")
        assert resolve_remote_path(config) == "myremote:mypfx"

    def test_bucket_and_prefix(self):
        config = self._config(bucket="mybucket", prefix="mypfx")
        assert resolve_remote_path(config) == "myremote:mybucket/mypfx"

    def test_relative_path_appended(self):
        config = self._config(bucket="b", prefix="p")
        assert (
            resolve_remote_path(config, relative_path="sub/dir")
            == "myremote:b/p/sub/dir"
        )

    def test_relative_path_without_bucket_prefix(self):
        config = self._config()
        assert resolve_remote_path(config, relative_path="data") == "myremote:data"

    def test_filename_appended(self):
        config = self._config(bucket="b")
        assert (
            resolve_remote_path(config, filename="report.csv")
            == "myremote:b/report.csv"
        )

    def test_filename_with_prefix(self):
        config = self._config(bucket="b", prefix="pfx")
        assert (
            resolve_remote_path(config, filename="out.txt") == "myremote:b/pfx/out.txt"
        )

    def test_relative_path_takes_precedence_over_filename(self):
        config = self._config(bucket="b")
        result = resolve_remote_path(config, relative_path="rel", filename="file.txt")
        assert result == "myremote:b/rel"

    def test_absolute_rclone_path_returned_verbatim(self):
        config = self._config(bucket="b", prefix="p")
        absolute = "myremote:some/absolute/path"
        assert resolve_remote_path(config, relative_path=absolute) == absolute

    def test_absolute_path_different_remote_not_treated_as_absolute(self):
        # Only paths starting with the *configured* remote name are treated as absolute
        config = self._config(remote="r1", bucket="b")
        result = resolve_remote_path(config, relative_path="r2:other/path")
        assert result == "r1:b/r2:other/path"

    def test_an_absolute_bucket_keeps_its_leading_slash(self):
        # On a local or SFTP remote, '/data' is an absolute path; stripped, it
        # was taken relative to the current directory. Inner slashes are
        # tidied, and a trailing '/' is preserved because it denotes
        # directory-destination intent (yd-copy / yd-upload)
        config = self._config(bucket="/b/", prefix="/p/")
        assert resolve_remote_path(config, relative_path="/sub/") == (
            "myremote:/b/p/sub/"
        )

    def test_an_absolute_prefix_with_no_bucket_keeps_its_leading_slash(self):
        config = self._config(bucket=None, prefix="/data/results")
        assert resolve_remote_path(config) == "myremote:/data/results"

    def test_an_object_store_bucket_is_unchanged(self):
        config = self._config(bucket="b/", prefix="/p/")
        assert resolve_remote_path(config, relative_path="x") == "myremote:b/p/x"

    def test_a_root_bucket_is_the_root(self):
        assert resolve_remote_path(self._config(bucket="/", prefix=None)) == (
            "myremote:/"
        )

    def test_the_bucket_path_keeps_the_same_rule(self):
        from yellowdog_cli.utils.dataclient.operations import resolve_bucket_path

        assert resolve_bucket_path(self._config(bucket="/data/", prefix="p")) == (
            "myremote:/data"
        )
        assert resolve_bucket_path(self._config(bucket="b", prefix="p")) == (
            "myremote:b"
        )

    def test_no_trailing_slash_unchanged(self):
        config = self._config(bucket="b")
        assert resolve_remote_path(config, relative_path="sub") == "myremote:b/sub"

    def test_slash_only_relative_path_ignored(self):
        config = self._config(bucket="b", prefix="p")
        assert resolve_remote_path(config, relative_path="/") == "myremote:b/p"

    def test_inline_remote_name_extracted(self):
        # Inline config string: "NAME,type=s3,..." → remote_name = "NAME"
        config = self._config(remote="s3remote,type=s3,provider=AWS", bucket="bucket")
        assert resolve_remote_path(config) == "s3remote:bucket"

    def test_rclone_prefix_stripped_from_plain_remote(self):
        config = self._config(remote="rclone:myremote", bucket="b")
        assert resolve_remote_path(config) == "myremote:b"

    def test_rclone_prefix_stripped_from_inline_remote(self):
        config = self._config(remote="rclone:s3r,type=s3,provider=AWS", bucket="b")
        assert resolve_remote_path(config) == "s3r:b"


class TestResolveRemotePathVariableSubstitution:
    """
    Variable substitutions ({{var}}) in relative_path and filename arguments.
    """

    def setup_method(self):
        VARIABLE_SUBSTITUTIONS["testns"] = "mynamespace"
        VARIABLE_SUBSTITUTIONS["testtag"] = "mytag"

    def teardown_method(self):
        VARIABLE_SUBSTITUTIONS.pop("testns", None)
        VARIABLE_SUBSTITUTIONS.pop("testtag", None)

    def _config(self, bucket: str = "b", prefix: str = "p") -> ConfigDataClient:
        return ConfigDataClient(remote="r", bucket=bucket, prefix=prefix)

    @pytest.mark.parametrize(
        "kwargs,expected",
        [
            ({"relative_path": "{{testns}}/data.csv"}, "r:b/p/mynamespace/data.csv"),
            ({"filename": "{{testtag}}_output.txt"}, "r:b/p/mytag_output.txt"),
            (
                {"relative_path": "{{testns}}/{{testtag}}/results"},
                "r:b/p/mynamespace/mytag/results",
            ),
            ({"relative_path": "{{testtag}}_*"}, "r:b/p/mytag_*"),
            # Unresolved variables are passed through unchanged
            ({"relative_path": "{{unknown}}/data"}, "r:b/p/{{unknown}}/data"),
        ],
    )
    def test_variable_substitution(self, kwargs, expected):
        assert resolve_remote_path(self._config(), **kwargs) == expected

    def test_builtin_variable_username(self):
        config = self._config(prefix="")
        result = resolve_remote_path(config, relative_path="{{username}}/data")
        # username is always set; just check it resolved to something
        assert "{{username}}" not in result
        assert result.startswith("r:b/")


class TestSplitGlobRemotePath:
    def test_glob_in_final_component(self):
        from yellowdog_cli.utils.dataclient.operations import split_glob_remote_path

        assert split_glob_remote_path("S3:bucket/prefix/xxx*") == (
            "S3:bucket/prefix/",
            "xxx*",
        )

    def test_glob_at_top_level(self):
        from yellowdog_cli.utils.dataclient.operations import split_glob_remote_path

        assert split_glob_remote_path("S3:xxx*") == ("S3:", "xxx*")

    @pytest.mark.parametrize(
        "path",
        ["S3:bucket/dir*/file.txt", "S3:buck?t/prefix/file*", "S3:a[1]/b/c*"],
    )
    def test_mid_path_glob_rejected(self, path):
        from yellowdog_cli.utils.dataclient.operations import split_glob_remote_path

        with pytest.raises(ValueError, match="final path component"):
            split_glob_remote_path(path)


class TestUploadDirectoryWalksOnlyForJson:
    """
    A directory upload lists its local files only to record them, which
    nothing prints without '--json': a large tree is not walked for nothing.
    """

    def _upload(self, monkeypatch, tmp_path, json_output: bool) -> list:
        (tmp_path / "d").mkdir()
        (tmp_path / "d" / "x.txt").write_text("x")
        output_settings.configure_output(MagicMock(json_output=json_output))
        stats: list = []
        real_stat = Path.stat

        def spy(self, *args, **kwargs):
            stats.append(self)
            return real_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", spy)
        walks: list = []
        real_walk = dcu_module._local_upload_files
        monkeypatch.setattr(
            dcu_module,
            "_local_upload_files",
            lambda *a: walks.append(a) or real_walk(*a),
        )
        upload_directory(
            ConfigDataClient(remote="r"), tmp_path / "d", "r:b/d", dry_run=True
        )
        return walks + stats

    def test_no_walk_and_no_stat_without_json(self, monkeypatch, tmp_path):
        assert self._upload(monkeypatch, tmp_path, json_output=False) == []

    def test_walked_with_json(self, monkeypatch, tmp_path):
        assert self._upload(monkeypatch, tmp_path, json_output=True) != []


# ---------------------------------------------------------------------------
# yd-download through a real rclone, against a local backend
# ---------------------------------------------------------------------------

needs_rclone = pytest.mark.skipif(
    find_rclone() is None, reason="needs an rclone binary"
)

_DOWNLOAD_ARGS = {
    "json_output": False,
    "dry_run": False,
    "quiet": True,
    "count_only": False,
    "interactive": False,
    "yes": True,
    "no_format": True,
    "print_pid": False,
    "debug": False,
    "upgrade_rclone": False,
    "which_rclone": False,
    "sync": False,
    "flatten": False,
    "destination": None,
    "into": None,
    "remote_paths": [],
}


@pytest.fixture()
def remote(tmp_path, monkeypatch):
    """
    A local rclone 'remote' under tmp_path: 'remote/a.txt', and
    'remote/mydir/b.txt' and 'remote/mydir/sub/c.txt' beneath a directory,
    with the working directory at tmp_path so that the remote's relative
    paths resolve there.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "remote" / "mydir" / "sub").mkdir(parents=True)
    (tmp_path / "remote" / "a.txt").write_text("hello")
    (tmp_path / "remote" / "mydir" / "b.txt").write_text("abc")
    (tmp_path / "remote" / "mydir" / "sub" / "c.txt").write_text("xyz")
    return tmp_path


@pytest.fixture()
def run_download(monkeypatch, capsys):
    """
    Return run_download(**args): run yd-download's main() through
    dataclient_wrapper against the local 'remote', and return
    (stdout, stderr, exit code).
    """
    reset_results()
    config = ConfigDataClient(remote="loc,type=local")

    def _run(**values):
        args = MagicMock(**{**_DOWNLOAD_ARGS, **values})
        for target in (
            yd_download,
            results_module,
            printing_module,
            interactive_module,
            dcw_module,
            rclone_utils_module,
        ):
            # A command taking a context has none of its own
            if hasattr(target, "ARGS_PARSER"):
                monkeypatch.setattr(target, "ARGS_PARSER", args)
        output_settings.configure_output(args)
        monkeypatch.setattr(yd_download, "CONFIG_DATA_CLIENT", config)
        with pytest.raises(SystemExit) as exit_info:
            yd_download.main()
        out, err = capsys.readouterr()
        return out, err, exit_info.value.code

    yield _run
    reset_results()


def _files_under(root: Path) -> set[str]:
    """
    Every file under 'root', as a POSIX path relative to it.
    """
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


@needs_rclone
class TestDownloadDestinations:
    """
    Where each of yd-download's three destination modes puts a file and a
    directory: '--into' and the bare form give an item its own path, which a
    single file must occupy itself rather than become a directory holding it.
    """

    def test_a_file_into_a_directory_keeps_its_own_path(self, remote, run_download):
        _, _, code = run_download(remote_paths=["loc:remote/a.txt"], into="dli")
        assert code == 0
        assert (remote / "dli" / "a.txt").is_file()
        assert (remote / "dli" / "a.txt").read_text() == "hello"

    def test_a_file_with_no_destination_lands_at_its_own_name(
        self, remote, run_download
    ):
        _, _, code = run_download(remote_paths=["loc:remote/a.txt"])
        assert code == 0
        assert (remote / "a.txt").is_file()

    def test_a_file_to_a_destination_goes_inside_it(self, remote, run_download):
        _, _, code = run_download(remote_paths=["loc:remote/a.txt"], destination="out")
        assert code == 0
        assert _files_under(remote / "out") == {"a.txt"}

    def test_a_directory_into_a_directory_keeps_its_name(self, remote, run_download):
        _, _, code = run_download(remote_paths=["loc:remote/mydir"], into="dli")
        assert code == 0
        assert _files_under(remote / "dli") == {"mydir/b.txt", "mydir/sub/c.txt"}

    def test_a_directory_with_no_destination_mirrors_its_name(
        self, remote, run_download
    ):
        _, _, code = run_download(remote_paths=["loc:remote/mydir"])
        assert code == 0
        assert _files_under(remote / "mydir") == {"b.txt", "sub/c.txt"}

    def test_a_directory_to_a_destination_puts_its_contents_in_it(
        self, remote, run_download
    ):
        _, _, code = run_download(remote_paths=["loc:remote/mydir"], destination="out")
        assert code == 0
        assert _files_under(remote / "out") == {"b.txt", "sub/c.txt"}


@needs_rclone
class TestDownloadFlatten:
    """
    '--flatten' puts every file of a directory tree directly in the
    destination, whether the directory is named or matched by a wildcard.
    """

    def test_a_literal_directory_is_flattened(self, remote, run_download):
        _, _, code = run_download(
            remote_paths=["loc:remote/mydir"], destination="flat", flatten=True
        )
        assert code == 0
        assert _files_under(remote / "flat") == {"b.txt", "c.txt"}

    def test_a_directory_matched_by_a_wildcard_is_flattened(self, remote, run_download):
        _, _, code = run_download(
            remote_paths=["loc:remote/my*"], destination="flat", flatten=True
        )
        assert code == 0
        assert _files_under(remote / "flat") == {"b.txt", "c.txt"}

    def test_a_wildcard_matching_files_and_directories(self, remote, run_download):
        _, _, code = run_download(
            remote_paths=["loc:remote/*"], destination="flat", flatten=True
        )
        assert code == 0
        assert _files_under(remote / "flat") == {"a.txt", "b.txt", "c.txt"}

    def test_a_name_collision_is_warned_of_and_the_later_file_wins(
        self, remote, run_download
    ):
        (remote / "remote" / "mydir" / "sub" / "b.txt").write_text("dup")
        out, err, code = run_download(
            remote_paths=["loc:remote/mydir"],
            destination="flat",
            flatten=True,
            quiet=False,
        )
        assert code == 0
        # A long warning may be wrapped, though never within a path
        text = " ".join((out + err).split())
        warnings = re.findall(
            r"'([^']+)' will overwrite '([^']+)' locally"
            r" \(same filename, flattened download\)",
            text,
        )
        assert len(warnings) == 1
        later, first = warnings[0]
        assert {later, first} == {
            "loc:remote/mydir/b.txt",
            "loc:remote/mydir/sub/b.txt",
        }
        expected = "dup" if later.endswith("sub/b.txt") else "abc"
        assert (remote / "flat" / "b.txt").read_text() == expected

    @pytest.mark.parametrize("dry_run", [False, True])
    def test_a_collision_between_arguments_is_warned_of(
        self, remote, run_download, dry_run
    ):
        # Each argument was checked alone, so one directory's file landing
        # on another's in the shared destination went unwarned
        (remote / "remote" / "other").mkdir()
        (remote / "remote" / "other" / "b.txt").write_text("other")
        out, err, code = run_download(
            remote_paths=["loc:remote/mydir", "loc:remote/oth*"],
            destination="flat",
            flatten=True,
            dry_run=dry_run,
            quiet=False,
        )
        assert code == 0
        text = " ".join((out + err).split())
        assert (
            "'loc:remote/other/b.txt' will overwrite 'loc:remote/mydir/b.txt'"
            " locally (same filename, flattened download)"
        ) in text
        if not dry_run:
            assert (remote / "flat" / "b.txt").read_text() == "other"

    def test_a_single_file_is_unaffected(self, remote, run_download):
        _, _, code = run_download(
            remote_paths=["loc:remote/a.txt"], destination="flat", flatten=True
        )
        assert code == 0
        assert _files_under(remote / "flat") == {"a.txt"}


@needs_rclone
class TestWildcardDownloadListing:
    """
    Under '--json' a wildcard download records every file of every match,
    which costs one recursive listing per matched directory: those run
    concurrently, and a matched file, whose entry is in hand, costs none.
    """

    DIRECTORIES = ("d1", "d2", "d3", "mydir")

    @pytest.fixture()
    def several(self, remote):
        for name in ("d1", "d2", "d3"):
            (remote / "remote" / name).mkdir()
            (remote / "remote" / name / f"{name}.txt").write_text(name)
        return remote

    def _listings(self, monkeypatch, before=None) -> list[str]:
        """
        Count the '_lsjson' calls, running 'before(path)' ahead of each.
        """
        calls: list[str] = []
        real = dcu_module._lsjson

        def counted(rclone, remote_path, *args, **kwargs):
            calls.append(remote_path)
            if before is not None:
                before(remote_path)
            return real(rclone, remote_path, *args, **kwargs)

        monkeypatch.setattr(dcu_module, "_lsjson", counted)
        return calls

    @pytest.mark.parametrize("dry_run", [False, True])
    def test_every_file_of_every_match_in_matched_order(
        self, several, run_download, monkeypatch, dry_run
    ):
        # The first directory's listing is made the slowest, so that finishing
        # order is not the matched order
        delays = {"loc:remote/d1": 0.3, "loc:remote/d2": 0.2, "loc:remote/d3": 0.1}
        calls = self._listings(
            monkeypatch, before=lambda path: time.sleep(delays.get(path, 0))
        )
        out, _, code = run_download(
            remote_paths=["loc:remote/*"],
            into="got",
            json_output=True,
            dry_run=dry_run,
        )
        assert code == 0
        records = json.loads(out)
        # Grouped by match in matched order; within a directory, as listed
        assert [r["match"] for r in records] == [
            "loc:remote/a.txt",
            "loc:remote/d1",
            "loc:remote/d2",
            "loc:remote/d3",
            "loc:remote/mydir",
            "loc:remote/mydir",
        ]
        assert {r["source"] for r in records[4:]} == {
            "loc:remote/mydir/b.txt",
            "loc:remote/mydir/sub/c.txt",
        }
        # One listing per matched directory, none for the matched file
        assert sorted(calls) == [f"loc:remote/{d}" for d in self.DIRECTORIES]

    def test_the_listings_run_concurrently(self, several, run_download, monkeypatch):
        # Every listing waits for all the others to start, which a serial
        # enumeration cannot satisfy
        barrier = threading.Barrier(len(self.DIRECTORIES), timeout=10)
        self._listings(monkeypatch, before=lambda path: barrier.wait())
        out, _, code = run_download(
            remote_paths=["loc:remote/*"], into="got", json_output=True, dry_run=True
        )
        assert code == 0
        assert len(json.loads(out)) == 6

    def test_a_failed_listing_in_a_worker_warns_of_nothing(
        self, several, run_download, monkeypatch
    ):
        # A matched directory gone by the time it is listed: rclone_api warns
        # with the whole command line on a failed run, which must stay silent
        # from a worker thread as from the main one
        def remove(path):
            if path == "loc:remote/d2":
                shutil.rmtree(several / "remote" / "d2")

        self._listings(monkeypatch, before=remove)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _, err, code = run_download(
                remote_paths=["loc:remote/*"],
                into="got",
                json_output=True,
                dry_run=True,
            )
        assert code != 0
        assert "Cannot list 'loc:remote/d2'" in err
        assert [w for w in caught if issubclass(w.category, UserWarning)] == []

    def test_the_warning_filters_are_left_as_found(self, several, run_download):
        # The listing pool holds one warning filter for its lifetime; a
        # filter left in place afterwards would silence every later warning
        before = list(warnings.filters)
        _, _, code = run_download(
            remote_paths=["loc:remote/*"], into="got", json_output=True, dry_run=True
        )
        assert code == 0
        assert list(warnings.filters) == before


@needs_rclone
class TestFailedTransfer:
    """
    A transfer rclone refuses is reported as the command's own 'failed'
    record and error, not as rclone_api's UserWarning (which carries the
    whole command line, an inline remote's parameters included) and a
    CalledProcessError that skips the record.
    """

    @staticmethod
    def _quiet_run(run, **values):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            out, err, code = run(**values)
        user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
        return out, err, code, user_warnings

    def test_a_file_blocked_by_a_directory_is_recorded_failed(
        self, remote, run_download
    ):
        (remote / "dli" / "a.txt").mkdir(parents=True)
        out, err, code, user_warnings = self._quiet_run(
            run_download,
            remote_paths=["loc:remote/a.txt"],
            into="dli",
            json_output=True,
        )
        assert code != 0
        assert user_warnings == []
        assert "Download of " in err and " failed: " in err
        records = json.loads(out)
        assert [(r["source"], r["action"]) for r in records] == [
            ("loc:remote/a.txt", "failed")
        ]
        assert "directory" in records[0]["error"]

    def test_a_directory_blocked_by_a_file_is_recorded_failed(
        self, remote, run_download
    ):
        (remote / "out").write_text("in the way")
        out, err, code, user_warnings = self._quiet_run(
            run_download,
            remote_paths=["loc:remote/mydir"],
            destination="out",
            json_output=True,
        )
        assert code != 0
        assert user_warnings == []
        assert "Download of " in err and " failed: " in err
        assert {(r["source"], r["action"]) for r in json.loads(out)} == {
            ("loc:remote/mydir/b.txt", "failed"),
            ("loc:remote/mydir/sub/c.txt", "failed"),
        }

    def test_without_json_the_failure_is_still_quiet(self, remote, run_download):
        (remote / "dli" / "a.txt").mkdir(parents=True)
        _, err, code, user_warnings = self._quiet_run(
            run_download, remote_paths=["loc:remote/a.txt"], into="dli"
        )
        assert code != 0
        assert user_warnings == []
        assert "Download of " in err and " failed: " in err


@needs_rclone
def test_an_upload_to_an_absolute_local_bucket_lands_there(tmp_path, monkeypatch):
    # From a working directory elsewhere: with the leading '/' stripped, the
    # bucket was taken relative to it
    from yellowdog_cli.utils.dataclient.operations import upload_file

    bucket = tmp_path / "bucket"
    bucket.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    source = tmp_path / "a.txt"
    source.write_text("a", encoding="utf-8")
    monkeypatch.chdir(elsewhere)
    output_settings.configure_output(MagicMock(json_output=False))
    config = ConfigDataClient(remote="loc,type=local", bucket=str(bucket), prefix="p")

    assert upload_file(config, source, resolve_remote_path(config, filename="a.txt"))
    assert (bucket / "p" / "a.txt").read_text(encoding="utf-8") == "a"
    # Nothing written relative to the working directory instead
    assert not any(elsewhere.iterdir())


# What a bucket-based remote answers 'lsjson --stat' with for a path that is
# not an object
_UNNAMED_DIRECTORY = {"Path": "", "Name": "", "Size": -1, "IsDir": True}


class TestRemoteStatOnBucketStorage:
    """
    rclone answers 'lsjson --stat' of a directory with an unnamed entry. A
    bucket-based remote (S3, Google Cloud Storage, Azure Blob), which cannot
    hold an empty directory, answers any path that is not an object with
    the same entry, exit 0: a missing path, an empty prefix and a prefix
    holding objects all look the same. remote_stat() lists such a path's
    first level to tell them apart, so that yd-delete, yd-download and
    yd-copy find a missing path missing; a listing (yd-ls) takes it as the
    empty directory rclone says it is. A backend that can hold an empty
    directory answers a missing path with exit 3, so there the entry is
    taken as it is. The listing runs alongside the stat, which on bucket
    storage lists a directory too, and is read only where it is needed.
    """

    @staticmethod
    def _listing(calls: list) -> list[str]:
        (listing,) = [c for c in calls if c[0] == "lsjson" and "--stat" not in c]
        return listing

    def _rclone(
        self,
        monkeypatch,
        stat: dict,
        listing: list | None,
        empty_directories: bool = False,
    ) -> list:
        """
        Answer 'lsjson --stat' with 'stat', 'backend features' with whether
        the backend can hold an empty directory (by default not: a bucket),
        and a listing with 'listing' (None: rclone's exit 3, directory not
        found); returns the commands.
        """
        calls: list[list[str]] = []

        def run(_rclone, args):
            calls.append(args)
            if "--stat" in args:
                return MagicMock(returncode=0, stdout=json.dumps(stat))
            if args[:2] == ["backend", "features"]:
                features = {"CanHaveEmptyDirectories": empty_directories}
                return MagicMock(
                    returncode=0, stdout=json.dumps({"Features": features})
                )
            if listing is None:
                return MagicMock(returncode=3, stdout="")
            return MagicMock(returncode=0, stdout=json.dumps(listing))

        monkeypatch.setattr(dcu_module, "_run_quietly", run)
        return calls

    def test_a_missing_path_is_none(self, monkeypatch):
        self._rclone(monkeypatch, _UNNAMED_DIRECTORY, [])
        assert dcu_module.remote_stat(MagicMock(), "s3:b/nope") is None

    def test_a_listing_rclone_cannot_find_is_none(self, monkeypatch):
        self._rclone(monkeypatch, _UNNAMED_DIRECTORY, None)
        assert dcu_module.remote_stat(MagicMock(), "s3:b/nope") is None

    def test_a_prefix_holding_objects_is_a_directory(self, monkeypatch):
        calls = self._rclone(monkeypatch, _UNNAMED_DIRECTORY, [{"Name": "a.txt"}])
        assert dcu_module.remote_stat(MagicMock(), "s3:b/dir") == _UNNAMED_DIRECTORY
        # One level only, so that a large tree is not walked to find one item
        assert self._listing(calls)[-3:] == ["--max-depth", "1", "s3:b/dir"]

    def test_the_existence_check_reads_no_modification_times(self, monkeypatch):
        # On S3 each object's time is a HEAD request of its own: a directory
        # of 100,000 objects took longer than 30 minutes to confirm
        calls = self._rclone(monkeypatch, _UNNAMED_DIRECTORY, [{"Name": "a.txt"}])
        dcu_module.remote_stat(MagicMock(), "s3:b/dir")
        assert "--no-modtime" in self._listing(calls)

    def test_an_empty_directory_where_one_can_be_held_is_a_directory(self, monkeypatch):
        # Local and SFTP: a missing path would have been rclone's exit 3, so
        # the listing's finding nothing does not make it missing
        self._rclone(monkeypatch, _UNNAMED_DIRECTORY, [], empty_directories=True)
        assert dcu_module.remote_stat(MagicMock(), "/tmp/empty") == _UNNAMED_DIRECTORY

    def test_a_listing_takes_it_as_an_empty_directory(self, monkeypatch):
        calls = self._rclone(monkeypatch, _UNNAMED_DIRECTORY, [])
        stat = dcu_module.remote_stat(MagicMock(), "s3:b/new", confirm_directory=False)
        assert stat == _UNNAMED_DIRECTORY
        assert len(calls) == 1  # no listing made

    @pytest.mark.parametrize(
        "stat",
        [
            {"Path": "a.txt", "Name": "a.txt", "Size": 6, "IsDir": False},
            # A named directory, as a local or SFTP remote answers, even empty
            {"Path": "dir", "Name": "dir", "Size": -1, "IsDir": True},
        ],
        ids=["file", "named-directory"],
    )
    def test_a_named_entry_is_taken_as_it_is(self, monkeypatch, stat):
        # The listing found nothing, and is not read: the entry is named
        calls = self._rclone(monkeypatch, stat, [])
        assert dcu_module.remote_stat(MagicMock(), "r:x") == stat
        assert not any(call[:2] == ["backend", "features"] for call in calls)

    def test_a_named_entry_ignores_a_failed_listing(self, monkeypatch):
        entry = {"Path": "a.txt", "Name": "a.txt", "Size": 6, "IsDir": False}

        def run(_rclone, args):
            if "--stat" in args:
                return MagicMock(returncode=0, stdout=json.dumps(entry))
            return MagicMock(returncode=1, stdout="", stderr="not a directory")

        monkeypatch.setattr(dcu_module, "_run_quietly", run)
        assert dcu_module.remote_stat(MagicMock(), "s3:b/a.txt") == entry

    def test_the_stat_and_the_listing_run_at_once(self, monkeypatch):
        # Each waits for the other to start: run one after the other, the
        # first would wait out its timeout
        started = {"stat": threading.Event(), "listing": threading.Event()}

        def run(_rclone, args):
            mine, other = (
                ("stat", "listing") if "--stat" in args else ("listing", "stat")
            )
            if args[:2] == ["backend", "features"]:
                return MagicMock(
                    returncode=0,
                    stdout=json.dumps({"Features": {"CanHaveEmptyDirectories": False}}),
                )
            started[mine].set()
            assert started[other].wait(5), f"the {other} never started"
            if "--stat" in args:
                return MagicMock(returncode=0, stdout=json.dumps(_UNNAMED_DIRECTORY))
            return MagicMock(returncode=0, stdout=json.dumps([{"Name": "a.txt"}]))

        monkeypatch.setattr(dcu_module, "_run_quietly", run)
        assert dcu_module.remote_stat(MagicMock(), "s3:b/dir") == _UNNAMED_DIRECTORY

    def test_an_abandoned_stat_does_not_hold_up_the_exit(self, tmp_path):
        # yd-doctor gives up on a stat that outlasts its timeout, and exits:
        # a listing still running must not keep the process alive
        script = tmp_path / "abandon.py"
        script.write_text(
            "import time\n"
            "from unittest.mock import MagicMock\n"
            "from yellowdog_cli.utils.dataclient import operations\n"
            "from yellowdog_cli.utils.doctor_checks import with_timeout\n"
            "operations._run_quietly = lambda rclone, args: time.sleep(60)\n"
            "with_timeout(lambda: operations.remote_stat(MagicMock(), 's3:b/x'), 0.2)\n",
            encoding="utf-8",
        )
        started = time.monotonic()
        subprocess.run(
            [sys.executable, str(script)],
            cwd=Path(__file__).parent.parent,
            timeout=30,
            check=True,
        )
        assert time.monotonic() - started < 20

    def test_a_listing_that_fails_raises(self, monkeypatch):
        def run(_rclone, args):
            if "--stat" in args:
                return MagicMock(returncode=0, stdout=json.dumps(_UNNAMED_DIRECTORY))
            if args[:2] == ["backend", "features"]:
                features = {"CanHaveEmptyDirectories": False}
                return MagicMock(
                    returncode=0, stdout=json.dumps({"Features": features})
                )
            return MagicMock(returncode=1, stdout="", stderr="AccessDenied")

        monkeypatch.setattr(dcu_module, "_run_quietly", run)
        monkeypatch.setattr(dcu_module, "_rclone_error_detail", lambda r: r.stderr)
        with pytest.raises(RuntimeError, match="Cannot access 's3:b/x': AccessDenied"):
            dcu_module.remote_stat(MagicMock(), "s3:b/x")

    def test_storage_whose_kind_cannot_be_told_raises(self, monkeypatch):
        def run(_rclone, args):
            if "--stat" in args:
                return MagicMock(returncode=0, stdout=json.dumps(_UNNAMED_DIRECTORY))
            return MagicMock(returncode=1, stdout="", stderr="unknown backend")

        monkeypatch.setattr(dcu_module, "_run_quietly", run)
        monkeypatch.setattr(dcu_module, "_rclone_error_detail", lambda r: r.stderr)
        with pytest.raises(RuntimeError, match="Cannot tell what kind of storage"):
            dcu_module.remote_stat(MagicMock(), "x:y")


class TestResolveRemotePathCurrentDirectorySegments:
    """
    A '.' segment names the directory it is in, so it is dropped: '.' alone is
    the prefix itself, which the root and bucket refusals then see as such.
    """

    @staticmethod
    def _config() -> ConfigDataClient:
        return ConfigDataClient(remote="myremote", bucket="b", prefix="p")

    def test_a_dot_alone_is_the_prefix(self):
        assert resolve_remote_path(self._config(), relative_path=".") == "myremote:b/p"

    def test_dots_within_a_path_are_dropped(self):
        assert (
            resolve_remote_path(self._config(), relative_path="./a/./b/")
            == "myremote:b/p/a/b/"
        )

    def test_dots_in_a_full_remote_path_are_dropped(self):
        assert (
            resolve_remote_path(self._config(), relative_path="myremote:b/./c")
            == "myremote:b/c"
        )

    def test_a_dot_with_no_prefix_is_the_bucket(self):
        config = ConfigDataClient(remote="myremote", bucket="b")
        assert resolve_remote_path(config, relative_path=".") == "myremote:b"


@pytest.mark.parametrize(
    "remote_path, name",
    [
        ("loc:a.txt", "a.txt"),
        ("S3:bucket/pfx/a.txt", "a.txt"),
        ("S3:bucket/pfx/dir/", "dir"),
        ("S3:bucket/a:b.txt", "a:b.txt"),
        ("loc:a:b.txt", "a:b.txt"),
    ],
)
def test_remote_basename_splits_off_the_remote_first(remote_path, name):
    assert dcu_module.remote_basename(remote_path) == name


class TestListingsReadModificationTimesOnlyWhereShown:
    """
    rclone reads an S3 object's modification time with a request of its own,
    so a listing asks for it only where 'yd data list' shows it.
    """

    def _calls(self, monkeypatch, listing=None) -> list[list[str]]:
        calls: list[list[str]] = []

        def run(_rclone, args):
            calls.append(args)
            return MagicMock(returncode=0, stdout=json.dumps(listing or []))

        monkeypatch.setattr(dcu_module, "_run_quietly", run)
        return calls

    def test_a_download_listing_reads_none(self, monkeypatch):
        calls = self._calls(monkeypatch)
        dcu_module._lsjson(MagicMock(), "s3:b/dir", recursive=True, files_only=True)
        assert "--no-modtime" in calls[0]

    def test_a_wildcard_match_for_a_transfer_reads_none(self, monkeypatch):
        calls = self._calls(monkeypatch, [{"Name": "a.txt", "IsDir": False}])
        dcu_module.glob_matches(MagicMock(), "s3:b/dir/*.txt")
        assert "--no-modtime" in calls[0]

    def test_ls_reads_them_for_its_wildcards_and_listings(self, monkeypatch):
        calls = self._calls(monkeypatch, [{"Name": "a.txt", "IsDir": False}])
        dcu_module.glob_matches(MagicMock(), "s3:b/dir/*.txt", modtime=True)
        dcu_module._lsjson(MagicMock(), "s3:b/dir", modtime=True)
        assert all("--no-modtime" not in call for call in calls)


# ---------------------------------------------------------------------------
# yd-upload of a symlinked file, through a real rclone
# ---------------------------------------------------------------------------


@needs_rclone
@pytest.mark.parametrize("into_other_directory", [False, True])
def test_symlinked_files_are_uploaded_as_their_targets(tmp_path, into_other_directory):
    """
    Symlinks among a directory's files are uploaded under their own names
    with their targets' content, not recorded as uploaded while rclone,
    given their names in a list, skips them (links it does not follow) or
    finds no such names (links pointing into another directory).
    """
    reset_results()
    data, elsewhere, destination = (tmp_path / d for d in ("data", "other", "dst"))
    for directory in (data, elsewhere, destination):
        directory.mkdir()
    targets = elsewhere if into_other_directory else data
    (targets / "2026.csv").write_text("this year")
    (targets / "2025.csv").write_text("last year")
    (data / "other.csv").write_text("plain")
    try:
        (data / "latest.csv").symlink_to(targets / "2026.csv")
        (data / "previous.csv").symlink_to(targets / "2025.csv")
    except OSError:
        pytest.skip("symbolic links cannot be made here")
    names = ("latest.csv", "previous.csv", "other.csv")
    uploads = [(data / name, f"loc:{destination.as_posix()}/{name}") for name in names]
    failed = upload_files(ConfigDataClient(remote="loc,type=local"), uploads)
    assert failed == 0
    assert [(destination / name).read_text() for name in names] == [
        "this year",
        "last year",
        "plain",
    ]
    assert [r["action"] for r in results_module._ITEMS] == ["uploaded"] * 3


# ---------------------------------------------------------------------------
# Paths at a remote's root
# ---------------------------------------------------------------------------


def test_files_under_a_bare_remote_are_not_made_absolute(tmp_path):
    # 'box:' + '/' + name is 'box:/name', the filesystem's root on a local
    # or SFTP remote, not the remote's own
    from yellowdog_cli.utils.dataclient.operations import (
        _local_upload_files,
        flattened_destinations,
    )

    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "f.txt").write_text("x", encoding="utf-8")
    assert flattened_destinations(tmp_path, "box:") == ["box:f.txt"]
    assert [d for _, d, _ in _local_upload_files(tmp_path, "box:")] == ["box:sub/f.txt"]
    assert flattened_destinations(tmp_path, "box:up/") == ["box:up/f.txt"]


@needs_rclone
def test_a_file_at_the_remotes_root_is_copied_under_its_own_name(tmp_path, monkeypatch):
    # Not named after the remote ('sub/loc:a.txt'), as the whole path's last
    # '/'-separated part would have it
    from yellowdog_cli.utils.dataclient.operations import copy_remote

    reset_results()
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    config = ConfigDataClient(remote="loc,type=local")
    copy_remote(config, "loc:a.txt", config, "loc:sub/", src_is_file=True)
    assert [p.name for p in (tmp_path / "sub").iterdir()] == ["a.txt"]


def test_items_are_grouped_by_directory_a_group_of_one_done_alone():
    from yellowdog_cli.utils.dataclient.operations import _by_directory

    items = ["a/1", "b/1", "a/2", "solo", "c/1"]
    groups, singles = _by_directory(
        items, lambda item: item.split("/")[0] if "/" in item else None
    )
    assert groups == {"a": ["a/1", "a/2"]}
    # In the order given: one with no directory, and those alone in theirs
    assert singles == ["b/1", "solo", "c/1"]


class TestTheTrace:
    """
    Each rclone run is traced with its command line, an inline remote's
    parameters withheld, and its exit status.
    """

    def test_a_run_and_its_exit_status_are_traced(self, caplog):
        rclone = MagicMock()
        rclone.impl._run.return_value = subprocess.CompletedProcess([], 3)
        with caplog.at_level(logging.DEBUG, logger="yellowdog_cli"):
            dcu_module._run_quietly(
                rclone,
                ["lsjson", ":s3,provider=AWS,secret_access_key=SECRET-KEY:bucket/p"],
            )
        assert caplog.messages == [
            "rclone lsjson :s3,provider=AWS,<1 parameter redacted>",
            "rclone lsjson: exit status 3",
        ]

    def test_a_copy_of_named_files_counts_them(self, caplog):
        rclone = MagicMock()
        rclone.copy.return_value = subprocess.CompletedProcess([], 0)
        with caplog.at_level(logging.DEBUG, logger="yellowdog_cli"):
            dcu_module._copy_files(rclone, "/data", "remote:b/p", ["a", "b"])
        assert caplog.messages[0] == (
            "rclone copy /data remote:b/p --files-from-raw <2 names>"
        )
