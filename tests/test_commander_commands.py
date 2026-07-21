"""
Command-construction ("contract") tests for the Commander GUI: each action must
translate into the correct yd-* command and arguments. The app is built
offscreen and _run_command_in_subprocess is stubbed to capture the command
instead of spawning a process, so no yd-* command is actually run.
"""

from os.path import abspath, dirname, join

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from yellowdog_cli.commander.commander import RESULTS_DIR, YellowDogApp


@pytest.fixture
def window(qapp):
    return YellowDogApp()


@pytest.fixture
def captured(window, monkeypatch):
    """Capture (command, args) that an action would run, without spawning it."""
    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        window,
        "_run_command_in_subprocess",
        lambda command, args, **kwargs: calls.append((command, args)),
    )
    return calls


# --- Submit Work Requirement -------------------------------------------------


def test_submit_default_follows_progress(window, captured):
    # "Follow Work Requirement Progress" is checked by default (set in __init__),
    # so a fresh submit follows progress.
    window._submit_work_requirement_action()
    assert captured == [("yd-submit", ["-f"])]


def test_submit_no_follow_no_dry_run(window, captured):
    window.follow_progress.setChecked(False)
    window._submit_work_requirement_action()
    assert captured == [("yd-submit", [])]


def test_submit_with_wr_file_dry_run_and_extra_options(window, captured):
    window._wr_file = "wr.json"
    window.dry_run.setChecked(True)
    window.wr_submit_options.setPlainText("--foo bar")
    window._submit_work_requirement_action()
    assert captured == [("yd-submit", ["-r", "wr.json", "-D", "--foo", "bar"])]


def test_submit_follow_only_when_not_dry_run(window, captured):
    window.follow_progress.setChecked(True)
    window.dry_run.setChecked(True)
    window._submit_work_requirement_action()
    # Dry-run wins: -D present, -f suppressed.
    assert captured == [("yd-submit", ["-D"])]


def test_submit_follow(window, captured):
    window.follow_progress.setChecked(True)
    window._submit_work_requirement_action()
    assert captured == [("yd-submit", ["-f"])]


# --- Provision Worker Pool ---------------------------------------------------


def test_provision_default_follows(window, captured):
    # "Follow Worker Pool Progress" is checked by default (set in __init__).
    window._create_worker_pool_action()
    assert captured == [("yd-provision", ["-af"])]


def test_provision_no_follow(window, captured):
    window.follow_worker_pool.setChecked(False)
    window._create_worker_pool_action()
    assert captured == [("yd-provision", [])]


def test_provision_with_wp_file_and_follow(window, captured):
    window._wp_file = "wp.json"
    window.follow_worker_pool.setChecked(True)
    window._create_worker_pool_action()
    assert captured == [("yd-provision", ["-p", "wp.json", "-af"])]


def test_provision_dry_run(window, captured):
    window.dry_run_worker_pool.setChecked(True)
    window._create_worker_pool_action()
    assert captured == [("yd-provision", ["-D"])]


# --- Cancel / Shutdown / Terminate -------------------------------------------


def test_cancel(window, captured):
    window._cancel_work_requirements_action()
    assert captured == [("yd-cancel", ["-y"])]


def test_cancel_and_abort(window, captured):
    window._cancel_work_requirements_and_abort_action()
    assert captured == [("yd-cancel", ["-ay"])]


def test_shutdown(window, captured):
    window._shutdown_all_worker_pools_action()
    assert captured == [("yd-shutdown", ["-y"])]


def test_terminate(window, captured):
    window._terminate_all_compute_requirements_action()
    assert captured == [("yd-terminate", ["-y"])]


# --- Download / Delete -------------------------------------------------------


def test_download(window, captured):
    window._config_file = "cfg/config.toml"
    window._tag = "my-tag"
    window._download_results_action()
    expected_dst = join(dirname(abspath("cfg/config.toml")), RESULTS_DIR)
    assert captured == [("yd-download", ["-d", expected_dst, "my-tag*"])]


def test_delete_with_path_override_and_dry_run(window, captured):
    window.object_path_override.setPlainText("prefix/*")
    window.dry_run_objects.setChecked(True)
    window._delete_objects_action()
    assert captured == [("yd-delete", ["-Ry", "prefix/*", "-D"])]


# --- Namespace / tag / user-variable assembly --------------------------------


def test_namespace_tag_and_user_vars_assembly(window):
    window.user_variables.setPlainText("x=y a=b")
    window.namespace_override.setPlainText("my-ns")
    window.tag_override.setPlainText("my-tag")
    assert window._namespace_tag_and_user_vars() == [
        "-n",
        "my-ns",
        "-t",
        "my-tag",
        "-v",
        "x=y",
        "-v",
        "a=b",
    ]


def test_namespace_tag_and_user_vars_empty(window):
    assert window._namespace_tag_and_user_vars() == []


# --- Object path -------------------------------------------------------------


def test_object_path_defaults_to_tag_glob(window):
    window._tag = "my-tag"
    assert window._object_path() == "my-tag*"


def test_object_path_uses_override(window):
    window._tag = "my-tag"
    window.object_path_override.setPlainText("custom/path/*")
    assert window._object_path() == "custom/path/*"


# --- Config-file requirement -------------------------------------------------


def test_check_config_file_false_without_config(window):
    # No config selected -> operations are blocked (the documented "config
    # required" behaviour).
    assert window._config_file is None
    assert window._check_config_file(quiet=True) is False


# --- Follow / dry-run mutual exclusion ---------------------------------------


def test_follow_and_dry_run_are_mutually_exclusive_work(window):
    # Checking dry-run turns follow off; checking follow turns dry-run off.
    window.dry_run.setChecked(True)
    assert window.follow_progress.isChecked() is False
    window.follow_progress.setChecked(True)
    assert window.dry_run.isChecked() is False


def test_follow_and_dry_run_are_mutually_exclusive_worker_pool(window):
    window.dry_run_worker_pool.setChecked(True)
    assert window.follow_worker_pool.isChecked() is False
    window.follow_worker_pool.setChecked(True)
    assert window.dry_run_worker_pool.isChecked() is False
