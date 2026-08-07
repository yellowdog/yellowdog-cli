"""
System tests: resource CRUD lifecycle against the real platform, using the resource
corpus (resource_corpus.py) and the live harness (resource_live.py) built for it.

Run with: pytest --run-system tests/test_system_resources.py

Prerequisites: YD_KEY and YD_SECRET in the environment (plus YD_URL for a
non-default platform). Nothing else -- no configuration file of your own, and no
cloud credentials. tests/resources/test-config.toml supplies the namespace and the
dummy infrastructure values, and deliberately carries no credentials of any kind;
see tests/resource_live.py's module docstring.
"""

from collections import defaultdict

import pytest
import resource_corpus
import resource_live
import resource_models

resource_corpus.require_jsonnet()

# Resource type (a corpus specification's own 'resource' property) -> the
# yd-list/yd-remove entity type it becomes. One entry per resource type the live
# corpus can create (resource_corpus.OFFLINE_ONLY's two files -- credentials and
# the shared namespace -- never reach this module at all, so neither needs an
# entry here).
ENTITY_TYPE_FOR_RESOURCE = {
    "Keyring": "keyrings",
    "NamespacePolicy": "namespace-policies",
    "MachineImageFamily": "image-families",
    "ComputeSourceTemplate": "compute-source-templates",
    "ComputeRequirementTemplate": "compute-requirement-templates",
    "Allowance": "allowances",
    "StringAttributeDefinition": "attribute-definitions",
    "NumericAttributeDefinition": "attribute-definitions",
    "Group": "groups",
    "Application": "applications",
    "ConfiguredWorkerPool": "worker-pools",
}

# WorkerPoolStatus values remove_configured_worker_pool() (remove.py) leaves a
# shut-down Configured Worker Pool in -- checked directly against the installed
# SDK's own WorkerPoolStatus.finished property, which agrees with exactly these
# two values.
_FINISHED_WORKER_POOL_STATUSES = {"SHUTDOWN", "TERMINATED"}

# The read gate's raw material: every property name actually seen in a live
# 'yd-show'/'yd-list --details' response, per model class, accumulated across every
# test_resource_lifecycle case in this session by _record_read_gate_evidence().
# Keyed the same way resource_models.SERVER_ASSIGNED_COVERAGE is (a concrete SDK
# class name, e.g. 'AwsInstancesComputeSource', 'AccountAllowance',
# 'MachineImageGroup') so test_every_server_assigned_property_came_back_in_a_live_run
# (defined last in this module, so it collects after every parametrized case has
# run) can read it directly.
_SEEN_PROPERTIES: dict[str, set[str]] = defaultdict(set)

# SERVER_ASSIGNED (property, class) pairs this run cannot confirm the platform
# ever populates for that specific class, each for a reason specific to what
# this suite is able to provision -- dummy credentials and un-provisioned
# templates/sources, never a real cloud instance -- rather than a gap in the
# corpus or the CLI. Keyed by (property, class), never by property name alone:
# resource_models.SERVER_ASSIGNED_COVERAGE exists specifically because name-level
# exclusion silently swallowed AwsCapacityReservation.id/SourcesAllowance.
# provider/MachineImage.provider (see that module's own docstring) -- the same
# mistake here would let one class's confirmed absence excuse every other
# class sharing the property name, undetected. Every entry was seen, directly,
# to still be absent from that specific class's live response after this run
# created one -- listed individually, not derived from SERVER_ASSIGNED_COVERAGE's
# own class sets, so an exclusion here can never silently absorb a class that
# registry adds in future without this suite ever having re-verified it against
# that class specifically. test_read_gate_exclusions_are_evidenced (below)
# guards the *other* direction: that every key still names a real (property,
# class) pair SERVER_ASSIGNED_COVERAGE records, so a stale entry (the corpus
# stops creating the class, or that registry changes) cannot rot here
# unnoticed either.
#
# The tightened, per-class read gate (this task's own second pass, after
# review) found 66 such pairs -- large, and worth reading as a finding about
# the platform in its own right, not a weakness in the test: every compute
# source's own nested object (as opposed to the ComputeSourceTemplate wrapper
# around it, whose 'id' does come back -- see 'id' below) is far less
# observable through a bare create-then-show than the write gate's exclusion
# list alone would suggest.
#
# Six properties, each confirmed absent for all nine compute source classes
# source-templates.jsonnet creates. The *observation* is identical for all six; the
# reason text is not shared, because what can honestly be said beyond the
# observation differs per property. An earlier version gave all of them one
# "only ever populated once a compute source is actually provisioning real
# instances" reason, which was an argument dressed as an observation for at
# least two of them: 'createdFromId' is template lineage, fixed at creation and
# nothing to do with provisioning, and 'credentials' (a derived aggregate of
# 'credential') was not provisioning-related either -- it has since left the read
# gate altogether, having moved from SERVER_ASSIGNED_COVERAGE to
# resource_models.NOT_SETTABLE, which carries no read-gate obligation. Where
# only the observation is available, only the observation is recorded.
_NEVER_RETURNED_OBSERVATION = (
    "created live (source-templates.jsonnet exercises all nine compute source classes), "
    "but the platform never returned this property for this class"
)
_ONLY_WHEN_PROVISIONING = (
    f"{_NEVER_RETURNED_OBSERVATION} -- it reports the state of a source that is "
    "actually provisioning instances, which this suite's dummy AWS/Azure/GCP/OCI "
    "credentials (and the Simulator, in a template never attached to a live "
    "Compute Requirement) never do"
)
_OBSERVED_ABSENT_ONLY = (
    f"{_NEVER_RETURNED_OBSERVATION}; nothing beyond that observation is claimed here"
)
_COMPUTE_SOURCE_READ_GATE_REASONS: dict[str, str] = {
    # The three the "not provisioning anything" reason genuinely fits: each
    # describes a source's live provisioning state.
    "status": _ONLY_WHEN_PROVISIONING,
    "instanceSummary": _ONLY_WHEN_PROVISIONING,
    "exhaustion": _ONLY_WHEN_PROVISIONING,
    # A message qualifying 'status'. Plausibly the same reason as 'status'
    # itself, but that was never separately observed, so it is not asserted.
    "statusMessage": _OBSERVED_ABSENT_ONLY,
    # Template lineage, set when the source is created: the provisioning reason
    # above does not apply to it at all. Why the platform does not echo it for a
    # source nested in the very template it came from was not established.
    "createdFromId": (
        f"{_OBSERVED_ABSENT_ONLY} -- note that it is template lineage, set at "
        "creation, so the 'only while provisioning' reason given for status/"
        "instanceSummary/exhaustion demonstrably does not apply here"
    ),
    # The nested source object's own id, not the wrapper's: the enclosing
    # ComputeSourceTemplate's 'id' does come back (see 'id' in
    # resource_models.SERVER_ASSIGNED_COVERAGE, and the wrapper is not listed
    # here).
    "id": (
        f"{_OBSERVED_ABSENT_ONLY} -- this is the nested source object's own id; "
        "the enclosing ComputeSourceTemplate's 'id' is returned, and is not "
        "excluded here"
    ),
}
_ALL_NINE_COMPUTE_SOURCE_CLASSES = (
    "AwsFleetComputeSource",
    "AwsInstancesComputeSource",
    "AzureInstancesComputeSource",
    "AzureScaleSetComputeSource",
    "GceInstanceGroupComputeSource",
    "GceInstancesComputeSource",
    "OciInstancePoolComputeSource",
    "OciInstancesComputeSource",
    "SimulatorComputeSource",
)
READ_GATE_EXCLUSIONS: dict[tuple[str, str], str] = {
    (name, cls): reason
    for name, reason in _COMPUTE_SOURCE_READ_GATE_REASONS.items()
    for cls in _ALL_NINE_COMPUTE_SOURCE_CLASSES
}
READ_GATE_EXCLUSIONS.update(
    {
        # AwsFleetComputeSource.fleetId: addComputeSourceTemplate rejects it
        # outright at creation time (see source-templates.jsonnet's own comment) --
        # server-assigned, never author-settable, so there is no way for this
        # suite to ever send a value the platform would then need to echo.
        ("fleetId", "AwsFleetComputeSource"): (
            "creation itself is rejected (see source-templates.jsonnet's own comment on "
            "why the corpus no longer sets it) -- never even reaches a "
            "yd-show to be confirmed or not"
        ),
        # rootDeviceName: only ever populated from real AMI metadata once an
        # AWS instance actually launches, which this suite never does; the two
        # classes here are exactly resource_models._AWS_COMPUTE_SOURCE_CLASSES,
        # the only two that declare this field at all.
        ("rootDeviceName", "AwsFleetComputeSource"): (
            "only populated from real AMI metadata once an AWS instance "
            "actually launches, which this suite never does"
        ),
        ("rootDeviceName", "AwsInstancesComputeSource"): (
            "only populated from real AMI metadata once an AWS instance "
            "actually launches, which this suite never does"
        ),
        # provider/instancePricing on SimulatorComputeSource specifically --
        # confirmed live (Task 8, second pass): every other compute source
        # class returns both with real values (AWS/Azure/GCE/OCI templates all
        # echo 'provider'; AwsInstancesComputeSource also echoes
        # 'instancePricing') -- SimulatorComputeSource, not being a real cloud
        # provider at all, apparently has neither concept populated.
        ("provider", "SimulatorComputeSource"): (
            "confirmed absent for SimulatorComputeSource specifically -- every "
            "other compute source class returns a real 'provider' value; a "
            "simulated source has no real cloud provider to report"
        ),
        ("instancePricing", "SimulatorComputeSource"): (
            "confirmed absent for SimulatorComputeSource specifically -- "
            "AwsInstancesComputeSource, at least, returns a real value; a "
            "simulated source has no real pricing model to report"
        ),
        # supportingResourceCreated -- confirmed absent for exactly these seven
        # classes, live, by direct re-probe (Task 8, second pass): re-created
        # source-templates.jsonnet by hand and checked 'source.supportingResourceCreated'
        # in each yd-show response directly. OciInstancesComputeSource and
        # SimulatorComputeSource are deliberately NOT here: both return a real
        # boolean ('False' and 'True' respectively, confirmed the same way) --
        # a genuine, surprising difference from the other seven, including
        # their own close relatives (OciInstancePoolComputeSource does not
        # return it; OciInstancesComputeSource does).
        ("supportingResourceCreated", "AwsFleetComputeSource"): (
            "confirmed absent by direct re-probe; OciInstancesComputeSource "
            "and SimulatorComputeSource return a real boolean instead -- see "
            "this dict's own comment"
        ),
        ("supportingResourceCreated", "AwsInstancesComputeSource"): (
            "confirmed absent by direct re-probe; OciInstancesComputeSource "
            "and SimulatorComputeSource return a real boolean instead -- see "
            "this dict's own comment"
        ),
        ("supportingResourceCreated", "AzureInstancesComputeSource"): (
            "confirmed absent by direct re-probe; OciInstancesComputeSource "
            "and SimulatorComputeSource return a real boolean instead -- see "
            "this dict's own comment"
        ),
        ("supportingResourceCreated", "AzureScaleSetComputeSource"): (
            "confirmed absent by direct re-probe; OciInstancesComputeSource "
            "and SimulatorComputeSource return a real boolean instead -- see "
            "this dict's own comment"
        ),
        ("supportingResourceCreated", "GceInstanceGroupComputeSource"): (
            "confirmed absent by direct re-probe; OciInstancesComputeSource "
            "and SimulatorComputeSource return a real boolean instead -- see "
            "this dict's own comment"
        ),
        ("supportingResourceCreated", "GceInstancesComputeSource"): (
            "confirmed absent by direct re-probe; OciInstancesComputeSource "
            "and SimulatorComputeSource return a real boolean instead -- see "
            "this dict's own comment"
        ),
        ("supportingResourceCreated", "OciInstancePoolComputeSource"): (
            "confirmed absent by direct re-probe; its own close relative "
            "OciInstancesComputeSource returns a real boolean instead -- see "
            "this dict's own comment"
        ),
    }
)


def _identity(entity: dict) -> tuple[str, object] | None:
    """
    The (property, value) pair that names this specification or returned entity,
    in priority order: 'name' (most resource types -- nested under 'source' for a
    ComputeSourceTemplate, which has no top-level 'name' field of its own at all,
    checked directly against the installed SDK: only 'id'/'source'/'namespace'/
    'description'/'attributes'), 'description' (an Allowance has no 'name'
    property at all -- remove_allowance() itself already relies on 'description'
    for the same reason), then 'namespace' (a NamespacePolicy has neither, but is
    the only specification in its own corpus file, so matching on 'namespace'
    alone is unambiguous).
    """
    name = entity.get("name") or (entity.get("source") or {}).get("name")
    if name is not None:
        return ("name", name)
    if entity.get("description") is not None:
        return ("description", entity["description"])
    if entity.get("namespace") is not None:
        return ("namespace", entity["namespace"])
    return None


def _spec_for(specs: list[dict], returned: dict) -> dict | None:
    """Match a returned entity to the specification that created it (see
    _identity() for what each is matched on)."""
    identity = _identity(returned)
    if identity is None:
        return None
    for spec in specs:
        if _identity(spec) == identity:
            return resource_corpus.spec_properties(spec)
    return None


def _expected_creation_failures(corpus_file, run_id: str) -> set[tuple[str, str]]:
    """
    The identity (see _identity()) of every specification in this file that
    resource_live.KNOWN_PARTIAL_FAILURES already documents as unable to be
    created standalone -- empty for every other file.
    """
    suffixes = resource_live.KNOWN_PARTIAL_FAILURE_NAMES.get(
        corpus_file.name, frozenset()
    )
    return {("name", f"yd-test-{run_id}-{suffix}") for suffix in suffixes}


def _remove_args(corpus_file) -> list[str]:
    """
    Extra 'yd-remove' arguments a corpus file needs beyond '-y' and the shared
    '-c'/'-v run_id=...'. Only allowances.jsonnet needs one: '-M' (see
    remove.py's remove_allowance()) opts into matching Allowances by their
    'description' property, without which yd-remove only warns and does
    nothing for every Allowance in the file.
    """
    if corpus_file.name == "allowances.jsonnet":
        return ["-M"]
    return []


def _record_read_gate_evidence(entity_type: str, returned: dict) -> None:
    """
    Attribute every property name in 'returned' (one live response) to the
    concrete model class it belongs to, into _SEEN_PROPERTIES.

    Only the four entity types resource_models.SERVER_ASSIGNED_COVERAGE actually
    names a class for are worth walking -- every other entity_type is a no-op
    here, since nothing in SERVER_ASSIGNED_COVERAGE could ever cite a class it
    would produce. A ComputeSourceTemplate response carries two classes at once
    (see resource_models.py's own module docstring on why build_models() does the
    same): the wrapper's own top-level properties, and the nested source's,
    identified by the source's own fully-qualified 'type' (comparable() strips the
    'co.yellowdog.platform.model.' prefix, matching SERVER_ASSIGNED_COVERAGE's own
    bare class names). A ComputeRequirementTemplate/Allowance response instead
    carries its own 'type' at the top level. A MachineImageFamily response nests
    imageGroups/images inline (checked directly, Task 8) rather than as separate
    top-level entities, so this descends into both.
    """
    if entity_type == "compute-source-templates":
        _SEEN_PROPERTIES["ComputeSourceTemplate"].update(returned)
        source = returned.get("source")
        if isinstance(source, dict) and source.get("type"):
            source_class = resource_models.comparable(str(source["type"]))
            _SEEN_PROPERTIES[source_class].update(k for k in source if k != "type")
    elif entity_type in ("compute-requirement-templates", "allowances"):
        if returned.get("type"):
            model_class = resource_models.comparable(str(returned["type"]))
            _SEEN_PROPERTIES[model_class].update(k for k in returned if k != "type")
    elif entity_type == "image-families":
        _SEEN_PROPERTIES["MachineImageFamily"].update(returned)
        for group in returned.get("imageGroups") or []:
            _SEEN_PROPERTIES["MachineImageGroup"].update(group)
            for image in group.get("images") or []:
                _SEEN_PROPERTIES["MachineImage"].update(image)


@pytest.mark.system
@pytest.mark.parametrize(
    "corpus_file",
    [pytest.param(path, id=path.stem) for path in resource_corpus.live_corpus_files()],
)
def test_resource_lifecycle(corpus_file, live_namespace, run_id, cleanup):
    """
    Create every specification in one live corpus file, confirm each one round-trips
    through yd-show/yd-list with no property silently dropped or mangled, then remove
    everything and confirm removal.

    requirement-templates.jsonnet and configured-worker-pools.jsonnet are exactly the
    two files resource_live.KNOWN_PARTIAL_FAILURES documents as unable to create every
    one of their specifications standalone (create_compute_requirement_template()/
    create_configured_worker_pool() read 'namespace' with a bare KeyError check before
    any model is built). For those two, both 'yd-create' and 'yd-remove' are expected
    to exit non-zero -- create_resources()/remove_resources() (create.py/remove.py)
    each continue past one resource's failure and only raise (a single RuntimeError)
    once the whole file is done -- and this test demands the *specific* specifications
    named in resource_live.KNOWN_PARTIAL_FAILURE_NAMES are the ones missing, not merely
    that the exit code is non-zero: an unrelated regression elsewhere in the same file
    would otherwise hide behind the already-expected failure.

    applications.jsonnet's Application specifications name a Group and a Keyring by
    name (created by groups.jsonnet/keyrings.jsonnet respectively) to grant. Run here
    alone, neither exists: create_application() (create.py) warns and continues for
    the missing Group, and prints an error and continues for the missing Keyring --
    so this proves the CLI degrades gracefully when a named grant target is absent,
    but does *not* prove the grant itself succeeds when the target exists. 'groups'/
    'keyrings' are excluded from the round-trip comparison entirely (see
    resource_live.LIVE_ONLY_EXCLUSIONS) for exactly this reason: yd-show's own
    'groups' key is a live membership listing (empty here), not an echo of what was
    sent, and comparing it would fail for a reason that has nothing to do with
    whether the CLI transmitted anything correctly.
    """
    cleanup(
        resource_live.command_line(
            "yd-remove", "-y", *_remove_args(corpus_file), str(corpus_file)
        )
    )

    specs = resource_live.load_corpus_file(corpus_file)
    entity_types = {ENTITY_TYPE_FOR_RESOURCE[spec["resource"]] for spec in specs}
    before = {entity: resource_live.current_keys(entity) for entity in entity_types}

    known_partial_failure = corpus_file.name in resource_live.KNOWN_PARTIAL_FAILURES
    secret_emitting = corpus_file.name in resource_live.SECRET_EMITTING

    result = resource_live.yd("yd-create", str(corpus_file))
    if known_partial_failure:
        assert result.exit_code != 0, (
            f"{corpus_file.name} is documented (resource_live.KNOWN_PARTIAL_FAILURES) "
            "to partially fail creation, but yd-create exited 0"
        )
    else:
        assert result.exit_code == 0, f"yd-create {corpus_file.name} failed" + (
            "" if secret_emitting else f":\n{result.stdout}"
        )

    created: dict[str, set[str]] = {
        entity: resource_live.current_keys(entity) - before[entity]
        for entity in entity_types
    }
    # Fetched once per (entity, key) and reused below for both the missing-
    # identities check and the mismatches loop -- fetch() is a subprocess
    # ('yd-show', or a full 'yd-list --details' for a NO_YDID_ENTITY_TYPES
    # entity), so re-fetching each one a second time would double the
    # subprocess count (and the wall-clock time) of every live run for no
    # reason: the entity does not change between the two uses.
    returned_by_key: dict[tuple[str, str], dict] = {
        (entity, key): resource_live.fetch(entity, key)
        for entity, keys in created.items()
        for key in keys
    }

    sent_identities = {i for spec in specs if (i := _identity(spec)) is not None}
    created_identities = {
        i for entity in returned_by_key.values() if (i := _identity(entity)) is not None
    }
    missing_identities = sent_identities - created_identities
    expected_failures = _expected_creation_failures(corpus_file, run_id)
    if known_partial_failure:
        assert missing_identities == expected_failures, (
            f"{corpus_file.name}: expected exactly {sorted(expected_failures)} to "
            f"fail creation, but {sorted(missing_identities)} are missing"
        )
    else:
        assert not missing_identities, (
            f"{corpus_file.name}: every specification should have been created, but "
            f"{sorted(missing_identities)} are missing"
        )

    problems: list[str] = []
    for (entity, key), returned in returned_by_key.items():
        _record_read_gate_evidence(entity, returned)
        spec = _spec_for(specs, returned)
        if spec is not None:
            problems += [
                f"{entity}/{key}: {problem}"
                for problem in resource_live.mismatches(spec, returned)
            ]
    assert not problems, "the platform did not return what was sent:\n" + "\n".join(
        problems
    )

    result = resource_live.yd(
        "yd-remove", "-y", *_remove_args(corpus_file), str(corpus_file)
    )
    if known_partial_failure:
        assert result.exit_code != 0, (
            f"{corpus_file.name} is documented (resource_live.KNOWN_PARTIAL_FAILURES) "
            "to partially fail removal too (the same specifications that could never "
            "be created cannot be removed either), but yd-remove exited 0"
        )
    else:
        assert result.exit_code == 0, f"yd-remove {corpus_file.name} failed"

    for entity in entity_types:
        if entity == "worker-pools":
            # A Configured Worker Pool is never actually deleted: remove_
            # configured_worker_pool() (remove.py) shuts it down, and a
            # shut-down/terminated pool remains listed forever, the same
            # lifecycle shape as a finished Work Requirement -- a live-only
            # finding (Task 8). current_keys() can therefore never return to
            # 'before' for this entity type; the real invariant is that every
            # pool this test created has reached a finished status instead.
            for key in created[entity]:
                status = resource_live.fetch(entity, key).get("status")
                assert status in _FINISHED_WORKER_POOL_STATUSES, (
                    f"{entity}/{key}: expected a finished status after yd-remove, "
                    f"got {status!r}"
                )
            continue
        assert resource_live.current_keys(entity) == before[entity], (
            f"{entity} not fully removed after {corpus_file.name}"
        )


@pytest.mark.system
def test_every_server_assigned_property_came_back_in_a_live_run():
    """
    The read gate: every (property, class) pair resource_models.
    SERVER_ASSIGNED_COVERAGE records -- i.e. every class the write-side coverage
    gate excludes a property from, because the platform (not a specification)
    assigns it for that class -- must actually have been *seen* coming back from
    that specific class's live response somewhere in this session, via
    _record_read_gate_evidence() as test_resource_lifecycle went. Defined last in
    this module so normal pytest collection order (top-to-bottom, parametrized
    cases collected together before the next function) runs every
    test_resource_lifecycle case first -- if this test is ever run in isolation
    (e.g. 'pytest -k test_every_server_assigned'), _SEEN_PROPERTIES is empty and
    every non-excluded pair fails with "no corpus specification produced a live
    resource", which is misleading in exactly that one circumstance; running the
    whole module (as 'pytest --run-system tests/test_system_resources.py' always
    does) is what this test assumes.

    Checked per (property, class) pair, not per property name: a property
    evidenced for many classes (e.g. 'id', evidenced for twenty) is only
    confirmed for the classes that actually returned it, not for all twenty the
    moment any single one does -- the same per-class rigour
    SERVER_ASSIGNED_COVERAGE's own write-side entries already have, now applied
    to the read side too.

    Four outcomes per pair, not two, because an exclusion
    (READ_GATE_EXCLUSIONS) is itself a claim that needs its own evidence, in
    both directions:

    - no corpus specification ever produced a live resource of this class at all
      (nothing to blame the platform for -- the corpus needs to actually create
      one);
    - a live resource of this class was created and read back, but the property
      was still never present in what came back, and nothing excuses it (a
      genuine gap);
    - the same "created, never returned" outcome, but READ_GATE_EXCLUSIONS
      already names this exact pair with an evidenced reason -- which itself
      still requires the class to have been instantiated this run, or the
      exclusion is unconfirmed rather than confirmed;
    - the pair is excluded *and* the platform returned it anyway, which is
      reported as a failure too, naming the exclusion to delete. Without this
      last case an exclusion could never be retired: 'continue' on 'excluded'
      alone short-circuits before the "was it seen?" check, so a platform that
      starts returning a property would leave its waiver in place forever,
      quietly suppressing a check that had begun to pass. The failure is a
      request to delete a line, not a defect to fix -- worded that way in the
      message.
    """
    gaps: list[str] = []
    for name in sorted(resource_models.SERVER_ASSIGNED):
        classes = resource_models.SERVER_ASSIGNED_COVERAGE[name]
        for cls in sorted(classes):
            instantiated = cls in _SEEN_PROPERTIES
            excluded = (name, cls) in READ_GATE_EXCLUSIONS
            if not instantiated:
                gaps.append(
                    f"{name}/{cls}: no corpus specification produced a live "
                    "resource of this class"
                    + (
                        " (and it is listed in READ_GATE_EXCLUSIONS, but that "
                        "exclusion cannot be confirmed without one)"
                        if excluded
                        else ""
                    )
                )
                continue
            if excluded:
                if name in _SEEN_PROPERTIES[cls]:
                    gaps.append(
                        f"{name}/{cls}: READ_GATE_EXCLUSIONS waives this pair, "
                        "but the platform DID return it this run -- the "
                        "exclusion is stale; delete it (its recorded reason no "
                        "longer holds)"
                    )
                continue
            if name not in _SEEN_PROPERTIES[cls]:
                gaps.append(
                    f"{name}/{cls}: created live, but the platform never "
                    f"returned {name!r} for it"
                )

    assert not gaps, (
        "SERVER_ASSIGNED (property, class) pairs not settled by this live run "
        "(never confirmed, or waived by a READ_GATE_EXCLUSIONS entry that no "
        "longer holds):\n" + "\n".join(gaps)
    )


def test_read_gate_exclusions_are_evidenced():
    """
    Every READ_GATE_EXCLUSIONS key must name a (property, class) pair
    resource_models.SERVER_ASSIGNED_COVERAGE itself records -- mirrors
    test_resource_property_coverage.py's own guards on the write side
    (test_server_assigned_coverage_references_real_fields_of_in_scope_models and
    siblings), so an exclusion cannot rot into referencing a class the corpus no
    longer creates, a property no longer SERVER_ASSIGNED, or a pair that was
    never evidenced in the first place. Unlike test_every_server_assigned_
    property_came_back_in_a_live_run, this needs no live run at all -- it only
    checks the two registries against each other -- so it is not marked
    '@pytest.mark.system' and runs in the default suite too.
    """
    for name, cls in READ_GATE_EXCLUSIONS:
        assert name in resource_models.SERVER_ASSIGNED, (
            f"READ_GATE_EXCLUSIONS names {(name, cls)}, but {name!r} is not in "
            "resource_models.SERVER_ASSIGNED at all"
        )
        assert cls in resource_models.SERVER_ASSIGNED_COVERAGE.get(name, frozenset()), (
            f"READ_GATE_EXCLUSIONS names {(name, cls)}, but resource_models."
            f"SERVER_ASSIGNED_COVERAGE[{name!r}] does not evidence {cls!r}"
        )
