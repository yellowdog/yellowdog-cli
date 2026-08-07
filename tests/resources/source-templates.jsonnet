// Compute sources: a minimal and a maximal variant of each of the nine source
// types the SDK exposes, each wrapped in a ComputeSourceTemplate.
//
// Minimal sets only the properties the SDK dataclass marks required, proving
// nothing optional is secretly required. Maximal sets every other settable
// property, which is what test_resource_property_coverage.py's coverage gate
// measures.
//
// A nested value (existingPlacementGroup, capacityReservation,
// secondaryNetworkInterfaces, instanceOverrides, onDemandOptions, spotOptions)
// gets no 'type' key: checked directly against the installed SDK
// (yellowdog_client.model), none of AwsPlacementGroup / AwsCapacityReservation /
// AwsSecondaryNetworkInterface / AwsFleetInstanceOverride /
// AwsFleetOnDemandOptions / AwsFleetSpotOptions declares a 'type' field or is a
// polymorphic base -- Json.load structures each straight into its concrete
// dataclass from the field's own declared type, with no discriminator to read.
// ComputeSourceTemplate.attributes is different: it holds
// List[AttributeValue[Any]], and AttributeValue *is* a polymorphic, non-dataclass
// base, so each entry needs a real 'type' -- the fully-qualified
// 'co.yellowdog.platform.model.<Class>' string the SDK's own leaf subclasses
// carry, not a bare class name, or Json.load's discriminator lookup misses and
// silently structures the abstract base instead.

local base = import 'lib/base.libsonnet';

// ---------------------------------------------------------------------------
// AWS: on-demand/spot instances
// ---------------------------------------------------------------------------

local awsInstancesMin = {
  type: 'co.yellowdog.platform.model.AwsInstancesComputeSource',
  name: base.name('aws-instances-min'),
  credential: '{{aws_credential}}',
  region: '{{aws_region}}',
  securityGroupId: '{{aws_security_group_id}}',
  instanceType: '{{aws_instance_type}}',
  imageId: '{{aws_image_id}}',
};

local awsInstancesMax = awsInstancesMin {
  name: base.name('aws-instances-max'),
  availabilityZone: '{{aws_availability_zone}}',
  subnetId: '{{aws_subnet_id}}',
  userData: '{{user_data}}',
  instanceTags: { purpose: 'yd-cli-tests' },
  bootVolumeSizeGb: 20,
  iamInstanceProfileArn: '{{aws_iam_instance_profile_arn}}',
  keyName: '{{aws_key_name}}',
  enableDetailedMonitoring: true,
  enableInstanceMetadataTags: true,
  instanceMetadataHttpPutResponseHopLimit: 2,
  useCapacityBlock: false,
  // Live-only finding (Task 8): the platform rejects secondaryNetworkInterfaces
  // together with assignPublicIp = true ("source must not specify
  // secondaryNetworkInterfaces when assignPublicIp = true"), a business rule the
  // offline model-building path this corpus is otherwise checked against never
  // enforces. assignPublicIp is still exercised (with 'true') by every other
  // maximal compute source below that also sets it.
  assignPublicIp: false,
  createClusterPlacementGroup: false,
  // Live-only finding (Task 8): AwsPlacementGroup also only accepts exactly one
  // of groupName/groupId ("source.existingPlacementGroup must specify either
  // groupName or id") -- awsFleetMax below sets the other, so both fields are
  // still covered across the corpus.
  existingPlacementGroup: {
    groupId: '{{aws_placement_group_id}}',
  },
  createElasticFabricAdapter: false,
  secondaryNetworkInterfaces: [
    {
      networkInterfaceType: 'ENI',
      securityGroupId: '{{aws_secondary_security_group_id}}',
      subnetId: '{{aws_secondary_subnet_id}}',
    },
  ],
  capacityReservation: {
    groupArn: '{{aws_capacity_reservation_group_arn}}',
    id: '{{aws_capacity_reservation_id}}',
    preference: 'CAPACITY_RESERVATIONS_ONLY',
  },
  limit: 4,
  specifyMinimum: false,
  spot: true,
  spotMaxPrice: 0.05,
};

// ---------------------------------------------------------------------------
// AWS: fleet (EC2 Fleet, one or more purchase options at once)
// ---------------------------------------------------------------------------

local awsFleetMin = {
  type: 'co.yellowdog.platform.model.AwsFleetComputeSource',
  name: base.name('aws-fleet-min'),
  credential: '{{aws_credential}}',
  region: '{{aws_region}}',
  securityGroupId: '{{aws_security_group_id}}',
  instanceType: '{{aws_instance_type}}',
  imageId: '{{aws_image_id}}',
  purchaseOption: 'SPOT_THEN_ON_DEMAND',
};

local awsFleetMax = awsFleetMin {
  name: base.name('aws-fleet-max'),
  // No 'fleetId': live-only finding (Task 8) -- addComputeSourceTemplate
  // rejects it ("...source.fleetId must be null"), the same server-assigned
  // shape as every other field the SDK declares init=False on this class.
  // Moved to resource_models.SERVER_ASSIGNED_COVERAGE now that it's evidenced.
  availabilityZone: '{{aws_availability_zone}}',
  subnetId: '{{aws_subnet_id}}',
  userData: '{{user_data}}',
  instanceTags: { purpose: 'yd-cli-tests' },
  bootVolumeSizeGb: 20,
  iamInstanceProfileArn: '{{aws_iam_instance_profile_arn}}',
  keyName: '{{aws_key_name}}',
  enableDetailedMonitoring: true,
  enableInstanceMetadataTags: true,
  instanceMetadataHttpPutResponseHopLimit: 2,
  // See awsInstancesMax above: assignPublicIp = true is incompatible with
  // secondaryNetworkInterfaces on the live platform, a rule the offline
  // model-building path never enforces.
  assignPublicIp: false,
  createClusterPlacementGroup: false,
  existingPlacementGroup: { groupName: '{{aws_placement_group}}' },
  createElasticFabricAdapter: false,
  secondaryNetworkInterfaces: [
    {
      networkInterfaceType: 'ENI',
      securityGroupId: '{{aws_secondary_security_group_id}}',
      subnetId: '{{aws_secondary_subnet_id}}',
    },
  ],
  capacityReservation: {
    groupArn: '{{aws_capacity_reservation_group_arn}}',
    id: '{{aws_capacity_reservation_id}}',
    preference: 'CAPACITY_RESERVATIONS_ONLY',
  },
  limit: 4,
  // Live-only finding (Task 8): the platform also rejects maintainCapacity
  // together with a single instance type on either purchase option ("source
  // must not specify maintainCapacity if On-Demand/Spot single instance type
  // is specified") -- another business rule invisible to the offline model
  // build. singleInstanceType is still exercised (with 'true') below.
  maintainCapacity: false,
  instanceOverrides: [
    {
      availabilityZone: '{{aws_availability_zone}}',
      instanceType: '{{aws_instance_type}}',
      spotMaxPrice: 0.06,
      subnetId: '{{aws_subnet_id}}',
    },
  ],
  onDemandOptions: {
    allocationStrategy: 'LOWEST_PRICE',
    maxTotalPrice: 5.0,
    minInstanceCount: 1,
    singleAvailabilityZone: true,
    singleInstanceType: true,
    useCapacityReservationsFirst: true,
  },
  spotOptions: {
    allocationStrategy: 'PRICE_CAPACITY_OPTIMIZED',
    instancePoolsToUseCount: 2,
    // Live-only finding (Task 8): the platform requires maintainCapacity = true
    // when this is set ("source must specify maintainCapacity if Spot launch
    // replacement instance on rebalance is specified"), the mirror image of the
    // maintainCapacity/singleInstanceType conflict noted above -- both cannot be
    // satisfied by the same maintainCapacity value, so this is 'false' instead.
    launchReplacementInstanceOnRebalance: false,
    maxTotalPrice: 5.0,
    minInstanceCount: 1,
    singleAvailabilityZone: true,
    singleInstanceType: true,
  },
};

// ---------------------------------------------------------------------------
// Azure: individual instances
// ---------------------------------------------------------------------------

local azureInstancesMin = {
  type: 'co.yellowdog.platform.model.AzureInstancesComputeSource',
  name: base.name('azure-instances-min'),
  credential: '{{azure_credential}}',
  region: '{{azure_region}}',
  networkResourceGroupName: '{{azure_network_resource_group}}',
  networkName: '{{azure_network_name}}',
  subnetName: '{{azure_subnet_name}}',
  vmSize: '{{azure_vm_size}}',
  imageId: '{{azure_image_id}}',
};

local azureInstancesMax = azureInstancesMin {
  name: base.name('azure-instances-max'),
  availabilityZone: '{{azure_availability_zone}}',
  environment: '{{azure_environment}}',
  userData: '{{user_data}}',
  instanceTags: { purpose: 'yd-cli-tests' },
  adminUserCredential: '{{azure_admin_credential}}',
  sshKey: '{{azure_ssh_key}}',
  assignPublicIp: true,
  createProximityPlacementGroup: false,
  useAcceleratedNetworking: true,
  useSpot: true,
  spotMaxPrice: 0.05,
  limit: 4,
};

// ---------------------------------------------------------------------------
// Azure: scale set
// ---------------------------------------------------------------------------

local azureScaleSetMin = azureInstancesMin {
  type: 'co.yellowdog.platform.model.AzureScaleSetComputeSource',
  name: base.name('azure-scaleset-min'),
};

local azureScaleSetMax = azureInstancesMax {
  type: 'co.yellowdog.platform.model.AzureScaleSetComputeSource',
  name: base.name('azure-scaleset-max'),
};

// ---------------------------------------------------------------------------
// GCE: managed instance group
// ---------------------------------------------------------------------------

local gceInstanceGroupMin = {
  type: 'co.yellowdog.platform.model.GceInstanceGroupComputeSource',
  name: base.name('gce-instance-group-min'),
  credential: '{{gcp_credential}}',
  project: '{{gcp_project}}',
  region: '{{gcp_region}}',
  machineType: '{{gcp_machine_type}}',
  image: '{{gcp_image}}',
};

local gceInstanceGroupMax = gceInstanceGroupMin {
  name: base.name('gce-instance-group-max'),
  limit: 4,
  assignPublicIp: true,
  userData: '{{user_data}}',
  instanceTags: { purpose: 'yd-cli-tests' },
  sshKeys: '{{gcp_ssh_keys}}',
  zone: '{{gcp_zone}}',
  network: '{{gcp_network}}',
  subnetwork: '{{gcp_subnetwork}}',
  preemptible: false,
  spot: true,
  confidential: false,
  acceleratorType: '{{gcp_accelerator_type}}',
  acceleratorCount: 1,
  hostMaintenanceBehaviour: 'MIGRATE',
  targetDistributionShape: 'BALANCED',
};

// ---------------------------------------------------------------------------
// GCE: individual instances
// ---------------------------------------------------------------------------

local gceInstancesMin = {
  type: 'co.yellowdog.platform.model.GceInstancesComputeSource',
  name: base.name('gce-instances-min'),
  credential: '{{gcp_credential}}',
  project: '{{gcp_project}}',
  region: '{{gcp_region}}',
  machineType: '{{gcp_machine_type}}',
  image: '{{gcp_image}}',
};

local gceInstancesMax = gceInstancesMin {
  name: base.name('gce-instances-max'),
  limit: 4,
  assignPublicIp: true,
  specifyMinimum: false,
  createCompactPlacementPolicy: false,
  userData: '{{user_data}}',
  instanceTags: { purpose: 'yd-cli-tests' },
  sshKeys: '{{gcp_ssh_keys}}',
  zone: '{{gcp_zone}}',
  network: '{{gcp_network}}',
  subnetwork: '{{gcp_subnetwork}}',
  preemptible: false,
  spot: true,
  confidential: false,
  acceleratorType: '{{gcp_accelerator_type}}',
  acceleratorCount: 1,
  hostMaintenanceBehaviour: 'MIGRATE',
};

// ---------------------------------------------------------------------------
// OCI: instance pool
// ---------------------------------------------------------------------------

local ociInstancePoolMin = {
  type: 'co.yellowdog.platform.model.OciInstancePoolComputeSource',
  name: base.name('oci-instance-pool-min'),
  credential: '{{oci_credential}}',
  region: '{{oci_region}}',
  compartmentId: '{{oci_compartment_id}}',
  imageId: '{{oci_image_id}}',
  shape: '{{oci_shape}}',
  subnetId: '{{oci_subnet_id}}',
};

local ociInstancePoolMax = ociInstancePoolMin {
  name: base.name('oci-instance-pool-max'),
  sshKey: '{{oci_ssh_key}}',
  availabilityDomain: '{{oci_availability_domain}}',
  flexOcpus: 2.0,
  flexRam: 16.0,
  limit: 4,
  assignPublicIp: true,
  createClusterNetwork: false,
  userData: '{{user_data}}',
  instanceTags: { purpose: 'yd-cli-tests' },
};

// ---------------------------------------------------------------------------
// OCI: individual instances
// ---------------------------------------------------------------------------

local ociInstancesMin = {
  type: 'co.yellowdog.platform.model.OciInstancesComputeSource',
  name: base.name('oci-instances-min'),
  credential: '{{oci_credential}}',
  region: '{{oci_region}}',
  compartmentId: '{{oci_compartment_id}}',
  imageId: '{{oci_image_id}}',
  shape: '{{oci_shape}}',
  subnetId: '{{oci_subnet_id}}',
};

local ociInstancesMax = ociInstancesMin {
  name: base.name('oci-instances-max'),
  sshKey: '{{oci_ssh_key}}',
  availabilityDomain: '{{oci_availability_domain}}',
  flexOcpus: 2.0,
  flexRam: 16.0,
  preemptible: false,
  limit: 4,
  assignPublicIp: true,
  userData: '{{user_data}}',
  instanceTags: { purpose: 'yd-cli-tests' },
};

// ---------------------------------------------------------------------------
// Simulator: no real cloud account, so nothing here is environment-specific
// ---------------------------------------------------------------------------

local simulatorMin = {
  type: 'co.yellowdog.platform.model.SimulatorComputeSource',
  name: base.name('simulator-min'),
};

local simulatorMax = simulatorMin {
  name: base.name('simulator-max'),
  credential: '{{aws_credential}}',
  region: 'simulated-region',
  // 'subregion'/'userData' are kept here, not dropped: both build cleanly
  // offline (resource_models.settable_properties() still demands them -- see
  // its own comment on why they are NOT in SERVER_ASSIGNED_COVERAGE despite
  // being declared init=False on this class), and the live layer's own
  // silent-drop finding belongs in resource_live.
  // LIVE_ONLY_EXCLUSIONS_BY_CLASS -- the *class-scoped* dict, keyed
  // 'SimulatorComputeSource' -> 'userData' -- not in the flat, name-keyed
  // LIVE_ONLY_EXCLUSIONS beside it. 'userData' is a real, correctly-echoed
  // field on the other eight compute source classes, so a name-keyed entry
  // would switch the live check off for all nine at once and hide a genuine
  // regression on, say, AwsInstancesComputeSource.userData: that is the exact
  // defect the class-scoped dict was added to fix. Either way, the corpus goes
  // on exercising the property rather than stopping just because the platform
  // currently mishandles it.
  subregion: 'simulated-subregion',
  instanceType: 'simulated-instance-type',
  imageId: 'simulated-image',
  instanceTags: { purpose: 'yd-cli-tests' },
  userData: '{{user_data}}',
  implicitCapacity: 10,
  instanceStartupTimeSeconds: 5,
  instanceStartupTimeVariance: 1.0,
  instanceShutdownTimeSeconds: 5,
  instanceShutdownTimeVariance: 1.0,
  unexpectedInstanceTerminationProbability: 0.0,
  failOnRequestAllInstances: false,
  failOnProvision: false,
  reportSupportingResourcesExist: true,
  limit: 4,
};

// ---------------------------------------------------------------------------
// Assemble: each entry is [source, description, extra wrapper-level fields].
// The wrapper-level 'attributes' property belongs to ComputeSourceTemplate, not
// to any source, so it only needs setting once -- attached here to the AWS
// instances maximal entry rather than repeated across all nine pairs.
// ---------------------------------------------------------------------------

local sources = [
  [awsInstancesMin, 'minimal AwsInstancesComputeSource'],
  [awsInstancesMax, 'maximal AwsInstancesComputeSource', {
    attributes: [
      {
        type: 'co.yellowdog.platform.model.StringAttributeValue',
        attribute: 'yd-cli-tests-tag',
        value: 'yd-cli-tests',
      },
      {
        type: 'co.yellowdog.platform.model.NumericAttributeValue',
        attribute: 'yd-cli-tests-priority',
        value: 1,
      },
    ],
  }],
  [awsFleetMin, 'minimal AwsFleetComputeSource'],
  [awsFleetMax, 'maximal AwsFleetComputeSource'],
  [azureInstancesMin, 'minimal AzureInstancesComputeSource'],
  [azureInstancesMax, 'maximal AzureInstancesComputeSource'],
  [azureScaleSetMin, 'minimal AzureScaleSetComputeSource'],
  [azureScaleSetMax, 'maximal AzureScaleSetComputeSource'],
  [gceInstanceGroupMin, 'minimal GceInstanceGroupComputeSource'],
  [gceInstanceGroupMax, 'maximal GceInstanceGroupComputeSource'],
  [gceInstancesMin, 'minimal GceInstancesComputeSource'],
  [gceInstancesMax, 'maximal GceInstancesComputeSource'],
  [ociInstancePoolMin, 'minimal OciInstancePoolComputeSource'],
  [ociInstancePoolMax, 'maximal OciInstancePoolComputeSource'],
  [ociInstancesMin, 'minimal OciInstancesComputeSource'],
  [ociInstancesMax, 'maximal OciInstancesComputeSource'],
  [simulatorMin, 'minimal SimulatorComputeSource'],
  [simulatorMax, 'maximal SimulatorComputeSource'],
];

[
  base.sourceTemplate(entry[0], entry[1])
  + (if std.length(entry) > 2 then entry[2] else {})
  for entry in sources
]
