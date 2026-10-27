"""
A configuration file chosen with '--config' outranks the environment, so a
value the environment offered for the same setting is passed over. That is
made visible, by name and never by value: once each under --debug, and in
yd-doctor's 'Environment outranked' row. Recorded for the '[common]'
properties, the '[dataClient]' fields and the YD_VAR_* variables; not where
the two agree, not without '--config', and not where the file would have won
anyway (a profile's own field, a '--property' override).
"""

import json
import os
import subprocess
import sys
from unittest.mock import MagicMock

import pytest

import yellowdog_cli.utils.variable_substitution as var_module
from yellowdog_cli.utils import doctor_checks, load_config
from yellowdog_cli.utils.doctor_checks import Status
from yellowdog_cli.utils.settings import (
    YD_DATA_CLIENT_BUCKET,
    YD_KEY,
    YD_NAMESPACE,
    YD_SECRET,
)


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
    monkeypatch.setattr(load_config, "CONFIG_SOURCES", {})
    monkeypatch.setattr(load_config, "ENVIRONMENT_OUTRANKED", {})
    monkeypatch.setattr(load_config, "CONFIG_FILE", "chosen.toml")
    for var in (YD_KEY, YD_SECRET, YD_NAMESPACE, "YD_TAG", "YD_URL", "YD_READ_TIMEOUT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(
        load_config, "add_substitutions_without_overwriting", lambda subs: None
    )
    monkeypatch.setattr(load_config, "register_dc_substitutions", lambda: None)
    monkeypatch.setattr(load_config, "_ARGS", _args())
    debug = MagicMock()
    monkeypatch.setattr(load_config, "print_debug", debug)
    return debug


def _load_common(monkeypatch, explicit: bool, **common) -> None:
    monkeypatch.setattr(
        load_config,
        "CONFIG_TOML",
        {"common": {"key": "k", "secret": "s", **common}},
    )
    monkeypatch.setattr(
        load_config, "config_file_explicitly_selected", lambda: explicit
    )
    load_config.load_config_common()


class TestCommon:
    def test_an_outranked_value_is_recorded_and_said_by_name(
        self, isolated, monkeypatch
    ):
        monkeypatch.setenv(YD_NAMESPACE, "env-ns")
        _load_common(monkeypatch, True, namespace="file-ns")
        assert load_config.ENVIRONMENT_OUTRANKED == {"common.namespace": YD_NAMESPACE}
        [message] = [
            str(call.args[0])
            for call in isolated.call_args_list
            if "rather than" in str(call.args[0])
        ]
        assert "'common.namespace'" in message and YD_NAMESPACE in message
        assert "env-ns" not in message and "file-ns" not in message

    def test_a_secret_is_named_never_shown(self, isolated, monkeypatch):
        monkeypatch.setenv(YD_SECRET, "env-secret-value")
        _load_common(monkeypatch, True)
        assert load_config.ENVIRONMENT_OUTRANKED == {"common.secret": YD_SECRET}
        said = " ".join(str(call.args[0]) for call in isolated.call_args_list)
        assert "env-secret-value" not in said and "'s'" not in said

    def test_agreeing_values_are_not_recorded(self, isolated, monkeypatch):
        monkeypatch.setenv(YD_NAMESPACE, "same")
        _load_common(monkeypatch, True, namespace="same")
        assert load_config.ENVIRONMENT_OUTRANKED == {}

    def test_without_config_the_environment_wins_and_nothing_is_recorded(
        self, isolated, monkeypatch
    ):
        monkeypatch.setenv(YD_NAMESPACE, "env-ns")
        _load_common(monkeypatch, False, namespace="file-ns")
        assert load_config.ENVIRONMENT_OUTRANKED == {}

    def test_namespace_and_tag_without_the_common_load(self, isolated, monkeypatch):
        # The data client commands' way: no key or secret needed
        monkeypatch.setenv(YD_NAMESPACE, "env-ns")
        monkeypatch.setenv("YD_TAG", "env-tag")
        monkeypatch.setattr(
            load_config, "CONFIG_TOML", {"common": {"namespace": "ns", "tag": "tg"}}
        )
        monkeypatch.setattr(
            load_config, "config_file_explicitly_selected", lambda: True
        )
        monkeypatch.setattr(load_config, "_set_by_property_override", lambda *a: False)
        load_config._load_namespace_and_tag()
        assert load_config.ENVIRONMENT_OUTRANKED == {
            "common.namespace": YD_NAMESPACE,
            "common.tag": "YD_TAG",
        }


class TestDataClient:
    def _value(
        self, monkeypatch, explicit: bool, profile_keys=frozenset(), overridden=False
    ):
        monkeypatch.setattr(
            load_config, "config_file_explicitly_selected", lambda: explicit
        )
        monkeypatch.setattr(
            load_config, "_set_by_property_override", lambda *a: overridden
        )
        monkeypatch.setenv(YD_DATA_CLIENT_BUCKET, "env-bucket")
        return load_config._data_client_value(
            {"bucket": "file-bucket"},
            "prod" if profile_keys else None,
            set(profile_keys),
            "bucket",
            YD_DATA_CLIENT_BUCKET,
        )

    def test_an_outranked_field_is_recorded(self, isolated, monkeypatch):
        assert self._value(monkeypatch, True) == "file-bucket"
        assert load_config.ENVIRONMENT_OUTRANKED == {
            "dataClient.bucket": YD_DATA_CLIENT_BUCKET
        }

    def test_without_config_nothing_is_recorded(self, isolated, monkeypatch):
        assert self._value(monkeypatch, False) == "env-bucket"
        assert load_config.ENVIRONMENT_OUTRANKED == {}

    @pytest.mark.parametrize(
        "kwargs", [{"profile_keys": {"bucket"}}, {"overridden": True}]
    )
    def test_a_field_that_wins_anyway_is_not_put_down_to_config(
        self, isolated, monkeypatch, kwargs
    ):
        # A profile's own field, or a '--property' one, outranks the
        # environment with or without '--config'
        assert self._value(monkeypatch, True, **kwargs) == "file-bucket"
        assert load_config.ENVIRONMENT_OUTRANKED == {}


class TestVariables:
    @pytest.fixture
    def table(self, monkeypatch):
        monkeypatch.setattr(var_module, "VARIABLE_SUBSTITUTIONS", {})
        monkeypatch.setattr(var_module, "_DEFINITIONS", {})
        monkeypatch.setattr(var_module, "CLI_DEFINED_VARIABLES", set())
        monkeypatch.setattr(
            var_module, "_ENVIRONMENT_DEFINED_VARIABLES", {"site", "same"}
        )
        monkeypatch.setattr(var_module, "_CONFIG_FILE_VARIABLES", set())
        monkeypatch.setattr(var_module, "_ENVIRONMENT_VARIABLES_OUTRANKED", set())
        monkeypatch.setenv("YD_VAR_site", "par")
        monkeypatch.setenv("YD_VAR_same", "x")
        debug = MagicMock()
        monkeypatch.setattr(var_module, "print_debug", debug)
        return debug

    def test_an_outranked_variable_is_recorded_and_said_by_name(
        self, table, monkeypatch
    ):
        monkeypatch.setattr(var_module, "_CONFIG_FILE_SELECTED", True)
        var_module.add_substitutions_from_config_file(
            {"site": "lon", "same": "x"}, selected_file=True
        )
        assert var_module.environment_variables_outranked() == ["site"]
        [message] = [str(call.args[0]) for call in table.call_args_list]
        assert "'site'" in message and "YD_VAR_site" in message
        assert "lon" not in message and "par" not in message

    def test_without_config_the_environment_wins_and_nothing_is_recorded(
        self, table, monkeypatch
    ):
        monkeypatch.setattr(var_module, "_CONFIG_FILE_SELECTED", False)
        var_module.add_substitutions_from_config_file(
            {"site": "lon"}, selected_file=True
        )
        assert var_module.environment_variables_outranked() == []


class TestDoctorRow:
    def test_none(self, monkeypatch):
        monkeypatch.setattr(load_config, "ENVIRONMENT_OUTRANKED", {})
        monkeypatch.setattr(var_module, "_ENVIRONMENT_VARIABLES_OUTRANKED", set())
        result = doctor_checks.check_environment_outranked(MagicMock())
        assert (result.status, result.detail) == (Status.OK, "none")

    def test_each_is_named_with_what_it_would_have_set(self, monkeypatch):
        monkeypatch.setattr(load_config, "CONFIG_FILE", "chosen.toml")
        monkeypatch.setattr(
            load_config,
            "ENVIRONMENT_OUTRANKED",
            {
                "common.namespace": YD_NAMESPACE,
                "dataClient.bucket": YD_DATA_CLIENT_BUCKET,
            },
        )
        monkeypatch.setattr(var_module, "_ENVIRONMENT_VARIABLES_OUTRANKED", {"site"})
        result = doctor_checks.check_environment_outranked(MagicMock())
        assert result.status == Status.WARN
        assert result.detail == (
            "'chosen.toml', chosen with --config, is used rather than"
            f" {YD_NAMESPACE} (common.namespace),"
            f" {YD_DATA_CLIENT_BUCKET} (dataClient.bucket), YD_VAR_site (variable 'site')"
        )
        assert result.remedy is not None and "--config" in result.remedy


CONFIG = """\
[common]
key = "file-key"
secret = "file-secret"
namespace = "file-ns"
tag = "same-tag"

[common.variables]
SITE = "lon"
"""


def _doctor(tmp_path, *args: str) -> dict:
    """
    'yd doctor --offline --json' in tmp_path, with the environment offering
    a different namespace, secret and 'SITE', and the same tag, and the
    shell's own YD_* variables dropped. The variable is upper-case because
    Windows upper-cases environment variable names, so 'YD_VAR_site' would
    define 'SITE' there and outrank nothing.
    """
    (tmp_path / "config.toml").write_text(CONFIG, encoding="utf-8")
    environment = {k: v for k, v in os.environ.items() if not k.startswith("YD_")}
    environment.update(
        YD_NAMESPACE="env-ns",
        YD_SECRET="env-secret",
        YD_TAG="same-tag",
        YD_VAR_SITE="par",
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "yellowdog_cli.yd",
            "doctor",
            "--offline",
            "--json",
            *args,
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert "env-secret" not in completed.stdout + completed.stderr
    assert "file-secret" not in completed.stdout + completed.stderr
    return {row["check"]: row for row in json.loads(completed.stdout)}


class TestDoctor:
    def test_with_config(self, tmp_path):
        row = _doctor(tmp_path, "-c", "config.toml")["Environment outranked"]
        assert row["status"] == "WARN"
        assert row["detail"] == (
            "'config.toml', chosen with --config, is used rather than"
            " YD_NAMESPACE (common.namespace), YD_SECRET (common.secret),"
            " YD_VAR_SITE (variable 'SITE')"
        )

    def test_without_config(self, tmp_path):
        row = _doctor(tmp_path)["Environment outranked"]
        assert (row["status"], row["detail"]) == ("OK", "none")
