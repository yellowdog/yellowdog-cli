"""
Live: 'yd usage' as an Application that may read usage in the run's
namespace alone ('compute-viewer' there) and can read the limited namespace
too ('work-viewer'), which is the case the Platform refuses an unscoped
report for. With no namespace given, the report is asked for in the
namespaces it can read, the limited one, refused, dropped, so it reports on
the run's namespace alone; the limited namespace given is refused, exit 5.
Provisions no compute.
"""

from collections.abc import Iterator

import pytest
from harness import limited
from harness.failures import PERMISSION, check_failure
from harness.limited import LIMITED_NAMESPACE, USAGE_SPEC
from harness.yd import Yd, YdError

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst-usage-scope")]

_JSON = ("--json", "--quiet")


@pytest.fixture(scope="module")
def as_usage_app(live_run) -> Iterator[Yd]:
    run, yd = live_run.run, live_run.yd
    app = limited.create_limited_app(yd, run, USAGE_SPEC)
    scoped = yd.with_credentials(app.key, app.secret)
    problems: list[str] = []
    try:
        if not limited.wait_until_usable(scoped):
            pytest.skip("the usage Application's key did not start working in time")
        yield scoped
    finally:
        for remove in (limited.remove_application, limited.remove_group):
            try:
                remove(yd, app)
            except YdError as error:
                problems.append(str(error))
    if problems:
        pytest.fail("removing the usage Application:\n" + "\n".join(problems))


def test_the_report_covers_the_namespaces_it_may_read_usage_in(live_run, as_usage_app):
    document = as_usage_app(
        "usage", "--from", "1 day ago", "--refresh", *_JSON
    ).document
    assert document["namespace"] is None
    assert document["namespaces"] == [live_run.run.namespace], document
    assert {g["namespace"] for g in document["groups"]} <= {live_run.run.namespace}


def test_a_namespace_it_may_not_read_usage_in_is_refused(as_usage_app):
    result = as_usage_app(
        "usage",
        "--namespace",
        LIMITED_NAMESPACE,
        "--refresh",
        *_JSON,
        check=False,
        ok=(5,),
        expected_failure=True,
    )
    check_failure(as_usage_app, result, 5, PERMISSION)
