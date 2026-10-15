"""
The failure tests' cases, the outcomes the Platform decides (pinned from an
observed run, with the reason), and the assertion every case makes: the exit
code, no traceback, a parseable '--json' document, and the failure's phrase
on stderr. The phrases are the CLI's own (wrapper._describe()).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from harness.yd import Result, Yd

PERMISSION = "required permissions"
AUTHENTICATION = "not recognised"
CONNECTION = "Cannot reach"
# A UUID no entity has
_NO_UUID = "00000000-0000-4000-8000-000000000000"

# Each case, as its test in test_live_failures.py is named, less 'test_'
CASES = (
    "not-found-wr-show",
    "not-found-cr-show",
    "not-found-wr-cancel-by-name",
    "not-found-resource-remove",
    "not-found-one-of-two-shown",
    "auth-wrong-secret-read",
    "auth-wrong-secret-action",
    "permission-control",
    "permission-other-namespace",
    "permission-unscoped",
    "permission-keyrings",
    "permission-compute-requirements",
    "permission-show-other-namespace",
    "permission-create",
    "permission-cancel",
    "connection-closed-port",
    "connection-unresolvable",
    "timeout-wait",
    "timeout-wait-one-missing",
    "auth-revoked",
)


@dataclass(frozen=True)
class Pinned:
    """
    An outcome the Platform decides, as observed, and why it stands.
    """

    exit_code: int
    phrase: str | None
    why: str


PINNED: dict[str, Pinned] = {
    "permission-unscoped": Pinned(
        0,
        None,
        "An unscoped search ('--namespace \"\"') is scoped by the CLI to the"
        " namespaces the Application can read, which avoids the Platform's 403"
        " for an Application without global read access: the limited"
        " Application reads only its own, empty, namespace, so it finds"
        " nothing (observed in run ydst-2610151534-ay3h)",
    ),
}


def expected(case: str, exit_code: int, phrase: str | None) -> tuple[int, str | None]:
    """
    The case's exit code and phrase: pinned, or the defaults given.
    """
    pinned = PINNED.get(case)
    return (exit_code, phrase) if pinned is None else (pinned.exit_code, pinned.phrase)


def fake_ydid(real_id: str, type_token: str) -> str:
    """
    A well-formed ID of the type that names nothing: the real ID's account
    segment kept, so the Platform answers 'not found', not 'not yours'.
    """
    segment = real_id.split(":")[2]
    return f"ydid:{type_token}:{segment}:{_NO_UUID}"


def check_failure(
    yd: Yd,
    result: Result,
    exit_code: int,
    phrase: str | None,
    *,
    json_document: bool = True,
) -> None:
    """
    Hold the result to a failure: its exit code, no traceback, stdout one
    JSON document (with 'json_document'), the phrase on stderr.
    """
    shown = yd.describe(result)
    assert result.exit_code == exit_code, (
        f"exit {result.exit_code}, not {exit_code}:\n{shown}"
    )
    assert "Traceback" not in result.stderr, f"Traceback on stderr:\n{shown}"
    if json_document and result.stdout.strip():
        try:
            json.loads(result.stdout)
        except ValueError:
            raise AssertionError(f"stdout is not one JSON document:\n{shown}") from None
    if phrase is not None:
        assert phrase.casefold() in result.stderr.casefold(), (
            f"phrase {phrase!r} not on stderr:\n{shown}"
        )
