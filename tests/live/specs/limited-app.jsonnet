// The failure tests' limited Application ('--variable
// limited_namespace=<namespace>'): a Group with 'work-viewer' in that
// namespace alone and no global role, and an Application in the Group. The
// namespace is created when missing and never populated or removed. Both
// descriptions name the run's namespace, which is how the sweep tells a run
// of its namespace's from another's, as for a Keyring.
[
  { resource: 'Namespace', name: '{{limited_namespace}}' },
  {
    resource: 'Group',
    name: '{{run_id}}-limited-group',
    description: 'Live system tests, run {{run_id}}, namespace {{namespace}}',
    roles: [
      {
        role: { name: 'work-viewer' },
        scope: { global: false, namespaces: [{ namespace: '{{limited_namespace}}' }] },
      },
    ],
  },
  {
    resource: 'Application',
    name: '{{run_id}}-limited-app',
    description: 'Live system tests, run {{run_id}}, namespace {{namespace}}',
    groups: ['{{run_id}}-limited-group'],
  },
]
