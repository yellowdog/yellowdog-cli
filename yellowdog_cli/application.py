#!/usr/bin/env python3

"""
A script for reporting on the details of the Application being used.
"""

import logging
import sys
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import quote

from yellowdog_client.common.json import Json
from yellowdog_client.model import ApplicationDetails

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_utils import (
    get_all_roles_and_namespaces_for_application,
    get_application_details,
    get_application_group_summaries,
    get_application_keyrings,
    keyring_credential_names,
)
from yellowdog_cli.utils.exit_codes import ExitCode, classify
from yellowdog_cli.utils.misc_utils import portal_base_url
from yellowdog_cli.utils.printing import print_json, print_simple, print_warning
from yellowdog_cli.utils.wrapper import main_wrapper

_LOG = logging.getLogger(__name__)

# What 'groupsAndRoles' says, under --json, when they are null for want of
# the permission to look them up
PERMISSION_DENIED = "permission denied"
ROLES_LABEL = "With role(s) [in namespace(s)]"
KEYRINGS_LABEL = "Keyring(s) [credentials]"
NOT_PERMITTED = "Cannot be determined due to application permissions"


@main_wrapper
def main(ctx: RunContext):
    report_application(ctx)


def report_application(ctx: RunContext):
    """
    Report the details of the Application, as JSON or as a readable report.

    The groups and roles, and the Keyrings the Application can use, are each
    left out (null in the JSON) when they can't be determined. Lacking the
    permission to look them up is an ordinary state for an Application, and
    is reported as such; any other failure is warned of, and exits with the
    failure's exit code once the rest is reported.
    """
    application_details: ApplicationDetails = get_application_details(ctx.client)
    application_id = cast(str, application_details.id)
    portal_url = _portal_url(ctx.config.url, application_details.accountName)
    groups, roles, error = _groups_and_roles(ctx, application_id)
    keyrings, keyrings_error = _keyrings(ctx, application_id)
    lookups = _Lookups(
        groups_denied=_denied(error), keyrings_denied=_denied(keyrings_error)
    )

    if ctx.args.json_output:
        _print_json(application_details, portal_url, groups, roles, keyrings, lookups)
    else:
        _print_report(application_details, portal_url, groups, roles, keyrings, lookups)

    failures = [
        (what, e)
        for what, e in (
            ("groups and roles", error),
            ("the Keyrings it can use", keyrings_error),
        )
        if e is not None and not _denied(e)
    ]
    for what, e in failures:
        print_warning(f"Unable to determine {what}: {e}")
        _LOG.debug("Looking up %s failed", what, exc_info=e)
    if failures:
        sys.exit(classify(failures[0][1]))


@dataclass(frozen=True)
class _Lookups:
    """
    Which lookups the Application lacks the permission to make.
    """

    groups_denied: bool = False
    keyrings_denied: bool = False


def _denied(error: Exception | None) -> bool:
    """
    Whether a lookup failed for want of permission, an ordinary state for an
    Application rather than a failure.
    """
    return error is not None and classify(error) == ExitCode.PERMISSION


def _portal_url(url: str, account_name: str | None) -> str | None:
    """
    The Portal sign-in URL for the account, under the Portal's address as
    the CLI's other Portal links derive it (misc_utils.portal_base_url():
    'https://api.yellowdog.ai' gives 'https://portal.yellowdog.ai', and a
    URL without an 'api' host, such as 'https://host/api', is used as it
    is), or None when the account's name is not known.
    """
    if not account_name:
        return None
    return f"{portal_base_url(url)}/#/signin?account={quote(account_name, safe='')}"


def _groups_and_roles(
    ctx: RunContext,
    application_id: str,
) -> tuple[list[str] | None, dict | None, Exception | None]:
    """
    The names of the groups to which the Application belongs, and its roles
    with the namespaces to which they apply. Both are None, accompanied by
    the exception, when they can't be determined.
    """
    try:
        groups = [
            cast(str, group.name)
            for group in get_application_group_summaries(ctx.client, application_id)
        ]
        roles = get_all_roles_and_namespaces_for_application(ctx.client, application_id)
        return groups, roles, None
    except Exception as e:
        return None, None, e


def _keyrings(
    ctx: RunContext, application_id: str
) -> tuple[list[dict] | None, Exception | None]:
    """
    The Keyrings the Application can use, each as its name, ID and
    credential names; None, accompanied by the exception, when they can't be
    determined.
    """
    try:
        return [
            {
                "name": keyring.name,
                "id": keyring.id,
                "credentials": keyring_credential_names(keyring),
            }
            for keyring in get_application_keyrings(ctx.client, application_id)
        ], None
    except Exception as e:
        return None, e


def _print_json(
    application_details: ApplicationDetails,
    portal_url: str | None,
    groups: list[str] | None,
    roles: dict | None,
    keyrings: list[dict] | None,
    lookups: _Lookups,
):
    """
    Print the Application's details as JSON: the properties of the
    ApplicationDetails object, plus the derived and looked-up properties,
    in alphabetical order. When the groups and roles, or the Keyrings, are
    null for want of the permission to look them up, 'groupsAndRoles' or
    'keyringsLookup' says so, as the report's line does; a lookup that
    failed otherwise exits non-zero.
    """
    # 'Json.dump' is typed as returning 'object'; it is a dict in practice
    application_data: Any = Json.dump(application_details)
    application_data.update(
        {
            "portalUrl": portal_url,
            "groups": groups,
            "roles": roles,
            "keyrings": keyrings,
        }
    )
    if lookups.groups_denied:
        application_data["groupsAndRoles"] = PERMISSION_DENIED
    if lookups.keyrings_denied:
        application_data["keyringsLookup"] = PERMISSION_DENIED
    print_json(dict(sorted(application_data.items())))


def _print_report(
    application_details: ApplicationDetails,
    portal_url: str | None,
    groups: list[str] | None,
    roles: dict | None,
    keyrings: list[dict] | None,
    lookups: _Lookups,
):
    """
    Print the Application's details as a readable report. The groups and
    roles, and the Keyrings, are each left out when they can't be
    determined, with a line saying so when that is for want of permission;
    an Application with none says so.
    """
    features = (
        ""
        if application_details.features is None
        else ", ".join([str(feature) for feature in application_details.features])
    )
    rows: list[tuple[str, object]] = [
        ("Application name", application_details.name),
        ("Application ID", application_details.id),
        ("Account name", application_details.accountName),
    ]
    if portal_url is not None:
        rows.append(("Portal URL", portal_url))
    rows += [
        ("Account ID", application_details.accountId),
        ("Account features", features),
        (
            "All namespaces readable",
            "Yes" if application_details.allNamespacesReadable else "No",
        ),
    ]
    if not application_details.allNamespacesReadable:
        rows.append(
            (
                "Readable namespaces",
                ", ".join(application_details.readableNamespaces or []),
            )
        )

    if lookups.groups_denied:
        rows.append(("Groups and roles", NOT_PERMITTED))
    elif groups is not None:
        rows.append(("In group(s)", ", ".join(groups) or "none"))
        role_lines = [
            f"{role} [{', '.join(namespaces)}]" if namespaces else role
            for role, namespaces in (roles or {}).items()
        ] or ["none"]
        rows.append((ROLES_LABEL, role_lines[0]))
        rows += [("", line) for line in role_lines[1:]]

    if lookups.keyrings_denied:
        rows.append(("Keyrings", NOT_PERMITTED))
    elif keyrings is not None:
        keyring_lines = [
            f"{k['name']} [{', '.join(k['credentials'])}]"
            if k["credentials"]
            else k["name"]
            for k in keyrings
        ] or ["none"]
        rows.append((KEYRINGS_LABEL, keyring_lines[0]))
        rows += [("", line) for line in keyring_lines[1:]]

    _print_rows(rows)


def _print_rows(rows: list[tuple[str, object]]) -> None:
    """
    The report's rows, each value starting in one column, worked out from
    the longest label; an empty label continues the row above it.
    """
    width = max(len(label) for label, _ in rows) + len(":    ")
    print_simple(override_quiet=True)
    for label, value in rows:
        labelled = f"{label}:" if label else ""
        print_simple(f"  {labelled:<{width}}{value}".rstrip(), override_quiet=True)
    print_simple(override_quiet=True)


if __name__ == "__main__":
    main()
