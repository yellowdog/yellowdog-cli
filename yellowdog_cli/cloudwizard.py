#!/usr/bin/env python

"""
Cloud Wizard: cloud provider and YellowDog account setup -- Compute Source
and Compute Requirement Templates, and the credentials they use. It creates
no cloud storage buckets and no namespace storage configurations.
"""

# CommonCloudConfig is imported for type checking only, so annotations must
# not be evaluated as the module loads (Python before 3.14 evaluates them)
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from yellowdog_cli.utils.check_imports import check_cloudwizard_imports
from yellowdog_cli.utils.command_registry import cloud_provider_of
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.exit_codes import ExitCode, ReportedFailure
from yellowdog_cli.utils.printing import print_error, print_info
from yellowdog_cli.utils.wrapper import main_wrapper

if TYPE_CHECKING:
    from yellowdog_cli.utils.cloudwizard.common import CommonCloudConfig


@main_wrapper
def main(ctx: RunContext):
    """
    Main dispatcher for Cloud Wizard setup and teardown. The provider, and
    what each operation needs, were checked as the command line was parsed.
    """

    check_cloudwizard_imports()

    provider = cloud_provider_of(ctx.args.cloud_provider)  # type: ignore[arg-type]
    print_info(f"YellowDog automated cloud provider setup/teardown for '{provider}'")
    if provider == "AWS":
        from yellowdog_cli.utils.cloudwizard.aws import AWSConfig

        cloud_provider_config = AWSConfig(
            ctx=ctx,
            region_name=ctx.args.region_name,
            show_secrets=ctx.args.show_secrets,
            instance_type=ctx.args.instance_type,  # type: ignore[arg-type]
        )
    elif provider == "GCP":
        from yellowdog_cli.utils.cloudwizard.gcp import GCPConfig

        cloud_provider_config = GCPConfig(
            service_account_file=ctx.args.credentials_file,  # type: ignore[arg-type]
            ctx=ctx,
            instance_type=ctx.args.instance_type,  # type: ignore[arg-type]
        )
    else:
        from yellowdog_cli.utils.cloudwizard.azure import AzureConfig

        cloud_provider_config = AzureConfig(
            ctx=ctx,
            instance_type=ctx.args.instance_type,  # type: ignore[arg-type]
        )

    run_operation(
        cloud_provider_config,
        ctx.args.operation,  # type: ignore[arg-type]  # A required positional
        ctx.args.region_name,
    )


def run_operation(
    config: CommonCloudConfig, operation: str, region_name: str | None
) -> None:
    """
    Run one Cloud Wizard operation on a provider's configuration, and exit 1
    if it reported an error.
    """
    from yellowdog_cli.utils.cloudwizard.common import errors_reported

    if operation == "setup":
        try:
            config.setup()
        finally:
            # The Keyring's password is shown only this once: however setup
            # ends, a Keyring it created is not left unclaimable
            config.print_keyring_details()

    elif operation == "teardown":
        config.teardown()
        if config.platform_failure is not None:
            # The YellowDog removals stopped, and the cloud provider's ran
            print_error(
                "The YellowDog resources were not all removed; run teardown"
                " again to remove what is left"
            )
            raise ReportedFailure(config.platform_failure)

    elif operation in ["add-ssh", "remove-ssh"]:
        config.set_ssh_ingress_rule(operation, region_name)

    # Each step carries on past a failure, so a teardown removes what it can;
    # a run that reported one is not a success
    if (errors := errors_reported()) > 0:
        print_error(f"Cloud Wizard finished with {errors} error(s)")
        sys.exit(ExitCode.FAILURE)


if __name__ == "__main__":
    """
    Standalone entry point
    """
    main()
