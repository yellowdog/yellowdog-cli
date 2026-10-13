// OCI for a run: its Credential in the run's Keyring, an on-demand Compute
// Source Template, and a static Compute Requirement Template over it.
[
  {
    resource: 'Credential',
    keyringName: '{{keyring}}',
    credential: {
      type: 'co.yellowdog.platform.account.credentials.OciCredential',
      name: '{{oci_credential_name}}',
      userId: '{{oci_user_id}}',
      tenantId: '{{oci_tenancy_id}}',
      fingerprint: '{{oci_fingerprint}}',
      // The key file's contents, escaped for this string by the Jsonnet pass
      privateKey: '{{secret_oci_private_key}}',
    },
  },
  {
    resource: 'ComputeSourceTemplate',
    namespace: '{{namespace}}',
    description: 'Live system tests, run {{run_id}}: OCI on-demand',
    source: {
      type: 'co.yellowdog.platform.model.OciInstancesComputeSource',
      name: '{{oci_source_template}}',
      credential: '{{oci_credential}}',
      region: '{{oci_region}}',
      compartmentId: '{{oci_compartment_id}}',
      availabilityDomain: '{{oci_availability_domain::}}',
      subnetId: '{{oci_subnet_id}}',
      shape: '{{oci_shape}}',
      flexOcpus: '{{num:oci_flex_ocpus}}',
      flexRam: '{{num:oci_flex_ram}}',
      imageId: '{{oci_image_id}}',
      assignPublicIp: true,
    },
  },
  {
    resource: 'ComputeRequirementTemplate',
    type: 'co.yellowdog.platform.model.ComputeRequirementStaticTemplate',
    namespace: '{{namespace}}',
    name: '{{oci_requirement_template}}',
    description: 'Live system tests, run {{run_id}}: OCI static',
    strategyType: 'co.yellowdog.platform.model.WaterfallProvisionStrategy',
    sources: [{ sourceTemplateId: '{{namespace}}/{{oci_source_template}}' }],
  },
]
