"""
Command-construction ("contract") tests for the Commander GUI: each action must
translate into the correct yd-* command and arguments. The app is built
offscreen and _run_command_in_subprocess is stubbed to capture the command
instead of spawning a process, so no yd-* command is actually run.
"""

import os
from os.path import abspath, dirname, join

import pytest
import qt_guard

qt_guard.require_qt()

from yellowdog_cli.commander.commander import (
    RESULTS_DIR,
    Confirmation,
    EntitySummary,
    ObjectSummary,
    YellowDogApp,
)


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


def test_destructive_action_runs_when_confirmed(window, captured, monkeypatch):
    entity = EntitySummary(id="ydid:x:1", name="x", status="RUNNING")
    monkeypatch.setattr(
        window, "_capture_dry_run_summaries", lambda command, extra_args=None: [entity]
    )
    monkeypatch.setattr(
        window,
        "_confirm_destructive",
        lambda *a, **k: Confirmation(proceed=True, handles=[entity.id]),
    )
    for method, command, args in [
        ("_cancel_work_requirements_action", "yd-cancel", ["-y", "ydid:x:1"]),
        (
            "_cancel_work_requirements_and_abort_action",
            "yd-cancel",
            ["-ay", "ydid:x:1"],
        ),
        ("_shutdown_all_worker_pools_action", "yd-shutdown", ["-y", "ydid:x:1"]),
        (
            "_terminate_all_compute_requirements_action",
            "yd-terminate",
            ["-y", "ydid:x:1"],
        ),
    ]:
        captured.clear()
        getattr(window, method)()
        assert captured == [(command, args)]


def test_name_glob_appended_on_confirmation_bypass(window, captured):
    window._skip_confirmations = {"terminate"}
    window.name_glob_override.setPlainText("cr-*")
    window._terminate_all_compute_requirements_action()
    assert captured == [("yd-terminate", ["-y", "cr-*"])]


def test_empty_name_glob_adds_no_positional(window, captured, monkeypatch):
    # A blank/whitespace-only Name field leaves the enumeration unfiltered.
    entity = EntitySummary(id="ydid:x:1", name="m", status="RUNNING")
    seen: list = []
    monkeypatch.setattr(
        window,
        "_capture_dry_run_summaries",
        lambda command, extra_args=None: seen.append(extra_args) or [entity],
    )
    monkeypatch.setattr(
        window,
        "_confirm_destructive",
        lambda *a, **k: Confirmation(proceed=True, handles=[entity.id]),
    )
    window.name_glob_override.setPlainText("   ")
    window._cancel_work_requirements_action()
    assert seen == [[]]
    assert captured == [("yd-cancel", ["-y", "ydid:x:1"])]


def test_destructive_action_declined_does_not_run(window, captured, monkeypatch):
    entity = EntitySummary(id="ydid:x:1", name="x", status="RUNNING")
    monkeypatch.setattr(
        window, "_capture_dry_run_summaries", lambda command, extra_args=None: [entity]
    )
    monkeypatch.setattr(
        window,
        "_confirm_destructive",
        lambda *a, **k: Confirmation(proceed=False, handles=None),
    )
    for method in (
        "_cancel_work_requirements_action",
        "_cancel_work_requirements_and_abort_action",
        "_shutdown_all_worker_pools_action",
        "_terminate_all_compute_requirements_action",
    ):
        getattr(window, method)()
    assert captured == []


def test_destructive_empty_set_logs_and_skips(window, captured, monkeypatch):
    monkeypatch.setattr(
        window, "_capture_dry_run_summaries", lambda command, extra_args=None: []
    )
    window.log_output.setPlainText("")
    window._terminate_all_compute_requirements_action()
    assert captured == []
    assert "No matching Compute Requirements" in window.log_output.toPlainText()


def test_destructive_logs_status_before_lookup(window, captured, monkeypatch):
    # A status line is logged before the (blocking) enumeration so the GUI does
    # not read as frozen during the lookup.
    logged: list[str] = []
    monkeypatch.setattr(
        window,
        "_capture_dry_run_summaries",
        lambda command, extra_args=None: (
            logged.append("looked-up")
            or [EntitySummary(id="ydid:x:1", name="cr-1", status="RUNNING")]
        ),
    )
    monkeypatch.setattr(
        window,
        "_confirm_destructive",
        lambda *a, **k: Confirmation(proceed=True, handles=["ydid:x:1"]),
    )
    window.log_output.setPlainText("")
    window._terminate_all_compute_requirements_action()
    assert "Checking which Compute Requirements would be affected" in (
        window.log_output.toPlainText()
    )
    assert logged == ["looked-up"]  # enumeration did run


def test_destructive_confirmation_body_reflects_name_glob(
    window, captured, monkeypatch
):
    # With a Name pattern set, the confirmation body describes the glob scope,
    # not the tag scope.
    monkeypatch.setattr(
        window,
        "_capture_dry_run_summaries",
        lambda command, extra_args=None: [
            EntitySummary(id="ydid:x:1", name="cr-1", status="RUNNING")
        ],
    )
    calls = []
    monkeypatch.setattr(
        window,
        "_confirm_destructive",
        lambda action_key, title, body, names=None, rows=None: (
            calls.append(body) or Confirmation(proceed=True, handles=["ydid:x:1"])
        ),
    )
    window._namespace, window._tag = "yd-demo", "pyex"
    window.name_glob_override.setPlainText("ci-*")
    window._terminate_all_compute_requirements_action()
    body = calls[0]
    assert "matching name pattern 'ci-*'" in body
    assert "in namespace 'yd-demo'" in body
    assert "with tags including" not in body


def test_destructive_enumeration_failure_falls_back_to_scope(
    window, captured, monkeypatch
):
    monkeypatch.setattr(
        window, "_capture_dry_run_summaries", lambda command, extra_args=None: None
    )
    calls = []
    monkeypatch.setattr(
        window,
        "_confirm_destructive",
        lambda action_key, title, body, names=None, rows=None: (
            calls.append((body, rows)) or Confirmation(proceed=True, handles=None)
        ),
    )
    window._terminate_all_compute_requirements_action()
    assert captured == [("yd-terminate", ["-y"])]
    body, entities = calls[0]
    assert "Terminating Compute Requirements" in body
    assert entities is None  # scope-level fallback lists nothing


def test_build_destructive_dialog_without_rows_has_no_listing(window):
    # The read-only 'names' listing this used to also cover is gone: object
    # deletion now uses the same selectable 'rows' listing as every other
    # destructive action, so 'rows=None' (nothing individually selectable) is
    # the only no-listing case left. See test_commander_entity_selection.py /
    # test_commander_object_selection.py for the selectable-listing coverage.
    from PyQt6.QtWidgets import QListWidget, QPlainTextEdit

    dialog, _yes, _skip = window._build_destructive_dialog("Delete", "Delete?")
    assert dialog.findChild(QListWidget, "selection_list") is None
    assert dialog.findChild(QPlainTextEdit, "entity_listing") is None


def test_bypass_skips_enumeration(window, captured, monkeypatch):
    def _fail(command, extra_args=None):
        raise AssertionError("enumeration must not run when confirmations are skipped")

    monkeypatch.setattr(window, "_capture_dry_run_summaries", _fail)
    window._skip_confirmations = {"terminate"}
    window._terminate_all_compute_requirements_action()
    assert captured == [("yd-terminate", ["-y"])]


def test_delete_runs_when_confirmed(window, captured, monkeypatch):
    monkeypatch.setattr(
        window,
        "_capture_dry_run_objects",
        lambda command, extra_args: [
            ObjectSummary(path="S3:b/pfx/obj", name="obj", is_dir=False)
        ],
    )
    monkeypatch.setattr(
        window,
        "_confirm_destructive",
        lambda *a, **k: Confirmation(proceed=True, handles=["S3:b/pfx/obj"]),
    )
    window._tag = "my-tag"
    window._delete_objects_action()
    assert captured == [("yd-delete", ["-Ry", "S3:b/pfx/obj"])]


def test_delete_declined_does_not_run(window, captured, monkeypatch):
    monkeypatch.setattr(
        window,
        "_capture_dry_run_objects",
        lambda command, extra_args: [
            ObjectSummary(path="S3:b/pfx/obj", name="obj", is_dir=False)
        ],
    )
    monkeypatch.setattr(
        window,
        "_confirm_destructive",
        lambda *a, **k: Confirmation(proceed=False, handles=None),
    )
    window._delete_objects_action()
    assert captured == []


def test_delete_none_match_logs_and_skips(window, captured, monkeypatch):
    monkeypatch.setattr(
        window, "_capture_dry_run_objects", lambda command, extra_args: []
    )
    window._tag = "my-tag"
    window.log_output.setPlainText("")
    window._delete_objects_action()
    assert captured == []
    assert "No objects match 'my-tag*'" in window.log_output.toPlainText()


def test_delete_enumeration_failure_falls_back(window, captured, monkeypatch):
    monkeypatch.setattr(
        window, "_capture_dry_run_objects", lambda command, extra_args: None
    )
    calls = []
    monkeypatch.setattr(
        window,
        "_confirm_destructive",
        lambda action_key, title, body, names=None, rows=None: (
            calls.append(rows) or Confirmation(proceed=True, handles=None)
        ),
    )
    window._tag = "my-tag"
    window._delete_objects_action()
    assert captured == [("yd-delete", ["-Ry", "my-tag*"])]
    assert calls[0] is None


def test_delete_dry_run_skips_confirmation(window, captured, monkeypatch):
    # Dry run is a harmless preview: it must run even when confirmation is denied.
    monkeypatch.setattr(
        window,
        "_confirm_destructive",
        lambda *a, **k: Confirmation(proceed=False, handles=None),
    )
    window._tag = "my-tag"
    window.dry_run_objects.setChecked(True)
    window._delete_objects_action()
    assert captured == [("yd-delete", ["-Ry", "my-tag*", "-D"])]


def test_delete_bypass_logs_the_suppression(window, captured, monkeypatch):
    # Recursive object deletion is arguably where the "never silent" bypass
    # log matters most, so it must log the suppression the same way the
    # entity-based destructive actions do.
    window._skip_confirmations = {"delete"}
    window._tag = "my-tag"
    window.log_output.setPlainText("")
    window._delete_objects_action()
    assert captured == [("yd-delete", ["-Ry", "my-tag*"])]
    assert (
        "Confirmations suppressed for 'delete'; deleting all objects matching"
        " 'my-tag*'" in window.log_output.toPlainText()
    )


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
    assert win._confirm_destructive("terminate", "t", "b") == Confirmation(
        proceed=True, handles=None
    )
    assert win._confirm_destructive("delete", "t", "b") == Confirmation(
        proceed=True, handles=None
    )


def test_confirmations_enabled_by_default(window):
    # Default construction leaves confirmations enabled.
    assert window._confirmations_disabled is False


def test_skip_confirmations_is_per_action(window):
    # The bypass is per-action: a key present short-circuits its own action, but
    # a different action's key is unaffected. Assert directly on the helper's
    # short-circuit (no dialog is created when the key is present).
    window._skip_confirmations = {"terminate"}
    assert window._confirm_destructive("terminate", "t", "b") == Confirmation(
        proceed=True, handles=None
    )
    assert "shutdown" not in window._skip_confirmations


def test_scope_phrase_tags_and_names(window):
    window._namespace, window._tag = "ns", "tg"
    assert window._scope_phrase("tags") == " in namespace 'ns' with tags including 'tg'"
    assert (
        window._scope_phrase("names") == " in namespace 'ns' with names including 'tg'"
    )


def test_scope_phrase_generic_when_unknown(window):
    window._namespace = None
    window._tag = None
    assert window._scope_phrase("tags") == " in the current namespace and tag"


# --- Download / Delete -------------------------------------------------------


def test_download(window, captured, monkeypatch):
    # Destination and path assembly, exercised through the enumeration-failure
    # fallback (which downloads the whole pattern, as this action always did).
    # The chooser path is covered in tests/test_commander_download_selection.py.
    monkeypatch.setattr(
        window, "_capture_dry_run_objects", lambda command, extra_args: None
    )
    window._config_file = "cfg/config.toml"
    window._tag = "my-tag"
    window._download_results_action()
    expected_dst = join(dirname(abspath("cfg/config.toml")), RESULTS_DIR)
    assert captured == [("yd-download", ["--into", expected_dst, "my-tag*"])]


def test_delete_with_path_override_and_dry_run(window, captured):
    window.object_path_override.setPlainText("prefix/*")
    window.dry_run_objects.setChecked(True)
    window._delete_objects_action()
    assert captured == [("yd-delete", ["-Ry", "prefix/*", "-D"])]


# --- Results / view actions work without a config file -----------------------


def test_download_results_no_config_uses_cwd(window, captured, monkeypatch):
    monkeypatch.setattr(
        window, "_capture_dry_run_objects", lambda command, extra_args: None
    )
    window._config_file = None
    window._tag = "my-tag"
    expected_path = window._object_path()
    window._download_results_action()
    assert captured == [
        (
            "yd-download",
            ["--into", os.path.join(os.getcwd(), RESULTS_DIR), expected_path],
        )
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


def test_object_path_is_unknown_without_a_tag_or_override(window):
    # It used to interpolate the missing tag, producing the literal 'None*' and
    # handing that to yd-download / yd-delete as the scope to act on.
    window._tag = None
    assert window._object_path() is None


def test_object_path_uses_the_override_even_without_a_tag(window):
    window._tag = None
    window.object_path_override.setPlainText("custom/path/*")
    assert window._object_path() == "custom/path/*"


def test_download_refuses_when_no_object_path_can_be_worked_out(window, captured):
    window._tag = None

    window._download_results_action()

    assert captured == []
    assert "no object path" in window.log_output.toPlainText().lower()


def test_delete_refuses_when_no_object_path_can_be_worked_out(window, captured):
    window._tag = None

    window._delete_objects_action()

    assert captured == []
    assert "no object path" in window.log_output.toPlainText().lower()


def test_delete_refuses_even_with_confirmations_suppressed(window, captured):
    # The dangerous combination: '--yes' skips the confirmation, so 'None*' would
    # have gone straight to 'yd-delete -Ry', deleting anything named 'None...'.
    window._tag = None
    window._confirmations_disabled = True

    window._delete_objects_action()

    assert captured == []


def test_dry_run_refuses_too_when_no_object_path_can_be_worked_out(window, captured):
    # A dry run reporting on 'None*' says 'nothing matches', which reads as
    # reassurance about the wrong question.
    window._tag = None
    window.dry_run_objects.setChecked(True)

    window._download_results_action()
    window._delete_objects_action()

    assert captured == []


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
