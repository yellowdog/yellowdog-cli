// The smoke Work Requirement for one provider ('--variable
// provider=<provider>'): one bash Task (the installed Agent's only task
// type) on that provider's Workers.
{
  name: '{{run_id}}-{{provider}}-smoke',
  taskType: 'bash',
  workerTags: ['{{run_id}}-{{provider}}'],
  taskGroups: [
    {
      name: 'smoke',
      tasks: [
        {
          name: 'smoke',
          arguments: ['-c', 'echo "ydst smoke {{run_id}} {{provider}} on $(hostname)"; uname -a'],
        },
      ],
    },
  ],
}
