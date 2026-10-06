"""
yd-create (utils/resource_creation.py): the behaviour its review changed. A
run exits with its failures' shared code (1 for different causes) and stops at
a session failure, recording the rest as not attempted; each failure is
printed once, naming the resource. Allowances replaced by description are
removed only once the new one exists; a Group, Role or User that does not
exist fails the resource before anything changes; without 'groups' or 'roles'
memberships are left alone, while '[]' removes them all; a dry run leaves a
template name not found unresolved; Attribute Definitions carry a timeout and
keep their exit codes; Keyring grants that fail fail the Application; and the
smaller corrections: dates, model errors, the namespace policy lookup, the
Image Family records.
"""

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from requests import HTTPError, Response

import yellowdog_cli.utils.resource_creation as yd_create
from yellowdog_cli.utils import entity_utils, resource_processing
from yellowdog_cli.utils.exit_codes import NotFoundError, ReportedFailure, classify
from yellowdog_cli.utils.interactive import NoAnswerToPrompt
from yellowdog_cli.utils.settings import RAW_REQUEST_TIMEOUT, ExitCode


def _http_error(status: int, text: str = "error") -> HTTPError:
    response = Response()
    response.status_code = status
    response._content = text.encode()
    return HTTPError(f"HTTP {status}", response=response)


def _response(status: int, text: str = "") -> Response:
    response = Response()
    response.status_code = status
    response._content = text.encode()
    return response


@pytest.fixture
def env(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(yd_create, "CLIENT", client)
    args = SimpleNamespace(
        dry_run=False,
        json_output=False,
        quiet=False,
        match_allowances_by_description=False,
        regenerate_app_keys=False,
        show_keyring_passwords=False,
    )
    monkeypatch.setattr(yd_create, "_OPTIONS", args)
    monkeypatch.setattr(
        yd_create,
        "CONFIG_COMMON",
        SimpleNamespace(namespace="ns", url="https://api.x/api", key="k", secret="s"),
    )
    monkeypatch.setattr(yd_create, "confirmed", lambda _: True)
    records: list[dict] = []

    def _record(resource_type, name, id, action, error=None, **extra):
        records.append(
            {"resource": resource_type, "name": name, "id": id, "action": action}
            | ({"error": error} if error else {})
            | extra
        )

    monkeypatch.setattr(yd_create, "record_resource", _record)
    monkeypatch.setattr(resource_processing, "record_resource", _record)
    return SimpleNamespace(client=client, args=args, records=records)


# ---------------------------------------------------------------------------
# The run: exit codes, session failures, one message per failure
# ---------------------------------------------------------------------------


def _namespaces(*names: str) -> list[dict]:
    return [{"resource": "Namespace", "name": name} for name in names]


def test_a_shared_cause_gives_its_exit_code(env):
    env.client.namespaces_client.create_namespace.side_effect = _http_error(403)
    with pytest.raises(ReportedFailure) as raised:
        yd_create.create_resources(_namespaces("a", "b"))
    assert classify(raised.value) == ExitCode.PERMISSION
    assert env.client.namespaces_client.create_namespace.call_count == 2


def test_different_causes_exit_1(env):
    env.client.namespaces_client.create_namespace.side_effect = [
        _http_error(403),
        _http_error(404),
    ]
    with pytest.raises(ReportedFailure) as raised:
        yd_create.create_resources(_namespaces("a", "b"))
    assert classify(raised.value) == ExitCode.FAILURE


def test_a_session_failure_stops_the_run(env):
    env.client.namespaces_client.create_namespace.side_effect = _http_error(401)
    with pytest.raises(ReportedFailure) as raised:
        yd_create.create_resources(_namespaces("a", "b", "c"))
    assert classify(raised.value) == ExitCode.AUTHENTICATION
    assert env.client.namespaces_client.create_namespace.call_count == 1
    assert [(r["name"], r["action"]) for r in env.records] == [
        ("a", "failed"),
        ("b", "skipped"),
        ("c", "skipped"),
    ]
    assert env.records[1]["error"].startswith("not attempted: ")


def test_a_failure_is_printed_once_naming_the_resource(env, capsys):
    env.client.keyring_client.put_credential_by_name.side_effect = _http_error(404)
    credential = {
        "resource": "Credential",
        "keyringName": "kr",
        "credential": {
            "type": "AwsCredential",
            "name": "c",
            "accessKeyId": "a",
            "secretAccessKey": "s",
        },
    }
    with pytest.raises(ReportedFailure) as raised:
        yd_create.create_resources([credential])
    output = capsys.readouterr()
    text = " ".join((output.out + output.err).split())  # Rich wraps lines
    assert text.count("Keyring 'kr' not found") == 1
    assert "Failed to create resource" not in text
    assert classify(raised.value) == ExitCode.NOT_FOUND


def test_an_unknown_resource_type_fails(env):
    with pytest.raises(ReportedFailure):
        yd_create.create_resources([{"resource": "Nonsense", "name": "x"}])
    assert env.records[0]["error"] == "Unknown resource type 'Nonsense'"


# ---------------------------------------------------------------------------
# Allowances
# ---------------------------------------------------------------------------


@pytest.fixture
def allowance_env(env, monkeypatch):
    monkeypatch.setattr(yd_create, "_get_model_object", lambda *a, **k: MagicMock())
    env.client.allowances_client.add_allowance.return_value = SimpleNamespace(id="new")
    return env


def _allowance(**values) -> dict:
    return {"type": "SourcesAllowance", "description": "d", **values}


def test_matching_allowances_are_chosen_before_and_removed_after_the_new_one(
    allowance_env, monkeypatch
):
    allowance_env.args.match_allowances_by_description = True
    calls = []
    allowance_env.client.allowances_client.add_allowance.side_effect = (
        lambda allowance: calls.append("add") or SimpleNamespace(id="new")
    )
    old = SimpleNamespace(id="old")
    monkeypatch.setattr(
        yd_create,
        "allowances_to_remove",
        lambda client, description: calls.append(("choose", description)) or [old],
    )
    monkeypatch.setattr(
        yd_create,
        "remove_allowances",
        lambda client, allowances: calls.append(("remove", allowances)) or ["old"],
    )
    yd_create.create_allowance(_allowance())
    assert calls == [("choose", "d"), "add", ("remove", [old])]
    assert [(r["id"], r["action"]) for r in allowance_env.records] == [
        ("new", "created"),
        ("old", "removed"),
    ]


def test_a_failed_creation_removes_nothing(allowance_env, monkeypatch):
    allowance_env.args.match_allowances_by_description = True
    allowance_env.client.allowances_client.add_allowance.side_effect = ValueError("bad")
    monkeypatch.setattr(
        yd_create, "allowances_to_remove", lambda *a: [SimpleNamespace(id="old")]
    )
    remove = MagicMock()
    monkeypatch.setattr(yd_create, "remove_allowances", remove)
    with pytest.raises(ValueError):
        yd_create.create_allowance(_allowance())
    remove.assert_not_called()


def test_an_unanswerable_choice_fails_before_the_new_allowance_exists(
    allowance_env, monkeypatch
):
    allowance_env.args.match_allowances_by_description = True

    def _no_answer(*a):
        raise NoAnswerToPrompt()

    monkeypatch.setattr(yd_create, "allowances_to_remove", _no_answer)
    with pytest.raises(NoAnswerToPrompt):
        yd_create.create_allowance(_allowance())
    allowance_env.client.allowances_client.add_allowance.assert_not_called()


def test_a_template_name_not_found_fails_the_allowance(allowance_env, monkeypatch):
    monkeypatch.setattr(
        yd_create, "get_compute_source_template_id_by_name", lambda *a: None
    )
    with pytest.raises(NotFoundError):
        yd_create.create_allowance(_allowance(sourceCreatedFromId="cst"))
    allowance_env.client.allowances_client.add_allowance.assert_not_called()


def test_a_dry_run_leaves_a_template_name_not_found(allowance_env, monkeypatch):
    allowance_env.args.dry_run = True
    monkeypatch.setattr(
        yd_create, "get_compute_source_template_id_by_name", lambda *a: None
    )
    shown = []
    monkeypatch.setattr(
        yd_create, "_show_dry_run_specification", lambda t, r: shown.append(r)
    )
    yd_create.create_allowance(_allowance(sourceCreatedFromId="cst"))
    assert shown[0]["sourceCreatedFromId"] == "cst"


def test_a_requirement_template_is_looked_for_in_the_configured_namespace(
    allowance_env, monkeypatch
):
    lookups = []
    monkeypatch.setattr(
        yd_create,
        "get_compute_requirement_template_id_by_name",
        lambda *a: lookups.append(a[1:]) or "crt-id",
    )
    resource = {"type": "RequirementsAllowance", "requirementCreatedFromId": "crt"}
    yd_create.create_allowance(resource)
    assert lookups == [("crt", "ns")]
    assert resource["requirementCreatedFromId"] == "crt-id"


@pytest.mark.parametrize(
    "value, expected",
    [
        (datetime(2026, 1, 2, 3, 4, 5), datetime(2026, 1, 2, 3, 4, 5)),
        (date(2026, 1, 2), datetime(2026, 1, 2)),
        ("2026-01-02 03:04:05", datetime(2026, 1, 2, 3, 4, 5)),
    ],
)
def test_allowance_dates_are_accepted_as_written(value, expected):
    assert yd_create._parsed_datetime("effectiveFrom", value) == expected


def test_an_allowance_date_that_is_no_date_is_refused():
    with pytest.raises(ValueError, match="must be a date"):
        yd_create._parsed_datetime("effectiveFrom", 3)
    with pytest.raises(ValueError, match="Unable to parse"):
        yd_create._parsed_datetime("effectiveFrom", "not a date at all")


def test_a_dry_run_shows_allowance_dates_in_iso_8601(allowance_env, monkeypatch):
    allowance_env.args.dry_run = True
    shown = []
    monkeypatch.setattr(
        yd_create, "_show_dry_run_specification", lambda t, r: shown.append(r)
    )
    yd_create.create_allowance(_allowance(effectiveFrom=datetime(2026, 1, 2, 3, 4)))
    assert shown[0]["effectiveFrom"] == "2026-01-02T03:04:00"


def test_only_exact_description_matches_are_removed(monkeypatch):
    client = MagicMock()
    client.allowances_client.get_allowances.return_value.list_all.return_value = [
        SimpleNamespace(id="old", description="d"),
        SimpleNamespace(id="other", description="d2"),
    ]
    monkeypatch.setattr(entity_utils, "confirmed", lambda _: True)
    assert entity_utils.remove_allowances_matching_description(client, "d") == ["old"]
    client.allowances_client.delete_allowance_by_id.assert_called_once_with("old")


def test_choosing_allowances_removes_none(monkeypatch):
    client = MagicMock()
    client.allowances_client.get_allowances.return_value.list_all.return_value = [
        SimpleNamespace(id="old", description="d")
    ]
    monkeypatch.setattr(entity_utils, "confirmed", lambda _: True)
    chosen = entity_utils.allowances_to_remove(client, "d")
    assert [a.id for a in chosen] == ["old"]
    client.allowances_client.delete_allowance_by_id.assert_not_called()


def test_declined_allowance_removals_are_not_counted(monkeypatch):
    client = MagicMock()
    client.allowances_client.get_allowances.return_value.list_all.return_value = [
        SimpleNamespace(id="old", description="d")
    ]
    monkeypatch.setattr(entity_utils, "confirmed", lambda _: False)
    assert entity_utils.remove_allowances_matching_description(client, "d") == []


# ---------------------------------------------------------------------------
# Groups, Roles, Applications and Users
# ---------------------------------------------------------------------------


def test_an_unknown_group_fails_an_application_before_any_change(env, monkeypatch):
    monkeypatch.setattr(yd_create, "get_group_id_by_name", lambda *a: None)
    monkeypatch.setattr(yd_create, "get_application_id_by_name", lambda *a: "aid")
    with pytest.raises(NotFoundError, match="Group 'admin' not found"):
        yd_create.create_application({"name": "a", "groups": ["admin"]})
    env.client.account_client.update_application.assert_not_called()
    env.client.account_client.remove_application_from_group.assert_not_called()


def test_an_unknown_group_fails_a_user_before_any_change(env, monkeypatch):
    monkeypatch.setattr(yd_create, "get_group_id_by_name", lambda *a: None)
    with pytest.raises(NotFoundError):
        yd_create.update_user({"name": "u", "groups": ["admin"]}, internal_user=True)
    env.client.account_client.remove_user_from_group.assert_not_called()


@pytest.fixture
def existing_application(env, monkeypatch):
    monkeypatch.setattr(yd_create, "get_application_id_by_name", lambda *a: "aid")
    monkeypatch.setattr(yd_create, "_get_model_object", lambda *a, **k: MagicMock())
    monkeypatch.setattr(yd_create, "get_group_name_by_id", lambda *a: "g")
    env.client.account_client.update_application.return_value = SimpleNamespace(
        id="aid", name="a"
    )
    summaries = MagicMock(return_value=[SimpleNamespace(id="g1")])
    monkeypatch.setattr(yd_create, "get_application_group_summaries", summaries)
    env.summaries = summaries
    return env


def test_an_application_without_groups_keeps_its_groups(existing_application):
    yd_create.create_application({"name": "a"})
    existing_application.summaries.assert_not_called()
    existing_application.client.account_client.remove_application_from_group.assert_not_called()


def test_an_application_with_no_groups_leaves_them_all(existing_application):
    yd_create.create_application({"name": "a", "groups": []})
    existing_application.client.account_client.remove_application_from_group.assert_called_once_with(
        "g1", "aid"
    )


def test_keyrings_for_an_existing_application_need_its_key(existing_application):
    with pytest.raises(ValueError, match="--regenerate-app-keys"):
        yd_create.create_application({"name": "a", "keyrings": ["kr"]})
    existing_application.client.account_client.update_application.assert_not_called()


def test_a_keyring_grant_that_fails_fails_the_application(env, monkeypatch):
    monkeypatch.setattr(yd_create, "get_application_id_by_name", lambda *a: None)
    monkeypatch.setattr(yd_create, "_get_model_object", lambda *a, **k: MagicMock())
    env.client.account_client.add_application.return_value = SimpleNamespace(
        application=SimpleNamespace(id="aid", name="a"),
        apiKey=SimpleNamespace(id="key", secret="secret"),
    )
    env.client.keyring_client.grant_application_access_to_keyring.side_effect = [
        None,
        _http_error(404),
    ]
    with pytest.raises(RuntimeError, match="Keyring\\(s\\) 'kr2'") as raised:
        yd_create.create_application({"name": "a", "keyrings": ["kr1", "kr2"]})
    assert classify(raised.value) == ExitCode.NOT_FOUND
    assert env.records[0]["action"] == "created"


@pytest.fixture
def existing_group(env, monkeypatch):
    monkeypatch.setattr(yd_create, "get_group_id_by_name", lambda *a: "gid")
    env.client.account_client.update_group.return_value = SimpleNamespace(
        id="gid",
        name="g",
        roles=[
            SimpleNamespace(
                role=SimpleNamespace(id="r1", name="role-1"),
                scope=SimpleNamespace(global_=True, namespaces=None),
            )
        ],
    )
    return env


def test_a_group_without_roles_keeps_its_roles(existing_group):
    yd_create.create_group({"name": "g"})
    existing_group.client.account_client.remove_role_from_group.assert_not_called()
    existing_group.client.account_client.add_role_to_group.assert_not_called()


def test_a_group_with_no_roles_loses_them_all(existing_group):
    yd_create.create_group({"name": "g", "roles": []})
    existing_group.client.account_client.remove_role_from_group.assert_called_once_with(
        "gid", "r1"
    )
    assert existing_group.records[-1]["rolesRemoved"] == ["role-1"]


def test_an_unknown_role_fails_the_group_before_any_change(env, monkeypatch):
    monkeypatch.setattr(yd_create, "get_group_id_by_name", lambda *a: None)
    monkeypatch.setattr(yd_create, "get_role_id_by_name", lambda *a: None)
    roles = [{"role": {"name": "nope"}, "scope": {"global": True}}]
    with pytest.raises(NotFoundError, match="Role 'nope' not found"):
        yd_create.create_group({"name": "g", "roles": roles})
    env.client.account_client.add_group.assert_not_called()


def test_a_user_without_groups_keeps_them(env, monkeypatch):
    monkeypatch.setattr(
        yd_create,
        "get_user_by_name_or_id",
        lambda client, identifier: SimpleNamespace(id="u1", name="u"),
    )
    get_user_groups = MagicMock()
    monkeypatch.setattr(yd_create, "get_user_groups", get_user_groups)
    yd_create.update_user({"name": "u"}, internal_user=False)
    get_user_groups.assert_not_called()
    assert env.records[0]["action"] == "updated"


def test_a_user_who_does_not_exist_fails(env, monkeypatch):
    monkeypatch.setattr(yd_create, "get_user_by_name_or_id", lambda *a: None)
    with pytest.raises(NotFoundError, match="User not found"):
        yd_create.update_user({"name": "u"}, internal_user=False)


def test_identifiers_naming_different_users_are_refused(env, monkeypatch):
    users = {"u": SimpleNamespace(id="u1", name="u"), "v": SimpleNamespace(id="u2")}
    monkeypatch.setattr(
        yd_create, "get_user_by_name_or_id", lambda client, i: users.get(i)
    )
    with pytest.raises(ValueError, match="different Users"):
        yd_create.update_user({"name": "u", "username": "v"}, internal_user=True)
    with pytest.raises(ValueError, match="do not match"):
        yd_create.update_user({"name": "u", "id": "u3"}, internal_user=True)


# ---------------------------------------------------------------------------
# Templates, Attribute Definitions, Namespace Policies, Image Families
# ---------------------------------------------------------------------------


@pytest.fixture
def requirement_template(env, monkeypatch):
    monkeypatch.setattr(
        yd_create, "get_compute_source_template_id_by_name", lambda **k: None
    )
    monkeypatch.setattr(yd_create, "get_image_name_or_id", lambda **k: None)
    monkeypatch.setattr(yd_create, "resolve_user_data_in_spec", lambda *a, **k: None)
    monkeypatch.setattr(yd_create, "_get_model_object", lambda *a, **k: MagicMock())
    shown = []
    monkeypatch.setattr(
        yd_create, "_show_dry_run_specification", lambda t, r: shown.append(r)
    )
    env.shown = shown
    return {
        "type": "ComputeRequirementStaticTemplate",
        "name": "t",
        "namespace": "ns",
        "sources": [{"sourceTemplateId": "cst-made-earlier"}],
    }


def test_a_dry_run_leaves_a_source_template_name_unresolved(env, requirement_template):
    env.args.dry_run = True
    yd_create.create_compute_requirement_template(requirement_template)
    assert env.shown[0]["sources"] == [{"sourceTemplateId": "cst-made-earlier"}]


def test_a_source_template_name_not_found_fails_for_real(env, requirement_template):
    with pytest.raises(NotFoundError):
        yd_create.create_compute_requirement_template(requirement_template)


def test_attribute_definitions_carry_a_timeout_and_keep_the_exit_code(env, monkeypatch):
    post = MagicMock(return_value=_response(401, "Unauthorized"))
    monkeypatch.setattr(yd_create, "post", post)
    with pytest.raises(HTTPError) as raised:
        yd_create.create_attribute_definition(
            {"name": "a", "title": "A"}, "StringAttributeDefinition"
        )
    assert post.call_args.kwargs["timeout"] == RAW_REQUEST_TIMEOUT
    assert classify(raised.value) == ExitCode.AUTHENTICATION


def test_an_existing_attribute_definition_is_updated(env, monkeypatch):
    monkeypatch.setattr(
        yd_create,
        "post",
        MagicMock(return_value=_response(400, "Attribute already exists")),
    )
    put = MagicMock(return_value=_response(200))
    monkeypatch.setattr(yd_create, "put", put)
    yd_create.create_attribute_definition(
        {"name": "a", "title": "A"}, "StringAttributeDefinition"
    )
    assert put.call_args.kwargs["timeout"] == RAW_REQUEST_TIMEOUT
    assert env.records[0]["action"] == "updated"


def test_a_namespace_policy_lookup_failure_is_not_taken_as_none(env):
    env.client.namespaces_client.get_namespace_policy.side_effect = _http_error(401)
    with pytest.raises(HTTPError):
        yd_create.create_namespace_policy({"namespace": "ns"})
    env.client.namespaces_client.save_namespace_policy.assert_not_called()


def test_a_namespace_policy_not_found_is_created(env):
    env.client.namespaces_client.get_namespace_policy.side_effect = _http_error(404)
    yd_create.create_namespace_policy({"namespace": "ns"})
    env.client.namespaces_client.save_namespace_policy.assert_called_once()
    assert env.records[0]["action"] == "created"


def test_a_new_image_family_records_its_groups_and_images(env, monkeypatch):
    first = SimpleNamespace(name="g1")
    second = SimpleNamespace(name="g2")
    monkeypatch.setattr(
        yd_create,
        "_get_model_object",
        lambda *a, **k: SimpleNamespace(name="f", imageGroups=[first, second]),
    )
    images = env.client.images_client
    images.get_image_family_by_name.side_effect = _http_error(404)
    images.add_image_family.return_value = SimpleNamespace(
        id="fam",
        imageGroups=[
            SimpleNamespace(
                id="g1", name="g1", images=[SimpleNamespace(id="i1", name="i1")]
            )
        ],
    )
    images.add_image_group.return_value = SimpleNamespace(id="g2", name="g2", images=[])
    yd_create.create_image_family({"name": "f", "namespace": "ns", "osType": "LINUX"})
    assert [(r["resource"], r["id"]) for r in env.records] == [
        ("MachineImageFamily", "fam"),
        ("MachineImageGroup", "g1"),
        ("MachineImage", "i1"),
        ("MachineImageGroup", "g2"),
    ]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_every_missing_property_is_named():
    with pytest.raises(ValueError, match="properties 'tenantId', 'clientId'"):
        yd_create._get_model_object("AzureAccountAuthenticationProperties", {})


@pytest.mark.parametrize("class_name", ["Nonsense", "ImageOsType"])
def test_an_unknown_type_is_named(class_name):
    with pytest.raises(ValueError, match=f"Unknown type '{class_name}'"):
        yd_create._get_model_object(class_name, {})


def test_a_missing_required_property_is_named_without_quotes_round_it():
    with pytest.raises(ValueError) as raised:
        yd_create.create_namespace({})
    assert str(raised.value) == "Expected property 'name' to be defined"
