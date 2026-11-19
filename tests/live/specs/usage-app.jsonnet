// The usage scope test's Application ('--variable
// limited_namespace=<namespace>'): a Group with 'compute-viewer', which
// carries COMPUTE_USAGE_READ, in the run's namespace alone, and
// 'work-viewer' in the limited namespace, which it can therefore read but
// not read usage in; no global role. The namespace is created when missing
// and never populated or removed. Both descriptions name the run's
// namespace, which is how the sweep tells a run of its namespace's from
// another's.
[
  { resource: 'Namespace', name: '{{limited_namespace}}' },
  {
    resource: 'Group',
    name: '{{run_id}}-usage-group',
    description: 'Live system tests, run {{run_id}}, namespace {{namespace}}',
    roles: [
      {
        role: { name: 'compute-viewer' },
        scope: { global: false, namespaces: [{ namespace: '{{namespace}}' }] },
      },
      {
        role: { name: 'work-viewer' },
        scope: { global: false, namespaces: [{ namespace: '{{limited_namespace}}' }] },
      },
    ],
  },
  {
    resource: 'Application',
    name: '{{run_id}}-usage-app',
    description: 'Live system tests, run {{run_id}}, namespace {{namespace}}',
    groups: ['{{run_id}}-usage-group'],
  },
]
