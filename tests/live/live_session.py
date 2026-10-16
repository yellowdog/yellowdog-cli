"""
Who owns the live run. Under xdist the controller, which never collects a
test (so never loads tests/live/conftest.py), sets the run up as the session
starts, when the command line's paths reach tests/live, and hands its ID and
directory to every worker; a worker only attaches to it. A lone process sets
it up when the first live test asks. Whoever set it up tears it down when
the session finishes, once every worker has, having first run the coverage
gate (harness/coverage.py) when the session ran the whole live suite. The
owner also makes the session's coverage directory and hands it to every
worker. The root conftest.py registers this plugin under '--run-live'.
"""

from __future__ import annotations

import shutil
import tempfile
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
from harness import coverage, data
from harness.config import LiveConfig, LiveConfigError, load_live_config
from harness.lifecycle import SetupError, setup, sweep, teardown
from harness.run import Run
from harness.yd import Yd

PLUGIN_NAME = "ydst-live-session"
WORKER_INPUT = "ydst_run"
LIVE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class LiveRun:
    """
    The session's run, and the 'yd' that acts for it.
    """

    run: Run
    yd: Yd


def reaches_live_tests(args: list[str], invocation_dir: Path) -> bool:
    """
    Whether a path on the command line is in tests/live or holds it.
    """
    for arg in args:
        path = (invocation_dir / arg.split("::", 1)[0]).resolve()
        if path == LIVE_DIR or LIVE_DIR in path.parents or path in LIVE_DIR.parents:
            return True
    return False


def is_distributing(config) -> bool:
    """
    Whether this process is an xdist controller with workers to hand to:
    under '--collect-only' xdist starts none.
    """
    if hasattr(config, "workerinput") or getattr(config.option, "collectonly", False):
        return False
    return bool(getattr(config.option, "numprocesses", None)) and (
        getattr(config.option, "dist", "no") != "no"
    )


def selects_whole_suite(config) -> bool:
    """
    Whether the session runs the whole live suite: a path that is tests/live
    or holds it, none inside it, no node ID, and no '-k' or '-m'.
    """
    option = config.option
    if getattr(option, "keyword", "") or getattr(option, "markexpr", ""):
        return False
    if any("::" in arg for arg in config.args):
        return False
    paths = [
        (Path(config.invocation_params.dir) / arg).resolve() for arg in config.args
    ]
    reaches = any(p == LIVE_DIR or p in LIVE_DIR.parents for p in paths)
    narrower = any(LIVE_DIR in p.parents for p in paths)
    return reaches and not narrower


def _temporary_parent() -> Path:
    return Path(tempfile.mkdtemp(prefix="ydst-"))


def _temporary_coverage_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="ydst-coverage-"))


class LiveSession:
    """
    The live run's owner, or a worker's view of it.
    """

    def __init__(
        self,
        config,
        *,
        load_config: Callable[[], LiveConfig] = load_live_config,
        make_yd: Callable[[Run], Yd] = Yd,
        set_up: Callable = setup,
        tear_down: Callable = teardown,
        sweep_runs: Callable = sweep,
        make_parent: Callable[[], Path] = _temporary_parent,
        make_coverage_dir: Callable[[], Path] = _temporary_coverage_dir,
    ) -> None:
        self._config = config
        self._load_config = load_config
        self._make_yd = make_yd
        self._set_up = set_up
        self._tear_down = tear_down
        self._sweep = sweep_runs
        self._make_parent = make_parent
        self._make_coverage_dir = make_coverage_dir
        self._live_config: LiveConfig | None = None
        self._live_run: LiveRun | None = None
        self._owned = False
        self._coverage_dir: Path | None = None

    def _write_line(self, text: str) -> None:
        reporter = self._config.pluginmanager.get_plugin("terminalreporter")
        (reporter.write_line if reporter is not None else print)(text)

    def configure(self) -> None:
        """
        Record coverage to the session's directory (the owner makes it, a
        worker is handed it); then, on an xdist controller whose paths reach
        tests/live, set the run up now, before any worker starts; a setup
        failure stops the session.
        """
        workerinput = getattr(self._config, "workerinput", None)
        if workerinput is not None:
            handed = workerinput.get(WORKER_INPUT) or {}
            if "coverage_dir" in handed:
                self._coverage_dir = Path(handed["coverage_dir"])
        else:
            self._coverage_dir = self._make_coverage_dir()
        coverage.configure(self._coverage_dir)
        if not is_distributing(self._config):
            return
        if not reaches_live_tests(
            list(self._config.args), Path(self._config.invocation_params.dir)
        ):
            return
        try:
            self._start()
        except SetupError as error:
            pytest.exit(
                f"Live run setup failed:\n{error}",
                returncode=pytest.ExitCode.TESTS_FAILED,
            )

    def live_config(self) -> LiveConfig:
        """
        The configuration, read once; a problem ends the session.
        """
        if self._live_config is None:
            try:
                self._live_config = self._load_config()
            except LiveConfigError as error:
                pytest.exit(str(error), returncode=pytest.ExitCode.USAGE_ERROR)
            self._write_line(self._live_config.summary())
            for warning in self._live_config.warnings:
                self._write_line(f"live config: warning: {warning}")
        return self._live_config

    def live_run(self) -> LiveRun:
        """
        The session's run: a worker's as handed to it, else this process's,
        set up on first use.
        """
        if self._live_run is not None:
            return self._live_run
        workerinput = getattr(self._config, "workerinput", None)
        if workerinput is None:
            return self._start()
        handed = workerinput.get(WORKER_INPUT) or {}
        if "run_id" not in handed:
            pytest.fail(
                "The xdist controller set up no live run: give tests/live, or a"
                " directory holding it, on the command line",
                pytrace=False,
            )
        run = Run(self.live_config(), handed["run_id"], Path(handed["directory"]))
        self._live_run = LiveRun(run, self._make_yd(run))
        return self._live_run

    def _start(self) -> LiveRun:
        config = self.live_config()
        settings = config.run
        run = Run.start(config, self._make_parent())
        yd = self._make_yd(run)
        if settings["sweep_on_start"]:
            older_than = timedelta(hours=settings["sweep_age_hours"])
            for problem in self._sweep(
                yd,
                run.namespace,
                older_than,
                settings["teardown_timeout_minutes"],
                report=self._write_line,
                data=data.local_remote(config) is not None,
            ):
                warnings.warn(f"sweep: {problem}", stacklevel=1)
        self._write_line(f"live run {run.run_id} in namespace {run.namespace}")
        self._set_up(run, yd)
        self._live_run = LiveRun(run, yd)
        self._owned = True
        return self._live_run

    @pytest.hookimpl(optionalhook=True)
    def pytest_configure_node(self, node) -> None:
        handed: dict[str, str] = {}
        if self._coverage_dir is not None:
            handed["coverage_dir"] = str(self._coverage_dir)
        if self._live_run is not None:
            run = self._live_run.run
            handed.update(run_id=run.run_id, directory=str(run.directory))
        if handed:
            node.workerinput[WORKER_INPUT] = handed

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus) -> None:
        gate_problems = self._gate()
        self._remove_coverage_dir()
        problems = self._finish(keep_if_asked=exitstatus != pytest.ExitCode.OK)
        if problems or gate_problems:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def _remove_coverage_dir(self) -> None:
        """
        The owner's coverage directory, read by the gate, is removed after it.
        """
        if self._coverage_dir is not None and not hasattr(self._config, "workerinput"):
            shutil.rmtree(self._coverage_dir, ignore_errors=True)
            coverage.configure(None)

    def _gate(self) -> list[str]:
        """
        The coverage gate, for a whole-suite session that set a run up; it
        leaves out the data verbs, saying why, when they cannot run.
        """
        if not self._owned or self._live_run is None or self._coverage_dir is None:
            return []
        if not selects_whole_suite(self._config):
            self._write_line(
                "coverage gate: skipped (the session ran part of the suite)"
            )
            return []
        reason = data.unavailable(self._live_run.run.config)
        excluded = {c: reason for c in coverage.DATA_COMMANDS} if reason else {}
        for command in sorted(excluded):
            self._write_line(f"coverage gate: left out {command}: {reason}")
        problems = coverage.gate(self._coverage_dir, excluded)
        if problems:
            self._write_line("coverage gate failed:\n" + "\n".join(problems))
        else:
            counted = (
                len(coverage.expected()) - len(coverage.NOT_EXERCISED) - len(excluded)
            )
            self._write_line(
                f"coverage gate: passed ({counted} commands exercised,"
                f" {len(coverage.NOT_EXERCISED)} not exercised, each with its reason)"
            )
        return problems

    def pytest_unconfigure(self, config) -> None:
        """
        The fallback: a start-up failure after the run was set up skips
        pytest_sessionfinish, so a run still owned here is torn down now, and
        the coverage directory removed.
        """
        self._finish(keep_if_asked=False)
        self._remove_coverage_dir()

    def _finish(self, *, keep_if_asked: bool) -> list[str]:
        """
        Tear the owned run down, once, returning the problems; with
        'keep_if_asked' and 'keep_on_failure', keep it.
        """
        if not self._owned or self._live_run is None:
            return []
        run, yd = self._live_run.run, self._live_run.yd
        self._live_run, self._owned = None, False
        settings = run.config.run
        keep = keep_if_asked and settings["keep_on_failure"]
        problems = self._tear_down(
            yd,
            run.namespace,
            run.run_id,
            settings["teardown_timeout_minutes"],
            stop_compute=not keep or settings["terminate_on_keep"],
            remove=not keep,
            data=data.local_remote(run.config) is not None,
        )
        if keep:
            self._write_line(
                f"kept run {run.run_id}; tear it down with:"
                f" python tests/live/sweep.py --run {run.run_id}"
            )
        if problems:
            self._write_line(
                f"Teardown of run {run.run_id} left problems:\n" + "\n".join(problems)
            )
        return problems
