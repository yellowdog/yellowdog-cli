"""
Which cloud actions each provider supports, and 'perform', which holds a
supported action to success and an unsupported one to a clean refusal (a
non-zero exit and a 'failed' record whose error contains the recorded
reason), so that a change in the Platform or the CLI shows up rather than
being skipped. A known fault, an action the Platform accepts but gets wrong
on that provider, is held to its symptom and reported as a warning naming
the bug raised, until it stops occurring. An action absent from a
provider's entries is supported; entries are added from real runs, with
the Platform's own wording.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

from harness.yd import Yd

PROVIDERS = ("aws", "azure", "gcp", "oci")
# The cloud actions test_live_providers.py takes, in order
ACTIONS = (
    "resize-up",
    "stop",
    "start",
    "restart",
    "terminate-instance",
    "reprovision",
    "resize-down",
    "deprovision",
)


@dataclass(frozen=True)
class Unsupported:
    """
    An action a provider refuses, and the text its refusal contains.
    """

    reason: str


@dataclass(frozen=True)
class KnownFault:
    """
    An action a provider accepts but the Platform gets wrong: the bug
    raised, the text its failure contains, and how long to wait for the
    action, since the fault makes the wait run to its end.
    """

    issue: str
    symptom: str
    wait_seconds: int


class KnownFaultWarning(UserWarning):
    """
    A known fault occurred, as recorded.
    """


CAPABILITIES: dict[str, dict[str, Unsupported | KnownFault]] = {
    "aws": {},
    "azure": {},
    "gcp": {
        # The resize terminates an Instance, then the target drops again, to
        # 0, with the other Instance left RUNNING
        "resize-down": KnownFault(
            issue="https://yellowdog.atlassian.net/browse/YEL-15298",
            symptom="1 of 0 Instance(s) running",
            wait_seconds=300,
        ),
    },
    "oci": {},
}


def unsupported(provider: str, action: str) -> Unsupported | None:
    entry = CAPABILITIES[provider].get(action)
    return entry if isinstance(entry, Unsupported) else None


def known_fault(provider: str, action: str) -> KnownFault | None:
    entry = CAPABILITIES[provider].get(action)
    return entry if isinstance(entry, KnownFault) else None


def perform(yd: Yd, provider: str, action: str, *args: str) -> bool:
    """
    Run 'yd <args>' for the action: True when it is supported and was done
    (records, none failed or skipped), False when it is unsupported and was
    refused cleanly, or showed its known fault; an AssertionError otherwise.
    """
    fault = known_fault(provider, action)
    if fault is not None:
        return _shows_fault(yd, provider, action, fault, args)
    refusal = unsupported(provider, action)
    if refusal is None:
        done = yd(*args)
        # 'yd' records an entity in the wrong state as skipped, and exits 0
        undone = [r for r in done.records if r.get("outcome") in ("failed", "skipped")]
        assert done.records and not undone, yd.describe(done)
        return True
    refused = yd(*args, check=False)
    assert refused.exit_code != 0, (
        f"'{action}' on {provider} is recorded as unsupported but succeeded:"
        " update the capability table"
    )
    errors = [
        r.get("error") or "" for r in refused.records if r.get("outcome") == "failed"
    ]
    assert errors, yd.describe(refused)
    assert any(refusal.reason in error for error in errors), (
        f"'{action}' on {provider} was refused, but not as recorded"
        f" ('{refusal.reason}'): {errors}"
    )
    return False


def _shows_fault(
    yd: Yd, provider: str, action: str, fault: KnownFault, args: tuple[str, ...]
) -> bool:
    """
    Run the action and hold it to its known fault: False, with a warning
    naming the bug, when the fault occurred; an AssertionError when the
    action succeeded (the fault is fixed) or failed some other way.
    """
    done = yd(*args, check=False)
    if done.exit_code != 0 and fault.symptom in done.stdout + done.stderr:
        warnings.warn(
            KnownFaultWarning(
                f"'{action}' on {provider}: the known fault occurred ({fault.issue})"
            ),
            stacklevel=3,
        )
        return False
    undone = [r for r in done.records if r.get("outcome") in ("failed", "skipped")]
    assert done.exit_code != 0 or undone or not done.records, (
        f"'{action}' on {provider} no longer shows its known fault ({fault.issue}):"
        " update the capability table"
    )
    raise AssertionError(yd.describe(done))
