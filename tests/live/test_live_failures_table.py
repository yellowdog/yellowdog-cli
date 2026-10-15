"""
The failure cases' table: every pin names a case and says why, every case
has its test, and the shared assertion holds a result to a failure.
"""

import ast
from pathlib import Path

import pytest
from harness.failures import CASES, PINNED, check_failure, expected, fake_ydid
from harness.yd import Result
from live_fake_yd import FakeYd

MODULE = Path(__file__).with_name("test_live_failures.py")


def test_every_pin_names_a_case_and_says_why():
    for case, pinned in PINNED.items():
        assert case in CASES
        assert pinned.why.strip()


def test_every_case_has_its_test_and_every_test_its_case():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    tests = {
        node.name.removeprefix("test_").replace("_", "-")
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    }
    assert tests == set(CASES)


def test_an_unpinned_case_keeps_its_default():
    assert expected("not-found-wr-show", 6, "x") == (6, "x")


def test_a_fake_id_keeps_the_real_ones_segment():
    real = "ydid:workreq:d9c548:98879b5a-9192-4a56-ad25-fc1330e49185"
    assert fake_ydid(real, "compreq") == (
        "ydid:compreq:d9c548:00000000-0000-4000-8000-000000000000"
    )


def _result(code, stdout="[]", stderr=""):
    return Result(("x",), code, stdout, stderr)


def test_check_failure_accepts_the_failure_it_expects():
    check_failure(
        FakeYd(None),
        _result(5, stderr="... the required permissions ..."),
        5,
        "Required Permissions",
    )


@pytest.mark.parametrize(
    "result, why",
    [
        (_result(4, stderr="not recognised"), "exit"),
        (
            _result(
                5, stderr="Traceback (most recent call last):\nrequired permissions"
            ),
            "Traceback",
        ),
        (_result(5, stdout="not json", stderr="required permissions"), "JSON"),
        (_result(5, stderr="something else"), "phrase"),
    ],
)
def test_check_failure_refuses_anything_else(result, why):
    with pytest.raises(AssertionError, match=why):
        check_failure(FakeYd(None), result, 5, "required permissions")
