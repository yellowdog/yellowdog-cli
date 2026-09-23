"""
The command field's history: recall of earlier commands with the arrow
buttons, as a shell does.
"""


class CommandHistory:
    def __init__(self, max_size: int = 250):
        self._max_size = max_size
        self._ptr = 0
        self._commands: list[str] = []
        self._empty_string_returned = False

    def save_command(self, command: str):
        """
        Save a command at the end of the command list.
        Consecutive duplicates are not stored.
        """
        if self._commands and self._commands[-1] == command:
            return
        if len(self._commands) == self._max_size:
            self._commands.pop(0)
        self._commands.append(command)
        self._ptr = len(self._commands) - 1
        self._empty_string_returned = False

    def step_forward(self) -> str | None:
        """
        Return the next (later) command in the list.
        Return an empty string if already at the end of the list.
        """
        if len(self._commands) == 0:
            return None
        if self._ptr < len(self._commands) - 1:
            self._ptr += 1
        else:
            self._empty_string_returned = True
            return ""
        return self._commands[self._ptr]

    def step_back(self) -> str | None:
        """
        Return the previous (earlier) command in the list.
        Keep returning the first command if pointer is at the start.
        """
        if len(self._commands) == 0:
            return None
        if self._ptr > 0:
            if self._empty_string_returned:
                self._empty_string_returned = False
            else:
                self._ptr -= 1
        return self._commands[self._ptr]
