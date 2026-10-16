// Applications. Emit secrets when created (the Application Key ID/Secret are
// printed at creation time, per create_application()/create.py) -- nothing
// for this offline corpus to act on, but worth remembering for the live
// layer, which must not print or persist them carelessly.
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
// The Group and Keyring application-max is granted are created in this
// file, before it ('yd resource create' sequences Keyring and Group before
// Application whatever the order here), so the live layer, which creates
// each corpus file on its own, creates the Application with both grants
// made: its Group membership and its access to the Keyring.
//
// The live layer then updates both Applications (resource_live.UPDATES):
// application-min gains a description and application-max's is cleared to
// ''. Removing a description by leaving it out is YEL-15305, held by
// test_system_resources.py's test_an_application_description_left_out_is_removed.

local base = import 'lib/base.libsonnet';

[
  {
    resource: 'Group',
    name: base.name('application-group'),
    description: 'the Group application-max is a member of',
  },
  {
    resource: 'Keyring',
    name: base.name('application-keyring'),
    description: 'the Keyring application-max is granted access to',
  },
  {
    resource: 'Application',
    name: base.name('application-min'),
  },
  {
    resource: 'Application',
    name: base.name('application-max'),
    description: 'maximal: every settable property of an AddApplicationRequest',
    groups: [base.name('application-group')],
    keyrings: [base.name('application-keyring')],
  },
]
