// Credentials: a minimal and maximal variant of all seven credential
// subtypes, with dummy key material. Offline only -- the live layer
// (Tasks 7-8) skips this file (see resource_corpus.OFFLINE_ONLY), since real
// provider secrets are out of scope for these tests. 'keyringName' names the
// Keyring to add the credential to and belongs to no model at all (see
// resource_models.build_models()'s Credential branch): it is passed straight
// to put_credential_by_name(), so a dummy Keyring name is fine here even
// though no such Keyring is ever created.
//
// 'expiryTime' is declared 'init=False' on four of the seven subtypes
// (AwsAccountRoleCredential, AzureStorageCredential, GoogleCloudCredential,
// OciCredential) -- checked directly against the installed SDK -- but it is
// still a genuinely settable property from a specification's point of view
// (the SDK structures every field, init=False or not; see
// resource_models.settable_properties()'s docstring) and is not recorded in
// SERVER_ASSIGNED_COVERAGE for any of the four, so the gap list demands it
// regardless. An ISO-8601 datetime string round-trips through Json.load/
// Json.dump cleanly (checked directly), so that is what the maximal variant
// of each of those four uses.

local base = import 'lib/base.libsonnet';

local keyringName = base.name('credentials-keyring');

local credential(type, name, extra) = {
  resource: 'Credential',
  keyringName: keyringName,
  credential: { type: 'co.yellowdog.platform.account.credentials.' + type, name: name } + extra,
};

[
  credential('AwsCredential', base.name('aws-credential-min'), {
    accessKeyId: 'AKIADUMMYDUMMYDUMMY',
    secretAccessKey: 'dummyDummyDummyDummyDummyDummyDummyDummy',
  }),
  credential('AwsCredential', base.name('aws-credential-max'), {
    accessKeyId: 'AKIADUMMYDUMMYDUMMY',
    secretAccessKey: 'dummyDummyDummyDummyDummyDummyDummyDummy',
    description: 'maximal: every settable property of an AwsCredential',
    sessionToken: 'dummy-session-token',
    expiryTime: '2030-01-01T00:00:00.000Z',
  }),

  credential('AwsAccountRoleCredential', base.name('aws-role-credential-min'), {
    externalRoleArn: 'arn:aws:iam::000000000000:role/yd-dummy',
    externalId: 'yd-dummy-external-id',
  }),
  credential('AwsAccountRoleCredential', base.name('aws-role-credential-max'), {
    externalRoleArn: 'arn:aws:iam::000000000000:role/yd-dummy',
    externalId: 'yd-dummy-external-id',
    description: 'maximal: every settable property of an AwsAccountRoleCredential',
    expiryTime: '2030-01-01T00:00:00.000Z',
  }),

  credential('AzureClientCredential', base.name('azure-client-credential-min'), {
    clientId: '00000000-0000-0000-0000-000000000001',
    tenantId: '00000000-0000-0000-0000-000000000002',
    subscriptionId: '00000000-0000-0000-0000-000000000003',
    key: 'dummy-client-key',
  }),
  credential('AzureClientCredential', base.name('azure-client-credential-max'), {
    clientId: '00000000-0000-0000-0000-000000000001',
    tenantId: '00000000-0000-0000-0000-000000000002',
    subscriptionId: '00000000-0000-0000-0000-000000000003',
    key: 'dummy-client-key',
    description: 'maximal: every settable property of an AzureClientCredential',
  }),

  credential('AzureInstanceCredential', base.name('azure-instance-credential-min'), {
    adminUsername: 'yd-dummy-admin',
  }),
  credential('AzureInstanceCredential', base.name('azure-instance-credential-max'), {
    adminUsername: 'yd-dummy-admin',
    description: 'maximal: every settable property of an AzureInstanceCredential',
    adminPassword: 'dummy-admin-password',
  }),

  credential('AzureStorageCredential', base.name('azure-storage-credential-min'), {
    accountName: 'yddummystorage',
    accountKey: 'dummy-account-key',
  }),
  credential('AzureStorageCredential', base.name('azure-storage-credential-max'), {
    accountName: 'yddummystorage',
    accountKey: 'dummy-account-key',
    description: 'maximal: every settable property of an AzureStorageCredential',
    expiryTime: '2030-01-01T00:00:00.000Z',
  }),

  credential('GoogleCloudCredential', base.name('gcp-credential-min'), {
    serviceAccountKeyJson: '{"type": "service_account", "project_id": "yd-dummy"}',
  }),
  credential('GoogleCloudCredential', base.name('gcp-credential-max'), {
    serviceAccountKeyJson: '{"type": "service_account", "project_id": "yd-dummy"}',
    description: 'maximal: every settable property of a GoogleCloudCredential',
    expiryTime: '2030-01-01T00:00:00.000Z',
  }),

  credential('OciCredential', base.name('oci-credential-min'), {
    userId: 'ocid1.user.oc1..dummy',
    tenantId: 'ocid1.tenancy.oc1..dummy',
    fingerprint: '00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00',
    privateKey: '-----BEGIN PRIVATE KEY-----\ndummy\n-----END PRIVATE KEY-----',
  }),
  credential('OciCredential', base.name('oci-credential-max'), {
    userId: 'ocid1.user.oc1..dummy',
    tenantId: 'ocid1.tenancy.oc1..dummy',
    fingerprint: '00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00',
    privateKey: '-----BEGIN PRIVATE KEY-----\ndummy\n-----END PRIVATE KEY-----',
    description: 'maximal: every settable property of an OciCredential',
    passphrase: 'dummy-passphrase',
    expiryTime: '2030-01-01T00:00:00.000Z',
  }),
]
