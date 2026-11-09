"""
yd resource plan (resource_plan.py): the command and its verb; the work is
utils/resource_plan.py's.
"""

from types import SimpleNamespace

import yellowdog_cli.resource_plan as plan_command
import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli.utils.command_registry import (
    COMMANDS,
    DRY_RUN_ACTION,
    RESOURCE_SET,
    RESOURCE_SPECIFICATIONS,
    RESOURCE_TYPE,
    SHOW_KEYRING_PASSWORDS,
    VALIDATE,
    VARIABLE,
    YES_ALLOW_UPDATES,
    ToolKind,
)
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.noun_registry import NOUN_COMMANDS
from yellowdog_cli.utils.resource_plan import PlanOptions


def test_the_verb_runs_the_plan_command():
    assert NOUN_COMMANDS["yd resource plan"].runs == "yd-resource-plan"


def test_it_is_read_only_with_no_script():
    command = COMMANDS["yd-resource-plan"]
    assert command.tool is ToolKind.READ_ONLY and not command.script


def test_it_takes_creates_inputs_and_none_of_its_actions():
    plan, create = COMMANDS["yd-resource-plan"], COMMANDS["yd-create"]
    for option in (RESOURCE_SPECIFICATIONS, RESOURCE_TYPE, RESOURCE_SET, VARIABLE):
        assert plan.has(option) and create.has(option)
    for option in (DRY_RUN_ACTION, YES_ALLOW_UPDATES, SHOW_KEYRING_PASSWORDS, VALIDATE):
        assert not plan.has(option)


def test_main_hands_the_specifications_and_options_to_plan_resources(monkeypatch):
    seen = {}
    loaded = [{"resource": "Keyring", "name": "k"}]
    monkeypatch.setattr(
        plan_command, "load_resource_specifications", lambda args, **kw: loaded
    )
    monkeypatch.setattr(
        plan_command,
        "plan_resources",
        lambda ctx, specs, options: seen.update(specs=specs, options=options),
    )
    args = SimpleNamespace(
        json_output=True,
        fail_on_changes=True,
        match_allowances_by_description=None,
        regenerate_app_keys=None,
    )
    plan_command.main.__closure__  # the wrapped command is main's closure
    inner = next(
        c.cell_contents
        for c in plan_command.main.__closure__
        if callable(c.cell_contents) and c.cell_contents.__name__ == "main"
    )
    inner(RunContext(args=args, config=wrapper_module.CONFIG_COMMON, client=None))
    assert seen["specs"] is loaded
    assert seen["options"] == PlanOptions(json_output=True, fail_on_changes=True)
