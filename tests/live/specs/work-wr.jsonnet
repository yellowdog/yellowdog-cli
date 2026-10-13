// Work for the actions pool: two Task Groups of two bash Tasks, each
// sleeping 'seconds' and exiting 'exit_code'. Variables: 'wr' (the name's
// suffix), 'worker_tag', 'seconds', 'exit_code' (default 0).
local task(name) = {
  name: name,
  arguments: ['-c', 'sleep {{seconds}}; exit {{exit_code:=0}}'],
};
{
  name: '{{run_id}}-{{wr}}',
  taskType: 'bash',
  workerTags: ['{{worker_tag}}'],
  taskGroups: [
    { name: 'first', tasks: [task('first-1'), task('first-2')] },
    { name: 'second', tasks: [task('second-1'), task('second-2')] },
  ],
}
