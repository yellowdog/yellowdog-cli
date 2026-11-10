// Work for resubmitting: two Task Groups of bash Tasks, each Task with an
// environment of its own, some exiting 0 and some 3 (failing). Variables:
// 'wr' (the name's suffix), 'worker_tag'.
local task(name, code) = {
  name: name,
  arguments: ['-c', 'echo "$WHO"; exit ' + code],
  environment: { WHO: name },
  timeout: 30,
  taskData: 'data-' + name,
};
{
  name: '{{run_id}}-{{wr}}',
  taskType: 'bash',
  workerTags: ['{{worker_tag}}'],
  taskGroups: [
    {
      name: 'first',
      tasks: [task('ok-1', 0), task('bad-1', 3), task('bad-2', 3)],
    },
    {
      name: 'second',
      tasks: [task('ok-2', 0), task('bad-3', 3)],
    },
  ],
}
