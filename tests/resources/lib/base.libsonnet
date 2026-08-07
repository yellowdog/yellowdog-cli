// Shared fragments for the resource corpus. Values come from
// tests/resources/test-config.toml via '{{variable}}' substitution, which happens
// before Jsonnet evaluation, so these are ordinary strings here.
{
  run_id: '{{run_id}}',
  namespace: '{{namespace}}',

  // A name that is unique to this run and says what it is.
  name(what):: 'yd-test-{{run_id}}-' + what,

  // Wrap a source in its template, so a file can emit both variants compactly.
  sourceTemplate(source, description):: {
    resource: 'ComputeSourceTemplate',
    namespace: $.namespace,
    description: description,
    source: source,
  },
}
