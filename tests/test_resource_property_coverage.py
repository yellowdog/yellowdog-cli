"""
The gate that keeps 'comprehensive' honest.

Every settable property of every in-scope model must be set by at least one corpus
specification, or excluded with a stated reason. An SDK upgrade that adds a property
therefore fails this test until the corpus covers it -- which is also how a serde
regression surfaces, since the offline layer round-trips every covered property
through model construction (see resource_models.build_models()).

Tasks 5 and 6 completed the corpus (compute sources, then everything else); the
xfail(strict=True) marker that guarded this test while the corpus was still being
built has been removed now that it passes for real.
"""

import dataclasses
from collections import defaultdict

import resource_corpus
import resource_models

resource_corpus.require_jsonnet()


def _properties_set_by_the_corpus() -> dict[str, set[str]]:
    """
    model class name -> every property any specification sets on it.

    Installs the corpus's dummy variables and removes exactly what it added,
    which matters beyond this module: VARIABLE_SUBSTITUTIONS is process-global,
    and this module is collected before tests/test_resource_specs.py, so an
    install left in place here would make *that* module's autouse
    _dummy_variables fixture observe every key as already present, compute
    'inserted == []', and remove nothing -- silently disabling the teardown it
    exists to provide, and leaving 'namespace'/'tag'/'run_id' installed for the
    rest of the session. try/finally rather than a fixture because this is a
    plain helper, called from a test body.
    """
    inserted = resource_corpus.install_variables()
    covered: dict[str, set[str]] = defaultdict(set)
    try:
        for path in resource_corpus.corpus_files():
            for resource in resource_corpus.load_corpus_file(path):
                resource_models.record_covered_properties(resource, covered)
    finally:
        resource_corpus.remove_variables(inserted)
    return covered


def test_every_settable_property_is_covered_or_excluded():
    covered = _properties_set_by_the_corpus()
    gaps: list[str] = []

    for model_name in sorted(resource_models.models_in_scope()):
        missing = resource_models.settable_properties(model_name) - covered.get(
            model_name, set()
        )
        if missing:
            gaps.append(f"  {model_name}: {sorted(missing)}")

    assert not gaps, (
        "settable properties never exercised by any specification:\n"
        + "\n".join(gaps)
        + "\n\nAdd them to a specification in tests/resources/, or -- if the"
        " creation path genuinely cannot populate the property -- to"
        " resource_models.NOT_SETTABLE with a reason citing the create.py"
        " behaviour or evidence that shows it, or to resource_models.NOT_TESTED"
        " if it's covered some other way. Do not exclude on a hunch: an"
        " excluded property is invisible to this gate forever, so when in doubt"
        " leave it here instead."
    )


def test_exclusions_all_carry_a_reason():
    for mapping in (resource_models.NOT_SETTABLE, resource_models.NOT_TESTED):
        for model_name, properties in mapping.items():
            for name, reason in properties.items():
                assert reason.strip(), (
                    f"{model_name}.{name} is excluded without a reason"
                )


def test_exclusions_reference_real_model_fields():
    """
    A property can only be excluded from a model it actually belongs to, and
    that this gate actually checks.

    Two ways an exclusion can be a no-op that still misdescribes the model, both
    found by review:

    - Naming a property that isn't a field of the named model at all (the
      original AddApplicationRequest.groups/keyrings bug -- neither is a field
      of any model, so the exclusion did nothing).
    - Naming a real field of a model that is not in models_in_scope() at all
      (the *other* form of the same bug: re-adding
      NOT_SETTABLE["Keyring"] = {"credentials": ..., "accessors": ...} passes
      the first check -- both are genuine Keyring fields -- but Keyring is
      never reachable from a MODEL_FOR_RESOURCE/DYNAMIC_MODELS root, so
      settable_properties("Keyring") is never even called and the exclusion is
      still inert).

    "*" in NOT_TESTED is exempt from both checks: it is a deliberate
    cross-cutting rule (the polymorphic 'type' discriminator, popped before any
    model is built) that applies across many different classes by design, not a
    single model's field list or scope membership to check against.
    """
    in_scope = resource_models.models_in_scope()
    for mapping in (resource_models.NOT_SETTABLE, resource_models.NOT_TESTED):
        for model_name, properties in mapping.items():
            if model_name == "*":
                continue
            assert model_name in in_scope, (
                f"{model_name} is excluded from, but is not in "
                "models_in_scope() at all -- settable_properties() is never "
                "called for it, so the exclusion has no effect and "
                "misdescribes the model; fix or remove it"
            )
            fields = {
                f.name
                for f in dataclasses.fields(resource_models._model_class(model_name))
            }
            for name in properties:
                assert name in fields, (
                    f"{model_name}.{name} is excluded, but '{name}' is not a "
                    f"field of {model_name} at all -- the exclusion has no "
                    "effect and misdescribes the model; fix or remove it"
                )


def test_server_assigned_does_not_bleed_into_an_unrelated_same_named_field():
    """
    A SERVER_ASSIGNED name is only evidenced for the classes recorded against
    it in SERVER_ASSIGNED_COVERAGE; guards against it silently swallowing a
    different, genuinely author-settable field that happens to share the name
    on some other model.

    All three cases below were found by exactly this mistake during review:
    'id'/'provider' are also plain (init=True) fields on models where they mean
    something the SERVER_ASSIGNED probe never tested -- an existing AWS capacity
    reservation to target, and an allowance/image's own author-supplied provider
    value -- and must stay in the gate.
    """
    for model_name, property_name in (
        ("AwsCapacityReservation", "id"),
        ("SourcesAllowance", "provider"),
        ("MachineImage", "provider"),
    ):
        assert property_name in resource_models.settable_properties(model_name), (
            f"{model_name}.{property_name} shares a name with a SERVER_ASSIGNED "
            "entry but is a different, author-settable field on this model; it "
            "must not be excluded"
        )


def test_server_assigned_coverage_does_not_infer_an_unprobed_class():
    """
    The mirror case of the bleed-guard above: a class that was never probed or
    verified must not be excluded just because the SDK happens to declare the
    field init=False there too.

    All seven pairs below were exactly this mistake, found by review of the
    first version of SERVER_ASSIGNED_COVERAGE (then a plain field.init check):
    each is a different resource family that merely happens to declare 'id' or
    'createdTime' the same way a probed class does. All seven are now settled
    by a direct live probe (see task-4-report.md) and belong in the gate as
    excluded -- this test is the regression guard, not a statement that they
    are still open questions.
    """
    for model_name, property_name in (
        ("ComputeSourceTemplate", "id"),
        ("ComputeRequirementStaticTemplate", "id"),
        ("ComputeRequirementDynamicTemplate", "id"),
        ("MachineImage", "id"),
        ("MachineImage", "createdTime"),
        ("MachineImageGroup", "id"),
        ("MachineImageGroup", "createdTime"),
    ):
        assert property_name not in resource_models.settable_properties(model_name), (
            f"{model_name}.{property_name} is expected to be SERVER_ASSIGNED "
            "(confirmed by a live probe; see task-4-report.md) -- if this now "
            "fails, either the probe evidence changed or "
            "SERVER_ASSIGNED_COVERAGE regressed"
        )


def test_a_server_assigned_name_is_not_excluded_from_an_unrecorded_class():
    """
    The guard on *how* exclusion is computed: only SERVER_ASSIGNED_COVERAGE may
    exclude, never a field's own dataclass metadata.

    test_server_assigned_coverage_does_not_infer_an_unprobed_class above asserts
    outcomes for seven settled pairs, so it catches a class being *deleted* from
    the registry -- a safe direction, since the property becomes visibly
    uncovered again. It says nothing about a fallback that re-derives exclusion
    from dataclasses.field.init, which is the criterion three earlier rounds of
    this task each established to be false (the SDK structures with
    _cattrs_include_init_false=True, so an init=False field is populated from a
    specification like any other). Such a fallback is inert today only because
    the registry is complete for the installed SDK: a *future* SDK class sharing
    a name with a SERVER_ASSIGNED entry and declaring it init=False, with no
    registry entry of its own, would silently inherit the exclusion and the gap
    would be invisible forever.

    So this synthesises exactly that class -- registered on the SDK's model
    module, which is where create._get_model_class() (and hence
    resource_models._model_class()) genuinely resolves names from, so nothing
    inside resource_models is stubbed -- puts it in scope, and asserts its
    init=False, SERVER_ASSIGNED-named field is still demanded. Everything it
    registers is removed again in the finally block.
    """
    from yellowdog_client import model as sdk_model

    property_name = "status"
    assert property_name in resource_models.SERVER_ASSIGNED, (
        f"this test needs a real SERVER_ASSIGNED name; {property_name!r} is no"
        " longer one -- pick another"
    )

    class_name = "_UnrecordedFutureModel"

    @dataclasses.dataclass
    class _UnrecordedFutureModel:
        name: str | None = None
        # Named in SERVER_ASSIGNED, declared exactly the way the SDK declares
        # the genuinely server-assigned ones -- and evidenced for no class.
        status: str | None = dataclasses.field(default=None, init=False)

    assert not hasattr(sdk_model, class_name), (
        f"{class_name} already exists on the SDK's model module; this test would"
        " clobber it"
    )
    assert not any(
        class_name in evidenced_for
        for evidenced_for in resource_models.SERVER_ASSIGNED_COVERAGE.values()
    )

    setattr(sdk_model, class_name, _UnrecordedFutureModel)
    resource_models.DYNAMIC_MODELS.add(class_name)
    try:
        assert class_name in resource_models.models_in_scope(), (
            "the synthesised model must be in scope for this to say anything"
            " about the gate"
        )
        assert property_name in resource_models.settable_properties(class_name), (
            f"{class_name}.{property_name} shares a name with a SERVER_ASSIGNED"
            " entry and is declared init=False, but no SERVER_ASSIGNED_COVERAGE"
            " entry records any evidence for this class -- it must stay in the"
            " gate. An exclusion inferred from field.init (or any other"
            " dataclass metadata) is exactly the discredited criterion"
            " SERVER_ASSIGNED_COVERAGE exists to replace; see"
            " settable_properties()'s docstring"
        )

        # Positive control: the same field, once the registry claims evidence
        # for this class, *is* excluded. Without this, the assertion above could
        # pass because the exclusion machinery never reached this class at all.
        original = resource_models.SERVER_ASSIGNED_COVERAGE[property_name]
        resource_models.SERVER_ASSIGNED_COVERAGE[property_name] = original | frozenset(
            {class_name}
        )
        try:
            assert property_name not in resource_models.settable_properties(class_name)
        finally:
            resource_models.SERVER_ASSIGNED_COVERAGE[property_name] = original
    finally:
        resource_models.DYNAMIC_MODELS.discard(class_name)
        delattr(sdk_model, class_name)

    assert class_name not in resource_models.models_in_scope()


def test_withdrawing_registry_evidence_puts_the_property_back_in_the_gate():
    """
    The same guarantee as the test above, on a real SDK class rather than a
    synthesised one: SERVER_ASSIGNED_COVERAGE is the *only* thing keeping
    MachineImageGroup.createdTime out of the gate.

    The pair is chosen because the discredited criterion still holds for it --
    the SDK really does declare this field init=False (asserted below, so this
    test stops being a discriminator loudly rather than silently if that
    changes) -- so any fallback re-deriving exclusion from field.init keeps the
    property excluded here even with the registry evidence withdrawn, and this
    test fails.
    """
    coverage = resource_models.SERVER_ASSIGNED_COVERAGE
    property_name, model_name = "createdTime", "MachineImageGroup"

    field = next(
        f
        for f in dataclasses.fields(resource_models._model_class(model_name))
        if f.name == property_name
    )
    assert field.init is False, (
        f"{model_name}.{property_name} is no longer declared init=False, so it"
        " can no longer distinguish registry-driven exclusion from one inferred"
        " from dataclass metadata -- pick another pair that is"
    )

    original = coverage[property_name]
    assert model_name in original
    assert property_name not in resource_models.settable_properties(model_name)

    coverage[property_name] = original - {model_name}
    try:
        assert property_name in resource_models.settable_properties(model_name), (
            f"{model_name} is no longer recorded in SERVER_ASSIGNED_COVERAGE"
            f"[{property_name!r}], so {property_name} must be demanded by the"
            " gate again -- something other than that registry (a field.init"
            " check, or any other dataclass metadata) is deciding exclusion"
        )
    finally:
        coverage[property_name] = original

    assert property_name not in resource_models.settable_properties(model_name)


def test_server_assigned_coverage_references_real_fields_of_in_scope_models():
    """
    Every (property, model) pair SERVER_ASSIGNED_COVERAGE records must name a
    real field of a model this gate actually checks -- the same guarantee
    test_exclusions_reference_real_model_fields gives NOT_SETTABLE/NOT_TESTED,
    extended to this registry since it is exactly the same shape of mapping.
    """
    in_scope = resource_models.models_in_scope()
    for property_name, model_names in resource_models.SERVER_ASSIGNED_COVERAGE.items():
        for model_name in model_names:
            assert model_name in in_scope, (
                f"SERVER_ASSIGNED_COVERAGE[{property_name!r}] names "
                f"{model_name}, which is not in models_in_scope()"
            )
            fields = {
                f.name
                for f in dataclasses.fields(resource_models._model_class(model_name))
            }
            assert property_name in fields, (
                f"SERVER_ASSIGNED_COVERAGE[{property_name!r}] names "
                f"{model_name}, which has no field called {property_name!r}"
            )
