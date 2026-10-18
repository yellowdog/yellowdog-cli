// A run's shared resources: the Keyring its Credentials go into, and the
// Allowance that caps what its Compute Requirements (tagged with the run ID,
// as every Compute Requirement the run makes is) may use. Every value is a
// variable tests/live/harness/run.py defines.
[
  {
    resource: 'Keyring',
    name: '{{keyring}}',
    // The sweep counts a Keyring only when it names the sweep's namespace
    description: 'Live system tests, run {{run_id}}, namespace {{namespace}}',
  },
  {
    resource: 'Allowance',
    type: 'co.yellowdog.platform.model.RequirementsAllowance',
    // Removal matches an Allowance by its description, so it names the run
    description: '{{allowance_description}}',
    namespace: '{{namespace}}',
    tag: '{{tag}}',
    effectiveFrom: 'Now',
    effectiveUntil: 'In 3 days',
    resetType: 'NONE',
    limitEnforcement: 'HARD',
    hardLimitGraceMinutes: 5,
    monitoredStatuses: ['PENDING', 'RUNNING'],
    allowedHours: '{{num:max_instance_hours}}',
  },
]
