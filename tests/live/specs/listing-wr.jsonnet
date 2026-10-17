// A Work Requirement that stays pending, for the listing tests: six Tasks in
// two Task Groups, for Workers nothing has, named so that a '--name' glob
// keeps some of them ('row-*') and the Platform's substring match ('row-')
// finds more ('xrow-1').
{
  name: '{{run_id}}-listing',
  taskType: 'bash',
  workerTags: ['{{run_id}}-nobody'],
  taskGroups: [
    {
      name: 'first',
      tasks: [
        { name: 'row-1', arguments: ['-c', 'true'] },
        { name: 'xrow-1', arguments: ['-c', 'true'] },
        { name: 'row-2', arguments: ['-c', 'true'] },
      ],
    },
    {
      name: 'second',
      tasks: [
        { name: 'row-3', arguments: ['-c', 'true'] },
        { name: 'other-1', arguments: ['-c', 'true'] },
        { name: 'other-2', arguments: ['-c', 'true'] },
      ],
    },
  ],
}
