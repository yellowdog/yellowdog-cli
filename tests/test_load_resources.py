"""
Unit tests for yellowdog_cli.utils.load_resources.load_resource_specifications:
a file that is not a resource specification or a list of them refused,
naming the file and the item, before anything indexes into it; and the
per-resource failure for a missing 'resource' naming no internal key.
"""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from yellowdog_cli.utils import load_resources, resource_processing


@pytest.fixture
def load(tmp_path, monkeypatch):
    """
    Load the specification text given, as yd-create would, returning the
    resources or raising what the loader raises.
    """
    monkeypatch.setattr(load_resources, "warn_of_violations", lambda *a: None)

    def _load(text: str) -> list[dict]:
        spec = tmp_path / "r.json"
        spec.write_text(text, encoding="utf-8")
        return load_resources.load_resource_specifications(
            SimpleNamespace(
                resource_specifications=[str(spec)],
                jsonnet_dry_run=False,
                validate=False,
                no_resequence=False,
            ),
            creation_or_update=True,
        )

    return _load


def test_an_item_that_is_no_object_is_named(load):
    with pytest.raises(ValueError, match=r"Item 2 in '.*r\.json' is a string"):
        load('[{"resource": "Keyring", "name": "k"}, "oops"]')


def test_a_file_that_is_no_object_or_list_is_named(load):
    with pytest.raises(ValueError, match=r"'.*r\.json' holds a number"):
        load("42")


def test_a_single_object_is_a_list_of_one(load):
    resources = load('{"resource": "Keyring", "name": "k"}')
    assert [r["name"] for r in resources] == ["k"]


def test_a_missing_resource_type_is_left_to_each_resource(load):
    resources = load('[{"name": "x"}, {"resource": "Keyring", "name": "k"}]')
    assert [r.get("resource") for r in resources] == ["Keyring", None]


def test_a_missing_resource_type_names_no_internal_key(monkeypatch):
    failures: list[str] = []
    monkeypatch.setattr(
        resource_processing,
        "print_error",
        lambda message: failures.append(str(message)),
    )
    monkeypatch.setattr(resource_processing, "record_resource", lambda *a, **k: None)
    with pytest.raises(Exception):
        resource_processing.process_resources(
            [{"name": "x", load_resources.RESOURCE_SOURCE_DIR: "/somewhere"}],
            lambda resource_type, specification: None,
            "create",
        )
    assert failures
    assert load_resources.RESOURCE_SOURCE_DIR not in failures[0]
    assert "'name': 'x'" in failures[0]


def test_the_order_resources_are_processed_in_is_traced(load, caplog):
    resources = load(
        '[{"resource": "ComputeRequirementTemplate", "name": "t"},'
        ' {"resource": "Keyring", "name": "k"}]'
    )
    with caplog.at_level(logging.DEBUG, logger="yellowdog_cli"):
        resource_processing.process_resources(
            resources, lambda resource_type, specification: None, "create"
        )
    assert caplog.messages[0] == (
        "To create, in this order: 1. Keyring 'k'; 2. ComputeRequirementTemplate 't'"
    )


# ---------------------------------------------------------------------------
# The resource types, written out in several places, held together
# ---------------------------------------------------------------------------


def test_the_creation_order_names_every_resource_type_once():
    from yellowdog_cli.utils.specs.sdk_models import RESOURCE_TYPES

    order = load_resources.RESOURCE_CREATION_ORDER
    assert len(order) == len(set(order))
    assert set(order) == set(RESOURCE_TYPES)


@pytest.mark.parametrize(
    "module_name, dispatch",
    [
        ("resource_creation", "_create_resource"),
        ("resource_removal", "_remove_resource"),
    ],
)
def test_every_resource_type_is_dispatched(module_name, dispatch, monkeypatch):
    """
    yd-create's and yd-remove's dispatch reaches a handler for every type in
    sdk_models.RESOURCE_TYPES, and refuses one that is not.
    """
    import importlib
    import sys

    from yellowdog_cli.utils.specs.sdk_models import RESOURCE_TYPES

    monkeypatch.setattr(sys, "argv", ["yd-create", "x.json"])
    module = importlib.import_module(f"yellowdog_cli.utils.{module_name}")
    handled: list[str] = []
    for name in dir(module):
        if name.startswith(("create_", "remove_", "update_")) and name not in (
            "create_resources",
            "remove_resources",
        ):
            monkeypatch.setattr(
                module, name, lambda *a, _name=name, **k: handled.append(_name)
            )
    monkeypatch.setattr(module, "print_warning", lambda *a, **k: handled.append("w"))
    monkeypatch.setattr(module, "record_resource", lambda *a, **k: None)
    run = getattr(module, dispatch)
    ctx = MagicMock()  # the handlers are stubbed
    for resource_type in RESOURCE_TYPES:
        before = len(handled)
        if module_name == "resource_creation":
            run(ctx, resource_type, {}, None, False)
        else:
            run(ctx, resource_type, {})
        assert len(handled) == before + 1, resource_type
    with pytest.raises(ValueError, match="Unknown resource type"):
        if module_name == "resource_creation":
            run(ctx, "NoSuchType", {}, None, False)
        else:
            run(ctx, "NoSuchType", {})


def test_per_source_gives_each_files_resources_in_file_order(tmp_path, monkeypatch):
    # For yd-remove to place each file's resources among its IDs; the whole
    # list is still re-sequenced (a Keyring is removed after a template)
    monkeypatch.setattr(load_resources, "warn_of_violations", lambda *a: None)
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    first.write_text('{"resource": "Keyring", "name": "k"}', encoding="utf-8")
    second.write_text(
        '[{"resource": "ComputeRequirementTemplate", "name": "t"},'
        ' {"resource": "Keyring", "name": "k2"}]',
        encoding="utf-8",
    )
    per_source: list[list[dict]] = []
    resources = load_resources.load_resource_specifications(
        SimpleNamespace(
            resource_specifications=[],
            jsonnet_dry_run=False,
            validate=False,
            no_resequence=False,
        ),
        creation_or_update=False,
        files=[str(first), str(second)],
        per_source=per_source,
    )
    assert [[r["name"] for r in group] for group in per_source] == [["k"], ["t", "k2"]]
    assert [r["name"] for r in resources] == ["t", "k", "k2"]
