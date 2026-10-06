#!/usr/bin/env python3

"""
A script for reporting on the details of the Application being used.
"""

import sys
from typing import Any, cast
from urllib.parse import quote

from yellowdog_client.common.json import Json
from yellowdog_client.model import ApplicationDetails

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_utils import (
    get_all_roles_and_namespaces_for_application,
    get_application_details,
    get_application_group_summaries,
)
from yellowdog_cli.utils.exit_codes import ExitCode, classify
from yellowdog_cli.utils.misc_utils import portal_base_url
from yellowdog_cli.utils.printing import print_json, print_simple, print_warning
from yellowdog_cli.utils.wrapper import main_wrapper

# What 'groupsAndRoles' says, under --json, when they are null for want of
# the permission to look them up
PERMISSION_DENIED = "permission denied"
ROLES_LABEL = "With role(s) [in namespace(s)]"


@main_wrapper
def main(ctx: RunContext):
    report_application(ctx)


def report_application(ctx: RunContext):
    """
    Report the details of the Application, as JSON or as a readable report.

    The groups and roles are left out (null in the JSON) when they can't be
    determined. Lacking the permission to look them up is an ordinary state
    for an Application, and is reported as such; any other failure is warned
    of, and exits with the failure's exit code once the rest is reported.
    """
    application_details: ApplicationDetails = get_application_details(ctx.client)
    portal_url = _portal_url(ctx.config.url, application_details.accountName)
    groups, roles, error = _groups_and_roles(ctx, cast(str, application_details.id))
    exit_code = None if error is None else classify(error)
    permission_denied = exit_code == ExitCode.PERMISSION

    if ctx.args.json_output:
        _print_json(application_details, portal_url, groups, roles, permission_denied)
    else:
        _print_report(application_details, portal_url, groups, roles, permission_denied)

    if error is not None and not permission_denied:
        print_warning(f"Unable to determine groups and roles: {error}")
        if ctx.args.debug:
            raise error
        sys.exit(exit_code)


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


def _print_json(
    application_details: ApplicationDetails,
    portal_url: str | None,
    groups: list[str] | None,
    roles: dict | None,
    permission_denied: bool,
):
    """
    Print the Application's details as JSON: the properties of the
    ApplicationDetails object, plus the derived and looked-up properties,
    in alphabetical order. When the groups and roles are null for want of
    the permission to look them up, 'groupsAndRoles' says so, as the
    report's line does; a lookup that failed otherwise exits non-zero.
    """
    # 'Json.dump' is typed as returning 'object'; it is a dict in practice
    application_data: Any = Json.dump(application_details)
    application_data.update(
        {
            "portalUrl": portal_url,
            "groups": groups,
            "roles": roles,
        }
    )
    if permission_denied:
        application_data["groupsAndRoles"] = PERMISSION_DENIED
    print_json(dict(sorted(application_data.items())))


def _print_report(
    application_details: ApplicationDetails,
    portal_url: str | None,
    groups: list[str] | None,
    roles: dict | None,
    permission_denied: bool,
):
    """
    Print the Application's details as a readable report. The groups and
    roles are left out when they can't be determined, with a line saying so
    when that is for want of permission; an Application with none says so.
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

    if permission_denied:
        rows.append(
            ("Groups and roles", "Cannot be determined due to application permissions")
        )
    elif groups is not None:
        rows.append(("In group(s)", ", ".join(groups) or "none"))
        role_lines = [
            f"{role} [{', '.join(namespaces)}]" if namespaces else role
            for role, namespaces in (roles or {}).items()
        ] or ["none"]
        rows.append((ROLES_LABEL, role_lines[0]))
        rows += [("", line) for line in role_lines[1:]]

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
