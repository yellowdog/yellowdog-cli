// The Task Group 'yd wr submit --add-to' adds: two short bash Tasks.
// Variables: 'worker_tag', 'seconds'.
{
  taskType: 'bash',
  workerTags: ['{{worker_tag}}'],
  taskGroups: [
    {
      name: 'third',
      tasks: [
        { name: 'third-1', arguments: ['-c', 'sleep {{seconds}}'] },
        { name: 'third-2', arguments: ['-c', 'sleep {{seconds}}'] },
      ],
    },
  ],
}
