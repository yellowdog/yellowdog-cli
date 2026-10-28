"""
Unit tests for the lookups in utils/entity_utils.py that tolerate some
failures and not others: the Image Family listing behind image name
resolution, the Compute Requirement Template name lookup, the
'--substitute-ids' name lookups and the Group name shown in yd-create's
messages.
"""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

import yellowdog_cli.utils.resource_creation as yd_create
import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli.utils import entity_utils
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_utils import AmbiguousNameError


def _ctx() -> RunContext:
    """
    The context a command is given: the wrapper globals, as patched.
    """
    return RunContext(
        wrapper_module.ARGS_PARSER, wrapper_module.CONFIG_COMMON, wrapper_module.CLIENT
    )


CST_ID = "ydid:cst:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class MissingPermission(Exception):
    def __str__(self) -> str:
        return "MissingPermissionException: IMAGE_READ"


@pytest.fixture(autouse=True)
def _fresh_caches():
    entity_utils.clear_image_caches()
    entity_utils.get_compute_requirement_templates.cache_clear()
    entity_utils._get_source_template_name_from_id.cache_clear()
    entity_utils.clear_group_caches()
    yield
    entity_utils.clear_image_caches()
    entity_utils.get_compute_requirement_templates.cache_clear()
    entity_utils._get_source_template_name_from_id.cache_clear()
    entity_utils.clear_group_caches()


def _image_client(families_side_effect) -> MagicMock:
    client = MagicMock()
    client.application_client.get_application_details.return_value = SimpleNamespace(
        allNamespacesReadable=True, readableNamespaces=None
    )
    client.images_client.get_image_families.side_effect = families_side_effect
    return client


# ---------------------------------------------------------------------------
# Image Families
# ---------------------------------------------------------------------------


def test_a_failed_image_family_listing_is_raised_not_passed_through():
    client = _image_client(requests.ConnectionError("refused"))
    with pytest.raises(requests.ConnectionError):
        entity_utils.get_image_name_or_id(client, "yd/ns/ubuntu")


def test_a_failed_image_family_listing_is_not_cached():
    family = SimpleNamespace(
        id="ydid:imgfam:000000:x", namespace="ns", name="ubuntu", access=None
    )
    listing = MagicMock()
    listing.list_all.return_value = [family]
    client = _image_client([requests.ConnectionError("refused"), listing])
    with pytest.raises(requests.ConnectionError):
        entity_utils.get_image_family_summaries(client)
    assert entity_utils.get_image_family_summaries(client) == [family]


def test_a_missing_permission_for_every_namespace_falls_back_quietly(capsys):
    client = _image_client(MissingPermission())
    assert entity_utils.get_image_family_summaries(client) == []
    assert "IMAGE_READ" not in capsys.readouterr().out


def test_a_missing_permission_for_a_namespace_is_warned_of(capsys):
    client = _image_client(MissingPermission())
    assert entity_utils.get_image_family_summaries(client, "ns") == []
    assert "IMAGE_READ" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Compute Requirement Templates
# ---------------------------------------------------------------------------


def _templates(*namespaces: str) -> MagicMock:
    client = MagicMock()
    client.compute_client.get_compute_requirement_templates.return_value.list_all.return_value = [
        SimpleNamespace(id=f"crt-{ns}", namespace=ns, name="gpu") for ns in namespaces
    ]
    return client


def test_a_template_name_in_two_namespaces_is_ambiguous():
    with pytest.raises(AmbiguousNameError, match="ns1, ns2"):
        entity_utils.get_compute_requirement_template_id_by_name(
            _templates("ns2", "ns1"), "gpu"
        )


def test_a_template_name_in_one_namespace_is_found():
    assert (
        entity_utils.get_compute_requirement_template_id_by_name(
            _templates("ns1"), "gpu"
        )
        == "crt-ns1"
    )


def test_a_source_template_name_in_two_namespaces_is_ambiguous():
    client = MagicMock()
    client.compute_client.get_compute_source_templates.return_value.list_all.return_value = [
        SimpleNamespace(id=f"cst-{ns}", namespace=ns, name="aws") for ns in ("b", "a")
    ]
    with pytest.raises(AmbiguousNameError, match="a, b"):
        entity_utils.get_compute_source_template_id_by_name(client, "aws")


# ---------------------------------------------------------------------------
# Names shown in place of IDs
# ---------------------------------------------------------------------------


def test_a_session_failure_naming_a_template_is_raised():
    client = MagicMock()
    client.compute_client.get_compute_source_template.side_effect = (
        requests.ConnectionError("refused")
    )
    with pytest.raises(requests.ConnectionError):
        entity_utils._get_source_template_name_from_id(client, CST_ID)


def test_any_other_failure_naming_a_template_shows_the_id():
    client = MagicMock()
    client.compute_client.get_compute_source_template.side_effect = ValueError("gone")
    assert entity_utils._get_source_template_name_from_id(client, CST_ID) == CST_ID


def test_a_group_whose_name_cannot_be_fetched_is_shown_by_its_id(monkeypatch):
    client = MagicMock()
    client.account_client.get_group.side_effect = ValueError("gone")
    monkeypatch.setattr(wrapper_module, "CLIENT", client)
    assert yd_create._group_shown(_ctx(), "ydid:grp:000000:x") == "ydid:grp:000000:x"


def test_a_group_is_shown_by_name_and_id(monkeypatch):
    client = MagicMock()
    client.account_client.get_group.return_value = SimpleNamespace(name="admins")
    monkeypatch.setattr(wrapper_module, "CLIENT", client)
    assert (
        yd_create._group_shown(_ctx(), "ydid:grp:000000:y")
        == "'admins' (ydid:grp:000000:y)"
    )


def test_split_namespace_and_name_strips_alike():
    assert entity_utils.split_namespace_and_name(" name ") == (None, "name")
    assert entity_utils.split_namespace_and_name(" ns/name ") == ("ns", "name")


# ---------------------------------------------------------------------------
# A search with no namespace, for an Application without global read access
# ---------------------------------------------------------------------------


def _application(all_readable: bool, readable: list[str] | None) -> MagicMock:
    client = MagicMock()
    client.application_client.get_application_details.return_value = SimpleNamespace(
        allNamespacesReadable=all_readable, readableNamespaces=readable
    )
    return client


@pytest.fixture
def _fresh_application_details():
    entity_utils.get_application_details.cache_clear()
    yield
    entity_utils.get_application_details.cache_clear()


class TestSearchNamespaces:
    """
    The Platform refuses an unscoped search (403, 'Specify namespaces where
    possible') from an Application that cannot read every namespace, even for
    a name in one it can, so a search with no namespace is scoped to the
    namespaces it can read.
    """

    def test_a_namespace_given_is_searched(self, _fresh_application_details):
        assert entity_utils.search_namespaces(MagicMock(), "ns") == ["ns"]

    def test_every_namespace_when_all_are_readable(self, _fresh_application_details):
        assert entity_utils.search_namespaces(_application(True, None), None) is None

    @pytest.mark.parametrize("namespace", [None, ""])
    def test_the_readable_namespaces_otherwise(
        self, namespace, _fresh_application_details
    ):
        client = _application(False, ["a", "b"])
        assert entity_utils.search_namespaces(client, namespace) == ["a", "b"]

    def test_none_readable_leaves_the_platform_to_say_why(
        self, _fresh_application_details
    ):
        # Unscoped, the Platform's 403 names the permission that is missing
        assert entity_utils.search_namespaces(_application(False, []), None) is None

    def test_the_scope_is_traced_once_per_run(
        self, _fresh_application_details, monkeypatch, caplog
    ):
        monkeypatch.setattr(entity_utils, "_SCOPES_TRACED", set())
        client = _application(False, ["a", "b"])
        with caplog.at_level(logging.DEBUG, logger="yellowdog_cli"):
            entity_utils.search_namespaces(client, None)
            entity_utils.search_namespaces(client, None)
            entity_utils.search_namespaces(client, "ns")
        assert caplog.messages == [
            "No namespace given: searching those the Application can read, 'a', 'b'"
        ]

    def test_a_template_lookup_without_a_namespace_is_scoped(
        self, _fresh_application_details
    ):
        client = _application(False, ["team-a"])
        client.compute_client.get_compute_requirement_templates.return_value.list_all.return_value = [
            SimpleNamespace(id="crt-1", namespace="team-a", name="gpu")
        ]
        assert (
            entity_utils.get_compute_requirement_template_id_by_name(client, "gpu")
            == "crt-1"
        )
        search = client.compute_client.get_compute_requirement_templates.call_args[0][0]
        assert search.namespaces == ["team-a"]


def _session_failure() -> requests.HTTPError:
    response = requests.Response()
    response.status_code = 401
    return requests.HTTPError("401 Unauthorized", response=response)


IMAGE_FAMILY_ID = "ydid:imgfam:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class TestSubstituteIdsForNames:
    """
    '--substitute-ids' on Compute Requirement and Source Templates: a name
    that cannot be found leaves the ID as it is, and a template without the
    property is left alone, but an authentication or connection failure is
    raised rather than hidden behind the IDs.
    """

    def test_a_session_failure_naming_a_crts_image_family_is_raised(self):
        client = MagicMock()
        client.images_client.get_image_family_by_id.side_effect = _session_failure()
        crt = SimpleNamespace(imagesId=IMAGE_FAMILY_ID, sources=[])
        with pytest.raises(requests.HTTPError):
            entity_utils.substitute_ids_for_names_in_crt(client, crt, substitute=True)

    def test_a_session_failure_naming_a_crt_sources_image_is_raised(self):
        client = MagicMock()
        client.images_client.get_image_family_by_id.side_effect = _session_failure()
        source = SimpleNamespace(sourceTemplateId=None, imageId=IMAGE_FAMILY_ID)
        crt = SimpleNamespace(imagesId=None, sources=[source])
        with pytest.raises(requests.HTTPError):
            entity_utils.substitute_ids_for_names_in_crt(client, crt, substitute=True)

    @pytest.mark.parametrize("image_property", ["imageId", "image"])
    def test_a_session_failure_naming_a_csts_image_is_raised(self, image_property):
        client = MagicMock()
        client.images_client.get_image_family_by_id.side_effect = _session_failure()
        cst = SimpleNamespace(
            source=SimpleNamespace(**{image_property: IMAGE_FAMILY_ID})
        )
        with pytest.raises(requests.HTTPError):
            entity_utils.substitute_image_family_id_for_name_in_cst(
                client, cst, substitute=True
            )

    def test_a_name_not_found_leaves_the_id(self):
        client = MagicMock()
        response = requests.Response()
        response.status_code = 404
        client.images_client.get_image_family_by_id.side_effect = requests.HTTPError(
            response=response
        )
        crt = SimpleNamespace(imagesId=IMAGE_FAMILY_ID, sources=None)
        result = entity_utils.substitute_ids_for_names_in_crt(
            client, crt, substitute=True
        )
        assert result.imagesId == IMAGE_FAMILY_ID

    def test_a_template_without_the_properties_is_left_alone(self):
        client = MagicMock()
        crt = SimpleNamespace(imagesId=None)  # No 'sources' at all
        assert entity_utils.substitute_ids_for_names_in_crt(client, crt, True) is crt
        cst = SimpleNamespace(source=SimpleNamespace())  # Neither image property
        assert (
            entity_utils.substitute_image_family_id_for_name_in_cst(client, cst, True)
            is cst
        )


# ---------------------------------------------------------------------------
# A reused name whose objects have all finished
# ---------------------------------------------------------------------------


def test_a_name_only_finished_work_requirements_share_finds_the_newest(monkeypatch):
    # Not whichever the search listed first: the latest run of 'nightly'
    from datetime import datetime, timezone

    from yellowdog_client.model import WorkRequirementStatus

    def summary(id_, day):
        return SimpleNamespace(
            id=id_,
            name="nightly",
            status=WorkRequirementStatus.COMPLETED,
            createdTime=datetime(2026, 10, day, tzinfo=timezone.utc),
        )

    monkeypatch.setattr(
        entity_utils,
        "get_filtered_work_requirement_summaries",
        lambda client, **k: [summary("old", 1), summary("new", 9), summary("mid", 5)],
    )
    found = entity_utils.find_work_requirement_by_name(
        MagicMock(), "nightly", "ns", [WorkRequirementStatus.RUNNING]
    )
    assert found.id == "new"


def test_a_name_only_terminated_compute_requirements_share_finds_the_newest(
    monkeypatch,
):
    from datetime import datetime, timezone

    from yellowdog_client.model import ComputeRequirementStatus

    def summary(id_, day):
        return SimpleNamespace(
            id=id_,
            name="cr",
            status=ComputeRequirementStatus.TERMINATED,
            createdTime=datetime(2026, 10, day, tzinfo=timezone.utc),
        )

    monkeypatch.setattr(
        entity_utils,
        "get_compute_requirement_summaries",
        lambda client, namespace, **k: [summary("old", 1), summary("new", 9)],
    )
    found = entity_utils.find_compute_requirement_by_name(
        MagicMock(), "cr", "ns", [ComputeRequirementStatus.RUNNING]
    )
    assert found.id == "new"


def test_a_task_groups_tasks_are_counted_across_every_slice():
    from yellowdog_client.model import SliceReference

    slices = {
        None: SimpleNamespace(items=[object()] * 1000, nextSliceId="s2"),
        "s2": SimpleNamespace(items=[object()] * 2, nextSliceId="s3"),
        "s3": SimpleNamespace(items=None, nextSliceId=None),
    }
    asked: list[SliceReference] = []

    def slice_of(reference: SliceReference) -> SimpleNamespace:
        asked.append(reference)
        return slices[reference.sliceId]

    client = MagicMock()
    client.work_client.get_tasks.return_value.slice.side_effect = slice_of
    assert entity_utils.count_tasks_in_task_group(client, "ydid:taskgrp:x") == 1002
    search = client.work_client.get_tasks.call_args.args[0]
    assert search.taskGroupId == "ydid:taskgrp:x"
    assert [r.sliceId for r in asked] == [None, "s2", "s3"]
    assert {r.size for r in asked} == {SliceReference.MAX_SIZE}


def test_a_task_name_is_taken_only_by_a_task_of_that_name_itself():
    # The Platform's name search matches a substring: 'task_1' finds 'task_10'
    client = MagicMock()
    client.work_client.get_tasks.return_value.iterate.return_value = [
        SimpleNamespace(name="task_10"),
        SimpleNamespace(name="task_11"),
    ]
    assert not entity_utils.task_name_taken(client, "ydid:taskgrp:x", "task_1")
    search = client.work_client.get_tasks.call_args.args[0]
    assert (search.taskGroupId, search.name) == ("ydid:taskgrp:x", "task_1")
    assert entity_utils.task_name_taken(client, "ydid:taskgrp:x", "task_11")
