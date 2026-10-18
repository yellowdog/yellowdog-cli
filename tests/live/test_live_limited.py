"""
The failure tests' limited Application, against a scripted 'yd': its
specification, its creation (the key and secret read and registered as
secrets before anything can show them) and the wait for it to work.
"""

import json
from types import SimpleNamespace

import pytest
from harness.limited import (
    CONTROL,
    LIMITED_NAMESPACE,
    LIMITED_SPEC,
    create_limited_app,
    remove_application,
    remove_group,
    wait_until_usable,
)
from harness.yd import Result, YdError
from live_fake_yd import FakeYd, result

from yellowdog_cli.utils.check_imports import check_jsonnet_import

RUN = SimpleNamespace(run_id="ydst-2610151200-ab12")
CREATED = [
    {
        "resource": "Namespace",
        "name": LIMITED_NAMESPACE,
        "id": None,
        "action": "skipped",
    },
    {
        "resource": "Group",
        "name": f"{RUN.run_id}-limited-group",
        "id": "ydid:group:000000:g",
        "action": "created",
    },
    {
        "resource": "Application",
        "name": f"{RUN.run_id}-limited-app",
        "id": "ydid:app:000000:a",
        "action": "created",
        "apiKeyId": "limited-key-0123456789",
        "apiKeySecret": "limited-secret-0123456789",
    },
]


def _specification() -> list[dict]:
    try:
        check_jsonnet_import()
    except ImportError as error:
        pytest.skip(str(error))
    import _jsonnet

    return json.loads(_jsonnet.evaluate_file(str(LIMITED_SPEC)))


def test_the_group_has_work_viewer_in_the_limited_namespace_alone():
    (_, group, application) = _specification()
    assert group["name"] == "{{run_id}}-limited-group"
    (role,) = group["roles"]
    assert role["role"] == {"name": "work-viewer"}
    assert role["scope"] == {
        "global": False,
        "namespaces": [{"namespace": "{{limited_namespace}}"}],
    }
    assert application["groups"] == [group["name"]]
    for resource in (group, application):
        assert resource["description"].endswith(", namespace {{namespace}}")


def test_creation_reads_and_registers_the_key_and_secret():
    yd = FakeYd(lambda args: result(args, document=CREATED))
    app = create_limited_app(yd, RUN)
    assert (app.app_id, app.group_id) == ("ydid:app:000000:a", "ydid:group:000000:g")
    assert (app.key, app.secret) == (
        "limited-key-0123456789",
        "limited-secret-0123456789",
    )
    assert {value for _, value in yd.secrets} == {app.key, app.secret}
    (call,) = yd.calls
    assert (
        call[call.index("--variable") + 1] == f"limited_namespace={LIMITED_NAMESPACE}"
    )
    assert "limited-secret" not in repr(app)
    assert "limited-key" not in repr(app)


def test_a_failed_creation_masks_and_reports():
    failed = [CREATED[1], {**CREATED[2], "action": "failed", "error": "refused"}]
    yd = FakeYd(lambda args: result(args, exit_code=1, document=failed))
    with pytest.raises(YdError):
        create_limited_app(yd, RUN)
    # Registered before the failure was reported, so the report is masked
    assert (
        "the limited Application's secret",
        "limited-secret-0123456789",
    ) in yd.secrets


def test_the_wait_ends_once_the_control_call_works():
    answers = iter([4, 4, 0])
    yd = FakeYd(lambda args: result(args, exit_code=next(answers), document=[]))
    clock = iter(range(0, 1000, 10))
    assert wait_until_usable(yd, sleep=lambda _: None, clock=lambda: next(clock))
    assert len(yd.calls) == 3
    assert yd.calls[0][: len(CONTROL)] == CONTROL


def test_the_wait_gives_up_at_its_bound():
    yd = FakeYd(lambda args: result(args, exit_code=4))
    clock = iter(range(0, 1000, 50))
    assert not wait_until_usable(
        yd, bound=120, sleep=lambda _: None, clock=lambda: next(clock)
    )


def test_removal_removes_each_by_its_id():
    yd = FakeYd(lambda args: result(args, document=[]))
    app = create_limited_app(FakeYd(lambda args: result(args, document=CREATED)), RUN)
    remove_application(yd, app)
    remove_group(yd, app)
    assert [c[:4] for c in yd.calls] == [
        ("resource", "remove", "--ids", "ydid:app:000000:a"),
        ("resource", "remove", "--ids", "ydid:group:000000:g"),
    ]


def test_output_that_does_not_parse_is_never_shown():
    # Nothing can be registered as a secret, so the report leaves stdout out
    def respond(args):
        return Result(args, 1, "not json: limited-secret-0123456789", "it broke")

    yd = FakeYd(respond)
    yd.describe = lambda answer: f"{answer.stdout} {answer.stderr}"
    with pytest.raises(YdError) as raised:
        create_limited_app(yd, RUN)
    assert "limited-secret" not in str(raised.value)
    assert "it broke" in str(raised.value)
