import ast
import random
import re

import pytest

from harness import mutate
from harness.compare import compare, expected_outputs
from harness.execute import run_program
from harness.languages import JAVA, PYTHON

from .conftest import CORPUS_DIR, requires_java
from .test_corpus import PROGRAMS, _tests

PY_OPS = [mutate.py_insert_unused_variable, mutate.py_insert_unused_function]
JAVA_OPS = [mutate.java_insert_unused_variable, mutate.java_insert_unused_function]


def _assert_preserves_behaviour(lang, source, ops, inputs, seeds):
    expected = expected_outputs(run_program(lang, source, inputs), inputs)
    for seed in seeds:
        rng = random.Random(seed)
        mutated = source
        for _ in range(3):
            mutated = rng.choice(ops)(mutated, rng)
        assert mutated != source
        result = compare(expected, run_program(lang, mutated, inputs), inputs)
        assert result.all_passed, f"seed {seed}: {result.error}\n{mutated}"


@pytest.mark.parametrize(
    "program_dir", [p for p in PROGRAMS if (p / "program.py").exists()], ids=lambda p: p.name
)
def test_python_mutants_preserve_behaviour(program_dir):
    source = (program_dir / "program.py").read_text()
    _assert_preserves_behaviour(PYTHON, source, PY_OPS, _tests(program_dir)[:5], range(5))


TRICKY_PY = '''"""Module doc."""
from __future__ import annotations


class Box:
    """Box doc."""

    size = 1


def f(x):
    """f doc."""
    return x
'''


@pytest.mark.parametrize("op", PY_OPS, ids=lambda op: op.__name__)
def test_python_placement_rules(op):
    for seed in range(50):
        tree = ast.parse(op(TRICKY_PY, random.Random(seed)))
        assert ast.get_docstring(tree) == "Module doc."
        assert isinstance(tree.body[1], ast.ImportFrom) and tree.body[1].module == "__future__"
        box = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        assert len(box.body) == 2  # class bodies are never touched
        f = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "f")
        assert ast.get_docstring(f) == "f doc."


def test_fresh_names_never_collide():
    rng = random.Random(0)
    source = "\n".join(f"_unused_{i} = {i}" for i in range(50))
    used = mutate._used_names(ast.parse(source))
    for _ in range(100):
        assert mutate._fresh_name(used, rng, "_unused_") not in {f"_unused_{i}" for i in range(50)}


def test_generate_variants_is_seeded_and_distinct():
    source = (CORPUS_DIR / "merge_sort" / "program.py").read_text()
    a = mutate.generate_variants(source, "python", 3, random.Random(1))
    b = mutate.generate_variants(source, "python", 3, random.Random(1))
    assert [v.source for v in a] == [v.source for v in b]
    assert [v.id for v in a] == ["m1", "m2", "m3"]
    assert len({v.source for v in a} | {source}) == 4


def test_generate_variants_unknown_language():
    assert mutate.generate_variants("x", "cobol", 2, random.Random(0)) == []


@requires_java
@pytest.mark.parametrize(
    "program_dir", [p for p in PROGRAMS if (p / "Main.java").exists()], ids=lambda p: p.name
)
def test_java_mutants_preserve_behaviour(program_dir):
    source = (program_dir / "Main.java").read_text()
    _assert_preserves_behaviour(JAVA, source, JAVA_OPS, _tests(program_dir)[:5], range(3))


TRICKY_JAVA = """
public class Main {
    static class Base { final int v; Base(int v) { this.v = v; } }
    static class Derived extends Base { Derived() { super(2); } }
    interface Shape { double area(); }
    static int early(int n) {
        if (n > 0) { return 1; }
        while (true) { if (n < -5) break; n--; }
        return 0;
    }
    public static void main(String[] args) throws Exception {
        System.in.readAllBytes();
        System.out.println(Json.stringify(early(3) + early(-1) + new Derived().v));
    }
}
"""


@requires_java
def test_java_tricky_constructs_still_compile():
    _assert_preserves_behaviour(JAVA, TRICKY_JAVA, JAVA_OPS, [[]], range(15))


def _is_subsequence(needle, haystack):
    it = iter(haystack)
    return all(tok in it for tok in needle)


@requires_java
def test_java_mutation_is_additive_only():
    tokens = lambda s: re.findall(r"\w+|\S", s)
    for seed in range(5):
        rng = random.Random(seed)
        mutated = mutate.java_insert_unused_variable(TRICKY_JAVA, rng)
        mutated = mutate.java_insert_unused_function(mutated, rng)
        assert len(tokens(mutated)) > len(tokens(TRICKY_JAVA))
        assert _is_subsequence(tokens(TRICKY_JAVA), tokens(mutated))
