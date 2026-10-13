"""
Which cloud actions each provider supports, and 'perform', which holds a
supported action to success and an unsupported one to a clean refusal (a
non-zero exit and a 'failed' record whose error contains the recorded
reason), so that a change in the Platform or the CLI shows up rather than
being skipped. An action absent from a provider's entries is supported;
entries are added from real runs, with the Platform's own wording.
"""

from __future__ import annotations

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


CAPABILITIES: dict[str, dict[str, Unsupported]] = {
    "aws": {},
    "azure": {},
    "gcp": {},
    "oci": {},
}


def unsupported(provider: str, action: str) -> Unsupported | None:
    return CAPABILITIES[provider].get(action)


def perform(yd: Yd, provider: str, action: str, *args: str) -> bool:
    """
    Run 'yd <args>' for the action: True when it is supported and was done
    (records, none failed or skipped), False when it is unsupported and was
    refused cleanly; an AssertionError otherwise.
    """
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
