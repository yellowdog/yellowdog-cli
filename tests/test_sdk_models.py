"""
utils/specs/sdk_models.py: the SDK-model knowledge the specification corpus and the
schema generator share -- the resource-type map, the polymorphic families,
which properties a specification can set and which it must.
"""

import dataclasses

from yellowdog_cli.utils.specs import sdk_models


def test_every_resource_type_has_a_model_entry():
    assert set(sdk_models.RESOURCE_TYPES) == set(sdk_models.MODEL_FOR_RESOURCE) | {
        "InternalUser",
        "ExternalUser",
    }


def test_every_polymorphic_class_is_a_dataclass_with_the_family_s_type_field():
    for family, classes in sdk_models.POLYMORPHIC_FAMILIES.items():
        for name in classes:
            cls = sdk_models.model_class(name)
            assert dataclasses.is_dataclass(cls), name
            field_names = {f.name for f in dataclasses.fields(cls)}
            assert ("type" in field_names) or ("action" in field_names), name


def test_required_is_a_subset_of_settable():
    for name in ("AddApplicationRequest", "MachineImageFamily", "NodeRunCommandAction"):
        required = sdk_models.required_properties(name)
        assert required <= sdk_models.settable_properties(name)
    assert sdk_models.required_properties("AddApplicationRequest") == {"name"}
    assert sdk_models.required_properties("MachineImageFamily") == {
        "namespace",
        "name",
        "osType",
    }


def test_nested_model_class_unwraps_optional_and_list():
    from yellowdog_client.model import MachineImageFamily, MachineImageGroup

    field = next(
        f for f in dataclasses.fields(MachineImageFamily) if f.name == "imageGroups"
    )
    assert sdk_models.nested_model_class(field.type) is MachineImageGroup
    assert sdk_models.nested_model_class(str) is None


def test_the_corpus_gate_imports_the_shared_knowledge():
    import resource_models

    assert resource_models.MODEL_FOR_RESOURCE is sdk_models.MODEL_FOR_RESOURCE
    assert resource_models.settable_properties is sdk_models.settable_properties
