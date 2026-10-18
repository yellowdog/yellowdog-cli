// Users. The CLI cannot create or remove a User, only update an existing
// one's Group memberships (update_user(), resource_creation.py), so no
// account can be relied on to hold the Users named here: this file is in
// resource_corpus.OFFLINE_ONLY, checked by the loader, the schema and the
// dry run, and never sent to the Platform.
//
// A User is named by any of 'name', 'username' (an InternalUser's only) and
// 'id'. Without 'groups' its memberships are left as they are; with
// 'groups' they are made to match it, so '[]' removes them all.

local base = import 'lib/base.libsonnet';

[
  {
    resource: 'InternalUser',
    name: base.name('internal-user-min'),
  },
  {
    resource: 'InternalUser',
    name: base.name('internal-user-max'),
    username: base.name('internal-user-max'),
    id: 'ydid:user:000000:00000000-0000-0000-0000-000000000001',
    groups: [base.name('group-max'), base.name('group-min')],
  },
  {
    resource: 'ExternalUser',
    name: base.name('external-user-min'),
  },
  {
    resource: 'ExternalUser',
    id: 'ydid:user:000000:00000000-0000-0000-0000-000000000002',
    groups: [],
  },
]
