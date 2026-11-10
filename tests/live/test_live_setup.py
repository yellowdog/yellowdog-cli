"""
Live: a run's setup makes what it should, a plan of what it made changes
nothing, nor does a plan of an export of it, creating it again writes
nothing but the always-sent, teardown leaves nothing, and
the run's Keyring and Credentials can provision (Open Question 1 of the
design). A Group and Application are made and planned again too, since
setup makes neither.

    pytest --run-live tests/live/test_live_setup.py
"""

import json
import time

import pytest
from harness import work
from harness.lifecycle import NAMESPACE_SPEC, REMOVAL_ORDER, owned, setup, teardown
from harness.run import Run
from harness.yd import Yd

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst")]

_POLL_SECONDS = 15
_SETTLED = {"RUNNING", "TERMINATED", "TERMINATING", "STOPPED"}
# What a plan of the specifications setup has just created says of each type:
# a Credential's secrets can't be read back, and an Allowance is never
# updated, only created again; everything else is unchanged
_PLANNED_AGAIN = {"Credential": "unknown", "Allowance": "create"}
_PLAN = ("resource", "plan", "--json", "--quiet")
# What 'yd resource create' of those specifications again records of each
# type: a Credential is put by name and an Allowance created again;
# everything else is unchanged, and not written
_CREATED_AGAIN = {"Credential": "created", "Allowance": "created"}
# The types of what setup makes, the namespace's defaults and the
# account-wide types among them, and the file in the run's directory an
# export of them is written to
_EXPORTED_TYPES = (
    "compute-source-templates",
    "compute-requirement-templates",
    "image-families",
    "namespace-policies",
    "keyrings",
    "allowances",
)
_EXPORT_FILE = "export.json"


def _names(entities: list[dict], key: str = "name") -> list[str]:
    return sorted(entity[key] for entity in entities)


def test_setup_made_the_keyring_templates_and_allowance(live_run):
    run, yd = live_run.run, live_run.yd
    providers = list(run.config.providers)
    assert _names(owned(yd, "keyrings", run.namespace, run.run_id)) == [run.keyring]
    assert _names(owned(yd, "compute-source-templates", run.namespace, run.run_id)) == (
        sorted(run.source_template(p) for p in providers)
    )
    assert _names(
        owned(yd, "compute-requirement-templates", run.namespace, run.run_id)
    ) == sorted(run.requirement_template(p) for p in providers)
    assert _names(
        owned(yd, "allowances", run.namespace, run.run_id), key="description"
    ) == [run.allowance_description]


def test_the_keyring_holds_a_credential_per_provider(live_run):
    run, yd = live_run.run, live_run.yd
    (keyring,) = owned(yd, "keyrings", run.namespace, run.run_id)
    shown = yd("resource", "show", keyring["id"], "--quiet").document
    assert sorted(c["name"] for c in shown["credentials"]) == sorted(
        run.credential_name(p) for p in run.config.providers
    )


def test_a_plan_of_what_setup_made_changes_nothing(live_run):
    """
    Each Platform default or reordered list the plan does not know of shows
    here as a change (PLATFORM_DEFAULTS, UNORDERED_LISTS in resource_plan.py).
    """
    run, yd = live_run.run, live_run.yd
    files = [str(NAMESPACE_SPEC), *(str(path) for path in run.spec_files())]
    records = yd(*_PLAN, *files).records
    assert records, "the plan recorded nothing"
    wrong = [
        record
        for record in records
        if record["action"] != _PLANNED_AGAIN.get(record["resource"], "unchanged")
    ]
    assert wrong == [], json.dumps(wrong, indent=2)


def test_an_export_of_what_setup_made_plans_as_unchanged(live_run):
    """
    'yd resource export' of the run's resources (its templates, Image
    Families, Keyring, Credentials and Allowance, by the run's name prefix)
    to a file in the run's directory, then 'yd resource plan' of that file:
    each exported specification as setup made it. An exported Credential's
    secrets are variables, given placeholders here, which the plan never
    sends.
    """
    run, yd = live_run.run, live_run.yd
    exported = yd(
        "resource",
        "export",
        *_EXPORTED_TYPES,
        "--include-credentials",
        "--name",
        f"{run.run_id}-*",
        "--output-file",
        _EXPORT_FILE,
        "--json",
        "--quiet",
    ).records
    providers = run.config.providers
    assert sorted((r["resource"], r["action"]) for r in exported) == sorted(
        [("Keyring", "exported"), ("Allowance", "exported")]
        + [
            (resource, "exported")
            for resource in (
                "Credential",
                "MachineImageFamily",
                "ComputeSourceTemplate",
                "ComputeRequirementTemplate",
            )
            for _ in providers
        ]
    ), json.dumps(exported, indent=2)

    specifications = json.loads(
        (run.directory / _EXPORT_FILE).read_text(encoding="utf-8")
    )
    placeholders = [
        argument
        for variable in sorted(_secret_variables(specifications))
        for argument in ("--variable", f"{variable}=exported-placeholder")
    ]
    records = yd(*_PLAN, *placeholders, _EXPORT_FILE).records
    assert len(records) == len(specifications), json.dumps(records, indent=2)
    wrong = [
        record
        for record in records
        if record["action"] != _PLANNED_AGAIN.get(record["resource"], "unchanged")
    ]
    assert wrong == [], json.dumps(wrong, indent=2)


def test_creating_what_setup_made_again_changes_nothing(live_run):
    """
    'yd resource create' of the specifications setup has just created: each
    existing resource the plan finds unchanged is left alone, bar those
    always sent: a Credential (put by name, recorded 'created') and an
    Allowance (created again). The second Allowance is given a description of
    its own, still the run's, so that no other test finds two of the run's
    one, and is removed after.
    """
    run, yd = live_run.run, live_run.yd
    files = [str(NAMESPACE_SPEC), *(str(path) for path in run.spec_files())]
    again = run.name("allowance-again")
    records = yd(
        "resource",
        "create",
        "--variable",
        f"allowance_description={again}",
        "--yes",
        *_PLAN[2:],
        *files,
    ).records
    allowances = [r["id"] for r in records if r["resource"] == "Allowance"]
    remove = ("resource", "remove", "--ids", *allowances, "--yes", *_PLAN[2:])
    with work.cleaned_up(lambda: allowances and yd(*remove)):
        assert records, "the run recorded nothing"
        wrong = [
            record
            for record in records
            if record["action"] != _CREATED_AGAIN.get(record["resource"], "unchanged")
        ]
        assert wrong == [], json.dumps(wrong, indent=2)
        assert [r["name"] for r in records if r["resource"] == "Allowance"] == [again]


def _secret_variables(specifications: list[dict]) -> set[str]:
    """
    The variables an exported Credential's secrets are written as.
    """
    return {
        value[2:-2]
        for specification in specifications
        if specification["resource"] == "Credential"
        for value in specification["credential"].values()
        if isinstance(value, str) and value.startswith("{{") and value.endswith("}}")
    }


def test_a_plan_of_a_group_and_application_changes_nothing(live_run, tmp_path):
    """
    A Group with a role in the run's namespace and an Application in it,
    created and planned again: both unchanged. Removed after, as teardown
    would remove them by name.
    """
    run, yd = live_run.run, live_run.yd
    group, application = run.name("plan-group"), run.name("plan-app")
    described = f"Live system tests, run {run.run_id}, namespace {run.namespace}"
    specification = tmp_path / "group-and-application.json"
    specification.write_text(
        json.dumps(
            [
                {
                    "resource": "Group",
                    "name": group,
                    "description": described,
                    "roles": [
                        {
                            "role": {"name": "work-viewer"},
                            "scope": {
                                "global": False,
                                "namespaces": [{"namespace": run.namespace}],
                            },
                        }
                    ],
                },
                {
                    "resource": "Application",
                    "name": application,
                    "description": described,
                    "groups": [group],
                },
            ]
        ),
        encoding="utf-8",
    )
    created = yd(
        "resource",
        "create",
        str(specification),
        "--yes",
        *_PLAN[2:],
        expect_secret=True,
    ).records
    for record in created:
        for field in ("apiKeyId", "apiKeySecret"):
            if record.get(field):
                yd.add_secret(f"the plan Application's {field}", record[field])
    ids = [record["id"] for record in created if record.get("id")]
    remove = ("resource", "remove", "--ids", *ids, "--yes", *_PLAN[2:])
    with work.cleaned_up(lambda: yd(*remove)):
        records = yd(*_PLAN, str(specification)).records
        assert [(r["resource"], r["action"]) for r in records] == [
            ("Group", "unchanged"),
            ("Application", "unchanged"),
        ], json.dumps(records, indent=2)


def test_a_plan_shows_one_changed_property(live_run, tmp_path):
    """
    A Compute Requirement Template as setup made it, but for its description:
    one update, of that one property, and '--fail-on-changes' exits 1.
    """
    run, yd = live_run.run, live_run.yd
    primary = run.config.primary
    changed = tmp_path / "changed-template.json"
    changed.write_text(
        json.dumps(
            {
                "resource": "ComputeRequirementTemplate",
                "type": "co.yellowdog.platform.model.ComputeRequirementStaticTemplate",
                "namespace": run.namespace,
                "name": run.requirement_template(primary),
                "description": "A changed description",
                "strategyType": "co.yellowdog.platform.model.WaterfallProvisionStrategy",
                "sources": [
                    {
                        "sourceTemplateId": f"{run.namespace}/{run.source_template(primary)}"
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (record,) = yd(*_PLAN, str(changed)).records
    assert record["action"] == "update", record
    assert record["name"] == f"{run.namespace}/{run.requirement_template(primary)}"
    (change,) = record["changes"]
    assert change["path"] == "description", record
    assert change["to"] == "A changed description", record

    failing = yd(*_PLAN, "--fail-on-changes", str(changed), ok=(1,))
    assert [r["action"] for r in failing.records] == ["update"]


def test_a_run_torn_down_leaves_nothing(live_config, tmp_path):
    run = Run.start(live_config, tmp_path)
    yd = Yd(run)
    try:
        setup(run, yd)
        assert owned(yd, "keyrings", run.namespace, run.run_id)
    finally:
        problems = teardown(
            yd, run.namespace, run.run_id, live_config.run["teardown_timeout_minutes"]
        )
    assert problems == []
    for entity_type in REMOVAL_ORDER:
        assert owned(yd, entity_type, run.namespace, run.run_id) == [], entity_type


def test_the_primary_provisions_with_the_runs_credential(live_run):
    """
    One instance from the primary's static template: proves the Application
    can use the Keyring it created without its being claimed in the Portal,
    and that the primary's credential, network and image work. Terminated
    whatever happens.
    """
    run, yd = live_run.run, live_run.yd
    primary = run.config.primary
    created = yd(
        "cr",
        "instantiate",
        "--property",
        f"workerPool.templateId={run.namespace}/{run.requirement_template(primary)}",
        "--property",
        f"workerPool.name={run.name('probe')}",
        "--target",
        "1",
        "--json",
        "--quiet",
    ).document
    requirement = created["id"]
    terminate = ("cr", "terminate", requirement, "--yes", "--json", "--quiet")
    with work.cleaned_up(lambda: yd(*terminate, ok=(0, 6))):
        status = _settled(yd, requirement, run.config.run["provision_timeout_minutes"])
        if status != "RUNNING":
            report = yd(
                "cr",
                "show",
                requirement,
                "--show-source-report",
                "--quiet",
                check=False,
            )
            pytest.fail(
                f"{requirement} reached {status}, not RUNNING:\n"
                + yd.mask(report.stdout),
                pytrace=False,
            )


def _settled(yd: Yd, requirement: str, timeout_minutes: int) -> str:
    """
    Poll a Compute Requirement until its status settles, or the time is up.
    """
    deadline = time.monotonic() + timeout_minutes * 60
    status = "UNKNOWN"
    while time.monotonic() < deadline:
        status = yd("cr", "show", requirement, "--quiet").document["status"]
        if status in _SETTLED:
            return status
        time.sleep(_POLL_SECONDS)
    return status
