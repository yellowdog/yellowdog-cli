"""
How 'yd resource remove --type <type> <name-or-id>...' names a resource,
and which types 'yd resource show --type' finds by name:
the specification a name stands for, which removal reads as it reads a
file's, and the kind of YellowDog ID that removes one. A type with no name
(an Allowance, named by its description) is removed by ID; one with no ID
'--ids' removes (a Namespace, a Namespace Policy, an Attribute Definition, a
Credential) by name; Users are not removed at all.

Imports only constants and the YDID parser, so that the registry's check
can read the table as the command line is parsed.
"""

from __future__ import annotations

from collections.abc import Callable

from yellowdog_cli.utils.entity_names import (
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
from yellowdog_cli.utils.property_names import (
    PROP_CREDENTIAL,
    PROP_KEYRING_NAME,
    PROP_NAME,
    PROP_NAMESPACE,
    PROP_RESOURCE,
    PROP_SOURCE,
)
from yellowdog_cli.utils.settings import NAMESPACE_PREFIX_SEPARATOR
from yellowdog_cli.utils.ydid_utils import YDIDType

# The types Users are, which the CLI does not remove
USER_TYPES = frozenset({RN_INTERNAL_USER, RN_EXTERNAL_USER})

# The kind of YellowDog ID that removes each type that has one '--ids' takes
ID_TYPES: dict[str, YDIDType] = {
    RN_KEYRING: YDIDType.KEYRING,
    RN_SOURCE_TEMPLATE: YDIDType.COMPUTE_SOURCE_TEMPLATE,
    RN_REQUIREMENT_TEMPLATE: YDIDType.COMPUTE_REQUIREMENT_TEMPLATE,
    RN_IMAGE_FAMILY: YDIDType.IMAGE_FAMILY,
    RN_CONFIGURED_POOL: YDIDType.WORKER_POOL,
    RN_ALLOWANCE: YDIDType.ALLOWANCE,
    RN_GROUP: YDIDType.GROUP,
    RN_APPLICATION: YDIDType.APPLICATION,
}


def _split(target: str, namespace: str | None) -> tuple[str, str]:
    """
    'namespace/name' as its two parts, the configured namespace for a name
    given without one.
    """
    prefix, separator, name = target.rpartition(NAMESPACE_PREFIX_SEPARATOR)
    return (prefix if separator else namespace or ""), name


def _named(target: str, _namespace: str | None) -> dict:
    return {PROP_NAME: target}


def _namespaced(target: str, namespace: str | None) -> dict:
    namespace, name = _split(target, namespace)
    return {PROP_NAMESPACE: namespace, PROP_NAME: name}


def _source_template(target: str, namespace: str | None) -> dict:
    namespace, name = _split(target, namespace)
    return {PROP_NAMESPACE: namespace, PROP_SOURCE: {PROP_NAME: name}}


def _namespace_policy(target: str, _namespace: str | None) -> dict:
    return {PROP_NAMESPACE: target}


def _credential(target: str, _namespace: str | None) -> dict:
    keyring, _, credential = target.partition(NAMESPACE_PREFIX_SEPARATOR)
    return {PROP_KEYRING_NAME: keyring, PROP_CREDENTIAL: {PROP_NAME: credential}}


# The types 'yd resource show --type' finds by name, and the kind of ID each
# name stands for: those with a name and an ID (an Allowance has no name; a
# Namespace, Namespace Policy, Attribute Definition or Credential no ID)
SHOWN_BY_NAME: dict[str, YDIDType] = {
    **{t: k for t, k in ID_TYPES.items() if t != RN_ALLOWANCE},
    RN_INTERNAL_USER: YDIDType.USER,
    RN_EXTERNAL_USER: YDIDType.USER,
}

# How a name, as typed, becomes the specification removal reads, per type
_BY_NAME: dict[str, Callable[[str, str | None], dict]] = {
    RN_KEYRING: _named,
    RN_NAMESPACE: _named,
    RN_GROUP: _named,
    RN_APPLICATION: _named,
    RN_STRING_ATTRIBUTE_DEFINITION: _named,
    RN_NUMERIC_ATTRIBUTE_DEFINITION: _named,
    RN_REQUIREMENT_TEMPLATE: _namespaced,
    RN_IMAGE_FAMILY: _namespaced,
    RN_CONFIGURED_POOL: _namespaced,
    RN_SOURCE_TEMPLATE: _source_template,
    RN_NAMESPACE_POLICY: _namespace_policy,
    RN_CREDENTIAL: _credential,
}
NAMED_TYPES = frozenset(_BY_NAME)


def specification_for_name(
    resource_type: str, target: str, namespace: str | None
) -> dict:
    """
    The specification a name of the type stands for: 'namespace/name' for a
    namespaced type (the configured namespace without one), 'keyring/name'
    for a Credential, the namespace itself for a Namespace Policy.
    """
    return {PROP_RESOURCE: resource_type, **_BY_NAME[resource_type](target, namespace)}


def name_problem(resource_type: str, target: str) -> str | None:
    """
    Why a target that is not an ID cannot name a resource of the type, or
    None if it can.
    """
    if resource_type in USER_TYPES:
        return "Users cannot be removed by the CLI; please use the YellowDog Portal"
    if resource_type == RN_ALLOWANCE:
        return (
            "an Allowance has no name: give its ID, or --set description=..."
            " with --match-allowances-by-description"
        )
    if resource_type == RN_CREDENTIAL and NAMESPACE_PREFIX_SEPARATOR not in target:
        return f"a Credential is named as 'keyring/credential', not '{target}'"
    return None
