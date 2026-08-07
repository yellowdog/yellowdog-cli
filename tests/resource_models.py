"""
Which SDK model(s) the CLI builds for each resource type, and how a specification's
properties are checked against them.

Most types go through create.py's _get_model_object, but by different routes: some
take the class name from a 'type' property, one from 'source.type', one from
'credential.type', and a handful bypass model construction entirely with a direct
client call or constructor.

A ComputeSourceTemplate specification builds *two* models, not one: create.py
(create_compute_source_template, around line 268) builds the source first, then
passes it as a keyword to build the wrapper. The wrapper's own top-level properties
-- namespace, description, attributes -- are fields of ComputeSourceTemplate, not of
the source class (AwsInstancesComputeSource has none of them); comparing a whole
specification against a single model would let those three properties be dropped
without any test noticing, since there would be nothing to check them against.

MODEL_FOR_RESOURCE distinguishes two different reasons a value is not a real class
name, so extending it by pattern-matching can't conflate them:
  * None -- the CLI never builds a model for this type; it calls the client (or a
    plain constructor) directly. There is nothing to compare a specification's
    properties against except the plain dict itself.
  * DYNAMIC -- the class name is not fixed for the resource type: it is read out of
    the specification itself ('type', 'source.type', or 'credential.type'). Such a
    type does build one or more models; build_models() resolves the actual class
    name(s) per-resource.

StringAttributeDefinition/NumericAttributeDefinition are a special case:
create_attribute_definition() builds a raw payload dict and POSTs it directly --
there is no '_get_model_object("StringAttributeDefinition", ...)' call anywhere in
create.py. Building the SDK model here anyway is still a valid check because the
model's field names coincide with the payload's keys, but the mapping does not
reflect a real code path, unlike every other non-None, non-DYNAMIC entry.
"""

import dataclasses
import types
import typing

from yellowdog_cli.utils.load_resources import RESOURCE_SOURCE_DIR

# Sentinel distinguishing "resolved dynamically from the specification" from
# "no model is ever built" -- both would otherwise be spelled None.
DYNAMIC = "dynamic"

# resource type -> fixed model class name, None (no model object is ever built), or
# DYNAMIC (class name depends on the specification; see build_models()).
MODEL_FOR_RESOURCE: dict[str, str | None] = {
    "ComputeSourceTemplate": DYNAMIC,  # source's own 'source.type', plus the wrapper
    "ComputeRequirementTemplate": DYNAMIC,  # from the spec's own 'type'
    "MachineImageFamily": "MachineImageFamily",
    "Credential": DYNAMIC,  # from the spec's 'credential.type'
    "StringAttributeDefinition": "StringAttributeDefinition",  # field-name check only; see module docstring
    "NumericAttributeDefinition": "NumericAttributeDefinition",  # ditto
    "Allowance": DYNAMIC,  # from the spec's own 'type'
    "ConfiguredWorkerPool": "AddConfiguredWorkerPoolRequest",
    "Application": "AddApplicationRequest",
    # No model object: a direct client call or constructor
    "Keyring": None,  # add_keyring(name, description)
    "Namespace": None,  # CreateNamespaceRequest(namespace=...)
    "NamespacePolicy": None,  # NamespacePolicy(namespace, autoscalingMaxNodes)
    "Group": None,  # AddGroupRequest(name, description)
}


# Prefix on a fully-qualified SDK class name -- e.g. 'co.yellowdog.platform.model.
# AwsInstancesComputeSource'. Task 1's live probe found 'source.type' comes back
# from yd-show fully qualified even where a specification sent the short name
# ('AwsInstancesComputeSource'); comparable() strips exactly this prefix, and only
# this prefix, so an unrelated string that merely contains a dot (a hostname, a
# version number) is never touched.
_FULLY_QUALIFIED_PREFIX = "co.yellowdog.platform.model."


def _class_name_suffix(value: str) -> str:
    if value.startswith(_FULLY_QUALIFIED_PREFIX):
        return value.rsplit(".", 1)[-1]
    return value


@typing.overload
def comparable(value: str) -> str: ...


@typing.overload
def comparable(value: object) -> object: ...


def comparable(value: object) -> object:
    """
    Reduce a value to the JSON-compatible shape the SDK's own wire-serialisation
    step produces, so a property compares correctly regardless of which side of the
    wire it came from.

    Both a nested model object (e.g. a list of AttributeValue instances built from a
    plain list of dicts) and an SDK enum need this to compare equal to the plain
    value a specification wrote: every enum this SDK defines has name == value
    (checked directly against the installed SDK, not assumed), and Json.dump turns
    an enum instance back into that value string. Applying it to both sides of a
    comparison -- not just the model's -- also makes a raw datetime (as returned in
    the properties dict by build_models() for an Allowance's dates) comparable with
    the model's own millisecond-precision round trip through Json.dump/Json.load,
    which a direct '==' between the pre- and post-round-trip datetimes would fail on
    sub-millisecond precision alone.

    A string is also reduced to its class-name suffix if it is fully qualified (see
    _FULLY_QUALIFIED_PREFIX) -- needed by the live layer (resource_live.mismatches()),
    which compares a raw specification dict against yd-show's raw JSON directly,
    with no model construction step in between to have already stripped 'type' (the
    way build_models() does for the offline comparisons above). Harmless for the
    offline comparisons in this module: every 'type'-shaped field they compare is
    either popped before comparison (build_models()'s ComputeSourceTemplate/
    Credential/Allowance/ComputeRequirementTemplate branches) or already fully
    qualified on both sides of the comparison (e.g. strategyType), so stripping the
    same prefix from both sides changes nothing there.

    The 'str -> str' overload is not a second behaviour, just the type-level
    statement of the first branch below: a string reduces to a string. It is what
    lets the two callers that use the result as a *dict key* -- resource_live.
    _compare_dict()'s LIVE_ONLY_EXCLUSIONS_BY_CLASS lookup and test_system_
    resources._record_read_gate_evidence()'s _SEEN_PROPERTIES key, both of which
    pass a class name -- do so without a cast that would silently outlive a
    change to what this returns.
    """
    from yellowdog_client.common.json import Json

    if isinstance(value, str):
        return _class_name_suffix(value)
    if isinstance(value, (int, float, bool, type(None))):
        return value
    return Json.dump(value)


def build_models(resource: dict) -> list[tuple[object, dict]]:
    """
    Build every model object create.py constructs for this resource, each paired
    with the subset of the specification's properties that model owns.

    A list of pairs rather than a single model because ComputeSourceTemplate builds
    two (see module docstring); a flat type yields exactly one pair, and a type with
    no model at all (see MODEL_FOR_RESOURCE) yields none.

    A property with no model owner at all is simply absent from every pair, rather
    than compared against the wrong one: a Credential's 'keyringName' names the
    Keyring to add it to and is passed straight to put_credential_by_name() (see
    create_credential()), never becoming a field of the credential model.

    An Application's 'groups' and 'keyrings' are the same shape of bug as
    Credential's keyringName, and are scoped out the same way: create_application()
    (create.py:1108-1109) pops both before building AddApplicationRequest, which
    has only 'name'/'description' fields, because each drives a separate API call
    rather than being a field of the request itself -- 'groups' resolves group
    names to IDs to add/remove the Application's group membership, and 'keyrings'
    grants the Application access to the named Keyrings. The Application branch
    below pops both from the properties dict before building the model and before
    returning it, for the same reason the Credential branch excludes keyringName:
    neither belongs to any model, so leaving either in the pair's properties dict
    would compare it against a model that doesn't declare it.

    Raises whatever _get_model_object raises, which is the point: a missing
    required property fails the test rather than reaching the platform.
    """
    from yellowdog_cli.create import _get_model_object, date_parse

    resource_type = resource["resource"]
    properties = {
        k: v for k, v in resource.items() if k not in ("resource", RESOURCE_SOURCE_DIR)
    }

    if resource_type == "ComputeSourceTemplate":
        source_properties = dict(properties.pop("source"))
        source_type = source_properties.pop("type").split(".")[-1]
        source_model = _get_model_object(source_type, dict(source_properties))
        wrapper_model = _get_model_object(
            "ComputeSourceTemplate", dict(properties), source=source_model
        )
        # 'source' was popped above so _get_model_object never sees it as a raw
        # dict keyword (it is passed as the already-built source_model instead);
        # put it back into the *returned* properties, pointing at that same
        # source_model object, so the wrapper's own 'source' field is not
        # silently absent from every pair -- comparable() -- comparable(wrapper_
        # model.source) against comparable(source_model) -- trivially agrees,
        # since they are the identical object, but "trivially" is the fix: before
        # this, ComputeSourceTemplate.source could never appear in a coverage
        # pair at all, so no corpus file could ever close that gap.
        wrapper_properties = dict(properties, source=source_model)
        return [(source_model, source_properties), (wrapper_model, wrapper_properties)]

    if resource_type == "Credential":
        credential_properties = dict(properties["credential"])
        credential_type = credential_properties.pop("type").split(".")[-1]
        credential_model = _get_model_object(
            credential_type, dict(credential_properties)
        )
        return [(credential_model, credential_properties)]

    if resource_type == "Allowance":
        allowance_type = properties.pop("type").split(".")[-1]
        # create_allowance() parses natural-language dates ('Today', '31-Dec-2026')
        # with dateparser before building the model; without this, Json.load raises
        # trying to structure the raw string as an ISO datetime.
        #
        # The None check mirrors create_allowance()'s own (create.py: "Unable to
        # parse '<property>' date '<value>'"), and is not redundant: date_parse
        # returns None for a string it cannot parse, and without raising here an
        # unparseable date would flow into the model as None, come back out as
        # None, and compare equal to itself -- a corpus file with a garbled date
        # would pass every offline check while 'yd-create' rejected it. Diverging
        # from create.py by one behaviour is exactly how this module's earlier
        # defects worked.
        for date_property in ("effectiveFrom", "effectiveUntil"):
            raw_date = properties.get(date_property)
            if raw_date is not None:
                parsed_date = date_parse(raw_date)
                if parsed_date is None:
                    raise ValueError(
                        f"Unable to parse '{date_property}' date '{raw_date}'"
                    )
                properties[date_property] = parsed_date
        allowance_model = _get_model_object(allowance_type, dict(properties))
        return [(allowance_model, properties)]

    if resource_type == "ComputeRequirementTemplate":
        crt_type = properties.pop("type").split(".")[-1]
        crt_model = _get_model_object(crt_type, dict(properties))
        return [(crt_model, properties)]

    if resource_type == "Application":
        properties.pop("groups", None)
        properties.pop("keyrings", None)
        application_model = _get_model_object("AddApplicationRequest", dict(properties))
        return [(application_model, properties)]

    class_name = MODEL_FOR_RESOURCE[resource_type]
    if class_name is None:
        return []
    model_obj = _get_model_object(class_name, dict(properties))
    return [(model_obj, properties)]


# ---------------------------------------------------------------------------
# Coverage gate: which properties of which models the corpus must exercise.
# ---------------------------------------------------------------------------
#
# Every concrete SDK class a DYNAMIC entry in MODEL_FOR_RESOURCE can resolve to --
# the class names read from a specification's own 'type' / 'source.type' /
# 'credential.type' rather than looked up by resource type. Checked directly
# against the installed SDK (dataclasses.fields()/dataclasses.is_dataclass()), not
# assumed: in particular ComputeSourceTemplate itself belongs here too, since its
# resource type is DYNAMIC (see build_models()) even though the wrapper class name
# never varies -- omitting it would let namespace/description/attributes, the
# wrapper's own three properties, go unchecked forever. Likewise the concrete
# Credential subclasses (from 'credential.type') have no entry of their own in
# MODEL_FOR_RESOURCE at all, so they must be listed explicitly here or they would
# never appear in models_in_scope().
DYNAMIC_MODELS = {
    # ComputeSourceTemplate: the wrapper, plus every 'source.type' it can name
    "ComputeSourceTemplate",
    "AwsFleetComputeSource",
    "AwsInstancesComputeSource",
    "AzureInstancesComputeSource",
    "AzureScaleSetComputeSource",
    "GceInstanceGroupComputeSource",
    "GceInstancesComputeSource",
    "OciInstancePoolComputeSource",
    "OciInstancesComputeSource",
    "SimulatorComputeSource",
    # ComputeRequirementTemplate: from the spec's own 'type'
    "ComputeRequirementStaticTemplate",
    "ComputeRequirementDynamicTemplate",
    # Allowance: from the spec's own 'type'
    "AccountAllowance",
    "RequirementAllowance",
    "RequirementsAllowance",
    "SourceAllowance",
    "SourcesAllowance",
    # Credential: from the spec's 'credential.type'
    "AwsCredential",
    "AzureStorageCredential",
    "OciCredential",
    "AwsAccountRoleCredential",
    "AzureInstanceCredential",
    "AzureClientCredential",
    "GoogleCloudCredential",
}

# Every concrete compute source class: identical field declarations, checked
# directly against the installed SDK (dataclasses.fields()), not assumed. Only
# AwsInstancesComputeSource was actually probed live; the other eight are a
# recorded inference from that structural identity, not a probe of their own.
_COMPUTE_SOURCE_CLASSES = frozenset(
    {
        "AwsInstancesComputeSource",  # probed
        "AwsFleetComputeSource",  # identical declaration (verified)
        "AzureInstancesComputeSource",  # identical declaration (verified)
        "AzureScaleSetComputeSource",  # identical declaration (verified)
        "GceInstanceGroupComputeSource",  # identical declaration (verified)
        "GceInstancesComputeSource",  # identical declaration (verified)
        "OciInstancePoolComputeSource",  # identical declaration (verified)
        "OciInstancesComputeSource",  # identical declaration (verified)
        "SimulatorComputeSource",  # identical declaration (verified)
    }
)

# rootDeviceName exists only on the two AWS compute source classes -- GCE/Azure/
# OCI/Simulator sources don't declare it at all, so there is nothing to exclude
# there regardless.
_AWS_COMPUTE_SOURCE_CLASSES = frozenset(
    {"AwsInstancesComputeSource", "AwsFleetComputeSource"}
)

# Every concrete allowance class: identical field declarations, checked directly
# against the installed SDK. Only AccountAllowance was probed live.
_ALLOWANCE_CLASSES = frozenset(
    {
        "AccountAllowance",  # probed
        "RequirementAllowance",  # identical declaration (verified)
        "RequirementsAllowance",  # identical declaration (verified)
        "SourceAllowance",  # identical declaration (verified)
        "SourcesAllowance",  # identical declaration (verified)
    }
)

# For each property the platform assigns, the exact set of model classes that
# claim is evidenced for -- by a direct live probe, or (noted per class above)
# by a sibling verified via dataclasses.fields() to declare the field
# identically to a probed class. A class *not* listed for a given property is
# simply not excluded for it here, regardless of anything the SDK's own
# dataclass declares (see settable_properties()'s docstring for why that
# matters): the first version of this registry excluded a SERVER_ASSIGNED name
# from *any* class where the SDK happened to mark that field init=False, which
# silently covered seven class/property pairs -- ComputeSourceTemplate.id,
# ComputeRequirementStaticTemplate.id, ComputeRequirementDynamicTemplate.id,
# MachineImage.id/createdTime, MachineImageGroup.id/createdTime -- that had
# never actually been reasoned about, let alone probed. All seven are now
# either probed directly or a recorded, verified-identical inference; see
# task-4-report.md for the round of probe evidence that closed each one.
SERVER_ASSIGNED_COVERAGE: dict[str, frozenset[str]] = {
    # ComputeSourceTemplate's source (AwsInstancesComputeSource probed live):
    # addComputeSourceTemplate rejects a request with any of these set
    # ("must not contain a source with ... set" / "must be null"), and
    # 'provider'/'instancePricing'/'traits' were accepted but the value
    # returned did not match what was sent -- see task-4-report.md.
    #
    # 'credentials' was here too, on the evidence "sent a value, the raw model
    # came back None". That is the *same* evidence shape this registry rejects
    # for SimulatorComputeSource.userData/subregion below (accepted-then-dropped
    # is not "the platform assigns it"), so it has been moved to NOT_SETTABLE,
    # where its actual reason -- a derived aggregate of 'credential' that no
    # specification would ever author -- belongs. See NOT_SETTABLE.
    "status": _COMPUTE_SOURCE_CLASSES,
    "statusMessage": _COMPUTE_SOURCE_CLASSES,
    "createdFromId": _COMPUTE_SOURCE_CLASSES,
    "supportingResourceCreated": _COMPUTE_SOURCE_CLASSES,
    "instanceSummary": _COMPUTE_SOURCE_CLASSES,
    "exhaustion": _COMPUTE_SOURCE_CLASSES,
    "provider": _COMPUTE_SOURCE_CLASSES,
    "instancePricing": _COMPUTE_SOURCE_CLASSES,
    "traits": _COMPUTE_SOURCE_CLASSES,
    "rootDeviceName": _AWS_COMPUTE_SOURCE_CLASSES,
    # 'fleetId' (AwsFleetComputeSource probed live, Task 8): addComputeSourceTemplate
    # rejects it ("...source.fleetId must be null"). Declared init=False only on
    # this one compute source class -- unlike every property above, it is not
    # part of _COMPUTE_SOURCE_CLASSES's "identical declaration" (checked
    # directly: no other of the nine declares a 'fleetId' field at all), so it
    # gets its own single-class frozenset rather than reusing that shared one.
    "fleetId": frozenset({"AwsFleetComputeSource"}),
    # 'userData'/'subregion' on SimulatorComputeSource are deliberately NOT
    # here, despite being declared init=False the same way every property
    # above is: addComputeSourceTemplate *accepts* a SimulatorComputeSource
    # specifying either, and yd-show simply never echoes them afterwards
    # (probed live, Task 8). That is not evidence the platform assigns them --
    # a genuinely server-assigned property comes back (see 'provider'/
    # 'traits'/'id' above, all confirmed live by this same task) -- it is
    # evidence the platform accepts and then silently drops them, a candidate
    # platform bug. SERVER_ASSIGNED_COVERAGE's contract is "the platform
    # assigns this", not "this suite cannot verify it landed"; excluding a
    # name here also removes it from the write gate's demand permanently, with
    # no way to notice a future fix. Both stay in the corpus
    # (source-templates.jsonnet's simulatorMax) and are instead skipped by the *live*
    # comparison only, via resource_live.LIVE_ONLY_EXCLUSIONS_BY_CLASS, which
    # records the same observation without touching what the write gate demands.
    # Allowance (AccountAllowance probed live): addAllowance rejects a request
    # with any of these set ("must be null").
    "createdById": _ALLOWANCE_CLASSES,
    "remainingHours": _ALLOWANCE_CLASSES,
    # 'id': probed live on seven different classes, independently, because
    # 'id' recurs across unrelated resource families and cannot be assumed to
    # behave the same way on all of them (see settable_properties()'s
    # docstring for the AwsCapacityReservation/SourcesAllowance/MachineImage.
    # provider collisions this exact assumption produced for 'provider'). The
    # two shared frozensets carry their own per-class probed/verified
    # annotations where they are defined above (the compute source's own 'id'
    # was probed on AwsInstancesComputeSource, the allowance's on
    # AccountAllowance); the classes listed here are the resource families
    # neither set covers. ComputeRequirementDynamicTemplate is the one
    # inference among them, recorded as such: identical declaration to the
    # probed ComputeRequirementStaticTemplate (both 'type'/'id', checked
    # directly).
    "id": _COMPUTE_SOURCE_CLASSES
    | _ALLOWANCE_CLASSES
    | frozenset(
        {
            "ComputeSourceTemplate",  # probed (the wrapper's own id)
            "ComputeRequirementStaticTemplate",  # probed
            "ComputeRequirementDynamicTemplate",  # identical declaration (verified)
            "MachineImageFamily",  # probed
            "MachineImageGroup",  # probed
            "MachineImage",  # probed
        }
    ),
    # 'createdTime': probed live on all three -- MachineImageFamily directly,
    # MachineImageGroup and MachineImage in the same nested-family create.
    "createdTime": frozenset(
        {"MachineImageFamily", "MachineImageGroup", "MachineImage"}
    ),
}

# Every property name SERVER_ASSIGNED_COVERAGE has evidence for, for Task 8's
# read gate (asserting every one of these appears in some 'yd-show' response
# during a live run) to consume without re-deriving the set. This is the *write*
# gate's exclusion only; the read gate is Task 8's, not this module's.
SERVER_ASSIGNED: set[str] = set(SERVER_ASSIGNED_COVERAGE)

# Properties a model declares but the CLI's creation path can never populate from
# a specification for a reason *other* than "the platform assigns it"
# (SERVER_ASSIGNED covers that case, globally, above).
#
# 'credentials' is the one entry, on all nine compute source classes. It was
# previously in SERVER_ASSIGNED_COVERAGE on the evidence "a value was sent and
# the raw SDK model's field (fetched directly via compute_client, bypassing
# yd-show's rendering) came back None" -- but that is precisely the evidence
# shape that was *rejected* for SimulatorComputeSource.userData/subregion, on
# the ruling that accepted-then-dropped is not the same claim as
# server-assigned. What actually disqualifies it is a different, stronger fact,
# checked directly against the installed SDK: alongside the plural, init=False
# 'credentials: Set[str] | None', every one of these classes declares a
# singular, required, author-settable 'credential: str' -- which the corpus does
# set, on every source. The plural is the derived aggregate of the singular; no
# specification would ever author it, and a specification that tried would be
# authoring the same fact twice in two shapes. That is exactly what this
# registry is for, and unlike SERVER_ASSIGNED_COVERAGE it carries no read-gate
# obligation (test_system_resources.py's read gate reads SERVER_ASSIGNED only),
# so the move also retires nine READ_GATE_EXCLUSIONS entries that were waiving a
# demand nothing should have made in the first place.
_CREDENTIALS_IS_A_DERIVED_AGGREGATE = (
    "the plural, init=False aggregate of the singular, required, author-settable "
    "'credential: str' this class also declares (checked directly against the "
    "installed SDK) -- the corpus sets 'credential' on every source, and no "
    "specification would author the derived set as well; not in "
    "SERVER_ASSIGNED_COVERAGE because 'a value was sent and None came back' is "
    "the accepted-then-dropped evidence shape that registry rejects, not "
    "evidence the platform assigns the property"
)
NOT_SETTABLE: dict[str, dict[str, str]] = {
    class_name: {"credentials": _CREDENTIALS_IS_A_DERIVED_AGGREGATE}
    for class_name in sorted(_COMPUTE_SOURCE_CLASSES)
}

# Properties deliberately left uncovered for a reason other than "the CLI's
# creation path cannot populate them" (that's SERVER_ASSIGNED/NOT_SETTABLE). "*"
# applies to every model regardless of name -- needed here because 'type' is a
# real field of 23 different classes (9 compute sources, 2
# compute-requirement-template types, 5 allowance types, 7 credential types), and
# repeating the same entry 23 times would obscure that it's one rule, not 23
# independent judgement calls.
NOT_TESTED: dict[str, dict[str, str]] = {
    "*": {
        "type": "the polymorphic discriminator; build_models() pops it from the "
        "specification before the model is ever constructed (see its "
        "ComputeSourceTemplate/Credential/Allowance/ComputeRequirementTemplate "
        "branches), exactly mirroring create_credential()/create_allowance()/"
        "create_compute_requirement_template() popping the same key from the "
        "real resource dict before calling _get_model_object themselves -- no "
        "pair's properties dict can ever carry it",
    },
}


def _model_class(model_name: str) -> type:
    from yellowdog_cli.create import _get_model_class

    return _get_model_class(model_name)


def _as_dataclass_type(candidate: object) -> type | None:
    """
    candidate if it is itself a dataclass *class* (not instance), else None.

    dataclasses.is_dataclass() accepts and narrows to either an instance or a
    class, which is_dataclass() alone can't tell pyright apart; the isinstance()
    check first is what lets this return a plain 'type' rather than that union.
    """
    if isinstance(candidate, type) and dataclasses.is_dataclass(candidate):
        return candidate
    return None


def _nested_model_class(annotation: object) -> type | None:
    """
    Unwrap a dataclass field's declared type to the dataclass model it names, or
    None if the field holds a plain value (str, an enum, Dict[str, str], ...).

    Handles Optional/list wrapping in any combination and either spelling: the
    installed SDK mixes 'X | None' with 'Optional[X]'/'Union[X, None]', and plain
    generics ('List[X]') with PEP 585 ones ('list[X]'), so unwrapping only one
    spelling would silently stop descending on the other.
    """
    origin = typing.get_origin(annotation)
    if origin in (list, set, frozenset):
        args = typing.get_args(annotation)
        return _nested_model_class(args[0]) if args else None
    if origin in (types.UnionType, typing.Union):
        for arg in typing.get_args(annotation):
            if arg is not type(None):
                found = _nested_model_class(arg)
                if found is not None:
                    return found
        return None
    if origin is not None:
        found = _as_dataclass_type(origin)
        if found is not None:
            return found
    return _as_dataclass_type(annotation)


def _nested_settable_models(cls: type) -> set[type]:
    """
    Every dataclass model named by one of cls's own settable fields.

    Follows settable_properties(cls.__name__) -- this module's own, evidence-based
    judgement of what a specification can populate -- rather than field.init:
    field.init is not evidence of specification-level settability (see
    settable_properties()'s docstring), so filtering reachability by it would
    reintroduce the exact mistake SERVER_ASSIGNED now fixes on purpose, just one
    layer removed. A field this module has excluded on live-probed evidence
    (instanceSummary, exhaustion) correctly stops the walk from pulling its type
    into scope; a field left in the gate because no evidence excludes it is
    still followed, since a specification can genuinely author a dict there for
    record_covered_properties() to recurse into.
    """
    settable = settable_properties(cls.__name__)
    return {
        nested
        for field in dataclasses.fields(cls)
        if field.name in settable
        for nested in (_nested_model_class(field.type),)
        if nested is not None
    }


def _reachable_models(roots: set[str], max_depth: int = 4) -> set[str]:
    """
    Follow every settable dataclass-typed field outward from each root model -- an
    image group inside a family, spot options inside a compute source, a source
    usage inside a static template -- to every model the corpus must also cover.

    Uses the same field-type reflection record_covered_properties() walks a
    specification with, so scope and coverage can never drift apart: whatever the
    recorder could descend into, this has already counted as in scope.

    Depth-capped (an image family -> image group -> image chain is 3 deep already;
    the margin covers one more layer added by a future SDK revision) and
    visited-set-guarded, so a self-referential annotation cannot loop forever
    either way.
    """
    reached: set[type] = set()
    frontier = {_model_class(name) for name in roots}
    depth = 0
    while frontier and depth <= max_depth:
        next_frontier: set[type] = set()
        for cls in frontier:
            if cls in reached:
                continue
            reached.add(cls)
            next_frontier |= _nested_settable_models(cls)
        frontier = next_frontier
        depth += 1
    return {cls.__name__ for cls in reached}


def models_in_scope() -> set[str]:
    """
    Every model class name the corpus must cover: every fixed value of
    MODEL_FOR_RESOURCE, every concrete class a DYNAMIC entry can resolve to
    (DYNAMIC_MODELS), and every model reachable from those by following nested
    dataclass-typed fields.
    """
    fixed = {
        name for name in MODEL_FOR_RESOURCE.values() if name not in (None, DYNAMIC)
    }
    return _reachable_models(fixed | DYNAMIC_MODELS)


def settable_properties(model_name: str) -> set[str]:
    """
    Every property of the model a specification could set.

    Starts from *every* dataclass field, not just the init=True ones: field.init
    is not evidence of what a specification can populate, mechanically or
    otherwise -- build_models() builds every model through
    _get_model_object()'s Json.load(), and the SDK's own Json.structure_json() is
    registered with _cattrs_include_init_false=True (see
    yellowdog_client/common/json/__init__.py), so an init=False field is
    constructed from whatever value a specification supplies just like any
    other. NOT_SETTABLE/NOT_TESTED (evidenced per entry, cited in the module
    docstring or comments) remove a property here -- never a dataclass metadata
    flag, and never an argument from a docstring's tone: 'traits' and
    'instancePricing' read exactly as read-oriented as the properties that
    turned out to be genuinely server-assigned, and only a live create-then-show
    round trip told them apart.

    A SERVER_ASSIGNED name is excluded here *only* for the exact classes listed
    against it in SERVER_ASSIGNED_COVERAGE -- never for a class merely because
    the SDK happens to declare that field init=False there too. That distinction
    is load-bearing, not cosmetic: this module's own first cut at this scoping
    used "any class where the field is init=False", which is what let
    AwsCapacityReservation.id, SourcesAllowance.provider, and MachineImage.
    provider (all plain, author-settable fields on classes nobody had reasoned
    about) get silently excluded alongside the classes that were actually
    probed. Fixing that the same way again -- inferring instead of recording --
    would have covered those three cases and reintroduced the identical bug for
    any other unprobed class, in either direction: a class that happens to
    share both the property name *and* the init=False declaration would still
    be swept in on no evidence of its own. SERVER_ASSIGNED_COVERAGE is the fix
    that generalises to neither direction: only a class explicitly recorded
    there -- because it was itself probed, or because it was checked directly
    against a probed sibling's identical field declaration and that check is
    recorded in a comment -- is ever excluded.
    """
    fields = {f.name for f in dataclasses.fields(_model_class(model_name))}
    excluded = {
        name
        for name, evidenced_for in SERVER_ASSIGNED_COVERAGE.items()
        if model_name in evidenced_for
    }
    excluded |= set(NOT_SETTABLE.get(model_name, {}))
    excluded |= set(NOT_TESTED.get(model_name, {}))
    excluded |= set(NOT_TESTED.get("*", {}))
    return fields - excluded


def record_covered_properties(resource: dict, covered: dict[str, set[str]]) -> None:
    """
    Record which properties of which models this specification sets.

    Builds on build_models() rather than re-deriving which properties belong to
    which model -- ComputeSourceTemplate's two pairs, Credential's keyringName
    exclusion, Allowance's parsed dates all already live in one place there.
    Then follows the same nested-field walk models_in_scope() uses to reach
    nested models (an image group inside a family, spot options inside a compute
    source, a source usage inside a static template), so a nested dict is
    recorded against its own model, not only against its container's.
    """
    for model, properties in build_models(resource):
        _record_properties(type(model), properties, covered, depth=0)


def _record_properties(
    cls: type, properties: dict, covered: dict[str, set[str]], depth: int
) -> None:
    covered[cls.__name__].update(properties)
    if depth >= 4:
        return
    settable = settable_properties(cls.__name__)
    for field in dataclasses.fields(cls):
        if field.name not in settable:
            continue
        nested_cls = _nested_model_class(field.type)
        if nested_cls is None:
            continue
        value = properties.get(field.name)
        if value is None:
            continue
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, dict):
                _record_properties(nested_cls, item, covered, depth + 1)
