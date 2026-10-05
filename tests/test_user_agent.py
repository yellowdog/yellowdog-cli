"""
Tests for the User-Agent patches (hybrid of options B and C).

Direct CLI calls must carry a CLI-only User-Agent (no SDK token), while calls
made through the SDK must additionally advertise the SDK version. These guard
against a future requests/SDK upgrade silently dropping a header or erasing the
distinction (e.g. the SDK auth callable being renamed).
"""

import requests
import requests.utils
from yellowdog_client._version import __version__ as _sdk_version
from yellowdog_client.common.credentials import ApiKeyAuthenticationHeadersProvider
from yellowdog_client.model import ApiKey

from yellowdog_cli._version import __version__
from yellowdog_cli.utils.user_agent import (
    CLI_USER_AGENT,
    SDK_USER_AGENT,
    set_user_agent,
)

_CLI_TOKEN = f"yellowdog-cli/{__version__}"
_SDK_TOKEN = f"yellowdog-sdk/{_sdk_version}"


def _sdk_prepared_ua() -> str:
    """User-Agent on a request prepared exactly as the SDK's Proxy does."""
    provider = ApiKeyAuthenticationHeadersProvider(ApiKey("id", "secret"))
    session = requests.Session()
    prepared = session.prepare_request(
        requests.Request("GET", "https://example.invalid", auth=provider)
    )
    return prepared.headers["User-Agent"]


# --- constants -------------------------------------------------------------


def test_cli_ua_has_cli_token_and_no_sdk_token():
    assert CLI_USER_AGENT.startswith(_CLI_TOKEN)
    assert _SDK_TOKEN not in CLI_USER_AGENT
    assert "python-requests/" in CLI_USER_AGENT


def test_sdk_ua_has_cli_then_sdk_token():
    assert SDK_USER_AGENT.startswith(f"{_CLI_TOKEN} {_SDK_TOKEN}")
    assert "python-requests/" in SDK_USER_AGENT


# --- direct (non-SDK) calls: baseline default ------------------------------


def test_default_user_agent_patched_to_cli_ua():
    set_user_agent()
    assert requests.utils.default_user_agent() == CLI_USER_AGENT


def test_direct_call_session_carries_cli_ua():
    # requests.post()/get() (the CLI's direct calls) build a Session that seeds
    # its headers from the patched default.
    set_user_agent()
    assert requests.Session().headers["User-Agent"] == CLI_USER_AGENT


# --- SDK calls: auth-callable override -------------------------------------


def test_sdk_request_carries_sdk_ua():
    set_user_agent()
    assert _sdk_prepared_ua() == SDK_USER_AGENT


def test_sdk_auth_header_still_applied():
    # The override must not displace the Authorization header the provider sets.
    set_user_agent()
    provider = ApiKeyAuthenticationHeadersProvider(ApiKey("id", "secret"))
    session = requests.Session()
    prepared = session.prepare_request(
        requests.Request("GET", "https://example.invalid", auth=provider)
    )
    assert prepared.headers["Authorization"].startswith("yd-key ")
    assert prepared.headers["User-Agent"] == SDK_USER_AGENT


def test_set_user_agent_idempotent():
    set_user_agent()
    set_user_agent()
    ua = _sdk_prepared_ua()
    assert ua == SDK_USER_AGENT
    # The SDK token must appear exactly once despite repeated patching.
    assert ua.count(_SDK_TOKEN) == 1


# --- the baseline alone, and an SDK without the callable --------------------


def test_the_baseline_alone_imports_no_sdk():
    """
    set_proxy() sets the baseline for the PAC file's fetch, in yd-variables
    too, which uses no client: it must not import the SDK, as the full
    set_user_agent() does to wrap the SDK's auth callable.
    """
    import subprocess
    import sys

    script = (
        "import sys\n"
        "from yellowdog_cli.utils.user_agent import set_default_user_agent, CLI_USER_AGENT\n"
        "import requests.utils\n"
        "set_default_user_agent()\n"
        "assert requests.utils.default_user_agent() == CLI_USER_AGENT\n"
        "print('yellowdog_client' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"


def test_set_proxy_sets_only_the_baseline(monkeypatch):
    from types import SimpleNamespace

    from yellowdog_cli.utils import user_agent, wrapper

    calls: list[str] = []
    monkeypatch.setattr(
        user_agent, "set_default_user_agent", lambda: calls.append("baseline")
    )
    monkeypatch.setattr(user_agent, "set_user_agent", lambda: calls.append("full"))
    monkeypatch.setattr(
        wrapper, "CONFIG_COMMON", SimpleNamespace(use_pac=True, url="https://x")
    )

    class _NoProxy:
        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    import pypac

    monkeypatch.setattr(pypac, "pac_context_for_url", lambda url: _NoProxy())
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    wrapper.set_proxy()
    assert calls == ["baseline"]


def test_an_sdk_without_the_auth_callable_keeps_the_baseline(monkeypatch):
    import yellowdog_client.common.credentials as credentials

    from yellowdog_cli.utils import user_agent

    monkeypatch.delattr(credentials, "ApiKeyAuthenticationHeadersProvider")
    debug: list[str] = []
    import yellowdog_cli.utils.printing as printing

    monkeypatch.setattr(printing, "print_debug", debug.append)
    user_agent.set_user_agent()  # No exception: the header is cosmetic
    assert requests.utils.default_user_agent() == CLI_USER_AGENT
    assert debug and "keep the CLI's User-Agent" in debug[0]
