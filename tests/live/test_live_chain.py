"""
A provider's chain of steps: a failed step skips the later ones, naming
it; a step marked 'always' runs regardless; a skip is not a failure.
"""

import pytest
from live_chain import Chain


def test_a_failed_step_is_recorded_and_raised():
    chain = Chain("aws")
    with pytest.raises(ValueError), chain.step("provision"):
        raise ValueError("boom")
    assert chain.failed == "provision"


def test_a_later_step_is_skipped_naming_the_failed_one():
    chain = Chain("aws", failed="provision")
    with pytest.raises(pytest.skip.Exception, match="after 'provision' failed"):
        with chain.step("smoke"):
            pytest.fail("the body ran")


def test_an_always_step_runs_after_a_failure():
    chain = Chain("aws", failed="smoke")
    ran = []
    with chain.step("shutdown", always=True):
        ran.append(True)
    assert ran == [True]


def test_the_first_failure_is_the_one_kept():
    chain = Chain("aws", failed="smoke")
    with pytest.raises(ValueError), chain.step("shutdown", always=True):
        raise ValueError("boom")
    assert chain.failed == "smoke"


def test_a_skip_inside_a_step_is_not_a_failure():
    chain = Chain("aws")
    with pytest.raises(pytest.skip.Exception), chain.step("start"):
        pytest.skip("nothing to start")
    assert chain.failed is None


def test_a_chain_holds_its_standalone_requirement_apart_from_its_pools():
    chain = Chain("aws", cr_id="ydid:compreq:pool", standalone_cr="ydid:compreq:alone")
    assert chain.standalone is None and chain.instance is None
