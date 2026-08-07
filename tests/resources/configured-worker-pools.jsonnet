// Configured Worker Pools. Emit secrets when created (the Worker Pool Token
// is printed at creation time, per create_configured_worker_pool()/
// create.py) -- nothing for this offline corpus to act on, but worth
// remembering for the live layer (Tasks 7-8).
//
// 'tokenTtl' is a datetime.timedelta; an ISO-8601 duration string ('PT1H')
// round-trips through the SDK's own Json.load/Json.dump cleanly (checked
// directly against the installed SDK), so that -- not a plain number of
// seconds, which Json.load rejects -- is what the maximal variant uses.
//
// 'namespace' is optional on AddConfiguredWorkerPoolRequest (settable_
// properties() still demands it be set *somewhere*, since it is a real
// field), so it is set only in the maximal variant, not the minimal one --
// matching source-templates.jsonnet's own contract that a minimal variant carries
// exactly the required properties. This means a real 'yd-create' run against
// poolMin alone would fail: create_configured_worker_pool() (create.py) does
// 'namespace = resource[PROP_NAMESPACE]', a plain KeyError if the property is
// absent, well before the model is ever built -- a stricter requirement than
// the dataclass itself imposes. Worth knowing for the live layer (Tasks 7-8),
// which cannot create poolMin as a standalone resource for that reason.

local base = import 'lib/base.libsonnet';

local poolMin = {
  resource: 'ConfiguredWorkerPool',
  name: base.name('configured-pool-min'),
};

local poolMax = {
  resource: 'ConfiguredWorkerPool',
  name: base.name('configured-pool-max'),
  namespace: base.namespace,
  tokenTtl: 'PT1H',
  properties: {
    targetNodeCount: 2,
    workerTag: 'yd-cli-tests-worker',
    metricsEnabled: true,
    nodeConfiguration: {
      // Two entries, not one: the platform rejects a NodeType that specifies
      // both 'count' and 'min' together ("must not specify both count and
      // min") -- a live-only finding (Task 8), invisible to the offline
      // model-building path this corpus is otherwise checked against. Splitting
      // across two entries still exercises both fields.
      nodeTypes: [
        {
          name: 'node-type-max',
          count: 2,
          sourceNames: ['yd-cli-tests-source'],
          slotNumbering: 'REUSABLE',
        },
        {
          name: 'node-type-max-min',
          min: 1,
          sourceNames: ['yd-cli-tests-source'],
        },
      ],
      nodeEvents: {
        NODES_ADDED: [
          {
            actions: [
              {
                action: 'RUN_COMMAND',
                path: '/bin/true',
              },
            ],
          },
        ],
      },
    },
  },
};

[poolMin, poolMax]
