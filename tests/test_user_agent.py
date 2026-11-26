"""
The User-Agent of the CLI's requests: its direct calls
(utils/direct_http.py) name the CLI as the client, in the SDKs' form, and
every Platform client it builds names the CLI through the SDK's own mechanism (a Product given to
PlatformClient.create()), which the SDK sends on each request.
"""

import sys
from types import SimpleNamespace

import pytest
import requests
from yellowdog_client import PlatformClient
from yellowdog_client._version import __version__ as _sdk_version
from yellowdog_client.common import Product
from yellowdog_client.model import ApiKey, ServicesSchema

import yellowdog_cli.utils.completion_lookups as completion_lookups
import yellowdog_cli.utils.doctor_checks as doctor_checks
import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli._version import __version__
from yellowdog_cli.utils.user_agent import CLI_USER_AGENT, cli_product

_CLI_TOKEN = f"yellowdog-cli/{__version__}"


# --- direct (non-SDK) calls -------------------------------------------------


def test_the_direct_calls_user_agent_names_the_cli_as_the_client():
    python = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert CLI_USER_AGENT == f"yd/1.1.0 {_CLI_TOKEN} python/{python}"


# --- SDK calls: the CLI as a product ----------------------------------------


def test_the_cli_product_is_its_name_and_version():
    assert cli_product() == Product("yellowdog-cli", __version__)


class _Sent(Exception):
    pass


def test_an_sdk_request_names_the_sdk_then_the_cli(monkeypatch):
    """
    What the SDK sends, captured as the request leaves: its own header, the
    CLI last.
    """
    seen: list[str] = []

    def send(_session, request, **_kwargs):
        seen.append(request.headers["User-Agent"])
        raise _Sent()

    monkeypatch.setattr(requests.Session, "send", send)
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
