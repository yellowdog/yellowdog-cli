"""
utils/load_config.py's error exits: a configuration that cannot be used is
reported, naming what is wrong, and exits 3 (ExitCode.CONFIGURATION) before
the command starts; under '--debug', a failure the loader cannot name is
raised instead, so its traceback shows. Each test drives one loader with the
module's state patched, and restored after it.
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

from yellowdog_cli.utils import load_config, output_settings
from yellowdog_cli.utils import variable_substitution as variable_substitution_module
from yellowdog_cli.utils.exit_codes import ExitCode


def _args(**values) -> MagicMock:
    args = MagicMock()
    args.config_file = values.get("config_file")
    args.no_config = False
    args.property_overrides = values.get("property_overrides")
    args.data_client_profile = values.get("data_client_profile")
    return args


@pytest.fixture
def loading(monkeypatch, tmp_path):
    """
    The loader's module state, restored after the test; the messages it
    prints are returned. The working directory is the test's own.
    """
    monkeypatch.chdir(tmp_path)
    for name in (
        "CONFIG_FILE",
        "CONFIG_FILE_DIR",
        "CONFIG_TOML",
        "_CONFIG_AS_WRITTEN",
        "_NO_FILE_REASON",
    ):
        monkeypatch.setattr(load_config, name, getattr(load_config, name))
    substitutions = dict(variable_substitution_module.VARIABLE_SUBSTITUTIONS)
    errors: list[str] = []
    monkeypatch.setattr(load_config, "print_error", lambda e: errors.append(str(e)))
    yield errors
    variable_substitution_module.VARIABLE_SUBSTITUTIONS.clear()
    variable_substitution_module.VARIABLE_SUBSTITUTIONS.update(substitutions)


def _exits_3(call) -> None:
    with pytest.raises(SystemExit) as exited:
        call()
    assert exited.value.code == ExitCode.CONFIGURATION


def _load(monkeypatch, **args) -> None:
    monkeypatch.setattr(load_config, "_ARGS", _args(**args))
    load_config._load_config_file()


class TestTheConfigurationFile:
    def test_an_explicit_file_that_does_not_exist_exits_3(self, loading, monkeypatch):
        _exits_3(lambda: _load(monkeypatch, config_file="missing.toml"))
        assert "missing.toml" in loading[0]

    def test_no_file_when_none_was_named_is_no_error(self, loading, monkeypatch):
        # config.toml is looked for, and its absence means the command line
        # and environment supply the configuration
        _load(monkeypatch)
        assert loading == []
        assert load_config.CONFIG_TOML == {"common": {}}

    def test_a_malformed_file_exits_3_naming_it(self, loading, monkeypatch, tmp_path):
        (tmp_path / "bad.toml").write_text("[common\nkey = ", encoding="utf-8")
        _exits_3(lambda: _load(monkeypatch, config_file="bad.toml"))
        assert "Unable to load configuration data from 'bad.toml'" in loading[0]

    @pytest.mark.skipif(
        sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
        reason="file permissions are not enforced here",
    )
    def test_an_unreadable_file_exits_3_naming_it(self, loading, monkeypatch, tmp_path):
        unreadable = tmp_path / "locked.toml"
        unreadable.write_text("[common]\n", encoding="utf-8")
        unreadable.chmod(0)
        try:
            _exits_3(lambda: _load(monkeypatch, config_file="locked.toml"))
        finally:
            unreadable.chmod(0o600)
        assert "Unable to load configuration data from 'locked.toml'" in loading[0]

    def test_an_unknown_property_exits_3(self, loading, monkeypatch, tmp_path):
        (tmp_path / "typo.toml").write_text(
            '[common]\nnamespce = "ns"\n', encoding="utf-8"
        )
        _exits_3(lambda: _load(monkeypatch, config_file="typo.toml"))
        assert "namespce" in loading[0]

    def test_an_unknown_property_is_raised_under_debug(
        self, loading, monkeypatch, tmp_path
    ):
        (tmp_path / "typo.toml").write_text(
            '[common]\nnamespce = "ns"\n', encoding="utf-8"
        )
        monkeypatch.setattr(output_settings.OUTPUT, "debug", True)
        with pytest.raises(Exception, match="namespce"):
            _load(monkeypatch, config_file="typo.toml")

    def test_any_other_failure_reading_it_exits_3(self, loading, monkeypatch, tmp_path):
        (tmp_path / "config.toml").write_text("[common]\n", encoding="utf-8")

        def fails(_filename):
            raise RuntimeError("the loader's own fault")

        monkeypatch.setattr(
            load_config, "load_toml_file_with_variable_substitutions", fails
        )
        _exits_3(lambda: _load(monkeypatch))
        assert loading == ["the loader's own fault"]

    def test_any_other_failure_is_raised_under_debug(
        self, loading, monkeypatch, tmp_path
    ):
        (tmp_path / "config.toml").write_text("[common]\n", encoding="utf-8")

        def fails(_filename):
            raise RuntimeError("the loader's own fault")

        monkeypatch.setattr(
            load_config, "load_toml_file_with_variable_substitutions", fails
        )
        monkeypatch.setattr(output_settings.OUTPUT, "debug", True)
        with pytest.raises(RuntimeError, match="own fault"):
            _load(monkeypatch)


class TestOverridesAndImports:
    def test_a_property_override_naming_a_bad_variable_exits_3(self, loading):
        _exits_3(
            lambda: load_config._apply_property_overrides(
                {"common": {}}, ["common.variables.key=x"]
            )
        )
        assert "key" in loading[0]

    def test_an_imported_common_file_that_does_not_exist_exits_3(
        self, loading, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(load_config, "CONFIG_FILE_DIR", str(tmp_path))
        _exits_3(lambda: load_config.import_toml("absent.toml"))
        assert "Unable to load imported common configuration data" in loading[0]


class TestDataClientProfiles:
    @pytest.fixture
    def profiles(self, loading, monkeypatch):
        monkeypatch.setattr(
            load_config,
            "CONFIG_TOML",
            {"common": {}, "dataClient": {"remote": "r", "work": {"bucket": "b"}}},
        )
        monkeypatch.setattr(load_config, "_load_namespace_and_tag", lambda: None)
        monkeypatch.setattr(load_config, "register_dc_substitutions", lambda: None)
        monkeypatch.delenv("YD_DATA_CLIENT", raising=False)
        return loading

    def test_an_unknown_profile_on_the_command_line_exits_3(
        self, profiles, monkeypatch
    ):
        monkeypatch.setattr(load_config, "_ARGS", _args(data_client_profile="nope"))
        _exits_3(load_config.load_config_data_client)
        assert "nope" in profiles[0]

    def test_an_unknown_destination_profile_exits_3(self, profiles, monkeypatch):
        monkeypatch.setattr(load_config, "_ARGS", _args())
        _exits_3(lambda: load_config.load_config_data_client_for_profile("nope"))
        assert "nope" in profiles[0]


class TestDataClientProfileNames:
    def test_a_profile_name_no_variable_could_have_exits_3(self, loading, monkeypatch):
        # A profile's name is part of its variables' names
        monkeypatch.setattr(
            load_config,
            "CONFIG_TOML",
            {"common": {}, "dataClient": {"remote": "r", "bad name": {"bucket": "b"}}},
        )
        monkeypatch.setattr(
            variable_substitution_module,
            "VARIABLE_SUBSTITUTIONS",
            dict(variable_substitution_module.VARIABLE_SUBSTITUTIONS),
        )
        _exits_3(load_config.register_dc_substitutions)
        assert "bad name" in loading[0]


class TestSectionsOfTheWrongShape:
    def test_a_work_requirement_property_of_the_wrong_type_exits_3(
        self, loading, monkeypatch
    ):
        monkeypatch.setattr(
            load_config, "CONFIG_TOML", {"workRequirement": {"workerTags": "one-tag"}}
        )
        monkeypatch.setattr(load_config, "_ARGS", _args())
        _exits_3(load_config.load_config_work_requirement)
        assert "workerTags" in loading[0]

    def test_a_worker_pool_property_of_the_wrong_type_exits_3(
        self, loading, monkeypatch
    ):
        monkeypatch.setattr(load_config, "CONFIG_TOML", {"workerPool": {"name": 123}})
        monkeypatch.setattr(load_config, "_ARGS", _args())
        _exits_3(load_config.load_config_worker_pool)
        assert "name" in loading[0]

    def test_either_is_raised_under_debug(self, loading, monkeypatch):
        monkeypatch.setattr(load_config, "CONFIG_TOML", {"workerPool": {"name": 123}})
        monkeypatch.setattr(load_config, "_ARGS", _args())
        monkeypatch.setattr(output_settings.OUTPUT, "debug", True)
        with pytest.raises(TypeError):
            load_config.load_config_worker_pool()


class TestTheCommandLineWithoutTheFileOrSection:
    """
    The command line is applied whatever the file holds: '--property' with
    no configuration file at all, and yd-submit's -C, -G, -T and -b with no
    [workRequirement] section in it, were ignored without a word.
    """

    def test_a_property_override_applies_with_no_file(self, loading, monkeypatch):
        _load(
            monkeypatch,
            property_overrides=["workRequirement.taskCount=3", "common.namespace=ns"],
        )
        assert load_config.CONFIG_TOML == {
            "common": {"namespace": "ns"},
            "workRequirement": {"taskCount": 3},
        }

    def test_the_task_options_apply_with_no_section(self, loading, monkeypatch):
        args = _args()
        args.task_count = 5
        args.task_group_count = 3
        args.task_type = "docker"
        args.task_batch_size = 7
        monkeypatch.setattr(load_config, "_ARGS", args)
        monkeypatch.setattr(load_config, "CONFIG_TOML", {"common": {}})
        config_wr = load_config.load_config_work_requirement()
        assert (
            config_wr.task_count,
            config_wr.task_group_count,
            config_wr.task_type,
            config_wr.task_batch_size,
        ) == (5, 3, "docker", 7)


class TestAMissingCredentialSaysWhy:
    """
    "Missing configuration data: 'key'" left the user to discover, with
    --debug, that no configuration file had been found at all.
    """

    @staticmethod
    def _common_args(**values) -> MagicMock:
        args = _args(**values)
        for name in ("key", "secret", "namespace", "tag", "url"):
            setattr(args, name, None)
        args.use_pac = False
        return args

    def test_no_file_found_is_said_with_where_else_to_give_it(
        self, loading, monkeypatch
    ):
        for name in ("YD_KEY", "YD_SECRET", "YD_API_KEY_ID", "YD_API_KEY_SECRET"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(load_config, "_ARGS", self._common_args())
        load_config._load_config_file()
        _exits_3(load_config.load_config_common)
        message = loading[-1]
        assert "Missing configuration data: 'key'" in message
        assert "no configuration file" in message and "config.toml" in message
        assert "--key" in message and "YD_KEY" in message

    @pytest.mark.parametrize("url", ["api.yellowdog.ai", "not a url", "ftp://x"])
    def test_a_url_without_http_is_a_configuration_error(
        self, loading, monkeypatch, url
    ):
        # It reached requests, which failed with 'No connection adapters were
        # found' and exit 1
        args = self._common_args()
        args.key, args.secret, args.url = "k", "s", url
        monkeypatch.setattr(load_config, "_ARGS", args)
        load_config._load_config_file()
        _exits_3(load_config.load_config_common)
        assert f"'{url}'" in loading[-1] and "https://" in loading[-1]
