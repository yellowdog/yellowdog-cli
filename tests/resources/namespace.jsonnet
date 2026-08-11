// The Namespace shared by every other file in this corpus. Builds no model
// at all (see resource_models.MODEL_FOR_RESOURCE -- create_namespace()
// constructs CreateNamespaceRequest(namespace=...) directly), so it
// contributes nothing to the coverage gate.
//
// No '{{run_id}}': unlike every other resource here, this one names the
// single shared, permanent namespace the rest of the corpus operates in --
// the live layer's session fixture (Tasks 7-8) creates it once per test
// account, not once per run.

[
  { resource: 'Namespace', name: '{{namespace}}' },
]
