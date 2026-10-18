"""
utils/failure_advice.py: what to check when the Platform refuses a request,
said once per run for each cause, wherever the failure is reported -- a
target of an action, an ID shown, a resource created -- and in the same
words the wrapper uses for a failure reaching it.
"""

from requests import HTTPError, Response

from yellowdog_cli.utils import action_runner, failure_advice
from yellowdog_cli.utils.action_runner import Item, Unit, carry_out


def _http_error(status_code: int) -> HTTPError:
    response = Response()
    response.status_code = status_code
    return HTTPError(f"{status_code} Client Error", response=response)


def _printed(monkeypatch) -> list[str]:
    lines: list[str] = []
    monkeypatch.setattr(failure_advice, "print_error", lines.append)
    return lines


def test_a_refusal_is_explained_once(monkeypatch):
    lines = _printed(monkeypatch)
    failure_advice.advise(_http_error(403))
    failure_advice.advise(_http_error(403))
    assert lines == [failure_advice.PERMISSION_ADVICE]
    assert "required permissions" in lines[0]


def test_an_unrecognised_key_is_explained(monkeypatch):
    lines = _printed(monkeypatch)
    failure_advice.advise(_http_error(401))
    assert lines == [failure_advice.AUTHENTICATION_ADVICE]
    assert "not recognised" in lines[0]


def test_anything_else_needs_no_advice(monkeypatch):
    lines = _printed(monkeypatch)
    for status in (404, 500):
        failure_advice.advise(_http_error(status))
    failure_advice.advise(ValueError("x"))
    assert lines == []


def test_the_wrapper_uses_the_same_words():
    from yellowdog_cli.utils.wrapper import _describe

    assert _describe(_http_error(403)).startswith(failure_advice.PERMISSION_ADVICE)
    assert _describe(_http_error(401)).startswith(failure_advice.AUTHENTICATION_ADVICE)


def test_an_action_refused_on_its_targets_is_explained(monkeypatch):
    lines = _printed(monkeypatch)
    monkeypatch.setattr(action_runner, "print_error", lambda _m: None)

    def refused():
        raise _http_error(403)

    items = [Item(name, "a", name, name) for name in ("x", "y")]
    carry_out(
        [Unit(items[:1], refused, str), Unit(items[1:], refused, str)],
        lambda *_: None,
    )
    assert lines == [failure_advice.PERMISSION_ADVICE]


def test_a_refused_show_is_explained(monkeypatch):
    from unittest.mock import MagicMock

    from yellowdog_cli import show
    from yellowdog_cli.utils.context import RunContext

    lines = _printed(monkeypatch)
    monkeypatch.setattr(show, "print_error", lambda _m: None)
    monkeypatch.setattr(show, "print_info", lambda *_a, **_k: None)
    client = MagicMock()
    client.work_client.get_task_by_id.side_effect = _http_error(403)
    ctx = RunContext(
        args=MagicMock(strip_ids=False, output_file=None),
        config=MagicMock(),
        client=client,
    )
    show.show_ydids(ctx, ["ydid:task:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:1:1"])
    assert lines == [failure_advice.PERMISSION_ADVICE]
