#!/usr/bin/env python3

"""
A script for reporting on the details of the Application being used.
"""

from typing import Any, cast

from yellowdog_client.common.json import Json
from yellowdog_client.model import ApplicationDetails

from yellowdog_cli.utils.entity_utils import (
    get_all_roles_and_namespaces_for_application,
    get_application_details,
    get_application_group_summaries,
)
from yellowdog_cli.utils.printing import print_json, print_simple, print_warning
from yellowdog_cli.utils.wrapper import (
    ARGS_PARSER,
    CLIENT,
    CONFIG_COMMON,
    main_wrapper,
)


@main_wrapper
def main():
    report_application()


def report_application():
    """
    Report the details of the Application, as JSON or as a readable report.
    """
    application_details: ApplicationDetails = get_application_details(CLIENT)
    portal_url = _portal_url(CONFIG_COMMON.url, application_details.accountName)
    groups, roles, error = _groups_and_roles(cast(str, application_details.id))

    if ARGS_PARSER.json_output:
        _print_json(application_details, portal_url, groups, roles)
    else:
        _print_report(application_details, portal_url, groups, roles, error)


def _portal_url(url: str, account_name: str | None) -> str | None:
    """
    The Portal sign-in URL for the account, or None when it can't be derived
    from the configured API URL.
    """
    if "api" not in url:
        return None
    return f"{url.replace('api', 'portal')}/#/signin?account={account_name}"


def _groups_and_roles(
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
            for group in get_application_group_summaries(CLIENT, application_id)
        ]
        roles = get_all_roles_and_namespaces_for_application(CLIENT, application_id)
        return groups, roles, None
    except Exception as e:
        return None, None, e


def _print_json(
    application_details: ApplicationDetails,
    portal_url: str | None,
    groups: list[str] | None,
    roles: dict | None,
):
    """
    Print the Application's details as JSON: the properties of the
    ApplicationDetails object, plus the derived and looked-up properties,
    in alphabetical order.
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
    print_json(dict(sorted(application_data.items())))


def _print_report(
    application_details: ApplicationDetails,
    portal_url: str | None,
    groups: list[str] | None,
    roles: dict | None,
    error: Exception | None,
):
    """
    Print the Application's details as a readable report.
    """
    print()
    print_simple(
        f"  Application name:                  {application_details.name}",
        override_quiet=True,
    )
    print_simple(
        f"  Application ID:                    {application_details.id}",
        override_quiet=True,
    )
    print_simple(
        f"  Account name:                      {application_details.accountName}",
        override_quiet=True,
    )
    if portal_url is not None:
        print_simple(
            f"  Portal URL:                        {portal_url}",
            override_quiet=True,
        )
    print_simple(
        f"  Account ID:                        {application_details.accountId}",
        override_quiet=True,
    )
    features = (
        ""
        if application_details.features is None
        else ", ".join([str(feature) for feature in application_details.features])
    )
    print_simple(
        f"  Account features:                  {features}",
        override_quiet=True,
    )
    all_ns_readable = "Yes" if application_details.allNamespacesReadable else "No"
    print_simple(
        f"  All namespaces readable:           {all_ns_readable}",
        override_quiet=True,
    )
    if not application_details.allNamespacesReadable:
        readable_namespaces = (
            ""
            if application_details.readableNamespaces is None
            else ", ".join(application_details.readableNamespaces)
        )
        print_simple(
            f"  Readable namespaces:               {readable_namespaces}",
            override_quiet=True,
        )

    if error is not None:
        if "Forbidden" in str(error):
            print_simple(
                "  Groups and roles:                  "
                "Cannot be determined due to application permissions",
                override_quiet=True,
            )
        else:
            print_warning(f"Unable to determine groups and roles: {error}")
        print()
        return

    print_simple(
        f"  In group(s):                       {', '.join(groups or [])}",
        override_quiet=True,
    )
    for i, (role, namespaces) in enumerate((roles or {}).items()):
        msg = f"{role} [{', '.join(namespaces)}]"
        if i == 0:
            print_simple(
                f"  With role(s) [in namespace(s)]:    {msg}",
                override_quiet=True,
            )
        else:
            print_simple(
                f"                                     {msg}",
                override_quiet=True,
            )
    print()
