"""
Tests for yd-upload's --destination handling of single vs. multiple files.

Multiple files (or an explicit 'dir/' destination) must each keep their own
filename under the destination; a single file with a plain destination is a
rename (rclone copyto semantics).
"""

from unittest.mock import MagicMock, patch

import pytest

import yellowdog_cli.upload as upload_module
from yellowdog_cli.utils.config_types import ConfigDataClient

CONFIG = ConfigDataClient(remote="myremote", bucket="b")


def _args(local_paths: list[str], destination: str | None) -> MagicMock:
    mock_args = MagicMock()
    mock_args.upgrade_rclone = False
    mock_args.which_rclone = False
    mock_args.sync = False
    mock_args.recursive = False
    mock_args.flatten = False
    mock_args.dry_run = False
    mock_args.destination = destination
    mock_args.local_paths = local_paths
    return mock_args


def _run_upload(tmp_path, filenames: list[str], destination: str | None) -> list[str]:
    """
    Run yd-upload main() with mocked transfer; return the remote paths
    passed to upload_file, in order.
    """
    local_paths = []
    for name in filenames:
        f = tmp_path / name
        f.write_text("content")
        local_paths.append(str(f))

    with (
        patch.object(upload_module, "ARGS_PARSER", _args(local_paths, destination)),
        patch.object(upload_module, "CONFIG_DATA_CLIENT", CONFIG),
        patch.object(upload_module, "upload_file") as mock_upload,
    ):
        with pytest.raises(SystemExit) as exc_info:
            upload_module.main()
        assert exc_info.value.code == 0

    return [call.args[2] for call in mock_upload.call_args_list]


class TestUploadDestination:
    def test_multiple_files_keep_their_names(self, tmp_path):
        remote_paths = _run_upload(tmp_path, ["a.txt", "b.txt"], "dest")
        assert remote_paths == ["myremote:b/dest/a.txt", "myremote:b/dest/b.txt"]

    def test_single_file_plain_destination_is_rename(self, tmp_path):
        remote_paths = _run_upload(tmp_path, ["a.txt"], "renamed.txt")
        assert remote_paths == ["myremote:b/renamed.txt"]

    def test_single_file_directory_destination_keeps_name(self, tmp_path):
        remote_paths = _run_upload(tmp_path, ["a.txt"], "dest/")
        assert remote_paths == ["myremote:b/dest/a.txt"]

    def test_no_destination_uses_filename(self, tmp_path):
        remote_paths = _run_upload(tmp_path, ["a.txt"], None)
        assert remote_paths == ["myremote:b/a.txt"]
