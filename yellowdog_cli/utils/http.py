"""
The CLI's direct HTTP requests: those it makes with 'requests' rather than
through the YellowDog SDK (the raw Work Requirement submission, event
streams, the usage report, the calls the SDK has no method for, yd-doctor's
checks and the PAC file's fetch). Each carries user_agent.CLI_USER_AGENT,
which names the CLI as the client, so the Platform never adapts the raw JSON
the CLI reads itself as it would an older SDK's. Every direct request is
made here: tests/test_http.py fails on one made with 'requests' itself.

It imports no SDK, so a command using none (yd-variables, under PAC) can
use it.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

import requests

from yellowdog_cli.utils.user_agent import CLI_USER_AGENT


def request(
    method: str, url: str, *, headers: Mapping[str, str] | None = None, **kwargs: Any
) -> requests.Response:
    """
    requests.request() with the CLI's User-Agent, which a caller's own
    headers may replace.
    """
    return requests.request(
        method, url, headers={"User-Agent": CLI_USER_AGENT, **(headers or {})}, **kwargs
    )


def get(url: str, **kwargs: Any) -> requests.Response:
    """
    A GET with the CLI's User-Agent.
    """
    return request("GET", url, **kwargs)


def post(url: str, **kwargs: Any) -> requests.Response:
    """
    A POST with the CLI's User-Agent.
    """
    return request("POST", url, **kwargs)


def put(url: str, **kwargs: Any) -> requests.Response:
    """
    A PUT with the CLI's User-Agent.
    """
    return request("PUT", url, **kwargs)


def delete(url: str, **kwargs: Any) -> requests.Response:
    """
    A DELETE with the CLI's User-Agent.
    """
    return request("DELETE", url, **kwargs)


@contextmanager
def pac_context(url: str) -> Iterator[None]:
    """
    pypac's pac_context_for_url(), with the PAC file fetched with the CLI's
    User-Agent: HTTPS_PROXY is set, while it is open, to the proxy the PAC
    file gives for url, if one is found.
    """
    from pypac import get_pac, pac_context_for_url

    session = requests.Session()
    session.headers["User-Agent"] = CLI_USER_AGENT
    pac = get_pac(session=session)
    # Given no PAC, pac_context_for_url() would look for one again, with its
    # own session
    if pac is None:
        yield
        return
    with pac_context_for_url(url, pac=pac):
        yield
