"""
'yd resource export' for Compute Source Templates, Compute Requirement
Templates and Machine Image Families (utils/resource_exporters.py), against
the fake Platform (resource_plan_platform.py): each exported specification
planned as 'yd resource plan' plans it, and found unchanged.
"""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
import requests
from requests.exceptions import HTTPError
from yellowdog_client.model import ImageAccess

import yellowdog_cli.utils.wrapper as wrapper_module
from tests.resource_plan_platform import (  # noqa: F401 (the fixture)
    FakePlatform,
    _clear_caches,
    platform,
)
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    ET_COMPUTE_REQUIREMENT_TEMPLATES,
    ET_COMPUTE_SOURCE_TEMPLATES,
    ET_IMAGE_FAMILIES,
    RN_IMAGE_FAMILY,
    RN_REQUIREMENT_TEMPLATE,
    RN_SOURCE_TEMPLATE,
)
from yellowdog_cli.utils.jsonnet_style import jsonnet_style
from yellowdog_cli.utils.load_resources import load_resource_specifications
from yellowdog_cli.utils.output_style import WARNING_MARKER
from yellowdog_cli.utils.resource_creation import (
    prepare_compute_requirement_template,
    prepare_compute_source_template,
    prepare_image_family,
)
from yellowdog_cli.utils.resource_export import (
    ExportOptions,
    ExportRecord,
    export_specifications,
)
from yellowdog_cli.utils.resource_exporters import (
    EXPORTERS,
    Exported,
    Reference,
    Selection,
    literal_for_jsonnet,
    specification_of,
)
from yellowdog_cli.utils.resource_plan import plan_one

AWS_INSTANCES = "co.yellowdog.platform.model.AwsInstancesComputeSource"
STATIC = "co.yellowdog.platform.model.ComputeRequirementStaticTemplate"
SPLIT = "co.yellowdog.platform.model.SplitProvisionStrategy"
NOW = "2026-11-09T12:00:00+00:00"
MISSING_CST = "ydid:cst:000000:00000000-0000-0000-eeee-000000000001"


def _ctx(platform: FakePlatform, namespace: str = "team-a") -> RunContext:
    return RunContext(
        SimpleNamespace(), SimpleNamespace(namespace=namespace), platform.client
    )


def _plan_ctx(platform: FakePlatform) -> RunContext:
    return RunContext(SimpleNamespace(), wrapper_module.CONFIG_COMMON, platform.client)


def _source_template(name: str = "aws-spot", namespace: str = "team-a", **source):
    return {
        "namespace": namespace,
        "description": "Spot instances",
        "source": {
            "type": AWS_INSTANCES,
            "name": name,
            "credential": "aws-keyring/aws-credential",
            "region": "eu-west-2",
            "securityGroupId": "sg-0123456789abcdef0",
            "instanceType": "t3.micro",
            "imageId": "ami-0123456789abcdef0",
            "limit": 10,
            **source,
        },
    }


def _requirement_template(*source_templates: str, **extra) -> dict:
    return {
        "type": STATIC,
        "name": "mixed",
        "namespace": "team-a",
        "strategyType": SPLIT,
        "sources": [
            {"sourceTemplateId": template}
            for template in (source_templates or ("aws-spot",))
        ],
        **extra,
    }


def _image_family(name: str = "fam", namespace: str = "team-a", **extra) -> dict:
    return {
        "namespace": namespace,
        "name": name,
        "osType": "LINUX",
        "imageGroups": [
            {
                "name": "g1",
                "osType": "LINUX",
                "images": [
                    {
                        "name": "i1",
                        "provider": "AWS",
                        "providerImageId": "ami-0123456789abcdef0",
                        "osType": "LINUX",
                        "regions": ["eu-west-2"],
                    }
                ],
            }
        ],
        **extra,
    }


def _hold_source_template(platform: FakePlatform, resource: dict):
    _, template = prepare_compute_source_template(
        _plan_ctx(platform), deepcopy(resource), None
    )
    # As the Platform returns it: with what it assigns
    template.source.statusMessage = "Ready"
    template.source.id = "ydid:compsrc:000000:00000000-0000-0000-eeee-000000000000"
    held = platform.holding(RN_SOURCE_TEMPLATE, template)
    _clear_caches()
    return held


def _hold_requirement_template(platform: FakePlatform, resource: dict):
    _, template, _ = prepare_compute_requirement_template(
        _plan_ctx(platform), deepcopy(resource), None
    )
    held = platform.holding(RN_REQUIREMENT_TEMPLATE, template)
    _clear_caches()
    return held


def _hold_image_family(
    platform: FakePlatform, resource: dict, access: ImageAccess = ImageAccess.PRIVATE
):
    _, family = prepare_image_family(_plan_ctx(platform), deepcopy(resource))
    family.access = access
    held = platform.holding(RN_IMAGE_FAMILY, family)
    held.createdTime = NOW
    for g, group in enumerate(held.imageGroups or []):
        group.id = f"{held.id.replace('imgfam', 'imggrp')}:{g + 1}"
        group.createdTime = NOW
        for i, image in enumerate(group.images or []):
            image.id = f"{held.id.replace('imgfam', 'image')}:{g + 1}:{i + 1}"
            image.createdTime = NOW
    _clear_caches()
    return held


def _export(
    platform: FakePlatform, export_type: str, name_glob: str | None = None
) -> list[Exported]:
    exporter = EXPORTERS[export_type]
    ctx = _ctx(platform)
    found = exporter.find(ctx, Selection(namespace="team-a", name_glob=name_glob))
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
    return entry.action


# ---------------------------------------------------------------------------
# Compute Source Templates
# ---------------------------------------------------------------------------


def test_a_source_template_round_trips_as_unchanged(platform):
    _hold_source_template(platform, _source_template(subnetId="subnet-1"))
    (exported,) = _export(platform, ET_COMPUTE_SOURCE_TEMPLATES)
    specification = exported.specification
    assert next(iter(specification)) == "resource"
    assert specification["resource"] == RN_SOURCE_TEMPLATE
    assert specification["source"]["name"] == "aws-spot"
    # Nothing the Platform assigns is written
    assert "id" not in specification["source"]
    assert "statusMessage" not in specification["source"]
    assert exported.references == ()
    assert _planned(platform, specification) == "unchanged"


def test_name_glob_matches_the_bare_name(platform):
    for name in ("aws-spot", "aws-fleet", "azure-spot"):
        _hold_source_template(platform, _source_template(name))
    _hold_source_template(platform, _source_template("aws-other", namespace="team-b"))
    exporter = EXPORTERS[ET_COMPUTE_SOURCE_TEMPLATES]
    found = exporter.find(_ctx(platform), Selection("team-a", "aws-*"))
    assert sorted(item.name for item in found) == [
        "team-a/aws-fleet",
        "team-a/aws-spot",
    ]
    found = exporter.find(_ctx(platform), Selection("team-a", "*-spot"))
    assert sorted(item.name for item in found) == [
        "team-a/aws-spot",
        "team-a/azure-spot",
    ]
    # A name, not a substring, is matched
    assert exporter.find(_ctx(platform), Selection("team-a", "aws")) == []


# ---------------------------------------------------------------------------
# Compute Requirement Templates
# ---------------------------------------------------------------------------


def test_a_requirement_template_names_its_source_templates_and_images(platform):
    _hold_image_family(platform, _image_family())
    _hold_source_template(platform, _source_template())
    _hold_requirement_template(platform, _requirement_template(imagesId="team-a/fam"))
    (exported,) = _export(platform, ET_COMPUTE_REQUIREMENT_TEMPLATES)
    specification = exported.specification
    assert [s["sourceTemplateId"] for s in specification["sources"]] == [
        "team-a/aws-spot"
    ]
    # As 'yd resource create' names a private family, which it resolves back
    assert specification["imagesId"] == "yd/team-a/fam"
    assert set(exported.references) == {
        Reference(ET_COMPUTE_SOURCE_TEMPLATES, "team-a/aws-spot"),
        Reference(ET_IMAGE_FAMILIES, "team-a/fam"),
    }
    assert exported.notes == ()
    assert _planned(platform, specification) == "unchanged"


def test_a_source_template_held_by_its_id_is_named(platform):
    held = _hold_source_template(platform, _source_template())
    _hold_requirement_template(platform, _requirement_template(held.id))
    (exported,) = _export(platform, ET_COMPUTE_REQUIREMENT_TEMPLATES)
    assert exported.specification["sources"][0]["sourceTemplateId"] == (
        "team-a/aws-spot"
    )
    assert _planned(platform, exported.specification) == "unchanged"


def test_a_reference_that_cannot_be_named_is_kept_as_its_id_and_noted(platform):
    _hold_requirement_template(platform, _requirement_template(MISSING_CST))
    (exported,) = _export(platform, ET_COMPUTE_REQUIREMENT_TEMPLATES)
    assert exported.specification["sources"][0]["sourceTemplateId"] == MISSING_CST
    assert exported.references == ()
    assert exported.notes == (
        f"Compute Requirement Template 'team-a/mixed': '{MISSING_CST}' could not be"
        " named, so is written as its ID",
    )


def test_a_platform_default_is_left_out(platform):
    _hold_source_template(platform, _source_template())
    _hold_requirement_template(platform, _requirement_template(instanceTags={}))
    (exported,) = _export(platform, ET_COMPUTE_REQUIREMENT_TEMPLATES)
    assert "instanceTags" not in exported.specification
    assert _planned(platform, exported.specification) == "unchanged"


def test_a_platform_default_property_with_a_value_is_kept(platform):
    _hold_source_template(platform, _source_template())
    _hold_requirement_template(
        platform, _requirement_template(instanceTags={"team": "a"})
    )
    (exported,) = _export(platform, ET_COMPUTE_REQUIREMENT_TEMPLATES)
    assert exported.specification["instanceTags"] == {"team": "a"}


# ---------------------------------------------------------------------------
# Machine Image Families
# ---------------------------------------------------------------------------


def test_an_image_family_is_exported_whole_and_round_trips(platform):
    _hold_image_family(platform, _image_family())
    (exported,) = _export(platform, ET_IMAGE_FAMILIES)
    specification = exported.specification
    assert next(iter(specification)) == "resource"
    assert specification["resource"] == RN_IMAGE_FAMILY
    (group,) = specification["imageGroups"]
    (image,) = group["images"]
    assert (group["name"], image["name"]) == ("g1", "i1")
    # Nothing the Platform assigns, at any level
    for written in (specification, group, image):
        assert "id" not in written
        assert "createdTime" not in written
    assert _planned(platform, specification) == "unchanged"


def _with_dependencies(
    platform: FakePlatform, *types: str
) -> tuple[list[dict], list[ExportRecord], list[str]]:
    notes: list[str] = []
    specifications, records = export_specifications(
        _ctx(platform),
        ExportOptions(
            types=types or (ET_COMPUTE_SOURCE_TEMPLATES,), with_dependencies=True
        ),
        warn=notes.append,
    )
    return specifications, records, notes


def test_public_image_families_are_never_exported(platform):
    public = _hold_image_family(
        platform, _image_family("ubuntu", namespace="yellowdog"), ImageAccess.PUBLIC
    )
    exporter = EXPORTERS[ET_IMAGE_FAMILIES]
    assert exporter.find(_ctx(platform), Selection("team-a", "ubu*")) == []
    assert exporter.find(_ctx(platform), Selection("team-a", None)) == []
    # Asked for in its own namespace, as a dependency would be
    assert exporter.find(_ctx(platform), Selection("yellowdog", "ubuntu")) == []

    # A template using it names it
    _hold_source_template(platform, _source_template(imageId=public.id))
    (exported,) = _export(platform, ET_COMPUTE_SOURCE_TEMPLATES)
    assert exported.specification["source"]["imageId"] == "yd/yellowdog/ubuntu"
    assert _planned(platform, exported.specification) == "unchanged"


@pytest.mark.parametrize("searchable", [True, False], ids=["readable", "refused"])
def test_with_dependencies_a_public_family_is_neither_followed_nor_noted(
    platform, capsys, searchable
):
    """
    A public family, YellowDog's own, is known by its own 'access', read
    from it by name, whether or not its namespace can be searched.
    """
    public = _hold_image_family(
        platform, _image_family("ubuntu", namespace="yellowdog"), ImageAccess.PUBLIC
    )
    if not searchable:
        platform.refused_image_namespaces.add("yellowdog")
    _hold_source_template(platform, _source_template(imageId=public.id))
    capsys.readouterr()
    specifications, records, notes = _with_dependencies(platform)
    assert notes == []
    assert [s["resource"] for s in specifications] == [RN_SOURCE_TEMPLATE]
    assert specifications[0]["source"]["imageId"] == "yd/yellowdog/ubuntu"
    assert [r.outcome for r in records] == ["exported"]
    captured = capsys.readouterr()
    assert WARNING_MARKER not in captured.out + captured.err


def test_a_private_family_in_another_readable_namespace_is_referred_to(platform):
    _hold_image_family(platform, _image_family("shared", namespace="team-b"))
    _hold_source_template(platform, _source_template(imageId="yd/team-b/shared"))
    (exported,) = _export(platform, ET_COMPUTE_SOURCE_TEMPLATES)
    assert exported.references == (Reference(ET_IMAGE_FAMILIES, "team-b/shared"),)


def test_a_family_not_found_is_referred_to(platform):
    # The engine notes one it cannot find under '--with-dependencies'
    _hold_source_template(platform, _source_template(imageId="yd/team-a/gone"))
    (exported,) = _export(platform, ET_COMPUTE_SOURCE_TEMPLATES)
    assert exported.references == (Reference(ET_IMAGE_FAMILIES, "team-a/gone"),)


def test_a_family_whose_access_cannot_be_read_is_not_followed(platform, capsys):
    _hold_image_family(platform, _image_family())
    _hold_source_template(platform, _source_template(imageId="yd/team-a/fam"))
    platform.refused_image_namespaces.add("team-a")
    capsys.readouterr()
    specifications, records, notes = _with_dependencies(platform)
    assert [s["resource"] for s in specifications] == [RN_SOURCE_TEMPLATE]
    assert ([r.outcome for r in records], notes) == (["exported"], [])
    captured = capsys.readouterr()
    assert WARNING_MARKER not in captured.out + captured.err


def _server_error() -> HTTPError:
    response = requests.Response()
    response.status_code = 503
    return HTTPError("unavailable", response=response)


def test_a_plain_export_reads_no_family_by_name(platform):
    """
    Whether a family is public decides only whether it is followed, so an
    export without '--with-dependencies' never asks; a lookup that would
    fail fails nothing.
    """
    _hold_image_family(platform, _image_family())
    public = _hold_image_family(
        platform, _image_family("ubuntu", namespace="yellowdog"), ImageAccess.PUBLIC
    )
    _hold_source_template(platform, _source_template("a", imageId="yd/team-a/fam"))
    _hold_source_template(platform, _source_template("b", imageId=public.id))
    by_name = platform.client.images_client.get_image_family_by_name
    by_name.side_effect = _server_error()
    specifications, records = export_specifications(
        _ctx(platform),
        ExportOptions(types=(ET_COMPUTE_SOURCE_TEMPLATES,)),
        warn=lambda message: pytest.fail(message),
    )
    assert [s["source"]["name"] for s in specifications] == ["a", "b"]
    assert [r.outcome for r in records] == ["exported", "exported"]
    assert by_name.call_count == 0


def test_with_dependencies_a_shared_family_is_read_by_name_once(platform):
    _hold_image_family(platform, _image_family())
    for n in range(20):
        image = "yd/team-a/fam" if n % 2 else "yd/team-a/fam/g1"
        _hold_source_template(platform, _source_template(f"cst-{n:02d}", imageId=image))
    by_name = platform.client.images_client.get_image_family_by_name
    specifications, _, notes = _with_dependencies(platform)
    assert notes == []
    assert [s["resource"] for s in specifications].count(RN_IMAGE_FAMILY) == 1
    assert len(specifications) == 21
    assert by_name.call_count == 1


def test_with_dependencies_a_failed_family_lookup_skips_the_family_alone(
    platform, capsys
):
    _hold_image_family(platform, _image_family())
    _hold_source_template(platform, _source_template(imageId="yd/team-a/fam"))
    platform.client.images_client.get_image_family_by_name.side_effect = _server_error()
    specifications, records, _ = _with_dependencies(platform)
    assert [s["resource"] for s in specifications] == [RN_SOURCE_TEMPLATE]
    assert [(r.resource_type, r.name, r.outcome) for r in records] == [
        (RN_SOURCE_TEMPLATE, "team-a/aws-spot", "exported"),
        (RN_IMAGE_FAMILY, "team-a/fam", "skipped"),
    ]
    assert "team-a/fam" in capsys.readouterr().err


def test_a_source_template_refers_to_its_private_family_by_group(platform):
    family = _hold_image_family(platform, _image_family())
    group_id = family.imageGroups[0].id
    _hold_source_template(platform, _source_template(imageId=group_id))
    (exported,) = _export(platform, ET_COMPUTE_SOURCE_TEMPLATES)
    assert exported.specification["source"]["imageId"] == "yd/team-a/fam/g1"
    assert exported.references == (Reference(ET_IMAGE_FAMILIES, "team-a/fam"),)


# ---------------------------------------------------------------------------
# Braces
# ---------------------------------------------------------------------------

USER_DATA = "#!/bin/bash\necho {{date}} {{ node.name }} __{{tag}}__"
DESCRIPTION = "Built {{date}} for {{ node.name }} and __{{tag}}__"


def _load(path) -> list[dict]:
    return load_resource_specifications(
        SimpleNamespace(
            resource_specifications=[str(path)],
            jsonnet_dry_run=False,
            validate=False,
            no_resequence=False,
        )
    )


def _held_with_braces(platform: FakePlatform) -> dict:
    _hold_source_template(
        platform,
        {
            **_source_template(userData=USER_DATA),
            "description": DESCRIPTION,
        },
    )
    (exported,) = _export(platform, ET_COMPUTE_SOURCE_TEMPLATES)
    return exported.specification


def _loaded_back(platform: FakePlatform, path) -> None:
    (loaded,) = _load(path)
    assert loaded["source"]["userData"] == USER_DATA
    assert loaded["description"] == DESCRIPTION


def test_braces_survive_loading_the_export(platform, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "yellowdog_cli.utils.load_resources.warn_of_violations", lambda *a: None
    )
    specification = _held_with_braces(platform)
    path = tmp_path / "export.json"
    path.write_text(json.dumps([specification]), encoding="utf-8")
    _loaded_back(platform, path)


def test_braces_survive_loading_a_jsonnet_export(platform, tmp_path, monkeypatch):
    pytest.importorskip("_jsonnet")
    monkeypatch.setattr(
        "yellowdog_cli.utils.load_resources.warn_of_violations", lambda *a: None
    )
    specification = _held_with_braces(platform)
    path = tmp_path / "export.jsonnet"
    text = json.dumps(literal_for_jsonnet([specification]))
    path.write_text(jsonnet_style(text), encoding="utf-8")
    _loaded_back(platform, path)


@pytest.mark.parametrize(
    "value, written",
    [
        ("plain", "plain"),
        ("{{date}}", "{{raw:date}}"),
        ("a {{x}} b {{y:=1}}", "a {{raw:x}} b {{raw:y:=1}}"),
        ("{{ node.name }}", "{{raw: node.name }}"),
        ("__{{tag}}__", "__{{raw:tag}}__"),
        ("{{a_{{b}}}}", "{{raw:a_{{b}}}}"),
        ("{{raw:x}}", "{{raw:raw:x}}"),
        ('{"a":{"b":1}}', '{"a":{"b":1}}'),
    ],
)
def test_every_expression_is_written_raw(value, written):
    specification = specification_of(
        RN_SOURCE_TEMPLATE, {"description": value, "list": [value]}
    )
    assert specification["description"] == written
    assert specification["list"] == [written]


@pytest.mark.parametrize("key", ["userData", "nodeEvents"])
def test_platform_mustache_is_written_raw_only_in_the_worker_pool_form(key):
    value = "{{date}} {{ node.name }} __{{tag}}__"
    specification = specification_of(RN_SOURCE_TEMPLATE, {key: {"x": [value]}})
    assert specification[key] == {"x": ["{{date}} {{ node.name }} __{{raw:tag}}__"]}
    # A Jsonnet file's text pass substitutes in every property: all are raw
    assert literal_for_jsonnet([specification])[0][key] == {
        "x": ["{{raw:date}} {{raw: node.name }} __{{raw:tag}}__"]
    }


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def test_a_dependency_with_glob_characters_in_its_name_is_found(platform):
    _hold_source_template(platform, _source_template("render[1]"))
    _hold_source_template(platform, _source_template("render1"))
    _hold_requirement_template(platform, _requirement_template("render[1]"))
    specifications, _ = export_specifications(
        _ctx(platform),
        ExportOptions(
            types=(ET_COMPUTE_REQUIREMENT_TEMPLATES,), with_dependencies=True
        ),
        warn=lambda message: pytest.fail(message),
    )
    assert [
        (s["resource"], s.get("name") or s["source"]["name"]) for s in specifications
    ] == [
        (RN_SOURCE_TEMPLATE, "render[1]"),
        (RN_REQUIREMENT_TEMPLATE, "mixed"),
    ]


# The search each templated type makes, and the property holding its name
_SEARCHES = {
    ET_COMPUTE_SOURCE_TEMPLATES: (
        "compute_client",
        "get_compute_source_templates",
        "name",
    ),
    ET_COMPUTE_REQUIREMENT_TEMPLATES: (
        "compute_client",
        "get_compute_requirement_templates",
        "name",
    ),
    ET_IMAGE_FAMILIES: ("images_client", "get_image_families", "familyName"),
}


@pytest.mark.parametrize("export_type", list(_SEARCHES))
@pytest.mark.parametrize(("glob", "searched"), [("*-spot", None), ("aws-*t", "aws-")])
def test_a_search_is_given_the_globs_literal_prefix(
    platform, export_type, glob, searched
):
    """
    As 'yd list' searches for these types: the glob's literal prefix, none
    for a glob starting with a wildcard.
    """
    client_name, method, property_ = _SEARCHES[export_type]
    EXPORTERS[export_type].find(_ctx(platform), Selection("team-a", glob))
    search_method = getattr(getattr(platform.client, client_name), method)
    assert getattr(search_method.call_args.args[0], property_) == searched
