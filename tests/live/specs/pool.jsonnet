// A run's Worker Pool on one provider ('--variable provider=<provider>'):
// one instance from the provider's static template, its Workers tagged
// '<run>-<provider>'. Idle timeouts are the crash guard, so the Platform
// shuts the pool down even if the harness dies; they are 30 minutes because
// the cloud-action steps leave the node idle for longer than 10. The Agent
// installer (install-agent.sh) is given on the command line as '--property
// workerPool.userDataFile=...', since a JSON specification's own
// 'userDataFile' is not read. Worker Pool specifications substitute as
// __{{name}}__.
{
  requirementTemplateUsage: {
    templateId: '__{{namespace}}__/__{{run_id}}__-__{{provider}}__-static',
    requirementName: '__{{run_id}}__-__{{provider}}__-pool',
    requirementNamespace: '__{{namespace}}__',
    requirementTag: '__{{tag}}__',
    targetInstanceCount: 1,
    maintainInstanceCount: false,
  },
  provisionedProperties: {
    createNodeWorkers: { targetCount: 1, targetType: 'PER_NODE' },
    minNodes: 0,
    maxNodes: 2,
    nodeBootTimeout: 'PT15M',
    idleNodeShutdown: { enabled: true, timeout: 'PT30M' },
    idlePoolShutdown: { enabled: true, timeout: 'PT30M' },
    workerTag: '__{{run_id}}__-__{{provider}}__',
  },
}
