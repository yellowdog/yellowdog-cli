// Work for resubmitting FAILED and CANCELLED Tasks: a Task Group of bash
// Tasks, some exiting 0 and some 3 (failing), run on the actions pool, and a
// Task Group waiting on Workers nothing has, whose Tasks are cancelled while
// they wait. Variables: 'wr' (the name's suffix), 'worker_tag'.
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
  taskGroups: [
    {
      name: 'running',
      workerTags: ['{{worker_tag}}'],
      tasks: [task('ok-1', 0), task('bad-1', 3), task('bad-2', 3)],
    },
    {
      name: 'waiting',
      workerTags: ['{{run_id}}-nobody'],
      tasks: [task('wait-1', 0), task('wait-2', 0)],
    },
  ],
}
