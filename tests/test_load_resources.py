"""
Unit tests for yellowdog_cli.utils.load_resources.load_resource_specifications:
a file that is not a resource specification or a list of them refused,
naming the file and the item, before anything indexes into it; and the
per-resource failure for a missing 'resource' naming no internal key.
"""

from types import SimpleNamespace

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
        monkeypatch.setattr(
            load_resources,
            "ARGS_PARSER",
            SimpleNamespace(
                resource_specifications=[str(spec)],
                jsonnet_dry_run=False,
                validate=False,
                no_resequence=False,
            ),
        )
        return load_resources.load_resource_specifications(creation_or_update=True)

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
