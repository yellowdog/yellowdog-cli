// The primary's actions pool, on which the action scenarios run work and act:
// two instances from the primary's static template, two Workers on each,
// room for a third node. Variables: 'provider' (the primary). Idle timeouts
// are the crash guard, as in pool.jsonnet; the Agent installer is given on
// the command line ('--property workerPool.userDataFile=...').
{
  requirementTemplateUsage: {
    templateId: '__{{namespace}}__/__{{run_id}}__-__{{provider}}__-static',
    requirementName: '__{{run_id}}__-__{{provider}}__-actions-pool',
    requirementNamespace: '__{{namespace}}__',
    requirementTag: '__{{tag}}__',
    targetInstanceCount: 2,
    maintainInstanceCount: false,
  },
  provisionedProperties: {
    createNodeWorkers: { targetCount: 2, targetType: 'PER_NODE' },
    minNodes: 0,
    maxNodes: 3,
    nodeBootTimeout: 'PT15M',
    idleNodeShutdown: { enabled: true, timeout: 'PT30M' },
    idlePoolShutdown: { enabled: true, timeout: 'PT30M' },
    workerTag: '__{{run_id}}__-__{{provider}}__-actions',
  },
}
