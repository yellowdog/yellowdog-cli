"""
Map an exception reaching a command wrapper to the process exit code, so a
script can tell an authentication failure from a missing entity from an
unreachable platform. The codes are ExitCode's, in settings.py.
"""

from requests import ConnectionError as RequestsConnectionError
from requests import HTTPError, Timeout
from yellowdog_client.model.exceptions.internal_server_exception import (
    InternalServerException,
)
from yellowdog_client.model.exceptions.not_authorised_exception import (
    NotAuthorisedException,
)
from yellowdog_client.model.exceptions.server_error_exception import (
    ServerErrorException,
)

from yellowdog_cli.utils.settings import ExitCode

# The message text the wrappers recognise for their friendly messages; the
# last resort, after every typed check
MISSING_PERMISSION_TEXT = "MissingPermissionException"
UNAUTHORIZED_TEXT = "Unauthorized"


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
    connection errors and timeouts), then the two message-text checks the
    wrappers use for their friendly messages; anything else is FAILURE.
    SystemExit is not classified: the wrappers pass its code through.
    """
    if isinstance(exception, HTTPError):
        code = _http_status(exception)
        if code is not None:
            return code
    if isinstance(exception, NotAuthorisedException):
        return ExitCode.AUTHENTICATION
    if isinstance(exception, (InternalServerException, ServerErrorException)):
        return ExitCode.PLATFORM
    if isinstance(exception, (RequestsConnectionError, Timeout)):
        return ExitCode.CONNECTION

    message = str(exception)
    if MISSING_PERMISSION_TEXT in message:
        return ExitCode.PERMISSION
    if UNAUTHORIZED_TEXT in message:
        return ExitCode.AUTHENTICATION
    return ExitCode.FAILURE
