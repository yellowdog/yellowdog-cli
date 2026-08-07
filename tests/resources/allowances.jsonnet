// Allowances: a minimal and maximal variant of all five subtypes.
//
// Coverage is recorded per exact class (resource_models.record_covered_
// properties() keys 'covered' by type(model).__name__), not shared across
// sibling Allowance subtypes -- so 'boostHours'/'description'/etc. must be
// set on each of the five concrete classes separately, even though they are
// declared identically on all of them.
//
// The brief's own illustrative example for this file included 'hardLimit'
// and 'limit' properties on AccountAllowance/SourcesAllowance. Checked
// directly against the installed SDK: neither AccountAllowance nor any other
// Allowance subclass declares a 'hardLimit' or a 'limit' field at all (the
// numeric cap is 'allowedHours'; 'limitEnforcement' -- SOFT/HARD -- is the
// closest real field to what 'hardLimit' suggested). Setting either would
// have produced 'Ignoring unexpected property' and silently dropped both
// from the request -- exactly the failure mode
// test_no_property_is_dropped_when_building_a_model exists to catch. Neither
// appears below.
//
// SourcesAllowance.sourceCreatedFromId resolves a Compute Source Template
// name to an ID in create_allowance() (create.py), but that resolution --
// like the equivalent one for ComputeRequirementStaticTemplate.sources --
// never happens in the offline model-building path this corpus is checked
// against, so the raw name round-trips as a plain string. This file emits
// the template it names.
//
// effectiveFrom/effectiveUntil use dateparser-friendly natural language
// (matching the README's own examples), not ISO datetimes: create_allowance()
// feeds them through dateparser before building the model, and
// tests/resource_models.py's build_models() does the same for this corpus
// (see test_allowance_natural_language_date_is_parsed_before_the_model_is_built
// in test_resource_specs.py).
//
// 'allowedHours' has an SDK default of 0 on every subtype, and is not required
// by the dataclass -- but the live platform rejects 0 outright ("allowedHours
// must be greater than or equal to 1"), a live-only finding (Task 8) invisible
// to the offline model-building path this corpus is otherwise checked against.
// Every minimal variant below therefore sets 'allowedHours: 1', the smallest
// value the platform accepts, rather than the true minimal (absent/0).
//
// RequirementsAllowance/SourcesAllowance have a second live-only requirement,
// also invisible offline: each must specify at least one of a distinct set of
// scoping properties (respectively requirementCreatedById/
// requirementCreatedFromId/namespace/tag, and sourceCreatedFromId/
// credentialName/instanceTypes/provider/regions) or the platform rejects the
// request as unscoped. requirementsMin sets 'tag' and sourcesMin sets
// 'provider' -- the cheapest member of each set that needs no other resource
// to already exist -- for that reason alone, not because either property is
// otherwise required.
//
// A further deliberate exception to the "minimal = exactly required
// properties" contract is 'description', which every minimal variant below
// sets too, even though it is optional: remove_allowance() (remove.py)
// matches an Allowance to remove by its 'description' alone, and an Allowance
// with no description can never be matched for removal at all -- so a
// description-less minimal variant would be silently unremovable by the live
// layer (Task 8), not merely untested. Giving each one a description makes the
// minimal variant genuinely less minimal, but a live resource this suite
// creates and cannot subsequently remove is the worse of the two compromises.

local base = import 'lib/base.libsonnet';

local template = base.sourceTemplate(
  {
    type: 'co.yellowdog.platform.model.SimulatorComputeSource',
    name: base.name('allowance-source'),
  },
  'referenced by the SourcesAllowance entries below'
);

local accountMin = {
  resource: 'Allowance',
  type: 'co.yellowdog.platform.model.AccountAllowance',
  description: base.name('allowance-account-min'),
  effectiveFrom: 'Now',
  resetType: 'NONE',
  limitEnforcement: 'SOFT',
  monitoredStatuses: ['RUNNING'],
  allowedHours: 1,
};

local accountMax = accountMin {
  description: base.name('allowance-account-max'),
  effectiveUntil: 'After six months',
  allowedHours: 100,
  boostHours: 10,
  resetInterval: 30,
  hardLimitGraceMinutes: 15,
  resetType: 'DAYS',
  limitEnforcement: 'HARD',
  monitoredStatuses: ['PENDING', 'RUNNING'],
};

local requirementMin = {
  resource: 'Allowance',
  type: 'co.yellowdog.platform.model.RequirementAllowance',
  requirementId: 'ydid:crt:000000:00000000-0000-0000-0000-000000000000',
  description: base.name('allowance-requirement-min'),
  effectiveFrom: 'Now',
  resetType: 'NONE',
  limitEnforcement: 'SOFT',
  monitoredStatuses: ['RUNNING'],
  allowedHours: 1,
};

local requirementMax = requirementMin {
  description: base.name('allowance-requirement-max'),
  effectiveUntil: 'After six months',
  allowedHours: 100,
  boostHours: 10,
  resetInterval: 30,
  hardLimitGraceMinutes: 15,
  resetType: 'DAYS',
  limitEnforcement: 'HARD',
  monitoredStatuses: ['PENDING', 'RUNNING'],
};

local requirementsMin = {
  resource: 'Allowance',
  type: 'co.yellowdog.platform.model.RequirementsAllowance',
  description: base.name('allowance-requirements-min'),
  effectiveFrom: 'Now',
  resetType: 'NONE',
  limitEnforcement: 'SOFT',
  monitoredStatuses: ['RUNNING'],
  allowedHours: 1,
  tag: '{{tag}}',
};

local requirementsMax = requirementsMin {
  description: base.name('allowance-requirements-max'),
  effectiveUntil: 'After six months',
  allowedHours: 100,
  boostHours: 10,
  resetInterval: 30,
  hardLimitGraceMinutes: 15,
  resetType: 'DAYS',
  limitEnforcement: 'HARD',
  monitoredStatuses: ['PENDING', 'RUNNING'],
  requirementCreatedFromId: 'ydid:crt:000000:00000000-0000-0000-0000-000000000000',
  requirementCreatedById: 'ydid:cr:000000:00000000-0000-0000-0000-000000000001',
  namespace: base.namespace,
  tag: '{{tag}}',
};

local sourceMin = {
  resource: 'Allowance',
  type: 'co.yellowdog.platform.model.SourceAllowance',
  sourceId: 'ydid:cs:000000:00000000-0000-0000-0000-000000000000',
  description: base.name('allowance-source-min'),
  effectiveFrom: 'Now',
  resetType: 'NONE',
  limitEnforcement: 'SOFT',
  monitoredStatuses: ['RUNNING'],
  allowedHours: 1,
};

local sourceMax = sourceMin {
  description: base.name('allowance-source-max'),
  effectiveUntil: 'After six months',
  allowedHours: 100,
  boostHours: 10,
  resetInterval: 30,
  hardLimitGraceMinutes: 15,
  resetType: 'DAYS',
  limitEnforcement: 'HARD',
  monitoredStatuses: ['PENDING', 'RUNNING'],
};

local sourcesMin = {
  resource: 'Allowance',
  type: 'co.yellowdog.platform.model.SourcesAllowance',
  description: base.name('allowance-sources-min'),
  effectiveFrom: 'Now',
  resetType: 'NONE',
  limitEnforcement: 'SOFT',
  monitoredStatuses: ['RUNNING'],
  allowedHours: 1,
  provider: 'AWS',
};

local sourcesMax = sourcesMin {
  description: base.name('allowance-sources-max'),
  effectiveUntil: 'After six months',
  allowedHours: 100,
  boostHours: 10,
  resetInterval: 30,
  hardLimitGraceMinutes: 15,
  resetType: 'DAYS',
  limitEnforcement: 'HARD',
  monitoredStatuses: ['PENDING', 'RUNNING'],
  sourceCreatedFromId: template.source.name,
  provider: 'AWS',
  regions: ['{{aws_region}}'],
  instanceTypes: ['{{aws_instance_type}}'],
  credentialName: '{{aws_credential}}',
};

[
  template,
  accountMin,
  accountMax,
  requirementMin,
  requirementMax,
  requirementsMin,
  requirementsMax,
  sourceMin,
  sourceMax,
  sourcesMin,
  sourcesMax,
]
