"""
load_config records where each [common] value came from (CONFIG_SOURCES), and
load_config_common(strict=False) returns a partial ConfigCommon instead of
exiting when the key or secret is missing.
"""

from unittest.mock import MagicMock

import pytest

from yellowdog_cli.utils import load_config
from yellowdog_cli.utils.settings import YD_KEY, YD_NAMESPACE, YD_SECRET


def _args(**values) -> MagicMock:
    args = MagicMock()
    for name in ("key", "secret", "namespace", "tag", "url", "use_pac", "config_file"):
        setattr(args, name, values.get(name))
    args.namespace_required = False
    args.tag_required = False
    args.property_overrides = None
    return args


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setattr(load_config, "CONFIG_TOML", {"common": {}})
    monkeypatch.setattr(load_config, "CONFIG_SOURCES", {})
    for var in (YD_KEY, YD_SECRET, YD_NAMESPACE, "YD_TAG", "YD_URL", "YD_READ_TIMEOUT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(load_config, "config_file_explicitly_selected", lambda: False)
    # As test_load_config_helpers does: keep the test's key, secret and
    # namespace out of the process-wide variable table
    monkeypatch.setattr(
        load_config, "add_substitutions_without_overwriting", lambda subs: None
    )
    monkeypatch.setattr(load_config, "register_dc_substitutions", lambda: None)


class TestConfigSources:
    def test_command_line_wins(self, isolated, monkeypatch):
        monkeypatch.setenv(YD_KEY, "env-key")
        monkeypatch.setattr(load_config, "_ARGS", _args(key="cli-key", secret="s"))
        cfg = load_config.load_config_common()
        assert cfg.key == "cli-key"
        assert load_config.CONFIG_SOURCES["key"] == "command line"
        assert load_config.CONFIG_SOURCES["secret"] == "command line"

    def test_environment_names_the_variable(self, isolated, monkeypatch):
        monkeypatch.setenv(YD_KEY, "env-key")
        monkeypatch.setenv(YD_SECRET, "env-secret")
        monkeypatch.setattr(load_config, "_ARGS", _args())
        load_config.load_config_common()
        assert load_config.CONFIG_SOURCES["key"] == f"environment ({YD_KEY})"
        assert load_config.CONFIG_SOURCES["namespace"] == "default"
        assert load_config.CONFIG_SOURCES["tag"] == "default"
        assert load_config.CONFIG_SOURCES["url"] == "default"

    def test_config_file(self, isolated, monkeypatch):
        monkeypatch.setattr(
            load_config,
            "CONFIG_TOML",
            {"common": {"key": "k", "secret": "s", "namespace": "ns"}},
        )
        monkeypatch.setattr(load_config, "CONFIG_FILE", "my.toml")
        monkeypatch.setattr(load_config, "_ARGS", _args())
        load_config.load_config_common()
        assert load_config.CONFIG_SOURCES["namespace"] == "config file (my.toml)"

    def test_imported_value_names_the_imported_file(self, isolated, monkeypatch):
        monkeypatch.setattr(
            load_config,
            "CONFIG_TOML",
            {"common": {"importCommon": "shared.toml", "namespace": "local"}},
        )
        monkeypatch.setattr(load_config, "CONFIG_FILE", "my.toml")
        monkeypatch.setattr(load_config, "CONFIG_FILE_DIR", "")
        monkeypatch.setattr(
            load_config,
            "import_toml",
            lambda name: {"key": "k", "secret": "s", "namespace": "shared"},
        )
        monkeypatch.setattr(load_config, "_ARGS", _args())
        load_config.load_config_common()
        assert load_config.CONFIG_SOURCES["key"] == "config file (shared.toml)"
        # a local value supersedes the imported one, and is sourced locally
        assert load_config.CONFIG_SOURCES["namespace"] == "config file (my.toml)"

    def test_explicit_config_file_beats_environment(self, isolated, monkeypatch):
        monkeypatch.setattr(
            load_config,
            "CONFIG_TOML",
            {"common": {"key": "k", "secret": "s", "namespace": "file-ns"}},
        )
        monkeypatch.setattr(load_config, "CONFIG_FILE", "my.toml")
        monkeypatch.setattr(
            load_config, "config_file_explicitly_selected", lambda: True
        )
        monkeypatch.setenv(YD_NAMESPACE, "env-ns")
        monkeypatch.setattr(load_config, "_ARGS", _args())
        cfg = load_config.load_config_common()
        assert cfg.namespace == "file-ns"
        assert load_config.CONFIG_SOURCES["namespace"] == "config file (my.toml)"


class TestStrict:
    def test_strict_exits_on_missing_key(self, isolated, monkeypatch):
        monkeypatch.setattr(load_config, "_ARGS", _args())
        with pytest.raises(SystemExit):
            load_config.load_config_common()

    def test_lenient_returns_none_for_missing_key_and_secret(
        self, isolated, monkeypatch
    ):
        monkeypatch.setattr(load_config, "_ARGS", _args())
        cfg = load_config.load_config_common(strict=False)
        assert cfg.key is None and cfg.secret is None
        assert cfg.namespace == "default"
        assert load_config.CONFIG_SOURCES["key"] == "not set"


class TestCommonValuesAreText:
    @pytest.mark.parametrize("name, value", [("tag", 2026), ("namespace", True)])
    def test_a_value_that_is_not_text_exits_3(self, isolated, monkeypatch, name, value):
        # 'tag = 2026' is a number to TOML: refused as the configuration is
        # read, not failing where a name is built from it
        from yellowdog_cli.utils.exit_codes import ExitCode

        monkeypatch.setattr(
            load_config,
            "CONFIG_TOML",
            {"common": {"key": "k", "secret": "s", name: value}},
        )
        errors: list[str] = []
        monkeypatch.setattr(load_config, "print_error", errors.append)
        monkeypatch.setattr(load_config, "_ARGS", _args())
        with pytest.raises(SystemExit) as exited:
            load_config.load_config_common()
        assert exited.value.code == ExitCode.CONFIGURATION
        assert f"'common.{name}' must be text" in errors[0]

    def test_without_strict_it_is_taken_as_its_text(self, isolated, monkeypatch):
        # yd-doctor reports the configuration rather than exiting on it
        monkeypatch.setattr(load_config, "CONFIG_TOML", {"common": {"tag": 2026}})
        monkeypatch.setattr(load_config, "_ARGS", _args())
        assert load_config.load_config_common(strict=False).name_tag == "2026"


class TestReadTimeout:
    """
    [common] readTimeout: seconds to wait for a Platform response, from the
    environment (YD_READ_TIMEOUT) or the file in the usual order; 90 if
    unset, and 0 for no limit.
    """

    def _load(self, monkeypatch, common: dict, explicit: bool = False):
        monkeypatch.setattr(
            load_config,
            "CONFIG_TOML",
            {"common": {"key": "k", "secret": "s", **common}},
        )
        monkeypatch.setattr(load_config, "CONFIG_FILE", "my.toml")
        monkeypatch.setattr(
            load_config, "config_file_explicitly_selected", lambda: explicit
        )
        monkeypatch.setattr(load_config, "_ARGS", _args())
        return load_config.load_config_common()

    def test_unset_is_the_default(self, isolated, monkeypatch):
        assert self._load(monkeypatch, {}).read_timeout == 90.0
        assert load_config.CONFIG_SOURCES["readTimeout"] == "default"

    def test_the_file_sets_it(self, isolated, monkeypatch):
        assert self._load(monkeypatch, {"readTimeout": 120}).read_timeout == 120.0
        assert load_config.CONFIG_SOURCES["readTimeout"] == "config file (my.toml)"

    def test_the_environment_beats_the_file(self, isolated, monkeypatch):
        monkeypatch.setenv("YD_READ_TIMEOUT", "45.5")
        assert self._load(monkeypatch, {"readTimeout": 120}).read_timeout == 45.5

    def test_an_explicit_file_beats_the_environment(self, isolated, monkeypatch):
        monkeypatch.setenv("YD_READ_TIMEOUT", "45")
        cfg = self._load(monkeypatch, {"readTimeout": 120}, explicit=True)
        assert cfg.read_timeout == 120.0

    def test_zero_is_no_limit(self, isolated, monkeypatch):
        assert self._load(monkeypatch, {"readTimeout": 0}).read_timeout is None

    def test_the_request_timeout_pairs_it_with_the_connect_timeout(
        self, isolated, monkeypatch
    ):
        cfg = self._load(monkeypatch, {"readTimeout": 30})
        assert cfg.request_timeout == (10.0, 30.0)
        assert self._load(monkeypatch, {"readTimeout": 0}).request_timeout == (
            10.0,
            None,
        )

    @pytest.mark.parametrize("value", [-1, "soon", True, float("inf")])
    def test_anything_else_is_a_configuration_error(self, isolated, monkeypatch, value):
        with pytest.raises(SystemExit) as exited:
            self._load(monkeypatch, {"readTimeout": value})
        assert exited.value.code == 3

    def test_a_bad_environment_value_is_a_configuration_error(
        self, isolated, monkeypatch
    ):
        monkeypatch.setenv("YD_READ_TIMEOUT", "ninety")
        with pytest.raises(SystemExit) as exited:
            self._load(monkeypatch, {})
        assert exited.value.code == 3
