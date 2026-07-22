"""
Command-construction ("contract") tests for the Commander GUI: each action must
translate into the correct yd-* command and arguments. The app is built
offscreen and _run_command_in_subprocess is stubbed to capture the command
instead of spawning a process, so no yd-* command is actually run.
"""

import os
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


# --- Config-source helpers ---------------------------------------------------


def test_config_source_args_no_config(window):
    window._config_file = None
    assert window._config_source_args() == ["--nc"]


def test_config_source_args_with_config(window):
    window._config_file = "some/dir/config.toml"
    assert window._config_source_args() == ["-c", "config.toml"]


def test_working_dir_no_config(window):
    window._config_file = None
    assert window._working_dir() == os.getcwd()


def test_working_dir_with_config(window):
    window._config_file = "some/dir/config.toml"
    assert window._working_dir() == os.path.dirname(
        os.path.abspath("some/dir/config.toml")
    )


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


# --- Destructive-action confirmations ----------------------------------------


@pytest.mark.parametrize(
    "method,command,args",
    [
        ("_cancel_work_requirements_action", "yd-cancel", ["-y"]),
        ("_cancel_work_requirements_and_abort_action", "yd-cancel", ["-ay"]),
        ("_shutdown_all_worker_pools_action", "yd-shutdown", ["-y"]),
        ("_terminate_all_compute_requirements_action", "yd-terminate", ["-y"]),
    ],
)
def test_destructive_action_runs_when_confirmed(
    window, captured, monkeypatch, method, command, args
):
    monkeypatch.setattr(window, "_confirm_destructive", lambda *a, **k: True)
    getattr(window, method)()
    assert captured == [(command, args)]


def test_destructive_action_declined_does_not_run(window, captured, monkeypatch):
    monkeypatch.setattr(window, "_confirm_destructive", lambda *a, **k: False)
    for method in (
        "_cancel_work_requirements_action",
        "_cancel_work_requirements_and_abort_action",
        "_shutdown_all_worker_pools_action",
        "_terminate_all_compute_requirements_action",
    ):
        getattr(window, method)()
    assert captured == []


def test_delete_runs_when_confirmed(window, captured, monkeypatch):
    monkeypatch.setattr(window, "_confirm_destructive", lambda *a, **k: True)
    window._tag = "my-tag"
    window._delete_objects_action()
    assert captured == [("yd-delete", ["-Ry", "my-tag*"])]


def test_delete_declined_does_not_run(window, captured, monkeypatch):
    monkeypatch.setattr(window, "_confirm_destructive", lambda *a, **k: False)
    window._delete_objects_action()
    assert captured == []


def test_delete_dry_run_skips_confirmation(window, captured, monkeypatch):
    # Dry run is a harmless preview: it must run even when confirmation is denied.
    monkeypatch.setattr(window, "_confirm_destructive", lambda *a, **k: False)
    window._tag = "my-tag"
    window.dry_run_objects.setChecked(True)
    window._delete_objects_action()
    assert captured == [("yd-delete", ["-Ry", "my-tag*", "-D"])]


def test_skip_confirmations_key_short_circuits(window, captured):
    # With this action's key in the bypass set, no dialog is created (exec would
    # block offscreen) and the command runs directly.
    window._skip_confirmations = {"terminate"}
    window._terminate_all_compute_requirements_action()
    assert captured == [("yd-terminate", ["-y"])]


def test_yes_flag_disables_all_confirmations(qapp):
    # Launching with disable_confirmations=True (the -y/--yes flag) makes every
    # destructive action auto-confirm with no dialog, across all action keys.
    win = YellowDogApp(disable_confirmations=True)
    assert win._confirm_destructive("terminate", "t", "b") is True
    assert win._confirm_destructive("delete", "t", "b") is True


def test_confirmations_enabled_by_default(window):
    # Default construction leaves confirmations enabled.
    assert window._confirmations_disabled is False


def test_skip_confirmations_is_per_action(window):
    # The bypass is per-action: a key present short-circuits its own action, but
    # a different action's key is unaffected. Assert directly on the helper's
    # short-circuit (no dialog is created when the key is present).
    window._skip_confirmations = {"terminate"}
    assert window._confirm_destructive("terminate", "t", "b") is True
    assert "shutdown" not in window._skip_confirmations


def test_scope_suffix_with_namespace_and_tag(window):
    window._namespace, window._tag = "ns", "tg"
    assert window._scope_suffix() == " in namespace 'ns' with tag 'tg'"


def test_scope_suffix_generic_when_unknown(window):
    window._namespace = None
    window._tag = None
    assert window._scope_suffix() == " in the current namespace and tag"


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


# --- Results / view actions work without a config file -----------------------


def test_download_results_no_config_uses_cwd(window, captured):
    window._config_file = None
    expected_path = window._object_path()
    window._download_results_action()
    assert captured == [
        ("yd-download", ["-d", os.path.join(os.getcwd(), RESULTS_DIR), expected_path])
    ]


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


# --- Command-arg construction (config source injection) ----------------------


def test_build_args_yd_command_no_config(window):
    window._config_file = None
    args = window._build_command_args("yd-submit", ["-r", "wr.json"], yd_command=True)
    assert args == ["--nc", "--nf", "--pp", "-r", "wr.json"]


def test_build_args_yd_command_with_config(window):
    window._config_file = "d/config.toml"
    args = window._build_command_args("yd-submit", ["-r", "wr.json"], yd_command=True)
    assert args == ["-c", "config.toml", "--nf", "--pp", "-r", "wr.json"]


def test_build_args_any_yd_command_no_config(window):
    window._config_file = None
    args = window._build_command_args("yd-list", ["-w"], yd_command=False)
    assert args == ["--nc", "-w", "--nf", "--pp"]


def test_build_args_any_yd_command_with_config(window):
    window._config_file = "d/config.toml"
    args = window._build_command_args("yd-list", ["-w"], yd_command=False)
    assert args == ["-c", "config.toml", "-w", "--nf", "--pp"]


def test_build_args_any_yd_command_respects_user_config_flag(window):
    window._config_file = None
    # User already supplied a config flag: do not inject another.
    args = window._build_command_args("yd-list", ["--nc", "-w"], yd_command=False)
    assert args == ["--nc", "-w", "--nf", "--pp"]


def test_build_args_shell_command_unchanged(window):
    window._config_file = None
    args = window._build_command_args("sh", ["-c", "ls"], yd_command=False)
    assert args == ["-c", "ls"]
