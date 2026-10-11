#!/usr/bin/env python3

"""
yd-completion: shell completion for the yd-* commands.

'yd-completion bash|zsh|fish|powershell' prints the shell's completion script,
which registers completion for every command a user types (the nouns, the
generic commands and the utilities; not the deprecated commands). On each Tab
the script runs 'yd-completion --complete <shell> <index> <words...>', handled
here before any parser is built, which prints the mode ('values', 'files' or
'dirs') on its first line and then a candidate per line, each
'value<TAB>description'. The work is utils/completion.py's.
"""

import sys
from importlib.resources import files

from yellowdog_cli.utils.command_registry import COMMANDS, build_parser
from yellowdog_cli.utils.completion import (
    complete,
    completion_names,
    join_bash_words,
)

COMPLETE_FLAG = "--complete"
_SCRIPTS = {
    "bash": "yd.bash",
    "zsh": "yd.zsh",
    "fish": "yd.fish",
    "powershell": "yd.ps1",
}
_NAMES_PLACEHOLDER = "@NAMES@"


def completion_script(shell: str) -> str:
    """
    The completion script for a shell, registered for completion_names().
    """
    names = completion_names()
    if shell == "powershell":
        listed = ", ".join(f"'{name}'" for name in names)
    else:
        listed = " ".join(names)
    script = (
        files("yellowdog_cli")
        .joinpath("completion_scripts")
        .joinpath(_SCRIPTS[shell])
        .read_text(encoding="utf-8")
    )
    return script.replace(_NAMES_PLACEHOLDER, listed)


def completion_reply(shell: str, index: int, words: list[str]) -> list[str]:
    """
    The lines answering a completion request: the mode, then the
    candidates. 'words' are the command line's words up to the cursor; the
    current word is words[index], or empty when there are only 'index'
    words (PowerShell 5.1 drops an empty argument, so it is never passed).
    """
    current = words[index] if len(words) > index else ""
    words = words[:index]
    prefix = ""
    if shell == "bash":
        words, current, prefix = join_bash_words(words, current)
    result = complete(words, current)
    lines = [result.mode.name.lower()]
    for candidate in result.candidates:
        value = candidate.value.removeprefix(prefix)
        if shell == "bash" or not candidate.description:
            lines.append(value)
        else:
            lines.append(f"{value}\t{candidate.description}")
    return lines


def _answer(arguments: list[str]) -> None:
    """
    Answer a completion request, printing nothing at all if it fails: a
    traceback would land in the middle of the user's command line.
    """
    try:
        shell, index, *words = arguments
        lines = completion_reply(shell, int(index), words)
        sys.stdout.write("".join(f"{line}\n" for line in lines))
        sys.stdout.flush()
    except Exception:
        pass


def main() -> None:
    if sys.argv[1:2] == [COMPLETE_FLAG]:
        _answer(sys.argv[2:])
        return
    parser = build_parser(COMMANDS["yd-completion"], prog="yd-completion")
    args = parser.parse_args()
    sys.stdout.write(completion_script(args.shell))


if __name__ == "__main__":
    main()
