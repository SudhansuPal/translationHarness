"""Exact-match differential comparison of program outputs.

Outputs are compared as JSON *values*, not raw bytes: each stdout is parsed and
re-serialized canonically (sorted keys, no whitespace). This removes cosmetic
differences between languages (`[1, 2]` vs `[1,2]`, `1e20` vs `1.0E20`) while
staying strict about everything that matters — an int is never equal to a float
(`1` != `1.0`), list order matters, and types must match exactly.

Output that is not exactly one valid JSON value is an I/O-contract violation
and counts as a failure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .execute import ProgramRun


class ContractViolation(ValueError):
    """Program stdout is not exactly one JSON value."""


def _reject_nonfinite(token: str):
    raise ContractViolation(f"non-standard JSON constant {token!r}")


def canonicalize(stdout: str) -> str:
    """Parse stdout as a single JSON value and return its canonical serialization."""
    text = stdout.strip()
    if not text:
        raise ContractViolation("stdout is empty (expected one JSON value)")
    try:
        value = json.loads(text, parse_constant=_reject_nonfinite)
    except json.JSONDecodeError as e:
        raise ContractViolation(f"stdout is not a single valid JSON value: {e}; stdout={text[:200]!r}") from None
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass
class Comparison:
    compiled: bool
    ran_ok: bool  # compiled and every test ran to completion (no crash/timeout)
    tests_passed: int
    tests_total: int
    first_failing_input: list | None = None
    error: str | None = None

    @property
    def all_passed(self) -> bool:
        return self.compiled and self.tests_total > 0 and self.tests_passed == self.tests_total


def expected_outputs(run: ProgramRun, inputs: list[list]) -> list[str]:
    """Canonical outputs of a reference program. Raises if the reference itself is broken."""
    if not run.compiled:
        raise RuntimeError(f"reference program does not compile:\n{run.compile_error}")
    outputs = []
    for test_input, t in zip(inputs, run.tests):
        if t.status != "ok":
            raise RuntimeError(f"reference program {t.status} on input {test_input!r}:\n{t.stderr}")
        try:
            outputs.append(canonicalize(t.stdout))
        except ContractViolation as e:
            raise RuntimeError(f"reference program violates I/O contract on {test_input!r}: {e}") from None
    return outputs


def compare(expected: list[str], run: ProgramRun, inputs: list[list]) -> Comparison:
    """Compare a candidate program's run against the expected canonical outputs."""
    total = len(expected)
    if not run.compiled:
        return Comparison(False, False, 0, total, inputs[0] if inputs else None, run.compile_error)

    passed = 0
    ran_ok = True
    first_fail: list | None = None
    first_error: str | None = None
    for test_input, want, t in zip(inputs, expected, run.tests):
        error = None
        if t.status != "ok":
            ran_ok = False
            error = f"{t.status} (exit {t.returncode}): {t.stderr}"
        else:
            try:
                got = canonicalize(t.stdout)
                if got == want:
                    passed += 1
                    continue
                error = f"output mismatch: expected {_short(want)}, got {_short(got)}"
            except ContractViolation as e:
                error = f"I/O contract violation: {e}"
        if first_fail is None:
            first_fail, first_error = test_input, error
    return Comparison(True, ran_ok, passed, total, first_fail, first_error)


def _short(s: str, limit: int = 200) -> str:
    return s if len(s) <= limit else s[:limit] + "..."

