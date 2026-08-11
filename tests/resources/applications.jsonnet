// Applications. Emit secrets when created (the Application Key ID/Secret are
// printed at creation time, per create_application()/create.py) -- nothing
// for this offline corpus to act on, but worth remembering for the live
// layer (Tasks 7-8), which must not print or persist them carelessly.
//
// 'groups' and 'keyrings' belong to no model: create_application() pops both
// before building AddApplicationRequest, which has only 'name'/'description'
// fields, because each drives a separate API call rather than being a field
// of the request itself -- 'groups' resolves group names to IDs to add the
// Application to those groups, and 'keyrings' grants the Application access
// to the named Keyrings. resource_models.build_models() now has an
// 'Application' branch that pops both the same way its 'Credential' branch
// pops keyringName, so setting them here no longer trips
// test_no_property_is_dropped_when_building_a_model's unexpected-property
// check. Neither appears in AddApplicationRequest's settable properties, so
// neither closes anything in the coverage gate -- but setting them still
// exercises the CLI's own group/keyring-grant handling, which is why the
// maximal variant does.
//
// The group and keyring named below are real, not dangling: 'group-max' is
// created by groups.jsonnet, and 'keyring-max' by keyrings.jsonnet -- both
// named via the same base.name()/run_id construction, so the strings match
// without either file importing the other. This file is not in
// resource_corpus.OFFLINE_ONLY, so the live layer (Tasks 7-8) creates it
// too: a real create needs the referenced Group and Keyring to already
// exist, so groups.jsonnet and keyrings.jsonnet must run first -- within a
// single yd-create invocation covering all three files,
// load_resources.py's resource_creation_order already sequences Keyring
// before Group before Application, so this only needs calling out if the
// live layer creates each corpus file as a separate invocation instead.

local base = import 'lib/base.libsonnet';

[
  {
    resource: 'Application',
    name: base.name('application-min'),
  },
  {
    resource: 'Application',
    name: base.name('application-max'),
    description: 'maximal: every settable property of an AddApplicationRequest',
    groups: [base.name('group-max')],
    keyrings: [base.name('keyring-max')],
  },
]
