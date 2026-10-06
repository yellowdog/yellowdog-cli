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

The SDK-model knowledge this gate shares with the specification schemas -- which
model each resource type builds (MODEL_FOR_RESOURCE, DYNAMIC, DYNAMIC_MODELS), the
evidenced exclusions (SERVER_ASSIGNED_COVERAGE, NOT_SETTABLE, NOT_TESTED) and
settable_properties() -- now lives in yellowdog_cli/utils/specs/sdk_models.py, with the
reasoning behind each registry. It is re-exported here under its old names, so
the corpus tests keep reading it from this module; the registries are the same
objects, so a test mutating one here mutates what settable_properties() reads.
What stays here is what only the corpus gate uses: build_models(), comparable(),
the nested-model walk behind models_in_scope(), and record_covered_properties().
"""

import dataclasses
import typing

from yellowdog_cli.utils.load_resources import RESOURCE_SOURCE_DIR
from yellowdog_cli.utils.specs import sdk_models

DYNAMIC = sdk_models.DYNAMIC
MODEL_FOR_RESOURCE = sdk_models.MODEL_FOR_RESOURCE
DYNAMIC_MODELS = sdk_models.DYNAMIC_MODELS
SERVER_ASSIGNED_COVERAGE = sdk_models.SERVER_ASSIGNED_COVERAGE
NOT_SETTABLE = sdk_models.NOT_SETTABLE
NOT_TESTED = sdk_models.NOT_TESTED
settable_properties = sdk_models.settable_properties
_model_class = sdk_models.model_class
_nested_model_class = sdk_models.nested_model_class

# Prefix on a fully-qualified SDK class name -- e.g. 'co.yellowdog.platform.model.
# AwsInstancesComputeSource'. A live probe found 'source.type' comes back
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
    from yellowdog_cli.utils.resource_creation import _get_model_object, date_parse

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

# Every property name SERVER_ASSIGNED_COVERAGE has evidence for, for the live
# read gate in test_system_resources.py (asserting every one of these appears
# in some 'yd-show' response during a live run) to consume without re-deriving
# the set. This is the *write* gate's exclusion only; the read gate is
# test_system_resources.py's, not this module's.
SERVER_ASSIGNED: set[str] = set(SERVER_ASSIGNED_COVERAGE)


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
