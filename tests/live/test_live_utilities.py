"""
Live: the Platform utilities against the run's configuration: yd doctor,
yd variables (every configured secret redacted), yd application, and
'yd resource create --validate', which checks and creates nothing. (yd schema
is left to the unit tests: see harness/coverage.py.)
"""

import pytest
from harness.run import SPECS

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst-utilities")]


def test_doctor_finds_nothing_failing(live_run):
    # yd doctor exits 1 when a check FAILs, which the assertion reports
    records = live_run.yd("doctor", "--json", "--quiet", ok=(0, 1)).records
    failing = [r for r in records if r.get("status") == "FAIL"]
    assert not failing, failing


def test_variables_redacts_every_configured_secret(live_run):
    # Yd's own check fails the call if any secret is printed; this asserts
    # the redaction is what the CLI reports, too
    report = live_run.yd("variables", "--quiet").document
    for name in live_run.run.secret_variables():
        assert report.get(name) == "<REDACTED>", name


def test_application_names_the_application(live_run):
    document = live_run.yd("application", "--json", "--quiet").document
    assert document.get("id")


def test_validate_checks_the_runs_specifications_and_creates_nothing(live_run):
    run, yd = live_run.run, live_run.yd
    files = [str(SPECS / "namespace.jsonnet"), *(str(p) for p in run.spec_files())]
    yd("resource", "create", "--validate", *files, "--quiet")
