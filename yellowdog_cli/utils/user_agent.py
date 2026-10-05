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
longer-term fix, after which the SDK-specific override can be removed. Being
cosmetic, it never stops a command: an SDK that no longer has the callable
keeps the baseline, saying so under '--debug'. The baseline alone, which
needs no SDK, is set_default_user_agent(), for a request made before any
client is built (the PAC file's fetch).
"""

import requests.utils

from yellowdog_cli._version import __version__
from yellowdog_cli.version import sdk_version

# Captured once, at import: the original requests User-Agent (requests/urllib3
# version), preserved as a suffix on both flavours below.
_REQUESTS_UA = requests.utils.default_user_agent()

# Direct (non-SDK) CLI calls.
CLI_USER_AGENT = f"yellowdog-cli/{__version__} {_REQUESTS_UA}"

# Calls made through the YellowDog SDK additionally advertise the SDK version.
SDK_USER_AGENT = (
    f"yellowdog-cli/{__version__} yellowdog-sdk/{sdk_version()} {_REQUESTS_UA}"
)

# Guards the SDK auth-callable wrapping against repeated application.
_SDK_PATCH_FLAG = "_yd_cli_user_agent_patched"


def set_default_user_agent() -> None:
    """
    The baseline for every requests Session -- the CLI's direct calls --
    without importing the SDK. Idempotent.
    """
    requests.utils.default_user_agent = lambda *_args, **_kwargs: CLI_USER_AGENT


def set_user_agent() -> None:
    """
    Apply both User-Agent patches. Idempotent.
    """
    # 1) Baseline for every requests Session — covers the CLI's direct calls.
    set_default_user_agent()

    # 2) SDK-only override, applied by the SDK's per-request auth callable;
    # imported here, since importing the SDK at all builds the whole client
    try:
        from yellowdog_client.common.credentials import (
            ApiKeyAuthenticationHeadersProvider,
        )

        ApiKeyAuthenticationHeadersProvider.__call__
    except (ImportError, AttributeError) as e:
        from yellowdog_cli.utils.printing import print_debug

        print_debug(f"SDK requests keep the CLI's User-Agent: {e}")
        return

    if not getattr(ApiKeyAuthenticationHeadersProvider, _SDK_PATCH_FLAG, False):
        original_call = ApiKeyAuthenticationHeadersProvider.__call__

        def _call_with_user_agent(self, r):
            r = original_call(self, r)
            r.headers["User-Agent"] = SDK_USER_AGENT
            return r

        ApiKeyAuthenticationHeadersProvider.__call__ = _call_with_user_agent
        setattr(ApiKeyAuthenticationHeadersProvider, _SDK_PATCH_FLAG, True)
