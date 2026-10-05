"""Stage support: build and run programs as subprocesses, capture their output.

Language-agnostic: every language-specific detail (file name, build command,
run command, support files) comes from the `Language` object. This module never
interprets program output — it only reports what happened. Comparison and
I/O-contract checking of stdout live in compare.py.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .languages import Language

COMPILE_TIMEOUT_S = 60
RUN_TIMEOUT_S = 10
MAX_ERROR_CHARS = 2000  # truncate captured stderr so logs stay readable


@dataclass
class TestRun:
    """Outcome of running a program on one test input."""

    status: str  # "ok" | "timeout" | "crash"
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None


@dataclass
class ProgramRun:
    """Outcome of building a program once and running it on every test input."""

    compiled: bool
    compile_error: str | None = None
    tests: list[TestRun] = field(default_factory=list)


def _truncate(text: str) -> str:
    text = text.strip()
    return text if len(text) <= MAX_ERROR_CHARS else text[:MAX_ERROR_CHARS] + "\n...[truncated]"


def _build(lang: Language, workdir: Path) -> str | None:
    """Run the language's build step. Returns None on success, error text on failure."""
    if lang.build_cmd is None:
        return None
    try:
        proc = subprocess.run(
            lang.build_cmd, cwd=workdir, capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S
        )
    except subprocess.TimeoutExpired:
        return f"build timed out after {COMPILE_TIMEOUT_S}s"
    except FileNotFoundError as e:
        return f"build tool not found: {e}"
    if proc.returncode != 0:
        return _truncate(proc.stderr or proc.stdout) or f"build exited with code {proc.returncode}"
    return None


def _run_one(lang: Language, workdir: Path, test_input: list) -> TestRun:
    stdin = json.dumps(test_input)
    try:
        proc = subprocess.run(
            lang.run_cmd,
            cwd=workdir,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return TestRun(status="timeout", stderr=f"timed out after {RUN_TIMEOUT_S}s")
    except FileNotFoundError as e:
        return TestRun(status="crash", stderr=f"runtime not found: {e}")
    status = "ok" if proc.returncode == 0 else "crash"
    return TestRun(status=status, stdout=proc.stdout, stderr=_truncate(proc.stderr), returncode=proc.returncode)


def run_program(lang: Language, source: str, inputs: list[list]) -> ProgramRun:
    """Write `source` into a fresh temp dir, build it, and run it on each input.

    Each input is fed to a separate process on stdin as JSON (the I/O contract).
    """
    for test_input in inputs:
        if not isinstance(test_input, list):
            raise ValueError(f"I/O contract: every test input must be a JSON array, got {test_input!r}")

    with tempfile.TemporaryDirectory(prefix=f"harness_{lang.name}_") as tmp:
        workdir = Path(tmp)
        (workdir / lang.source_filename).write_text(source, encoding="utf-8")
        for support in lang.runtime_files:
            shutil.copy(support, workdir / support.name)

        compile_error = _build(lang, workdir)
        if compile_error is not None:
            return ProgramRun(compiled=False, compile_error=compile_error)
        return ProgramRun(compiled=True, tests=[_run_one(lang, workdir, x) for x in inputs])
