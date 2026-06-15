"""
Unit tests for yellowdog_cli.utils.load_resources._resequence_resources
"""

import pytest

from yellowdog_cli.utils.load_resources import _resequence_resources
from yellowdog_cli.utils.settings import (
    RN_CREDENTIAL,
    RN_IMAGE_FAMILY,
    RN_KEYRING,
    RN_NAMESPACE,
    RN_REQUIREMENT_TEMPLATE,
    RN_SOURCE_TEMPLATE,
)


class TestResequenceResources:
    """
    _resequence_resources reorders a list of resource dicts so that
    creation dependencies are satisfied. Removal uses the reverse order.
    """

    # ------------------------------------------------------------------
    # Trivial cases
    # ------------------------------------------------------------------

    def test_single_resource_unchanged(self):
        resources = [{"resource": RN_NAMESPACE, "name": "ns"}]
        result = _resequence_resources(resources)
        assert [r["resource"] for r in result] == [RN_NAMESPACE]

    def test_empty_list_unchanged(self):
        result = _resequence_resources([])
        assert result == []

    # ------------------------------------------------------------------
    # Creation ordering (creation_or_update=True, the default)
    # ------------------------------------------------------------------

    def test_creation_order_namespace_before_keyring(self):
        resources = [
            {"resource": RN_KEYRING},
            {"resource": RN_NAMESPACE},
        ]
        result = _resequence_resources(resources, creation_or_update=True)
        types = [r["resource"] for r in result]
        assert types.index(RN_NAMESPACE) < types.index(RN_KEYRING)

    def test_creation_order_full_chain(self):
        # Submit in reverse dependency order; expect correct creation order.
        resources = [
            {"resource": RN_REQUIREMENT_TEMPLATE},
            {"resource": RN_SOURCE_TEMPLATE},
            {"resource": RN_CREDENTIAL},
            {"resource": RN_KEYRING},
            {"resource": RN_NAMESPACE},
        ]
        result = _resequence_resources(resources, creation_or_update=True)
        types = [r["resource"] for r in result]
        assert types == [
            RN_NAMESPACE,
            RN_KEYRING,
            RN_CREDENTIAL,
            RN_SOURCE_TEMPLATE,
            RN_REQUIREMENT_TEMPLATE,
        ]

    def test_already_ordered_resources_unchanged(self):
        resources = [
            {"resource": RN_NAMESPACE},
            {"resource": RN_KEYRING},
            {"resource": RN_REQUIREMENT_TEMPLATE},
        ]
        result = _resequence_resources(resources, creation_or_update=True)
        types = [r["resource"] for r in result]
        assert types == [RN_NAMESPACE, RN_KEYRING, RN_REQUIREMENT_TEMPLATE]

    # ------------------------------------------------------------------
    # Removal ordering (creation_or_update=False → reversed)
    # ------------------------------------------------------------------

    def test_removal_order_is_reversed_creation_order(self):
        resources = [
            {"resource": RN_NAMESPACE},
            {"resource": RN_KEYRING},
            {"resource": RN_REQUIREMENT_TEMPLATE},
        ]
        result = _resequence_resources(resources, creation_or_update=False)
        types = [r["resource"] for r in result]
        assert types == [RN_REQUIREMENT_TEMPLATE, RN_KEYRING, RN_NAMESPACE]

    def test_removal_requirement_template_before_namespace(self):
        resources = [
            {"resource": RN_NAMESPACE},
            {"resource": RN_REQUIREMENT_TEMPLATE},
        ]
        result = _resequence_resources(resources, creation_or_update=False)
        types = [r["resource"] for r in result]
        assert types.index(RN_REQUIREMENT_TEMPLATE) < types.index(RN_NAMESPACE)

    # ------------------------------------------------------------------
    # no_resequence flag
    # ------------------------------------------------------------------

    def test_no_resequence_preserves_original_order(self):
        from unittest.mock import patch

        resources = [
            {"resource": RN_REQUIREMENT_TEMPLATE},
            {"resource": RN_NAMESPACE},
        ]
        with patch("yellowdog_cli.utils.load_resources.ARGS_PARSER") as mock_args:
            mock_args.no_resequence = True
            result = _resequence_resources(resources, creation_or_update=True)
        types = [r["resource"] for r in result]
        assert types == [RN_REQUIREMENT_TEMPLATE, RN_NAMESPACE]

    # ------------------------------------------------------------------
    # Error cases
    # ------------------------------------------------------------------

    def test_missing_resource_key_raises(self):
        resources = [{"name": "something"}, {"resource": RN_NAMESPACE}]
        with pytest.raises(Exception, match="'resource' is not specified"):
            _resequence_resources(resources)

    def test_unknown_resource_type_warns_and_sequences_last(self):
        # Unknown types must not abort the batch: they're warned about here
        # and reported per-resource (counting as failures) in create/remove
        resources = [{"resource": "UnknownResourceType"}, {"resource": RN_NAMESPACE}]
        result = _resequence_resources(resources, creation_or_update=True)
        types = [r["resource"] for r in result]
        assert types == [RN_NAMESPACE, "UnknownResourceType"]

    def test_image_family_ordered_correctly(self):
        resources = [
            {"resource": RN_KEYRING},
            {"resource": RN_IMAGE_FAMILY},
            {"resource": RN_NAMESPACE},
        ]
        result = _resequence_resources(resources, creation_or_update=True)
        types = [r["resource"] for r in result]
        # Namespace → Keyring → ImageFamily in creation order
        assert types.index(RN_NAMESPACE) < types.index(RN_KEYRING)
        assert types.index(RN_KEYRING) < types.index(RN_IMAGE_FAMILY)
