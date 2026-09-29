"""
Splitting Commander's text fields into command-line arguments, and quoting
arguments back into a field. Qt-free, like startup.py, so that launcher.py can
use it before any Qt import is attempted.

The fields are split as a shell would split them, but only as far as quoting
goes: whitespace separates arguments, and single or double quotes group text
containing whitespace into one argument, the quotes themselves being removed.
There are no backslash escapes, deliberately: a shell's would turn a Windows
path such as 'C:\\results\\new' into 'C:resultsnew', and Commander's fields are
typed on Windows as often as anywhere else. The price is that a quote character
can only appear inside quotes of the other kind: '"a"' is the three characters
"a", and "it's" is it's.
"""

QUOTES = "'\""


class QuotingError(ValueError):
    """A field whose quotes do not balance, so it cannot be split."""


def split_arguments(text: str) -> list[str]:
    """
    The arguments in 'text'. Adjacent quoted and unquoted text is one argument,
    as in a shell, so 'workRequirement.workerTags=["a", "b"]' can be written
    with the quotes around the value alone: workRequirement.workerTags='["a", "b"]'.
    An empty pair of quotes is an empty argument. Raises QuotingError for a
    quote left open.
    """
    arguments: list[str] = []
    current: list[str] = []
    in_argument = False  # distinguishes '' (an empty argument) from nothing
    quote: str | None = None
    for char in text:
        if quote is not None:
            if char == quote:
                quote = None
            else:
                current.append(char)
        elif char in QUOTES:
            quote = char
            in_argument = True
        elif char.isspace():
            if in_argument:
                arguments.append("".join(current))
                current = []
                in_argument = False
        else:
            current.append(char)
            in_argument = True
    if quote is not None:
        raise QuotingError(f"the {quote} quote is never closed")
    if in_argument:
        arguments.append("".join(current))
    return arguments


def quote_argument(argument: str) -> str:
    """
    'argument' as field text that split_arguments() returns unchanged: as it is
    if it needs no quotes, else in whichever kind of quote it does not contain.
    Raises QuotingError for one containing both kinds and needing quotes, which
    the field cannot hold.
    """
    needs_quotes = not argument or any(
        char.isspace() or char in QUOTES for char in argument
    )
    if not needs_quotes:
        return argument
    for quote in QUOTES:
        if quote not in argument:
            return f"{quote}{argument}{quote}"
    raise QuotingError(
        f"'{argument}' contains both kinds of quote, so it cannot be quoted"
    )


def property_is_complete(argument: str) -> bool:
    """
    Whether an argument from the Properties field is a 'section.key=value' the
    CLI will accept in form: an '=' with a section and a key in front of it,
    separated by a '.'. Mirrors the checks in load_config._apply_property_overrides(),
    except that an unknown section is left for the CLI to report.
    """
    name, separator, _ = argument.partition("=")
    section, dot, key = name.partition(".")
    return bool(separator) and bool(section) and bool(dot) and bool(key)
