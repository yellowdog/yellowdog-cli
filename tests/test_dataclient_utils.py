"""
Unit tests for yellowdog_cli.utils.dataclient_utils
"""

import json
import re
import shutil
import threading
import time
import warnings
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import yellowdog_cli.download as yd_download
import yellowdog_cli.utils.dataclient_utils as dcu_module
import yellowdog_cli.utils.dataclient_wrapper as dcw_module
import yellowdog_cli.utils.interactive as interactive_module
import yellowdog_cli.utils.printing as printing_module
import yellowdog_cli.utils.rclone_utils as rclone_utils_module
import yellowdog_cli.utils.results as results_module
from yellowdog_cli.utils.config_types import ConfigDataClient
from yellowdog_cli.utils.dataclient_utils import resolve_remote_path, upload_directory
from yellowdog_cli.utils.rclone_version import find_rclone
from yellowdog_cli.utils.results import reset_results
from yellowdog_cli.utils.variables import VARIABLE_SUBSTITUTIONS


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

    def test_strips_leading_slashes_keeps_directory_intent(self):
        # Leading slashes are stripped; a trailing '/' is preserved because it
        # denotes directory-destination intent (yd-copy / yd-upload)
        config = self._config(bucket="/b/", prefix="/p/")
        assert resolve_remote_path(config, relative_path="/sub/") == "myremote:b/p/sub/"

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
        from yellowdog_cli.utils.dataclient_utils import _split_glob_remote_path

        assert _split_glob_remote_path("S3:bucket/prefix/xxx*") == (
            "S3:bucket/prefix/",
            "xxx*",
        )

    def test_glob_at_top_level(self):
        from yellowdog_cli.utils.dataclient_utils import _split_glob_remote_path

        assert _split_glob_remote_path("S3:xxx*") == ("S3:", "xxx*")

    @pytest.mark.parametrize(
        "path",
        ["S3:bucket/dir*/file.txt", "S3:buck?t/prefix/file*", "S3:a[1]/b/c*"],
    )
    def test_mid_path_glob_rejected(self, path):
        from yellowdog_cli.utils.dataclient_utils import _split_glob_remote_path

        with pytest.raises(ValueError, match="final path component"):
            _split_glob_remote_path(path)


class TestUploadDirectoryWalksOnlyForJson:
    """
    A directory upload lists its local files only to record them, which
    nothing prints without '--json': a large tree is not walked for nothing.
    """

    def _upload(self, monkeypatch, tmp_path, json_output: bool) -> list:
        (tmp_path / "d").mkdir()
        (tmp_path / "d" / "x.txt").write_text("x")
        monkeypatch.setattr(
            results_module, "ARGS_PARSER", MagicMock(json_output=json_output)
        )
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
            monkeypatch.setattr(target, "ARGS_PARSER", args)
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
