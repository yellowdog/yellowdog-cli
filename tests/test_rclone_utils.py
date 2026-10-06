"""
Unit tests for yellowdog_cli.utils.dataclient.rclone
"""

from unittest.mock import MagicMock, patch

import pytest

from yellowdog_cli.utils.dataclient.rclone import (
    is_inline_remote,
    parse_rclone_config,
    shown_remote,
)


class TestParseRcloneConfig:
    """
    parse_rclone_config accepts either:
      - A plain remote name  ("myremote")          → (name, None)
      - An inline config     ("NAME,type=s3,...")   → (name, ini_section_str)
    An optional leading "rclone:" prefix is stripped in both cases.
    """

    def setup_method(self):
        parse_rclone_config.cache_clear()

    # ------------------------------------------------------------------
    # Plain remote names (defined in system rclone.conf)
    # ------------------------------------------------------------------

    def test_plain_remote_name(self):
        name, config = parse_rclone_config("myremote")
        assert name == "myremote"
        assert config is None

    def test_plain_remote_strips_rclone_prefix(self):
        name, config = parse_rclone_config("rclone:myremote")
        assert name == "myremote"
        assert config is None

    def test_empty_string_defaults_to_remote(self):
        name, config = parse_rclone_config("")
        assert name == "remote"
        assert config is None

    def test_whitespace_only_defaults_to_remote(self):
        name, config = parse_rclone_config("  ")
        assert name == "remote"
        assert config is None

    # ------------------------------------------------------------------
    # Inline config strings (all parameters embedded in the string)
    # ------------------------------------------------------------------

    def test_inline_config_remote_name(self):
        name, config = parse_rclone_config("S3,type=s3,provider=AWS")
        assert name == "S3"
        assert config is not None

    def test_inline_config_section_header(self):
        _name, config = parse_rclone_config("S3,type=s3,provider=AWS")
        assert config is not None
        assert "[S3]" in config

    def test_inline_config_params_present(self):
        _name, config = parse_rclone_config("S3,type=s3,provider=AWS,env_auth=true")
        assert config is not None
        assert "type = s3" in config
        assert "provider = AWS" in config
        assert "env_auth = true" in config

    def test_inline_config_strips_rclone_prefix(self):
        name, config = parse_rclone_config("rclone:myS3,type=s3,provider=AWS")
        assert name == "myS3"
        assert config is not None
        assert "[myS3]" in config

    def test_inline_config_region_param(self):
        _name, config = parse_rclone_config(
            "S3,type=s3,provider=AWS,env_auth=true,region=eu-west-2"
        )
        assert config is not None
        assert "region = eu-west-2" in config

    def test_inline_config_empty_remote_name_defaults(self):
        # Leading comma → empty remote_name → defaults to "remote"
        name, config = parse_rclone_config(",type=s3")
        assert name == "remote"
        assert config is not None
        assert "[remote]" in config

    # ------------------------------------------------------------------
    # Caching: clearing and re-querying produces the same result
    # ------------------------------------------------------------------

    def test_repeated_call_after_clear_returns_same_result(self):
        r1 = parse_rclone_config("cached_remote")
        parse_rclone_config.cache_clear()
        r2 = parse_rclone_config("cached_remote")
        assert r1 == r2

    # ------------------------------------------------------------------
    # Quoted / stripped values
    # ------------------------------------------------------------------

    def test_single_quoted_value_stripped(self):
        _name, config = parse_rclone_config("R,type='s3'")
        assert config is not None
        assert "type = s3" in config

    def test_double_quoted_value_stripped(self):
        _name, config = parse_rclone_config('R2,type="s3"')
        assert config is not None
        assert "type = s3" in config


# ---------------------------------------------------------------------------
# make_rclone_for_copy: remote-name collision handling
# ---------------------------------------------------------------------------


class TestMakeRcloneForCopy:
    """
    Remote names must be unique in the combined config passed to rclone;
    colliding inline remotes are renamed and the new names returned.
    """

    def setup_method(self):
        parse_rclone_config.cache_clear()

    def _call(self, src: str, dst: str, sys_conf: str | None = None):
        """
        Run make_rclone_for_copy with make_rclone mocked out.
        Returns (src_name, dst_name, config_text_passed_to_make_rclone).
        """
        import yellowdog_cli.utils.dataclient.rclone as rcu

        captured: dict = {}

        def fake_make_rclone(config):
            captured["config"] = config
            return MagicMock()

        with (
            patch.object(rcu, "make_rclone", side_effect=fake_make_rclone),
            patch.object(
                rcu,
                "_find_rclone_conf",
                return_value=MagicMock(read_text=lambda **k: sys_conf or ""),
            ),
        ):
            src_name, dst_name, _ = rcu.make_rclone_for_copy(src, dst)

        config = captured["config"]
        config_text = None if config is None else config.text
        return src_name, dst_name, config_text

    def test_both_system_remotes_no_config(self):
        src_name, dst_name, config_text = self._call("r1", "r2")
        assert (src_name, dst_name) == ("r1", "r2")
        assert config_text is None

    def test_identical_inline_configs_share_one_section(self):
        remote = "S3,type=s3,provider=AWS"
        src_name, dst_name, config_text = self._call(remote, remote)
        assert (src_name, dst_name) == ("S3", "S3")
        assert config_text is not None
        assert config_text.count("[S3]") == 1

    def test_same_name_different_inline_configs_renamed(self):
        src_name, dst_name, config_text = self._call(
            "S3,type=s3,provider=AWS,access_key_id=AAA",
            "S3,type=s3,provider=AWS,access_key_id=BBB",
        )
        assert src_name == "S3"
        assert dst_name == "S3-dst"
        assert config_text is not None
        assert "[S3]" in config_text
        assert "[S3-dst]" in config_text
        assert "access_key_id = AAA" in config_text
        assert "access_key_id = BBB" in config_text

    def test_inline_name_colliding_with_system_conf_renamed(self):
        sys_conf = "[S3]\ntype = s3\nprovider = AWS\n"
        src_name, dst_name, config_text = self._call(
            "S3,type=s3,provider=Other", "sysremote", sys_conf=sys_conf
        )
        assert src_name == "S3-src"
        assert dst_name == "sysremote"
        assert config_text is not None
        assert "[S3]" in config_text
        assert "[S3-src]" in config_text

    def test_no_collision_names_unchanged(self):
        src_name, dst_name, config_text = self._call(
            "SRC,type=s3,provider=AWS", "DST,type=gcs"
        )
        assert (src_name, dst_name) == ("SRC", "DST")
        assert config_text is not None
        assert "[SRC]" in config_text
        assert "[DST]" in config_text


class TestIsInlineRemote:
    """
    What yd-variables withholds the parameters of, by the shape of the value:
    strict, so that an ordinary comma-separated value is never taken for one.
    """

    @pytest.mark.parametrize(
        "value",
        [
            "S3,type=s3,provider=AWS,secret_access_key=X",
            "rclone:S3,type=s3,secret_access_key=X",
            "rclone:S3,type=s3,secret_access_key=X:bucket/path",
            ":s3,provider=AWS,secret_access_key=X:",
            ":s3,secret_access_key=X",
            "loc,type=local",
        ],
    )
    def test_inline_remotes(self, value):
        assert is_inline_remote(value)

    @pytest.mark.parametrize(
        "value",
        ["myremote:", "rclone:myremote:path", "a,b", "x,y=z", "a,b,port=8080", ""],
    )
    def test_not_inline_remotes(self, value):
        assert not is_inline_remote(value)


class TestShownRemote:
    @pytest.mark.parametrize(
        "remote, shown",
        [
            (
                "rclone:S3,type=s3,provider=AWS,access_key_id=A,secret_access_key=B",
                "rclone:S3,type=s3,provider=AWS,<2 parameters redacted>",
            ),
            # A trailing path goes with the last parameter: it cannot be told
            # apart from the port of a URL there
            (
                "rclone:S3,type=s3,secret_access_key=B:bucket/path",
                "rclone:S3,type=s3,<1 parameter redacted>",
            ),
            (
                "r,type=s3,endpoint=http://127.0.0.1:9",
                "r,type=s3,<1 parameter redacted>",
            ),
        ],
    )
    def test_the_prefix_is_kept(self, remote, shown):
        assert shown_remote(remote) == shown


class TestParametersReadAsRcloneReadsThem:
    """
    An inline remote's values: quoted ones may hold commas (a doubled quote
    is the quote), spaces are allowed around '=', and rclone's own
    ':backend' form is a remote named for its backend, of that type.
    """

    def test_a_quoted_value_keeps_its_commas(self):
        _, section = parse_rclone_config(
            'S3,type=s3,secret_access_key="a,b=c",region=eu'
        )
        assert section == "[S3]\ntype = s3\nsecret_access_key = a,b=c\nregion = eu"

    def test_a_single_quoted_value_and_a_doubled_quote(self):
        _, section = parse_rclone_config("""S3,type=s3,a='x,y',b="say ""hi\"\"\"""")
        assert section == '[S3]\ntype = s3\na = x,y\nb = say "hi"'

    def test_spaces_around_the_equals_sign(self):
        _, section = parse_rclone_config("S3, type = s3 , secret_access_key = X")
        assert section == "[S3]\ntype = s3\nsecret_access_key = X"

    def test_rclone_backend_form(self):
        assert parse_rclone_config(":s3,provider=AWS,env_auth=true") == (
            "s3",
            "[s3]\ntype = s3\nprovider = AWS\nenv_auth = true",
        )
        assert parse_rclone_config(":local") == ("local", "[local]\ntype = local")

    def test_spaced_credentials_are_still_recognised_and_withheld(self):
        remote = "S3, type = s3 , secret_access_key = X"
        assert is_inline_remote(remote)
        assert "X" not in shown_remote(remote)

    def test_a_quoted_credential_is_withheld_whole(self):
        shown = shown_remote('rclone:S3,type=s3,secret_access_key="a,b=c"')
        assert shown == "rclone:S3,type=s3,<1 parameter redacted>"

    def test_the_backend_form_is_shown_as_written(self):
        assert (
            shown_remote(":s3,provider=AWS,env_auth=true")
            == ":s3,provider=AWS,<1 parameter redacted>"
        )


class TestNoRcloneConfiguration:
    def test_a_missing_configuration_says_where_it_looked(self, monkeypatch, tmp_path):
        from yellowdog_cli.utils.dataclient import rclone as rclone_utils

        monkeypatch.delenv("RCLONE_CONFIG", raising=False)
        monkeypatch.setattr(rclone_utils.Path, "home", lambda: tmp_path)
        monkeypatch.setattr(rclone_utils.platform, "system", lambda: "Linux")
        with pytest.raises(FileNotFoundError, match="looked for") as raised:
            rclone_utils._find_rclone_conf()
        assert str(tmp_path) in str(raised.value)
        assert "RCLONE_CONFIG" in str(raised.value)


def test_rclone_api_logging_is_kept_off_stdout():
    """
    Importing rclone_api puts a logging handler on stdout, through which it
    logs its first-run download; under '--json' that would come before the
    document. Every use of rclone_api moves it to stderr first.
    """
    import subprocess
    import sys

    script = (
        "import logging, sys; sys.argv = ['yd-ls']\n"
        "import rclone_api\n"
        "from yellowdog_cli.utils.dataclient.rclone import _keep_logging_off_stdout\n"
        "_keep_logging_off_stdout()\n"
        "logging.getLogger('rclone_api.install').warning('Downloading rclone')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert result.stdout == ""
    assert "Downloading rclone" in result.stderr
