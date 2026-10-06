"""
System tests: dataclient commands (yd-upload, yd-ls, yd-download, yd-delete).

Each test is self-contained: it uploads whatever it needs, exercises the
command under test, cleans up, and verifies the post-condition.

Run with: pytest --run-system tests/test_system_dataclient.py

Prerequisites: YD_KEY, YD_SECRET (or equivalent) must be set in the
environment, and tests/system/config.toml must contain a [dataClient] section.
"""

import pytest
from cli_test_helpers import shell

from yellowdog_cli.utils.output_style import DRY_RUN_MARKER

SYSTEM_DIR = "tests/system"


@pytest.fixture(scope="session")
def dc_base(system_tag):
    """
    Session-unique remote base directory for all dataclient tests.

    A belt-and-braces recursive delete runs at session end; individual tests
    also register their own cleanup via the ``cleanup`` fixture.
    """
    base = f"pytest-dc/{system_tag}"
    yield base
    shell(f"cd {SYSTEM_DIR} && yd-delete -y -R {base}")


@pytest.mark.system
class TestSystemDataClient:
    # ------------------------------------------------------------------
    # Upload → list → delete
    # ------------------------------------------------------------------

    def test_upload_list_delete(self, dc_base, tmp_path, cleanup):
        remote = f"{dc_base}/upload-list-delete"
        cleanup(f"cd {SYSTEM_DIR} && yd-delete -y -R {remote}")
        filename = "hello.txt"
        (tmp_path / filename).write_text("hello from pytest")

        result = shell(
            f"cd {SYSTEM_DIR} && yd-upload {tmp_path / filename} --destination {remote}/{filename}"
        )
        assert result.exit_code == 0, f"upload failed:\n{result.stdout}"

        result = shell(f"cd {SYSTEM_DIR} && yd-ls {remote}/")
        assert result.exit_code == 0
        assert filename in result.stdout, f"file not found in ls:\n{result.stdout}"

        result = shell(f"cd {SYSTEM_DIR} && yd-delete -y {remote}/{filename}")
        assert result.exit_code == 0, f"delete failed:\n{result.stdout}"

        result = shell(f"cd {SYSTEM_DIR} && yd-ls {remote}/")
        assert result.exit_code == 0
        assert filename not in result.stdout, f"file still present after delete"

    # ------------------------------------------------------------------
    # Upload → download → verify content
    # ------------------------------------------------------------------

    def test_upload_download_roundtrip(self, dc_base, tmp_path, cleanup):
        remote = f"{dc_base}/roundtrip"
        cleanup(f"cd {SYSTEM_DIR} && yd-delete -y -R {remote}")
        filename = "roundtrip.txt"
        content = "roundtrip-content-abc123\n"
        (tmp_path / filename).write_text(content)
        dl_dir = tmp_path / "downloaded"

        result = shell(
            f"cd {SYSTEM_DIR} && yd-upload {tmp_path / filename} --destination {remote}/{filename}"
        )
        assert result.exit_code == 0, f"upload failed:\n{result.stdout}"

        result = shell(
            f"cd {SYSTEM_DIR} && yd-download {remote}/{filename} --destination {dl_dir}"
        )
        assert result.exit_code == 0, f"download failed:\n{result.stdout}"

        downloaded = dl_dir / filename
        assert downloaded.exists(), f"downloaded file not found: {downloaded}"
        assert downloaded.read_text() == content, "downloaded content does not match"

    # ------------------------------------------------------------------
    # Recursive upload → recursive ls
    # ------------------------------------------------------------------

    def test_upload_recursive_and_ls_recursive(self, dc_base, tmp_path, cleanup):
        remote = f"{dc_base}/recursive"
        cleanup(f"cd {SYSTEM_DIR} && yd-delete -y -R {remote}")
        src = tmp_path / "srcdir"
        src.mkdir()
        (src / "alpha.txt").write_text("alpha")
        (src / "beta.txt").write_text("beta")
        subdir = src / "sub"
        subdir.mkdir()
        (subdir / "gamma.txt").write_text("gamma")

        result = shell(f"cd {SYSTEM_DIR} && yd-upload {src} -R --destination {remote}")
        assert result.exit_code == 0, f"recursive upload failed:\n{result.stdout}"

        result = shell(f"cd {SYSTEM_DIR} && yd-ls -R {remote}")
        assert result.exit_code == 0
        assert "alpha.txt" in result.stdout
        assert "beta.txt" in result.stdout
        assert "gamma.txt" in result.stdout

    # ------------------------------------------------------------------
    # Wildcard list and delete
    # ------------------------------------------------------------------

    def test_wildcard_ls_and_delete(self, dc_base, tmp_path, cleanup):
        remote = f"{dc_base}/wildcard"
        cleanup(f"cd {SYSTEM_DIR} && yd-delete -y -R {remote}")
        for name in ("w1.csv", "w2.csv", "keep.txt"):
            (tmp_path / name).write_text(name)
            result = shell(
                f"cd {SYSTEM_DIR} && yd-upload {tmp_path / name} --destination {remote}/{name}"
            )
            assert result.exit_code == 0, f"upload of {name} failed:\n{result.stdout}"

        # Wildcard list: CSVs only
        result = shell(f"cd {SYSTEM_DIR} && yd-ls '{remote}/*.csv'")
        assert result.exit_code == 0
        assert "w1.csv" in result.stdout
        assert "w2.csv" in result.stdout
        assert "keep.txt" not in result.stdout

        # Wildcard delete: remove CSVs only
        result = shell(f"cd {SYSTEM_DIR} && yd-delete -y '{remote}/*.csv'")
        assert result.exit_code == 0, f"wildcard delete failed:\n{result.stdout}"

        # CSVs gone, txt survives
        result = shell(f"cd {SYSTEM_DIR} && yd-ls {remote}/")
        assert result.exit_code == 0
        assert "w1.csv" not in result.stdout
        assert "w2.csv" not in result.stdout
        assert "keep.txt" in result.stdout

    # ------------------------------------------------------------------
    # Dry-run: upload does not create remote file
    # ------------------------------------------------------------------

    def test_dry_run_upload(self, dc_base, tmp_path):
        remote = f"{dc_base}/dryrun-upload"
        filename = "dry.txt"
        (tmp_path / filename).write_text("dry run test")

        result = shell(
            f"cd {SYSTEM_DIR} && yd-upload -D {tmp_path / filename} --destination {remote}/{filename}"
        )
        assert result.exit_code == 0
        assert DRY_RUN_MARKER in result.stdout, (
            f"expected dry-run message:\n{result.stdout}"
        )

        result = shell(f"cd {SYSTEM_DIR} && yd-ls {remote}/")
        assert result.exit_code == 0
        assert filename not in result.stdout, "file was uploaded despite --dry-run"

    # ------------------------------------------------------------------
    # Dry-run: delete does not remove remote file
    # ------------------------------------------------------------------

    def test_dry_run_delete(self, dc_base, tmp_path, cleanup):
        remote = f"{dc_base}/dryrun-delete"
        cleanup(f"cd {SYSTEM_DIR} && yd-delete -y -R {remote}")
        filename = "nodelete.txt"
        (tmp_path / filename).write_text("keep me")

        result = shell(
            f"cd {SYSTEM_DIR} && yd-upload {tmp_path / filename} --destination {remote}/{filename}"
        )
        assert result.exit_code == 0, f"upload failed:\n{result.stdout}"

        result = shell(f"cd {SYSTEM_DIR} && yd-delete -D {remote}/{filename}")
        assert result.exit_code == 0
        assert DRY_RUN_MARKER in result.stdout, (
            f"expected dry-run message:\n{result.stdout}"
        )

        result = shell(f"cd {SYSTEM_DIR} && yd-ls {remote}/")
        assert result.exit_code == 0
        assert filename in result.stdout, "file was deleted despite --dry-run"

    # ------------------------------------------------------------------
    # Dry-run: download does not create local file
    # ------------------------------------------------------------------

    def test_dry_run_download(self, dc_base, tmp_path, cleanup):
        remote = f"{dc_base}/dryrun-download"
        cleanup(f"cd {SYSTEM_DIR} && yd-delete -y -R {remote}")
        filename = "nodownload.txt"
        (tmp_path / filename).write_text("remote content")
        dl_dir = tmp_path / "dl"

        result = shell(
            f"cd {SYSTEM_DIR} && yd-upload {tmp_path / filename} --destination {remote}/{filename}"
        )
        assert result.exit_code == 0, f"upload failed:\n{result.stdout}"

        result = shell(
            f"cd {SYSTEM_DIR} && yd-download -D {remote}/{filename} --destination {dl_dir}"
        )
        assert result.exit_code == 0
        assert DRY_RUN_MARKER in result.stdout, (
            f"expected dry-run message:\n{result.stdout}"
        )
        assert not (dl_dir / filename).exists(), "file was downloaded despite --dry-run"

    # ------------------------------------------------------------------
    # A path that does not exist: a bucket-based remote answers rclone's
    # stat of any such path with an unnamed directory, which read as an
    # empty directory to all three commands
    # ------------------------------------------------------------------

    def test_a_missing_path_is_not_downloaded(self, dc_base, tmp_path):
        result = shell(
            f"cd {SYSTEM_DIR} && yd-download {dc_base}/no-such-path"
            f" --destination {tmp_path / 'dl'}"
        )
        assert result.exit_code == 1
        assert "does not exist" in result.stdout + result.stderr

    def test_a_missing_path_is_not_deleted(self, dc_base):
        # Gone already is what a deletion wants: a warning, not 'is a directory'
        result = shell(f"cd {SYSTEM_DIR} && yd-delete -y {dc_base}/no-such-path")
        assert result.exit_code == 0
        output = result.stdout + result.stderr
        assert "does not exist" in output and "is a directory" not in output

    def test_a_missing_path_lists_as_empty(self, dc_base):
        # On a bucket-based remote an empty prefix and a missing one are the
        # same thing, and a prefix nothing is uploaded to yet is no error
        result = shell(f"cd {SYSTEM_DIR} && yd-ls {dc_base}/no-such-path")
        assert result.exit_code == 0
