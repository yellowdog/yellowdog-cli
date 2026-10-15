"""
A scripted stand-in for harness.yd.Yd, for the lifecycle's offline tests:
each call is recorded and answered by a function of its arguments.
"""

import json
from collections.abc import Callable, Iterable

from harness.yd import Result, YdError


def result(args: tuple[str, ...], exit_code: int = 0, document=None) -> Result:
    """
    A Result whose stdout is the document as JSON (nothing for None).
    """
    stdout = "" if document is None else json.dumps(document)
    return Result(tuple(args), exit_code, stdout, "")


class FakeYd:
    """
    Records each call's arguments and answers it with 'respond'.
    """

    def __init__(self, respond: Callable[[tuple[str, ...]], Result]) -> None:
        self.respond = respond
        self.calls: list[tuple[str, ...]] = []
        self.secrets: list[tuple[str, str]] = []
        self.credentials: tuple[str, str] | None = None

    def __call__(
        self,
        *args: str,
        check: bool = True,
        ok: Iterable[int] = (0,),
        timeout: float | None = None,
        expect_secret: bool = False,
        expected_failure: bool = False,
    ) -> Result:
        self.calls.append(args)
        answer = self.respond(args)
        if check and answer.exit_code not in tuple(ok):
            raise YdError(self.describe(answer))
        return answer

    def add_secret(self, label: str, value: str) -> None:
        self.secrets.append((label, value))

    def with_credentials(
        self, key: str, secret: str, url: str | None = None
    ) -> "FakeYd":
        self.credentials = (key, secret)
        return self

    def describe(self, answer: Result) -> str:
        return f"yd {' '.join(answer.args)} exited {answer.exit_code}"

    def mask(self, text: str) -> str:
        return text

    def words(self) -> list[tuple[str, ...]]:
        """
        Each call's leading words, up to its first option.
        """
        return [tuple(word for word in self._until_option(call)) for call in self.calls]

    @staticmethod
    def _until_option(call: tuple[str, ...]) -> Iterable[str]:
        for word in call:
            if word.startswith("-"):
                return
            yield word
