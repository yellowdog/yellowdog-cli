"""
A report of the package's code complexity, for 'make complexity': each
function's McCabe complexity (worst first), ruff's counts of functions with
too many branches, statements, returns or arguments, and function lengths.

A report, not a gate: it always exits 0, and the checks it runs are enabled
for it alone, not in pyproject.toml's ruff configuration, so 'make format'
and the pre-commit hook are unaffected. Run from the repository root.
"""

import argparse
import ast
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

PACKAGE = Path("yellowdog_cli")

# Ruff's rules for the structure of a function, beyond McCabe complexity
STRUCTURE_RULES = {
    "PLR0911": "too many return statements",
    "PLR0912": "too many branches",
    "PLR0913": "too many arguments",
    "PLR0915": "too many statements",
}

_COMPLEXITY = re.compile(r"`(?P<name>[^`]+)` is too complex \((?P<score>\d+) >")


def _ruff(threshold: int) -> list[dict]:
    """
    Ruff's findings for the package, as JSON: C901 at 'threshold', and the
    structure rules at their defaults.
    """
    result = subprocess.run(
        [
            "ruff",
            "check",
            str(PACKAGE),
            "--select",
            ",".join(["C901", *STRUCTURE_RULES]),
            "--config",
            f"lint.mccabe.max-complexity={threshold}",
            "--output-format",
            "json",
            "--exit-zero",
            "--no-cache",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def _function_lengths() -> list[tuple[int, str]]:
    """
    (lines, 'path:line name') for every function and method in the package.
    """
    lengths = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lengths.append(
                    (
                        (node.end_lineno or node.lineno) - node.lineno + 1,
                        f"{path.as_posix()}:{node.lineno} {node.name}",
                    )
                )
    return lengths


def _location(finding: dict) -> str:
    path = Path(finding["filename"]).resolve().relative_to(Path.cwd().resolve())
    return f"{path.as_posix()}:{finding['location']['row']}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="A report of the package's code complexity."
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=15,
        help="report functions whose McCabe complexity exceeds this (default 15)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="how many of the most complex and the longest to list (default 10)",
    )
    args = parser.parse_args()

    findings = _ruff(args.threshold)
    complex_functions = sorted(
        (
            (int(match["score"]), f"{_location(f)} {match['name']}")
            for f in findings
            if f["code"] == "C901" and (match := _COMPLEXITY.search(f["message"]))
        ),
        reverse=True,
    )
    lengths = sorted(_function_lengths(), reverse=True)
    lines = [length for length, _ in lengths]

    print(f"Complexity of {PACKAGE}/ ({len(lines):,} functions)")
    print()
    print("McCabe complexity")
    print(f"  over 20: {sum(score > 20 for score, _ in complex_functions)}")
    print(f"  over {args.threshold}: {len(complex_functions)}")
    for score, where in complex_functions[: args.top]:
        print(f"  {score:4d}  {where}")
    print()
    print("Function structure (ruff's default limits)")
    for code, description in STRUCTURE_RULES.items():
        count = sum(f["code"] == code for f in findings)
        print(f"  {count:4d}  {code}  {description}")
    print()
    print("Function length (lines)")
    print(
        f"  median {statistics.median(lines):g}, 90th percentile"
        f" {sorted(lines)[int(0.9 * len(lines))]}, over 100: {sum(n > 100 for n in lines)}"
    )
    for length, where in lengths[: args.top]:
        print(f"  {length:4d}  {where}")


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError:
        print("ruff was not found: install the dev extra", file=sys.stderr)
        sys.exit(1)
