"""
The user's own configuration file, $XDG_CONFIG_HOME/yellowdog/config.toml
(~/.config/yellowdog/config.toml without it): used when the current
directory has no config.toml and none is named with --config, read as
./config.toml is (the environment ahead of it), and named where yd says
which file it read or that it found none.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from yellowdog_cli.utils.paths import default_config_file, user_config_file


@pytest.fixture
def user_home(tmp_path, monkeypatch) -> Path:
    """
    An XDG_CONFIG_HOME of the test's own, holding no file yet.
    """
    home = tmp_path / "xdg"
    home.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    return home


def _write_user_config(home: Path, text: str) -> Path:
    path = home / "yellowdog" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestWhereItIs:
    def test_under_xdg_config_home(self, user_home):
        assert user_config_file() == os.path.join(
            str(user_home), "yellowdog", "config.toml"
        )

    def test_under_dot_config_without_it(self, monkeypatch, tmp_path):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        assert user_config_file() == os.path.join(
            str(tmp_path), ".config", "yellowdog", "config.toml"
        )


class TestWhichFileIsRead:
    def test_the_current_directorys_first(self, user_home, tmp_path, monkeypatch):
        _write_user_config(user_home, "")
        work = tmp_path / "work"
        work.mkdir()
        (work / "config.toml").write_text("", encoding="utf-8")
        monkeypatch.chdir(work)
        assert default_config_file() == "config.toml"

    def test_the_users_when_the_current_directory_has_none(
        self, user_home, tmp_path, monkeypatch
    ):
        path = _write_user_config(user_home, "")
        work = tmp_path / "work"
        work.mkdir()
        monkeypatch.chdir(work)
        assert default_config_file() == str(path)

    def test_config_toml_when_there_is_neither(self, user_home, tmp_path, monkeypatch):
        work = tmp_path / "work"
        work.mkdir()
        monkeypatch.chdir(work)
        assert default_config_file() == "config.toml"


def _yd(*args: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith("YD_")
    }
    environment.update(env)
    return subprocess.run(
        [sys.executable, "-m", "yellowdog_cli.yd", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        cwd=cwd,
        timeout=120,
    )


class TestThroughACommand:
    def test_a_command_reads_the_users_file(self, user_home, tmp_path):
        _write_user_config(
            user_home,
            '[common]\nnamespace = "from-user-file"\ntag = "t"\n'
            '[common.variables]\nwhere = "user"\n',
        )
        work = tmp_path / "work"
        work.mkdir()
        result = _yd(
            "variables",
            "--quiet",
            "where",
            "namespace",
            cwd=work,
            env={"XDG_CONFIG_HOME": str(user_home)},
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {
            "where": "user",
            "namespace": "from-user-file",
        }

    def test_the_environment_wins_over_it_as_over_config_toml(
        self, user_home, tmp_path
    ):
        _write_user_config(user_home, '[common]\nnamespace = "from-user-file"\n')
        work = tmp_path / "work"
        work.mkdir()
        result = _yd(
            "variables",
            "--quiet",
            "namespace",
            cwd=work,
            env={
                "XDG_CONFIG_HOME": str(user_home),
                "YD_NAMESPACE": "from-environment",
            },
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {"namespace": "from-environment"}

    def test_the_current_directorys_file_wins(self, user_home, tmp_path):
        _write_user_config(user_home, '[common]\nnamespace = "from-user-file"\n')
        work = tmp_path / "work"
        work.mkdir()
        (work / "config.toml").write_text(
            '[common]\nnamespace = "from-local-file"\n', encoding="utf-8"
        )
        result = _yd(
            "variables",
            "--quiet",
            "namespace",
            cwd=work,
            env={"XDG_CONFIG_HOME": str(user_home)},
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {"namespace": "from-local-file"}

    def test_with_neither_the_error_names_both_places(self, user_home, tmp_path):
        work = tmp_path / "work"
        work.mkdir()
        result = _yd("wr", "list", cwd=work, env={"XDG_CONFIG_HOME": str(user_home)})
        assert result.returncode == 3
        assert os.path.join("yellowdog", "config.toml") in result.stderr.replace(
            "\n", ""
        ).replace(" ", "")


def test_a_dot_env_in_the_current_directory_comes_before_one_beside_the_users_file(
    user_home, tmp_path, monkeypatch
):
    from yellowdog_cli.utils.misc_utils import dotenv_file_path

    user_file = _write_user_config(user_home, "")
    (user_file.parent / ".env").write_text("YD_X=user\n", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    (work / ".env").write_text("YD_X=local\n", encoding="utf-8")
    monkeypatch.chdir(work)
    assert dotenv_file_path(None) == str(work / ".env")


def test_a_dot_env_beside_the_users_file_without_one_here(
    user_home, tmp_path, monkeypatch
):
    from yellowdog_cli.utils.misc_utils import dotenv_file_path

    user_file = _write_user_config(user_home, "")
    (user_file.parent / ".env").write_text("YD_X=user\n", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    assert dotenv_file_path(None) == str(user_file.parent / ".env")
