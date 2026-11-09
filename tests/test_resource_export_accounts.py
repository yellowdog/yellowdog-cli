"""
'yd resource export' for Namespaces, Namespace Policies, Keyrings, Attribute
Definitions, Groups, Applications and Users (utils/resource_exporters.py),
against the fake Platform (resource_plan_platform.py): each exported
specification planned as 'yd resource plan' plans it, and found unchanged.
"""

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests
from requests.exceptions import HTTPError
from yellowdog_client.model import (
    AllowanceLimitEnforcement,
    AllowanceResetType,
    Application,
    ConfiguredWorkerPool,
    ConfiguredWorkerPoolProperties,
    ExternalUser,
    GrantedPermissionScope,
    Group,
    GroupRole,
    InstanceStatus,
    InternalUser,
    Keyring,
    KeyringAccessor,
    KeyringCredential,
    Namespace,
    NamespacePolicy,
    NamespaceRef,
    RequirementAllowance,
    RequirementsAllowance,
    RoleSummary,
    SourceAllowance,
    SourcesAllowance,
    WorkerPoolStatus,
    WorkerPoolSummary,
)

import yellowdog_cli.utils.wrapper as wrapper_module
from tests.resource_plan_platform import (  # noqa: F401 (the fixture)
    FakePlatform,
    _clear_caches,
    _forbidden,
    _not_found,
    platform,
)
from yellowdog_cli.utils import resource_export
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    ET_ALLOWANCES,
    ET_APPLICATIONS,
    ET_ATTRIBUTE_DEFINITIONS,
    ET_COMPUTE_SOURCE_TEMPLATES,
    ET_CONFIGURED_WORKER_POOLS,
    ET_CREDENTIALS,
    ET_GROUPS,
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
    RN_INTERNAL_USER,
    RN_KEYRING,
    RN_NAMESPACE,
    RN_NAMESPACE_POLICY,
    RN_NUMERIC_ATTRIBUTE_DEFINITION,
    RN_SOURCE_TEMPLATE,
    RN_STRING_ATTRIBUTE_DEFINITION,
)
from yellowdog_cli.utils.exit_codes import ExitCode, ReportedFailure, classify
from yellowdog_cli.utils.noun_registry import EXPORT_TYPES
from yellowdog_cli.utils.resource_creation import prepare_allowance
from yellowdog_cli.utils.resource_export import (
    ExportOptions,
    export_resources,
    export_specifications,
)
from yellowdog_cli.utils.resource_exporters import (
    ALL_TYPES,
    EXPORTERS,
    Exported,
    Reference,
    Selection,
    credential_variable,
)
from yellowdog_cli.utils.resource_plan import plan_one
from yellowdog_cli.utils.resource_planners import CONFIGURED_POOL_EXISTS

STRING_DEFINITION = "co.yellowdog.platform.model.StringAttributeDefinition"
NUMERIC_DEFINITION = "co.yellowdog.platform.model.NumericAttributeDefinition"


def _ctx(platform: FakePlatform, namespace: str = "team-a") -> RunContext:
    config = wrapper_module.CONFIG_COMMON
    return RunContext(
        SimpleNamespace(),
        SimpleNamespace(
            namespace=namespace,
            url=config.url,
            key=config.key,
            secret=config.secret,
            request_timeout=config.request_timeout,
        ),
        platform.client,
    )


def _plan_ctx(platform: FakePlatform) -> RunContext:
    return RunContext(SimpleNamespace(), wrapper_module.CONFIG_COMMON, platform.client)


def _export(
    platform: FakePlatform,
    export_type: str,
    name_glob: str | None = None,
    namespace: str | None = "team-a",
) -> list[Exported]:
    exporter = EXPORTERS[export_type]
    ctx = _ctx(platform)
    selection = Selection(
        namespace=namespace if exporter.namespaced else None, name_glob=name_glob
    )
    found = exporter.find(ctx, selection)
    exported = [exporter.export(ctx, item) for item in found]
    _clear_caches()
    return exported


def _planned(platform: FakePlatform, specification: dict) -> str:
    """
    What 'yd resource plan' makes of an exported specification.
    """
    resource = deepcopy(specification)
    resource_type = resource.pop("resource")
    entry = plan_one(_plan_ctx(platform), resource_type, resource, None, set())
    assert entry.changes == (), entry.changes
    _clear_caches()
    return entry.action


def _role(platform: FakePlatform, name: str) -> RoleSummary:
    return platform.holding("Role", RoleSummary(name=name))


def _group_role(role: RoleSummary, *namespaces: str) -> GroupRole:
    return GroupRole(
        role=RoleSummary(id=role.id, name=role.name),
        scope=GrantedPermissionScope(
            global_=not namespaces,
            namespaces=(
                [
                    NamespaceRef(id=f"ydid:ns:000000:{n}", namespace=n)
                    for n in namespaces
                ]
                if namespaces
                else None
            ),
        ),
    )


def _group(platform: FakePlatform, name: str, *roles: GroupRole) -> Group:
    number = len(platform.held.get(RN_GROUP, [])) + 1
    group = Group(
        name=name, description=f"{name} group", roles=list(roles), adminGroup=False
    )
    group.id = f"ydid:group:000000:00000000-0000-0000-0000-{number:012d}"
    return platform.holding(RN_GROUP, group)


def _application(platform: FakePlatform, name: str, *groups: Group) -> Application:
    held = platform.holding(
        RN_APPLICATION,
        Application(
            name=name, description="renders", createdByUserId="ydid:user:000000:1"
        ),
    )
    platform.member_of(held.id, *groups)
    return held


# ---------------------------------------------------------------------------
# Namespaces and Namespace Policies
# ---------------------------------------------------------------------------


def test_a_namespace_round_trips_as_unchanged(platform):
    for name in ("team-a", "team-b", "other"):
        platform.holding(
            RN_NAMESPACE, Namespace(id=f"ydid:ns:000000:{name}", namespace=name)
        )
    exported = _export(platform, ET_NAMESPACES, "team-*")
    assert [e.specification for e in exported] == [
        {"resource": RN_NAMESPACE, "name": "team-a"},
        {"resource": RN_NAMESPACE, "name": "team-b"},
    ]
    for each in exported:
        assert _planned(platform, each.specification) == "unchanged"


def test_a_namespace_policy_round_trips_as_unchanged(platform):
    platform.holding(
        RN_NAMESPACE_POLICY, NamespacePolicy(namespace="team-a", autoscalingMaxNodes=10)
    )
    (exported,) = _export(platform, ET_NAMESPACE_POLICIES)
    assert exported.specification == {
        "resource": RN_NAMESPACE_POLICY,
        "namespace": "team-a",
        "autoscalingMaxNodes": 10,
    }
    assert _planned(platform, exported.specification) == "unchanged"


def test_a_namespace_policy_without_a_limit_round_trips(platform):
    platform.holding(RN_NAMESPACE_POLICY, NamespacePolicy(namespace="team-a"))
    (exported,) = _export(platform, ET_NAMESPACE_POLICIES)
    assert exported.specification == {
        "resource": RN_NAMESPACE_POLICY,
        "namespace": "team-a",
    }
    assert _planned(platform, exported.specification) == "unchanged"


def test_namespace_policy_is_the_selected_namespaces_only(platform):
    for namespace in ("team-a", "team-b"):
        platform.holding(
            RN_NAMESPACE_POLICY,
            NamespacePolicy(namespace=namespace, autoscalingMaxNodes=5),
        )
    exporter = EXPORTERS[ET_NAMESPACE_POLICIES]
    assert exporter.namespaced
    found = exporter.find(_ctx(platform), Selection("team-b", None))
    assert [item.name for item in found] == ["team-b"]
    # A namespace with no policy has none to export
    assert exporter.find(_ctx(platform), Selection("team-c", None)) == []


# ---------------------------------------------------------------------------
# Keyrings
# ---------------------------------------------------------------------------


def test_a_keyring_round_trips_as_unchanged(platform):
    platform.holding(RN_KEYRING, Keyring(name="aws-keyring", description="AWS"))
    platform.holding(RN_KEYRING, Keyring(name="azure-keyring", description="Azure"))
    (exported,) = _export(platform, ET_KEYRINGS, "aws-*")
    assert exported.specification == {
        "resource": RN_KEYRING,
        "name": "aws-keyring",
        "description": "AWS",
    }
    assert _planned(platform, exported.specification) == "unchanged"


def test_a_keyring_glob_with_no_literal_prefix_searches_every_keyring(platform):
    platform.holding(RN_KEYRING, Keyring(name="render-keyring", description="Render"))
    platform.holding(RN_KEYRING, Keyring(name="other", description="Other"))
    (exported,) = _export(platform, ET_KEYRINGS, "*-keyring")
    assert exported.specification["name"] == "render-keyring"
    # As 'yd list keyrings' searches: the glob's literal prefix, here none
    search = platform.client.keyring_client.get_keyrings.call_args.args[0]
    assert search.name is None


def test_a_keyring_search_is_given_the_globs_literal_prefix(platform):
    platform.holding(RN_KEYRING, Keyring(name="render-keyring", description="Render"))
    _export(platform, ET_KEYRINGS, "render-*ring")
    search = platform.client.keyring_client.get_keyrings.call_args.args[0]
    assert search.name == "render-"


def test_a_namespace_search_is_given_the_globs_literal_prefix(platform):
    platform.holding(
        RN_NAMESPACE, Namespace(id="ydid:ns:000000:team-a", namespace="team-a")
    )
    (exported,) = _export(platform, ET_NAMESPACES, "*-a")
    assert exported.specification["name"] == "team-a"
    search = platform.client.namespaces_client.get_namespaces.call_args.args[0]
    assert search.namespaceContains is None
    _export(platform, ET_NAMESPACES, "team-*")
    search = platform.client.namespaces_client.get_namespaces.call_args.args[0]
    assert search.namespaceContains == "team-"


# ---------------------------------------------------------------------------
# Attribute Definitions
# ---------------------------------------------------------------------------

# As GET /compute/attributes/user lists them: an unset description as "" and
# unset options as []
_STRING_LISTED = {
    "type": STRING_DEFINITION,
    "name": "user.owner",
    "title": "Owner",
    "description": "",
    "options": [],
}
_NUMERIC_LISTED = {
    "type": NUMERIC_DEFINITION,
    "name": "user.max-cost",
    "title": "Maximum cost",
    "defaultRankOrder": "PREFER_LOWER",
    "description": "The most an hour may cost",
    "units": "$",
    "range": {"min": 1, "max": 10},
    "options": [],
}


def test_attribute_definitions_round_trip_as_unchanged(platform):
    platform.attribute_definitions.extend(
        [deepcopy(_STRING_LISTED), deepcopy(_NUMERIC_LISTED)]
    )
    exported = _export(platform, ET_ATTRIBUTE_DEFINITIONS)
    by_name = {e.specification["name"]: e.specification for e in exported}
    assert by_name["user.owner"] == {
        "resource": RN_STRING_ATTRIBUTE_DEFINITION,
        "name": "user.owner",
        "title": "Owner",
    }
    assert by_name["user.max-cost"] == {
        "resource": RN_NUMERIC_ATTRIBUTE_DEFINITION,
        "name": "user.max-cost",
        "title": "Maximum cost",
        "defaultRankOrder": "PREFER_LOWER",
        "description": "The most an hour may cost",
        "units": "$",
        "range": {"min": 1, "max": 10},
    }
    for specification in by_name.values():
        assert _planned(platform, specification) == "unchanged"


def test_the_platforms_own_attribute_definitions_are_not_exported(platform):
    platform.attribute_definitions.extend(
        [
            deepcopy(_STRING_LISTED),
            {**deepcopy(_STRING_LISTED), "name": "yd.region", "title": "Region"},
        ]
    )
    exported = _export(platform, ET_ATTRIBUTE_DEFINITIONS)
    assert [e.specification["name"] for e in exported] == ["user.owner"]


def test_attribute_definitions_are_matched_by_name_glob(platform):
    platform.attribute_definitions.extend(
        [deepcopy(_STRING_LISTED), deepcopy(_NUMERIC_LISTED)]
    )
    exported = _export(platform, ET_ATTRIBUTE_DEFINITIONS, "user.max-*")
    assert [e.specification["name"] for e in exported] == ["user.max-cost"]


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


def test_a_group_round_trips_as_unchanged(platform):
    viewer, manager = _role(platform, "work-viewer"), _role(platform, "work-manager")
    _group(platform, "renderers", _group_role(viewer), _group_role(manager, "team-a"))
    _group(platform, "empty")
    exported = _export(platform, ET_GROUPS)
    assert [e.specification["name"] for e in exported] == ["renderers", "empty"]
    for each in exported:
        assert each.references == ()
        assert _planned(platform, each.specification) == "unchanged"
    assert exported[1].specification == {
        "resource": RN_GROUP,
        "name": "empty",
        "description": "empty group",
        "roles": [],
    }


def test_a_group_role_scoped_to_a_namespace_is_written_by_name(platform):
    manager = _role(platform, "work-manager")
    _group(platform, "renderers", _group_role(manager, "team-b", "team-a"))
    (exported,) = _export(platform, ET_GROUPS)
    assert exported.specification["roles"] == [
        {
            "role": {"name": "work-manager"},
            "scope": {
                "global": False,
                "namespaces": [{"namespace": "team-a"}, {"namespace": "team-b"}],
            },
        }
    ]
    assert "ydid:" not in str(exported.specification)
    assert _planned(platform, exported.specification) == "unchanged"


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------


def test_an_application_round_trips_as_unchanged(platform):
    renderers, viewers = _group(platform, "renderers"), _group(platform, "viewers")
    _application(platform, "render-app", viewers, renderers)
    (exported,) = _export(platform, ET_APPLICATIONS)
    assert exported.specification == {
        "resource": RN_APPLICATION,
        "name": "render-app",
        "description": "renders",
        "groups": ["renderers", "viewers"],
    }
    assert exported.notes == ()
    assert _planned(platform, exported.specification) == "unchanged"


def test_an_application_references_its_groups(platform):
    renderers, viewers = _group(platform, "renderers"), _group(platform, "viewers")
    _application(platform, "render-app", renderers, viewers)
    (exported,) = _export(platform, ET_APPLICATIONS)
    assert exported.references == (
        Reference(ET_GROUPS, "renderers"),
        Reference(ET_GROUPS, "viewers"),
    )


def test_an_application_with_keyring_access_is_noted_and_written_without_it(
    platform,
):
    app = _application(platform, "render-app")
    platform.holding(
        RN_KEYRING,
        Keyring(
            name="aws-keyring",
            description="AWS",
            accessors=[KeyringAccessor(accessorId=app.id, accessorType="APPLICATION")],
        ),
    )
    (exported,) = _export(platform, ET_APPLICATIONS)
    assert "keyrings" not in exported.specification
    assert exported.notes == (
        "Application 'render-app': its Keyring access is not exported",
    )
    # Written without its grant, it round-trips without '--regenerate-app-keys'
    assert _planned(platform, exported.specification) == "unchanged"


def test_keyring_access_that_cannot_be_read_is_not_noted(platform):
    _application(platform, "render-app")
    platform.client.keyring_client.find_all_keyrings.side_effect = _forbidden()
    (exported,) = _export(platform, ET_APPLICATIONS)
    assert exported.notes == ()


def test_an_application_exports_its_groups_as_dependencies(platform):
    viewer = _role(platform, "work-viewer")
    _group(platform, "renderers", _group_role(viewer))
    _group(platform, "unrelated")
    _application(platform, "render-app", platform.held[RN_GROUP][0])
    specifications, _ = export_specifications(
        _ctx(platform),
        ExportOptions(types=(ET_APPLICATIONS,), with_dependencies=True),
        warn=lambda message: pytest.fail(message),
    )
    assert [(s["resource"], s["name"]) for s in specifications] == [
        (RN_GROUP, "renderers"),
        (RN_APPLICATION, "render-app"),
    ]


def test_a_group_dependency_named_with_a_slash_is_found_whole(platform):
    """
    An account-wide name holding a '/' is a name, not 'namespace/name'.
    """
    _group(platform, "ops/admin")
    _application(platform, "render-app", platform.held[RN_GROUP][0])
    specifications, records = export_specifications(
        _ctx(platform),
        ExportOptions(types=(ET_APPLICATIONS,), with_dependencies=True),
        warn=lambda message: pytest.fail(message),
    )
    assert [(s["resource"], s["name"]) for s in specifications] == [
        (RN_GROUP, "ops/admin"),
        (RN_APPLICATION, "render-app"),
    ]
    assert [r.outcome for r in records] == ["exported", "exported"]


def test_applications_are_matched_by_name_glob(platform):
    _application(platform, "render-app")
    _application(platform, "admin-app")
    exported = _export(platform, ET_APPLICATIONS, "render-*")
    assert [e.specification["name"] for e in exported] == ["render-app"]


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def test_an_internal_user_round_trips_as_unchanged(platform):
    renderers = _group(platform, "renderers")
    held = platform.holding(
        RN_INTERNAL_USER,
        InternalUser(username="alice@example.com", name="alice", email="a@b.c"),
    )
    platform.member_of(held.id, renderers)
    (exported,) = _export(platform, ET_USERS)
    assert exported.specification == {
        "resource": RN_INTERNAL_USER,
        "username": "alice@example.com",
        "groups": ["renderers"],
    }
    assert exported.references == (Reference(ET_GROUPS, "renderers"),)
    assert _planned(platform, exported.specification) == "unchanged"


def test_an_external_user_round_trips_as_unchanged(platform):
    renderers = _group(platform, "renderers")
    user = ExternalUser(name="bob")
    held = platform.holding(RN_EXTERNAL_USER, user)
    platform.member_of(held.id, renderers)
    (exported,) = _export(platform, ET_USERS)
    assert exported.specification == {
        "resource": RN_EXTERNAL_USER,
        "name": "bob",
        "groups": ["renderers"],
    }
    assert exported.references == (Reference(ET_GROUPS, "renderers"),)
    assert _planned(platform, exported.specification) == "unchanged"


def test_users_are_matched_by_name_glob(platform):
    for name in ("alice", "bob"):
        platform.holding(
            RN_INTERNAL_USER, InternalUser(username=f"{name}@example.com", name=name)
        )
    exported = _export(platform, ET_USERS, "al*")
    assert [e.specification["username"] for e in exported] == ["alice@example.com"]


@pytest.mark.parametrize(
    "export_type",
    [
        ET_NAMESPACES,
        ET_KEYRINGS,
        ET_ATTRIBUTE_DEFINITIONS,
        ET_GROUPS,
        ET_APPLICATIONS,
        ET_USERS,
    ],
)
def test_account_wide_types_are_not_namespaced(export_type):
    assert not EXPORTERS[export_type].namespaced


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

AWS_CREDENTIAL = "co.yellowdog.platform.model.AwsCredential"


def _keyring_with_credentials(platform: FakePlatform, name: str, *credentials):
    return platform.holding(
        RN_KEYRING,
        Keyring(name=name, description="Keys", credentials=list(credentials)),
    )


def test_a_credential_is_written_with_variables_for_its_secrets(platform):
    _keyring_with_credentials(
        platform,
        "render-keys",
        KeyringCredential(name="aws-prod", type=AWS_CREDENTIAL, description="AWS"),
    )
    (exported,) = _export(platform, ET_CREDENTIALS, "render-*")
    assert exported.specification == {
        "resource": RN_CREDENTIAL,
        "keyringName": "render-keys",
        "credential": {
            "type": AWS_CREDENTIAL,
            "name": "aws-prod",
            "description": "AWS",
            "accessKeyId": "{{render_keys_aws_prod_accesskeyid}}",
            "secretAccessKey": "{{render_keys_aws_prod_secretaccesskey}}",
        },
    }
    assert exported.references == (Reference(ET_KEYRINGS, "render-keys"),)
    assert exported.notes == (
        "Credential 'render-keys/aws-prod': its required fields other than its"
        " name and description are written as variables, since the Platform"
        " does not return them; supply variables"
        " render_keys_aws_prod_accesskeyid, render_keys_aws_prod_secretaccesskey",
    )
    # Its secrets unreadable, an existing Credential's plan is 'unknown'
    assert _planned(platform, exported.specification) == "unknown"


def test_credentials_are_matched_by_their_keyrings_name(platform):
    _keyring_with_credentials(
        platform,
        "render-keys",
        KeyringCredential(name="a", type=AWS_CREDENTIAL),
        KeyringCredential(name="b", type=AWS_CREDENTIAL),
    )
    _keyring_with_credentials(
        platform, "other", KeyringCredential(name="c", type=AWS_CREDENTIAL)
    )
    exported = _export(platform, ET_CREDENTIALS, "render-*")
    assert [
        (e.specification["keyringName"], e.specification["credential"]["name"])
        for e in exported
    ] == [("render-keys", "a"), ("render-keys", "b")]
    assert "description" not in exported[0].specification["credential"]


def test_credential_variable_names_are_sanitised():
    assert (
        credential_variable("Render Keys", "aws-prod", "secretAccessKey")
        == "render_keys_aws_prod_secretaccesskey"
    )


def test_credentials_whose_variables_would_collide_are_numbered(platform):
    """
    'aws-keys' + 'prod' and 'aws' + 'keys-prod' both make 'aws_keys_prod_*':
    the later by name is numbered, deterministically, and its note says so.
    """
    _keyring_with_credentials(
        platform, "aws", KeyringCredential(name="keys-prod", type=AWS_CREDENTIAL)
    )
    _keyring_with_credentials(
        platform, "aws-keys", KeyringCredential(name="prod", type=AWS_CREDENTIAL)
    )
    exported = {
        e.specification["keyringName"]: e for e in _export(platform, ET_CREDENTIALS)
    }
    first = exported["aws-keys"]
    later = exported["aws"]
    assert first.specification["credential"]["accessKeyId"] == (
        "{{aws_keys_prod_accesskeyid}}"
    )
    assert later.specification["credential"]["accessKeyId"] == (
        "{{aws_keys_prod_accesskeyid_2}}"
    )
    assert later.specification["credential"]["secretAccessKey"] == (
        "{{aws_keys_prod_secretaccesskey_2}}"
    )
    (first_note,) = first.notes
    assert "numbered" not in first_note
    (later_note,) = later.notes
    assert later_note.endswith(
        "; aws_keys_prod_accesskeyid_2, aws_keys_prod_secretaccesskey_2 are"
        " numbered, since another Credential's variables have the same names"
    )


def test_credentials_are_exported_with_their_keyring_as_a_dependency(platform):
    _keyring_with_credentials(
        platform,
        "render-keys",
        KeyringCredential(name="aws-prod", type=AWS_CREDENTIAL),
    )
    specifications, _ = export_specifications(
        _ctx(platform),
        ExportOptions(types=(ET_CREDENTIALS,), with_dependencies=True),
        warn=lambda message: None,
    )
    assert [s["resource"] for s in specifications] == [RN_KEYRING, RN_CREDENTIAL]


# ---------------------------------------------------------------------------
# Allowances
# ---------------------------------------------------------------------------


def _hold_allowance(platform: FakePlatform, description: str | None = "monthly"):
    if not platform.held.get(RN_SOURCE_TEMPLATE):
        platform.holding(
            RN_SOURCE_TEMPLATE,
            SimpleNamespace(
                namespace="team-a", source=SimpleNamespace(name="aws-spot")
            ),
        )
        _clear_caches()
    resource = {
        "type": "co.yellowdog.platform.model.SourcesAllowance",
        "effectiveFrom": "2030-01-01T00:00:00+00:00",
        "resetType": "NONE",
        "limitEnforcement": "SOFT",
        "monitoredStatuses": ["RUNNING"],
        "allowedHours": 10,
        "sourceCreatedFromId": "team-a/aws-spot",
        **({"description": description} if description is not None else {}),
    }
    _, allowance = prepare_allowance(_plan_ctx(platform), resource)
    _clear_caches()
    return platform.holding(RN_ALLOWANCE, allowance)


def test_an_allowance_names_its_template_and_plans_as_create(platform):
    _hold_allowance(platform)
    (exported,) = _export(platform, ET_ALLOWANCES, "month*")
    assert exported.specification == {
        "resource": RN_ALLOWANCE,
        "type": "co.yellowdog.platform.model.SourcesAllowance",
        "effectiveFrom": "2030-01-01T00:00:00+00:00",
        "resetType": "NONE",
        "limitEnforcement": "SOFT",
        "monitoredStatuses": ["RUNNING"],
        "sourceCreatedFromId": "team-a/aws-spot",
        "description": "monthly",
        "allowedHours": 10,
    }
    assert exported.references == (
        Reference(ET_COMPUTE_SOURCE_TEMPLATES, "team-a/aws-spot"),
    )
    # Allowances are never updated: always 'create'
    assert _planned(platform, exported.specification) == "create"


def test_allowances_are_matched_by_description(platform):
    _hold_allowance(platform, "monthly")
    _hold_allowance(platform, "weekly")
    _hold_allowance(platform, None)
    exported = _export(platform, ET_ALLOWANCES, "week*")
    assert [e.specification["description"] for e in exported] == ["weekly"]
    assert len(_export(platform, ET_ALLOWANCES)) == 3


def test_allowances_of_one_description_are_each_exported(platform):
    _hold_allowance(platform, "monthly")
    _hold_allowance(platform, "monthly")
    specifications, _ = export_specifications(
        _ctx(platform),
        ExportOptions(types=(ET_ALLOWANCES,)),
        warn=lambda message: pytest.fail(message),
    )
    assert [s["description"] for s in specifications] == ["monthly", "monthly"]


# ---------------------------------------------------------------------------
# Configured Worker Pools
# ---------------------------------------------------------------------------


def test_a_configured_pool_plans_as_failed_for_its_taken_name(platform):
    platform.holding(
        RN_CONFIGURED_POOL,
        ConfiguredWorkerPool(
            name="render",
            namespace="team-a",
            status=WorkerPoolStatus.RUNNING,
            expectedNodeCount=2,
            awaitingNodes=False,
            properties=ConfiguredWorkerPoolProperties(
                targetNodeCount=2, workerTag="render"
            ),
        ),
    )
    platform.holding(
        RN_CONFIGURED_POOL, ConfiguredWorkerPool(name="other", namespace="team-b")
    )
    (exported,) = _export(platform, ET_CONFIGURED_WORKER_POOLS)
    assert exported.specification == {
        "resource": RN_CONFIGURED_POOL,
        "name": "render",
        "namespace": "team-a",
        "properties": {"targetNodeCount": 2, "workerTag": "render"},
    }
    resource = deepcopy(exported.specification)
    resource_type = resource.pop("resource")
    with pytest.raises(ValueError) as raised:
        plan_one(_plan_ctx(platform), resource_type, resource, None, set())
    assert str(raised.value) == CONFIGURED_POOL_EXISTS


def test_a_provisioned_pool_is_not_a_configured_one(platform):
    platform.holding(
        RN_CONFIGURED_POOL,
        WorkerPoolSummary(
            name="render",
            namespace="team-a",
            type="co.yellowdog.platform.model.ProvisionedWorkerPool",
        ),
    )
    assert _export(platform, ET_CONFIGURED_WORKER_POOLS) == []


def test_configured_pools_are_matched_by_name_glob(platform):
    for name in ("render", "other"):
        platform.holding(
            RN_CONFIGURED_POOL, ConfiguredWorkerPool(name=name, namespace="team-a")
        )
    exported = _export(platform, ET_CONFIGURED_WORKER_POOLS, "*nder")
    assert [e.specification["name"] for e in exported] == ["render"]
    search = platform.client.worker_pool_client.get_worker_pools.call_args.args[0]
    assert search.name is None


@pytest.mark.parametrize(
    "export_type", [ET_CREDENTIALS, ET_ALLOWANCES, ET_CONFIGURED_WORKER_POOLS]
)
def test_namespaced_only_configured_pools(export_type):
    assert EXPORTERS[export_type].namespaced == (
        export_type == ET_CONFIGURED_WORKER_POOLS
    )


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def test_every_export_type_has_an_exporter():
    assert set(EXPORTERS) == set(EXPORT_TYPES)
    assert len(EXPORTERS) == len(EXPORT_TYPES)


def test_all_types_is_every_exporter_but_credentials():
    assert set(ALL_TYPES) == set(EXPORTERS) - {ET_CREDENTIALS}


# ---------------------------------------------------------------------------
# Fix round 1: references that cannot be named, Keyrings that cannot be read
# ---------------------------------------------------------------------------

_ALLOWANCE_TERMS = dict(
    effectiveFrom=datetime(2030, 1, 1, tzinfo=timezone.utc),
    resetType=AllowanceResetType.NONE,
    limitEnforcement=AllowanceLimitEnforcement.SOFT,
    monitoredStatuses=[InstanceStatus.RUNNING],
    description="monthly",
)
MISSING_CST = "ydid:cst:000000:00000000-0000-0000-eeee-000000000001"
MISSING_CRT = "ydid:crt:000000:00000000-0000-0000-eeee-000000000002"
SOURCE_ID = "ydid:compsrc:000000:00000000-0000-0000-eeee-000000000003"
REQUIREMENT_ID = "ydid:compreq:000000:00000000-0000-0000-eeee-000000000004"


@pytest.mark.parametrize(
    ("model", "property_", "value"),
    [
        (SourcesAllowance, "sourceCreatedFromId", MISSING_CST),
        (RequirementsAllowance, "requirementCreatedFromId", MISSING_CRT),
        (SourceAllowance, "sourceId", SOURCE_ID),
        (RequirementAllowance, "requirementId", REQUIREMENT_ID),
    ],
    ids=["template-gone", "requirement-template-gone", "source", "requirement"],
)
def test_an_allowance_reference_that_cannot_be_named_is_noted(
    platform, model, property_, value
):
    allowance = model(**_ALLOWANCE_TERMS, **{property_: value})
    platform.client.compute_client.get_compute_source_template.side_effect = (
        _not_found()
    )
    platform.client.compute_client.get_compute_requirement_template_by_id.side_effect = _not_found()
    platform.client.compute_client.get_compute_requirement_template.side_effect = (
        _not_found()
    )
    platform.holding(RN_ALLOWANCE, allowance)
    (exported,) = _export(platform, ET_ALLOWANCES)
    assert exported.specification[property_] == value
    assert exported.references == ()
    (note,) = exported.notes
    assert note.startswith("Allowance 'monthly': ")
    assert value in note
    assert "written as its ID" in note


def test_a_keyring_that_cannot_be_read_leaves_out_its_credentials_alone(platform):
    readable = _keyring_with_credentials(
        platform, "aws-keys", KeyringCredential(name="aws-prod", type=AWS_CREDENTIAL)
    )
    refused = _keyring_with_credentials(
        platform, "azure-keys", KeyringCredential(name="az", type=AWS_CREDENTIAL)
    )
    read = platform.client.keyring_client.get_keyring.side_effect

    def _get_keyring(ydid: str):
        if ydid == refused.id:
            raise _forbidden()
        return read(ydid)

    platform.client.keyring_client.get_keyring.side_effect = _get_keyring
    errors: list[str] = []
    with patch.object(resource_export, "print_error", errors.append):
        specifications, records = export_specifications(
            _ctx(platform),
            ExportOptions(types=(ET_CREDENTIALS,)),
            warn=lambda message: None,
        )
    assert [s["keyringName"] for s in specifications] == [readable.name]
    (skipped,) = [r for r in records if r.outcome == "skipped"]
    assert skipped.name == "azure-keys"
    (error,) = errors
    assert "azure-keys" in error
    # The failure keeps the refusal's exit code
    with pytest.raises(ReportedFailure) as raised:
        export_resources(
            _ctx(platform),
            ExportOptions(types=(ET_CREDENTIALS,)),
        )
    assert classify(raised.value) == ExitCode.PERMISSION


def test_a_keyring_refused_for_authentication_stops_the_export(platform):
    _keyring_with_credentials(
        platform, "aws-keys", KeyringCredential(name="aws-prod", type=AWS_CREDENTIAL)
    )
    response = requests.Response()
    response.status_code = 401
    platform.client.keyring_client.get_keyring.side_effect = HTTPError(
        "unauthorised", response=response
    )
    with pytest.raises(HTTPError):
        export_specifications(
            _ctx(platform),
            ExportOptions(types=(ET_CREDENTIALS,)),
            warn=lambda message: None,
        )
