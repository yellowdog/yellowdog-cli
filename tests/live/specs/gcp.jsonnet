// GCP for a run: its Credential in the run's Keyring, an on-demand Compute
// Source Template, and a static Compute Requirement Template over it.
[
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
      image: '{{gcp_image}}',
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
