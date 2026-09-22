"""
Unit tests for yellowdog_cli.utils.type_check
"""

import pytest

from yellowdog_cli.utils.type_check import (
    check_bool,
    check_dict,
    check_float,
    check_float_or_int,
    check_int,
    check_list,
    check_str,
)


class TestCheckInt:
    @pytest.mark.parametrize("value,expected", [(42, 42), (0, 0), (-7, -7)])
    def test_valid(self, value, expected):
        assert check_int(value) == expected

    def test_none_returns_none(self):
        assert check_int(None) is None

    def test_bool_accepted(self):
        # bool is a subtype of int; isinstance(True, int) is True
        assert check_int(True) is True

    @pytest.mark.parametrize("value", [1.5, "5"])
    def test_raises(self, value):
        with pytest.raises(Exception, match="Integer"):
            check_int(value)


class TestCheckFloat:
    def test_valid(self):
        assert check_float(3.14) == 3.14

    def test_none_returns_none(self):
        assert check_float(None) is None

    @pytest.mark.parametrize("value", [1, "1.5"])
    def test_raises(self, value):
        # int is not a float in Python's type system
        with pytest.raises(Exception, match="Float"):
            check_float(value)


class TestCheckFloatOrInt:
    @pytest.mark.parametrize("value,expected", [(3.14, 3.14), (5, 5)])
    def test_valid(self, value, expected):
        assert check_float_or_int(value) == expected

    def test_none_returns_none(self):
        assert check_float_or_int(None) is None

    def test_string_raises(self):
        with pytest.raises(Exception, match=r"Float.*Integer"):
            check_float_or_int("abc")

    def test_list_raises(self):
        with pytest.raises(Exception):
            check_float_or_int([1.0])


class TestCheckBool:
    @pytest.mark.parametrize("value,expected", [(True, True), (False, False)])
    def test_valid(self, value, expected):
        assert check_bool(value) is expected

    def test_none_returns_none(self):
        assert check_bool(None) is None

    @pytest.mark.parametrize("value", [1, 0, "True"])
    def test_raises(self, value):
        # type(1) != bool, even though isinstance(1, int) is True
        with pytest.raises(Exception, match="Boolean"):
            check_bool(value)


class TestCheckStr:
    @pytest.mark.parametrize("value,expected", [("hello", "hello"), ("", "")])
    def test_valid(self, value, expected):
        assert check_str(value) == expected

    def test_none_returns_none(self):
        assert check_str(None) is None

    @pytest.mark.parametrize("value", [42, ["a"]])
    def test_raises(self, value):
        with pytest.raises(Exception, match="String"):
            check_str(value)


class TestCheckList:
    @pytest.mark.parametrize("value,expected", [([1, 2, 3], [1, 2, 3]), ([], [])])
    def test_valid(self, value, expected):
        assert check_list(value) == expected

    def test_none_returns_none(self):
        assert check_list(None) is None

    @pytest.mark.parametrize("value", [(1, 2), {"a": 1}])
    def test_raises(self, value):
        with pytest.raises(Exception, match="List"):
            check_list(value)


class TestCheckDict:
    @pytest.mark.parametrize("value,expected", [({"a": 1}, {"a": 1}), ({}, {})])
    def test_valid(self, value, expected):
        assert check_dict(value) == expected

    def test_none_returns_none(self):
        assert check_dict(None) is None

    @pytest.mark.parametrize("value", [[1, 2], "{'a': 1}"])
    def test_raises(self, value):
        with pytest.raises(Exception, match="Dict"):
            check_dict(value)


class TestPropertyNameInMessage:
    """
    The property name is included in the message wherever the caller supplies
    one, so a type error says which property is wrong.
    """

    @pytest.mark.parametrize(
        "check,value,type_name",
        [
            (check_int, "5", "Integer"),
            (check_float, "1.5", "Float"),
            (check_bool, 1, "Boolean"),
            (check_str, 42, "String"),
            (check_list, {"a": 1}, "List"),
            (check_dict, [1], "Dict"),
        ],
    )
    def test_message_names_the_property(self, check, value, type_name):
        with pytest.raises(TypeError) as excinfo:
            check(value, "taskCount")
        assert str(excinfo.value) == (
            f"Property 'taskCount' value '{value}' should be of type '{type_name}'"
        )

    def test_float_or_int_message_names_the_property(self):
        with pytest.raises(TypeError) as excinfo:
            check_float_or_int("abc", "priority")
        assert str(excinfo.value) == (
            "Property 'priority' value 'abc' should be of type 'Float' or 'Integer'"
        )

    def test_message_without_a_property_name_is_unchanged(self):
        with pytest.raises(TypeError) as excinfo:
            check_str(42)
        assert str(excinfo.value) == "Property value '42' should be of type 'String'"

    def test_float_or_int_message_without_a_property_name_is_unchanged(self):
        with pytest.raises(TypeError) as excinfo:
            check_float_or_int("abc")
        assert str(excinfo.value) == (
            "Property value 'abc' should be of type 'Float' or 'Integer'"
        )

    def test_valid_value_is_returned_when_named(self):
        assert check_str("abc", "name") == "abc"
