// Keyrings. Only 'name' and 'description' are settable: add_keyring() takes no
// more. The Keyring model's own 'credentials'/'accessors' fields are not
// excluded anywhere in the write gate, and must not be -- 'Keyring' is never in
// the gate's scope at all, because resource_models.MODEL_FOR_RESOURCE['Keyring']
// is None (create_keyring() calls add_keyring(name, description) directly, with
// no model object), so settable_properties('Keyring') is never called. Adding
// NOT_SETTABLE['Keyring'] would fail test_exclusions_reference_real_model_fields
// for exactly that reason.
local base = import 'lib/base.libsonnet';

[
  {
    resource: 'Keyring',
    name: base.name('keyring-min'),
    description: 'minimal',
  },
  {
    resource: 'Keyring',
    name: base.name('keyring-max'),
    description: 'maximal: every settable property of a Keyring',
  },
]
