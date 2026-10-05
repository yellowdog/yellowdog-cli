"""
The YellowDog item types the CLI lists and prints, as one union. Type-only:
the SDK is imported for type checking alone, since importing it at all
builds the whole Platform client.

A union, not a TypeVar: it annotates "any one of these" (a list of mixed
summaries, an object whose type is to be named), not one type held the same
throughout a generic function.
"""

from typing import TYPE_CHECKING, TypeAlias

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

    Item: TypeAlias = (
        AWSAvailabilityZone
        | Allowance
        | Application
        | ComputeRequirement
        | ComputeRequirementSummary
        | ComputeRequirementTemplateSummary
        | ComputeSourceTemplate
        | ComputeSourceTemplateSummary
        | ConfiguredWorkerPool
        | Group
        | Instance
        | KeyringSummary
        | MachineImageFamilySummary
        | Namespace
        | NamespacePolicy
        | Node
        | PermissionDetail
        | ProvisionedWorkerPool
        | Role
        | Task
        | TaskGroup
        | User
        | WorkRequirementSummary
        | Worker
        | WorkerPoolSummary
    )
