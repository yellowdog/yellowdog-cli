"""
Map an exception reaching a command wrapper to the process exit code, so a
script can tell an authentication failure from a missing entity from an
unreachable platform. The codes are ExitCode's.
"""

from __future__ import annotations

import sys
from enum import IntEnum
from typing import TYPE_CHECKING


class ExitCode(IntEnum):
    """
    The process exit codes, so a script can tell kinds of failure apart.

    | Code | Name           | When                                               |
    |------|----------------|----------------------------------------------------|
    | 0    | SUCCESS        |                                                    |
    | 1    | FAILURE        | the operation, the work (yd-wait, yd-submit -E),   |
    |      |                | or a check (yd-doctor) failed                      |
    | 2    | USAGE          | argparse's own                                     |
    | 3    | CONFIGURATION  | missing configuration data, unreadable or invalid  |
    |      |                | TOML, a variable error at load, a missing --config |
    | 4    | AUTHENTICATION | HTTP 401, NotAuthorisedException, 'Unauthorized'   |
    | 5    | PERMISSION     | HTTP 403, 'MissingPermissionException'             |
    | 6    | NOT_FOUND      | HTTP 404 reaching the wrapper, or NotFoundError    |
    | 7    | PLATFORM       | HTTP 5xx, InternalServerException,                 |
    |      |                | ServerErrorException                               |
    | 8    | CONNECTION     | requests connection errors and timeouts            |
    | 130  | INTERRUPTED    | keyboard interrupt                                 |

    What reaches a command wrapper is mapped by exit_codes.classify();
    commands that catch a failure themselves exit FAILURE. So does any
    command whose recorded results include a 'failed' outcome/action, even
    where main() itself returns normally (results.any_failed(), checked by
    both wrappers straight after a successful run).
    """

    SUCCESS = 0
    FAILURE = 1
    USAGE = 2
    CONFIGURATION = 3
    AUTHENTICATION = 4
    PERMISSION = 5
    NOT_FOUND = 6
    PLATFORM = 7
    CONNECTION = 8
    INTERRUPTED = 130


# The message text the wrappers recognise for their friendly messages; the
# last resort, after every typed check
MISSING_PERMISSION_TEXT = "MissingPermissionException"
UNAUTHORIZED_TEXT = "Unauthorized"

# Failures of the session rather than of the item being acted on: every later
# call would fail in the same way, so an action command that classifies a
# per-item failure as one of these attempts nothing further
SESSION_FAILURES = frozenset({ExitCode.AUTHENTICATION, ExitCode.CONNECTION})


class ReportedFailure(Exception):
    """
    A failure the command has already reported and recorded, raised so that
    the wrapper exits with the failure's own code rather than the FAILURE a
    recorded 'failed' outcome gives, and without printing it a second time.
    The action commands raise it once a SESSION_FAILURES failure has stopped
    them and the items not attempted have been recorded. classify() reaches
    the code through the cause.
    """

    def __init__(self, cause: BaseException):
        super().__init__(str(cause))
        self.__cause__ = cause


class NotFoundError(LookupError):
    """
    An entity the command was given does not exist. Raised in place of the
    HTTP 404 (chained to it, where there was one) to name the entity, and
    classified NOT_FOUND like the 404 itself. A LookupError rather than a
    KeyError, whose message str() would print in quotes.
    """


if TYPE_CHECKING:
    from requests import HTTPError


def _http_status(exception: HTTPError) -> ExitCode | None:
    response = exception.response
    status = getattr(response, "status_code", None)
    if not isinstance(status, int):
        return None
    if status == 401:
        return ExitCode.AUTHENTICATION
    if status == 403:
        return ExitCode.PERMISSION
    if status == 404:
        return ExitCode.NOT_FOUND
    if 500 <= status < 600:
        return ExitCode.PLATFORM
    return None


def classify(exception: BaseException) -> ExitCode:
    """
    The exit code for an exception. Typed checks come first (the HTTP status
    of a 'requests' HTTPError, the SDK's own exception classes, 'requests'
    connection errors and timeouts, the CLI's own NotFoundError), then the
    two message-text checks the wrappers use for their friendly messages,
    then the exception's cause, so that a failure re-raised with a clearer
    message ('raise RuntimeError(...) from e') keeps its exit code; anything
    else is FAILURE. SystemExit is not classified: the wrappers pass its
    code through.

    The typed checks import their classes here, and only if their package
    is already loaded, since an instance cannot exist otherwise: importing
    the SDK at all builds the whole Platform client, and 'requests' is
    ~50ms that a command which never used it should not pay to fail.
    """
    if isinstance(exception, NotFoundError):
        return ExitCode.NOT_FOUND
    requests_loaded = "requests" in sys.modules
    if requests_loaded:
        from requests import HTTPError

        if isinstance(exception, HTTPError):
            code = _http_status(exception)
            if code is not None:
                return code
    if "yellowdog_client" in sys.modules:
        from yellowdog_client.model.exceptions.internal_server_exception import (
            InternalServerException,
        )
        from yellowdog_client.model.exceptions.not_authorised_exception import (
            NotAuthorisedException,
        )
        from yellowdog_client.model.exceptions.server_error_exception import (
            ServerErrorException,
        )

        if isinstance(exception, NotAuthorisedException):
            return ExitCode.AUTHENTICATION
        if isinstance(exception, (InternalServerException, ServerErrorException)):
            return ExitCode.PLATFORM
    if requests_loaded:
        from requests import ConnectionError as RequestsConnectionError
        from requests import Timeout

        if isinstance(exception, (RequestsConnectionError, Timeout)):
            return ExitCode.CONNECTION

    message = str(exception)
    if MISSING_PERMISSION_TEXT in message:
        return ExitCode.PERMISSION
    if UNAUTHORIZED_TEXT in message:
        return ExitCode.AUTHENTICATION
    if exception.__cause__ is not None:
        return classify(exception.__cause__)
    return ExitCode.FAILURE
