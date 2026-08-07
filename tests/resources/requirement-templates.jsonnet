// Compute Requirement Templates: a minimal and maximal variant of both the
// static and dynamic template types.
//
// A static template's 'sources' property is a list of ComputeSourceUsage
// entries, each naming a ComputeSourceTemplate by name -- yd-create resolves
// the name to an ID (create_compute_requirement_template(), create.py), but
// the offline model-building path this corpus is checked against
// (tests/resource_models.py's build_models()) never performs that
// resolution, so the raw name round-trips as a plain string. This file
// therefore emits the SimulatorComputeSource template its own
// ComputeSourceUsage entries name, exactly as allowances.jsonnet does for
// SourcesAllowance.sourceCreatedFromId.
//
// A dynamic template's 'constraints'/'preferences' hold real
// StringAttributeConstraint/NumericAttributeConstraint/
// StringAttributePreference/NumericAttributePreference shapes, each with the
// fully-qualified 'co.yellowdog.platform.model.<Class>' 'type' discriminator
// the SDK's polymorphic dispatch keys on -- checked directly against the
// installed SDK (none of the four is a dataclass itself, so none is reachable
// from resource_models.models_in_scope()'s nested-field walk; they still
// need real shapes for the model to actually build, just not individual
// property coverage of their own).
//
// 'namespace' is optional on both template dataclasses (settable_properties()
// still demands it be set *somewhere*, since it is a real field), so it is
// set only in the maximal variants, not the minimal ones -- matching
// source-templates.jsonnet's own contract that a minimal variant carries exactly the
// required properties. This means a real 'yd-create' run against staticMin/
// dynamicMin alone would fail: create_compute_requirement_template()
// (create.py) does 'namespace = resource[PROP_NAMESPACE]', a plain KeyError
// if the property is absent, well before the model is ever built -- a stricter
// requirement than the dataclass itself imposes. Worth knowing for the live
// layer (Tasks 7-8), which cannot create these two specifications as
// standalone resources for that reason.

local base = import 'lib/base.libsonnet';

local sourceTemplate = base.sourceTemplate(
  {
    type: 'co.yellowdog.platform.model.SimulatorComputeSource',
    name: base.name('requirement-template-source'),
  },
  'referenced by requirement-templates.jsonnet ComputeSourceUsage entries'
);

local staticMin = {
  resource: 'ComputeRequirementTemplate',
  type: 'co.yellowdog.platform.model.ComputeRequirementStaticTemplate',
  name: base.name('static-template-min'),
  strategyType: 'co.yellowdog.platform.model.WaterfallProvisionStrategy',
  sources: [
    { sourceTemplateId: sourceTemplate.source.name },
  ],
};

local staticMax = staticMin {
  name: base.name('static-template-max'),
  namespace: base.namespace,
  description: 'maximal: every settable property of a ComputeRequirementStaticTemplate',
  imagesId: '{{aws_image_id}}',
  userData: '{{user_data}}',
  instanceTags: { purpose: 'yd-cli-tests' },
  sources: [
    {
      sourceTemplateId: sourceTemplate.source.name,
      instanceType: '{{aws_instance_type}}',
      imageId: '{{aws_image_id}}',
    },
  ],
};

local dynamicMin = {
  resource: 'ComputeRequirementTemplate',
  type: 'co.yellowdog.platform.model.ComputeRequirementDynamicTemplate',
  name: base.name('dynamic-template-min'),
  strategyType: 'co.yellowdog.platform.model.SplitProvisionStrategy',
};

local dynamicMax = dynamicMin {
  name: base.name('dynamic-template-max'),
  namespace: base.namespace,
  description: 'maximal: every settable property of a ComputeRequirementDynamicTemplate',
  minimumSourceCount: 1,
  maximumSourceCount: 10,
  imagesId: '{{aws_image_id}}',
  userData: '{{user_data}}',
  instanceTags: { purpose: 'yd-cli-tests' },
  sourceNamespaces: [base.namespace],
  sourceTraits: {
    canRestart: true,
    canScaleOut: true,
    canStopStart: true,
    isSelfMaintained: false,
  },
  constraints: [
    {
      type: 'co.yellowdog.platform.model.StringAttributeConstraint',
      attribute: 'source.provider',
      anyOf: ['AWS'],
    },
    {
      type: 'co.yellowdog.platform.model.NumericAttributeConstraint',
      attribute: 'yd.cost',
      min: 0,
      max: 0.05,
    },
  ],
  preferences: [
    {
      type: 'co.yellowdog.platform.model.NumericAttributePreference',
      attribute: 'yd.cpu',
      weight: 3,
      rankOrder: 'PREFER_HIGHER',
    },
    {
      type: 'co.yellowdog.platform.model.StringAttributePreference',
      attribute: 'yd.cpu-type',
      weight: 1,
      preferredValues: ['AMD'],
    },
  ],
};

[sourceTemplate, staticMin, staticMax, dynamicMin, dynamicMax]
