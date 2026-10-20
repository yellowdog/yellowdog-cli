"""
Unit tests for load_config._build_dc_substitutions
"""

from yellowdog_cli.utils.load_config import _build_dc_substitutions
from yellowdog_cli.utils.settings import DEFAULT_DATA_CLIENT_PREFIX


class TestBuildDcSubstitutions:
    def test_empty_base_has_the_default_prefix(self):
        # As the data client's, so a specification finds what it uploaded
        assert _build_dc_substitutions({}) == {
            "dataClient.prefix": DEFAULT_DATA_CLIENT_PREFIX
        }

    def test_base_scalars_only(self):
        base = {"remote": "r", "bucket": "b", "prefix": "p"}
        result = _build_dc_substitutions(base)
        assert result == {
            "dataClient.remote": "r",
            "dataClient.bucket": "b",
            "dataClient.prefix": "p",
        }

    def test_base_partial_scalars(self):
        base = {"remote": "r"}
        result = _build_dc_substitutions(base)
        assert result == {
            "dataClient.remote": "r",
            "dataClient.prefix": DEFAULT_DATA_CLIENT_PREFIX,
        }
        assert "dataClient.bucket" not in result

    def test_a_profile_without_a_prefix_has_the_default(self):
        result = _build_dc_substitutions({"prod": {"remote": "r"}})
        assert result["dataClient.prod.prefix"] == DEFAULT_DATA_CLIENT_PREFIX

    def test_an_empty_prefix_is_kept(self):
        # '' is no prefix, as the data client takes it; not the default
        assert _build_dc_substitutions({"prefix": ""})["dataClient.prefix"] == ""

    def test_named_profile_inherits_base(self):
        base = {"prefix": "ns/tag", "prod": {"remote": "prod-r", "bucket": "prod-b"}}
        result = _build_dc_substitutions(base)
        assert result["dataClient.prefix"] == "ns/tag"
        assert result["dataClient.prod.remote"] == "prod-r"
        assert result["dataClient.prod.bucket"] == "prod-b"
        assert result["dataClient.prod.prefix"] == "ns/tag"

    def test_profile_overrides_base_field(self):
        base = {"remote": "base-r", "bucket": "base-b", "prod": {"remote": "prod-r"}}
        result = _build_dc_substitutions(base)
        assert result["dataClient.remote"] == "base-r"
        assert result["dataClient.prod.remote"] == "prod-r"
        assert result["dataClient.prod.bucket"] == "base-b"

    def test_multiple_profiles(self):
        base = {
            "remote": "base",
            "prod": {"bucket": "prod-b"},
            "staging": {"bucket": "staging-b", "remote": "staging-r"},
        }
        result = _build_dc_substitutions(base)
        assert result["dataClient.remote"] == "base"
        assert result["dataClient.prod.remote"] == "base"
        assert result["dataClient.prod.bucket"] == "prod-b"
        assert result["dataClient.staging.remote"] == "staging-r"
        assert result["dataClient.staging.bucket"] == "staging-b"

    def test_profiles_do_not_bleed_into_each_other(self):
        base = {
            "prod": {"bucket": "prod-b"},
            "staging": {"bucket": "staging-b"},
        }
        result = _build_dc_substitutions(base)
        assert result.get("dataClient.prod.bucket") == "prod-b"
        assert result.get("dataClient.staging.bucket") == "staging-b"
        # prod's bucket should not appear under staging and vice versa
        assert "staging" not in result.get("dataClient.prod.bucket", "")
        assert "prod" not in result.get("dataClient.staging.bucket", "")

    def test_base_section_keys_not_in_output_for_profiles(self):
        # Profile sub-table names must not appear as top-level dataClient keys
        base = {"remote": "r", "prod": {"bucket": "b"}}
        result = _build_dc_substitutions(base)
        assert "dataClient.prod" not in result

    def test_unrecognised_fields_in_profile_ignored(self):
        # Only remote/bucket/prefix are extracted; other fields are silently skipped
        base = {"prod": {"remote": "r", "bucket": "b", "unknown_field": "x"}}
        result = _build_dc_substitutions(base)
        assert set(result.keys()) == {
            "dataClient.prefix",
            "dataClient.prod.remote",
            "dataClient.prod.bucket",
            "dataClient.prod.prefix",
        }
