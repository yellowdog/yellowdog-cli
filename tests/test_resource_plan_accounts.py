"""
'yd resource plan' for Groups, Applications and Internal and External Users
(utils/resource_planners.py), against the fake Platform
(resource_plan_platform.py) on which any change fails the test: a Group's
roles, an Application's and a User's groups added and removed, an
Application's Keyrings and key regeneration, and a User not found.
"""

from json import loads as json_loads
from types import SimpleNamespace

import pytest
from yellowdog_client.model import (
    Application,
    GrantedPermissionScope,
    Group,
    GroupRole,
    InternalUser,
    NamespaceRef,
    RoleSummary,
)

import yellowdog_cli.utils.results as results_module
import yellowdog_cli.utils.wrapper as wrapper_module
from tests.resource_plan_platform import (  # noqa: F401 (the fixture)
    FakePlatform,
    platform,
)
from yellowdog_cli.utils import output_settings, resource_creation
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    RN_APPLICATION,
    RN_EXTERNAL_USER,
    RN_GROUP,
    RN_INTERNAL_USER,
)
from yellowdog_cli.utils.exit_codes import NotFoundError
from yellowdog_cli.utils.resource_creation import CreateOptions
from yellowdog_cli.utils.resource_plan import (
    Change,
    PlanOptions,
    ToBeCreated,
    plan_one,
    plan_resources,
)

# Values that would be secrets, were the fake to hand any out: none may
# reach the plan's output
API_KEY_ID = "ydid:apikey:000000:secret-key-id"
API_KEY_SECRET = "s3cr3t-application-key-secret"


def _ctx(platform: FakePlatform) -> RunContext:
    return RunContext(SimpleNamespace(), wrapper_module.CONFIG_COMMON, platform.client)


def _plan(
    platform: FakePlatform,
    resource_type: str,
    resource: dict,
    planned: set[tuple[str, str]] | None = None,
):
    return plan_one(_ctx(platform), resource_type, resource, None, planned or set())


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
    # A Group's ID well-formed, since a Group may be named by its ID
    number = len(platform.held.get(RN_GROUP, [])) + 1
    group = Group(
        name=name, description=f"{name} group", roles=list(roles), adminGroup=False
    )
    group.id = f"ydid:group:000000:00000000-0000-0000-0000-{number:012d}"
    return platform.holding(RN_GROUP, group)


def _spec_role(name: str, *namespaces: str) -> dict:
    scope = (
        {"global": False, "namespaces": [{"namespace": n} for n in namespaces]}
        if namespaces
        else {"global": True}
    )
    return {"role": {"name": name}, "scope": scope}


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


def test_a_new_group_is_created(platform):
    entry = _plan(platform, RN_GROUP, {"name": "renderers"})
    assert (entry.action, entry.name, entry.id) == ("create", "renderers", None)


def test_group_roles_added_and_removed(platform):
    viewer, admin = _role(platform, "work-viewer"), _role(platform, "work-admin")
    _role(platform, "work-manager")
    held = _group(
        platform, "renderers", _group_role(viewer), _group_role(admin, "team-a")
    )
    spec = {
        "name": "renderers",
        "description": "renderers group",
        "roles": [_spec_role("work-viewer"), _spec_role("work-manager", "team-a")],
    }
    entry = _plan(platform, RN_GROUP, spec)
    assert (entry.action, entry.id) == ("update", held.id)
    assert entry.changes == (
        Change("roles", None, "work-manager in team-a", "added"),
        Change("roles", "work-admin in team-a", None, "removed"),
    )


def test_a_role_scope_change_is_one_removed_and_one_added(platform):
    viewer = _role(platform, "work-viewer")
    _group(platform, "renderers", _group_role(viewer, "team-a"))
    entry = _plan(
        platform,
        RN_GROUP,
        {
            "name": "renderers",
            "description": "renderers group",
            "roles": [_spec_role("work-viewer", "team-a", "team-b")],
        },
    )
    assert entry.changes == (
        Change("roles", None, "work-viewer in team-a, team-b", "added"),
        Change("roles", "work-viewer in team-a", None, "removed"),
    )


def test_group_roles_not_compared_without_roles(platform):
    viewer = _role(platform, "work-viewer")
    held = _group(platform, "renderers", _group_role(viewer))
    entry = _plan(
        platform, RN_GROUP, {"name": "renderers", "description": "renderers group"}
    )
    assert (entry.action, entry.id, entry.changes) == ("unchanged", held.id, ())

    entry = _plan(platform, RN_GROUP, {"name": "renderers", "description": "new"})
    assert entry.changes == (
        Change("description", "renderers group", "new", "changed"),
    )


def test_matching_roles_are_unchanged(platform):
    viewer = _role(platform, "work-viewer")
    _group(platform, "renderers", _group_role(viewer, "team-a"))
    entry = _plan(
        platform,
        RN_GROUP,
        {
            "name": "renderers",
            "description": "renderers group",
            "roles": [_spec_role("work-viewer", "team-a")],
        },
    )
    assert entry.action == "unchanged"


def test_an_unknown_role_fails_the_group(platform):
    _group(platform, "renderers")
    with pytest.raises(NotFoundError, match="Role 'nope' not found"):
        _plan(platform, RN_GROUP, {"name": "renderers", "roles": [_spec_role("nope")]})


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------


@pytest.fixture
def regenerating():
    """
    The plan's options as the real run's, '--regenerate-app-keys' given,
    for one test.
    """
    with resource_creation.options_in_effect(CreateOptions(regenerate_app_keys=True)):
        yield


def _application(platform: FakePlatform, name: str, *groups: Group) -> Application:
    held = platform.holding(
        RN_APPLICATION,
        Application(name=name, description="app", createdByUserId="ydid:user:000000:1"),
    )
    platform.member_of(held.id, *groups)
    return held


def test_a_new_application_is_created(platform):
    _group(platform, "renderers")
    entry = _plan(
        platform,
        RN_APPLICATION,
        {"name": "app", "groups": ["renderers"], "keyrings": ["kr"]},
    )
    assert (entry.action, entry.name, entry.id) == ("create", "app", None)


def test_application_groups_and_keyrings(platform, regenerating):
    renderers, viewers = _group(platform, "renderers"), _group(platform, "viewers")
    _group(platform, "admins")
    held = _application(platform, "app", renderers, viewers)
    entry = _plan(
        platform,
        RN_APPLICATION,
        {
            "name": "app",
            "description": "app",
            "groups": ["renderers", "admins", "new-group"],
            "keyrings": ["kr-1", "kr-2"],
        },
        planned={(RN_GROUP, "new-group")},
    )
    assert (entry.action, entry.id) == ("update", held.id)
    assert entry.changes == (
        Change("groups", None, "admins", "added"),
        Change("groups", None, ToBeCreated("new-group"), "added"),
        Change("groups", "viewers", None, "removed"),
        Change("keyrings", None, "kr-1", "added"),
        Change("keyrings", None, "kr-2", "added"),
        Change("apiKey", None, "regenerated", "changed"),
    )


def test_application_groups_not_compared_without_groups(platform):
    held = _application(platform, "app", _group(platform, "renderers"))
    entry = _plan(platform, RN_APPLICATION, {"name": "app", "description": "app"})
    assert (entry.action, entry.id, entry.changes) == ("unchanged", held.id, ())

    entry = _plan(platform, RN_APPLICATION, {"name": "app"})
    assert entry.changes == (Change("description", "app", None, "cleared"),)


def test_an_unknown_group_fails_the_application(platform):
    _application(platform, "app")
    with pytest.raises(NotFoundError, match="Group 'nope' not found"):
        _plan(platform, RN_APPLICATION, {"name": "app", "groups": ["nope"]})


def test_keyrings_on_an_existing_application_need_its_key(platform):
    _application(platform, "app")
    with pytest.raises(ValueError, match="--regenerate-app-keys"):
        _plan(platform, RN_APPLICATION, {"name": "app", "keyrings": ["kr"]})


def _configured(json_output: bool) -> None:
    output_settings.configure_output(
        SimpleNamespace(json_output=json_output, no_format=True, quiet=False)
    )


@pytest.mark.parametrize("json_output", [False, True])
def test_application_key_regeneration_shows_no_key(platform, capsys, json_output):
    held = _application(platform, "app")
    # Were the plan to regenerate the key, the fake fails the test: the key
    # it would hand back is never asked for, so never shown
    _configured(json_output)
    results_module.reset_results()
    try:
        plan_resources(
            _ctx(platform),
            [{"resource": RN_APPLICATION, "name": "app", "description": "app"}],
            PlanOptions(json_output=json_output, regenerate_app_keys=True),
        )
        results_module.flush_results()
    finally:
        results_module.reset_results()
    out, err = capsys.readouterr()
    shown = out + err
    if json_output:
        [record] = json_loads(out)
        assert record["action"] == "update"
        assert record["changes"] == [
            {"path": "apiKey", "from": None, "to": "regenerated"}
        ]
        assert set(record) <= {"resource", "name", "id", "action", "changes"}
    else:
        assert "apiKey: would be regenerated" in out
    for secret in (API_KEY_ID, API_KEY_SECRET, "apiKeyId", "apiKeySecret"):
        assert secret not in shown
    assert held.id in shown
    platform.client.account_client.regenerate_application_api_key.assert_not_called()


def test_the_regeneration_option_lasts_for_the_plan_alone(platform):
    _application(platform, "app")
    plan_resources(
        _ctx(platform),
        [{"resource": RN_APPLICATION, "name": "app", "description": "app"}],
        PlanOptions(regenerate_app_keys=True),
    )
    assert resource_creation.run_options() == CreateOptions()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def _user(platform: FakePlatform, name: str, *groups: Group) -> InternalUser:
    held = platform.holding(
        RN_INTERNAL_USER,
        InternalUser(username=f"{name}@example.com", name=name),
    )
    platform.member_of(held.id, *groups)
    return held


def test_user_groups(platform):
    renderers, viewers = _group(platform, "renderers"), _group(platform, "viewers")
    _group(platform, "admins")
    held = _user(platform, "alice", renderers, viewers)
    entry = _plan(
        platform,
        RN_INTERNAL_USER,
        {"name": "alice", "groups": ["renderers", "admins", "new-group"]},
        planned={(RN_GROUP, "new-group")},
    )
    assert (entry.action, entry.name, entry.id) == (
        "update",
        "alice@example.com",
        held.id,
    )
    assert entry.changes == (
        Change("groups", None, "admins", "added"),
        Change("groups", None, ToBeCreated("new-group"), "added"),
        Change("groups", "viewers", None, "removed"),
    )


def test_a_user_found_by_id_with_groups_by_id(platform):
    renderers = _group(platform, "renderers")
    held = _user(platform, "alice", renderers)
    entry = _plan(platform, RN_INTERNAL_USER, {"id": held.id, "groups": [renderers.id]})
    assert (entry.action, entry.changes) == ("unchanged", ())


def test_a_user_without_groups_is_unchanged(platform):
    held = _user(platform, "alice", _group(platform, "renderers"))
    entry = _plan(platform, RN_INTERNAL_USER, {"username": "alice@example.com"})
    assert (entry.action, entry.id, entry.reason) == (
        "unchanged",
        held.id,
        "no groups given: left as they are",
    )


def test_an_unknown_user_fails(platform):
    with pytest.raises(NotFoundError, match="Users cannot be created"):
        _plan(platform, RN_EXTERNAL_USER, {"name": "nobody"})


def test_an_unknown_group_fails_the_user(platform):
    _user(platform, "alice")
    with pytest.raises(NotFoundError, match="Group 'nope' not found"):
        _plan(platform, RN_INTERNAL_USER, {"name": "alice", "groups": ["nope"]})


def test_the_text_lines(platform, capsys):
    viewer = _role(platform, "work-viewer")
    _group(platform, "renderers", _group_role(viewer))
    _configured(False)
    plan_resources(
        _ctx(platform),
        [
            {"resource": RN_GROUP, "name": "new-group"},
            {
                "resource": RN_GROUP,
                "name": "renderers",
                "description": "renderers group",
                "roles": [_spec_role("work-viewer", "team-a")],
            },
        ],
        PlanOptions(),
    )
    out = capsys.readouterr().out
    assert "roles: + 'work-viewer in team-a'" in out
    assert "roles: - 'work-viewer in all namespaces'" in out
