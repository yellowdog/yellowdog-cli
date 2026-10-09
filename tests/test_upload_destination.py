"""
Tests for yd-upload's --destination handling of single vs. multiple files.

Multiple files (or an explicit 'dir/' destination) must each keep their own
filename under the destination; a single file with a plain destination is a
rename (rclone copyto semantics).
"""

from unittest.mock import MagicMock, patch

import pytest

import yellowdog_cli.upload as upload_module
import yellowdog_cli.utils.dataclient.wrapper as dataclient_wrapper_module
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
        patch.object(
            dataclient_wrapper_module, "ARGS_PARSER", _args(local_paths, destination)
        ),
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


class TestSyncIntoTheRootOrBucketIsRefused:
    """
    --sync deletes every remote file not in the local directory, so a sync
    whose destination is the remote's root or the configured bucket itself
    is refused before anything is uploaded, as yd-copy's is.
    """

    @staticmethod
    def _sync(tmp_path, config: ConfigDataClient, destination: str) -> tuple:
        directory = tmp_path / "d"
        directory.mkdir()
        (directory / "a.txt").write_text("a", encoding="utf-8")
        args = _args([str(directory)], destination)
        args.sync = True
        with (
            patch.object(dataclient_wrapper_module, "ARGS_PARSER", args),
            patch.object(upload_module, "CONFIG_DATA_CLIENT", config),
            patch.object(upload_module, "upload_directory") as mock_upload,
            pytest.raises(SystemExit) as raised,
        ):
            upload_module.main()
        return raised.value.code, mock_upload

    @pytest.mark.parametrize("destination", ["/", "."])
    def test_into_the_bucket(self, tmp_path, destination):
        code, mock_upload = self._sync(tmp_path, CONFIG, destination)
        assert code == 2
        mock_upload.assert_not_called()

    def test_into_the_remote_root(self, tmp_path):
        code, mock_upload = self._sync(
            tmp_path, ConfigDataClient(remote="myremote"), "/"
        )
        assert code == 2
        mock_upload.assert_not_called()

    def test_into_a_directory_within_the_bucket(self, tmp_path):
        code, mock_upload = self._sync(tmp_path, CONFIG, "dest")
        assert code == 0
        assert mock_upload.call_args.args[2] == "myremote:b/dest"


@pytest.mark.parametrize("dry_run, said", [(False, "Upload complete"), (True, None)])
def test_a_dry_run_does_not_say_it_uploaded(tmp_path, dry_run, said):
    # It ended 'Upload complete', having uploaded nothing
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    args = _args([str(tmp_path / "a.txt")], None)
    args.dry_run = dry_run
    infos: list[str] = []
    with (
        patch.object(dataclient_wrapper_module, "ARGS_PARSER", args),
        patch.object(upload_module, "CONFIG_DATA_CLIENT", CONFIG),
        patch.object(upload_module, "upload_file", return_value=True),
        patch.object(upload_module, "print_info", side_effect=infos.append),
        pytest.raises(SystemExit),
    ):
        upload_module.main()
    if said is not None:
        assert infos[-1] == said
    else:
        assert not any("complete" in info and "Dry run" not in info for info in infos)
        assert infos[-1].startswith("Dry run complete")
