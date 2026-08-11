// Namespace Policy. Builds no model at all (see resource_models.
// MODEL_FOR_RESOURCE -- create_namespace_policy() constructs a plain
// NamespacePolicy(namespace=..., autoscalingMaxNodes=...) directly rather
// than going through _get_model_object), so it contributes nothing to the
// coverage gate. Written anyway for the live layer (Tasks 7-8), which needs
// a specification to create/update against.
//
// Namespace Policies are matched by their 'namespace' property, and there is
// only one namespace shared across a run (see namespace.jsonnet) -- so, like
// that file, this one targets '{{namespace}}' directly rather than a
// run-unique name.

[
  {
    resource: 'NamespacePolicy',
    namespace: '{{namespace}}',
    autoscalingMaxNodes: 5,
  },
]
