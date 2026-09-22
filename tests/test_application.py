"""
Unit tests for yd-application's output.

Covers:
  - report_application()   the '--json' payload and the human-readable report
"""

from json import loads as json_loads
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from yellowdog_client.model import ApplicationDetails, Feature

import yellowdog_cli.application as application_module
from yellowdog_cli.application import report_application

API_URL = "https://api.yellowdog.ai"
NON_API_URL = "https://yd.example.com"
APP_ID = "ydid:app:000000:1d0a6a5c-3f9e-4d1e-8a2e-3a2f1b0c9d8e"


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
    with (
        patch.object(application_module, "ARGS_PARSER", args),
        patch.object(application_module, "CLIENT", MagicMock()),
        patch.object(application_module, "CONFIG_COMMON", SimpleNamespace(url=url)),
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
        report_application()

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

    def test_portal_url_is_null_when_the_url_is_not_derivable(self, capsys):
        payload = json_loads(_run(capsys, json_output=True, url=NON_API_URL))
        assert payload["portalUrl"] is None

    @pytest.mark.parametrize(
        "error",
        [Exception("Forbidden"), Exception("connection reset")],
    )
    def test_groups_and_roles_are_null_when_they_cannot_be_determined(
        self, capsys, error
    ):
        payload = json_loads(_run(capsys, json_output=True, groups_error=error))
        assert payload["groups"] is None
        assert payload["roles"] is None

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

    def test_report_omits_the_portal_url_when_it_is_not_derivable(self, capsys):
        output = _run(capsys, json_output=False, url=NON_API_URL)
        assert "Portal URL:" not in output

    def test_report_explains_a_forbidden_groups_lookup(self, capsys):
        output = _run(
            capsys, json_output=False, groups_error=Exception("Forbidden: nope")
        )
        assert "Cannot be determined due to application permissions" in output

    def test_report_warns_on_any_other_groups_failure(self, capsys):
        output = _run(
            capsys, json_output=False, groups_error=Exception("connection reset")
        )
        assert "Unable to determine groups and roles: connection reset" in output
