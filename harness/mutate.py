"""Stage 1: generate semantically-equivalent variants with AST-level mutations.

Mutations are ADDITIVE ONLY: they insert dead code and never delete, rename,
reorder, or modify anything already in the program. Mutation happens in the
SOURCE language of each translation direction (Python source for
python->java, Java source for java->python).

Two operators per language:
  - unused_variable: insert a variable that is assigned but never read
  - unused_function: insert a syntactically valid function that is never called

Every operator has the same signature, `(source: str, rng: random.Random) -> str`,
so each language is free to use its own AST tooling. NEVER use string
replacement or regexes on the source text — parse, edit the tree, print it back.

Python operators work in-process on the stdlib `ast`. Java operators shell
out to tools/JavaMutator.java (JavaParser); the first use downloads the
pinned JavaParser jar and compiles the tool into .cache/tools/.

Stage 2 (in runner.py) re-checks every variant's behavior anyway, so a buggy operator produces a
discarded variant, never a false "translation bug".
"""

from __future__ import annotations

import ast
import hashlib
import logging
import os
import random
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

MutationOp = Callable[[str, random.Random], str]


@dataclass
class Variant:
    id: str  # "original" for the unmutated program, else "m1", "m2", ...
    source: str
    mutations: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Python operators — use the stdlib `ast` module (or libcst to keep comments
# and formatting: `ast.unparse` drops comments and normalizes layout, which is
# still behavior-preserving but makes variants look less like the original).
# --------------------------------------------------------------------------


def _used_names(tree: ast.AST) -> set[str]:
    """Every identifier the program already uses, so fresh names never collide."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.alias):
            names.add((node.asname or node.name).split(".")[0])
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.update(node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
    return names


def _fresh_name(used: set[str], rng: random.Random, prefix: str) -> str:
    while True:
        name = f"{prefix}{rng.randrange(10**6)}"
        if name not in used:
            used.add(name)
            return name


def _is_docstring(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _insertion_points(tree: ast.Module) -> list[tuple[list[ast.stmt], int]]:
    """Statement lists where dead code may go, each with its lowest safe index.

    Skips class bodies (a new name there becomes a class attribute), keeps
    module/function docstrings first, keeps `from __future__` imports first,
    and leaves empty `orelse`/`finalbody` lists alone (no new else/finally).
    """
    points: list[tuple[list[ast.stmt], int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            continue
        for field_name in ("body", "orelse", "finalbody"):
            body = getattr(node, field_name, None)
            if not isinstance(body, list) or not body or not isinstance(body[0], ast.stmt):
                continue
            start = 0
            if field_name == "body" and isinstance(
                node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                if _is_docstring(body[0]):
                    start = 1
                if isinstance(node, ast.Module):
                    while (
                        start < len(body)
                        and isinstance(body[start], ast.ImportFrom)
                        and body[start].module == "__future__"
                    ):
                        start += 1
            points.append((body, start))
    return points


def _insert_at_random_point(tree: ast.Module, stmt: ast.stmt, rng: random.Random) -> str:
    body, start = rng.choice(_insertion_points(tree))
    body.insert(rng.randint(start, len(body)), stmt)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def _random_literal(rng: random.Random) -> ast.Constant:
    return ast.Constant(
        rng.choice([rng.randint(-1000, 1000), rng.randint(0, 99) / 4, f"s{rng.randrange(1000)}", True, False, None])
    )


def py_insert_unused_variable(source: str, rng: random.Random) -> str:
    """Insert `<fresh_name> = <constant>` at a random valid statement position.

    The name is fresh (never shadows anything) and the value is a constant, so
    the assignment has no observable effect. Placement rules live in
    `_insertion_points`.
    """
    tree = ast.parse(source)
    name = _fresh_name(_used_names(tree), rng, "_unused_")
    stmt = ast.Assign(targets=[ast.Name(name, ast.Store())], value=_random_literal(rng))
    return _insert_at_random_point(tree, stmt, rng)


def py_insert_unused_function(source: str, rng: random.Random) -> str:
    """Insert a never-called `def <fresh_name>(...): ...` at a random valid position.

    The function has no decorators and no defaults, so executing the `def`
    statement only binds a fresh name. Its body is randomized arithmetic over
    its parameters ending in a `return`, so repeated application differs.
    """
    tree = ast.parse(source)
    used = _used_names(tree)
    func_name = _fresh_name(used, rng, "_unused_fn_")
    params = [_fresh_name(used, rng, "_p") for _ in range(rng.randint(1, 3))]

    def load(n: str) -> ast.Name:
        return ast.Name(n, ast.Load())

    ops = [ast.Add(), ast.Sub(), ast.Mult()]
    body: list[ast.stmt] = []
    acc = params[0]
    for p in params[1:] + [None] * rng.randint(0, 2):
        operand = load(p) if p else ast.Constant(rng.randint(1, 9))
        tmp = _fresh_name(used, rng, "_t")
        body.append(
            ast.Assign(
                targets=[ast.Name(tmp, ast.Store())],
                value=ast.BinOp(load(acc), rng.choice(ops), operand),
            )
        )
        acc = tmp
    body.append(ast.Return(load(acc)))

    func = ast.FunctionDef(
        name=func_name,
        args=ast.arguments(
            posonlyargs=[], args=[ast.arg(p) for p in params], kwonlyargs=[], kw_defaults=[], defaults=[]
        ),
        body=body,
        decorator_list=[],
        returns=None,
        type_params=[],
    )
    return _insert_at_random_point(tree, func, rng)


# --------------------------------------------------------------------------
# Java operators — tools/JavaMutator.java (JavaParser) takes the operator
# name + seed as args, reads source on stdin, and writes the mutated source to
# stdout. It uses LexicalPreservingPrinter so untouched code keeps its layout.
# (`javalang` for Python can parse Java but cannot print it back.)
# --------------------------------------------------------------------------


JAVAPARSER_VERSION = "3.28.2"
JAVAPARSER_URL = (
    "https://repo1.maven.org/maven2/com/github/javaparser/javaparser-core/"
    f"{JAVAPARSER_VERSION}/javaparser-core-{JAVAPARSER_VERSION}.jar"
)
# Pinned so a tampered or corrupted download is rejected (SHA-1 cross-checked
# against Maven Central's published .sha1 when this was pinned).
JAVAPARSER_SHA256 = "b5499a3b1c40b16c0671fabe478c9aafeab38160c6fde74a6c13f42d86716ecd"

ROOT = Path(__file__).resolve().parent.parent
MUTATOR_SRC = ROOT / "tools" / "JavaMutator.java"
TOOLS_CACHE = ROOT / ".cache" / "tools"
MUTATOR_TIMEOUT_S = 60


def _javaparser_jar() -> Path:
    """Download (once) and verify the JavaParser jar into .cache/tools/."""
    jar = TOOLS_CACHE / f"javaparser-core-{JAVAPARSER_VERSION}.jar"
    if jar.exists() and hashlib.sha256(jar.read_bytes()).hexdigest() == JAVAPARSER_SHA256:
        return jar
    log.info("downloading JavaParser %s for the Java mutation operators", JAVAPARSER_VERSION)
    TOOLS_CACHE.mkdir(parents=True, exist_ok=True)
    tmp = jar.with_suffix(".part")
    # curl rather than urllib: python.org builds on macOS ship without CA
    # certificates, while curl uses the system trust store.
    proc = subprocess.run(
        ["curl", "-fsSL", "--max-time", "120", "-o", str(tmp), JAVAPARSER_URL],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"could not download JavaParser: {proc.stderr.strip()}")
    digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
    if digest != JAVAPARSER_SHA256:
        tmp.unlink()
        raise RuntimeError(f"JavaParser jar checksum mismatch: got {digest}")
    tmp.replace(jar)
    return jar


def _java_mutator_classpath() -> str:
    """Compile tools/JavaMutator.java (when missing or stale) and return its classpath."""
    jar = _javaparser_jar()
    classes = TOOLS_CACHE / "classes"
    built = classes / "JavaMutator.class"
    if not built.exists() or built.stat().st_mtime < MUTATOR_SRC.stat().st_mtime:
        classes.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            ["javac", "-encoding", "UTF-8", "-cp", str(jar), "-d", str(classes), str(MUTATOR_SRC)],
            capture_output=True,
            text=True,
            timeout=MUTATOR_TIMEOUT_S,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"could not compile JavaMutator: {proc.stderr.strip()}")
    return os.pathsep.join([str(jar), str(classes)])


def _java_mutate(operator: str, source: str, rng: random.Random) -> str:
    proc = subprocess.run(
        ["java", "-cp", _java_mutator_classpath(), "JavaMutator", operator, str(rng.randrange(2**31))],
        input=source,
        capture_output=True,
        text=True,
        timeout=MUTATOR_TIMEOUT_S,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"JavaMutator {operator} failed: {proc.stderr.strip()}")
    return proc.stdout


def java_insert_unused_variable(source: str, rng: random.Random) -> str:
    """Insert a local `<type> <fresh_name> = <literal>;` into a random block.

    Done by tools/JavaMutator.java (JavaParser). It only inserts directly
    before an existing statement (always reachable, so javac never sees an
    unreachable statement) or into an empty block, never ahead of a
    constructor's `this(...)`/`super(...)` call, and always uses a name not
    found anywhere in the program.
    """
    return _java_mutate("unused_variable", source, rng)


def java_insert_unused_function(source: str, rng: random.Random) -> str:
    """Add a never-called `private static` method with a fresh name to a random class.

    Done by tools/JavaMutator.java (JavaParser). Targets only top-level or
    static nested classes, uses only primitive types (no imports needed), and
    a fresh name, so no existing call site can resolve to it.
    """
    return _java_mutate("unused_function", source, rng)


OPERATORS: dict[str, dict[str, MutationOp]] = {
    "python": {
        "unused_variable": py_insert_unused_variable,
        "unused_function": py_insert_unused_function,
    },
    "java": {
        "unused_variable": java_insert_unused_variable,
        "unused_function": java_insert_unused_function,
    },
}


def generate_variants(
    source: str,
    language: str,
    num_variants: int,
    rng: random.Random,
    max_ops_per_variant: int = 3,
) -> list[Variant]:
    """Produce up to `num_variants` distinct mutated variants of `source`.

    Each variant applies 1..max_ops_per_variant operators, chosen at random
    (with repetition — applying the same operator twice is fine). Duplicate
    variants and variants identical to the original are dropped, so fewer than
    `num_variants` may be returned. The caller must still verify behavior
    (stage 2) before using them.
    """
    ops = OPERATORS.get(language, {})
    if not ops:
        log.warning("no mutation operators registered for %s; skipping mutation", language)
        return []

    variants: list[Variant] = []
    seen = {source}
    # A few extra tries in case some variants come out as duplicates.
    for _ in range(num_variants * 3):
        if len(variants) >= num_variants:
            break
        mutated = source
        applied: list[str] = []
        for _ in range(rng.randint(1, max_ops_per_variant)):
            name = rng.choice(sorted(ops))
            try:
                mutated = ops[name](mutated, rng)
            except NotImplementedError as e:
                log.warning("mutation operator %s is not implemented yet; skipping mutation", e)
                return []
            except Exception as e:  # a buggy operator shouldn't kill the whole run
                log.warning("operator %s failed on %s source: %s", name, language, e)
                break
            applied.append(name)
        if applied and mutated not in seen:
            seen.add(mutated)
            variants.append(Variant(id=f"m{len(variants) + 1}", source=mutated, mutations=applied))
    return variants
