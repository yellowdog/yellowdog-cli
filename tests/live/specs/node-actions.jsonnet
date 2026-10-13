// Node actions for the actions pool: write a file holding the run ID, then
// a command that succeeds only if the file holds it. Node action
// specifications substitute as __{{name}}__.
local path = '/tmp/__{{run_id}}__-node-action.txt';
{
  actions: [
    { type: 'writeFile', path: path, content: '__{{run_id}}__' },
    { type: 'runCommand', path: '/bin/grep', arguments: ['-q', '__{{run_id}}__', path] },
  ],
}
