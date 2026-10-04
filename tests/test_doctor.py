"""
yd-doctor: the check model and runner, each check group through the seam it
reads, and the entry point. Also holds the one test that YD_CONF is ignored,
since the doctor is where a stray environment variable would be reported.
"""

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib

from yellowdog_cli import doctor
from yellowdog_cli.utils import doctor_checks as dc
from yellowdog_cli.utils.settings import DOCTOR_DEFAULT_TIMEOUT, PYTHON_MIN_VERSION
from yellowdog_cli.utils.variable_substitution import undefined_variable_references


def _ctx(**overrides) -> dc.Context:
    base = dict(
        offline=False,
        timeout=1,
        config_loaded=False,
        config_error=None,
        config_common=None,
        client=None,
        data_client=None,
        debug=False,
    )
    base.update(overrides)
    return dc.Context(**base)


def _clean_env(**extra: str) -> dict[str, str]:
    """The current environment with every YD_* variable removed."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("YD_")}
    env.update(extra)
    return env


class TestYdConfIsIgnored:
    def test_a_set_yd_conf_no_longer_exits(self):
        # yd-variables needs credentials but never contacts the platform
        result = subprocess.run(
            ["yd-variables", "--nc", "--quiet"],
            env=_clean_env(YD_KEY="k", YD_SECRET="s", YD_CONF="anything"),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "no longer supported" not in result.stdout + result.stderr
        json.loads(result.stdout)  # the variables report


class TestUndefinedVariableReferences:
    def test_lists_each_unresolved_reference_once(self):
        data = {"a": "{{nope}}", "b": ["{{nope}}", "{{also_nope}}"], "c": "fine"}
        assert undefined_variable_references(data) == ["also_nope", "nope"]

    def test_empty_when_all_resolved(self):
        assert undefined_variable_references({"a": "x"}) == []


class TestRunner:
    def test_unmet_need_is_skip_with_reason(self):
        check = dc.Check(
            "x",
            "Platform",
            dc.Need.CREDENTIALS_AND_NETWORK,
            lambda ctx: dc.Result(dc.Status.OK, "ran"),
        )
        [(_, result)] = dc.run_checks(_ctx(offline=True), checks=(check,))
        assert result.status is dc.Status.SKIP
        assert result.detail == "--offline"

    def test_no_credentials_reason(self):
        check = dc.Check(
            "x",
            "Platform",
            dc.Need.CREDENTIALS,
            lambda ctx: dc.Result(dc.Status.OK, "ran"),
        )
        [(_, result)] = dc.run_checks(_ctx(config_loaded=True), checks=(check,))
        assert (result.status, result.detail) == (dc.Status.SKIP, "no credentials")

    def test_config_and_network_skips_offline_first(self):
        check = dc.Check(
            "x",
            "Platform",
            dc.Need.CONFIG_AND_NETWORK,
            lambda ctx: dc.Result(dc.Status.OK, "ran"),
        )
        [(_, result)] = dc.run_checks(_ctx(offline=True), checks=(check,))
        assert (result.status, result.detail) == (dc.Status.SKIP, "--offline")

    def test_config_and_network_needs_the_configuration(self):
        check = dc.Check(
            "x",
            "Platform",
            dc.Need.CONFIG_AND_NETWORK,
            lambda ctx: dc.Result(dc.Status.OK, "ran"),
        )
        [(_, result)] = dc.run_checks(_ctx(), checks=(check,))
        assert (result.status, result.detail) == (
            dc.Status.SKIP,
            "configuration did not load",
        )
        # and needs nothing more: no credentials, no data client
        [(_, result)] = dc.run_checks(_ctx(config_loaded=True), checks=(check,))
        assert (result.status, result.detail) == (dc.Status.OK, "ran")

    def test_dynamic_rows_precede_the_data_client_group(self):
        def ok(ctx):
            return dc.Result(dc.Status.OK, "x")

        def loads(ctx):
            ctx.config_loaded = True
            ctx.profiles["[dataClient]"] = None
            return dc.Result(dc.Status.OK, "loaded")

        checks = (
            dc.Check(dc.CONFIG_LOADS, "Configuration", dc.Need.NOTHING, loads),
            dc.Check("Platform row", "Platform", dc.Need.NOTHING, ok),
            dc.Check("Remote row", "Data client", dc.Need.NOTHING, ok),
        )
        names = [c.name for c, _ in dc.run_checks(_ctx(), checks=checks)]
        assert names == [
            dc.CONFIG_LOADS,
            "Platform row",
            "Data client profile [dataClient]",
            "Remote row",
        ]

    def test_raising_check_is_fail_with_message(self):
        def boom(ctx):
            raise RuntimeError("kaboom")

        [(_, result)] = dc.run_checks(
            _ctx(), checks=(dc.Check("x", "Installation", dc.Need.NOTHING, boom),)
        )
        assert (result.status, result.detail) == (dc.Status.FAIL, "kaboom")

    def test_raising_check_reraises_under_debug(self):
        def boom(ctx):
            raise RuntimeError("kaboom")

        with pytest.raises(RuntimeError):
            dc.run_checks(
                _ctx(debug=True),
                checks=(dc.Check("x", "Installation", dc.Need.NOTHING, boom),),
            )

    def test_exiting_check_is_fail_with_status(self):
        def leave(ctx):
            raise SystemExit(3)

        [(_, result)] = dc.run_checks(
            _ctx(), checks=(dc.Check("x", "Installation", dc.Need.NOTHING, leave),)
        )
        assert (result.status, result.detail) == (
            dc.Status.FAIL,
            "exited with status 3",
        )

    def test_exiting_check_reraises_under_debug(self):
        def leave(ctx):
            raise SystemExit(3)

        with pytest.raises(SystemExit):
            dc.run_checks(
                _ctx(debug=True),
                checks=(dc.Check("x", "Installation", dc.Need.NOTHING, leave),),
            )

    def test_with_timeout_reports_expiry(self):
        import time

        result = dc.with_timeout(lambda: time.sleep(2), seconds=0.1)
        assert result.status is dc.Status.FAIL
        assert "0.1" in result.detail


class TestPythonVersion:
    def test_minimum_matches_pyproject(self):
        with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
            requires = tomllib.load(f)["project"]["requires-python"]
        assert requires == ">=" + ".".join(map(str, PYTHON_MIN_VERSION))

    def test_below_minimum_fails(self, monkeypatch):
        monkeypatch.setattr(dc.sys, "version_info", (3, 9, 0, "final", 0))
        assert dc.check_python_version(_ctx()).status is dc.Status.FAIL

    def test_above_tested_warns(self, monkeypatch):
        monkeypatch.setattr(dc.sys, "version_info", (3, 99, 0, "final", 0))
        assert dc.check_python_version(_ctx()).status is dc.Status.WARN


class TestRendering:
    def _rows(self):
        c = dc.Check(
            "Python version", "Installation", dc.Need.NOTHING, lambda ctx: None
        )
        return [(c, dc.Result(dc.Status.FAIL, "3.9.0", "Install Python 3.10 or later"))]

    def test_exit_code_follows_fail_only(self):
        c = dc.Check("x", "Installation", dc.Need.NOTHING, lambda ctx: None)
        assert doctor.exit_code([(c, dc.Result(dc.Status.WARN, "w"))]) == 0
        assert doctor.exit_code([(c, dc.Result(dc.Status.FAIL, "f"))]) == 1

    def test_json_rows(self):
        [row] = doctor.render_json(self._rows())
        assert row == {
            "group": "Installation",
            "check": "Python version",
            "status": "FAIL",
            "detail": "3.9.0",
            "remedy": "Install Python 3.10 or later",
        }

    def test_table_names_check_status_detail_and_remedy(self, capsys):
        doctor.render_table(self._rows())
        out = capsys.readouterr().out
        assert "Python version" in out and "FAIL" in out and "3.9.0" in out
        assert "FAIL Python version: Install Python 3.10 or later" in out
        assert "1 checks: 0 OK, 0 WARN, 1 FAIL, 0 SKIP" in out


class TestCommandRegistration:
    def test_registered_as_api_command_with_its_own_options(self):
        from yellowdog_cli.utils.command_registry import COMMANDS, CommandKind

        cmd = COMMANDS["yd-doctor"]
        assert cmd.kind is CommandKind.API and cmd.requires_namespace_and_tag
        names = [o.name for o in cmd.flat_options()]
        assert names[-3:] == ["--offline", "--json", "--timeout"]
        assert "--namespace" in names and "--variable" in names

    def test_parser_defaults(self):
        from yellowdog_cli.utils.args import CLIParser

        p = CLIParser(command="yd-doctor", argv=[])
        assert (
            p.offline is False
            and p.timeout == DOCTOR_DEFAULT_TIMEOUT
            and p.json_output is False
        )

    @pytest.mark.parametrize("value", ["0", "-1", "x"])
    def test_a_non_positive_timeout_is_a_usage_error(self, value, capsys):
        from yellowdog_cli.utils.args import CLIParser

        with pytest.raises(SystemExit) as e:
            CLIParser(command="yd-doctor", argv=["--timeout", value])
        assert e.value.code == 2
        assert "--timeout" in capsys.readouterr().err

    def test_a_positive_timeout_is_kept(self):
        from yellowdog_cli.utils.args import CLIParser

        assert CLIParser(command="yd-doctor", argv=["--timeout", "3"]).timeout == 3


def _args(monkeypatch, **values) -> None:
    """Set ARGS_PARSER's properties for one test (on the class: they have no setters)."""
    from yellowdog_cli.utils.args import CLIParser

    defaults = dict(
        json_output=False,
        quiet=False,
        offline=False,
        timeout=DOCTOR_DEFAULT_TIMEOUT,
        debug=False,
        no_format=False,
    )
    defaults.update(values)
    for name, value in defaults.items():
        monkeypatch.setattr(CLIParser, name, value)


def _check(name: str, result: dc.Result) -> dc.Check:
    return dc.Check(name, "Installation", dc.Need.NOTHING, lambda ctx: result)


def _row(name: str, result: dc.Result) -> tuple[dc.Check, dc.Result]:
    return (_check(name, result), result)


class TestRenderingRegressions:
    @pytest.mark.parametrize("no_format", [True, False])
    def test_details_line_up_across_statuses(self, monkeypatch, capsys, no_format):
        # with formatting on, the markup is what once pushed the columns apart
        _args(monkeypatch, no_format=no_format)
        doctor.render_table(
            [
                (
                    _check("Python version", dc.Result(dc.Status.OK, "3.14.7")),
                    dc.Result(dc.Status.OK, "3.14.7"),
                ),
                (
                    _check("Latest", dc.Result(dc.Status.FAIL, "old")),
                    dc.Result(dc.Status.FAIL, "old", "Upgrade"),
                ),
            ]
        )
        lines = capsys.readouterr().out.splitlines()
        ok = next(line for line in lines if line.startswith("Python version"))
        fail = next(line for line in lines if line.startswith("Latest"))
        assert ok.index("3.14.7") == fail.index("old")

    DETAIL = " ".join(f"word{i}" for i in range(30))  # 30 words, well past 60 columns

    def _narrow_console(self, monkeypatch, force_terminal=True):
        import io

        from rich.console import Console

        console = Console(
            width=60, file=io.StringIO(), force_terminal=force_terminal, no_color=True
        )
        monkeypatch.setattr(doctor, "CONSOLE_TABLE", console)
        return console

    def test_a_long_detail_wraps_under_its_column(self, monkeypatch, capsys):
        _args(monkeypatch)
        console = self._narrow_console(monkeypatch, force_terminal=True)
        detail = self.DETAIL
        assert len(detail) > 150
        doctor.render_table([_row("Groups and roles", dc.Result(dc.Status.OK, detail))])
        lines = console.file.getvalue().splitlines()
        offset = len("Groups and roles") + 2 + len("WARN") + 2
        assert lines[0].startswith("Groups and roles  OK")
        assert len(lines) > 2
        assert all(len(line) <= 60 for line in lines)
        for line in lines[1:]:
            assert line.startswith(" " * offset) and line[offset] != " "
        pieces = [lines[0][offset:]] + [line[offset:] for line in lines[1:]]
        assert " ".join(pieces) == detail

    def test_a_long_detail_is_one_line_off_a_terminal(self, monkeypatch, capsys):
        _args(monkeypatch)
        console = self._narrow_console(monkeypatch, force_terminal=False)
        detail = self.DETAIL
        assert len(detail) > 150
        doctor.render_table([_row("Groups and roles", dc.Result(dc.Status.OK, detail))])
        lines = console.file.getvalue().splitlines()
        rows = [line for line in lines if "word" in line]
        assert len(rows) == 1 and rows[0].endswith(detail)

    def test_a_long_detail_is_one_line_under_no_format(self, monkeypatch, capsys):
        _args(monkeypatch, no_format=True)
        self._narrow_console(monkeypatch)
        doctor.render_table(
            [_row("Groups and roles", dc.Result(dc.Status.OK, self.DETAIL))]
        )
        rows = [line for line in capsys.readouterr().out.splitlines() if "word" in line]
        assert len(rows) == 1 and rows[0].endswith(self.DETAIL)

    def test_a_long_remedy_wraps_under_its_text(self, monkeypatch):
        _args(monkeypatch)
        console = self._narrow_console(monkeypatch, force_terminal=True)
        doctor._print_remedies(
            [
                (
                    _check("Latest", dc.Result(dc.Status.WARN, "old")),
                    dc.Result(dc.Status.WARN, "old", self.DETAIL),
                )
            ]
        )
        lines = console.file.getvalue().splitlines()
        offset = len("WARN ")
        assert lines[0].startswith("WARN Latest: word0")
        assert len(lines) > 2 and all(len(line) <= 60 for line in lines)
        for line in lines[1:]:
            assert line.startswith(" " * offset) and line[offset] != " "
        text = " ".join([lines[0][offset:]] + [line[offset:] for line in lines[1:]])
        assert text == f"Latest: {self.DETAIL}"

    def test_a_long_remedy_is_one_line_off_a_terminal(self, monkeypatch):
        _args(monkeypatch)
        console = self._narrow_console(monkeypatch, force_terminal=False)
        doctor._print_remedies(
            [
                (
                    _check("Latest", dc.Result(dc.Status.WARN, "old")),
                    dc.Result(dc.Status.WARN, "old", self.DETAIL),
                )
            ]
        )
        lines = console.file.getvalue().splitlines()
        rows = [line for line in lines if line.startswith("WARN Latest:")]
        assert len(rows) == 1 and rows[0] == f"WARN Latest: {self.DETAIL}"

    def test_a_long_token_is_not_split(self, monkeypatch):
        _args(monkeypatch)
        console = self._narrow_console(monkeypatch, force_terminal=True)
        token = "ydid:" + "x" * 65
        doctor.render_table(
            [_row("Tag", dc.Result(dc.Status.OK, f"short {token} end"))]
        )
        # the token stands whole on a line of its own, past the width
        lines = console.file.getvalue().splitlines()
        assert any(line.strip() == token for line in lines)
        assert all("x" * 65 in line for line in lines if "ydid:" in line)

    def test_quiet_prints_a_warn_remedy(self, monkeypatch, capsys):
        _args(monkeypatch, quiet=True)
        warn = dc.Result(dc.Status.WARN, "1.0", "Upgrade to 2.0")
        monkeypatch.setattr(dc, "CHECKS", (_check("Latest", warn),))
        with pytest.raises(SystemExit):
            doctor.main()
        out = capsys.readouterr().out
        assert "WARN Latest: Upgrade to 2.0" in out
        assert "1 checks: 0 OK, 1 WARN, 0 FAIL, 0 SKIP" in out


class TestMain:
    def _checks(self, second: dc.Status) -> tuple[dc.Check, ...]:
        return (
            _check("First", dc.Result(dc.Status.OK, "fine")),
            _check("Second", dc.Result(second, "detail", "remedy")),
        )

    def test_exit_code_is_one_with_a_fail(self, monkeypatch, capsys):
        _args(monkeypatch)
        monkeypatch.setattr(dc, "CHECKS", self._checks(dc.Status.FAIL))
        with pytest.raises(SystemExit) as e:
            doctor.main()
        assert e.value.code == 1
        assert "FAIL Second: remedy" in capsys.readouterr().out

    def test_exit_code_is_zero_without_a_fail(self, monkeypatch, capsys):
        _args(monkeypatch)
        monkeypatch.setattr(dc, "CHECKS", self._checks(dc.Status.WARN))
        with pytest.raises(SystemExit) as e:
            doctor.main()
        assert e.value.code == 0

    def test_json_stdout_is_the_rows(self, monkeypatch, capsys):
        _args(monkeypatch, json_output=True)
        monkeypatch.setattr(dc, "CHECKS", self._checks(dc.Status.FAIL))
        with pytest.raises(SystemExit) as e:
            doctor.main()
        assert e.value.code == 1
        rows = json.loads(capsys.readouterr().out)
        assert [(r["check"], r["status"]) for r in rows] == [
            ("First", "OK"),
            ("Second", "FAIL"),
        ]


def _cfg(**kw) -> SimpleNamespace:
    """A ConfigCommon stand-in, with PAC off unless a test turns it on."""
    values = dict(
        key="k",
        secret="s",
        url="https://api.example",
        namespace="ns",
        name_tag="t",
        use_pac=False,
    )
    values.update(kw)
    return SimpleNamespace(**values)


def _fake_pac(monkeypatch, proxy):
    """A pac_context_for_url fake that sets HTTPS_PROXY while it is open."""
    entered = []

    @contextlib.contextmanager
    def fake(url):
        entered.append(url)
        saved = os.environ.get("HTTPS_PROXY")
        if proxy is not None:
            os.environ["HTTPS_PROXY"] = proxy
        try:
            yield
        finally:
            if saved is None:
                os.environ.pop("HTTPS_PROXY", None)
            else:
                os.environ["HTTPS_PROXY"] = saved

    monkeypatch.setattr(dc, "pac_context_for_url", fake)
    return entered


class TestInstallation:
    def test_install_kind_detects_venv(self, monkeypatch):
        monkeypatch.setattr(dc.sys, "prefix", "/x/venv")
        monkeypatch.setattr(dc.sys, "base_prefix", "/usr")
        monkeypatch.setattr(dc.sys, "executable", "/x/venv/bin/python")
        r = dc.check_install_kind(_ctx())
        assert (r.status, r.detail) == (dc.Status.OK, "virtual environment (/x/venv)")

    @pytest.mark.parametrize(
        "exe, kind",
        [
            ("/home/u/.local/pipx/venvs/yellowdog-cli/bin/python", "pipx"),
            ("/home/u/.local/share/uv/tools/yellowdog-cli/bin/python", "uv tool"),
        ],
    )
    def test_install_kind_detects_managers(self, monkeypatch, exe, kind):
        monkeypatch.setattr(dc.sys, "prefix", exe.rsplit("/bin", 1)[0])
        monkeypatch.setattr(dc.sys, "base_prefix", "/usr")
        monkeypatch.setattr(dc.sys, "executable", exe)
        assert dc.check_install_kind(_ctx()).detail.startswith(kind)

    def test_install_kind_warns_on_system_python(self, monkeypatch):
        monkeypatch.setattr(dc.sys, "prefix", "/usr")
        monkeypatch.setattr(dc.sys, "base_prefix", "/usr")
        monkeypatch.setattr(dc.sys, "executable", "/usr/bin/python3")
        r = dc.check_install_kind(_ctx())
        assert r.status is dc.Status.WARN and "pipx" in (r.remedy or "")

    def test_extra_absent_is_ok_optional(self, monkeypatch):
        monkeypatch.setattr(dc, "_module_is_installed", lambda name: False)
        r = dc.check_extra_jsonnet(_ctx())
        assert (r.status, r.detail) == (dc.Status.OK, "not installed (optional)")

    def test_extra_present_and_loading_is_ok(self, monkeypatch):
        monkeypatch.setattr(dc, "_module_is_installed", lambda name: True)
        monkeypatch.setattr(dc, "check_jsonnet_import", lambda: None)
        assert dc.check_extra_jsonnet(_ctx()).status is dc.Status.OK

    def test_extra_present_but_broken_is_fail_with_the_guards_remedy(self, monkeypatch):
        monkeypatch.setattr(dc, "_module_is_installed", lambda name: True)

        def broken():
            raise ImportError("libstdc++ missing: install it")

        monkeypatch.setattr(dc, "check_jsonnet_import", broken)
        r = dc.check_extra_jsonnet(_ctx())
        assert (
            r.status is dc.Status.FAIL and r.remedy == "libstdc++ missing: install it"
        )

    def test_the_mcp_extra_is_checked_like_the_others(self, monkeypatch):
        monkeypatch.setattr(dc, "_module_is_installed", lambda name: False)
        r = dc.check_extra_mcp(_ctx())
        assert (r.status, r.detail) == (dc.Status.OK, "not installed (optional)")
        monkeypatch.setattr(dc, "_module_is_installed", lambda name: True)
        monkeypatch.setattr(dc, "check_mcp_imports", lambda: None)
        assert dc.check_extra_mcp(_ctx()).status is dc.Status.OK

    def test_rclone_missing_warns(self, monkeypatch):
        monkeypatch.setattr(dc, "find_rclone", lambda: None)
        r = dc.check_rclone(_ctx())
        assert r.status is dc.Status.WARN and "yd-upload" in (r.remedy or "")

    def test_rclone_found(self, monkeypatch):
        monkeypatch.setattr(
            dc, "find_rclone", lambda: ("/usr/local/bin/rclone", "PATH")
        )
        monkeypatch.setattr(dc, "rclone_version", lambda: "1.68.0")
        assert dc.check_rclone(_ctx()).detail == "1.68.0 (/usr/local/bin/rclone, PATH)"

    def _loaded(self, **kw) -> dc.Context:
        return _ctx(config_loaded=True, config_common=_cfg(**kw))

    def test_proxy_reports_env_and_leaves_pac_alone(self, monkeypatch):
        monkeypatch.setenv("HTTPS_PROXY", "http://proxy:3128")
        entered = _fake_pac(monkeypatch, "http://pac-proxy:3128")
        r = dc.check_proxy(self._loaded())
        assert (r.status, r.detail) == (dc.Status.OK, "HTTPS_PROXY=http://proxy:3128")
        assert entered == []

    def test_proxy_none(self, monkeypatch):
        monkeypatch.delenv("HTTPS_PROXY", raising=False)
        monkeypatch.delenv("https_proxy", raising=False)
        assert dc.check_proxy(self._loaded()).detail == "none"

    def test_proxy_without_a_configuration_says_pac_is_unknown(self, monkeypatch):
        monkeypatch.delenv("HTTPS_PROXY", raising=False)
        monkeypatch.delenv("https_proxy", raising=False)
        assert dc.check_proxy(_ctx()).detail == (
            "none (PAC status unknown: configuration did not load)"
        )

    def test_pac_proxy_is_reported_and_kept_for_the_later_checks(self, monkeypatch):
        # set first, so that monkeypatch restores the variable's absence
        # after check_proxy has written it
        monkeypatch.setenv("HTTPS_PROXY", "placeholder")
        monkeypatch.delenv("HTTPS_PROXY")
        entered = _fake_pac(monkeypatch, "http://pac-proxy:3128")
        r = dc.check_proxy(self._loaded(use_pac=True))
        assert (r.status, r.detail) == (
            dc.Status.OK,
            "PAC resolved HTTPS_PROXY=http://pac-proxy:3128 for https://api.example",
        )
        assert entered == ["https://api.example"]
        assert os.environ["HTTPS_PROXY"] == "http://pac-proxy:3128"

    def test_pac_resolving_nothing_warns(self, monkeypatch):
        monkeypatch.delenv("HTTPS_PROXY", raising=False)
        _fake_pac(monkeypatch, None)
        r = dc.check_proxy(self._loaded(use_pac=True))
        assert r.status is dc.Status.WARN
        assert r.detail == (
            "PAC enabled but no proxy resolved for https://api.example;"
            " commands will connect directly"
        )
        assert "usePAC" in (r.remedy or "") and "--pac" in (r.remedy or "")

    def test_pac_is_not_resolved_offline(self, monkeypatch):
        entered = _fake_pac(monkeypatch, "http://pac-proxy:3128")
        ctx = self._loaded(use_pac=True)
        ctx.offline = True
        r = dc.check_proxy(ctx)
        assert (r.status, r.detail) == (
            dc.Status.OK,
            "PAC enabled (not resolved: --offline)",
        )
        assert entered == []

    def test_pac_resolution_raising_fails(self, monkeypatch):
        @contextlib.contextmanager
        def broken(url):
            raise RuntimeError("PAC file could not be fetched")
            yield

        monkeypatch.setattr(dc, "pac_context_for_url", broken)
        r = dc.check_proxy(self._loaded(use_pac=True))
        assert r.status is dc.Status.FAIL
        assert "PAC file could not be fetched" in r.detail
        assert "usePAC" in (r.remedy or "")

    def test_certificates_missing_file_fails(self, monkeypatch, tmp_path):
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(tmp_path / "nope.pem"))
        r = dc.check_certificates(_ctx(config_loaded=True))
        assert r.status is dc.Status.FAIL

    def test_certificates_system_default(self, monkeypatch):
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        assert (
            dc.check_certificates(_ctx(config_loaded=True)).detail == "system default"
        )

    def test_pypi_newer_version_warns(self, monkeypatch):
        monkeypatch.setattr(dc, "_pypi_latest_version", lambda timeout: "99.0.0")
        r = dc.check_newer_cli_on_pypi(_ctx())
        assert r.status is dc.Status.WARN and "99.0.0" in r.detail

    def test_pypi_unreachable_skips(self, monkeypatch):
        def nope(timeout):
            raise OSError("no route")

        monkeypatch.setattr(dc, "_pypi_latest_version", nope)
        assert dc.check_newer_cli_on_pypi(_ctx()).status is dc.Status.SKIP

    def test_checks_are_registered_in_order(self):
        names = [c.name for c in dc.CHECKS if c.group == "Installation"]
        assert names == [
            "Python version",
            "Install kind",
            "CLI and SDK versions",
            "SDK imports",
            "Jsonnet",
            "Cloud Wizard",
            "Commander",
            "MCP Server",
            "rclone",
            # Ahead of PyPI, which goes through the proxy PAC resolves
            "Proxy",
            "Certificates",
            "Newer CLI on PyPI",
        ]


def _run_doctor(tmp_path, *args, env=None, config=None):
    if config is not None:
        (tmp_path / "config.toml").write_text(config)
    result = subprocess.run(
        ["yd-doctor", "--offline", "--json", *args],
        cwd=tmp_path,
        env=env or _clean_env(),
        capture_output=True,
        text=True,
    )
    rows = {row["check"]: row for row in json.loads(result.stdout)}
    return result.returncode, rows


class TestConfiguration:
    def test_no_configuration_at_all(self, tmp_path):
        code, rows = _run_doctor(tmp_path)
        assert rows["Configuration loads"]["detail"] == "no file, environment only"
        assert rows["Key"]["status"] == "FAIL" and rows["Secret"]["status"] == "FAIL"
        assert rows["Namespace"] == {
            **rows["Namespace"],
            "status": "OK",
            "detail": "default (default)",
        }
        assert rows["Authenticated"]["status"] == "SKIP"
        assert code == 1

    def test_no_config_with_no_file_present_says_no_file(self, tmp_path):
        _, rows = _run_doctor(tmp_path, "--nc")
        assert rows["Configuration loads"]["detail"] == "no file, environment only"

    def test_no_config_with_a_file_present_says_it_is_ignored(self, tmp_path):
        _, rows = _run_doctor(tmp_path, "--nc", config='[common]\nkey = "k"\n')
        assert (
            rows["Configuration loads"]["detail"]
            == "config.toml ignored, environment only"
        )

    def test_good_file(self, tmp_path):
        code, rows = _run_doctor(
            tmp_path,
            config='[common]\nkey = "k"\nsecret = "s"\nnamespace = "ns"\ntag = "tg"\n',
        )
        assert rows["Configuration loads"]["detail"] == "config.toml"
        assert rows["Key"]["detail"] == "k (config file (config.toml))"
        assert rows["Secret"]["detail"] == "<REDACTED> (config file (config.toml))"
        assert rows["Namespace"]["detail"] == "ns (config file (config.toml))"
        assert rows["Variable references"]["status"] == "OK"
        assert rows["Tag"]["status"] == "OK"
        assert code == 0

    def test_malformed_file_is_reported_not_fatal(self, tmp_path):
        code, rows = _run_doctor(tmp_path, config="[common\nkey = ")
        assert rows["Configuration loads"]["status"] == "FAIL"
        assert "config.toml" in rows["Configuration loads"]["detail"]
        assert rows["Key"]["status"] == "SKIP"
        assert rows["Key"]["detail"] == "configuration did not load"
        assert code == 1

    @pytest.mark.parametrize("extra", [(), ("--no-format",)])
    def test_load_error_is_one_line_without_the_log_prefix(self, tmp_path, extra):
        _, rows = _run_doctor(tmp_path, *extra, config="[common\nkey = ")
        detail = rows["Configuration loads"]["detail"]
        assert detail.startswith("Unable to load configuration data from 'config.toml'")
        assert "\n" not in detail and "ERROR" not in detail

    def test_unknown_property_is_reported(self, tmp_path):
        _, rows = _run_doctor(
            tmp_path, config='[common]\nkey = "k"\nsecret = "s"\nbogus = 1\n'
        )
        assert rows["Configuration loads"]["status"] == "FAIL"
        assert "bogus" in rows["Configuration loads"]["detail"]

    def test_environment_sources(self, tmp_path):
        _, rows = _run_doctor(
            tmp_path, env=_clean_env(YD_KEY="k", YD_SECRET="s", YD_NAMESPACE="ns")
        )
        assert rows["Key"]["detail"] == "k (environment (YD_KEY))"
        assert rows["Namespace"]["detail"] == "ns (environment (YD_NAMESPACE))"

    def test_undefined_variable_warns(self, tmp_path):
        _, rows = _run_doctor(
            tmp_path,
            config='[common]\nkey = "k"\nsecret = "s"\nnamespace = "{{nope}}"\n',
        )
        assert rows["Variable references"]["status"] == "WARN"
        assert "nope" in rows["Variable references"]["detail"]

    def test_illegal_tag_warns(self, tmp_path):
        _, rows = _run_doctor(
            tmp_path, config='[common]\nkey = "k"\nsecret = "s"\ntag = "Has Spaces!"\n'
        )
        assert rows["Tag"]["status"] == "OK"  # the value row reports the value
        assert rows["Tag is a legal name"]["status"] == "WARN"

    def test_dotenv_file_named(self, tmp_path):
        (tmp_path / ".env").write_text("YD_KEY=k\nYD_SECRET=s\n")
        _, rows = _run_doctor(tmp_path)
        assert rows[".env file"]["detail"].endswith(".env")
        assert rows["Key"]["detail"] == "k (environment (YD_KEY))"

    def test_certificates_checked_once_the_configuration_loads(self, tmp_path):
        _, rows = _run_doctor(
            tmp_path,
            config='[common]\nkey = "k"\nsecret = "s"\ncertificates = "missing.pem"\n',
        )
        assert rows["Certificates"]["status"] == "FAIL"
        assert "missing.pem" in rows["Certificates"]["detail"]

    def test_configuration_rows_follow_installation(self, tmp_path):
        _, rows = _run_doctor(tmp_path, config='[common]\nkey = "k"\nsecret = "s"\n')
        names = [name for name, row in rows.items() if row["group"] == "Configuration"]
        assert names == [
            "Configuration loads",
            "Config schema",
            "Key",
            "Secret",
            "Namespace",
            "Tag",
            "URL",
            "Variable references",
            ".env file",
            "Tag is a legal name",
        ]

    def test_config_schema_ok(self, tmp_path):
        _, rows = _run_doctor(tmp_path, config='[common]\nkey = "k"\nsecret = "s"\n')
        assert rows["Config schema"]["status"] == "OK"
        assert rows["Config schema"]["detail"] == "no violations"

    def test_config_schema_no_file(self, tmp_path):
        _, rows = _run_doctor(tmp_path)
        assert rows["Config schema"]["status"] == "OK"
        assert rows["Config schema"]["detail"] == "no configuration file"

    def test_config_schema_warns_of_violations(self, tmp_path):
        _, rows = _run_doctor(
            tmp_path,
            config=(
                '[common]\nkey = "k"\nsecret = "s"\nusePAC = "yes"\n'
                "[workRequirement]\nminNodes = 1\n"
                '[workerPool]\nmaxNodes = "a"\nminNodes = "b"\n'
            ),
        )
        row = rows["Config schema"]
        assert row["status"] == "WARN"
        assert row["detail"].startswith("4 violations: ")
        assert "common.usePAC: must be boolean" in row["detail"]
        assert row["detail"].endswith("; and 1 more")
        assert "warning" in row["remedy"]

    def test_config_schema_skipped_when_the_file_does_not_load(self, tmp_path):
        _, rows = _run_doctor(tmp_path, config="[common\nkey = ")
        assert rows["Config schema"]["status"] == "SKIP"

    def test_config_schema_unbuildable_warns(self, monkeypatch):
        from yellowdog_cli.utils import load_config, spec_validation
        from yellowdog_cli.utils.spec_schema import SchemaGenerationError

        def fail(document, sections):
            raise SchemaGenerationError("Thing.field: unknown annotation")

        monkeypatch.setattr(load_config, "_CONFIG_AS_WRITTEN", {"common": {}})
        monkeypatch.setattr(spec_validation, "validate_config", fail)
        result = dc.check_config_schema(_ctx(config_loaded=True))
        assert result.status is dc.Status.WARN
        assert "Thing.field" in result.detail

    def test_data_client_profiles_listed(self, tmp_path):
        config = (
            '[common]\nkey = "k"\nsecret = "s"\n'
            '[dataClient]\nremote = ":s3,provider=AWS:"\nbucket = "b"\nprefix = "p"\n'
            '[dataClient.backup]\nbucket = "b2"\n'
        )
        _, rows = _run_doctor(tmp_path, config=config)
        assert (
            rows["Data client profile [dataClient]"]["detail"]
            == ":s3,provider=AWS: b/p"
        )
        assert rows["Data client profile backup"]["detail"] == ":s3,provider=AWS: b2/p"
        # the profile rows open the Data client group, after Platform, so
        # that the JSON's order is the table's
        order = list(rows)
        at = order.index("Namespace granted")
        assert order[at + 1 : at + 4] == [
            "Data client profile [dataClient]",
            "Data client profile backup",
            "Remote reachable",
        ]

    def test_no_data_client_section_is_one_skip_row(self, tmp_path):
        _, rows = _run_doctor(tmp_path, config='[common]\nkey = "k"\nsecret = "s"\n')
        profile_rows = [name for name in rows if name.startswith("Data client profile")]
        assert profile_rows == ["Data client profile"]
        row = rows["Data client profile"]
        assert row["group"] == "Data client"
        assert row["status"] == "SKIP" and row["detail"] == "no [dataClient] section"

    def test_no_profile_row_when_the_configuration_did_not_load(self, tmp_path):
        _, rows = _run_doctor(tmp_path, config="[common\nkey = ")
        assert not [name for name in rows if name.startswith("Data client profile")]

    def test_named_remote_absent_from_rclone_config_fails(self, tmp_path):
        from yellowdog_cli.utils.rclone_version import find_rclone

        if find_rclone() is None:
            pytest.skip("rclone not installed")
        config = (
            '[common]\nkey = "k"\nsecret = "s"\n'
            '[dataClient]\nremote = "nonesuch-remote-xyz"\nbucket = "b"\n'
        )
        _, rows = _run_doctor(tmp_path, config=config)
        row = rows["Data client profile [dataClient]"]
        assert row["status"] == "FAIL" and "nonesuch-remote-xyz" in row["detail"]


class TestProfileLoadFailure:
    def test_the_loaders_message_is_the_rows_detail(self):
        from yellowdog_cli.utils.printing import print_error

        def load(name):
            if name == "bad":
                print_error(
                    "Circular variable reference: 'x' refers back to itself,"
                    " in 'dataClient.bad.bucket'"
                )
                raise SystemExit(1)
            return SimpleNamespace(remote="r:", bucket="b", prefix="p")

        fake = SimpleNamespace(
            CONFIG_TOML={"dataClient": {"remote": "r:", "bad": {"bucket": "x"}}},
            DATA_CLIENT_SECTION="dataClient",
            load_config_data_client_for_profile=load,
        )
        ctx = _ctx(config_loaded=True)
        dc._load_data_client_profiles(ctx, fake)
        assert ctx.profiles["bad"] is None
        r = dc._profile_check("bad")(ctx)
        assert r.status is dc.Status.FAIL
        assert r.detail == (
            "could not be loaded: Circular variable reference: 'x' refers back"
            " to itself, in 'dataClient.bad.bucket'"
        )
        assert r.remedy is not None
        assert "[dataClient.bad]" in r.remedy and "'bucket'" in r.remedy

    def test_a_real_load_failure_reaches_the_row(self, tmp_path):
        config = (
            '[common]\nkey = "k"\nsecret = "s"\n'
            '[dataClient]\nremote = "loc,type=local"\n'
            '[dataClient.backup]\nbucket = "b"\n'
        )
        _, rows = _run_doctor(
            tmp_path,
            config=config,
            env=_clean_env(YD_DATA_CLIENT_BUCKET="{{num:x:=abc}}"),
        )
        row = rows["Data client profile backup"]
        assert row["status"] == "FAIL"
        assert row["detail"] == (
            "could not be loaded: Cannot substitute '{{num:x:=abc}}':"
            " 'abc' is not a number"
        )
        assert "[dataClient.backup]" in row["remedy"]


class TestDynamicChecks:
    def test_a_custom_tuple_gets_no_dynamic_rows(self):
        ctx = _ctx(config_loaded=True)
        ctx.profiles["[dataClient]"] = object()
        check = dc.Check(
            "Only",
            "Installation",
            dc.Need.NOTHING,
            lambda c: dc.Result(dc.Status.OK, "x"),
        )
        rows = dc.run_checks(ctx, checks=(check,))
        assert [c.name for c, _ in rows] == ["Only"]

    def test_dynamic_checks_one_per_profile_base_first(self):
        ctx = _ctx(config_loaded=True)
        ctx.profiles.update({"[dataClient]": None, "backup": None})
        names = [c.name for c in dc.dynamic_checks(ctx)]
        assert names == [
            "Data client profile [dataClient]",
            "Data client profile backup",
        ]


class TestLive:
    def _cfg(self, **kw):
        return _cfg(**kw)

    def test_reachable_any_http_status_is_ok(self, monkeypatch):
        monkeypatch.setattr(
            dc.requests, "get", lambda url, timeout: SimpleNamespace(status_code=404)
        )
        r = dc.check_platform_reachable(
            _ctx(config_loaded=True, config_common=self._cfg())
        )
        assert r.status is dc.Status.OK and "404" in r.detail

    def test_reachable_connection_error_fails_with_exception_text(self, monkeypatch):
        def boom(url, timeout):
            raise dc.requests.ConnectionError("Name or service not known")

        monkeypatch.setattr(dc.requests, "get", boom)
        r = dc.check_platform_reachable(
            _ctx(config_loaded=True, config_common=self._cfg())
        )
        assert r.status is dc.Status.FAIL and "Name or service not known" in r.detail

    def test_reachable_timeout_is_no_answer(self, monkeypatch):
        import time

        def slow(url, timeout):
            time.sleep(2)

        monkeypatch.setattr(dc.requests, "get", slow)
        r = dc.check_platform_reachable(
            _ctx(config_loaded=True, config_common=self._cfg(), timeout=0.1)
        )
        assert r.status is dc.Status.FAIL
        assert r.detail == "no answer within 0.1 seconds"

    def test_reachable_uses_the_environments_proxy_and_names_it_under_pac(
        self, monkeypatch
    ):
        monkeypatch.setenv("HTTPS_PROXY", "http://pac-proxy:3128")
        seen = []

        def get(url, timeout):
            seen.append((url, os.environ.get("HTTPS_PROXY")))
            return SimpleNamespace(status_code=404)

        monkeypatch.setattr(dc.requests, "get", get)
        r = dc.check_platform_reachable(
            _ctx(config_loaded=True, config_common=self._cfg(use_pac=True))
        )
        assert (r.status, r.detail) == (
            dc.Status.OK,
            "https://api.example answered HTTP 404 via HTTPS_PROXY=http://pac-proxy:3128",
        )
        assert seen == [("https://api.example", "http://pac-proxy:3128")]

    def test_reachable_does_not_resolve_pac(self, monkeypatch):
        monkeypatch.delenv("HTTPS_PROXY", raising=False)
        monkeypatch.delenv("https_proxy", raising=False)
        entered = _fake_pac(monkeypatch, "http://pac-proxy:3128")
        monkeypatch.setattr(
            dc.requests, "get", lambda url, timeout: SimpleNamespace(status_code=404)
        )
        r = dc.check_platform_reachable(
            _ctx(config_loaded=True, config_common=self._cfg(use_pac=True))
        )
        assert (r.status, r.detail) == (
            dc.Status.OK,
            "https://api.example answered HTTP 404",
        )
        assert entered == []

    def test_pac_resolving_nothing_and_no_answer_is_two_rows(self, monkeypatch):
        monkeypatch.delenv("HTTPS_PROXY", raising=False)
        monkeypatch.delenv("https_proxy", raising=False)
        _fake_pac(monkeypatch, None)

        def boom(url, timeout):
            raise dc.requests.ConnectionError("refused")

        monkeypatch.setattr(dc.requests, "get", boom)
        checks = tuple(c for c in dc.CHECKS if c.name in ("Proxy", "Reachable"))
        rows = dc.run_checks(
            _ctx(config_loaded=True, config_common=self._cfg(use_pac=True)),
            checks=checks,
        )
        assert [(c.name, r.status) for c, r in rows] == [
            ("Proxy", dc.Status.WARN),
            ("Reachable", dc.Status.FAIL),
        ]
        assert "refused" in rows[1][1].detail

    def test_authenticated_skips_when_the_platform_is_unreachable(self, monkeypatch):
        def refused(url, timeout):
            raise dc.requests.ConnectionError("Connection refused")

        def never(cfg):
            raise AssertionError("_build_client called")

        monkeypatch.setattr(dc.requests, "get", refused)
        monkeypatch.setattr(dc, "_build_client", never)
        checks = tuple(c for c in dc.CHECKS if c.name in ("Reachable", "Authenticated"))
        rows = dc.run_checks(
            _ctx(config_loaded=True, config_common=self._cfg()), checks=checks
        )
        assert [(c.name, r.status) for c, r in rows] == [
            ("Reachable", dc.Status.FAIL),
            ("Authenticated", dc.Status.SKIP),
        ]
        assert rows[1][1].detail == "platform not reachable"

    def test_authenticated_ok_records_client_and_application(self, monkeypatch):
        details = SimpleNamespace(
            name="app",
            accountName="acct",
            id="ydid:app:1",
            allNamespacesReadable=False,
            readableNamespaces=["ns"],
        )
        client = SimpleNamespace(
            application_client=SimpleNamespace(get_application_details=lambda: details)
        )
        monkeypatch.setattr(dc, "_build_client", lambda cfg: client)
        ctx = _ctx(config_loaded=True, config_common=self._cfg())
        r = dc.check_authenticated(ctx)
        assert (r.status, r.detail) == (
            dc.Status.OK,
            "application 'app' in account 'acct'",
        )
        assert ctx.client is client and ctx.application is details

    def test_authenticated_401_is_fail(self, monkeypatch):
        def boom():
            raise RuntimeError("401 Unauthorized")

        client = SimpleNamespace(
            application_client=SimpleNamespace(get_application_details=boom)
        )
        monkeypatch.setattr(dc, "_build_client", lambda cfg: client)
        r = dc.check_authenticated(_ctx(config_loaded=True, config_common=self._cfg()))
        assert r.status is dc.Status.FAIL and "not recognised" in r.detail

    def test_authenticated_other_error_is_fail_with_its_text(self, monkeypatch):
        def boom():
            raise RuntimeError("Service Unavailable")

        client = SimpleNamespace(
            application_client=SimpleNamespace(get_application_details=boom)
        )
        monkeypatch.setattr(dc, "_build_client", lambda cfg: client)
        ctx = _ctx(config_loaded=True, config_common=self._cfg())
        r = dc.check_authenticated(ctx)
        assert (r.status, r.detail) == (dc.Status.FAIL, "Service Unavailable")
        assert ctx.application is None

    def test_authenticated_timeout(self, monkeypatch):
        import time

        client = SimpleNamespace(
            application_client=SimpleNamespace(
                get_application_details=lambda: time.sleep(2)
            )
        )
        monkeypatch.setattr(dc, "_build_client", lambda cfg: client)
        r = dc.check_authenticated(
            _ctx(config_loaded=True, config_common=self._cfg(), timeout=0.1)
        )
        assert r.status is dc.Status.FAIL and "no answer" in r.detail

    def test_groups_and_roles(self, monkeypatch):
        import yellowdog_cli.utils.entity_utils as entity_utils

        monkeypatch.setattr(
            entity_utils,
            "get_application_group_summaries",
            lambda client, app_id: [SimpleNamespace(name="administrators")],
        )
        monkeypatch.setattr(
            entity_utils,
            "get_all_roles_and_namespaces_for_application",
            lambda client, app_id: {"admin": ["GLOBAL"]},
        )
        ctx = _ctx(config_loaded=True, config_common=self._cfg(), client=object())
        ctx.application = SimpleNamespace(id="ydid:app:1")
        r = dc.check_groups_and_roles(ctx)
        assert r.detail == "groups: administrators; roles: admin (GLOBAL)"

    def test_no_roles_warns(self, monkeypatch):
        import yellowdog_cli.utils.entity_utils as entity_utils

        monkeypatch.setattr(
            entity_utils, "get_application_group_summaries", lambda c, a: []
        )
        monkeypatch.setattr(
            entity_utils,
            "get_all_roles_and_namespaces_for_application",
            lambda c, a: {},
        )
        ctx = _ctx(config_loaded=True, config_common=self._cfg(), client=object())
        ctx.application = SimpleNamespace(id="ydid:app:1")
        r = dc.check_groups_and_roles(ctx)
        assert (r.status, r.detail) == (dc.Status.WARN, "groups: none; roles: none")

    def test_platform_rows_skip_when_not_authenticated(self):
        ctx = _ctx(config_loaded=True, config_common=self._cfg())
        for check in (dc.check_groups_and_roles, dc.check_namespace_granted):
            assert check(ctx) == dc.Result(dc.Status.SKIP, "not authenticated")

    def test_namespace_not_granted_warns(self):
        ctx = _ctx(
            config_loaded=True,
            config_common=self._cfg(namespace="other"),
            client=object(),
        )
        ctx.application = SimpleNamespace(
            allNamespacesReadable=False, readableNamespaces=["ns"]
        )
        r = dc.check_namespace_granted(ctx)
        assert r.status is dc.Status.WARN and "other" in r.detail

    def test_namespace_granted_globally(self):
        ctx = _ctx(
            config_loaded=True,
            config_common=self._cfg(namespace="anything"),
            client=object(),
        )
        ctx.application = SimpleNamespace(
            allNamespacesReadable=True, readableNamespaces=[]
        )
        assert dc.check_namespace_granted(ctx).status is dc.Status.OK

    def _remote(self, monkeypatch, stats: dict, name: str = "backup"):
        """
        The Remote reachable row, remote_stat answering from 'stats' (a
        path to its entry, None, or an exception to raise).
        """
        import yellowdog_cli.utils.dataclient_utils as dcu

        def stat(rclone, path):
            answer = stats[path]
            if isinstance(answer, Exception):
                raise answer
            return answer

        monkeypatch.setattr(dc, "_rclone_for_config", lambda cfg: ("remote", None))
        monkeypatch.setattr(dcu, "remote_stat", stat)
        ctx = _ctx(
            config_loaded=True,
            data_client=SimpleNamespace(remote="remote", bucket="b", prefix="p"),
            data_client_name=name,
        )
        return dc.check_data_client_remote(ctx)

    def test_data_client_remote_checks_the_prefix_and_names_the_profile(
        self, monkeypatch
    ):
        # The prefix, where the commands work: a policy scoped to it may
        # refuse the bucket's root although every command would work
        r = self._remote(monkeypatch, {"remote:b/p": {"IsDir": True}})
        assert (r.status, r.detail) == (
            dc.Status.OK,
            "remote:b/p reachable (profile backup)",
        )

    def test_a_prefix_not_created_yet_is_ok_in_a_bucket_that_is_there(
        self, monkeypatch
    ):
        r = self._remote(monkeypatch, {"remote:b/p": None, "remote:b": {"IsDir": True}})
        assert r.status is dc.Status.OK and "not created yet" in r.detail

    def test_a_bucket_that_is_not_there_fails(self, monkeypatch):
        r = self._remote(monkeypatch, {"remote:b/p": None, "remote:b": None})
        assert (r.status, r.detail) == (
            dc.Status.FAIL,
            "remote:b (profile backup): bucket not found",
        )

    def test_data_client_remote_failure_is_rclones_error(self, monkeypatch):
        error = RuntimeError(
            "Cannot access 'remote:b/p': 2026/09/25 ERROR : noise\n"
            "Failed to lsjson: permission denied\n"
        )
        r = self._remote(monkeypatch, {"remote:b/p": error}, name="[dataClient]")
        assert r.status is dc.Status.FAIL
        assert r.detail == (
            "remote:b/p (profile [dataClient]): Failed to lsjson: permission denied"
        )

    def test_a_server_error_from_the_platform_warns(self, monkeypatch):
        monkeypatch.setattr(
            dc.requests, "get", lambda url, timeout: SimpleNamespace(status_code=503)
        )
        ctx = _ctx(config_loaded=True, config_common=self._cfg())
        r = dc.check_platform_reachable(ctx)
        assert r.status is dc.Status.WARN and "503" in r.detail

    @pytest.mark.parametrize(
        "status, detail",
        [
            (401, "key or secret not recognised"),
            (403, "the Application is not permitted to read its own details"),
            (502, "the platform reported a server error"),
        ],
    )
    def test_authentication_failures_are_classified(self, monkeypatch, status, detail):
        from requests import HTTPError, Response

        response = Response()
        response.status_code = status

        def refuse():
            raise HTTPError(f"HTTP {status}", response=response)

        client = SimpleNamespace(
            application_client=SimpleNamespace(get_application_details=refuse)
        )
        monkeypatch.setattr(dc, "_build_client", lambda cfg: client)
        ctx = _ctx(config_loaded=True, config_common=self._cfg())
        r = dc.check_authenticated(ctx)
        assert (r.status, r.detail) == (dc.Status.FAIL, detail)
        assert r.remedy

    def test_authenticated_skips_when_the_sdk_did_not_import(self):
        ctx = _ctx(config_loaded=True, config_common=self._cfg())
        ctx.sdk_error = "No module named 'yellowdog_client'"
        assert dc.check_authenticated(ctx) == dc.Result(
            dc.Status.SKIP, "SDK did not import"
        )

    def test_live_checks_registered_in_order_and_needs(self):
        live = [
            (c.name, c.needs)
            for c in dc.CHECKS
            if c.group in ("Platform", "Data client")
        ]
        assert live == [
            ("Reachable", dc.Need.CONFIG_AND_NETWORK),
            ("Authenticated", dc.Need.CREDENTIALS_AND_NETWORK),
            ("Groups and roles", dc.Need.CREDENTIALS_AND_NETWORK),
            ("Namespace granted", dc.Need.CREDENTIALS_AND_NETWORK),
            ("Remote reachable", dc.Need.DATA_CLIENT),
        ]


def _run_doctor_online(tmp_path, env, config):
    """
    yd-doctor without --offline, against a URL that refuses at once, so that
    the data client rows run for real (rclone's local backend) without the
    platform rows waiting on a network.
    """
    config = '[common]\nkey = "k"\nsecret = "s"\nurl = "http://127.0.0.1:9"\n' + config
    return _run_doctor_without_offline(tmp_path, env=env, config=config)


def _run_doctor_without_offline(tmp_path, env, config):
    (tmp_path / "config.toml").write_text(config)
    result = subprocess.run(
        ["yd-doctor", "--json", "--timeout", "2"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    return {row["check"]: row for row in json.loads(result.stdout)}


class TestDataClientUnderTest:
    """The Remote reachable row tests the profile a data client command would use."""

    @pytest.fixture(autouse=True)
    def _needs_rclone(self):
        from yellowdog_cli.utils.rclone_version import find_rclone

        if find_rclone() is None:
            pytest.skip("rclone not installed")

    # The buckets are relative, resolved from the doctor's working directory
    # (tmp_path): resolve_remote_path(), whose path the commands use and so
    # the row checks, takes a bucket's leading '/' off

    def test_environment_alone_configures_it(self, tmp_path):
        (tmp_path / "data").mkdir()
        env = _clean_env(
            YD_DATA_CLIENT_REMOTE="loc,type=local", YD_DATA_CLIENT_BUCKET="data"
        )
        rows = _run_doctor_online(tmp_path, env, "")
        assert rows["Data client profile"]["status"] == "SKIP"
        row = rows["Remote reachable"]
        assert row["status"] == "OK", row
        # The default prefix is not there yet, in a bucket that is
        assert row["detail"].startswith("loc:data/")
        assert row["detail"].endswith(
            "reachable, not created yet (profile [dataClient])"
        )

    def test_yd_data_client_names_the_profile(self, tmp_path):
        (tmp_path / "other" / "pfx").mkdir(parents=True)
        config = (
            '[dataClient]\nremote = "loc,type=local"\nbucket = "absent"\n'
            '[dataClient.backup]\nbucket = "other"\nprefix = "pfx"\n'
        )
        rows = _run_doctor_online(tmp_path, _clean_env(YD_DATA_CLIENT="backup"), config)
        row = rows["Remote reachable"]
        assert row["status"] == "OK", row
        assert row["detail"] == "loc:other/pfx reachable (profile backup)"

    def test_an_absolute_bucket_is_reached_where_it_is(self, tmp_path):
        (tmp_path / "abs" / "pfx").mkdir(parents=True)
        config = (
            f'[dataClient]\nremote = "loc,type=local"\n'
            f'bucket = "{tmp_path / "abs"}"\nprefix = "pfx"\n'
        )
        # Run from elsewhere: the bucket must not be taken relative to it
        (tmp_path / "elsewhere").mkdir()
        rows = _run_doctor_online(tmp_path / "elsewhere", _clean_env(), config)
        row = rows["Remote reachable"]
        assert row["status"] == "OK", row
        assert (
            row["detail"]
            == f"loc:{tmp_path / 'abs' / 'pfx'} reachable (profile [dataClient])"
        )

    def test_a_missing_bucket_fails(self, tmp_path):
        config = '[dataClient]\nremote = "loc,type=local"\nbucket = "absent"\n'
        rows = _run_doctor_online(tmp_path, _clean_env(), config)
        row = rows["Remote reachable"]
        assert row["status"] == "FAIL"
        assert row["detail"] == "loc:absent (profile [dataClient]): bucket not found"

    def test_a_profile_that_does_not_load_is_named(self, tmp_path):
        config = '[dataClient]\nremote = "loc,type=local"\n'
        rows = _run_doctor_online(
            tmp_path, _clean_env(YD_DATA_CLIENT="nonesuch"), config
        )
        row = rows["Remote reachable"]
        assert row["status"] == "SKIP"
        assert "nonesuch" in row["detail"]


class TestSecretsStayOut:
    """
    The report is one the README says to paste into a support request, so
    no credential may reach it: not the [common] secret, not an inline
    remote's parameters, not a variable's value substituted into one.
    """

    SECRETS = ("SUPERSECRET-COMMON-7Q", "SUPERSECRET-REMOTE-4Z", "SUPERSECRET-VAR-9K")

    def _config(self) -> str:
        return (
            '[common]\nkey = "k"\nsecret = "SUPERSECRET-COMMON-7Q"\n'
            'url = "http://127.0.0.1:9"\n'
            "[dataClient]\n"
            'remote = ":s3,provider=Other,access_key_id={{MYTOKEN}},'
            "secret_access_key=SUPERSECRET-REMOTE-4Z,"
            'endpoint=http://127.0.0.1:9"\n'
            'bucket = "b"\n'
        )

    @pytest.mark.parametrize("live", [False, True], ids=["offline", "live"])
    @pytest.mark.parametrize(
        "output", [("--json",), (), ("--no-format",)], ids=["json", "table", "plain"]
    )
    def test_no_secret_appears(self, tmp_path, live, output):
        (tmp_path / "config.toml").write_text(self._config())
        args = ["yd-doctor", *output] + (["--timeout", "2"] if live else ["--offline"])
        result = subprocess.run(
            args,
            cwd=tmp_path,
            env=_clean_env(YD_VAR_MYTOKEN="SUPERSECRET-VAR-9K"),
            capture_output=True,
            text=True,
        )
        text = result.stdout + result.stderr
        assert "Data client profile [dataClient]" in text or "--json" in output
        for secret in self.SECRETS:
            assert secret not in text, f"{secret} in: {text}"
        if "--json" in output:
            rows = {row["check"]: row for row in json.loads(result.stdout)}
            assert rows["Data client profile [dataClient]"]["detail"].startswith(
                ":s3,provider=Other,<3 parameters redacted> b/"
            )
            if live:
                assert rows["Remote reachable"]["status"] != "SKIP"


class TestShownRemote:
    @pytest.mark.parametrize(
        "remote, shown",
        [
            ("myremote:", "myremote:"),
            (":s3,provider=AWS:", ":s3,provider=AWS:"),
            (
                ":s3,provider=AWS,access_key_id=AKIAEXAMPLE,secret_access_key=X:",
                ":s3,provider=AWS,<2 parameters redacted>:",
            ),
            ("loc,type=local", "loc,type=local"),
            ("r,type=s3,key=v", "r,type=s3,<1 parameter redacted>"),
        ],
    )
    def test_rendering(self, remote, shown):
        assert dc.shown_remote(remote) == shown

    def test_remote_reachable_names_the_remote_only(self, monkeypatch):
        remote = ":s3,provider=AWS,secret_access_key=SUPERSECRET:"
        rclone = SimpleNamespace(
            ls=lambda path, max_depth: SimpleNamespace(dirs=[], files=[])
        )
        monkeypatch.setattr(dc, "_rclone_for_config", lambda cfg: (":s3", rclone))
        ctx = _ctx(
            config_loaded=True,
            data_client=SimpleNamespace(remote=remote, bucket="b", prefix="p"),
            data_client_name="[dataClient]",
        )
        r = dc.check_data_client_remote(ctx)
        assert "SUPERSECRET" not in r.detail + (r.remedy or "")


class TestEntryPoint:
    def test_offline_no_config_exits_1_with_every_live_row_skipped(self, tmp_path):
        result = subprocess.run(
            ["yd-doctor", "--offline", "--nc"],
            cwd=tmp_path,
            env=_clean_env(),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "Key" in result.stdout and "FAIL" in result.stdout
        _, rows = _run_doctor(tmp_path, "--nc")
        assert all(
            rows[n]["status"] == "SKIP"
            for n in (
                "Reachable",
                "Authenticated",
                "Groups and roles",
                "Namespace granted",
            )
        )

    def test_quiet_prints_only_problems_and_summary(self, tmp_path):
        result = subprocess.run(
            # --no-format: one line per remedy, however long
            ["yd-doctor", "--offline", "--nc", "--quiet", "--no-format"],
            cwd=tmp_path,
            env=_clean_env(),
            capture_output=True,
            text=True,
        )
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        assert lines[-1].endswith("SKIP") and all(
            ("FAIL" in line or "WARN" in line or "checks:" in line) for line in lines
        )

    def test_quiet_config_load_failure_names_the_error(self, tmp_path):
        missing = tmp_path / "nonesuch-config.toml"
        result = subprocess.run(
            # --no-format: one line per remedy, however long
            [
                "yd-doctor",
                "--offline",
                "--quiet",
                "--no-format",
                "--config",
                str(missing),
            ],
            cwd=tmp_path,
            env=_clean_env(),
            capture_output=True,
            text=True,
        )
        line = next(
            line
            for line in result.stdout.splitlines()
            if line.startswith("FAIL Configuration loads:")
        )
        assert "nonesuch-config.toml" in line

    def test_readme_documents_it(self):
        text = (Path(__file__).parent.parent / "README.md").read_text()
        assert "\n### yd-doctor\n" in text
        assert "--offline" in text.split("### yd-doctor")[1].split("### yd-help")[0]


class TestLogging:
    def test_rclone_api_cannot_put_log_records_on_stdout(self):
        # rclone_api installs a stdout handler on the root logger at import
        # unless one exists; urllib3's retry warnings then broke --json
        script = (
            "import logging\n"
            "from yellowdog_cli import doctor\n"
            "doctor._keep_logging_off_stdout()\n"
            "import rclone_api\n"
            "logging.getLogger('urllib3.connectionpool').warning('Retrying')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=_clean_env(),
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""


class TestWithoutTheSdk:
    """
    An SDK that will not import is a diagnosis, not a crash: the doctor
    imports none at module level, reports it in the 'SDK imports' row, and
    the checks that need it skip.
    """

    def test_the_row_fails_and_records_why(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "yellowdog_client", None)
        ctx = _ctx()
        r = dc.check_sdk_imports(ctx)
        assert r.status is dc.Status.FAIL and r.remedy
        assert ctx.sdk_error

    def test_the_row_passes_with_the_sdk(self):
        assert dc.check_sdk_imports(_ctx()).status is dc.Status.OK

    def test_the_doctor_runs_with_the_sdk_blocked(self, tmp_path):
        # A fresh interpreter, the SDK made unimportable before anything
        # else is: the doctor must still print its rows
        probe = (
            "import sys; sys.modules['yellowdog_client'] = None;"
            " sys.argv = ['yd-doctor', '--offline', '--json'];"
            " from yellowdog_cli import doctor; doctor.main()"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=tmp_path,
            env=_clean_env(),
            capture_output=True,
            text=True,
        )
        rows = {row["check"]: row for row in json.loads(result.stdout)}
        assert rows["SDK imports"]["status"] == "FAIL", result.stderr
        assert result.returncode == 1
