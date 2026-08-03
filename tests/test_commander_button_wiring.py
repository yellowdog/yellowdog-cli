"""
Every main-window button must be connected to the action it claims to perform.

Nothing checked this before: test_commander_ui_loads proves the widgets named in
commander.ui exist, and the contract tests call the action methods directly. So a
button added to the .ui but never connected, or connected to the wrong action,
would have looked entirely healthy — and would have done nothing at all when a
user pressed it.

Connections are made in __init__ against the bound method, so replacing a method on
an existing window would not intercept them. These tests patch the class first and
build the window afterwards, which is what makes the click observable.
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QPushButton

from yellowdog_cli.commander.commander import YellowDogApp

# (button attribute in commander.ui, action method it must invoke).
WIRING = [
    ("select_config_file", "_select_config_file_action"),
    ("select_work_requirement", "_select_work_requirement_action"),
    ("submit_work_requirement", "_submit_work_requirement_action"),
    ("cancel_work_requirements", "_cancel_work_requirements_action"),
    (
        "cancel_work_requirements_and_abort",
        "_cancel_work_requirements_and_abort_action",
    ),
    ("select_worker_pool", "_select_worker_pool_action"),
    ("create_worker_pool", "_create_worker_pool_action"),
    ("shutdown_all_worker_pools", "_shutdown_all_worker_pools_action"),
    (
        "terminate_all_compute_requirements",
        "_terminate_all_compute_requirements_action",
    ),
    ("download_results", "_download_results_action"),
    ("delete_objects", "_delete_objects_action"),
    ("view_results", "_view_results_action"),
    ("clear_command_output", "_clear_output_action"),
    ("copy_command_output", "_copy_output_action"),
    ("save_command_output", "_save_output_action"),
    ("show_configuration", "_show_config_action"),
    ("show_wr", "_show_wr_action"),
    ("show_wp", "_show_wp_action"),
    ("deselect_files", "_deselect_files_action"),
    ("view_config_directory", "_view_config_directory_action"),
    ("run_any_command", "_run_any_command_action"),
    ("next_command", "_next_command_action"),
    ("prev_command", "_prev_command_action"),
]


@pytest.mark.parametrize("button_name,action_name", WIRING)
def test_clicking_the_button_invokes_its_action(
    qapp, monkeypatch, button_name, action_name
):
    fired: list[str] = []
    monkeypatch.setattr(
        YellowDogApp,
        action_name,
        lambda self, *args, **kwargs: fired.append(action_name),
    )
    window = YellowDogApp()  # built after the patch, so the connection sees it

    button = getattr(window, button_name)
    assert isinstance(button, QPushButton), f"{button_name} is not a button"
    button.click()

    assert fired == [action_name], (
        f"clicking {button_name} did not invoke {action_name}"
    )


def test_every_button_in_the_ui_is_connected_to_something(qapp):
    """
    Catch a button added to commander.ui and never wired, without anyone having to
    remember to extend the table above. Qt will report how many receivers a signal
    has, which is enough to tell 'connected' from 'inert' even though it will not
    say to what.
    """
    window = YellowDogApp()
    named_buttons = {
        button.objectName(): button
        for button in window.findChildren(QPushButton)
        if button.objectName()
    }
    unconnected = sorted(
        name
        for name, button in named_buttons.items()
        if button.receivers(button.clicked) == 0
    )
    assert unconnected == [], f"buttons in commander.ui with no action: {unconnected}"


def test_the_wiring_table_covers_every_button_in_the_ui(qapp):
    """
    Keep the explicit table honest. A button connected to something but missing
    from the table above would be untested for *which* action it invokes.
    """
    window = YellowDogApp()
    in_ui = {
        button.objectName()
        for button in window.findChildren(QPushButton)
        if button.objectName()
    }
    tabled = {button_name for button_name, _action in WIRING}
    assert in_ui - tabled == set(), (
        f"buttons in commander.ui absent from the wiring table: "
        f"{sorted(in_ui - tabled)}"
    )
