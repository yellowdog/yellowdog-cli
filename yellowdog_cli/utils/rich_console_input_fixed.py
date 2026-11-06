"""
A Rich Console whose input() keeps its prompt while the line is edited.

Rich's own Console.input() prints the prompt itself, then calls input()
with no prompt (https://github.com/Textualize/rich/issues/2293). readline
knows nothing of the printed prompt, so redrawing the line on an editing
key (backspace, a cursor key, history) erases it.

With readline loaded and both stdin and stdout terminals, the prompt's last
line goes to input() itself, so readline redraws it with the line, and the
cursor keys and history work. GNU readline is given its colour codes
between \\001 and \\002 (RL_PROMPT_START_IGNORE/END_IGNORE), which leave
them out of the prompt's width. libedit (macOS's Python, and others) is
given the last line uncoloured: it counts a colour code's characters as
columns, and writes the codes between those markers ahead of the text and
again at each redraw. Any earlier lines of the prompt are printed as they
are.

Otherwise the prompt is printed and the line read from sys.stdin, with the
terminal's own line editing, if any. Bypassing readline at a terminal would
leave the cursor keys echoed as escape sequences, which then become part of
the answer.
"""

import re
import sys
from getpass import getpass
from typing import TextIO

from rich.console import Console
from rich.text import TextType

# A CSI escape sequence: the colours and styles Rich writes
_ESCAPE_SEQUENCE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

_READLINE_IGNORE_START = "\001"
_READLINE_IGNORE_END = "\002"


class ConsoleWithInputBackspaceFixed(Console):
    def input(
        self,
        prompt: TextType = "",
        *,
        markup: bool = True,
        emoji: bool | None = None,  # The console's own setting
        password: bool = False,
        stream: TextIO | None = None,
    ) -> str:
        prompt_str = ""
        if prompt:
            with self.capture() as capture:
                self.print(prompt, markup=markup, emoji=emoji, end="", soft_wrap=True)
            prompt_str = capture.get()
        if self.legacy_windows:
            self.file.write(prompt_str)
            prompt_str = ""
        if password:
            return getpass(prompt_str, stream=stream)
        if stream is None and self._line_editing():
            earlier_lines, newline, last_line = prompt_str.rpartition("\n")
            if newline:
                self.file.write(earlier_lines + newline)
                self.file.flush()
            return input(_readline_prompt(last_line))
        # Bypassing readline, which would erase the printed prompt on
        # redrawing the line
        self.file.write(prompt_str)
        self.file.flush()
        if stream:
            # As Rich's own input(): the line as read, newline and all,
            # and "" at the end of the stream
            return stream.readline()
        raw_line = sys.stdin.readline()
        if raw_line == "":
            # Match builtin input(): EOF must raise, not return "",
            # otherwise callers' retry loops spin forever
            raise EOFError("EOF when reading a line")
        return raw_line.rstrip("\n")

    def _line_editing(self) -> bool:
        """
        Whether the line is read through readline: only with readline
        loaded, and both stdin and stdout terminals, the prompt going to
        stdout, which must be this console's file.
        """
        if "readline" not in sys.modules or self.file is not sys.stdout:
            return False
        try:
            return sys.stdin.isatty() and sys.stdout.isatty()
        except (AttributeError, ValueError):
            return False


def _readline_prompt(prompt: str) -> str:
    """
    The prompt as readline is to be given it: its escape sequences marked
    as taking no width for GNU readline, removed for libedit.
    """
    if _is_libedit():
        return _ESCAPE_SEQUENCE.sub("", prompt)
    return _ESCAPE_SEQUENCE.sub(
        lambda match: _READLINE_IGNORE_START + match.group(0) + _READLINE_IGNORE_END,
        prompt,
    )


def _is_libedit() -> bool:
    """
    Whether the readline module is libedit's: its 'backend' from Python
    3.13, its docstring before that.
    """
    readline = sys.modules.get("readline")
    if readline is None:
        return False
    backend = getattr(readline, "backend", None)
    if backend is not None:
        return backend == "editline"
    return "libedit" in (readline.__doc__ or "")
