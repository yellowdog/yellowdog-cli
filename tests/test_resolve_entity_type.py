"""
Unit tests for resolve_entity_type() in yellowdog_cli.utils.command_registry.

Tests cover:
  - exact full names
  - single uppercase synonyms (all 21)
  - unambiguous prefix matching
  - ambiguous prefix → error
  - unknown value → error
"""

import argparse

import pytest

from yellowdog_cli.utils.command_registry import (
    ENTITY_TYPES,
    SYNONYMS,
    resolve_entity_type,
)

# ---------------------------------------------------------------------------
# Exact full names
# ---------------------------------------------------------------------------


class TestExactFullNames:
    @pytest.mark.parametrize("entity_type", ENTITY_TYPES)
    def test_exact_name_resolves(self, entity_type: str):
        assert resolve_entity_type(entity_type) == entity_type


# ---------------------------------------------------------------------------
# Uppercase synonyms
# ---------------------------------------------------------------------------


class TestSynonyms:
    @pytest.mark.parametrize("synonym,expected", list(SYNONYMS.items()))
    def test_synonym_resolves_to_canonical(self, synonym: str, expected: str):
        assert resolve_entity_type(synonym) == expected

    def test_all_entity_types_have_a_synonym(self):
        assert set(SYNONYMS.values()) == set(ENTITY_TYPES)

    def test_all_synonyms_are_single_uppercase_letters(self):
        for synonym in SYNONYMS:
            assert len(synonym) == 1 and synonym.isupper(), (
                f"Synonym {synonym!r} is not a single uppercase letter"
            )

    def test_lowercase_synonym_does_not_match(self):
        # 'w' is not a registered synonym; prefix matching finds 'work-requirements'
        # and 'worker-pools' and 'workers' → ambiguous
        with pytest.raises(argparse.ArgumentTypeError, match="ambiguous"):
            resolve_entity_type("w")


# ---------------------------------------------------------------------------
# Prefix matching
# ---------------------------------------------------------------------------


class TestPrefixMatching:
    def test_unambiguous_prefix_resolves(self):
        assert resolve_entity_type("work-r") == "work-requirements"

    def test_single_char_prefix_when_unambiguous(self):
        # 'k' matches only 'keyrings'
        assert resolve_entity_type("k") == "keyrings"

    def test_ambiguous_prefix_raises(self):
        # 'work' matches work-requirements, worker-pools, workers
        with pytest.raises(argparse.ArgumentTypeError, match="ambiguous"):
            resolve_entity_type("work")

    def test_ambiguous_prefix_error_lists_matches(self):
        with pytest.raises(argparse.ArgumentTypeError) as exc_info:
            resolve_entity_type("work")
        msg = str(exc_info.value)
        assert "work-requirements" in msg
        assert "worker-pools" in msg
        assert "workers" in msg

    def test_unknown_value_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="unknown entity type"):
            resolve_entity_type("nonexistent")

    def test_unknown_value_error_lists_valid_types(self):
        with pytest.raises(argparse.ArgumentTypeError) as exc_info:
            resolve_entity_type("nonexistent")
        msg = str(exc_info.value)
        for entity_type in ENTITY_TYPES:
            assert entity_type in msg

    def test_prefix_does_not_match_synonym_namespace(self):
        # 'W' is a synonym, but 'WO' is not — falls through to prefix matching
        with pytest.raises(argparse.ArgumentTypeError, match="unknown entity type"):
            resolve_entity_type("WO")

    @pytest.mark.parametrize(
        "prefix,expected",
        [
            ("allow", "allowances"),
            ("attr", "attribute-definitions"),
            (
                "compute-r",
                None,
            ),  # ambiguous: compute-requirements + compute-requirement-templates
            ("compute-requirement-t", "compute-requirement-templates"),
            (
                "compute-requirements",
                "compute-requirements",
            ),  # full name needed to disambiguate
            ("compute-s", "compute-source-templates"),
            ("image", "image-families"),
            ("inst", "instances"),
            ("key", "keyrings"),
            ("namespace-p", "namespace-policies"),
            ("namespacep", None),  # invalid → error
        ],
    )
    def test_various_prefixes(self, prefix: str, expected: str | None):
        if expected is not None:
            assert resolve_entity_type(prefix) == expected
        else:
            with pytest.raises(argparse.ArgumentTypeError):
                resolve_entity_type(prefix)
