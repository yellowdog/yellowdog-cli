// Namespace Policy. Builds no model at all (see resource_models.
// MODEL_FOR_RESOURCE -- create_namespace_policy() constructs a plain
// NamespacePolicy(namespace=..., autoscalingMaxNodes=...) directly rather
// than going through _get_model_object), so it contributes nothing to the
// coverage gate. Written anyway for the live layer, which needs
// a specification to create/update against.
//
// Namespace Policies are matched by their 'namespace' property, and there is
// only one namespace shared across a run (see namespace.jsonnet) -- so, like
// that file, this one targets '{{namespace}}' directly rather than a
// run-unique name. The namespace is the live system tests' too, so the
// limit is set well above anything a live run provisions: the policy is
// read back, never relied on to cap anything.

[
  {
    resource: 'NamespacePolicy',
    namespace: '{{namespace}}',
    autoscalingMaxNodes: 100,
  },
]
