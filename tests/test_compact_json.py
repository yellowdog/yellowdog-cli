"""
Unit tests for yellowdog_cli.utils.compact_json
"""

import json

import pytest

from yellowdog_cli.utils.compact_json import CompactJSONEncoder


def _enc(data, **kwargs) -> str:
    return json.dumps(data, cls=CompactJSONEncoder, **kwargs)


class TestSmallContainers:
    """
    Small containers (few items, short repr) go on a single line.
    """

    def test_small_list(self):
        assert _enc([1, 2, 3]) == "[1, 2, 3]"

    def test_single_element_list(self):
        assert _enc([42]) == "[42]"

    def test_small_dict(self):
        assert _enc({"a": 1, "b": 2}) == '{"a": 1, "b": 2}'

    def test_empty_list(self):
        assert _enc([]) == "[]"

    def test_empty_dict(self):
        assert _enc({}) == "{}"

    def test_string_values(self):
        result = _enc(["hello", "world"])
        assert result == '["hello", "world"]'

    def test_mixed_primitive_types(self):
        result = _enc([True, None, 3.14, "x"])
        assert result.startswith("[")
        assert result.endswith("]")
        parsed = json.loads(result)
        assert parsed == [True, None, 3.14, "x"]


class TestLargeContainers:
    """
    Containers exceeding MAX_ITEMS or MAX_WIDTH are expanded across lines.
    """

    def test_list_over_max_items(self):
        data = list(range(11))  # 11 > MAX_ITEMS = 10
        result = _enc(data)
        assert result.startswith("[\n")
        assert result.endswith("\n]")

    def test_list_at_max_items_stays_inline(self):
        data = list(range(10))  # exactly MAX_ITEMS = 10
        result = _enc(data)
        assert "\n" not in result

    def test_list_over_max_width(self):
        # 5 x 22-char strings -> repr > MAX_WIDTH = 100 chars -> multi-line
        data = ["x" * 22] * 5
        result = _enc(data)
        assert result.startswith("[\n")

    def test_large_dict_expanded(self):
        data = {f"key{i}": "x" * 20 for i in range(4)}
        result = _enc(data)
        assert result.startswith("{\n")
        assert result.endswith("\n}")

    def test_expanded_list_is_valid_json(self):
        data = list(range(15))
        assert json.loads(_enc(data)) == data

    def test_expanded_dict_is_valid_json(self):
        data = {f"k{i}": i for i in range(15)}
        assert json.loads(_enc(data)) == data


class TestNestedContainers:
    """
    Containers that hold other containers are never put on a single line.
    """

    def test_list_of_lists(self):
        result = _enc([[1, 2], [3, 4]])
        assert result.startswith("[\n")

    def test_list_of_dicts(self):
        result = _enc([{"a": 1}, {"b": 2}])
        assert result.startswith("[\n")

    def test_dict_with_list_value(self):
        result = _enc({"key": [1, 2, 3]})
        assert result.startswith("{\n")

    def test_dict_with_dict_value(self):
        result = _enc({"outer": {"inner": 1}})
        assert result.startswith("{\n")

    def test_nested_output_is_valid_json(self):
        data = {"items": [{"x": 1}, {"x": 2}], "counts": [1, 2, 3]}
        assert json.loads(_enc(data)) == data


class TestFloatFormatting:
    """
    Floats are serialized at full precision, identically to json.dumps.
    """

    def test_regular_float(self):
        assert _enc(3.14) == "3.14"

    def test_whole_float_keeps_decimal_point(self):
        assert _enc(1.0) == "1.0"

    @pytest.mark.parametrize("value", [1234567.89, 0.123456789, 1e15, 1.23e-7])
    def test_full_precision_round_trip(self, value):
        assert json.loads(_enc(value)) == value
        assert json.loads(_enc({"v": [value]})) == {"v": [value]}

    def test_float_in_list_formatted(self):
        assert _enc([1.0, 2.5]) == "[1.0, 2.5]"

    def test_float_in_dict_formatted(self):
        assert _enc({"v": 3.0}) == '{"v": 3.0}'


class TestDefaultIndent:
    def test_default_indent_is_4(self):
        enc = CompactJSONEncoder()
        assert enc.indent == 4

    def test_explicit_indent_none_becomes_4(self):
        enc = CompactJSONEncoder(indent=None)
        assert enc.indent == 4

    def test_custom_indent_applied(self):
        data = list(range(11))
        result = _enc(data, indent=2)
        # Expanded list: each element should be indented by 2 spaces
        assert "  " in result

    def test_string_indent_applied(self):
        data = list(range(11))
        result = json.dumps(data, cls=CompactJSONEncoder, indent="\t")
        assert "\t" in result


class TestIterencode:
    def test_iterencode_matches_encode(self):
        enc = CompactJSONEncoder()
        data = {"a": [1, 2, 3], "b": list(range(11))}
        assert enc.iterencode(data) == enc.encode(data)


class TestRoundTrip:
    """
    Encoded output must always be valid JSON that round-trips correctly.
    """

    @pytest.mark.parametrize(
        "data",
        [
            [1, 2, 3],
            list(range(15)),
            {"name": "test", "values": [1, 2, 3]},
            {"nested": {"a": 1, "b": [1, 2, 3]}},
            [{"x": i} for i in range(5)],
            {"floats": [1.0, 2.5, 3.14]},
            {"empty_list": [], "empty_dict": {}},
        ],
    )
    def test_round_trip(self, data):
        assert json.loads(_enc(data)) == data
