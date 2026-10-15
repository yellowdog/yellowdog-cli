"""
Running 'yd' for the live system tests: 'python -m yellowdog_cli.yd' with
the run's configuration and environment, from the run's directory, output
captured. A Result is returned as it was; what the harness shows of it (a
failure, the log) has every configured secret masked: the secret whole,
JSON-escaped, line by line, and a service account's private key within it.
And every call's output is checked for every configured secret: one found
fails the call (SecretInOutput), naming where it was configured.
A call that exits as expected is recorded for the coverage gate
(harness/coverage.py), unless it was made to fail.

Every caller passes the long '--json' and '--quiet', so stdout is the
document alone: '-J' is '--jsonnet-dry-run' on 'yd resource create'.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from harness import coverage
from harness.run import Run

DEFAULT_PROGRAM = (sys.executable, "-m", "yellowdog_cli.yd")
DEFAULT_TIMEOUT = 1800  # Seconds: a command taking longer has hung
MASK = "<redacted>"
_MIN_SECRET = 6  # Shorter is too likely to be ordinary text
_MIN_LINE = 16  # A line of a multi-line secret, masked on its own
_SERVICE_ACCOUNT_SECRETS = ("private_key", "private_key_id")
_TAIL_LINES = 40

LOG = logging.getLogger("ydst")


def mask_variants(secrets: Iterable[str]) -> list[str]:
    """
    Every form of the secrets to mask, longest first, so that a secret is
    masked whole before any line of it is.
    """
    variants: set[str] = set()

    def add(text: str) -> None:
        text = text.strip()
        if len(text) < _MIN_SECRET:
            return
        variants.add(text)
        variants.add(json.dumps(text)[1:-1])
        variants.update(
            line.strip() for line in text.splitlines() if len(line.strip()) >= _MIN_LINE
        )

    for secret in secrets:
        add(secret)
        try:
            document = json.loads(secret)
        except ValueError:
            continue
        if isinstance(document, dict):
            for key in _SERVICE_ACCOUNT_SECRETS:
                if isinstance(document.get(key), str):
                    add(document[key])
    return sorted(variants, key=len, reverse=True)


@dataclass(frozen=True)
class Result:
    """
    One 'yd' command's outcome, as it was: its output unmasked, so left out
    of its repr, which pytest shows in a failure.
    """

    args: tuple[str, ...]
    exit_code: int
    stdout: str = field(repr=False)
    stderr: str = field(repr=False)

    @property
    def document(self) -> Any:
        """
        The JSON document on stdout; None when the command printed nothing.
        """
        return json.loads(self.stdout) if self.stdout.strip() else None

    @property
    def records(self) -> list[dict]:
        """
        The document as a list of records: an array as it is, one object as
        a list of one, nothing as none.
        """
        document = self.document
        if document is None:
            return []
        return document if isinstance(document, list) else [document]


class YdError(AssertionError):
    """
    A 'yd' command that failed or ran too long; its message is masked.
    """


class SecretInOutput(YdError):
    """
    A 'yd' command printed a configured secret; the message names where it
    was configured and shows the command's output masked, never the secret.
    """


class Yd:
    """
    Runs 'yd' for a run.
    """

    def __init__(
        self,
        run: Run,
        program: Sequence[str] = DEFAULT_PROGRAM,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.run = run
        self._program = tuple(program)
        self._timeout = timeout
        # Credentials in place of [platform]'s (with_credentials())
        self._credentials: dict[str, str] = {}
        self._masks = mask_variants(run.config.secrets())
        # Each variant of each secret, with where it was configured
        self._secret_labels: list[tuple[str, str]] = sorted(
            (
                (variant, label)
                for label, secret in run.config.labelled_secrets(shown=False).items()
                for variant in mask_variants([secret])
            ),
            key=lambda pair: len(pair[0]),
            reverse=True,
        )

    def with_credentials(self, key: str, secret: str, url: str | None = None) -> Yd:
        """
        A runner for the same run acting with these credentials (and URL,
        when given) in place of [platform]'s. It shares this runner's
        secrets, so a secret either learns is masked and checked by both.
        """
        derived = copy.copy(self)
        derived._credentials = {"YD_KEY": key, "YD_SECRET": secret}
        if url is not None:
            derived._credentials["YD_URL"] = url
        return derived

    def add_secret(self, label: str, value: str) -> None:
        """
        Mask a secret learned during the run, and fail any later call whose
        output holds it, naming the label. In place, so every runner derived
        from this one, or that this one was derived from, sees it.
        """
        variants = mask_variants([value])
        self._masks[:] = sorted({*self._masks, *variants}, key=len, reverse=True)
        self._secret_labels[:] = sorted(
            [*self._secret_labels, *((variant, label) for variant in variants)],
            key=lambda pair: len(pair[0]),
            reverse=True,
        )

    def mask(self, text: str) -> str:
        """
        The text with every configured secret masked.
        """
        for variant in self._masks:
            text = text.replace(variant, MASK)
        return text

    def __call__(
        self,
        *args: str,
        check: bool = True,
        ok: Iterable[int] = (0,),
        timeout: float | None = None,
        expect_secret: bool = False,
        expected_failure: bool = False,
    ) -> Result:
        """
        Run 'yd <args> --config <the run's configuration>'. With 'check', an
        exit code not in 'ok' raises YdError. 'expect_secret' skips the
        secret-in-output check for this call, whose output is known to hold
        one; 'expected_failure' records no coverage for an accepted exit
        code other than 0.
        """
        argv = [*self._program, *args, "--config", str(self.run.cli_config)]
        shown = self.mask("yd " + " ".join(args))
        environment = self.run.environment(os.environ)
        environment.update(self._credentials)
        try:
            completed = subprocess.run(
                argv,
                cwd=self.run.directory,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout or self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise YdError(
                f"{shown}: still running after {error.timeout:.0f}s"
            ) from None
        result = Result(
            tuple(args), completed.returncode, completed.stdout, completed.stderr
        )
        if not expect_secret:
            self._check_no_secret(shown, result)
        if result.exit_code in tuple(ok) and not (
            expected_failure and result.exit_code != 0
        ):
            coverage.record(args)
        LOG.info("%s -> %d", shown, result.exit_code)
        if check and result.exit_code not in tuple(ok):
            raise YdError(self.describe(result))
        return result

    def _check_no_secret(self, shown: str, result: Result) -> None:
        """
        Fail the call, whatever its exit code, if its output holds any
        configured secret.
        """
        for variant, label in self._secret_labels:
            if variant in result.stdout or variant in result.stderr:
                raise SecretInOutput(
                    f"{shown}: its output holds the secret configured as {label}\n"
                    + self.describe(result)
                )

    def describe(self, result: Result) -> str:
        """
        A failed command for a message: what ran, its exit code, and the
        tail of its output, masked.
        """
        return self.mask(
            f"yd {' '.join(result.args)} exited {result.exit_code}"
            f"\n--- stdout ---\n{_tail(result.stdout)}"
            f"\n--- stderr ---\n{_tail(result.stderr)}"
        )


def _tail(text: str) -> str:
    return "\n".join(text.rstrip().splitlines()[-_TAIL_LINES:])
