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
    for var in (YD_KEY, YD_SECRET, YD_NAMESPACE, "YD_TAG", "YD_URL"):
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
        monkeypatch.setattr(
            load_config, "ARGS_PARSER", _args(key="cli-key", secret="s")
        )
        cfg = load_config.load_config_common()
        assert cfg.key == "cli-key"
        assert load_config.CONFIG_SOURCES["key"] == "command line"
        assert load_config.CONFIG_SOURCES["secret"] == "command line"

    def test_environment_names_the_variable(self, isolated, monkeypatch):
        monkeypatch.setenv(YD_KEY, "env-key")
        monkeypatch.setenv(YD_SECRET, "env-secret")
        monkeypatch.setattr(load_config, "ARGS_PARSER", _args())
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
        monkeypatch.setattr(load_config, "ARGS_PARSER", _args())
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
        monkeypatch.setattr(load_config, "ARGS_PARSER", _args())
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
        monkeypatch.setattr(load_config, "ARGS_PARSER", _args())
        cfg = load_config.load_config_common()
        assert cfg.namespace == "file-ns"
        assert load_config.CONFIG_SOURCES["namespace"] == "config file (my.toml)"


class TestStrict:
    def test_strict_exits_on_missing_key(self, isolated, monkeypatch):
        monkeypatch.setattr(load_config, "ARGS_PARSER", _args())
        with pytest.raises(SystemExit):
            load_config.load_config_common()

    def test_lenient_returns_none_for_missing_key_and_secret(
        self, isolated, monkeypatch
    ):
        monkeypatch.setattr(load_config, "ARGS_PARSER", _args())
        cfg = load_config.load_config_common(strict=False)
        assert cfg.key is None and cfg.secret is None
        assert cfg.namespace == "default"
        assert load_config.CONFIG_SOURCES["key"] == "not set"
