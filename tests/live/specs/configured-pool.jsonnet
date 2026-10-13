// The run's Configured Worker Pool, for 'yd wp token': no nodes need join
// it. Removed by teardown with the run's other resources.
[
  {
    resource: 'ConfiguredWorkerPool',
    name: '{{run_id}}-configured-pool',
    namespace: '{{namespace}}',
    tokenTtl: 'PT1H',
  },
]
