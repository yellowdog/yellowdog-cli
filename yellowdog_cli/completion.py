#!/usr/bin/env python3

"""
yd completion: shell completion for the yd command.

'yd completion bash|zsh|fish|powershell' prints the shell's completion
script, which registers completion for 'yd' (not for the deprecated 'yd-*'
commands). On each Tab the script runs 'yd completion --complete <shell>
<index> <words...>', handled here before any parser is built, which prints
the mode ('values', 'files' or 'dirs') on its first line and then a
candidate per line, each 'value<TAB>description'. The work is
utils/completion.py's.

An entity argument is completed from the Platform when the script was
printed with '--names' ('yd completion zsh --names'), which makes its Tab run
'yd completion --complete --names ...': complete() asks for a lookup, which
is made here (utils/completion_lookups.py) on a thread given
LOOKUP_TIMEOUT_SECONDS, unless YD_COMPLETION_LOOKUPS switches lookups off.
Without '--names' no lookup is made, and the variable cannot turn them on.
While a request is answered, file descriptors 1 and 2 point at the null
device, so that nothing the configuration loader, the SDK or anything else
prints reaches the user's command line; the answer is written to the real
stdout. A lookup still running at the deadline is abandoned: the answer is
written without it and the process ends at once, since a thread blocked in
a network call cannot be stopped and must not hold the shell.
"""

import dataclasses
import os
import sys
import threading
from importlib.resources import files

from yellowdog_cli.utils.command_registry import COMMANDS, build_parser
from yellowdog_cli.utils.completion import (
    Candidate,
    LookupRequest,
    complete,
    join_bash_words,
    unquoted,
)
from yellowdog_cli.utils.invocation import selected_prog
from yellowdog_cli.utils.limits import LOOKUP_TIMEOUT_SECONDS
from yellowdog_cli.utils.settings import ENV_OFF_VALUES, YD_COMPLETION_LOOKUPS

COMPLETE_FLAG = "--complete"
NAMES_FLAG = "--names"
_SCRIPTS = {
    "bash": "yd.bash",
    "zsh": "yd.zsh",
    "fish": "yd.fish",
    "powershell": "yd.ps1",
}

# Set when a lookup was still running at its deadline
_abandoned = threading.Event()


def completion_script(shell: str, names: bool = False) -> str:
    """
    The completion script for a shell; with 'names', one whose Tab asks for
    the names and IDs on the Platform too.
    """
    script = (
        files("yellowdog_cli")
        .joinpath("completion_scripts")
        .joinpath(_SCRIPTS[shell])
        .read_text(encoding="utf-8")
    )
    if not names:
        return script
    request = f"yd completion {COMPLETE_FLAG} {shell}"
    if script.count(request) != 1:
        raise RuntimeError(f"the {shell} script does not run '{request}' once")
    return script.replace(
        request, f"yd completion {COMPLETE_FLAG} {NAMES_FLAG} {shell}"
    )


def completion_reply(
    shell: str, index: int, words: list[str], names: bool = False
) -> list[str]:
    """
    The lines answering a completion request: the mode, then the
    candidates, with 'names' those the Platform gives where it is asked.
    'words' are the command line's words up to the cursor; the current word
    is words[index], or empty when there are only 'index' words (PowerShell
    5.1 drops an empty argument, so it is never passed).
    """
    current = words[index] if len(words) > index else ""
    words = words[:index]
    prefix = ""
    if shell == "bash":
        words, current, prefix = join_bash_words(words, current)
    # As the command will be given them: bash and zsh pass every word as
    # typed, quotes and all ('-t ""' the empty tag), fish and PowerShell
    # the earlier ones unquoted but the current one as typed
    if shell in ("bash", "zsh"):
        words = [unquoted(word) for word in words]
    result = complete(words, unquoted(current))
    found = (
        _look_up(result.lookup)
        if result.lookup is not None and names and lookups_enabled()
        else ()
    )
    lines = [result.mode.name.lower()]
    if found and result.lookup is not None:
        found = tuple(
            dataclasses.replace(candidate, value=result.lookup.prefix + candidate.value)
            for candidate in found
        )
    for candidate in found or result.candidates:
        value = candidate.value.removeprefix(prefix)
        if shell == "bash" or not candidate.description:
            lines.append(value)
        else:
            lines.append(f"{value}\t{candidate.description}")
    return lines


def lookups_enabled() -> bool:
    """
    Whether Platform lookups are allowed: unless YD_COMPLETION_LOOKUPS says
    off. A script printed with '--names' asks for them.
    """
    value = os.environ.get(YD_COMPLETION_LOOKUPS, "")
    return value.strip().lower() not in ENV_OFF_VALUES


def _look_up(request: LookupRequest) -> tuple[Candidate, ...]:
    """
    The lookup's candidates, or none: nothing found, or not found within
    LOOKUP_TIMEOUT_SECONDS, when the lookup is abandoned.
    """
    from yellowdog_cli.utils import completion_lookups

    found: list[tuple[Candidate, ...]] = []
    thread = threading.Thread(
        target=lambda: found.append(completion_lookups.candidates(request)),
        daemon=True,
    )
    thread.start()
    thread.join(LOOKUP_TIMEOUT_SECONDS)
    if thread.is_alive():
        _abandoned.set()
        return ()
    return found[0] if found else ()


def _answer(arguments: list[str]) -> None:
    """
    Answer a completion request, printing nothing at all if it fails: a
    traceback would land in the middle of the user's command line. Nothing
    printed while it is answered is seen (descriptors 1 and 2 point at the
    null device); the answer goes to the real stdout. An abandoned lookup
    ends the process once the answer is written.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    stdout, stderr = os.dup(1), os.dup(2)
    null = os.open(os.devnull, os.O_WRONLY)
    os.dup2(null, 1)
    os.dup2(null, 2)
    os.close(null)
    # Python's own streams too, which may not write through the descriptors
    streams = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = open(os.devnull, "w", encoding="utf-8")
    try:
        names = arguments[:1] == [NAMES_FLAG]
        shell, index, *words = arguments[1:] if names else arguments
        lines = completion_reply(shell, int(index), words, names=names)
        _write(stdout, "".join(f"{line}\n" for line in lines).encode())
    except Exception:
        pass
    if _abandoned.is_set():
        os._exit(0)
    sys.stdout.close()
    sys.stdout, sys.stderr = streams
    os.dup2(stdout, 1)
    os.dup2(stderr, 2)
    os.close(stdout)
    os.close(stderr)


def _write(descriptor: int, data: bytes) -> None:
    while data:
        data = data[os.write(descriptor, data) :]


def main() -> None:
    if sys.argv[1:2] == [COMPLETE_FLAG]:
        _answer(sys.argv[2:])
        return
    parser = build_parser(
        COMMANDS["yd-completion"], prog=selected_prog("yd-completion")
    )
    args = parser.parse_args()
    sys.stdout.write(completion_script(args.shell, names=args.names))


if __name__ == "__main__":
    main()
