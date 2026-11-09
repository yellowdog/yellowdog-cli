"""
The exporters of 'yd resource export': one per type of resource, each finding
the resources of its type in a selection and writing one out as a
specification. EXPORTERS is keyed by the type word and filled in as each
type's exporter is written; the engine (utils/resource_export.py) knows only
this interface.

A specification is what 'yd resource plan' compares (comparable()), less a
property holding its Platform default, with every reference to another
resource written as its name, and every '{{...}}' in a string written so
that loading the file gives the string back (specification_of(),
literal_for_jsonnet()).
"""

import json
import logging
import re
from collections import Counter
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, fields
from fnmatch import fnmatchcase
from typing import Any, cast

from yellowdog_client.model import (
    Allowance,
    AllowanceSearch,
    Application,
    ComputeRequirementTemplateSearch,
    ComputeSourceTemplateSearch,
    ExternalUser,
    Group,
    GroupRole,
    GroupSummary,
    ImageAccess,
    InternalUser,
    Keyring,
    KeyringCredential,
    KeyringSearch,
    KeyringSummary,
    MachineImageFamilySearch,
    NamespacePolicy,
    NamespaceSearch,
    RequirementAllowance,
    RequirementsAllowance,
    SourceAllowance,
    SourcesAllowance,
    User,
)

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    ET_ALLOWANCES,
    ET_APPLICATIONS,
    ET_ATTRIBUTE_DEFINITIONS,
    ET_COMPUTE_REQUIREMENT_TEMPLATES,
    ET_COMPUTE_SOURCE_TEMPLATES,
    ET_CONFIGURED_WORKER_POOLS,
    ET_CREDENTIALS,
    ET_GROUPS,
    ET_IMAGE_FAMILIES,
    ET_KEYRINGS,
    ET_NAMESPACE_POLICIES,
    ET_NAMESPACES,
    ET_USERS,
    RN_ALLOWANCE,
    RN_APPLICATION,
    RN_CONFIGURED_POOL,
    RN_CREDENTIAL,
    RN_EXTERNAL_USER,
    RN_GROUP,
    RN_IMAGE_FAMILY,
    RN_INTERNAL_USER,
    RN_KEYRING,
    RN_NAMESPACE,
    RN_NAMESPACE_POLICY,
    RN_NUMERIC_ATTRIBUTE_DEFINITION,
    RN_REQUIREMENT_TEMPLATE,
    RN_SOURCE_TEMPLATE,
    RN_STRING_ATTRIBUTE_DEFINITION,
)
from yellowdog_cli.utils.entity_utils import (
    filter_summaries_by_name_glob,
    get_all_applications,
    get_all_groups,
    get_all_users,
    get_application_group_summaries,
    get_application_keyrings,
    get_user_attribute_definitions,
    get_user_groups,
    get_worker_pool_summaries,
    search_namespaces,
    substitute_id_for_name_in_allowance,
    substitute_ids_for_names_in_crt,
    substitute_image_family_id_for_name_in_cst,
)
from yellowdog_cli.utils.exit_codes import SESSION_FAILURES, ExitCode, classify
from yellowdog_cli.utils.glob_utils import glob_search_prefix
from yellowdog_cli.utils.misc_utils import (
    find_delimited_expression_spans,
    is_http_not_found,
)
from yellowdog_cli.utils.noun_registry import EXPORT_TYPES
from yellowdog_cli.utils.printing import plural
from yellowdog_cli.utils.property_names import (
    PROP_AUTOSCALING_MAX_NODES,
    PROP_CREDENTIAL,
    PROP_CST_ID,
    PROP_DEFAULT_RANK_ORDER,
    PROP_DESCRIPTION,
    PROP_GLOBAL,
    PROP_GROUPS,
    PROP_ID,
    PROP_IMAGE,
    PROP_IMAGE_ID,
    PROP_IMAGES_ID,
    PROP_KEYRING_NAME,
    PROP_NAME,
    PROP_NAMESPACE,
    PROP_NAMESPACES,
    PROP_OPTIONS,
    PROP_RANGE,
    PROP_REQUIREMENT_CREATED_FROM,
    PROP_RESOURCE,
    PROP_ROLE,
    PROP_ROLES,
    PROP_SCOPE,
    PROP_SOURCE_CREATED_FROM,
    PROP_SOURCES,
    PROP_TITLE,
    PROP_TYPE,
    PROP_UNITS,
    PROP_USERNAME,
)
from yellowdog_cli.utils.resource_plan import (
    RESOURCE_TYPE_NAMES,
    comparable,
    differences,
    path_pattern,
    platform_defaults,
)
from yellowdog_cli.utils.settings import (
    NAMESPACE_PREFIX_SEPARATOR,
    USER_ATTRIBUTE_PREFIX,
)
from yellowdog_cli.utils.specs.sdk_models import model_class, required_properties
from yellowdog_cli.utils.variable_substitution import PLATFORM_MUSTACHE_PROPERTIES
from yellowdog_cli.utils.variable_syntax import (
    RAW_PREFIX,
    VAR_CLOSING_DELIMITER,
    VAR_OPENING_DELIMITER,
    WP_VARIABLES_POSTFIX,
    WP_VARIABLES_PREFIX,
)
from yellowdog_cli.utils.ydid_utils import get_ydid_type

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class Selection:
    """
    What an export is asked for: the namespace and the name glob.
    """

    namespace: str | None  # the configured or -n namespace; None for account-wide types
    name_glob: str | None  # --name


@dataclass(frozen=True)
class Found:
    """
    A resource an exporter found, not yet fetched in full.
    """

    resource_type: str  # an RN_* name: what 'resource' will be
    name: str  # as create names it: 'namespace/name' for namespaced types
    key: Any  # what export() fetches it by (an ID, a summary, a payload)


@dataclass(frozen=True)
class Reference:
    """
    A resource another refers to, which --with-dependencies exports too,
    unless its exporter says it is not followed (a public Image Family).
    """

    export_type: str  # an EXPORTERS key: 'compute-source-templates'
    name: str  # as Found.name spells it


@dataclass(frozen=True)
class Exported:
    """
    One resource written out: its specification and what it refers to.
    """

    specification: dict  # 'resource' first, then the properties
    references: tuple[Reference, ...] = ()
    notes: tuple[str, ...] = ()  # warnings: an unnamed reference, grants, variables


@dataclass(frozen=True)
class Exporter:
    """
    How one type of resource is found and written out.
    """

    namespaced: bool
    find: Callable[[RunContext, Selection], list[Found]]
    export: Callable[[RunContext, Found], Exported]
    # The RN_* name of what it exports, where that is one type: what a
    # reference to one that could not be looked up is recorded as
    resource_type: str | None = None
    # Whether a reference to a resource of the name given is followed, asked
    # only under '--with-dependencies', once per name; None follows each one
    followed: Callable[[RunContext, str], bool] | None = None


# Keyed by the type word
EXPORTERS: dict[str, Exporter] = {}

# What an export with no type and no --all writes, in EXPORT_TYPES order
DEFAULT_TYPES: tuple[str, ...] = tuple(
    t
    for t in EXPORT_TYPES
    if t
    in (
        ET_COMPUTE_SOURCE_TEMPLATES,
        ET_COMPUTE_REQUIREMENT_TEMPLATES,
        ET_IMAGE_FAMILIES,
        ET_NAMESPACE_POLICIES,
    )
)

# What --all writes: every type but Credentials, which need --include-credentials
ALL_TYPES: tuple[str, ...] = tuple(t for t in EXPORT_TYPES if t != ET_CREDENTIALS)


# ---------------------------------------------------------------------------
# Specifications
# ---------------------------------------------------------------------------

# In PLATFORM_MUSTACHE_PROPERTIES, the properties whose text the Platform's
# own Mustache reads, the loader substitutes only the Worker Pool form
# ('__{{x}}__'), at any depth; the loader's own set, so the two cannot differ
_DELIMITERS = (VAR_OPENING_DELIMITER, VAR_CLOSING_DELIMITER)
_WP_DELIMITERS = (
    WP_VARIABLES_PREFIX + VAR_OPENING_DELIMITER,
    VAR_CLOSING_DELIMITER + WP_VARIABLES_POSTFIX,
)


def _raw(text: str, delimiters: tuple[str, str], keep: Callable[[int], bool]) -> str:
    """
    'text' with each top-level expression in 'delimiters' written as a raw
    literal ('{{x}}' as '{{raw:x}}', '__{{x}}__' as '__{{raw:x}}__'), which
    loading gives back as written; an expression starting where 'keep' says
    is left as it is.
    """
    opening, _ = delimiters
    if opening not in text:
        return text
    pieces: list[str] = []
    position = 0
    for span in find_delimited_expression_spans(text, *delimiters):
        if keep(span.start):
            continue
        inside = span.start + len(opening)
        pieces += [text[position:inside], RAW_PREFIX]
        position = inside
    pieces.append(text[position:])
    return "".join(pieces)


def _never(_position: int) -> bool:
    return False


def _literal(data: Any, mustache: bool = False) -> Any:
    """
    'data' with every string's expressions written raw: in the plain form,
    or, within a Platform Mustache property, in the Worker Pool form alone,
    since there the loader substitutes no other and a plain one is the
    Platform's ('{{node.name}}'), kept as written.
    """
    if isinstance(data, str):
        return _raw(data, _WP_DELIMITERS if mustache else _DELIMITERS, _never)
    if isinstance(data, dict):
        return {
            key: _literal(value, mustache or key in PLATFORM_MUSTACHE_PROPERTIES)
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [_literal(item, mustache) for item in data]
    return data


def _plain_expressions_raw(text: str) -> str:
    """
    A Platform Mustache string as specification_of() writes it, with its
    plain expressions written raw too: those outside the Worker Pool form's,
    which it has already written raw.
    """
    if VAR_OPENING_DELIMITER not in text:
        return text
    worker_pool = find_delimited_expression_spans(text, *_WP_DELIMITERS)

    def _inside_worker_pool_form(position: int) -> bool:
        return any(span.start <= position < span.end for span in worker_pool)

    return _raw(text, _DELIMITERS, _inside_worker_pool_form)


def literal_for_jsonnet(data: Any, mustache: bool = False) -> Any:
    """
    Specifications as specification_of() writes them, for a Jsonnet file:
    the Jsonnet loader substitutes the plain form in every property before
    evaluating the file, the Platform Mustache properties included, so a
    plain expression in one is written raw too.
    """
    if isinstance(data, str):
        return _plain_expressions_raw(data) if mustache else data
    if isinstance(data, dict):
        return {
            key: literal_for_jsonnet(
                value, mustache or key in PLATFORM_MUSTACHE_PROPERTIES
            )
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [literal_for_jsonnet(item, mustache) for item in data]
    return data


def _without_defaults(data: Any, defaults: Mapping[str, Any], path: str = "") -> Any:
    """
    'data' less each property holding the default 'defaults' maps its path
    to, which the Platform sets when it is unset; one holding anything else
    is kept.
    """
    if isinstance(data, dict):
        kept: dict[str, Any] = {}
        for key, value in data.items():
            child = f"{path}.{key}" if path else key
            pattern = path_pattern(child)
            if pattern in defaults and not differences(value, defaults[pattern]):
                continue
            kept[key] = _without_defaults(value, defaults, child)
        return kept
    if isinstance(data, list):
        return [
            _without_defaults(item, defaults, f"{path}[{index}]")
            for index, item in enumerate(data)
        ]
    return data


def specification_of(
    resource_type: str, model: object, model_name: str | None = None
) -> dict:
    """
    The specification of a resource as the Platform holds it: 'resource'
    first, then what 'yd resource plan' compares (comparable()), less a
    property holding its Platform default, with each '{{...}}' in a string
    written raw, so that loading it gives the string back. With
    'model_name', the model 'yd resource create' sends where it is not the
    one read back (AddConfiguredWorkerPoolRequest for a ConfiguredWorkerPool),
    only that model's properties are written.
    """
    properties = _without_defaults(
        comparable(model, model_name),
        platform_defaults(resource_type),
    )
    if model_name is not None:
        sent = {f.name for f in fields(model_class(model_name))}
        properties = {key: value for key, value in properties.items() if key in sent}
    properties.pop(PROP_RESOURCE, None)
    return {PROP_RESOURCE: resource_type, **_literal(properties)}


@dataclass
class _Links:
    """
    What a resource refers to, as it is exported: the references to follow
    under '--with-dependencies', and the notes on those left as IDs.
    """

    resource_type: str
    name: str
    references: list[Reference]
    notes: list[str]

    def add(self, value: Any, reference: Callable[[str], Reference | None]) -> None:
        found, note = _reference_or_note(
            self.resource_type, self.name, value, reference
        )
        if found is not None and found not in self.references:
            self.references.append(found)
        if note is not None:
            self.notes.append(note)

    def exported(self, specification: dict) -> Exported:
        return Exported(specification, tuple(self.references), tuple(self.notes))


def _reference_or_note(
    resource_type: str,
    name: str,
    value: Any,
    reference: Callable[[str], Reference | None],
) -> tuple[Reference | None, str | None]:
    """
    A reference a resource makes, after its IDs were named: a name gives the
    Reference 'reference' makes of it (None for one not to follow); an ID
    that could not be named is kept, and gives a note saying so; no value
    gives neither.
    """
    if not isinstance(value, str):
        return None, None
    if get_ydid_type(value) is not None:
        return None, (
            f"{RESOURCE_TYPE_NAMES.get(resource_type, resource_type)} '{name}':"
            f" '{value}' could not be named, so is written as its ID"
        )
    return reference(value), None


def _named(namespace: str | None, name: str | None) -> str:
    return f"{namespace}{NAMESPACE_PREFIX_SEPARATOR}{name}"


def _found(resource_type: str, summaries: list, selection: Selection) -> list[Found]:
    """
    The summaries in the selection's namespace whose bare name matches its
    glob, as found resources keyed by their IDs.
    """
    in_namespace = [
        summary
        for summary in summaries
        if selection.namespace is None or summary.namespace == selection.namespace
    ]
    if selection.name_glob is not None:
        in_namespace = filter_summaries_by_name_glob(in_namespace, selection.name_glob)
    return [
        Found(resource_type, _named(summary.namespace, summary.name), summary.id)
        for summary in in_namespace
        if summary.name is not None
    ]


def _prefix_hint(selection: Selection) -> str | None:
    """
    What a search is given of the name glob: its literal prefix, or nothing,
    as 'yd list' gives the search of each type exported.
    """
    if selection.name_glob is None:
        return None
    return glob_search_prefix(selection.name_glob) or None


# ---------------------------------------------------------------------------
# Compute Source and Requirement Templates, Image Families
# ---------------------------------------------------------------------------

# An image reference in the form 'yd resource create' names a family, or a
# group in one: 'yd/<namespace>/<family>[/<group>]'
_IMAGE_NAME_PREFIX = "yd/"


def _image_reference(value: str) -> Reference | None:
    """
    The Reference an image reference makes: to the Image Family it names,
    public or not (whether it is followed is the exporter's 'followed' to
    say, asked only under '--with-dependencies'), unless the reference is a
    provider's own image ID.
    """
    if not value.startswith(_IMAGE_NAME_PREFIX):
        return None  # A provider's own image ID
    parts = value.removeprefix(_IMAGE_NAME_PREFIX).split(NAMESPACE_PREFIX_SEPARATOR)
    if len(parts) < 2:
        return None
    return Reference(ET_IMAGE_FAMILIES, _named(parts[0], parts[1]))


def _image_family_followed(ctx: RunContext, name: str) -> bool:
    """
    Whether a reference to the Image Family 'namespace/family' is followed:
    not if it is public (YellowDog's own, never exported), or may be.
    """
    namespace, _, family = name.partition(NAMESPACE_PREFIX_SEPARATOR)
    return not _may_be_public(ctx, namespace, family)


def _may_be_public(ctx: RunContext, namespace: str, family: str) -> bool:
    """
    Whether the Image Family 'namespace/family' is public, or cannot be
    known not to be: its own 'access', read from it by name, since a search
    of another namespace never returns a public family, 'includePublic' or
    not. One not found is not public (the export notes one it cannot find);
    one the Application may not read is taken as public, with no warning,
    since it could not be exported either. Any other failure is raised.
    """
    try:
        found = ctx.client.images_client.get_image_family_by_name(
            namespace=namespace, family_name=family
        )
    except Exception as e:
        if is_http_not_found(e):
            return False
        if classify(e) != ExitCode.PERMISSION:
            raise
        _LOG.debug(
            "Image Family '%s/%s' not followed: its access could not be read",
            namespace,
            family,
            exc_info=True,
        )
        return True
    return found.access == ImageAccess.PUBLIC


def _source_template_reference(value: str) -> Reference:
    return Reference(ET_COMPUTE_SOURCE_TEMPLATES, value)


def find_source_templates(ctx: RunContext, selection: Selection) -> list[Found]:
    """
    The Compute Source Templates in the namespace matching the name glob.
    """
    summaries = ctx.client.compute_client.get_compute_source_templates(
        ComputeSourceTemplateSearch(
            name=_prefix_hint(selection),
            namespaces=search_namespaces(ctx.client, selection.namespace),
        )
    ).list_all()
    return _found(RN_SOURCE_TEMPLATE, summaries, selection)


def export_source_template(ctx: RunContext, found: Found) -> Exported:
    """
    A Compute Source Template, its image named, referring to its Image
    Family.
    """
    template = substitute_image_family_id_for_name_in_cst(
        ctx.client,
        ctx.client.compute_client.get_compute_source_template(found.key),
        True,
    )
    links = _Links(RN_SOURCE_TEMPLATE, found.name, [], [])
    for image_property in (PROP_IMAGE_ID, PROP_IMAGE):
        links.add(getattr(template.source, image_property, None), _image_reference)
    return links.exported(specification_of(RN_SOURCE_TEMPLATE, template))


def find_requirement_templates(ctx: RunContext, selection: Selection) -> list[Found]:
    """
    The Compute Requirement Templates in the namespace matching the name glob.
    """
    summaries = ctx.client.compute_client.get_compute_requirement_templates(
        ComputeRequirementTemplateSearch(
            name=_prefix_hint(selection),
            namespaces=search_namespaces(ctx.client, selection.namespace),
        )
    ).list_all()
    return _found(RN_REQUIREMENT_TEMPLATE, summaries, selection)


def export_requirement_template(ctx: RunContext, found: Found) -> Exported:
    """
    A Compute Requirement Template, its Source Templates and images named,
    referring to the Source Templates and the Image Families.
    """
    template = substitute_ids_for_names_in_crt(
        ctx.client,
        ctx.client.compute_client.get_compute_requirement_template_by_id(found.key),
        True,
    )
    links = _Links(RN_REQUIREMENT_TEMPLATE, found.name, [], [])
    images = _image_reference
    # A dynamic template has no Sources
    for source in getattr(template, PROP_SOURCES, None) or []:
        links.add(getattr(source, PROP_CST_ID, None), _source_template_reference)
        links.add(getattr(source, PROP_IMAGE_ID, None), images)
    links.add(getattr(template, PROP_IMAGES_ID, None), images)
    return links.exported(specification_of(RN_REQUIREMENT_TEMPLATE, template))


def find_image_families(ctx: RunContext, selection: Selection) -> list[Found]:
    """
    The Machine Image Families in the namespace matching the name glob; a
    public one, YellowDog's own, never.
    """
    summaries = ctx.client.images_client.get_image_families(
        MachineImageFamilySearch(
            familyName=_prefix_hint(selection),
            namespaces=search_namespaces(ctx.client, selection.namespace),
            includePublic=False,
        )
    ).list_all()
    private = [s for s in summaries if s.access != ImageAccess.PUBLIC]
    return _found(RN_IMAGE_FAMILY, private, selection)


def export_image_family(ctx: RunContext, found: Found) -> Exported:
    """
    A Machine Image Family whole: its Image Groups and their Images, as
    'yd resource create' takes it.
    """
    family = ctx.client.images_client.get_image_family_by_id(found.key)
    return Exported(specification_of(RN_IMAGE_FAMILY, family))


EXPORTERS[ET_COMPUTE_SOURCE_TEMPLATES] = Exporter(
    namespaced=True,
    find=find_source_templates,
    export=export_source_template,
    resource_type=RN_SOURCE_TEMPLATE,
)
EXPORTERS[ET_COMPUTE_REQUIREMENT_TEMPLATES] = Exporter(
    namespaced=True,
    find=find_requirement_templates,
    export=export_requirement_template,
    resource_type=RN_REQUIREMENT_TEMPLATE,
)
EXPORTERS[ET_IMAGE_FAMILIES] = Exporter(
    namespaced=True,
    find=find_image_families,
    export=export_image_family,
    resource_type=RN_IMAGE_FAMILY,
    followed=_image_family_followed,
)


# ---------------------------------------------------------------------------
# Namespaces, Namespace Policies, Keyrings and Attribute Definitions
# ---------------------------------------------------------------------------


def _specification(resource_type: str, properties: dict) -> dict:
    """
    A specification written from its properties, 'resource' first, a None
    property left out, each '{{...}}' in a string written raw.
    """
    kept = {key: value for key, value in properties.items() if value is not None}
    return {PROP_RESOURCE: resource_type, **_literal(kept)}


def _matches(name: str | None, selection: Selection) -> bool:
    return name is not None and (
        selection.name_glob is None or fnmatchcase(name, selection.name_glob)
    )


def find_namespaces(ctx: RunContext, selection: Selection) -> list[Found]:
    """
    The Namespaces whose name matches the name glob.
    """
    namespaces = ctx.client.namespaces_client.get_namespaces(
        NamespaceSearch(namespaceContains=_prefix_hint(selection))
    ).list_all()
    return [
        Found(RN_NAMESPACE, namespace.namespace, namespace.namespace)
        for namespace in namespaces
        if _matches(namespace.namespace, selection)
    ]


def export_namespace(ctx: RunContext, found: Found) -> Exported:
    """
    A Namespace: its name alone.
    """
    return Exported(_specification(RN_NAMESPACE, {PROP_NAME: found.key}))


def find_namespace_policies(ctx: RunContext, selection: Selection) -> list[Found]:
    """
    The Namespace Policy of the selection's namespace, if it has one and its
    namespace matches the name glob, a policy being named by its namespace.
    """
    namespace = selection.namespace
    if namespace is None or not _matches(namespace, selection):
        return []
    try:
        policy = ctx.client.namespaces_client.get_namespace_policy(namespace=namespace)
    except Exception as e:
        if not is_http_not_found(e):
            raise
        return []
    return [Found(RN_NAMESPACE_POLICY, namespace, policy)]


def export_namespace_policy(ctx: RunContext, found: Found) -> Exported:
    """
    A Namespace Policy: its namespace and its 'autoscalingMaxNodes'.
    """
    policy: NamespacePolicy = found.key
    return Exported(
        _specification(
            RN_NAMESPACE_POLICY,
            {
                PROP_NAMESPACE: policy.namespace,
                PROP_AUTOSCALING_MAX_NODES: policy.autoscalingMaxNodes,
            },
        )
    )


def find_keyrings(ctx: RunContext, selection: Selection) -> list[Found]:
    """
    The Keyrings whose name matches the name glob.
    """
    summaries = ctx.client.keyring_client.get_keyrings(
        KeyringSearch(name=_prefix_hint(selection))
    ).list_all()
    return [
        Found(RN_KEYRING, cast(str, summary.name), summary)
        for summary in summaries
        if _matches(summary.name, selection)
    ]


def export_keyring(ctx: RunContext, found: Found) -> Exported:
    """
    A Keyring: its name and its description, both required. Its Credentials
    are exported as their own type, its accessors not at all.
    """
    summary: KeyringSummary = found.key
    return Exported(
        {
            PROP_RESOURCE: RN_KEYRING,
            **_literal(
                {PROP_NAME: summary.name, PROP_DESCRIPTION: summary.description}
            ),
        }
    )


# The properties of each type of Attribute Definition 'yd resource create'
# sends (prepare_attribute_definition()), required ones first
_ATTRIBUTE_PROPERTIES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    RN_STRING_ATTRIBUTE_DEFINITION: (
        (PROP_NAME, PROP_TITLE),
        (PROP_DESCRIPTION, PROP_OPTIONS),
    ),
    RN_NUMERIC_ATTRIBUTE_DEFINITION: (
        (PROP_NAME, PROP_TITLE, PROP_DEFAULT_RANK_ORDER),
        (PROP_DESCRIPTION, PROP_UNITS, PROP_RANGE, PROP_OPTIONS),
    ),
}


def _attribute_type(definition: dict) -> str:
    """
    The resource type of an Attribute Definition as the Platform lists it,
    as 'yd list attribute-definitions' decides it.
    """
    if "Numeric" in str(definition.get(PROP_TYPE)):
        return RN_NUMERIC_ATTRIBUTE_DEFINITION
    return RN_STRING_ATTRIBUTE_DEFINITION


def find_attribute_definitions(ctx: RunContext, selection: Selection) -> list[Found]:
    """
    The user Attribute Definitions whose name matches the name glob: those
    the account defined, listed at the endpoint 'yd resource create' writes
    to, and named with the 'user.' prefix, which the Platform requires of
    them. The Platform's own are read-only, so never exported.
    """
    return [
        Found(_attribute_type(definition), definition[PROP_NAME], definition)
        for definition in get_user_attribute_definitions(ctx.config)
        if str(definition.get(PROP_NAME)).startswith(USER_ATTRIBUTE_PREFIX)
        and _matches(definition.get(PROP_NAME), selection)
    ]


def export_attribute_definition(ctx: RunContext, found: Found) -> Exported:
    """
    An Attribute Definition: the properties 'yd resource create' sends, an
    optional one left out where the Platform lists it unset ('' or []).
    """
    definition: dict = found.key
    required, optional = _ATTRIBUTE_PROPERTIES[found.resource_type]
    properties = {key: definition.get(key) for key in required}
    properties.update(
        {
            key: definition[key]
            for key in optional
            if definition.get(key) not in (None, "", [], {})
        }
    )
    return Exported(_specification(found.resource_type, properties))


# ---------------------------------------------------------------------------
# Groups, Applications and Users
# ---------------------------------------------------------------------------


def _group_reference(value: str) -> Reference:
    return Reference(ET_GROUPS, value)


def find_groups(ctx: RunContext, selection: Selection) -> list[Found]:
    """
    The Groups whose name matches the name glob.
    """
    return [
        Found(RN_GROUP, cast(str, summary.name), summary.id)
        for summary in get_all_groups(ctx.client)
        if _matches(summary.name, selection)
    ]


def _role_specification(group_role: GroupRole) -> dict:
    """
    A Group's role as 'yd resource create' takes it: the role and the
    namespaces of its scope by name (sorted), or its scope global.
    """
    role = group_role.role
    scope = group_role.scope
    role_named = {PROP_NAME: role.name} if role.name is not None else {PROP_ID: role.id}
    if scope.global_:
        return {PROP_ROLE: role_named, PROP_SCOPE: {PROP_GLOBAL: True}}
    return {
        PROP_ROLE: role_named,
        PROP_SCOPE: {
            PROP_GLOBAL: False,
            PROP_NAMESPACES: [
                {PROP_NAMESPACE: namespace}
                for namespace in sorted(ref.namespace for ref in scope.namespaces or [])
            ],
        },
    }


def export_group(ctx: RunContext, found: Found) -> Exported:
    """
    A Group: its name, its description and its roles, each a built-in role
    in a scope, by name, so it refers to nothing to export. The roles are
    always written, '[]' for none, so that 'yd resource create' makes them
    match.
    """
    group: Group = ctx.client.account_client.get_group(found.key)
    roles = sorted(
        (_role_specification(role) for role in group.roles or []),
        key=lambda role: json.dumps(role, sort_keys=True),
    )
    return Exported(
        _specification(
            RN_GROUP,
            {
                PROP_NAME: group.name,
                PROP_DESCRIPTION: group.description,
                PROP_ROLES: roles,
            },
        )
    )


def _group_names(links: _Links, summaries: list[GroupSummary]) -> list[str]:
    """
    The Groups an Application or User is in, by name (sorted), each a
    reference; a Group with no name is written as its ID and noted.
    """
    names = sorted(cast(str, summary.name or summary.id) for summary in summaries)
    for name in names:
        links.add(name, _group_reference)
    return names


def find_applications(ctx: RunContext, selection: Selection) -> list[Found]:
    """
    The Applications whose name matches the name glob.
    """
    return [
        Found(RN_APPLICATION, application.name, application.id)
        for application in get_all_applications(ctx.client)
        if _matches(application.name, selection)
    ]


def _has_keyring_access(ctx: RunContext, application_id: str) -> bool:
    """
    Whether the Application is an accessor of any Keyring the export can
    read; Keyrings that cannot be listed for a missing permission give no
    access to say anything of.
    """
    try:
        return bool(get_application_keyrings(ctx.client, application_id))
    except Exception as e:
        if classify(e) != ExitCode.PERMISSION:
            raise
        _LOG.debug(
            "The Keyrings Application '%s' can use could not be read",
            application_id,
            exc_info=True,
        )
        return False


def export_application(ctx: RunContext, found: Found) -> Exported:
    """
    An Application: its name, its description and its Groups by name,
    referring to them. Its Keyring access is not written, since 'yd
    resource create' refuses a grant to an existing Application without
    '--regenerate-app-keys': where it has any, a note says so.
    """
    application: Application = ctx.client.account_client.get_application(found.key)
    links = _Links(RN_APPLICATION, found.name, [], [])
    groups = _group_names(links, get_application_group_summaries(ctx.client, found.key))
    if _has_keyring_access(ctx, found.key):
        links.notes.append(
            f"Application '{found.name}': its Keyring access is not exported"
        )
    return links.exported(
        _specification(
            RN_APPLICATION,
            {
                PROP_NAME: application.name,
                PROP_DESCRIPTION: application.description,
                PROP_GROUPS: groups,
            },
        )
    )


def find_users(ctx: RunContext, selection: Selection) -> list[Found]:
    """
    The Internal and External Users whose name matches the name glob (the
    name, as 'yd list users' matches it), each found by what identifies it
    to 'yd resource create': an Internal User's username, an External
    User's name.
    """
    found = []
    for user in get_all_users(ctx.client):
        if not _matches(user.name, selection):
            continue
        if isinstance(user, InternalUser):
            found.append(Found(RN_INTERNAL_USER, user.username, user))
        elif isinstance(user, ExternalUser):
            found.append(Found(RN_EXTERNAL_USER, user.name, user))
    return found


def export_user(ctx: RunContext, found: Found) -> Exported:
    """
    A User, which 'yd resource create' does not create but finds: an
    Internal User by its username, an External User by its name, with its
    Groups by name, referring to them.
    """
    user: User = found.key
    links = _Links(found.resource_type, found.name, [], [])
    groups = _group_names(links, get_user_groups(ctx.client, cast(str, user.id)))
    identifier = PROP_USERNAME if found.resource_type == RN_INTERNAL_USER else PROP_NAME
    return links.exported(
        _specification(
            found.resource_type, {identifier: found.name, PROP_GROUPS: groups}
        )
    )


EXPORTERS[ET_NAMESPACES] = Exporter(
    namespaced=False,
    find=find_namespaces,
    export=export_namespace,
    resource_type=RN_NAMESPACE,
)
EXPORTERS[ET_NAMESPACE_POLICIES] = Exporter(
    namespaced=True,
    find=find_namespace_policies,
    export=export_namespace_policy,
    resource_type=RN_NAMESPACE_POLICY,
)
EXPORTERS[ET_KEYRINGS] = Exporter(
    namespaced=False,
    find=find_keyrings,
    export=export_keyring,
    resource_type=RN_KEYRING,
)
EXPORTERS[ET_ATTRIBUTE_DEFINITIONS] = Exporter(
    namespaced=False,
    find=find_attribute_definitions,
    export=export_attribute_definition,
)
EXPORTERS[ET_GROUPS] = Exporter(
    namespaced=False, find=find_groups, export=export_group, resource_type=RN_GROUP
)
EXPORTERS[ET_APPLICATIONS] = Exporter(
    namespaced=False,
    find=find_applications,
    export=export_application,
    resource_type=RN_APPLICATION,
)
EXPORTERS[ET_USERS] = Exporter(namespaced=False, find=find_users, export=export_user)


# ---------------------------------------------------------------------------
# Credentials, Allowances and Configured Worker Pools
# ---------------------------------------------------------------------------

# What the SDK's model package prefixes a Credential's type with
_MODEL_PACKAGE_SEPARATOR = "."


def _keyring_reference(value: str) -> Reference:
    return Reference(ET_KEYRINGS, value)


# The properties of a Credential the Keyring's summary of it gives back
_CREDENTIAL_GIVEN = (PROP_TYPE, PROP_NAME, PROP_DESCRIPTION)


def credential_variable(keyring: str, credential: str, field: str) -> str:
    """
    The variable an exported Credential's field is written as: the
    Keyring's name, the Credential's and the field's, joined with '_',
    lowercased, each character outside [a-z0-9_] written as '_'.
    """
    joined = "_".join((keyring, credential, field)).lower()
    return re.sub(r"[^a-z0-9_]", "_", joined)


def _credential_fields(credential_type: str) -> list[str]:
    """
    The fields of a type of Credential written as variables: those it
    requires that the Keyring's summary does not give back.
    """
    model_name = credential_type.split(_MODEL_PACKAGE_SEPARATOR)[-1]
    required = required_properties(model_name)
    return [
        field.name
        for field in fields(model_class(model_name))
        if field.name in required and field.name not in _CREDENTIAL_GIVEN
    ]


@dataclass(frozen=True)
class _FoundCredential:
    """
    A Credential found in its Keyring, with the variable each of its fields
    is written as, and those of them numbered to keep them distinct.
    """

    keyring: str
    summary: KeyringCredential
    variables: tuple[tuple[str, str], ...]  # (field, variable)
    numbered: tuple[str, ...]


def _found_credentials(found: list[Found]) -> list[Found]:
    """
    The Credentials found, each with its variables, distinct across them
    all: two Credentials can make the same name ('aws-keys' + 'prod' and
    'aws' + 'keys-prod'), so, taking them by name, a variable already made
    is numbered ('_2', then '_3', ...) on the later.
    """
    taken: set[str] = set()
    variables: dict[str, tuple[tuple[tuple[str, str], ...], tuple[str, ...]]] = {}
    for item in sorted(found, key=lambda item: item.name):
        if isinstance(item.key, _UnreadKeyring):
            continue
        keyring, summary = cast(tuple[str, KeyringCredential], item.key)
        made: list[tuple[str, str]] = []
        numbered: list[str] = []
        for field in _credential_fields(cast(str, summary.type)):
            base = credential_variable(keyring, cast(str, summary.name), field)
            variable, number = base, 2
            while variable in taken:
                variable, number = f"{base}_{number}", number + 1
            if variable != base:
                numbered.append(variable)
            taken.add(variable)
            made.append((field, variable))
        variables[item.name] = (tuple(made), tuple(numbered))
    return [
        item
        if isinstance(item.key, _UnreadKeyring)
        else Found(
            item.resource_type,
            item.name,
            _FoundCredential(item.key[0], item.key[1], *variables[item.name]),
        )
        for item in found
    ]


@dataclass(frozen=True)
class _UnreadKeyring:
    """
    A Keyring whose Credentials could not be read, and why.
    """

    error: Exception


def find_credentials(ctx: RunContext, selection: Selection) -> list[Found]:
    """
    The Credentials in each Keyring whose name matches the name glob, each
    found as 'keyring/credential' with its Keyring's name, its summary and
    the variables its fields are written as (_found_credentials()). The
    Keyring's credentials are summaries, holding no secret. A Keyring that
    cannot be read is found as itself, its export failing, so that it alone
    is reported and left out; an authentication or connection failure stops
    the export.
    """
    found: list[Found] = []
    for summary in find_keyrings(ctx, selection):
        try:
            keyring: Keyring = ctx.client.keyring_client.get_keyring(summary.key.id)
        except Exception as e:
            if classify(e) in SESSION_FAILURES:
                raise
            # Found as the Keyring, its export failing for it alone
            found.append(Found(RN_CREDENTIAL, summary.name, _UnreadKeyring(e)))
            continue
        # Counted, never shown: a summary is the user's to see, not the trace's
        _LOG.debug(
            "Keyring '%s' holds %d Credential(s)",
            summary.name,
            len(keyring.credentials or []),
        )
        for credential in keyring.credentials or []:
            if credential.name is None:
                continue
            found.append(
                Found(
                    RN_CREDENTIAL,
                    _named(summary.name, credential.name),
                    (summary.name, credential),
                )
            )
    return _found_credentials(found)


def export_credential(ctx: RunContext, found: Found) -> Exported:
    """
    A Credential as 'yd resource create' takes it: its Keyring's name, and
    its type, name and description as the Keyring summarises it, with each
    other property its type requires, which the Platform never gives back,
    written as a variable ('{{<keyring>_<credential>_<field>}}', numbered
    where another Credential's would have its name) for the user to supply,
    which a note lists. Refers to its Keyring.
    """
    if isinstance(found.key, _UnreadKeyring):
        raise RuntimeError(
            f"the Credentials of Keyring '{found.name}' could not be read:"
            f" {found.key.error}"
        ) from found.key.error
    credential: _FoundCredential = found.key
    keyring_name, summary = credential.keyring, credential.summary
    given = {
        PROP_TYPE: summary.type,
        PROP_NAME: summary.name,
        PROP_DESCRIPTION: summary.description,
    }
    variables = dict(credential.variables)
    links = _Links(RN_CREDENTIAL, found.name, [], [])
    links.add(keyring_name, _keyring_reference)
    if variables:
        note = (
            f"Credential '{found.name}': its required fields other than its name"
            " and description are written as variables, since the Platform does"
            f" not return them; supply {plural('variable', len(variables))}"
            f" {', '.join(variables.values())}"
        )
        if credential.numbered:
            note += (
                f"; {', '.join(credential.numbered)}"
                f" {'is' if len(credential.numbered) == 1 else 'are'} numbered,"
                " since another Credential's variables have the same names"
            )
        links.notes.append(note)
    written = {
        **_literal({key: value for key, value in given.items() if value is not None}),
        **{
            field: f"{VAR_OPENING_DELIMITER}{variable}{VAR_CLOSING_DELIMITER}"
            for field, variable in variables.items()
        },
    }
    return links.exported(
        {
            PROP_RESOURCE: RN_CREDENTIAL,
            **_literal({PROP_KEYRING_NAME: keyring_name}),
            PROP_CREDENTIAL: written,
        }
    )


def _requirement_template_reference(value: str) -> Reference:
    return Reference(ET_COMPUTE_REQUIREMENT_TEMPLATES, value)


def find_allowances(ctx: RunContext, selection: Selection) -> list[Found]:
    """
    The Allowances whose description matches the name glob, all of them
    without one, as 'yd list allowances' searches them. Each is found by its
    description; one with none, or sharing it with another found, by its
    description and ID, so that each is exported.
    """
    allowances: list[Allowance] = [
        allowance
        for allowance in ctx.client.allowances_client.get_allowances(
            AllowanceSearch()
        ).list_all()
        if selection.name_glob is None or _matches(allowance.description, selection)
    ]
    descriptions = Counter(allowance.description for allowance in allowances)
    found = []
    for allowance in allowances:
        description = allowance.description
        if description is not None and descriptions[description] == 1:
            name = description
        elif description is not None:
            name = f"{description} ({allowance.id})"
        else:
            name = cast(str, allowance.id)
        found.append(Found(RN_ALLOWANCE, name, allowance))
    return found


def _unnamed_note(name: str, refers_to: str, ydid: str) -> str:
    """
    The note on an Allowance for one Compute Source or Requirement, which
    has an ID and no name to write.
    """
    return (
        f"{RESOURCE_TYPE_NAMES[RN_ALLOWANCE]} '{name}': refers to {refers_to}"
        f" '{ydid}', which cannot be named, so is written as its ID"
    )


def export_allowance(ctx: RunContext, found: Found) -> Exported:
    """
    An Allowance, its Compute Source or Requirement Template named as
    'yd resource create' takes it, referring to that template. One for a
    single Compute Source or Requirement keeps its ID, which has no name,
    and a note says so, as for a template that cannot be named.
    """
    allowance = substitute_id_for_name_in_allowance(
        ctx.client, deepcopy(found.key), True
    )
    links = _Links(RN_ALLOWANCE, found.name, [], [])
    if isinstance(allowance, SourcesAllowance):
        links.add(
            getattr(allowance, PROP_SOURCE_CREATED_FROM, None),
            _source_template_reference,
        )
    elif isinstance(allowance, RequirementsAllowance):
        links.add(
            getattr(allowance, PROP_REQUIREMENT_CREATED_FROM, None),
            _requirement_template_reference,
        )
    elif isinstance(allowance, SourceAllowance) and allowance.sourceId:
        links.notes.append(
            _unnamed_note(found.name, "Compute Source", allowance.sourceId)
        )
    elif isinstance(allowance, RequirementAllowance) and allowance.requirementId:
        links.notes.append(
            _unnamed_note(found.name, "Compute Requirement", allowance.requirementId)
        )
    return links.exported(specification_of(RN_ALLOWANCE, allowance))


def find_configured_worker_pools(ctx: RunContext, selection: Selection) -> list[Found]:
    """
    The Configured Worker Pools in the namespace matching the name glob.
    """
    summaries = get_worker_pool_summaries(
        ctx.client,
        selection.namespace,
        _prefix_hint(selection),
        partial_name_matches=True,
        pool_type=RN_CONFIGURED_POOL,
    )
    return _found(RN_CONFIGURED_POOL, summaries, selection)


def export_configured_worker_pool(ctx: RunContext, found: Found) -> Exported:
    """
    A Configured Worker Pool as 'yd resource create' sends it: the
    properties of an AddConfiguredWorkerPoolRequest.
    """
    pool = ctx.client.worker_pool_client.get_worker_pool_by_id(found.key)
    return Exported(
        specification_of(
            RN_CONFIGURED_POOL, pool, model_name="AddConfiguredWorkerPoolRequest"
        )
    )


EXPORTERS[ET_CREDENTIALS] = Exporter(
    namespaced=False,
    find=find_credentials,
    export=export_credential,
    resource_type=RN_CREDENTIAL,
)
EXPORTERS[ET_ALLOWANCES] = Exporter(
    namespaced=False,
    find=find_allowances,
    export=export_allowance,
    resource_type=RN_ALLOWANCE,
)
EXPORTERS[ET_CONFIGURED_WORKER_POOLS] = Exporter(
    namespaced=True,
    find=find_configured_worker_pools,
    export=export_configured_worker_pool,
    resource_type=RN_CONFIGURED_POOL,
)
