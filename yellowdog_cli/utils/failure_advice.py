"""
What to check when the Platform refuses a request: a missing permission
(403) or an unrecognised key (401). The wrapper prefixes a failure reaching
it with these words; a command reporting a failure itself, per item (an
action's target, an ID shown, a resource created), calls advise(), which
says them once per run for each cause, however many items fail for it.
"""

from __future__ import annotations

from yellowdog_cli.utils.exit_codes import ExitCode, classify
from yellowdog_cli.utils.printing import print_error

PERMISSION_ADVICE = (
    "Your Application does not have the required permissions to perform the"
    " requested operation. Please check that the Application belongs to the"
    " required group(s), e.g., 'administrators', with roles in the required"
    " namespace(s)"
)
AUTHENTICATION_ADVICE = "Your Application Key ID and SECRET are not recognised"
_ADVICE = {
    ExitCode.PERMISSION: PERMISSION_ADVICE,
    ExitCode.AUTHENTICATION: AUTHENTICATION_ADVICE,
}
# The causes already advised on in this run
_GIVEN: set[ExitCode] = set()


def advise(error: BaseException) -> None:
    """
    Say what to check for a refused request, the first time its cause is
    met in this run; nothing for any other failure.
    """
    code = classify(error)
    advice = _ADVICE.get(code)
    if advice is None or code in _GIVEN:
        return
    _GIVEN.add(code)
    print_error(advice)


def reset_advice() -> None:
    """
    Forget the advice given (for tests).
    """
    _GIVEN.clear()
