"""
Offline coverage of the resource specification corpus: no credentials, no network.

Each corpus file is loaded through the CLI's own loader, so Jsonnet expansion and
'{{variable}}' substitution are exercised exactly as in production.
"""

from datetime import datetime

import pytest
import resource_corpus
import resource_live
import resource_models

resource_corpus.require_jsonnet()


@pytest.fixture(autouse=True)
def _dummy_variables():
    """
    Feed the corpus's dummy values to the in-process substitution engine, then
    remove exactly what was added.

    VARIABLE_SUBSTITUTIONS is a process-global dict (see
    tests/test_dataclient_utils.py's setup_method/teardown_method for the same
    concern with the same dict); leaving the corpus's values installed for the
    rest of the session could let a later test's lookup of a generically-named
    variable -- namespace, tag, run_id -- silently succeed where it expected to
    default.
    """
    inserted = resource_corpus.install_variables()
    yield
    resource_corpus.remove_variables(inserted)


def test_corpus_files_are_found():
    names = {path.name for path in resource_corpus.corpus_files()}
    assert "keyrings.jsonnet" in names


def test_keyring_specs_load_with_substitutions_applied():
    resources = resource_corpus.load_corpus_file(
        resource_corpus.CORPUS_DIR / "keyrings.jsonnet"
    )

    assert [r["resource"] for r in resources] == ["Keyring", "Keyring"]
    names = [r["name"] for r in resources]
    assert all("{{" not in name for name in names), names
    assert any(name.endswith("-keyring-min") for name in names)


def test_install_variables_forces_the_corpus_value_and_restores_what_it_found():
    """
    Regression test for both halves of the install/remove contract, in the
    direction each has already failed once.

    Forcing: an earlier version merged without overwriting, so a key that already
    had a value kept it -- and 'namespace' and 'tag' always do, because conftest's
    credential probe imports wrapper, which registers the ambient configuration's
    values. The corpus then resolved '{{namespace}}' to whatever config.toml said
    while the live layer resolved it to the test config's namespace, and nothing
    noticed, because the offline comparison checks a specification against a model
    built from that same specification.

    Restoring: remove_variables() must put back exactly what was there, since
    VARIABLE_SUBSTITUTIONS is process-global. Deleting a key that held some other
    value would leave the session different from how the test found it, and leaving
    the corpus value installed would let a later test's lookup of a name as generic
    as 'namespace' silently succeed where it expected to default.

    Saves and restores both keys directly, independent of the module's autouse
    fixture, so the outcome does not depend on what that fixture already installed.
    """
    from yellowdog_cli.utils.variables import VARIABLE_SUBSTITUTIONS

    occupied_key = "namespace"  # stands in for the ambient config's value
    fresh_key = "aws_region"

    original = {
        key: VARIABLE_SUBSTITUTIONS[key]
        for key in (occupied_key, fresh_key)
        if key in VARIABLE_SUBSTITUTIONS
    }

    VARIABLE_SUBSTITUTIONS[occupied_key] = "ambient-value"
    VARIABLE_SUBSTITUTIONS.pop(fresh_key, None)

    try:
        wanted = resource_corpus.dummy_variables()
        previous = resource_corpus.install_variables()

        # The corpus value wins over the one that was already there, and the key
        # that was absent is now present.
        assert VARIABLE_SUBSTITUTIONS[occupied_key] == wanted[occupied_key]
        assert VARIABLE_SUBSTITUTIONS[fresh_key] == wanted[fresh_key]
        assert previous[occupied_key] == "ambient-value"
        assert previous[fresh_key] is None

        resource_corpus.remove_variables(previous)

        # What was there is back; what was not is gone again.
        assert VARIABLE_SUBSTITUTIONS[occupied_key] == "ambient-value"
        assert fresh_key not in VARIABLE_SUBSTITUTIONS
    finally:
        for key in (occupied_key, fresh_key):
            VARIABLE_SUBSTITUTIONS.pop(key, None)
        VARIABLE_SUBSTITUTIONS.update(original)


def test_a_corpus_load_uses_the_test_config_namespace_not_the_ambient_one():
    """
    The guard that would have caught the bug above where it actually mattered.

    The previous test checks the registry; this one checks the consequence a reader
    cares about: that a loaded specification carries the test config's namespace
    even when the process already has a different one registered, as it always does
    under pytest. Without forcing, this resolved to the ambient config's namespace
    ('yd-demo' on the machine where it was found) while the live layer, passing
    '-c test-config.toml' to a subprocess, used 'yd-cli-tests'.
    """
    from yellowdog_cli.utils.variables import VARIABLE_SUBSTITUTIONS

    key = "namespace"
    original = (
        {key: VARIABLE_SUBSTITUTIONS[key]} if key in VARIABLE_SUBSTITUTIONS else {}
    )
    VARIABLE_SUBSTITUTIONS[key] = "ambient-namespace"

    try:
        previous = resource_corpus.install_variables()
        try:
            resources = resource_corpus.load_corpus_file(
                resource_corpus.CORPUS_DIR / "image-families.jsonnet"
            )
        finally:
            resource_corpus.remove_variables(previous)

        namespaces = {r["namespace"] for r in resources if "namespace" in r}
        assert namespaces == {resource_corpus.dummy_variables()[key]}, namespaces
        assert "ambient-namespace" not in namespaces
    finally:
        VARIABLE_SUBSTITUTIONS.pop(key, None)
        VARIABLE_SUBSTITUTIONS.update(original)


def test_every_corpus_resource_builds_a_model_or_is_declared_modelless():
    for path in resource_corpus.corpus_files():
        for resource in resource_corpus.load_corpus_file(path):
            resource_type = resource["resource"]
            assert resource_type in resource_models.MODEL_FOR_RESOURCE, (
                f"{path.name}: resource type '{resource_type}' is not in"
                " MODEL_FOR_RESOURCE"
            )


def test_keyring_properties_survive_into_the_model():
    resources = resource_corpus.load_corpus_file(
        resource_corpus.CORPUS_DIR / "keyrings.jsonnet"
    )
    # Keyring is built by a direct client call, so there is no model to compare
    # against; assert the declaration says so, that build_models() agrees, and
    # that the properties are intact.
    assert resource_models.MODEL_FOR_RESOURCE["Keyring"] is None
    for resource in resources:
        assert resource_models.build_models(resource) == []
        properties = resource_corpus.spec_properties(resource)
        assert set(properties) == {"name", "description"}


def test_no_property_is_dropped_when_building_a_model(capsys):
    """
    Two guards, because neither covers the other's cases.

    _get_model_object's 'Ignoring unexpected property' warning fires when a
    *top-level* property of one pair's dict is not a field of that pair's model,
    and the property is then silently absent from the request the real CLI would
    send -- so the warning must never appear. But it is top-level only: it
    inspects the keys of the dict it is handed, never the keys of a dict nested
    inside it, so a *nested* rename (a property of a compute source's
    spotOptions, of an image group inside a family, of a constraint inside a
    dynamic template) produces no warning at all.

    The value comparison is what actually protects those: the model's nested
    object, structured on the way in and dumped again by comparable(), no longer
    carries the renamed key, so it no longer equals what the specification sent.
    The same comparison is also the only thing that catches a property surviving
    under the right name with a mangled value.
    """
    for path in resource_corpus.corpus_files():
        for resource in resource_corpus.load_corpus_file(path):
            pairs = resource_models.build_models(resource)
            output = capsys.readouterr().out
            assert "Ignoring unexpected property" not in output, (
                f"{path.name}: {resource['resource']}: {output.strip()}"
            )
            for model, properties in pairs:
                for name, expected in properties.items():
                    assert hasattr(model, name), (
                        f"{path.name}: {type(model).__name__} has no '{name}'"
                    )
                    actual = resource_models.comparable(getattr(model, name))
                    assert actual == resource_models.comparable(expected), (
                        f"{path.name}: {type(model).__name__}.{name} = {actual!r},"
                        f" expected {resource_models.comparable(expected)!r}"
                    )


def test_compute_source_template_wrapper_and_source_properties_go_to_the_right_model():
    """
    Regression test for the defect that motivated build_models() returning pairs:
    a ComputeSourceTemplate specification's top-level properties (namespace,
    description, attributes) are fields of the wrapper, not of the source class --
    see create.py's create_compute_source_template(), which builds the source and
    passes it as a keyword to build the wrapper. Comparing the whole specification
    against a single model let those three properties be silently dropped, since
    AwsInstancesComputeSource has none of them. Written inline rather than as a
    corpus file: corpus files belong to Tasks 5-6.
    """
    resource = {
        "resource": "ComputeSourceTemplate",
        "namespace": "my-namespace",
        "description": "test source template",
        "attributes": [],
        "source": {
            "type": "co.yellowdog.platform.model.AwsInstancesComputeSource",
            "name": "my-source",
            "credential": "my-keyring/my-aws-credential",
            "region": "eu-west-2",
            "securityGroupId": "sg-0123456789",
            "instanceType": "t3a.micro",
            "imageId": "ami-0123456789",
            "limit": 3,
            "assignPublicIp": True,
            "instanceTags": {"environment": "test"},
        },
    }

    pairs = resource_models.build_models(resource)
    assert len(pairs) == 2
    source_model, source_properties = pairs[0]
    wrapper_model, wrapper_properties = pairs[1]

    assert type(source_model).__name__ == "AwsInstancesComputeSource"
    assert type(wrapper_model).__name__ == "ComputeSourceTemplate"

    # The wrapper's own properties are not fields of the source, and vice versa --
    # proving each property pair is checked against the model that actually owns it.
    assert not hasattr(source_model, "namespace")
    assert not hasattr(source_model, "description")
    assert not hasattr(wrapper_model, "region")
    assert not hasattr(wrapper_model, "instanceType")

    for name, expected in source_properties.items():
        assert resource_models.comparable(
            getattr(source_model, name)
        ) == resource_models.comparable(expected)
    for name, expected in wrapper_properties.items():
        assert resource_models.comparable(
            getattr(wrapper_model, name)
        ) == resource_models.comparable(expected)


def test_allowance_natural_language_date_is_parsed_before_the_model_is_built():
    """
    create_allowance() feeds effectiveFrom/effectiveUntil through dateparser before
    building the model (see create.py's PROP_EFFECTIVE_FROM/PROP_EFFECTIVE_UNTIL
    handling), because the CLI documents natural-language dates like 'Today' as
    supported. Without that step, _get_model_object's underlying Json.load raises
    trying to structure 'Today' as an ISO datetime -- reusing the CLI's own
    dateparser call, rather than reimplementing it, is what this test protects.
    """
    resource = {
        "resource": "Allowance",
        "type": "co.yellowdog.platform.model.AccountAllowance",
        "effectiveFrom": "Today",
        "effectiveUntil": "31 December 2026",
        "resetType": "NONE",
        "limitEnforcement": "HARD",
        "monitoredStatuses": ["RUNNING"],
        "allowedHours": 5,
    }

    [(model, properties)] = resource_models.build_models(resource)

    assert type(model).__name__ == "AccountAllowance"
    # The compared value is the parsed datetime, not the original natural-language
    # string -- proving the parsing happened before the comparison, not after.
    assert isinstance(properties["effectiveFrom"], datetime)
    assert isinstance(properties["effectiveUntil"], datetime)
    for name, expected in properties.items():
        assert resource_models.comparable(
            getattr(model, name)
        ) == resource_models.comparable(expected)


# ---------------------------------------------------------------------------
# The dry-run step: create.py's own dispatch, offline.
# ---------------------------------------------------------------------------
#
# Everything above builds models through resource_models.build_models(), which
# *mirrors* create.py rather than calling it: it re-implements which properties
# each model owns, and which keys are popped before construction. Six defects on
# this branch were that mirror drifting from the original. A dry run closes the
# gap from the other side, because create.py deliberately calls
# _get_model_object() on the dry-run path for the three resource types whose
# construction needs pre-processing -- Compute Source Templates (create.py's
# create_compute_source_template), Compute Requirement Templates and Allowances
# -- so this exercises create.py's *own* dispatch and its own pops, with no
# mirror in between. (Every other resource type takes create_resources()'s
# generic dry-run branch, which prints the specification and continues without
# building anything; those files are still run here, for the 'resource'/
# '_sourceDir' pops and the dispatch itself.)
#
# Run in-process rather than as a 'yd-create -D' subprocess, which cannot be
# offline: create_compute_source_template() resolves an image name to an ID, and
# create_compute_requirement_template()/create_allowance() resolve a Compute
# Source (or Requirement) Template name to an ID, *before* reaching their
# dry-run branch -- all three are platform calls (get_image_name_or_id() fetches
# the account's image family summaries; the template lookups search the
# account), so a real 'yd-create -D' on source-templates.jsonnet, requirement-templates.
# jsonnet or allowances.jsonnet exits non-zero without credentials and a network,
# whatever the specification says. Those three resolvers are therefore the only
# things stubbed here, each to the identity/a fixed YDID: they are name->ID
# lookups, orthogonal to the dispatch and the pops this test is about. Nothing
# else is faked -- create_resources(), the dispatch, the pops, _get_model_object
# and print_json are all the real ones -- and in-process needs no config file or
# credentials beyond what importing yellowdog_cli.create already requires of
# every test in this module.
_DRY_RUN_FAKE_CST_ID = "ydid:cst:000000:00000000-0000-0000-0000-000000000000"
_DRY_RUN_FAKE_CRT_ID = "ydid:crt:000000:00000000-0000-0000-0000-000000000000"

# Corpus specifications the dry run is expected to fail on, per corpus file,
# named by their base.name() suffix exactly as resource_live.
# KNOWN_PARTIAL_FAILURE_NAMES names theirs -- and asserted below to be a subset
# of that registry, so the offline expectation can never claim a failure the
# live layer does not already document.
#
# requirement-templates.jsonnet's staticMin/dynamicMin omit 'namespace', and
# create_compute_requirement_template() reads it with a bare subscript before
# any model is built: the dry run reproduces that live finding with no platform
# at all. configured-worker-pools.jsonnet's poolMin, the third entry in that
# registry, is deliberately absent here: create_configured_worker_pool() has no
# dry-run branch of its own, so create_resources()' generic branch prints the
# specification and continues before that function is ever called, and the
# failure is simply not reachable offline.
_DRY_RUN_EXPECTED_FAILURES: dict[str, frozenset[str]] = {
    "requirement-templates.jsonnet": frozenset(
        {"static-template-min", "dynamic-template-min"}
    ),
}


@pytest.fixture
def dry_run_create():
    """
    create.create_resources, in dry-run mode, with only the three name->ID
    platform lookups stubbed (see this section's own comment for why those three
    and nothing else). Every patch is undone afterwards, including the dry-run
    flag, which does not exist on the argparse namespace under pytest at all.
    """
    from yellowdog_cli import create
    from yellowdog_cli.utils.args import ARGS_PARSER

    def _identity_image(client, image_name_or_id, **kwargs):
        return image_name_or_id

    patches = {
        "get_image_name_or_id": _identity_image,
        "get_compute_source_template_id_by_name": lambda **kwargs: _DRY_RUN_FAKE_CST_ID,
        "get_compute_requirement_template_id_by_name": (
            lambda **kwargs: _DRY_RUN_FAKE_CRT_ID
        ),
    }
    originals = {name: getattr(create, name) for name in patches}
    had_dry_run = hasattr(ARGS_PARSER.args, "dry_run")
    original_dry_run = getattr(ARGS_PARSER.args, "dry_run", None)

    for name, replacement in patches.items():
        setattr(create, name, replacement)
    ARGS_PARSER.args.dry_run = True
    try:
        yield create.create_resources
    finally:
        if had_dry_run:
            ARGS_PARSER.args.dry_run = original_dry_run
        else:
            delattr(ARGS_PARSER.args, "dry_run")
        for name, original in originals.items():
            setattr(create, name, original)


def _dry_run_one(dry_run_create, resource: dict) -> bool:
    """
    Whether create_resources() reported a failure for this one specification.

    One call per specification, rather than one per file, purely for
    attribution: create_resources() catches each resource's exception, prints it
    and continues, raising a single RuntimeError naming only a count at the end
    -- which cannot say *which* specification failed. Calling it per resource
    makes the answer the caller's own loop variable. The list is passed as an
    argument, so create_resources() deep-copies it and the caller's specification
    is left unmutated.
    """
    try:
        dry_run_create([resource])
        return False
    except RuntimeError:
        return True


@pytest.mark.parametrize(
    "corpus_file",
    [pytest.param(path, id=path.stem) for path in resource_corpus.corpus_files()],
)
def test_every_corpus_specification_survives_a_dry_run_create(
    corpus_file, dry_run_create, capsys
):
    """
    Every specification in the file passes 'yd-create --dry-run''s real code
    path -- create_resources()' dispatch, its 'resource'/'_sourceDir' pops, and
    _get_model_object() where create.py itself calls it -- except the ones
    resource_live.KNOWN_PARTIAL_FAILURE_NAMES already documents as
    uncreatable, which must fail and must be exactly the ones that do.
    """
    expected_suffixes = _DRY_RUN_EXPECTED_FAILURES.get(corpus_file.name, frozenset())
    assert expected_suffixes <= resource_live.KNOWN_PARTIAL_FAILURE_NAMES.get(
        corpus_file.name, frozenset()
    ), (
        f"{corpus_file.name}: the dry run expects a failure that resource_live."
        "KNOWN_PARTIAL_FAILURE_NAMES does not document; reconcile the two"
    )
    run_id = resource_corpus.dummy_variables()["run_id"]
    expected_failures = {f"yd-test-{run_id}-{s}" for s in expected_suffixes}

    resources = resource_corpus.load_corpus_file(corpus_file)
    assert resources, f"{corpus_file.name} loaded no specifications at all"

    failed: set[str] = set()
    for index, resource in enumerate(resources):
        identity = resource.get("name") or f"{resource['resource']}#{index}"
        if _dry_run_one(dry_run_create, resource):
            failed.add(identity)
        output = capsys.readouterr().out
        assert "Ignoring unexpected property" not in output, (
            f"{corpus_file.name}: {identity}: {output.strip()}"
        )

    assert failed == expected_failures, (
        f"{corpus_file.name}: expected exactly {sorted(expected_failures)} to fail "
        f"a dry-run create, but {sorted(failed)} did"
    )


def test_the_dry_run_create_notices_a_property_no_model_declares(
    dry_run_create, capsys
):
    """
    Positive control for the test above: a dry run that could not fail would
    prove nothing. A property no model declares must produce create.py's own
    'Ignoring unexpected property' warning -- the warning that test asserts the
    absence of -- from create_compute_source_template()'s dry-run branch, which
    is the whole reason a dry run is worth running offline at all.
    """
    [resource] = [
        r
        for r in resource_corpus.load_corpus_file(
            resource_corpus.CORPUS_DIR / "source-templates.jsonnet"
        )
        if r["source"]["name"].endswith("aws-instances-min")
    ]
    resource["source"]["noSuchProperty"] = "value"

    assert not _dry_run_one(dry_run_create, resource)
    assert "Ignoring unexpected property" in capsys.readouterr().out


def test_comparable_mismatch_is_caught_not_silently_passed():
    """
    A value-equality check that can never fail is not a check: this proves the
    comparison used above actually catches a property whose value was mangled on
    the way into the model, not just one that vanished entirely.
    """
    resource = {
        "resource": "Allowance",
        "type": "co.yellowdog.platform.model.AccountAllowance",
        "effectiveFrom": "Today",
        "resetType": "NONE",
        "limitEnforcement": "HARD",
        "monitoredStatuses": ["RUNNING"],
        "allowedHours": 5,
    }
    [(model, properties)] = resource_models.build_models(resource)

    wrong_properties = dict(properties)
    wrong_properties["allowedHours"] = properties["allowedHours"] + 1

    mismatches = [
        name
        for name, expected in wrong_properties.items()
        if resource_models.comparable(getattr(model, name))
        != resource_models.comparable(expected)
    ]
    assert mismatches == ["allowedHours"]
