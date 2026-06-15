"""
Configuration and utilities related to GCP account setup.
"""

from google.cloud import compute_v1
from google.oauth2 import service_account
from google.oauth2.service_account import Credentials
from yellowdog_client import PlatformClient

from yellowdog_cli.create import create_resources
from yellowdog_cli.utils.cloudwizard_common import CommonCloudConfig
from yellowdog_cli.utils.interactive import select
from yellowdog_cli.utils.printing import print_info, print_warning
from yellowdog_cli.utils.settings import RN_SOURCE_TEMPLATE

YD_KEYRING_NAME = "cloudwizard-gcp"
YD_CREDENTIAL_NAME = "cloudwizard-gcp"
YD_RESOURCE_PREFIX = "cloudwizard-gcp"
YD_RESOURCES_FILE = f"{YD_RESOURCE_PREFIX}-yellowdog-resources.json"
YD_INSTANCE_TAG = {"yd-cloudwizard": "yellowdog-cloudwizard-source"}
YD_DEFAULT_INSTANCE_TYPE = "{{instance_type:=f1-micro}}"


class GCPConfig(CommonCloudConfig):
    """
    Class for GCP resource creation.
    """

    def __init__(
        self, service_account_file: str, client: PlatformClient, instance_type: str
    ):
        super().__init__(client=client, cloud_provider="GCP")
        self._service_account_file = service_account_file
        try:
            self._credentials: Credentials = (
                service_account.Credentials.from_service_account_file(
                    service_account_file
                )
            )
        except FileNotFoundError:
            raise FileNotFoundError(
                f"GCP credentials file '{service_account_file}' not found"
            )

        self._regions_with_default_subnets: list[str] = []
        self._selected_regions: list[str] = []
        self._instance_type = (
            YD_DEFAULT_INSTANCE_TYPE if instance_type is None else instance_type
        )

    def setup(self):
        """
        Set up GCP and YellowDog assets in their respective accounts.
        """
        self._create_gcp_resources()
        self._create_yellowdog_resources()

    def teardown(self):
        """
        Remove YellowDog and GCP assets from their respective accounts.
        """
        self._remove_yellowdog_resources()
        self._remove_gcp_resources()

    def _create_gcp_resources(self):
        """
        Set up resources within GCP
        """

    def _remove_gcp_resources(self):
        """
        Remove any resources created within GCP.
        """

    def _create_yellowdog_resources(self):
        """
        Set up YellowDog assets.
        """
        print_info(
            "Please select the Google Compute Engine regions for which to create"
            " YellowDog Compute Source Templates"
        )
        self._gather_regions()
        self._selected_regions = select(
            client=self._client,
            objects=self._regions_with_default_subnets,
            object_type_name="region",
            force_interactive=True,
            override_quiet=True,
        )

        if not self._selected_regions:
            print_warning(
                "No regions selected; no Compute Source/Requirement Templates will be"
                " created"
            )
            return

        # Create Compute Source Templates
        for region in self._selected_regions:
            name = f"{YD_RESOURCE_PREFIX}-{region}-spot"
            self._source_template_resources.append(
                self._generate_gcp_compute_source_template(
                    region=region, name=name, spot=True
                )
            )
            self._source_names_spot.append(name)
            name = f"{YD_RESOURCE_PREFIX}-{region}-ondemand"
            self._source_template_resources.append(
                self._generate_gcp_compute_source_template(
                    region=region, name=name, spot=False
                )
            )
            self._source_names_ondemand.append(name)
        print_info("Creating YellowDog Compute Source Templates")
        create_resources(self._source_template_resources)

        # Create Compute Requirement Templates
        self._create_compute_requirement_templates(resource_prefix=YD_RESOURCE_PREFIX)

        # Create Keyring and remember the Keyring password
        self._create_keyring(keyring_name=YD_KEYRING_NAME)

        # Create Credential and add to Keyring
        create_resources(
            [self._generate_yd_gcp_credential(YD_KEYRING_NAME, YD_CREDENTIAL_NAME)]
        )

        # Save the Compute Requirement and Source Templates
        self._save_resource_list(
            self._requirement_template_resources + self._source_template_resources,
            YD_RESOURCES_FILE,
        )

        # Always show the Keyring details
        self._print_keyring_details()

    def _remove_yellowdog_resources(self):
        """
        Remove YellowDog resources in the Platform account.
        """
        self._remove_yd_templates_by_prefix(
            client=self._client, name_prefix=YD_RESOURCE_PREFIX
        )
        self._remove_keyring(YD_KEYRING_NAME)

    def _gather_regions(self):
        """
        Find the regions in the default VPC with default subnets.
        """
        try:
            networks = compute_v1.NetworksClient(credentials=self._credentials).list(
                project=self._credentials.project_id
            )
        except Exception as e:
            if "401" in str(e):
                raise RuntimeError(f"Invalid GCP credentials: {e}")
            else:
                raise e

        for network in networks:
            if network.name == "default":
                for subnet in network.subnetworks:
                    # Exact-match the final path component: a substring test
                    # would also match e.g. '/subnetworks/my-default'
                    if subnet.endswith("/subnetworks/default"):
                        region = subnet.replace(
                            "https://www.googleapis.com/compute/v1/projects/"
                            f"{self._credentials.project_id}/regions/",
                            "",
                        ).replace("/subnetworks/default", "")
                        self._regions_with_default_subnets.append(region)
                break
        else:
            print_warning(
                f"Default VPC not found for project '{self._credentials.project_id}'"
            )

    def _generate_gcp_compute_source_template(
        self, region: str, name: str, spot: bool
    ) -> dict:
        """
        Generate a GCP Compute Source Template resource definition.
        """
        spot_str = "Spot" if spot is True else "On-Demand"
        return {
            "resource": RN_SOURCE_TEMPLATE,
            "namespace": self._namespace,
            "description": (
                f"GCE {region} {spot_str} Compute Source Template automatically created"
                " by YellowDog Cloud Wizard"
            ),
            "source": {
                "assignPublicIp": True,
                "credential": f"{YD_KEYRING_NAME}/{YD_CREDENTIAL_NAME}",
                "image": "*",
                "machineType": "*",
                "name": name,
                "preemptible": False,
                "project": self._credentials.project_id,
                "region": region,
                "spot": spot,
                "type": "co.yellowdog.platform.model.GceInstancesComputeSource",
            },
        }

    def _generate_yd_gcp_credential(
        self,
        keyring_name: str,
        credential_name: str,
    ) -> dict:
        """
        Generate a GCP Credential resource definition.
        """
        with open(self._service_account_file) as f:
            service_account_file_contents = f.read()
        return {
            "resource": "Credential",
            "keyringName": keyring_name,
            "credential": {
                "type": (
                    "co.yellowdog.platform.account.credentials.GoogleCloudCredential"
                ),
                "name": credential_name,
                "description": (
                    "GCP credential automatically created by YellowDog Cloud Wizard"
                ),
                "serviceAccountKeyJson": service_account_file_contents,
            },
        }
