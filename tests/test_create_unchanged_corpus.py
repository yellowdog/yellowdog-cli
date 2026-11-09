"""
'yd resource create' over the whole resource corpus (tests/resources/), on
the fake Platform (resource_plan_platform.py) holding what each
specification would make: every existing resource the plan finds unchanged
is left alone, unwritten and unasked about, and only what is always sent
is written: a Credential (put by name, recorded 'created') and an Allowance
(always created again); a Configured Worker Pool fails, its name being
taken.
"""

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import requests
from requests.exceptions import HTTPError
from resource_corpus import (
    corpus_files,
    install_variables,
    remove_variables,
    require_jsonnet,
)
from yellowdog_client.model import RoleSummary

import yellowdog_cli.utils.results as results_module
from tests.resource_plan_platform import (  # noqa: F401 (the fixture)
    MUTATING_PREFIXES,
    FakePlatform,
    corpus_ctx,
    fails_for_want_of_a_namespace,
    holding_all,
    platform,
)
from yellowdog_cli.utils import resource_creation
from yellowdog_cli.utils.entity_names import (
    RN_ALLOWANCE,
    RN_APPLICATION,
    RN_CONFIGURED_POOL,
    RN_CREDENTIAL,
)
from yellowdog_cli.utils.exit_codes import ReportedFailure
from yellowdog_cli.utils.resource_creation import CreateOptions, create_resources

require_jsonnet()

# The Platform's built-in roles the corpus's Groups name
BUILT_IN_ROLES = ("work-viewer", "work-manager")

# What each type is recorded as when created again, where not 'unchanged'
CREATED_AGAIN = {
    RN_CREDENTIAL: "created",
    RN_ALLOWANCE: "created",
    RN_CONFIGURED_POOL: "failed",
}

# The only writes a run of the held corpus makes: a Credential put by name,
# an Allowance added, and a Configured Worker Pool's attempt, which the
# Platform refuses
ALWAYS_SENT = {
    RN_CREDENTIAL: "keyring_client.put_credential_by_name",
    RN_ALLOWANCE: "allowances_client.add_allowance",
    RN_CONFIGURED_POOL: "worker_pool_client.add_configured_worker_pool",
}

NAME_TAKEN = "a Worker Pool of that name already exists"


@pytest.fixture(autouse=True)
def _corpus_variables() -> Iterator[None]:
    previous = install_variables()
    try:
        yield
    finally:
        remove_variables(previous)


@pytest.fixture(autouse=True)
def _results() -> Iterator[None]:
    results_module.reset_results()
    yield
    results_module.reset_results()


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """
    The prompts the run asks, each answered yes.
    """
    prompts: list[str] = []

    def _confirmed(prompt: str) -> bool:
        prompts.append(prompt)
        return True

    monkeypatch.setattr(resource_creation, "confirmed", _confirmed)
    return prompts


def _name_taken(*args: Any, **kwargs: Any) -> None:
    response = requests.Response()
    response.status_code = 400
    raise HTTPError(NAME_TAKEN, response=response)


def _let_the_always_sent_through(platform: FakePlatform) -> None:
    client = platform.client
    put = client.keyring_client.put_credential_by_name
    put.side_effect, put.return_value = None, None
    add = client.allowances_client.add_allowance
    add.side_effect = None
    add.return_value = SimpleNamespace(id="ydid:allow:000000:created-again")
    client.worker_pool_client.add_configured_worker_pool.side_effect = _name_taken


def _mutations(platform: FakePlatform) -> list[str]:
    return [
        name
        for name, _, _ in platform.client.mock_calls
        if name.rsplit(".", 1)[-1].startswith(MUTATING_PREFIXES)
    ]


@pytest.mark.parametrize("path", corpus_files(), ids=lambda p: p.stem)
def test_creating_the_held_corpus_again_writes_nothing_but_the_always_sent(
    path: Path, platform: FakePlatform, asked: list[str]
):
    for name in BUILT_IN_ROLES:
        platform.holding("Role", RoleSummary(name=name))
    specifications = holding_all(platform, path)
    _let_the_always_sent_through(platform)

    try:
        create_resources(corpus_ctx(platform), specifications, CreateOptions())
    except ReportedFailure:
        pass  # A failure the records say, checked below

    records = list(results_module._ITEMS)
    assert len(records) == len(specifications), records
    expected_writes = []
    for specification, record in zip(specifications, records):
        resource_type = specification["resource"]
        if fails_for_want_of_a_namespace(path, specification) or (
            resource_type == RN_APPLICATION and specification.get("keyrings")
        ):
            # Refused by the creator as by the plan (no namespace; a
            # Keyring granted to an existing Application needs its key)
            assert record["action"] == "failed", record
            continue
        assert record["action"] == CREATED_AGAIN.get(resource_type, "unchanged"), record
        if resource_type == RN_CONFIGURED_POOL:
            assert NAME_TAKEN in record["error"], record
        if resource_type in ALWAYS_SENT:
            expected_writes.append(ALWAYS_SENT[resource_type])

    assert _mutations(platform) == expected_writes
    assert asked == []
