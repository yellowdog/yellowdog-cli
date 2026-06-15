#!/usr/bin/env python3

"""
A script for reporting on the details of the Application being used.
"""

from typing import cast

from yellowdog_client.model import ApplicationDetails

from yellowdog_cli.utils.entity_utils import (
    get_all_roles_and_namespaces_for_application,
    get_application_details,
    get_application_group_summaries,
)
from yellowdog_cli.utils.printing import print_simple, print_warning
from yellowdog_cli.utils.wrapper import CLIENT, CONFIG_COMMON, main_wrapper


@main_wrapper
def main():

    application_details: ApplicationDetails = get_application_details(CLIENT)

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
    if "api" in CONFIG_COMMON.url:
        print_simple(
            "  Portal URL:                        "
            f"{CONFIG_COMMON.url.replace('api', 'portal')}"
            f"/#/signin?account={application_details.accountName}",
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
    try:
        groups = get_application_group_summaries(
            CLIENT, cast(str, application_details.id)
        )
        group_names = ", ".join([cast(str, group.name) for group in groups])
        print_simple(
            f"  In group(s):                       {group_names}",
            override_quiet=True,
        )
        for i, (role, namespaces) in enumerate(
            get_all_roles_and_namespaces_for_application(
                CLIENT, cast(str, application_details.id)
            ).items()
        ):
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

    except Exception as e:
        if "Forbidden" in str(e):
            print_simple(
                "  Groups and roles:                  "
                "Cannot be determined due to application permissions",
                override_quiet=True,
            )
        else:
            print_warning(f"Unable to determine groups and roles: {e}")
    print()
