// Azure for a run: its Credential in the run's Keyring, an on-demand Compute
// Source Template, and a static Compute Requirement Template over it.
[
  {
    resource: 'Credential',
    keyringName: '{{keyring}}',
    credential: {
      type: 'co.yellowdog.platform.account.credentials.AzureClientCredential',
      name: '{{azure_credential_name}}',
      clientId: '{{azure_client_id}}',
      tenantId: '{{azure_tenant_id}}',
      subscriptionId: '{{azure_subscription_id}}',
      key: '{{secret_azure_client_secret}}',
    },
  },
  {
    resource: 'ComputeSourceTemplate',
    namespace: '{{namespace}}',
    description: 'Live system tests, run {{run_id}}: Azure on-demand',
    source: {
      type: 'co.yellowdog.platform.model.AzureInstancesComputeSource',
      name: '{{azure_source_template}}',
      credential: '{{azure_credential}}',
      region: '{{azure_region}}',
      networkResourceGroupName: '{{azure_network_resource_group}}',
      networkName: '{{azure_network_name}}',
      subnetName: '{{azure_subnet_name}}',
      vmSize: '{{azure_vm_size}}',
      imageId: '{{azure_image_id}}',
      sshKey: '{{azure_ssh_public_key::}}',
      assignPublicIp: true,
    },
  },
  {
    resource: 'ComputeRequirementTemplate',
    type: 'co.yellowdog.platform.model.ComputeRequirementStaticTemplate',
    namespace: '{{namespace}}',
    name: '{{azure_requirement_template}}',
    description: 'Live system tests, run {{run_id}}: Azure static',
    strategyType: 'co.yellowdog.platform.model.WaterfallProvisionStrategy',
    sources: [{ sourceTemplateId: '{{namespace}}/{{azure_source_template}}' }],
  },
]
