"""
Unit tests for yd-application's output.

Covers:
  - report_application()   the '--json' payload and the human-readable report,
                           and what a failed groups/roles lookup does to each
  - _portal_url()          deriving the Portal's sign-in URL from the API's
"""

from json import loads as json_loads
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from requests import ConnectionError as RequestsConnectionError
from requests import HTTPError, Response
from yellowdog_client.model import ApplicationDetails, Feature

import yellowdog_cli.application as application_module
from yellowdog_cli.application import _portal_url, report_application
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.exit_codes import ExitCode

API_URL = "https://api.yellowdog.ai"
NON_API_URL = "https://yd.example.com/api"
APP_ID = "ydid:app:000000:1d0a6a5c-3f9e-4d1e-8a2e-3a2f1b0c9d8e"


def _http_error(status_code: int, text: str) -> HTTPError:
    response = Response()
    response.status_code = status_code
    return HTTPError(text, response=response)


# As the SDK raises them: the Platform's MissingPermissionException is not
# one of the SDK's error types, so it arrives as a plain HTTPError
FORBIDDEN = _http_error(
    403,
    "403 Client Error: Forbidden for url: https://api.yellowdog.ai/x "
    'Response Body: {"errorType": "MissingPermissionException"}',
)
CONNECTION_RESET = RequestsConnectionError("connection reset")


def _application_details() -> ApplicationDetails:
    return ApplicationDetails(
        accountId="acc-1",
        accountName="my-account",
        id=APP_ID,
        name="my-app",
        allNamespacesReadable=False,
        readableNamespaces=["ns1", "ns2"],
        features=[Feature.PLATFORM],
    )


def _args(json_output: bool) -> MagicMock:
    args = MagicMock()
    args.json_output = json_output
    args.debug = False
    args.quiet = False
    args.count_only = False
    args.no_format = True
    args.strip_ids = False
    args.output_file = None
    return args


def _run(
    capsys,
    json_output: bool,
    url: str = API_URL,
    groups: list[str] | None = None,
    roles: dict | None = None,
    groups_error: Exception | None = None,
    debug: bool = False,
) -> str:
    """
    Run report_application() with the platform lookups stubbed, and return
    everything it printed to stdout.
    """
    groups = ["group-a", "group-b"] if groups is None else groups
    roles = {"ADMINISTRATOR": ["GLOBAL"]} if roles is None else roles

    mock_groups = MagicMock()
    if groups_error is not None:
        mock_groups.side_effect = groups_error
    else:
        mock_groups.return_value = [SimpleNamespace(name=name) for name in groups]

    mock_roles = MagicMock()
    if groups_error is not None:
        mock_roles.side_effect = groups_error
    else:
        mock_roles.return_value = roles

    args = _args(json_output)
    args.debug = debug
    ctx = RunContext(args=args, config=SimpleNamespace(url=url), client=MagicMock())
    with (
        patch.object(
            application_module,
            "get_application_details",
            MagicMock(return_value=_application_details()),
        ),
        patch.object(
            application_module, "get_application_group_summaries", mock_groups
        ),
        patch.object(
            application_module,
            "get_all_roles_and_namespaces_for_application",
            mock_roles,
        ),
        patch("yellowdog_cli.utils.printing.ARGS_PARSER", args),
    ):
        report_application(ctx)

    return capsys.readouterr().out


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


class TestJsonOutput:
    def test_application_details_fields_are_emitted_verbatim(self, capsys):
        payload = json_loads(_run(capsys, json_output=True))
        assert payload["name"] == "my-app"
        assert payload["id"] == APP_ID
        assert payload["accountName"] == "my-account"
        assert payload["accountId"] == "acc-1"
        assert payload["allNamespacesReadable"] is False
        assert payload["readableNamespaces"] == ["ns1", "ns2"]
        assert payload["features"] == ["PLATFORM"]

    def test_properties_are_emitted_in_alphabetical_order(self, capsys):
        # json_loads preserves the order in which the properties were emitted
        payload = json_loads(_run(capsys, json_output=True))
        assert list(payload) == [
            "accountId",
            "accountName",
            "allNamespacesReadable",
            "features",
            "groups",
            "id",
            "name",
            "portalUrl",
            "readableNamespaces",
            "roles",
        ]

    def test_portal_url_groups_and_roles_are_added(self, capsys):
        payload = json_loads(_run(capsys, json_output=True))
        assert payload["portalUrl"] == (
            "https://portal.yellowdog.ai/#/signin?account=my-account"
        )
        assert payload["groups"] == ["group-a", "group-b"]
        assert payload["roles"] == {"ADMINISTRATOR": ["GLOBAL"]}

    def test_a_url_without_an_api_host_is_used_as_it_is(self, capsys):
        payload = json_loads(_run(capsys, json_output=True, url=NON_API_URL))
        assert payload["portalUrl"] == (
            "https://yd.example.com/api/#/signin?account=my-account"
        )

    def test_groups_and_roles_are_null_without_the_permission_to_see_them(self, capsys):
        output = _run(capsys, json_output=True, groups_error=FORBIDDEN)
        payload = json_loads(output)
        assert payload["groups"] is None
        assert payload["roles"] is None
        # Why, as the report's line says it
        assert payload["groupsAndRoles"] == "permission denied"

    def test_groups_and_roles_says_nothing_when_they_are_there(self, capsys):
        assert "groupsAndRoles" not in json_loads(_run(capsys, json_output=True))

    def test_any_other_failure_is_null_with_a_warning_and_its_exit_code(self, capsys):
        with pytest.raises(SystemExit) as raised:
            _run(capsys, json_output=True, groups_error=CONNECTION_RESET)
        assert raised.value.code == ExitCode.CONNECTION
        captured = capsys.readouterr()
        payload = json_loads(captured.out)  # the document alone, on stdout
        assert payload["groups"] is None
        assert payload["roles"] is None
        assert payload["name"] == "my-app"
        assert "Unable to determine groups and roles: connection reset" in (
            captured.err
        )

    def test_no_groups_is_distinguishable_from_undeterminable_groups(self, capsys):
        payload = json_loads(_run(capsys, json_output=True, groups=[], roles={}))
        assert payload["groups"] == []
        assert payload["roles"] == {}

    def test_nothing_but_json_is_printed(self, capsys):
        # The report's own lines use print_simple(override_quiet=True), which
        # would otherwise print straight through '--json'.
        output = _run(capsys, json_output=True)
        assert "Application name:" not in output
        json_loads(output)  # parses as a whole, so nothing else was printed


# ---------------------------------------------------------------------------
# Human-readable report
# ---------------------------------------------------------------------------


class TestHumanReadableReport:
    def test_report_shows_the_application_and_its_groups_and_roles(self, capsys):
        output = _run(capsys, json_output=False)
        assert "Application name:" in output
        assert "my-app" in output
        assert "Portal URL:" in output
        assert "group-a, group-b" in output
        assert "ADMINISTRATOR [GLOBAL]" in output
        assert "Readable namespaces:" in output

    def test_report_shows_a_url_without_an_api_host_as_it_is(self, capsys):
        output = _run(capsys, json_output=False, url=NON_API_URL)
        assert "https://yd.example.com/api/#/signin?account=my-account" in output

    def test_report_explains_a_forbidden_groups_lookup(self, capsys):
        output = _run(capsys, json_output=False, groups_error=FORBIDDEN)
        assert "Cannot be determined due to application permissions" in output
        assert "Unable to determine" not in output

    def test_report_warns_on_any_other_groups_failure_and_exits(self, capsys):
        with pytest.raises(SystemExit) as raised:
            _run(capsys, json_output=False, groups_error=CONNECTION_RESET)
        assert raised.value.code == ExitCode.CONNECTION
        output = capsys.readouterr().out
        assert "Application name:" in output  # the rest is still reported
        assert "In group(s):" not in output
        assert "due to application permissions" not in output
        assert "Unable to determine groups and roles: connection reset" in output

    def test_an_unclassified_failure_exits_1(self, capsys):
        with pytest.raises(SystemExit) as raised:
            _run(capsys, json_output=False, groups_error=Exception("odd"))
        assert raised.value.code == ExitCode.FAILURE

    def test_debug_raises_the_failure_for_its_traceback(self, capsys):
        with pytest.raises(RequestsConnectionError):
            _run(
                capsys,
                json_output=False,
                groups_error=CONNECTION_RESET,
                debug=True,
            )

    def test_report_with_no_groups_or_roles_says_none(self, capsys):
        output = _run(capsys, json_output=False, groups=[], roles={})
        lines = output.splitlines()
        assert any(
            line.startswith("  In group(s):") and line.endswith("none")
            for line in lines
        )
        assert any(
            line.startswith("  With role(s) [in namespace(s)]:")
            and line.endswith("none")
            for line in lines
        )

    def test_every_value_starts_in_one_column(self, capsys):
        # Worked out from the longest label, the roles' own: two spaces, the
        # label and its colon, then four spaces
        output = _run(
            capsys, json_output=False, roles={"ADMIN": ["GLOBAL"], "VIEWER": ["ns"]}
        )
        column = len("  With role(s) [in namespace(s)]:    ")
        values = [line for line in output.splitlines() if line.strip()]
        assert (
            values[0]
            == "  Application name:"
            + " " * (column - len("  Application name:"))
            + "my-app"
        )
        # A second role continues under the first
        assert values[-1] == " " * column + "VIEWER [ns]"

    def test_a_role_with_no_namespaces_has_no_empty_brackets(self, capsys):
        output = _run(capsys, json_output=False, roles={"VIEWER": []})
        assert "VIEWER" in output
        assert "VIEWER []" not in output


# ---------------------------------------------------------------------------
# The Portal URL
# ---------------------------------------------------------------------------


class TestPortalUrl:
    @pytest.mark.parametrize(
        "url, expected",
        [
            ("https://api.yellowdog.ai", "https://portal.yellowdog.ai"),
            ("https://api.yellowdog.ai/", "https://portal.yellowdog.ai"),
            ("https://API.yellowdog.ai", "https://portal.yellowdog.ai"),
            ("https://api.eu.yellowdog.ai", "https://portal.eu.yellowdog.ai"),
            ("https://api.example.com:8443", "https://portal.example.com:8443"),
        ],
    )
    def test_an_api_host_becomes_portal(self, url, expected):
        assert _portal_url(url, "acct") == f"{expected}/#/signin?account=acct"

    @pytest.mark.parametrize(
        "url, expected",
        [
            ("https://yd.example.com/api", "https://yd.example.com/api"),
            ("https://yd.example.com/api/", "https://yd.example.com/api"),
            ("https://capital.example.com/rapid", "https://capital.example.com/rapid"),
            ("https://myapihost.example.com", "https://myapihost.example.com"),
        ],
    )
    def test_any_other_url_is_used_as_it_is(self, url, expected):
        assert _portal_url(url, "acct") == f"{expected}/#/signin?account=acct"

    def test_a_path_is_kept_under_an_api_host(self):
        assert _portal_url("https://api.capital.example.com/api", "acct") == (
            "https://portal.capital.example.com/api/#/signin?account=acct"
        )

    @pytest.mark.parametrize("account_name", [None, ""])
    def test_no_account_name_is_not_derivable(self, account_name):
        assert _portal_url(API_URL, account_name) is None

    def test_the_account_name_is_url_encoded(self):
        assert _portal_url(API_URL, "a b&c") == (
            "https://portal.yellowdog.ai/#/signin?account=a%20b%26c"
        )
