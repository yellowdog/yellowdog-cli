"""
Utility class for YellowDog item types. Type-only: the SDK is imported for
type checking alone, since importing it at all builds the whole Platform
client.
"""

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from yellowdog_client.model import (
        Allowance,
        Application,
        ComputeRequirement,
        ComputeRequirementSummary,
        ComputeRequirementTemplateSummary,
        ComputeSourceTemplate,
        ComputeSourceTemplateSummary,
        ConfiguredWorkerPool,
        Group,
        Instance,
        KeyringSummary,
        MachineImageFamilySummary,
        Namespace,
        NamespacePolicy,
        Node,
        PermissionDetail,
        ProvisionedWorkerPool,
        Role,
        Task,
        TaskGroup,
        User,
        Worker,
        WorkerPoolSummary,
        WorkRequirementSummary,
    )

    from yellowdog_cli.utils.cloudwizard_aws_types import AWSAvailabilityZone

    Item = TypeVar(
        "Item",
        AWSAvailabilityZone,
        Allowance,
        Application,
        ComputeRequirement,
        ComputeRequirementSummary,
        ComputeRequirementTemplateSummary,
        ComputeSourceTemplate,
        ComputeSourceTemplateSummary,
        ConfiguredWorkerPool,
        Group,
        Instance,
        KeyringSummary,
        MachineImageFamilySummary,
        Namespace,
        NamespacePolicy,
        Node,
        PermissionDetail,
        ProvisionedWorkerPool,
        Role,
        Task,
        TaskGroup,
        User,
        WorkRequirementSummary,
        Worker,
        WorkerPoolSummary,
    )
