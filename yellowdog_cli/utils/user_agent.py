"""
Set custom User-Agent headers on outgoing HTTP requests, distinguishing the
CLI's own direct REST calls from calls made through the YellowDog SDK:

  * Direct CLI calls:  yellowdog-cli/<ver> python-requests/<ver>
  * SDK calls:         yellowdog-cli/<ver> yellowdog-sdk/<ver> python-requests/<ver>

Mechanism:
  * The baseline (and therefore every direct CLI call) is handled by patching
    requests.utils.default_user_agent(); every requests.Session seeds its
    headers from it, so the direct call sites need no changes.
  * SDK calls additionally pass through the SDK's authentication callable,
    ApiKeyAuthenticationHeadersProvider.__call__, which runs on every prepared
    SDK request (REST and SSE) *after* the session default has been applied.
    Wrapping it lets us override the User-Agent with the SDK-flavoured value on
    SDK traffic only.

This is a deliberate stop-gap: native User-Agent support in the SDK is the
longer-term fix, after which the SDK-specific override can be removed.
"""

import requests.utils
from yellowdog_client._version import __version__ as _sdk_version
from yellowdog_client.common.credentials import ApiKeyAuthenticationHeadersProvider

from yellowdog_cli._version import __version__

# Captured once, at import: the original requests User-Agent (requests/urllib3
# version), preserved as a suffix on both flavours below.
_REQUESTS_UA = requests.utils.default_user_agent()

# Direct (non-SDK) CLI calls.
CLI_USER_AGENT = f"yellowdog-cli/{__version__} {_REQUESTS_UA}"

# Calls made through the YellowDog SDK additionally advertise the SDK version.
SDK_USER_AGENT = (
    f"yellowdog-cli/{__version__} yellowdog-sdk/{_sdk_version} {_REQUESTS_UA}"
)

# Guards the SDK auth-callable wrapping against repeated application.
_SDK_PATCH_FLAG = "_yd_cli_user_agent_patched"


def set_user_agent() -> None:
    """
    Apply both User-Agent patches. Idempotent.
    """
    # 1) Baseline for every requests Session — covers the CLI's direct calls.
    requests.utils.default_user_agent = lambda *_args, **_kwargs: CLI_USER_AGENT

    # 2) SDK-only override, applied by the SDK's per-request auth callable.
    if not getattr(ApiKeyAuthenticationHeadersProvider, _SDK_PATCH_FLAG, False):
        original_call = ApiKeyAuthenticationHeadersProvider.__call__

        def _call_with_user_agent(self, r):
            r = original_call(self, r)
            r.headers["User-Agent"] = SDK_USER_AGENT
            return r

        ApiKeyAuthenticationHeadersProvider.__call__ = _call_with_user_agent
        setattr(ApiKeyAuthenticationHeadersProvider, _SDK_PATCH_FLAG, True)
