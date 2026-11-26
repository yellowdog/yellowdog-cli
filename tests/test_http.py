"""
utils/http.py, through which the CLI makes its direct requests: each carries
the CLI's User-Agent, the PAC file's fetch included, and no direct request
is made with 'requests' itself anywhere else in the package.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pypac
import pytest
import requests

from yellowdog_cli.utils import http
from yellowdog_cli.utils.user_agent import CLI_USER_AGENT

_PACKAGE = Path(__file__).resolve().parent.parent / "yellowdog_cli"


class _Sent(Exception):
    pass


@pytest.fixture
def sent(monkeypatch) -> list[requests.PreparedRequest]:
    """
    Each request as it leaves; none reaches the network.
    """
    seen: list[requests.PreparedRequest] = []

    def send(_session, request, **_kwargs):
        seen.append(request)
        raise _Sent()

    monkeypatch.setattr(requests.Session, "send", send)
    return seen


@pytest.mark.parametrize(
    "call, method",
    [
        (http.get, "GET"),
        (http.post, "POST"),
        (http.put, "PUT"),
        (http.delete, "DELETE"),
    ],
)
def test_a_direct_request_carries_the_cli_user_agent(sent, call, method):
    with pytest.raises(_Sent):
        call(url="https://example.invalid/x", headers={"Authorization": "yd-key k:s"})
    [request] = sent
    assert request.method == method
    assert request.headers["User-Agent"] == CLI_USER_AGENT
    assert request.headers["Authorization"] == "yd-key k:s"


def test_the_pac_file_is_fetched_with_the_cli_user_agent(monkeypatch):
    sessions: list[requests.Session] = []
    monkeypatch.setattr(
        pypac, "get_pac", lambda session: sessions.append(session) or "the PAC"
    )
    resolved: list[tuple] = []

    class _Context:
        def __init__(self, url, pac):
            resolved.append((url, pac))

        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(pypac, "pac_context_for_url", _Context)
    with http.pac_context("https://api.example.invalid"):
        pass
    [session] = sessions
    assert session.headers["User-Agent"] == CLI_USER_AGENT
    assert resolved == [("https://api.example.invalid", "the PAC")]


def test_no_pac_found_is_not_looked_for_again(monkeypatch):
    """
    pac_context_for_url(), given no PAC, would look for one itself.
    """
    monkeypatch.setattr(pypac, "get_pac", lambda session: None)

    def refuse(*_args, **_kwargs):
        raise AssertionError("pac_context_for_url() called with no PAC")

    monkeypatch.setattr(pypac, "pac_context_for_url", refuse)
    with http.pac_context("https://api.example.invalid"):
        pass


def test_it_imports_no_sdk():
    """
    set_proxy() uses it for the PAC file's fetch in yd-variables too, which
    builds no client.
    """
    script = (
        "import sys\n"
        "import yellowdog_cli.utils.http\n"
        "print('yellowdog_client' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"


_REQUESTING = {"request", "get", "post", "put", "patch", "delete", "head", "options"}
_REQUESTING |= {"Session", "session"}


def _root_name(node: ast.Attribute) -> str | None:
    """
    The name an attribute chain starts from: 'requests' in requests.api.get.
    """
    value = node.value
    while isinstance(value, ast.Attribute):
        value = value.value
    return value.id if isinstance(value, ast.Name) else None


def _direct_requests(tree: ast.AST) -> list[str]:
    # The names 'requests' is bound to: 'rq' in 'import requests as rq'
    modules = {
        alias.asname or "requests"
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name == "requests" or alias.name.startswith("requests.")
    }
    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in _REQUESTING
            and _root_name(node) in modules
        ):
            found.append(f"{ast.unparse(node)} (line {node.lineno})")
        elif isinstance(node, ast.ImportFrom) and node.module in (
            "requests",
            "requests.api",
            "requests.sessions",
        ):
            found += [
                f"from {node.module} import {alias.name} (line {node.lineno})"
                for alias in node.names
                if alias.name in _REQUESTING
            ]
        # pypac fetches the PAC file with a session of its own unless given one
        elif (isinstance(node, ast.ImportFrom) and node.module == "pypac") or (
            isinstance(node, ast.Import)
            and any(alias.name == "pypac" for alias in node.names)
        ):
            found.append(f"pypac (line {node.lineno})")
    return found


def test_every_direct_request_is_made_through_http():
    """
    A request made with 'requests' itself would send python-requests as its
    User-Agent.
    """
    offenders = {}
    for path in sorted(_PACKAGE.rglob("*.py")):
        if path == _PACKAGE / "utils" / "http.py":
            continue
        found = _direct_requests(ast.parse(path.read_text(encoding="utf-8")))
        if found:
            offenders[str(path.relative_to(_PACKAGE))] = found
    assert offenders == {}
