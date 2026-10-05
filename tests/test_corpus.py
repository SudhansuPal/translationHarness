"""Every corpus program must honour the I/O contract, and references in both
languages must agree — otherwise translation results against them are meaningless."""

import json

import pytest

from harness.compare import expected_outputs
from harness.execute import run_program
from harness.languages import JAVA, LANGUAGES
from harness.runner import NUM_TESTS

from .conftest import CORPUS_DIR, HAVE_JAVA

PROGRAMS = sorted(p for p in CORPUS_DIR.iterdir() if p.is_dir())


def _tests(program_dir):
    return json.loads((program_dir / "tests.json").read_text())


@pytest.mark.parametrize("program_dir", PROGRAMS, ids=lambda p: p.name)
def test_layout(program_dir):
    tests = _tests(program_dir)
    assert tests and all(isinstance(t, list) for t in tests)
    assert any((program_dir / lang.source_filename).exists() for lang in LANGUAGES.values())


@pytest.mark.parametrize("program_dir", PROGRAMS, ids=lambda p: p.name)
def test_reference_outputs(program_dir):
    inputs = _tests(program_dir)[:NUM_TESTS]
    outputs = {}
    for lang in LANGUAGES.values():
        path = program_dir / lang.source_filename
        if not path.exists():
            continue
        if lang is JAVA and not HAVE_JAVA:
            continue
        outputs[lang.name] = expected_outputs(run_program(lang, path.read_text(), inputs), inputs)
    if len(outputs) > 1:
        first, *rest = outputs.values()
        assert all(o == first for o in rest), outputs
