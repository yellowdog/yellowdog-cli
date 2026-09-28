"""
The SDK-model knowledge the specification corpus's coverage gate
(tests/resource_models.py) and the specification schemas share: which SDK
model(s) the CLI builds for each resource type, the concrete classes each
polymorphic base resolves to, and which properties of a model a specification
can set and which it must.

Every registry here is evidence-based, not inferred from the SDK's dataclass
metadata: the comments beside each record the live probe or the direct check
against the installed SDK that justifies it. See CLAUDE.md's "Resource
Specification Test Corpus" section for the gate that holds them to account.

MODEL_FOR_RESOURCE distinguishes two different reasons a value is not a real class
name, so extending it by pattern-matching can't conflate them:
  * None -- the CLI never builds a model for this type; it calls the client (or a
    plain constructor) directly. There is nothing to compare a specification's
    properties against except the plain dict itself.
  * DYNAMIC -- the class name is not fixed for the resource type: it is read out of
    the specification itself ('type', 'source.type', or 'credential.type'). Such a
    type does build one or more models; tests/resource_models.py's build_models()
    resolves the actual class name(s) per-resource.

StringAttributeDefinition/NumericAttributeDefinition are a special case:
create_attribute_definition() builds a raw payload dict and POSTs it directly --
there is no '_get_model_object("StringAttributeDefinition", ...)' call anywhere in
create.py. Building the SDK model anyway is still a valid check because the
model's field names coincide with the payload's keys, but the mapping does not
reflect a real code path, unlike every other non-None, non-DYNAMIC entry.

This module must not import create.py, which imports wrapper.py and so builds a
Platform client at import: model_class() resolves through yellowdog_client.model
directly, which is all create._get_model_class() does.
"""

import dataclasses
import types
import typing

from yellowdog_client import model

# Sentinel distinguishing "resolved dynamically from the specification" from
# "no model is ever built" -- both would otherwise be spelled None.
DYNAMIC = "dynamic"

# resource type -> fixed model class name, None (no model object is ever built), or
# DYNAMIC (class name depends on the specification; see tests/resource_models.py's build_models()).
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

# ---------------------------------------------------------------------------
# Which properties of which models a specification can set.
# ---------------------------------------------------------------------------
#
# Every concrete SDK class a DYNAMIC entry in MODEL_FOR_RESOURCE can resolve to --
# the class names read from a specification's own 'type' / 'source.type' /
# 'credential.type' rather than looked up by resource type. Checked directly
# against the installed SDK (dataclasses.fields()/dataclasses.is_dataclass()), not
# assumed: in particular ComputeSourceTemplate itself belongs here too, since its
# resource type is DYNAMIC (see tests/resource_models.py's build_models()) even though the wrapper class name
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
COMPUTE_SOURCE_CLASSES = frozenset(
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
AWS_COMPUTE_SOURCE_CLASSES = frozenset(
    {"AwsInstancesComputeSource", "AwsFleetComputeSource"}
)

# Every concrete allowance class: identical field declarations, checked directly
# against the installed SDK. Only AccountAllowance was probed live.
ALLOWANCE_CLASSES = frozenset(
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
    "status": COMPUTE_SOURCE_CLASSES,
    "statusMessage": COMPUTE_SOURCE_CLASSES,
    "createdFromId": COMPUTE_SOURCE_CLASSES,
    "supportingResourceCreated": COMPUTE_SOURCE_CLASSES,
    "instanceSummary": COMPUTE_SOURCE_CLASSES,
    "exhaustion": COMPUTE_SOURCE_CLASSES,
    "provider": COMPUTE_SOURCE_CLASSES,
    "instancePricing": COMPUTE_SOURCE_CLASSES,
    "traits": COMPUTE_SOURCE_CLASSES,
    "rootDeviceName": AWS_COMPUTE_SOURCE_CLASSES,
    # 'fleetId' (AwsFleetComputeSource probed live, Task 8): addComputeSourceTemplate
    # rejects it ("...source.fleetId must be null"). Declared init=False only on
    # this one compute source class -- unlike every property above, it is not
    # part of COMPUTE_SOURCE_CLASSES's "identical declaration" (checked
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
    "createdById": ALLOWANCE_CLASSES,
    "remainingHours": ALLOWANCE_CLASSES,
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
    "id": COMPUTE_SOURCE_CLASSES
    | ALLOWANCE_CLASSES
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

# Properties a model declares but the CLI's creation path can never populate from
# a specification for a reason *other* than "the platform assigns it"
# (SERVER_ASSIGNED_COVERAGE covers that case, per class, above).
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
# obligation (test_system_resources.py's read gate reads SERVER_ASSIGNED, the
# set of SERVER_ASSIGNED_COVERAGE's names in tests/resource_models.py, only),
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
    for class_name in sorted(COMPUTE_SOURCE_CLASSES)
}

# Properties deliberately left uncovered for a reason other than "the CLI's
# creation path cannot populate them" (that's SERVER_ASSIGNED_COVERAGE/NOT_SETTABLE). "*"
# applies to every model regardless of name -- needed here because 'type' is a
# real field of 23 different classes (9 compute sources, 2
# compute-requirement-template types, 5 allowance types, 7 credential types), and
# repeating the same entry 23 times would obscure that it's one rule, not 23
# independent judgement calls.
NOT_TESTED: dict[str, dict[str, str]] = {
    "*": {
        "type": "the polymorphic discriminator; tests/resource_models.py's build_models() pops it from the "
        "specification before the model is ever constructed (see its "
        "ComputeSourceTemplate/Credential/Allowance/ComputeRequirementTemplate "
        "branches), exactly mirroring create_credential()/create_allowance()/"
        "create_compute_requirement_template() popping the same key from the "
        "real resource dict before calling _get_model_object themselves -- no "
        "pair's properties dict can ever carry it",
    },
}


# The concrete classes each polymorphic base resolves to, by the discriminator
# each specification writes: a Compute Source Template's 'source.type', a
# Compute Requirement Template's or an Allowance's 'type', a Credential's
# 'credential.type'. Built from the sets above, so the two cannot disagree.
POLYMORPHIC_FAMILIES: dict[str, frozenset[str]] = {
    "ComputeSource": COMPUTE_SOURCE_CLASSES,
    "ComputeRequirementTemplate": frozenset(
        {"ComputeRequirementStaticTemplate", "ComputeRequirementDynamicTemplate"}
    ),
    "Allowance": ALLOWANCE_CLASSES,
    "Credential": frozenset(
        {
            "AwsCredential",
            "AzureStorageCredential",
            "OciCredential",
            "AwsAccountRoleCredential",
            "AzureInstanceCredential",
            "AzureClientCredential",
            "GoogleCloudCredential",
        }
    ),
    "NodeAction": frozenset(
        {"NodeRunCommandAction", "NodeWriteFileAction", "NodeCreateWorkersAction"}
    ),
}

# The resource types yd-create accepts (create_resources()'s dispatch), in the
# order the README's Resource Specification Definitions section lists them
RESOURCE_TYPES: tuple[str, ...] = (
    "ComputeSourceTemplate",
    "ComputeRequirementTemplate",
    "Keyring",
    "Credential",
    "MachineImageFamily",
    "ConfiguredWorkerPool",
    "Allowance",
    "StringAttributeDefinition",
    "NumericAttributeDefinition",
    "NamespacePolicy",
    "Group",
    "Application",
    "InternalUser",
    "ExternalUser",
    "Namespace",
)


def model_class(model_name: str) -> type:
    """
    The SDK model class of this name, resolved as create._get_model_class()
    resolves it, without importing create.py (see the module docstring).
    """
    return getattr(model, model_name)


def as_dataclass_type(candidate: object) -> type | None:
    """
    candidate if it is itself a dataclass *class* (not instance), else None.

    dataclasses.is_dataclass() accepts and narrows to either an instance or a
    class, which is_dataclass() alone can't tell pyright apart; the isinstance()
    check first is what lets this return a plain 'type' rather than that union.
    """
    if isinstance(candidate, type) and dataclasses.is_dataclass(candidate):
        return candidate
    return None


def nested_model_class(annotation: object) -> type | None:
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
        return nested_model_class(args[0]) if args else None
    if origin in (types.UnionType, typing.Union):
        for arg in typing.get_args(annotation):
            if arg is not type(None):
                found = nested_model_class(arg)
                if found is not None:
                    return found
        return None
    if origin is not None:
        found = as_dataclass_type(origin)
        if found is not None:
            return found
    return as_dataclass_type(annotation)


def settable_properties(model_name: str) -> set[str]:
    """
    Every property of the model a specification could set.

    Starts from *every* dataclass field, not just the init=True ones: field.init
    is not evidence of what a specification can populate, mechanically or
    otherwise -- tests/resource_models.py's build_models() builds every model through
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
    fields = {f.name for f in dataclasses.fields(model_class(model_name))}
    excluded = {
        name
        for name, evidenced_for in SERVER_ASSIGNED_COVERAGE.items()
        if model_name in evidenced_for
    }
    excluded |= set(NOT_SETTABLE.get(model_name, {}))
    excluded |= set(NOT_TESTED.get(model_name, {}))
    excluded |= set(NOT_TESTED.get("*", {}))
    return fields - excluded


def required_properties(model_name: str) -> set[str]:
    """
    The properties a specification must give: the fields with no default and
    no default factory, less those settable_properties() excludes.
    """
    cls = model_class(model_name)
    required = {
        f.name
        for f in dataclasses.fields(cls)
        if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
    }
    return required & settable_properties(model_name)
