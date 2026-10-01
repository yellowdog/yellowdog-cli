"""
The rule for variable names, and where it is enforced.

A variable name starts with a letter, digit or '_', and continues with
letters, digits, '_', '.' and '-' (VARIABLE_NAME_PATTERN in settings.py). A
name that breaks the rule is an error wherever a variable is defined -- '-v',
'YD_VAR_*' environment variables, '[common.variables]' and '--property
common.variables.<name>' -- and the same rule decides what a '{{...}}'
expression refers to: one whose name breaks it is text, never a variable, so
the undefined-variable warning and the circular-reference check cover every
reference there is. An 'env:' name belongs to the operating system, and may be
anything but whitespace and the substitution syntax.

The variables the CLI defines from its own configuration -- 'namespace', 'tag',
'key', 'secret' and 'url' (RESERVED_VARIABLE_NAMES) -- are an error at those
same user sources: defined as a variable, only '{{name}}' would change and not
the value the command acts on, and one unset with '{{::}}' would be defined
again from the configuration. The CLI's own registration of them is unaffected.
"""

import os
import subprocess
from unittest.mock import MagicMock

import pytest

import yellowdog_cli.utils.variable_substitution as var_module
from yellowdog_cli.utils.settings import RESERVED_VARIABLE_NAMES, ExitCode

VALID = ["a", "A1", "_x", "9lives", "42", "my-var", "dataClient.1.remote", "a.b-c_d"]
INVALID = ["", "my var", ".ID", "-x", "a:b", "num:x", "a}}b", "a=b", "a{b", "é"]


@pytest.fixture()
def subs(monkeypatch):
    monkeypatch.setattr(var_module, "VARIABLE_SUBSTITUTIONS", {"myvar": "hello"})


class TestTheRule:
    @pytest.mark.parametrize("name", VALID)
    def test_valid(self, name):
        var_module.check_variable_name(name, "somewhere")

    @pytest.mark.parametrize("name", INVALID)
    def test_invalid(self, name):
        with pytest.raises(ValueError, match="Invalid variable name") as exc:
            var_module.check_variable_name(name, "somewhere")
        assert repr(name) in str(exc.value) or f"'{name}'" in str(exc.value)
        assert "somewhere" in str(exc.value)


class TestDefinitionsAreChecked:
    def test_add_or_update_substitution(self, subs):
        with pytest.raises(ValueError, match="'my var'"):
            var_module.add_or_update_substitution("my var", "x")

    def test_add_substitutions_without_overwriting(self, subs):
        with pytest.raises(ValueError, match="'my var'"):
            var_module.add_substitutions_without_overwriting({"my var": "x"})

    def test_config_file_variables(self, subs, tmp_path):
        config = tmp_path / "config.toml"
        config.write_text('[common.variables]\n"my var" = "x"\n')
        with pytest.raises(ValueError, match=r"'my var'.*config\.toml"):
            var_module.load_toml_file_with_variable_substitutions(str(config))

    def test_a_valid_name_starting_with_a_digit_is_defined(self, subs):
        var_module.add_or_update_substitution("9lives", "cat")
        assert var_module.process_variable_substitutions("{{9lives}}") == "cat"


class TestReservedNames:
    @pytest.mark.parametrize("name", sorted(RESERVED_VARIABLE_NAMES))
    def test_a_reserved_name_is_refused(self, name):
        with pytest.raises(ValueError, match="set by the configuration") as exc:
            var_module.check_user_variable_name(name, "somewhere")
        assert f"'{name}'" in str(exc.value)
        assert "somewhere" in str(exc.value)

    def test_the_rule_still_applies(self):
        with pytest.raises(ValueError, match="Invalid variable name"):
            var_module.check_user_variable_name("my var", "somewhere")

    @pytest.mark.parametrize("name", ["TAG", "wr_tag", "tag2", "username"])
    def test_other_names_are_accepted(self, name):
        var_module.check_user_variable_name(name, "somewhere")

    def test_the_cli_still_registers_its_own(self, subs):
        var_module.add_substitutions_without_overwriting({"tag": "t"})
        assert var_module.process_variable_substitutions("{{tag}}") == "t"

    def test_config_file_variables(self, subs, tmp_path):
        config = tmp_path / "config.toml"
        config.write_text('[common.variables]\ntag = "x"\n')
        with pytest.raises(ValueError, match=r"'tag'.*config\.toml"):
            var_module.load_toml_file_with_variable_substitutions(str(config))

    def test_config_file_common_properties_are_unaffected(self, subs, tmp_path):
        config = tmp_path / "config.toml"
        config.write_text('[common]\ntag = "x"\n[common.variables]\nother = "y"\n')
        var_module.load_toml_file_with_variable_substitutions(str(config))


class TestReferences:
    @pytest.fixture()
    def warnings(self, subs, monkeypatch) -> MagicMock:
        monkeypatch.setattr(var_module, "_UNDEFINED_VARIABLE_WARNINGS", True)
        monkeypatch.setattr(var_module, "_UNDEFINED_VARIABLES_REPORTED", set())
        warning = MagicMock()
        monkeypatch.setattr(var_module, "print_warning", warning)
        return warning

    @pytest.mark.parametrize("text", ["{{9lives}}", "{{42}}", "{{num:7up}}"])
    def test_a_name_starting_with_a_digit_is_a_reference(self, warnings, text):
        var_module.resolve_variables_insitu({"t": text})
        assert warnings.call_count == 1

    @pytest.mark.parametrize(
        "text", ["{{.ID}}", "{{- .Values.x }}", "{{ spaced }}", "{{my var}}"]
    )
    def test_a_name_breaking_the_rule_is_text(self, warnings, text):
        data = {"t": text}
        var_module.resolve_variables_insitu(data)
        assert data == {"t": text}
        assert warnings.call_count == 0

    def test_an_env_name_may_hold_what_the_system_allows(self, warnings, monkeypatch):
        monkeypatch.setenv("YD_TEST_PF(x86)", "C:\\Program Files (x86)")
        data = {"a": "{{env:YD_TEST_PF(x86)}}", "b": "{{env:YD_TEST_UNSET(x86)}}"}
        var_module.resolve_variables_insitu(data)
        assert data["a"] == "C:\\Program Files (x86)"
        [call] = warnings.call_args_list
        assert "'{{env:YD_TEST_UNSET(x86)}}'" in call.args[0]


# ---------------------------------------------------------------------------
# The sources checked as a command starts, run as the command
# ---------------------------------------------------------------------------


def _yd_variables(*args: str, cwd, env: dict | None = None):
    environment = {
        **{k: v for k, v in os.environ.items() if not k.startswith("YD_")},
        "YD_KEY": "k",
        "YD_SECRET": "s",
        "YD_NAMESPACE": "ns",
        "YD_TAG": "tg",
        **(env or {}),
    }
    return subprocess.run(
        ["yd-variables", *args],
        capture_output=True,
        text=True,
        env=environment,
        cwd=cwd,
        timeout=120,
    )


class TestCommandSources:
    def test_command_line(self, tmp_path):
        result = _yd_variables("--nc", "-v", "my var=1", cwd=tmp_path)
        assert result.returncode == ExitCode.CONFIGURATION
        assert "'my var'" in result.stdout + result.stderr

    def test_environment(self, tmp_path):
        result = _yd_variables("--nc", cwd=tmp_path, env={"YD_VAR_my.var!": "1"})
        assert result.returncode == ExitCode.CONFIGURATION
        assert "YD_VAR_my.var!" in result.stdout + result.stderr

    def test_property_override(self, tmp_path):
        result = _yd_variables(
            "--nc", "--property", "common.variables.my var=1", cwd=tmp_path
        )
        assert result.returncode == ExitCode.CONFIGURATION
        assert "'my var'" in result.stdout + result.stderr

    def test_config_file(self, tmp_path):
        config = tmp_path / "config.toml"
        config.write_text('[common.variables]\n"my var" = "x"\n')
        result = _yd_variables("-c", str(config), cwd=tmp_path)
        assert result.returncode == ExitCode.CONFIGURATION
        assert "'my var'" in result.stdout + result.stderr

    def test_a_valid_name_starting_with_a_digit(self, tmp_path):
        result = _yd_variables("--nc", "-v", "9lives=cat", "9lives", cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        assert '"9lives": "cat"' in result.stdout


class TestReservedNamesAtTheCommandSources:
    def _refused(self, result, name: str) -> None:
        assert result.returncode == ExitCode.CONFIGURATION
        # Rich wraps the message, so compare it with the whitespace collapsed
        output = " ".join((result.stdout + result.stderr).split())
        assert f"Variable '{name}'" in output
        assert "set by the configuration" in output

    def test_command_line(self, tmp_path):
        # The case that prompted the rule: '{{::}}' used to be defined again
        # from the configuration, silently
        self._refused(_yd_variables("--nc", "-v", "tag={{::}}", cwd=tmp_path), "tag")

    def test_command_line_value(self, tmp_path):
        self._refused(
            _yd_variables("--nc", "-v", "namespace=x", cwd=tmp_path), "namespace"
        )

    def test_environment(self, tmp_path):
        self._refused(
            _yd_variables("--nc", cwd=tmp_path, env={"YD_VAR_url": "x"}), "url"
        )

    def test_property_override(self, tmp_path):
        self._refused(
            _yd_variables(
                "--nc", "--property", "common.variables.secret=1", cwd=tmp_path
            ),
            "secret",
        )

    def test_config_file(self, tmp_path):
        config = tmp_path / "config.toml"
        config.write_text('[common.variables]\nkey = "x"\n')
        self._refused(_yd_variables("-c", str(config), cwd=tmp_path), "key")

    def test_the_options_still_set_them(self, tmp_path):
        result = _yd_variables("--nc", "-t", "foo", "tag", cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        assert '"tag": "foo"' in result.stdout
