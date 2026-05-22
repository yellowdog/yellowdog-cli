"""
Unit tests for yellowdog_cli.utils.misc_utils

Note: split_delimited_string and remove_outer_delimiters are
tested in test_variable_processing.py; this file covers the rest.
"""

import re

import pytest
from yellowdog_client.model import (
    ComputeRequirement,
    ConfiguredWorkerPool,
    ProvisionedWorkerPool,
    WorkRequirement,
)

from yellowdog_cli.utils.misc_utils import (
    Substring,
    add_batch_number_postfix,
    camel_case_split,
    entities,
    format_yd_name,
    generate_id,
    get_delimited_string_boundaries,
    link,
    link_entity,
    pathname_relative_to_config_file,
    split_delimited_string,
)


class TestAddBatchNumberPostfix:
    @pytest.mark.parametrize(
        "name,batch,total,expected",
        [
            ("job", 0, 1, "job"),
            ("job", 0, 2, "job_1"),
            ("job", 1, 2, "job_2"),
            ("job", 0, 10, "job_01"),
            ("job", 9, 10, "job_10"),
            ("job", 0, 100, "job_001"),
            ("job", 99, 100, "job_100"),
        ],
    )
    def test_postfix(self, name, batch, total, expected):
        assert add_batch_number_postfix(name, batch, total) == expected


class TestFormatYdName:
    @pytest.mark.parametrize(
        "s,expected",
        [
            ("path/to/thing", "path-to-thing"),
            ("hello world", "hello_world"),
            ("file.name", "file_name"),
            ("UPPER", "upper"),
            ("a@b#c!d", "abcd"),
            ("My Job/2024.run test", "my_job-2024_run_test"),
        ],
    )
    def test_transformation(self, s, expected):
        assert format_yd_name(s) == expected

    @pytest.mark.parametrize(
        "s,add_prefix,expected",
        [
            ("123abc", True, "y123abc"),
            ("123abc", False, "123abc"),
            ("abc123", True, "abc123"),
        ],
    )
    def test_numeric_prefix_behaviour(self, s, add_prefix, expected):
        assert format_yd_name(s, add_prefix=add_prefix) == expected

    def test_truncated_at_60_chars(self):
        assert len(format_yd_name("a" * 70)) == 60

    def test_result_only_contains_valid_chars(self):
        result = format_yd_name("weird @#$% chars!!", add_prefix=False)
        assert re.match(r"^[a-z0-9_-]*$", result)


class TestCamelCaseSplit:
    @pytest.mark.parametrize(
        "s,expected",
        [
            ("WorkRequirement", "Work Requirement"),
            ("Hello", "Hello"),
            ("ConfiguredWorkerPool", "Configured Worker Pool"),
            ("ComputeRequirement", "Compute Requirement"),
            ("WorkerPool", "Worker Pool"),
        ],
    )
    def test_split(self, s, expected):
        assert camel_case_split(s) == expected


class TestGenerateId:
    def test_format_with_prefix(self):
        result = generate_id(prefix="test")
        # format: test_YYMMDD-HHMMSSmmm (timestamp is 17 chars)
        assert re.match(r"test_\d{6}-\d{9}$", result)

    def test_format_with_empty_prefix(self):
        result = generate_id()
        assert re.match(r"_\d{6}-\d{9}$", result)

    def test_length_fits_within_max(self):
        result = generate_id(prefix="a" * 43, max_length=60)
        assert len(result) == 60

    def test_too_long_raises(self):
        with pytest.raises(Exception, match="maximum length"):
            generate_id(prefix="a" * 44, max_length=60)

    def test_two_calls_produce_same_timestamp(self):
        # UTCNOW is module-level constant, so both IDs share the same timestamp
        id1 = generate_id(prefix="first")
        id2 = generate_id(prefix="second")
        assert id1[len("first") :] == id2[len("second") :]


class TestGetDelimitedStringBoundaries:
    def test_single_variable(self):
        result = get_delimited_string_boundaries("{{hello}}", "{{", "}}")
        assert result == [Substring(start=0, end=9)]

    def test_two_variables(self):
        result = get_delimited_string_boundaries("{{a}} and {{b}}", "{{", "}}")
        assert result == [Substring(start=0, end=5), Substring(start=10, end=15)]

    def test_no_variables(self):
        result = get_delimited_string_boundaries("no vars here", "{{", "}}")
        assert result == []

    def test_nested_delimiters(self):
        # "{{{{x}}}}" - outer {{...}} contains inner {{x}}
        result = get_delimited_string_boundaries("{{{{x}}}}", "{{", "}}")
        assert result == [Substring(start=0, end=9)]

    def test_variable_with_surrounding_text(self):
        result = get_delimited_string_boundaries("prefix {{x}} suffix", "{{", "}}")
        assert result == [Substring(start=7, end=12)]

    def test_unclosed_delimiter_raises(self):
        with pytest.raises(Exception, match="Mismatched"):
            get_delimited_string_boundaries("{{unclosed", "{{", "}}")

    def test_extra_closing_delimiter_raises(self):
        with pytest.raises(Exception, match="Mismatched"):
            get_delimited_string_boundaries("extra}}", "{{", "}}")

    def test_mismatched_count_raises(self):
        with pytest.raises(Exception, match="Mismatched"):
            get_delimited_string_boundaries("{{a}}{{b}}}}", "{{", "}}")


class TestSplitDelimitedStringEdgeCases:
    """Additional cases not covered by test_variable_processing.py"""

    def test_variable_at_end(self):
        result = split_delimited_string("text{{var}}", "{{", "}}")
        assert result == ["text", "{{var}}"]

    def test_variable_at_start(self):
        result = split_delimited_string("{{var}}text", "{{", "}}")
        assert result == ["{{var}}", "text"]

    def test_only_text_no_variables(self):
        result = split_delimited_string("plain text", "{{", "}}")
        assert result == ["plain text"]

    def test_empty_string(self):
        result = split_delimited_string("", "{{", "}}")
        assert result == [""]

    def test_adjacent_variables(self):
        # Adjacent variables produce an empty string between them
        result = split_delimited_string("{{a}}{{b}}", "{{", "}}")
        assert result == ["{{a}}", "", "{{b}}"]


class TestEntities:
    """
    entities dict maps SDK class names to their URL path segments.
    link_entity uses type(entity).__name__ as the key.
    """

    def test_all_four_types_present(self):
        assert set(entities.keys()) == {
            "ConfiguredWorkerPool",
            "ProvisionedWorkerPool",
            "WorkRequirement",
            "ComputeRequirement",
        }

    @pytest.mark.parametrize(
        "cls,expected_segment",
        [
            (ConfiguredWorkerPool, "workers"),
            (ProvisionedWorkerPool, "workers"),
            (WorkRequirement, "work"),
            (ComputeRequirement, "compute"),
        ],
    )
    def test_class_name_maps_to_correct_segment(self, cls, expected_segment):
        assert entities[cls.__name__] == expected_segment

    @pytest.mark.parametrize(
        "cls,expected_segment",
        [
            (ConfiguredWorkerPool, "workers"),
            (ProvisionedWorkerPool, "workers"),
            (WorkRequirement, "work"),
            (ComputeRequirement, "compute"),
        ],
    )
    def test_link_entity_uses_correct_path_segment(self, cls, expected_segment):
        # object.__new__ gives a bare instance so type(entity).__name__ is correct
        entity = object.__new__(cls)
        entity.id = "test-id-123"
        result = link_entity("https://app.yellowdog.ai", entity)
        assert f"#/{expected_segment}/test-id-123" in result


class TestLink:
    def test_url_and_suffix(self):
        result = link("https://api.example.com", "path/to/thing")
        assert result == "https://portal.example.com/path/to/thing"

    def test_with_display_text(self):
        result = link("https://api.example.com", "path", "My Link")
        assert result == "My Link (https://portal.example.com/path)"

    def test_no_suffix(self):
        result = link("https://api.example.com")
        assert result == "https://portal.example.com/"

    def test_path_stripped_from_base_url(self):
        # link() extracts only scheme + netloc from base_url, replacing api→portal
        result = link("https://api.example.com/ignored/path", "newpath")
        assert result == "https://portal.example.com/newpath"

    def test_text_same_as_url_returns_url_only(self):
        url = "https://portal.example.com/path"
        result = link("https://api.example.com", "path", url)
        assert result == url  # text == url → no parens


class TestPathnameRelativeToConfigFile:
    def test_basic_join(self):
        result = pathname_relative_to_config_file("/configs", "myfile.toml")
        # normpath(relpath("/configs/myfile.toml")) from cwd
        assert "myfile.toml" in result

    def test_returns_string(self):
        result = pathname_relative_to_config_file("/some/dir", "file.json")
        assert isinstance(result, str)
