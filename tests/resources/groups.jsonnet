// Groups. Builds no model at all (see resource_models.MODEL_FOR_RESOURCE --
// create_group() constructs AddGroupRequest/UpdateGroupRequest directly and
// handles 'roles' separately via account_client role calls, never through
// _get_model_object), so it contributes nothing to the coverage gate.
// Written anyway for the live layer (Tasks 7-8), which needs a specification
// to create/update against.
//
// The 'roles' shape mirrors the README's own example: a global role plus a
// role scoped to this run's namespace. 'work-viewer'/'work-manager' are
// built-in platform roles, not created by this corpus.

local base = import 'lib/base.libsonnet';

[
  {
    resource: 'Group',
    name: base.name('group-min'),
    description: 'minimal',
  },
  {
    resource: 'Group',
    name: base.name('group-max'),
    description: 'maximal: every settable property of a Group',
    roles: [
      {
        role: { name: 'work-viewer' },
        scope: { global: true },
      },
      {
        role: { name: 'work-manager' },
        scope: {
          global: false,
          namespaces: [
            { namespace: base.namespace },
          ],
        },
      },
    ],
  },
]
