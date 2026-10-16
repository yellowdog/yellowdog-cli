// A Work Requirement that stays pending until it is acted on: one Task for
// Workers nothing has. The failure tests' is '<run>-stuck'; another takes a
// name of its own with '--variable wr=<name>'.
{
  name: '{{run_id}}-{{wr:=stuck}}',
  taskType: 'bash',
  workerTags: ['{{run_id}}-nobody'],
  taskGroups: [{ name: 'stuck', tasks: [{ name: 'stuck', arguments: ['-c', 'true'] }] }],
}
