// AWS for a run: its Credential in the run's Keyring, an on-demand Compute
// Source Template, and a static Compute Requirement Template over it.
[
  {
    resource: 'Credential',
    keyringName: '{{keyring}}',
    credential: {
      type: 'co.yellowdog.platform.account.credentials.AwsCredential',
      name: '{{aws_credential_name}}',
      accessKeyId: '{{secret_aws_access_key_id}}',
      secretAccessKey: '{{secret_aws_secret_access_key}}',
    },
  },
  {
    resource: 'ComputeSourceTemplate',
    namespace: '{{namespace}}',
    description: 'Live system tests, run {{run_id}}: AWS on-demand',
    source: {
      type: 'co.yellowdog.platform.model.AwsInstancesComputeSource',
      name: '{{aws_source_template}}',
      credential: '{{aws_credential}}',
      region: '{{aws_region}}',
      securityGroupId: '{{aws_security_group_id}}',
      subnetId: '{{aws_subnet_id}}',
      availabilityZone: '{{aws_availability_zone}}',
      instanceType: '{{aws_instance_type}}',
      imageId: '{{aws_image_id}}',
      iamInstanceProfileArn: '{{aws_iam_instance_profile_arn::}}',
      assignPublicIp: true,
    },
  },
  {
    resource: 'ComputeRequirementTemplate',
    type: 'co.yellowdog.platform.model.ComputeRequirementStaticTemplate',
    namespace: '{{namespace}}',
    name: '{{aws_requirement_template}}',
    description: 'Live system tests, run {{run_id}}: AWS static',
    strategyType: 'co.yellowdog.platform.model.WaterfallProvisionStrategy',
    sources: [{ sourceTemplateId: '{{namespace}}/{{aws_source_template}}' }],
  },
]
