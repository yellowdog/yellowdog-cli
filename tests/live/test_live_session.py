"""
Who owns the live run, offline: under xdist the controller sets it up once
and tears it down once, a worker only attaches to the run it is handed, a
lone process sets it up when first asked, and a session whose paths do not
reach tests/live sets nothing up.
"""

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from harness import config as config_module
from harness.config import load_live_config
from harness.lifecycle import SetupError
from live_samples import AWS, PLATFORM, write_config
from live_session import (
    LIVE_DIR,
    WORKER_INPUT,
    LiveSession,
    reaches_live_tests,
    selects_whole_suite,
)

REPO = LIVE_DIR.parent.parent


@pytest.fixture(autouse=True)
def _no_default_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "DEFAULT_PATH", tmp_path / "absent.toml")


class Calls:
    """
    The lifecycle as recorded calls, failing where told to.
    """

    def __init__(self, setup_fails: bool = False, problems=()) -> None:
        self.setups: list[str] = []
        self.teardowns: list[dict] = []
        self.sweeps = 0
        self._setup_fails = setup_fails
        self._problems = list(problems)

    def set_up(self, run, yd):
        if self._setup_fails:
            raise SetupError("creation failed")
        self.setups.append(run.run_id)

    def tear_down(self, yd, namespace, run_id, timeout, **kwargs):
        self.teardowns.append({"run_id": run_id, **kwargs})
        return self._problems

    def sweep_runs(self, *args, **kwargs):
        self.sweeps += 1
        return []


def _pytest_config(
    args=("tests/live",), workers=4, workerinput=None, collect_only=False
):
    config = SimpleNamespace(
        option=SimpleNamespace(
            numprocesses=workers,
            dist="load" if workers else "no",
            collectonly=collect_only,
        ),
        args=list(args),
        invocation_params=SimpleNamespace(dir=REPO),
        pluginmanager=SimpleNamespace(get_plugin=lambda name: None),
    )
    if workerinput is not None:
        config.workerinput = workerinput
    return config


def _session(tmp_path, calls: Calls, keep: bool = False, **config_args) -> LiveSession:
    text = PLATFORM + AWS + ("[run]\nkeep_on_failure = true\n" if keep else "")
    live = load_live_config(write_config(tmp_path, text))
    return LiveSession(
        _pytest_config(**config_args),
        load_config=lambda: live,
        make_yd=lambda run: SimpleNamespace(run=run),
        set_up=calls.set_up,
        tear_down=calls.tear_down,
        sweep_runs=calls.sweep_runs,
        make_parent=lambda: tmp_path / "runs",
        make_coverage_dir=lambda: Path(tempfile.mkdtemp(dir=tmp_path)),
    )


def _finish(session: LiveSession, exitstatus: int = 0) -> SimpleNamespace:
    pytest_session = SimpleNamespace(exitstatus=exitstatus)
    session.pytest_sessionfinish(pytest_session, exitstatus)
    return pytest_session


def test_the_controller_sets_up_once_hands_the_run_on_and_tears_down_once(tmp_path):
    calls = Calls()
    session = _session(tmp_path, calls)
    session.configure()
    assert len(calls.setups) == 1 and calls.sweeps == 1
    node = SimpleNamespace(workerinput={})
    session.pytest_configure_node(node)
    assert node.workerinput[WORKER_INPUT]["run_id"] == calls.setups[0]
    _finish(session)
    _finish(session)
    assert [t["run_id"] for t in calls.teardowns] == calls.setups


def test_paths_outside_live_set_up_nothing(tmp_path):
    calls = Calls()
    session = _session(tmp_path, calls, args=("tests/test_cancel.py",))
    session.configure()
    node = SimpleNamespace(workerinput={})
    session.pytest_configure_node(node)
    _finish(session)
    assert calls.setups == [] and calls.teardowns == []
    assert "run_id" not in node.workerinput.get(WORKER_INPUT, {})


def test_a_worker_attaches_to_the_run_it_was_handed(tmp_path):
    calls = Calls()
    directory = tmp_path / "runs" / "ydst-2610130811-ab12"
    directory.mkdir(parents=True)
    handed = {"run_id": "ydst-2610130811-ab12", "directory": str(directory)}
    session = _session(tmp_path, calls, workerinput={WORKER_INPUT: handed})
    session.configure()
    live = session.live_run()
    assert live.run.run_id == handed["run_id"] and live.run.directory == directory
    _finish(session)
    assert calls.setups == [] and calls.teardowns == []


def test_a_worker_handed_no_run_fails_saying_why(tmp_path):
    session = _session(tmp_path, Calls(), workerinput={})
    with pytest.raises(pytest.fail.Exception, match="set up no live run"):
        session.live_run()


def test_a_lone_process_sets_up_when_first_asked(tmp_path):
    calls = Calls()
    session = _session(tmp_path, calls, workers=0)
    session.configure()
    assert calls.setups == []
    first, second = session.live_run(), session.live_run()
    assert first is second and len(calls.setups) == 1
    _finish(session)
    assert len(calls.teardowns) == 1


def test_a_failed_setup_stops_the_session(tmp_path):
    session = _session(tmp_path, Calls(setup_fails=True))
    with pytest.raises(pytest.exit.Exception, match="creation failed"):
        session.configure()


def test_a_failed_session_keeps_the_run_when_asked(tmp_path):
    calls = Calls()
    session = _session(tmp_path, calls, keep=True)
    session.configure()
    _finish(session, exitstatus=1)
    assert calls.teardowns[0]["remove"] is False


def test_teardown_problems_fail_the_session(tmp_path):
    session = _session(tmp_path, Calls(problems=["still alive"]))
    session.configure()
    assert _finish(session).exitstatus == pytest.ExitCode.TESTS_FAILED


@pytest.mark.parametrize(
    ("arg", "reaches"),
    [
        ("tests/live", True),
        ("tests/live/test_live_config.py::test_x", True),
        (".", True),
        ("tests/test_cancel.py", False),
        ("yellowdog_cli", False),
    ],
)
def test_which_paths_reach_the_live_tests(arg, reaches):
    assert reaches_live_tests([arg], REPO) is reaches


def test_a_path_holding_live_reaches_it():
    assert reaches_live_tests(["tests"], REPO) is True


def test_collecting_only_sets_nothing_up(tmp_path):
    # xdist starts no workers under '--collect-only', so nothing would use it
    calls = Calls()
    session = _session(tmp_path, calls, collect_only=True)
    session.configure()
    assert calls.setups == [] and calls.sweeps == 0


def test_a_run_set_up_but_never_finished_is_torn_down_at_unconfigure(tmp_path):
    # A later start-up failure skips pytest_sessionfinish
    calls = Calls()
    session = _session(tmp_path, calls)
    session.configure()
    session.pytest_unconfigure(SimpleNamespace())
    assert [t["run_id"] for t in calls.teardowns] == calls.setups
    assert calls.teardowns[0].get("remove", True) is True


def test_unconfigure_after_a_finished_session_tears_nothing_down_again(tmp_path):
    calls = Calls()
    session = _session(tmp_path, calls)
    session.configure()
    _finish(session)
    session.pytest_unconfigure(SimpleNamespace())
    assert len(calls.teardowns) == 1


@pytest.mark.parametrize(
    ("args", "keyword", "markexpr", "whole"),
    [
        (("tests/live",), "", "", True),
        (("tests",), "", "", True),
        ((".",), "", "", True),
        (("tests/live",), "providers", "", False),
        (("tests/live",), "", "live", False),
        (("tests/live/test_live_providers.py",), "", "", False),
        (("tests/live", "tests/live/test_live_data.py"), "", "", False),
    ],
)
def test_the_gate_is_skipped_for_a_narrowed_session(args, keyword, markexpr, whole):
    config = SimpleNamespace(
        args=list(args),
        invocation_params=SimpleNamespace(dir=REPO),
        option=SimpleNamespace(keyword=keyword, markexpr=markexpr),
    )
    assert selects_whole_suite(config) is whole


def test_the_controller_hands_its_coverage_directory_to_workers(tmp_path):
    session = _session(tmp_path, Calls())
    session.configure()
    node = SimpleNamespace(workerinput={})
    session.pytest_configure_node(node)
    assert Path(node.workerinput[WORKER_INPUT]["coverage_dir"]).is_dir()


def test_a_whole_suite_session_fails_on_the_gate_before_teardown(tmp_path):
    calls = Calls()
    session = _session(tmp_path, calls)
    session.configure()
    finished = _finish(session)
    assert finished.exitstatus == pytest.ExitCode.TESTS_FAILED  # nothing recorded
    assert len(calls.teardowns) == 1  # teardown still ran


def test_a_narrowed_session_does_not_run_the_gate(tmp_path):
    calls = Calls()
    session = _session(tmp_path, calls, args=("tests/live/test_live_setup.py",))
    session.configure()
    assert _finish(session).exitstatus == 0


def test_the_owner_removes_its_coverage_directory_after_the_gate(tmp_path):
    session = _session(tmp_path, Calls())
    session.configure()
    node = SimpleNamespace(workerinput={})
    session.pytest_configure_node(node)
    directory = Path(node.workerinput[WORKER_INPUT]["coverage_dir"])
    assert directory.is_dir()
    _finish(session)
    assert not directory.exists()


def test_the_coverage_directory_is_made_where_the_session_is_told(tmp_path):
    session = _session(tmp_path, Calls())
    session.configure()
    node = SimpleNamespace(workerinput={})
    session.pytest_configure_node(node)
    assert Path(node.workerinput[WORKER_INPUT]["coverage_dir"]).parent == tmp_path


def test_a_passing_gate_says_so(tmp_path, capsys):
    from harness import coverage

    session = _session(tmp_path, Calls())
    session.configure()
    for command in coverage.expected():
        coverage.record(tuple(command.split()[1:]))
    _finish(session)
    assert "coverage gate: passed" in capsys.readouterr().out


def test_the_configurations_warnings_are_shown_with_its_summary(tmp_path, capsys):
    text = PLATFORM + AWS + '[run]\nnamespace = "elsewhere"\n'
    live = load_live_config(write_config(tmp_path, text))
    session = LiveSession(_pytest_config(workers=0), load_config=lambda: live)
    session.live_config()
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("live config:")
    assert lines[1].startswith("live config: warning: [run] namespace")
