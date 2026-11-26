"""
The User-Agent of the CLI's outgoing HTTP requests, which distinguishes the
CLI's own direct REST calls from calls made through the YellowDog SDK:

  * Direct CLI calls:  yellowdog-cli/<ver> python-requests/<ver>
  * SDK calls:         yd/<ver> yellowdog-sdk-python/<ver> python/<ver> yellowdog-cli/<ver>

The SDK writes its own header and adds the products a client is created
with (PlatformClient.create()'s Product arguments), so every client the CLI
builds is given cli_product(). The SDK sets the header on each request, over
the session's default, so the baseline below never reaches SDK traffic.

The direct calls (the usage report, the raw Work Requirement submission,
yd-doctor's checks, an event stream reconnected by hand, the PAC file's
fetch) are made with requests, which the SDK has no part in: for them,
set_default_user_agent() replaces requests.utils.default_user_agent(), from
which every requests.Session seeds its headers, so their call sites need no
changes. It imports no SDK, so a command using none (yd-variables, under
PAC) can set it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import requests.utils

from yellowdog_cli._version import __version__

if TYPE_CHECKING:
    from yellowdog_client.common import Product

# The name the CLI is known by in a User-Agent, on its own calls and the SDK's
CLI_PRODUCT_NAME = "yellowdog-cli"

# Captured once, at import: the original requests User-Agent (requests/urllib3
# version), kept as the direct calls' suffix
_REQUESTS_UA = requests.utils.default_user_agent()

# Direct (non-SDK) CLI calls
CLI_USER_AGENT = f"{CLI_PRODUCT_NAME}/{__version__} {_REQUESTS_UA}"


def set_default_user_agent() -> None:
    """
    The User-Agent of every requests Session -- the CLI's direct calls --
    without importing the SDK. Idempotent.
    """
    requests.utils.default_user_agent = lambda *_args, **_kwargs: CLI_USER_AGENT


def cli_product() -> Product:
    """
    The CLI as a product for PlatformClient.create(), which the SDK adds to
    the User-Agent of every request the client makes. Imports the SDK, so it
    is called only where a client is built.
    """
    from yellowdog_client.common import Product

    return Product(CLI_PRODUCT_NAME, __version__)
