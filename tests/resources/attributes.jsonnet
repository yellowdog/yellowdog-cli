// Attribute Definitions: String and Numeric.
//
// create_attribute_definition() (create.py) builds a raw payload dict and
// POSTs it directly rather than calling _get_model_object -- there is no
// live model-building code path for these two types at all. Building the
// SDK model here anyway (resource_models.MODEL_FOR_RESOURCE) is still a
// valid check because the model's field names coincide with the payload's
// keys (see that module's docstring).
//
// 'range' and 'options' are mutually exclusive on a NumericAttributeDefinition
// (the platform, not the dataclass, enforces this -- see the README), so two
// maximal variants are given: one exercising 'range', one exercising
// 'options', rather than one invalid combination of both.
//
// The 'user.' name prefix mirrors the README's own examples; it is not
// enforced by the model itself, only by the platform.

local base = import 'lib/base.libsonnet';

[
  {
    resource: 'StringAttributeDefinition',
    name: 'user.' + base.name('string-attr-min'),
    title: 'minimal StringAttributeDefinition',
  },
  {
    resource: 'StringAttributeDefinition',
    name: 'user.' + base.name('string-attr-max'),
    title: 'maximal: every settable property of a StringAttributeDefinition',
    description: 'a description',
    options: ['yes', 'no', 'maybe'],
  },
  {
    resource: 'NumericAttributeDefinition',
    name: 'user.' + base.name('numeric-attr-min'),
    title: 'minimal NumericAttributeDefinition',
    defaultRankOrder: 'PREFER_LOWER',
  },
  {
    resource: 'NumericAttributeDefinition',
    name: 'user.' + base.name('numeric-attr-max-range'),
    title: 'maximal (range variant): every settable property of a NumericAttributeDefinition except options',
    defaultRankOrder: 'PREFER_HIGHER',
    description: 'a description',
    units: '$',
    range: { min: 1, max: 10 },
  },
  {
    resource: 'NumericAttributeDefinition',
    name: 'user.' + base.name('numeric-attr-max-options'),
    title: 'maximal (options variant): covers the "options" property NumericAttributeDefinition-max-range omits',
    defaultRankOrder: 'PREFER_HIGHER',
    options: [1, 2, 3],
  },
]
