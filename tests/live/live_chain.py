"""
A provider's steps as an ordered chain: once a step fails, each later one
is skipped, naming it, so a provider's one failure is reported once; a step
marked 'always' (the shutdown) runs regardless. A skip is not a failure.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import pytest


@dataclass
class Chain:
    """
    One provider's chain: the step that failed first, and what the steps
    have made.
    """

    provider: str
    failed: str | None = None
    pool_id: str | None = None
    cr_id: str | None = None
    instance: str | None = None  # 'cr_id.instance_id', the pool's one acted on
    # A Worker Pool takes a stopped node's instance away, so stop, start and
    # restart act on a Compute Requirement no pool manages
    standalone_cr: str | None = None
    standalone: str | None = None  # Its 'cr_id.instance_id'

    @contextmanager
    def step(self, name: str, *, always: bool = False) -> Iterator[Chain]:
        if self.failed is not None and not always:
            pytest.skip(f"{self.provider}: skipped after '{self.failed}' failed")
        try:
            yield self
        except pytest.skip.Exception:
            raise
        except BaseException:
            if self.failed is None:
                self.failed = name
            raise
