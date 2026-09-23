"""
Warnings for undefined variables in what the data walk never sees.

resolve_variables_insitu() reports undefined variables in the specifications
and configuration sections it walks (see test_variable_subs.py). These are the
places substituted some other way, each of which checks its own result:

  - the configuration values resolved one string at a time at import -- the
    '[common]' namespace, tag and URL and the '[dataClient]' remote, bucket and
    prefix, profiles included -- checked by both command wrappers as a command
    starts;
  - file contents substituted as text: User Data files, 'yd-nodeaction'
    'writeFile' content files, and Task Data files;
  - the paths the data client commands are given.
"""

from unittest.mock import MagicMock

import pytest

import yellowdog_cli.utils.load_config as lc_module
import yellowdog_cli.utils.variables as var_module
from yellowdog_cli.utils.config_types import ConfigDataClient, ConfigWorkerPool
from yellowdog_cli.utils.dataclient_utils import resolve_remote_path
from yellowdog_cli.utils.property_names import TASK_DATA_FILE, TASK_DATA_FILES
from yellowdog_cli.utils.provision_utils import get_user_data_property
from yellowdog_cli.utils.submit_utils import resolve_task_data


@pytest.fixture()
def warnings(monkeypatch) -> MagicMock:
    monkeypatch.setattr(var_module, "_UNDEFINED_VARIABLE_WARNINGS", True)
    monkeypatch.setattr(var_module, "_UNDEFINED_VARIABLES_REPORTED", set())
    warning = MagicMock()
    monkeypatch.setattr(var_module, "print_warning", warning)
    return warning


def _messages(warning: MagicMock) -> list[str]:
    return [str(call.args[0]) for call in warning.call_args_list]


# ---------------------------------------------------------------------------
# Configuration values resolved at import
# ---------------------------------------------------------------------------


class TestConfigValues:
    @pytest.fixture(autouse=True)
    def table(self, monkeypatch):
        # load_config holds the table by reference, so it is edited in place
        subs = var_module.VARIABLE_SUBSTITUTIONS
        for name in list(subs):
            if name.startswith("dataClient."):
                monkeypatch.delitem(subs, name)
        monkeypatch.setitem(subs, "namespace", "ns")
        monkeypatch.setitem(subs, "tag", "tg")
        monkeypatch.setitem(subs, "url", "https://example.com")

    def test_common_values_are_checked(self, warnings, monkeypatch):
        monkeypatch.setitem(var_module.VARIABLE_SUBSTITUTIONS, "tag", "t-{{nope}}")
        lc_module.warn_of_undefined_config_variables()
        [message] = _messages(warnings)
        assert "'{{nope}}'" in message and "'common.tag'" in message

    def test_data_client_values_are_checked(self, warnings, monkeypatch):
        monkeypatch.setitem(
            var_module.VARIABLE_SUBSTITUTIONS, "dataClient.prod.bucket", "{{nope}}"
        )
        lc_module.warn_of_undefined_config_variables()
        [message] = _messages(warnings)
        assert "'dataClient.prod.bucket'" in message

    def test_credentials_are_not_checked(self, warnings, monkeypatch):
        # Their text is never put in a warning, and a wrong one fails anyway
        monkeypatch.setitem(var_module.VARIABLE_SUBSTITUTIONS, "key", "{{nope}}")
        monkeypatch.setitem(var_module.VARIABLE_SUBSTITUTIONS, "secret", "{{nope}}")
        lc_module.warn_of_undefined_config_variables()
        assert _messages(warnings) == []

    def test_nothing_to_report(self, warnings):
        lc_module.warn_of_undefined_config_variables()
        assert _messages(warnings) == []


class TestWrappersCheckConfigValues:
    """Both wrappers check the configuration values once warnings are on."""

    @staticmethod
    def _run(wrapped, module, monkeypatch) -> list[bool]:
        seen: list[bool] = []
        monkeypatch.setattr(var_module, "_UNDEFINED_VARIABLE_WARNINGS", False)
        monkeypatch.setattr(
            module,
            "warn_of_undefined_config_variables",
            lambda: seen.append(var_module._UNDEFINED_VARIABLE_WARNINGS),
        )
        with pytest.raises(SystemExit):
            wrapped(lambda: None)()
        return seen

    def test_main_wrapper(self, monkeypatch):
        import yellowdog_cli.utils.wrapper as wrapper_module

        monkeypatch.setattr(wrapper_module, "set_proxy", lambda: None)
        monkeypatch.setattr(wrapper_module, "CLIENT", MagicMock())
        seen = self._run(wrapper_module.main_wrapper, wrapper_module, monkeypatch)
        assert seen == [True]

    def test_dataclient_wrapper(self, monkeypatch):
        import yellowdog_cli.utils.dataclient_wrapper as dcw_module

        seen = self._run(dcw_module.dataclient_wrapper, dcw_module, monkeypatch)
        assert seen == [True]


# ---------------------------------------------------------------------------
# File contents substituted as text
# ---------------------------------------------------------------------------


class TestUserDataFiles:
    def test_undefined_variable_is_reported_by_file(self, warnings, tmp_path):
        script = tmp_path / "setup.sh"
        script.write_text("echo __{{nope}}__ {{mustache_for_the_platform}}\n")
        get_user_data_property(ConfigWorkerPool(user_data_file=str(script)))
        [message] = _messages(warnings)
        assert "'__{{nope}}__'" in message and "setup.sh" in message

    def test_concatenated_files_are_reported(self, warnings, tmp_path):
        a, b = tmp_path / "a.sh", tmp_path / "b.sh"
        a.write_text("echo a\n")
        b.write_text("echo __{{nope}}__\n")
        get_user_data_property(ConfigWorkerPool(user_data_files=[str(a), str(b)]))
        [message] = _messages(warnings)
        assert "a.sh" in message and "b.sh" in message


class TestNodeActionContentFiles:
    @pytest.mark.parametrize("prop", ["contentFile", "contentFiles"])
    def test_undefined_variable_is_reported(self, warnings, tmp_path, prop):
        from yellowdog_cli.nodeaction import _parse_action

        content = tmp_path / "payload.txt"
        content.write_text("value=__{{nope}}__ {{mustache}}\n")
        value = str(content) if prop == "contentFile" else [str(content)]
        _parse_action({"type": "writeFile", "path": "/tmp/x", prop: value}, ".")
        [message] = _messages(warnings)
        assert "'__{{nope}}__'" in message and "payload.txt" in message


class TestTaskDataFiles:
    @pytest.mark.parametrize("prop", [TASK_DATA_FILE, TASK_DATA_FILES])
    def test_undefined_variable_is_reported(self, warnings, tmp_path, prop):
        data = tmp_path / "input.json"
        data.write_text('{"region": "{{nope}}", "format": "{{.ID}}"}\n')
        value = str(data) if prop == TASK_DATA_FILE else [str(data)]
        resolve_task_data({prop: value})
        [message] = _messages(warnings)
        assert "'{{nope}}'" in message and "input.json" in message


# ---------------------------------------------------------------------------
# Data client paths
# ---------------------------------------------------------------------------


class TestDataClientPaths:
    @pytest.mark.parametrize("arg", ["relative_path", "filename"])
    def test_undefined_variable_is_reported(self, warnings, arg):
        resolve_remote_path(ConfigDataClient(remote="r"), **{arg: "x/{{nope}}"})
        [message] = _messages(warnings)
        assert "'{{nope}}'" in message and "x/{{nope}}" in message


class TestDataClientPathChains:
    def test_a_chain_resolves_and_is_not_reported(self, warnings, monkeypatch):
        monkeypatch.setenv("YD_TEST_A", "{{env:YD_TEST_B}}")
        monkeypatch.setenv("YD_TEST_B", "data")
        path = resolve_remote_path(
            ConfigDataClient(remote="r"), relative_path="{{env:YD_TEST_A}}/x"
        )
        assert path.endswith("data/x")
        assert _messages(warnings) == []
