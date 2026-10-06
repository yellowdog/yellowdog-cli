"""
User interaction processing utilities.
"""

from __future__ import annotations

import sys
from contextlib import redirect_stdout
from typing import TYPE_CHECKING, TypeVar

from yellowdog_cli.utils.output_settings import OUTPUT
from yellowdog_cli.utils.printing import (
    CONSOLE,
    CONSOLE_ERR,
    print_error,
    print_info,
    print_string,
)
from yellowdog_cli.utils.tables import print_numbered_object_list, sorted_objects

if TYPE_CHECKING:
    # For the annotation only: every command that confirms an action imports
    # this module, yd-delete among them, which must start without the SDK
    from yellowdog_client import PlatformClient

try:
    import readline  # noqa: F401
except ImportError:
    pass

_T = TypeVar("_T")


def select(
    client: PlatformClient,
    objects: list[_T],
    object_type_name: str | None = None,
    override_quiet: bool = False,
    single_result: bool = False,
    showing_all: bool = False,
    force_interactive: bool = False,
    result_required: bool = False,
    sort_objects: bool = True,
) -> list[_T]:
    """
    Print a numbered list of objects.
    Manually select objects from a list if --interactive is set.
    Return the list of objects.
    """

    if not objects:
        return objects

    if sort_objects:
        objects = sorted_objects(objects)  # type: ignore[arg-type, assignment]

    selecting = bool(OUTPUT.interactive or force_interactive)
    if OUTPUT.json_output:
        # Under '--json' stdout is the result document alone: the list is
        # shown only when a selection is to be made from it, and on stderr,
        # as the selection prompt is
        if selecting:
            with redirect_stdout(sys.stderr):
                print_numbered_object_list(
                    client,
                    objects,  # type: ignore[arg-type]
                    override_quiet=True,
                    showing_all=showing_all,
                    object_type_name=object_type_name,
                )
    elif not OUTPUT.quiet or override_quiet or OUTPUT.interactive:
        print_numbered_object_list(
            client,
            objects,  # type: ignore[arg-type]
            override_quiet=override_quiet,
            showing_all=showing_all,
            object_type_name=object_type_name,
        )

    if not selecting:
        return objects

    if OUTPUT.auto_select_all:
        print_info("Automatically selecting all objects")
        return objects

    return [
        objects[x - 1]
        for x in get_selected_list_items(
            len(objects), result_required=result_required, single_result=single_result
        )
    ]


def get_selected_list_items(
    num_items: int, result_required: bool = False, single_result: bool = False
) -> list[int]:
    """
    Get a numbered selection list.
    """

    def in_range(num: int) -> bool:
        if 1 <= num <= num_items:
            return True
        print_error(f"'{num}' is out of range (1-{num_items})")
        return False

    while True:
        cancel_string = "" if result_required else " or press <Return> to cancel"
        input_string = (
            f"Please select an item number{cancel_string}:"
            if single_result
            else f"Please select items (e.g.: 1,2,4-7 / *){cancel_string}:"
        )
        selector_string = _get_user_input(print_string(input_string) + " ")
        if selector_string.strip() == "*":
            selector_string = f"1-{num_items}"
        selector_list = selector_string.split(",")
        selector_set: set[int] = set()
        error_flag = False
        for selector in selector_list:
            try:
                if "-" in selector:
                    low_s, high_s = selector.split("-")
                    low = int(low_s)
                    high = int(high_s)
                    if low > high:
                        raise ValueError
                    # Checked by its ends, once: not number by number, which
                    # printed an error for each of '1-200000''s out of range
                    if 1 <= low and high <= num_items:
                        selector_set.update(range(low, high + 1))
                    else:
                        print_error(
                            f"'{selector.strip()}' is out of range (1-{num_items})"
                        )
                        error_flag = True
                elif not (selector.isspace() or not selector):
                    i = int(selector)
                    if in_range(i):
                        selector_set.add(i)
                    else:
                        error_flag = True
            except ValueError:
                print_error(f"'{selector}' is not a valid selection")
                error_flag = True
        if error_flag:
            continue
        if not selector_set:
            if result_required:
                print_error("please select at least one item")
                continue
            break
        if single_result and len(selector_set) != 1:
            print_error("please enter a single item number")
            continue
        break

    selected_list = sorted(list(selector_set))
    if selected_list:
        if not single_result:
            if len(selected_list) > 20:
                display_selections = (
                    ", ".join([str(x) for x in selected_list[:10]])
                    + " ... "
                    + ", ".join([str(x) for x in selected_list[-8:]])
                )
            else:
                display_selections = ", ".join([str(x) for x in selected_list])
            print_info(f"Selected item number(s): {display_selections}")
    else:
        print_info("No items selected")

    return selected_list


def confirmed(msg: str) -> bool:
    """
    Confirm an action.
    """
    # Confirmed on the command line?
    if OUTPUT.yes:
        print_info(f"Action proceeding without user confirmation ({msg})")
        return True

    # Seek user confirmation
    while True:
        response = _get_user_input(print_string(f"{msg} (y/N):") + " ").strip()
        if response.lower() in ["y", "yes"]:
            print_info("Action confirmed by user")
            return True
        if response.lower() in ["n", "no", ""]:
            print_info("Action cancelled by user")
            return False


class NoAnswerToPrompt(Exception):
    """
    A prompt was shown but stdin was at end of input: a script that forgot
    '--yes', or a run with stdin redirected from /dev/null. Raised in place
    of the EOFError, whose message ('EOF when reading a line') says nothing
    about what to do; the wrapper reports it and exits with a failure.
    """

    def __init__(self) -> None:
        super().__init__(
            "The prompt got no answer: stdin is at end of input, as when a command"
            " is run without a terminal. Use '--yes' to proceed without"
            " confirmation, or run the command from a terminal"
        )


def wait_for_enter(prompt: str) -> None:
    """
    Show 'prompt' and wait for the Enter key: whatever '--quiet' says, on
    stderr under '--json', and NoAnswerToPrompt, with its remedy, rather
    than an EOFError when there is no terminal to answer from.
    """
    _get_user_input(print_string(prompt) + " ")


def _get_user_input(input_prompt: str) -> str:
    """
    Get user input, respecting the --no-format option. Under '--json' the
    prompt goes to stderr, so stdout holds only the result document.
    """
    try:
        if OUTPUT.json_output:
            CONSOLE_ERR.print(input_prompt, end="")
            return input("")
        if OUTPUT.no_format:
            return input(input_prompt)
        # Prevents broken wrapping
        CONSOLE.print(input_prompt, end="")
        return CONSOLE.input("")
    except EOFError:
        raise NoAnswerToPrompt() from None
