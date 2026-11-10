"""
'yd resource plan' for Machine Image Families (utils/resource_planners.py),
the whole tree compared: the family's own properties, its Image Groups by
name and, within each, its Images by name, against the fake Platform
(resource_plan_platform.py) on which any change fails the test.
"""

from copy import deepcopy
from json import loads as json_loads
from types import SimpleNamespace

import pytest

import yellowdog_cli.utils.results as results_module
import yellowdog_cli.utils.wrapper as wrapper_module
from tests.resource_plan_platform import (  # noqa: F401 (the fixture)
    FakePlatform,
    platform,
)
from yellowdog_cli.utils import output_settings
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import RN_IMAGE_FAMILY
from yellowdog_cli.utils.resource_creation import prepare_image_family
from yellowdog_cli.utils.resource_plan import (
    Change,
    PlanOptions,
    plan_one,
    plan_resources,
)

NOW = "2026-11-09T12:00:00+00:00"


def _ctx(platform: FakePlatform) -> RunContext:
    return RunContext(SimpleNamespace(), wrapper_module.CONFIG_COMMON, platform.client)


def _plan(platform: FakePlatform, resource: dict):
    return plan_one(_ctx(platform), RN_IMAGE_FAMILY, resource, None, set())


def _image(name: str = "i1", **extra: object) -> dict:
    return {
        "name": name,
        "provider": "AWS",
        "providerImageId": "ami-0123456789abcdef0",
        "osType": "LINUX",
        "regions": ["eu-west-2"],
        **extra,
    }


def _group(name: str = "g1", images: list | None = None) -> dict:
    return {
        "name": name,
        "osType": "LINUX",
        "images": [_image()] if images is None else images,
    }


def _family(groups: list | None = None, **extra: object) -> dict:
    return {
        "namespace": "team-a",
        "name": "fam",
        "osType": "LINUX",
        "imageGroups": [_group()] if groups is None else groups,
        **extra,
    }


def _hold(platform: FakePlatform, resource: dict):
    """
    Hold the family 'resource' describes as the Platform returns it: with
    the IDs and creation times it assigns at every level.
    """
    _, family = prepare_image_family(_ctx(platform), resource)
    held = platform.holding(RN_IMAGE_FAMILY, family)
    held.createdTime = NOW
    for g, group in enumerate(held.imageGroups or []):
        group.id = f"ydid:imggrp:000000:{g}"
        group.createdTime = NOW
        for i, image in enumerate(group.images or []):
            image.id = f"ydid:image:000000:{g}-{i}"
            image.createdTime = NOW
    return held


def test_a_new_family_is_create(platform):
    entry = _plan(platform, _family())
    assert (entry.action, entry.name, entry.id) == ("create", "team-a/fam", None)
    assert entry.changes == ()


def test_the_same_tree_is_unchanged(platform):
    held = _hold(platform, _family())
    entry = _plan(platform, _family())
    assert (entry.action, entry.name, entry.id) == ("unchanged", "team-a/fam", held.id)
    assert entry.changes == ()


def test_a_family_in_another_namespace_is_create(platform):
    _hold(platform, _family(namespace="team-b"))
    assert _plan(platform, _family()).action == "create"


def test_a_group_added_and_one_removed(platform):
    _hold(platform, _family([_group("g1")]))
    entry = _plan(platform, _family([_group("g2")]))
    assert entry.action == "update"
    assert entry.changes == (
        Change("imageGroups", "g1", None, "removed"),
        Change("imageGroups", None, "g2", "added"),
    )


def test_an_image_added_and_one_removed_within_a_group(platform):
    _hold(platform, _family([_group("g1", [_image("i1")])]))
    entry = _plan(platform, _family([_group("g1", [_image("i2")])]))
    assert entry.changes == (
        Change("imageGroups[name=g1].images", "i1", None, "removed"),
        Change("imageGroups[name=g1].images", None, "i2", "added"),
    )


def test_an_image_changed_within_a_group(platform):
    _hold(platform, _family())
    changed = _family([_group("g1", [_image(providerImageId="ami-2")])])
    entry = _plan(platform, changed)
    assert entry.changes == (
        Change(
            "imageGroups[name=g1].images[name=i1].providerImageId",
            "ami-0123456789abcdef0",
            "ami-2",
            "changed",
        ),
    )


def test_the_family_alone_changed(platform):
    _hold(platform, _family())
    entry = _plan(platform, _family(metadataSpecification={"purpose": "tests"}))
    assert entry.changes == (
        Change("metadataSpecification", None, {"purpose": "tests"}, "added"),
    )


def test_groups_or_images_absent_on_one_side_are_matched_by_name(platform):
    _hold(platform, _family([_group("g1", [])]))
    entry = _plan(platform, _family([_group("g1", [_image("i1")])]))
    assert entry.changes == (
        Change("imageGroups[name=g1].images", None, "i1", "added"),
    )

    entry = _plan(platform, {**_family(), "imageGroups": []})
    assert entry.changes == (Change("imageGroups", "g1", None, "removed"),)


def test_a_missing_property_fails_as_the_real_run_does(platform):
    resource = _family()
    del resource["osType"]
    with pytest.raises(ValueError, match="osType"):
        _plan(platform, resource)


def test_an_invalid_os_type_fails_as_the_real_run_does(platform):
    with pytest.raises(ValueError, match="invalid value 'PLAN9'"):
        _plan(platform, _family(osType="PLAN9"))


def test_members_show_by_name_in_text_and_json(platform, capsys):
    _hold(platform, _family([_group("g1", [_image("i1")])]))
    specification = {
        "resource": RN_IMAGE_FAMILY,
        **_family([_group("g1", [_image("i2")]), _group("g2")]),
    }
    results_module.reset_results()
    try:
        with output_settings.configured(
            SimpleNamespace(json_output=False, no_format=True, quiet=False)
        ):
            plan_resources(_ctx(platform), [deepcopy(specification)], PlanOptions())
        out = capsys.readouterr().out
        with output_settings.configured(
            SimpleNamespace(json_output=True, no_format=True, quiet=False)
        ):
            plan_resources(_ctx(platform), [deepcopy(specification)], PlanOptions())
            capsys.readouterr()
            results_module.flush_results()
            document = json_loads(capsys.readouterr().out)
    finally:
        results_module.reset_results()
    assert "imageGroups[name=g1].images: - 'i1'" in out
    assert "imageGroups[name=g1].images: + 'i2'" in out
    assert "imageGroups: + 'g2'" in out
    assert document[-1]["changes"] == [
        {"path": "imageGroups[name=g1].images", "from": "i1", "to": None},
        {"path": "imageGroups[name=g1].images", "from": None, "to": "i2"},
        {"path": "imageGroups", "from": None, "to": "g2"},
    ]
