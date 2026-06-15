"""
Base class and utilities for Cloud Wizard.
"""

import json
from abc import ABC, abstractmethod
from copy import deepcopy
from os.path import exists

from yellowdog_client import PlatformClient

from yellowdog_cli.create import create_resources
from yellowdog_cli.remove import remove_resource_by_id
from yellowdog_cli.utils.compact_json import CompactJSONEncoder
from yellowdog_cli.utils.entity_utils import (
    clear_compute_requirement_template_cache,
    clear_compute_source_template_cache,
    get_compute_requirement_templates,
    get_compute_source_templates,
)
from yellowdog_cli.utils.interactive import confirmed
from yellowdog_cli.utils.printing import print_error, print_info, print_warning
from yellowdog_cli.utils.settings import RN_KEYRING, RN_REQUIREMENT_TEMPLATE
from yellowdog_cli.utils.variables import process_variable_substitutions_insitu

CLOUDWIZARD_NAMESPACE_PREFIX = "cloudwizard"


class CommonCloudConfig(ABC):
    """
    Abstract base class for Cloud Wizard cloud provider configuration classes.
    """

    def __init__(self, client: PlatformClient, cloud_provider: str = ""):
        self._cloud_provider = cloud_provider
        self._namespace = f"{CLOUDWIZARD_NAMESPACE_PREFIX}-{cloud_provider.lower()}"
        self._client = client

        self._instance_type: str | None = None
        self._source_names_spot: list[str] = []
        self._source_names_ondemand: list[str] = []
        self._source_template_resources: list[dict] = []
        self._requirement_template_resources: list[dict] = []

        self._keyring_name: str | None = None
        self._keyring_password: str | None = None

    @abstractmethod
    def setup(self):
        pass

    @abstractmethod
    def teardown(self):
        pass

    def set_ssh_ingress_rule(self, operation: str, selected_region: str | None = None):
        print_warning(
            f"Operation '{operation}' not supported for cloud provider"
            f" '{self._cloud_provider}'"
        )

    def _remove_yd_templates_by_prefix(self, client: PlatformClient, name_prefix: str):
        """
        Remove YellowDog Compute Source & Requirement Templates based on a prefix.
        """
        if not confirmed(
            f"Remove all Compute Requirement and Compute Source Templates in "
            f"namespace '{self._namespace}' with names starting with '{name_prefix}'?"
        ):
            return

        # Compute Requirement Templates
        clear_compute_requirement_template_cache()
        counter = 0
        for compute_requirement_template_summary in get_compute_requirement_templates(
            client, self._namespace, partial_name_matches=True
        ):
            if (
                compute_requirement_template_summary.name.startswith(name_prefix)  # type: ignore[union-attr]
                and compute_requirement_template_summary.namespace == self._namespace
            ):
                counter += 1
                try:
                    remove_resource_by_id(compute_requirement_template_summary.id)  # type: ignore[arg-type]
                except Exception as e:
                    print_error(f"Unable to remove Compute Requirement Template: {e}")
        if counter == 0:
            print_warning("No Compute Requirement Templates to remove")

        # Remove Compute Source Templates
        clear_compute_source_template_cache()
        counter = 0
        for compute_source_template_summary in get_compute_source_templates(
            client, self._namespace
        ):
            if (
                compute_source_template_summary.name.startswith(name_prefix)  # type: ignore[union-attr]
                and compute_source_template_summary.namespace == self._namespace
            ):
                counter += 1
                try:
                    remove_resource_by_id(compute_source_template_summary.id)  # type: ignore[arg-type]
                except Exception as e:
                    print_error(f"Unable to remove Compute Source Template: {e}")
        if counter == 0:
            print_warning("No Compute Source Templates to remove")

    def _generate_static_compute_requirement_template(
        self,
        source_names: list[str],
        spot_or_ondemand: str,
        strategy: str,
        instance_type: str,
        name_prefix: str,
    ) -> dict:
        """
        Generate a static compute requirement resource definition
        from a list of source names. Strategy can be one of:
        - SingleSource
        - Split
        - Waterfall
        Instance type must be a valid AWS instance type.
        """
        return {
            "resource": RN_REQUIREMENT_TEMPLATE,
            "name": f"{name_prefix}-{strategy.lower()}-{spot_or_ondemand}",
            "namespace": self._namespace,
            "description": (
                "Compute Requirement Template automatically created by YellowDog"
                " Cloud Wizard"
            ),
            "strategyType": f"co.yellowdog.platform.model.{strategy}ProvisionStrategy",
            "type": "co.yellowdog.platform.model.ComputeRequirementStaticTemplate",
            "sources": [
                {
                    "instanceType": instance_type,
                    "sourceTemplateId": f"{self._namespace}/{name}",
                }
                for name in source_names
            ],
        }

    def _generate_static_compute_requirement_template_spot_ondemand_waterfall(
        self,
        source_names_spot: list[str],
        source_names_on_demand: list[str],
        instance_type: str,
        name_prefix: str,
    ) -> dict:
        """
        Generate a static Waterfall compute requirement resource definition from
        lists of spot and on-demand source names.
        Instance type must be a valid AWS instance type.
        """
        return {
            "resource": RN_REQUIREMENT_TEMPLATE,
            "name": f"{name_prefix}-waterfall-spot-to-ondemand",
            "namespace": self._namespace,
            "description": (
                "Compute Requirement Template automatically created by YellowDog"
                " Cloud Wizard"
            ),
            "strategyType": "co.yellowdog.platform.model.WaterfallProvisionStrategy",
            "type": "co.yellowdog.platform.model.ComputeRequirementStaticTemplate",
            "sources": [
                {
                    "instanceType": instance_type,
                    "sourceTemplateId": f"{self._namespace}/{name}",
                }
                for name in source_names_spot + source_names_on_demand
            ],
        }

    def _generate_dynamic_compute_requirement_template(
        self,
        strategy: str,
        name_prefix: str,
    ) -> dict:
        """
        Generate a dynamic compute requirement resource definition.
        Strategy can be one of:
        - SingleSource
        - Split
        - Waterfall
        """
        return {
            "resource": RN_REQUIREMENT_TEMPLATE,
            "name": f"{name_prefix}-dynamic-{strategy.lower()}-lowestcost",
            "namespace": self._namespace,
            "description": (
                "Compute Requirement Template automatically created by YellowDog Cloud"
                " Wizard"
            ),
            "constraints": [
                {
                    "attribute": "yd.ram",
                    "max": 4096,
                    "min": 4,
                    "type": "co.yellowdog.platform.model.NumericAttributeConstraint",
                },
                {
                    "anyOf": [self._cloud_provider],
                    "attribute": "source.provider",
                    "type": "co.yellowdog.platform.model.StringAttributeConstraint",
                },
            ],
            "preferences": [
                {
                    "attribute": "yd.cost",
                    "rankOrder": "PREFER_LOWER",
                    "type": "co.yellowdog.platform.model.NumericAttributePreference",
                    "weight": 1,
                }
            ],
            "maximumSourceCount": 5,
            "minimumSourceCount": 1,
            "strategyType": f"co.yellowdog.platform.model.{strategy}ProvisionStrategy",
            "type": "co.yellowdog.platform.model.ComputeRequirementDynamicTemplate",
        }

    @staticmethod
    def _generate_yd_keyring(keyring_name: str) -> dict:
        """
        Generate a YellowDog keyring resource definition.
        """
        return {
            "resource": RN_KEYRING,
            "description": "Keyring automatically created by YellowDog Cloud Wizard",
            "name": keyring_name,
        }

    @staticmethod
    def _save_resource_list(resource_list: list[dict], resources_file: str) -> bool:
        """
        Save the list of generated resources. Returns True for success.
        """
        if exists(resources_file):
            if not confirmed(
                f"YellowDog resources definition file '{resources_file}' already"
                " exists; OK to overwrite?"
            ):
                print_info("Not overwriting YellowDog resources definition file")
                return False

        try:
            with open(resources_file, "w") as f:
                json.dump(resource_list, f, indent=2, cls=CompactJSONEncoder)
                f.write("\n")
                print_info(
                    f"Saved YellowDog resource definitions to '{resources_file}'"
                )
                return True
        except Exception as e:
            print_error(
                f"Unable to save YellowDog resources definition file"
                f" '{resources_file}': {e}"
            )
            return False

    def _remove_keyring(self, keyring_name: str):
        """
        Remove a Keyring by its name.
        """
        if confirmed(f"Remove Keyring '{keyring_name}'?"):
            try:
                self._client.keyring_client.delete_keyring_by_name(keyring_name)
                print_info(f"Removed Keyring '{keyring_name}'")
            except Exception as e:
                if "NotFoundException" in str(e):
                    print_warning(f"No Keyring '{keyring_name}' to remove")
                else:
                    print_error(f"Unable to remove Keyring '{keyring_name}': {e}")

    def _create_compute_requirement_templates(self, resource_prefix: str):
        """
        Generate the Compute Requirement Templates
        """
        print_info(
            "Creating example Compute Requirement Templates with instance type"
            f" '{self._instance_type}'"
        )
        clear_compute_source_template_cache()
        self._requirement_template_resources: list[dict] = [
            self._generate_static_compute_requirement_template(
                source_names=self._source_names_ondemand,
                spot_or_ondemand="ondemand",
                strategy="Split",
                instance_type=self._instance_type,  # type: ignore[arg-type]
                name_prefix=resource_prefix,
            ),
            self._generate_static_compute_requirement_template(
                source_names=self._source_names_spot,
                spot_or_ondemand="spot",
                strategy="Split",
                instance_type=self._instance_type,  # type: ignore[arg-type]
                name_prefix=resource_prefix,
            ),
            self._generate_static_compute_requirement_template(
                source_names=self._source_names_ondemand,
                spot_or_ondemand="ondemand",
                strategy="Waterfall",
                instance_type=self._instance_type,  # type: ignore[arg-type]
                name_prefix=resource_prefix,
            ),
            self._generate_static_compute_requirement_template(
                source_names=self._source_names_spot,
                spot_or_ondemand="spot",
                strategy="Waterfall",
                instance_type=self._instance_type,  # type: ignore[arg-type]
                name_prefix=resource_prefix,
            ),
            self._generate_static_compute_requirement_template_spot_ondemand_waterfall(
                source_names_spot=self._source_names_spot,
                source_names_on_demand=self._source_names_ondemand,
                instance_type=self._instance_type,  # type: ignore[arg-type]
                name_prefix=resource_prefix,
            ),
            self._generate_dynamic_compute_requirement_template(
                strategy="Waterfall", name_prefix=resource_prefix
            ),
            self._generate_dynamic_compute_requirement_template(
                strategy="Split", name_prefix=resource_prefix
            ),
        ]

        print_info("Creating YellowDog Compute Requirement Templates")
        create_resources(
            process_variable_substitutions_insitu(  # type: ignore[arg-type]
                deepcopy(self._requirement_template_resources)
            )
        )

    def _create_keyring(self, keyring_name: str):
        """
        Create a YellowDog Keyring
        """
        # Create Keyring and remember the Keyring password
        keyring_resource = self._generate_yd_keyring(keyring_name)
        try:
            keyring_response = self._client.keyring_client.add_keyring(
                keyring_name, keyring_resource["description"]
            )
            keyring = keyring_response.keyring
            self._keyring_password = keyring_response.keyringPassword
            print_info(f"Created YellowDog Keyring '{keyring_name}' ({keyring.id})")  # type: ignore[union-attr]
            self._keyring_name = keyring_name
        except Exception as e:
            if "A keyring already exists" in str(e):
                print_warning(f"Keyring '{keyring_name}' already exists")
            else:
                print_error(f"Unable to create Keyring '{keyring_name}': {e}")

    def _print_keyring_details(self):
        """
        Print the details of the Keyring and Keyring password.
        """
        if self._keyring_password is not None:
            print_info(
                "In the 'Keyrings' section of the YellowDog Portal, please claim your"
                " Keyring using the name and password below. The password will not be"
                " shown again."
            )
            print_info(f"--> Keyring name     = '{self._keyring_name}'")
            print_info(f"--> Keyring password = '{self._keyring_password}'")
