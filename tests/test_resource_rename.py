"""
Tests for yd resource rename (utils/resource_rename.py): a resource found by
ID or by name (in the configured namespace or 'namespace/name'), renamed in
place through its type's update, its name lookups cleared, and recorded; a
name already taken refused, the same name left unchanged, a dry run and a
declined rename renaming nothing; and the command line's checks.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from requests import HTTPError, Response

from yellowdog_cli.utils import resource_rename
from yellowdog_cli.utils.command_registry import COMMANDS, check_rename_target
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    RENAMEABLE_RESOURCE_TYPES,
    RN_APPLICATION,
    RN_GROUP,
    RN_REQUIREMENT_TEMPLATE,
    RN_SOURCE_TEMPLATE,
)
from yellowdog_cli.utils.exit_codes import NotFoundError

CST = "ydid:cst:000000:76D13D:a31f1676-4deb-4168-afa9-1af6b404d627"
CRT = "ydid:crt:000000:76D13D:3552807d-2c2c-42d2-8296-b3c827e2f539"
GROUP = "ydid:group:000000:f28e481c-f109-4213-8aef-bc9f155a29e6"
APP = "ydid:app:000000:f27eeec2-843e-4035-84f7-a08821b0ea30"


@pytest.fixture
def env(monkeypatch):
    """
    A client holding one Compute Source Template ('render-prod/aws-old'),
    one Compute Requirement Template ('render-prod/gpu-old'), one Group
    ('artists') and one Application ('pipeline'); every rename confirmed;
    the records and the caches cleared kept.
    """
    client = MagicMock()
    source = SimpleNamespace(
        id=CST, namespace="render-prod", source=SimpleNamespace(name="aws-old")
    )
    template = SimpleNamespace(id=CRT, namespace="render-prod", name="gpu-old")
    group = SimpleNamespace(id=GROUP, name="artists", description="the artists")
    app = SimpleNamespace(id=APP, name="pipeline", description="the pipeline")
    client.compute_client.get_compute_source_template.return_value = source
    client.compute_client.get_compute_requirement_template.return_value = template
    client.account_client.get_group.return_value = group
    client.account_client.get_application.return_value = app

    names = {
        (RN_SOURCE_TEMPLATE, "render-prod", "aws-old"): CST,
        (RN_REQUIREMENT_TEMPLATE, "render-prod", "gpu-old"): CRT,
        (RN_GROUP, None, "artists"): GROUP,
        (RN_APPLICATION, None, "pipeline"): APP,
    }
    looked_up: list[tuple] = []

    def finder(resource_type):
        def find(client_, name, namespace):
            looked_up.append((resource_type, namespace, name))
            return names.get((resource_type, namespace, name))

        return find

    cleared: list[str] = []
    for resource_type, renamer in list(resource_rename._RENAMERS.items()):
        monkeypatch.setitem(
            resource_rename._RENAMERS,
            resource_type,
            resource_rename._Renamer(
                renamer.shown,
                renamer.ydid_type,
                renamer.namespaced,
                finder(resource_type),
                renamer.fetch,
                renamer.name_of,
                renamer.namespace_of,
                renamer.rename,
                lambda resource_type=resource_type: cleared.append(resource_type),
            ),
        )
    records: list[dict] = []
    monkeypatch.setattr(
        resource_rename,
        "record_resource",
        lambda resource_type, name, id, action, **extra: records.append(
            {"resource": resource_type, "name": name, "id": id, "action": action}
            | extra
        ),
    )
    monkeypatch.setattr(resource_rename, "confirmed", lambda _: True)
    return SimpleNamespace(
        client=client,
        ctx=RunContext(
            args=SimpleNamespace(),  # type: ignore[arg-type]
            config=SimpleNamespace(namespace="render-prod"),  # type: ignore[arg-type]
            client=client,
        ),
        source=source,
        template=template,
        records=records,
        cleared=cleared,
        looked_up=looked_up,
    )


def rename(env, resource_type, target, new_name, dry_run=False):
    resource_rename.rename_resource(env.ctx, resource_type, target, new_name, dry_run)


def test_the_renamers_are_the_renameable_types():
    assert tuple(resource_rename._RENAMERS) == RENAMEABLE_RESOURCE_TYPES


def test_a_source_template_by_name_in_the_configured_namespace(env):
    rename(env, RN_SOURCE_TEMPLATE, "aws-old", "aws-new")
    update = env.client.compute_client.update_compute_source_template
    update.assert_called_once()
    assert update.call_args.args[0].source.name == "aws-new"
    assert env.records == [
        {
            "resource": RN_SOURCE_TEMPLATE,
            "name": "aws-new",
            "id": CST,
            "action": "renamed",
            "previousName": "aws-old",
        }
    ]
    assert env.cleared == [RN_SOURCE_TEMPLATE]


def test_a_requirement_template_by_namespace_and_name(env):
    rename(env, RN_REQUIREMENT_TEMPLATE, "render-prod/gpu-old", "gpu-new")
    update = env.client.compute_client.update_compute_requirement_template
    assert update.call_args.args[0].name == "gpu-new"
    # The new name looked for where the template is, to refuse a clash
    assert (RN_REQUIREMENT_TEMPLATE, "render-prod", "gpu-new") in env.looked_up


def test_a_group_by_name_keeps_its_description(env):
    rename(env, RN_GROUP, "artists", "render-artists")
    group_id, request = env.client.account_client.update_group.call_args.args
    assert group_id == GROUP
    assert (request.name, request.description) == ("render-artists", "the artists")


def test_an_application_by_id_needs_no_type(env):
    rename(env, None, APP, "render-pipeline")
    app_id, request = env.client.account_client.update_application.call_args.args
    assert app_id == APP
    assert (request.name, request.description) == ("render-pipeline", "the pipeline")
    assert env.records[0]["resource"] == RN_APPLICATION


def test_an_id_of_a_type_that_cannot_be_renamed_is_refused(env):
    with pytest.raises(
        ValueError, match="not the ID of a resource that can be renamed"
    ):
        rename(
            env, None, "ydid:keyring:000000:3f1e2d4c-5b6a-4c7d-8e9f-0a1b2c3d4e5f", "x"
        )


def test_an_id_of_another_type_than_given_is_refused(env):
    with pytest.raises(ValueError, match="is not the ID of a Group"):
        rename(env, RN_GROUP, APP, "x")


def test_a_namespace_on_an_account_wide_type_is_refused(env):
    with pytest.raises(ValueError, match="has no namespace"):
        rename(env, RN_GROUP, "render-prod/artists", "x")


@pytest.mark.parametrize("new_name", ["other-ns/aws-new", "  "])
def test_a_new_name_with_a_namespace_or_empty_is_refused(env, new_name):
    with pytest.raises(ValueError):
        rename(env, RN_SOURCE_TEMPLATE, "aws-old", new_name)
    env.client.compute_client.update_compute_source_template.assert_not_called()


def test_a_name_not_found_is_not_found(env):
    with pytest.raises(NotFoundError, match="'render-prod/nowhere' not found"):
        rename(env, RN_SOURCE_TEMPLATE, "nowhere", "x")


def test_an_id_not_found_is_not_found(env):
    response = Response()
    response.status_code = 404
    env.client.account_client.get_group.side_effect = HTTPError(response=response)
    with pytest.raises(NotFoundError, match=f"Group {GROUP} not found"):
        rename(env, None, GROUP, "x")


def test_a_name_another_resource_of_the_type_holds_is_refused(env, monkeypatch):
    renamer = resource_rename._RENAMERS[RN_GROUP]
    monkeypatch.setitem(
        resource_rename._RENAMERS,
        RN_GROUP,
        resource_rename._Renamer(
            renamer.shown,
            renamer.ydid_type,
            renamer.namespaced,
            lambda client, name, namespace: {"artists": GROUP, "taken": "other"}.get(
                name
            ),
            renamer.fetch,
            renamer.name_of,
            renamer.namespace_of,
            renamer.rename,
            renamer.clear,
        ),
    )
    with pytest.raises(ValueError, match="'taken' is already the name of other"):
        rename(env, RN_GROUP, "artists", "taken")
    env.client.account_client.update_group.assert_not_called()


def test_the_same_name_is_left_unchanged(env):
    rename(env, RN_SOURCE_TEMPLATE, "aws-old", "aws-old")
    env.client.compute_client.update_compute_source_template.assert_not_called()
    assert env.records[0]["action"] == "unchanged"


def test_a_dry_run_renames_nothing(env):
    rename(env, RN_SOURCE_TEMPLATE, "aws-old", "aws-new", dry_run=True)
    env.client.compute_client.update_compute_source_template.assert_not_called()
    assert env.records[0]["action"] == "would rename"
    assert env.records[0]["previousName"] == "aws-old"
    assert env.cleared == []


def test_a_declined_rename_is_skipped(env, monkeypatch):
    monkeypatch.setattr(resource_rename, "confirmed", lambda _: False)
    rename(env, RN_GROUP, "artists", "render-artists")
    env.client.account_client.update_group.assert_not_called()
    assert [(r["name"], r["action"]) for r in env.records] == [("artists", "skipped")]


def test_the_command_line_needs_a_type_with_a_name():
    parser = MagicMock()
    parser.error.side_effect = SystemExit(2)
    with pytest.raises(SystemExit):
        check_rename_target(
            SimpleNamespace(rename_target="artists", resource_type=None), parser
        )
    check_rename_target(
        SimpleNamespace(rename_target=GROUP, resource_type=None), parser
    )
    check_rename_target(
        SimpleNamespace(rename_target="artists", resource_type=RN_GROUP), parser
    )


def test_the_command_takes_only_the_renameable_types():
    (type_option,) = [
        o for o in COMMANDS["yd-resource-rename"].flat_options() if o.name == "--type"
    ]
    assert tuple(type_option.kwargs["choices"]) == RENAMEABLE_RESOURCE_TYPES
