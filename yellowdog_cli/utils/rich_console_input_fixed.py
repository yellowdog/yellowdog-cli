"""
This fixes an issue using Rich's Console.input() method, where the prompt
is deleted if a backspace is typed. The problematic method in the base
Console class is overridden.

Bug:
  https://github.com/Textualize/rich/issues/2293

Root cause: Rich 13.x prints the prompt directly then calls input() with no
arguments. readline doesn't know about the pre-printed prompt, so when it
redraws the line on any editing keystroke (backspace, cursor movement), it
erases the prompt.

Fix: capture the rendered prompt string, write it to the console's output
file directly, then read from sys.stdin. This bypasses readline entirely and
relies on the terminal's own cooked-mode line editing, which correctly handles
backspace without any knowledge of the prompt width.

The \001/\002 (RL_PROMPT_START_IGNORE/END_IGNORE) approach used to signal
non-printing characters to readline is not used here because macOS Python uses
libedit rather than GNU readline, and libedit does not reliably support those
markers.
"""

import sys
from getpass import getpass
from typing import TextIO

from rich.console import Console
from rich.text import TextType


class ConsoleWithInputBackspaceFixed(Console):
    def input(
        self,
        prompt: TextType = "",
        *,
        markup: bool = True,
        emoji: bool = True,
        password: bool = False,
        stream: TextIO | None = None,
    ) -> str:
        prompt_str = ""
        if prompt:
            with self.capture() as capture:
                self.print(prompt, markup=markup, emoji=emoji, end="")
            prompt_str = capture.get()
        if self.legacy_windows:
            self.file.write(prompt_str)
            prompt_str = ""
        if password:
            result = getpass(prompt_str, stream=stream)
        else:
            if stream:
                self.file.write(prompt_str)
                result = stream.readline()
            else:
                self.file.write(prompt_str)
                self.file.flush()
                raw_line = sys.stdin.readline()
                if raw_line == "":
                    # Match builtin input(): EOF must raise, not return "",
                    # otherwise callers' retry loops spin forever
                    raise EOFError("EOF when reading a line")
                result = raw_line.rstrip("\n")
        return result
