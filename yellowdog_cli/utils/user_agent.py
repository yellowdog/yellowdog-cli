"""
The User-Agent of the CLI's outgoing HTTP requests, which distinguishes the
CLI's own direct REST calls from calls made through the YellowDog SDK:

  * Direct CLI calls:  yd/1.1.0 yellowdog-cli/<ver> python/<ver>
  * SDK calls:         yd/1.1.0 yellowdog-sdk-python/<ver> python/<ver> yellowdog-cli/<ver>

The SDK writes its own header and adds the products a client is created
with (PlatformClient.create()'s Product arguments), so every client the CLI
builds is given cli_product(). The Platform then knows SDK calls for the
SDK's, and adapts its responses to the SDK's version.

The direct calls are made through direct_http.py, which sends
CLI_USER_AGENT. It has the SDKs' form, so the Platform reads it, but names
the CLI as the client, which the Platform does not know and so never
adapts for: the CLI reads those responses' JSON itself, not through the
SDK's models.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from yellowdog_cli._version import __version__

if TYPE_CHECKING:
    from yellowdog_client.common import Product

# The name the CLI is known by in a User-Agent, on its own calls and the SDK's
CLI_PRODUCT_NAME = "yellowdog-cli"

# Direct (non-SDK) CLI calls; yd/1.1.0 is the version of the header's form
CLI_USER_AGENT = (
    f"yd/1.1.0 {CLI_PRODUCT_NAME}/{__version__}"
    f" python/{sys.version_info.major}.{sys.version_info.minor}"
)


def cli_product() -> Product:
    """
    The CLI as a product for PlatformClient.create(), which the SDK adds to
    the User-Agent of every request the client makes. Imports the SDK, so it
    is called only where a client is built.
    """
    from yellowdog_client.common import Product

    return Product(CLI_PRODUCT_NAME, __version__)
