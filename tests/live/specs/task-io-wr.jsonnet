// A Task's inputs and outputs (taskDataInputs, taskDataOutputs, which the
// Agent transfers with rclone) through the Task remote, keyless, the
// instance profile giving the access: the Task reads input.bin and writes
// its SHA-256 to output.txt, uploaded beside it. Variables: 'worker_tag'.
// The Platform requires 'rclone:' on the remote side and 'local:' on the Task's
// side.
local at(path) = 'rclone:{{task_data_remote}}:{{dataClient.bucket}}/{{dataClient.prefix}}/task-io/' + path;
{
  name: '{{run_id}}-task-io',
  taskType: 'bash',
  workerTags: ['{{worker_tag}}'],
  taskDataInputs: [{ source: at('input.bin'), destination: 'local:input.bin' }],
  taskDataOutputs: [{ source: 'local:output.txt', destination: at('output.txt'), alwaysUpload: true }],
  taskGroups: [
    {
      name: 'hash',
      tasks: [{ name: 'hash', arguments: ['-c', 'sha256sum input.bin > output.txt'] }],
    },
  ],
}
