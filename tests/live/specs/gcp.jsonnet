// GCP for a run: its Credential in the run's Keyring, an on-demand Compute
// Source Template naming the run's Image Family for it, which holds the
// configured image, and a static Compute Requirement Template over it.
local imageFamily = import 'image-family.libsonnet';

[
  imageFamily('{{gcp_image_family}}', 'GOOGLE', '{{gcp_image}}', '{{gcp_region}}'),
  {
    resource: 'Credential',
    keyringName: '{{keyring}}',
    credential: {
      type: 'co.yellowdog.platform.account.credentials.GoogleCloudCredential',
      name: '{{gcp_credential_name}}',
      // The key, escaped for this string by the Jsonnet pass
      serviceAccountKeyJson: '{{secret_gcp_service_account_key_json}}',
    },
  },
  {
    resource: 'ComputeSourceTemplate',
    namespace: '{{namespace}}',
    description: 'Live system tests, run {{run_id}}: GCP on-demand',
    source: {
      type: 'co.yellowdog.platform.model.GceInstancesComputeSource',
      name: '{{gcp_source_template}}',
      credential: '{{gcp_credential}}',
      project: '{{gcp_project}}',
      region: '{{gcp_region}}',
      zone: '{{gcp_zone::}}',
      network: '{{gcp_network::}}',
      subnetwork: '{{gcp_subnetwork::}}',
      machineType: '{{gcp_machine_type}}',
      image: '{{namespace}}/{{gcp_image_family}}',
      assignPublicIp: true,
    },
  },
  {
    resource: 'ComputeRequirementTemplate',
    type: 'co.yellowdog.platform.model.ComputeRequirementStaticTemplate',
    namespace: '{{namespace}}',
    name: '{{gcp_requirement_template}}',
    description: 'Live system tests, run {{run_id}}: GCP static',
    strategyType: 'co.yellowdog.platform.model.WaterfallProvisionStrategy',
    sources: [{ sourceTemplateId: '{{namespace}}/{{gcp_source_template}}' }],
  },
]
