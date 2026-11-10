"""
'yd resource export' over the whole resource corpus (tests/resources/), on
the fake Platform (resource_plan_platform.py): every corpus file held as
'yd resource create' would make it, exported with every type, written,
loaded back and planned as 'yd resource plan' plans it, each found
unchanged (a Credential 'unknown', an Allowance 'create', a Configured
Worker Pool 'failed', as the plan always finds them); every held resource
exported; and nothing written to the Platform on the way.
"""

import json
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from resource_corpus import (
    corpus_files,
    install_variables,
    remove_variables,
    require_jsonnet,
)
from yellowdog_client.model import ImageAccess, RoleSummary

import yellowdog_cli.utils.results as results_module
from tests.resource_plan_platform import (  # noqa: F401 (the fixture)
    MUTATING_PREFIXES,
    PLAN_CHANGED_SOMETHING,
    FakePlatform,
    _clear_caches,
    corpus_ctx,
    fails_for_want_of_a_namespace,
    holding_all,
    platform,
)
from yellowdog_cli.utils import resource_creation, resource_planners
from yellowdog_cli.utils.entity_names import (
    ET_COMPUTE_REQUIREMENT_TEMPLATES,
    RN_ALLOWANCE,
    RN_CONFIGURED_POOL,
    RN_CREDENTIAL,
    RN_IMAGE_FAMILY,
    RN_INTERNAL_USER,
    RN_KEYRING,
    RN_NAMESPACE,
    RN_NAMESPACE_POLICY,
    RN_REQUIREMENT_TEMPLATE,
    RN_SOURCE_TEMPLATE,
)
from yellowdog_cli.utils.exit_codes import ReportedFailure
from yellowdog_cli.utils.load_resources import (
    load_resource_specifications,
)
from yellowdog_cli.utils.resource_export import ExportOptions, export_specifications
from yellowdog_cli.utils.resource_plan import PlanOptions, plan_resources
from yellowdog_cli.utils.resource_planners import CONFIGURED_POOL_EXISTS
from yellowdog_cli.utils.variable_substitution import VARIABLE_SUBSTITUTIONS

require_jsonnet()

# The Platform's built-in roles the corpus's Groups name
BUILT_IN_ROLES = ("work-viewer", "work-manager")

# What the plan makes of an exported specification of each type, where not
# 'unchanged': a Credential's secrets cannot be read back, an Allowance is
# never updated, and the Platform refuses a second Configured Worker Pool of
# a name
PLANNED_AS = {
    RN_CREDENTIAL: "unknown",
    RN_ALLOWANCE: "create",
    RN_CONFIGURED_POOL: "failed",
}

# Every type, Credentials included
EVERYTHING = ExportOptions(types=(), all_types=True, include_credentials=True)

# What an exported Credential's secret variables are given, to load it back
SECRET_VALUE = "exported-secret"


@pytest.fixture(autouse=True)
def _corpus_variables() -> Iterator[None]:
    previous = install_variables()
    try:
        yield
    finally:
        remove_variables(previous)


@pytest.fixture(autouse=True)
def _results() -> Iterator[None]:
    results_module.reset_results()
    yield
    results_module.reset_results()


def _holding_the_corpus(platform: FakePlatform) -> list[tuple[Path, dict]]:
    """
    Hold every corpus file's resources on the one Platform, with the
    built-in roles; gives each specification held, with its file.
    """
    for name in BUILT_IN_ROLES:
        platform.holding("Role", RoleSummary(name=name))
    held = []
    for path in corpus_files():
        held += [
            (path, specification)
            for specification in holding_all(platform, path)
            if not fails_for_want_of_a_namespace(path, specification)
        ]
    return held


def _exported(platform: FakePlatform, options: ExportOptions = EVERYTHING):
    """
    The export's specifications and records, every note recorded.
    """
    notes: list[str] = []
    specifications, records = export_specifications(
        corpus_ctx(platform), options, warn=notes.append
    )
    _clear_caches()
    return specifications, records, notes


def _loaded_back(
    specifications: list[dict], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> list[dict]:
    """
    The exported specifications written as 'yd resource export' writes them
    and loaded as 'yd resource plan' loads them, each Credential's secret
    variables given a value.
    """
    path = tmp_path / "export.json"
    path.write_text(json.dumps(specifications, indent=2), encoding="utf-8")
    for variable in _secret_variables(specifications):
        monkeypatch.setitem(VARIABLE_SUBSTITUTIONS, variable, SECRET_VALUE)
    return load_resource_specifications(
        SimpleNamespace(
            resource_specifications=[str(path)],
            jsonnet_dry_run=False,
            validate=False,
            no_resequence=False,
        )
    )


def _secret_variables(specifications: list[dict]) -> set[str]:
    return {
        value[2:-2]
        for specification in specifications
        if specification["resource"] == RN_CREDENTIAL
        for value in specification["credential"].values()
        if isinstance(value, str) and value.startswith("{{")
    }


def _plan(platform: FakePlatform, specifications: list[dict]) -> list[dict]:
    """
    The plan's record of each specification, failures included.
    """
    results_module.reset_results()
    try:
        plan_resources(corpus_ctx(platform), specifications, PlanOptions())
    except ReportedFailure:
        pass
    records = list(results_module._ITEMS)
    assert len(records) == len(specifications), records
    return records


def _guarded(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """
    requests' post() and put() as the resource libraries call them, each
    recorded and failing the test; gives the record.
    """
    posted: list[tuple] = []

    def _recorded(*args: Any, **kwargs: Any) -> None:
        posted.append((args, kwargs))
        raise AssertionError(PLAN_CHANGED_SOMETHING)

    for module in (resource_creation, resource_planners):
        for name in ("post", "put"):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, _recorded)
    return posted


def _mutations(platform: FakePlatform) -> list[str]:
    return [
        name
        for name, _, _ in platform.client.mock_calls
        if name.rsplit(".", 1)[-1].startswith(MUTATING_PREFIXES)
    ]


def _held(platform: FakePlatform) -> set[tuple[str, str]]:
    """
    Each resource the Platform holds, as (resource type, name), named as an
    export finds it: a namespaced one as 'namespace/name', a Credential as
    'keyring/credential', an Internal User by its username, an Allowance by
    its description. The built-in roles are not resources.
    """
    held: set[tuple[str, str]] = set()
    for resource_type, models in platform.held.items():
        for model in models:
            match resource_type:
                case "Role":
                    continue
                case _ if resource_type == RN_SOURCE_TEMPLATE:
                    name = f"{model.namespace}/{model.source.name}"
                case _ if resource_type in (
                    RN_REQUIREMENT_TEMPLATE,
                    RN_IMAGE_FAMILY,
                    RN_CONFIGURED_POOL,
                ):
                    name = f"{model.namespace}/{model.name}"
                case _ if resource_type == RN_KEYRING:
                    name = model.name
                    held |= {
                        (RN_CREDENTIAL, f"{model.name}/{credential.name}")
                        for credential in model.credentials
                    }
                case _ if resource_type in (RN_NAMESPACE, RN_NAMESPACE_POLICY):
                    name = model.namespace
                case _ if resource_type == RN_INTERNAL_USER:
                    name = model.username
                case _ if resource_type == RN_ALLOWANCE:
                    name = model.description
                case _:
                    name = model.name
            held.add((resource_type, name))
    held |= {
        (definition["type"].rpartition(".")[2], definition["name"])
        for definition in platform.attribute_definitions
    }
    return held


def test_every_corpus_resource_round_trips(platform, tmp_path, monkeypatch):
    _holding_the_corpus(platform)
    posted = _guarded(monkeypatch)
    specifications, records, _ = _exported(platform)
    assert not [r for r in records if r.outcome != "exported"], records

    loaded = _loaded_back(specifications, tmp_path, monkeypatch)
    planned = _plan(platform, loaded)

    for specification, record in zip(loaded, planned):
        expected = PLANNED_AS.get(specification["resource"], "unchanged")
        assert record["action"] == expected, (specification, record)
        assert "changes" not in record, (specification, record)
        if expected == "failed":
            assert record["error"] == CONFIGURED_POOL_EXISTS, record
    assert _mutations(platform) == []
    assert posted == []


def test_every_held_resource_is_exported(platform):
    _holding_the_corpus(platform)
    # A public Image Family, YellowDog's own, is never exported
    public = deepcopy(
        next(
            family
            for family in platform.held[RN_IMAGE_FAMILY]
            if family.access == ImageAccess.PRIVATE
        )
    )
    public.id, public.name, public.access = None, "public-family", ImageAccess.PUBLIC
    held_public = platform.holding(RN_IMAGE_FAMILY, public)
    _, records, _ = _exported(platform)
    exported = {(r.resource_type, r.name) for r in records}
    assert exported == _held(platform) - {
        (RN_IMAGE_FAMILY, f"{held_public.namespace}/{held_public.name}")
    }


def test_the_export_writes_nothing(platform, monkeypatch):
    _holding_the_corpus(platform)
    platform.client.reset_mock(return_value=False, side_effect=False)
    posted = _guarded(monkeypatch)
    for options in (
        EVERYTHING,
        ExportOptions(types=(), with_dependencies=True),
        ExportOptions(types=(), all_types=True, with_dependencies=True),
    ):
        _exported(platform, options)
    assert _mutations(platform) == []
    assert posted == []


def test_with_dependencies_a_template_alone_brings_its_source_templates_and_families(
    platform,
):
    _holding_the_corpus(platform)
    # The corpus's static template, its images an Image Family of the corpus
    template = next(
        held
        for held in platform.held[RN_REQUIREMENT_TEMPLATE]
        if held.name.endswith("-static-template-max")
    )
    family = next(
        held
        for held in platform.held[RN_IMAGE_FAMILY]
        if held.name.endswith("-image-family-max")
    )
    template.imagesId = family.id
    template_name = f"{template.namespace}/{template.name}"

    specifications, records, notes = _exported(
        platform,
        ExportOptions(
            types=(ET_COMPUTE_REQUIREMENT_TEMPLATES,),
            name_glob=template.name,
            with_dependencies=True,
        ),
    )

    assert notes == []
    assert [s["resource"] for s in specifications] == [
        RN_IMAGE_FAMILY,
        RN_SOURCE_TEMPLATE,
        RN_REQUIREMENT_TEMPLATE,
    ]
    assert {(r.resource_type, r.name, r.outcome, r.reason) for r in records} == {
        (RN_REQUIREMENT_TEMPLATE, template_name, "exported", None),
        (
            RN_SOURCE_TEMPLATE,
            specifications[2]["sources"][0]["sourceTemplateId"],
            "exported",
            f"a dependency of {template_name}",
        ),
        (
            RN_IMAGE_FAMILY,
            f"{family.namespace}/{family.name}",
            "exported",
            f"a dependency of {template_name}",
        ),
    }
    assert specifications[2]["imagesId"] == f"yd/{family.namespace}/{family.name}"
