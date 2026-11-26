"""
The User-Agent of the CLI's requests: its direct calls carry a CLI-only one
(the requests default replaced), and every Platform client it builds names
the CLI through the SDK's own mechanism (a Product given to
PlatformClient.create()), which the SDK sends on each request over the
session's default.
"""

import subprocess
import sys
from types import SimpleNamespace

import pytest
import requests
import requests.utils
from yellowdog_client import PlatformClient
from yellowdog_client._version import __version__ as _sdk_version
from yellowdog_client.common import Product
from yellowdog_client.model import ApiKey, ServicesSchema

import yellowdog_cli.utils.completion_lookups as completion_lookups
import yellowdog_cli.utils.doctor_checks as doctor_checks
import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli._version import __version__
from yellowdog_cli.utils.user_agent import (
    CLI_USER_AGENT,
    cli_product,
    set_default_user_agent,
)

_CLI_TOKEN = f"yellowdog-cli/{__version__}"


# --- direct (non-SDK) calls: the requests default ---------------------------


def test_the_direct_calls_user_agent_names_the_cli_and_requests():
    assert CLI_USER_AGENT.startswith(f"{_CLI_TOKEN} python-requests/")
    assert "sdk" not in CLI_USER_AGENT


def test_a_direct_calls_session_carries_it():
    # requests.get()/post() (the CLI's direct calls) build a Session that
    # seeds its headers from the replaced default
    set_default_user_agent()
    set_default_user_agent()  # idempotent
    assert requests.utils.default_user_agent() == CLI_USER_AGENT
    assert requests.Session().headers["User-Agent"] == CLI_USER_AGENT


def test_the_direct_calls_user_agent_imports_no_sdk():
    """
    set_proxy() sets it for the PAC file's fetch, in yd-variables too, which
    builds no client: it must not import the SDK.
    """
    script = (
        "import sys\n"
        "from yellowdog_cli.utils.user_agent import set_default_user_agent\n"
        "set_default_user_agent()\n"
        "print('yellowdog_client' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"


# --- SDK calls: the CLI as a product ----------------------------------------


def test_the_cli_product_is_its_name_and_version():
    assert cli_product() == Product("yellowdog-cli", __version__)


class _Sent(Exception):
    pass


def test_an_sdk_request_names_the_sdk_then_the_cli(monkeypatch):
    """
    What the SDK sends, captured as the request leaves: its own header, the
    CLI last, and the direct calls' default not reaching it.
    """
    seen: list[str] = []

    def send(_session, request, **_kwargs):
        seen.append(request.headers["User-Agent"])
        raise _Sent()

    monkeypatch.setattr(requests.Session, "send", send)
    set_default_user_agent()
    client = PlatformClient.create(
        ServicesSchema(defaultUrl="https://example.invalid/api"),
        ApiKey("id", "secret"),
        cli_product(),
    )
    with pytest.raises(_Sent):
        client.keyring_client.find_all_keyrings()
    [agent] = seen
    assert f"yellowdog-sdk-python/{_sdk_version}" in agent
    assert agent.endswith(f" {_CLI_TOKEN}")
    assert "python-requests" not in agent


@pytest.fixture
def products(monkeypatch) -> list:
    """
    The products each PlatformClient.create() is given; no client is built.
    """
    seen: list = []
    monkeypatch.setattr(
        PlatformClient,
        "create",
        staticmethod(lambda _schema, _key, *given: seen.append(given) or object()),
    )
    return seen


def test_every_client_the_cli_builds_names_it(products):
    common = SimpleNamespace(url="https://x", key="k", secret="s")
    wrapper_module._create_client()
    doctor_checks._build_client(common, 7)
    completion_lookups._client(common)  # type: ignore[arg-type]
    assert products == [(cli_product(),)] * 3


def test_the_commands_client_sets_the_direct_calls_user_agent(products, monkeypatch):
    monkeypatch.setattr(
        requests.utils, "default_user_agent", lambda *_a, **_k: "untouched"
    )
    wrapper_module._create_client()
    assert requests.utils.default_user_agent() == CLI_USER_AGENT


def test_set_proxy_sets_the_direct_calls_user_agent(monkeypatch):
    from yellowdog_cli.utils import user_agent

    calls: list[str] = []
    monkeypatch.setattr(
        user_agent, "set_default_user_agent", lambda: calls.append("default")
    )
    monkeypatch.setattr(
        wrapper_module, "CONFIG_COMMON", SimpleNamespace(use_pac=True, url="https://x")
    )

    class _NoProxy:
        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    import pypac

    monkeypatch.setattr(pypac, "pac_context_for_url", lambda url: _NoProxy())
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    wrapper_module.set_proxy()
    assert calls == ["default"]
