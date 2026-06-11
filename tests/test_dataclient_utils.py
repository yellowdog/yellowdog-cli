"""
Unit tests for yellowdog_cli.utils.dataclient_utils
"""

import pytest

from yellowdog_cli.utils.config_types import ConfigDataClient
from yellowdog_cli.utils.dataclient_utils import resolve_remote_path
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
