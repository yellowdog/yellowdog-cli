// The failure tests' Work Requirement: one Task for Workers nothing has, so
// it stays pending until it is cancelled.
{
  name: '{{run_id}}-stuck',
  taskType: 'bash',
  workerTags: ['{{run_id}}-nobody'],
  taskGroups: [{ name: 'stuck', tasks: [{ name: 'stuck', arguments: ['-c', 'true'] }] }],
}
