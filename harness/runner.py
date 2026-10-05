"""Orchestrates the 4-stage pipeline for every (program, direction):

  1. Mutate            generate additive-only variants of the source program
  2. Verify mutations  keep only variants whose outputs match the original
  3. Translate         translate the original + each surviving variant
  4. Verify            build/run each translation, compare with the original;
                       retry up to MAX_RETRIES attempts in total

Writes one JSON record per (program, variant, direction, attempt) to
results/results.jsonl and prints a compilability / correctness report.

Run from the project root:
    python -m harness.runner --dry-run          # plumbing only, no API calls
    python -m harness.runner                    # real run (needs ANTHROPIC_API_KEY)
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .compare import Comparison, compare, expected_outputs
from .execute import run_program
from .languages import LANGUAGES, Language, get_language
from .mutate import Variant, generate_variants
from .translate import AnthropicTranslator, DryRunTranslator, Translator

# ----------------------------------------------------------------------------
# Config — defaults are deliberately small so a smoke test costs very little.
# ----------------------------------------------------------------------------
NUM_VARIANTS = 2  # mutated variants per (program, direction), plus the original
NUM_TESTS = 5  # test inputs used per program (first N of corpus/<prog>/tests.json)
MAX_RETRIES = 3  # translation attempts in total per (program, variant, direction)
DIRECTIONS: list[tuple[str, str]] = [("python", "java")]  # (source, target) pairs
MODEL = "claude-opus-5-5"
SEED = 0  # makes mutation choices reproducible

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "corpus"
RESULTS_DIR = ROOT / "results"
RESULTS_FILE = RESULTS_DIR / "results.jsonl"
TRANSLATIONS_DIR = RESULTS_DIR / "translations"  # every translated program, for debugging
CACHE_DIR = ROOT / ".cache" / "translations"

log = logging.getLogger("harness")


# ----------------------------------------------------------------------------
# Corpus
# ----------------------------------------------------------------------------
@dataclass
class Program:
    id: str
    sources: dict[str, str]  # language name -> source (a language may be missing)
    tests: list[list]


def load_corpus(corpus_dir: Path, only: str | None = None) -> list[Program]:
    """Each corpus/<id>/ holds one source file per language plus tests.json."""
    programs = []
    for d in sorted(p for p in corpus_dir.iterdir() if p.is_dir()):
        if only and d.name != only:
            continue
        sources = {
            lang.name: (d / lang.source_filename).read_text(encoding="utf-8")
            for lang in LANGUAGES.values()
            if (d / lang.source_filename).exists()
        }
        tests = json.loads((d / "tests.json").read_text())
        if not all(isinstance(t, list) for t in tests):
            raise ValueError(f"{d}/tests.json: I/O contract requires every test input to be a JSON array")
        programs.append(Program(d.name, sources, tests))
    if not programs:
        raise SystemExit(f"no programs found in {corpus_dir}" + (f" matching {only!r}" if only else ""))
    return programs


# ----------------------------------------------------------------------------
# Stage 2: mutation verification
# ----------------------------------------------------------------------------
def verify_variants(
    variants: list[Variant], lang: Language, inputs: list[list], expected: list[str]
) -> tuple[list[Variant], list[tuple[Variant, Comparison]]]:
    """Split variants into (behavior-preserving, discarded-with-reason)."""
    kept, discarded = [], []
    for v in variants:
        result = compare(expected, run_program(lang, v.source, inputs), inputs)
        if result.all_passed:
            kept.append(v)
        else:
            discarded.append((v, result))
    return kept, discarded


# ----------------------------------------------------------------------------
# Stages 3 + 4: translate, verify, retry
# ----------------------------------------------------------------------------
def translate_and_verify(
    program: Program,
    variant: Variant,
    src: Language,
    tgt: Language,
    inputs: list[list],
    expected: list[str],
    translator: Translator,
    out,
    run_id: str,
) -> list[dict]:
    direction = f"{src.name}->{tgt.name}"
    records = []
    for attempt in range(1, MAX_RETRIES + 1):
        tr = translator.translate(variant.source, src, tgt, attempt, program.sources.get(tgt.name))

        translation_path = None
        if tr.code is None:
            result = Comparison(False, False, 0, len(inputs), None, tr.error)
        else:
            path = TRANSLATIONS_DIR / program.id / f"{src.name}_to_{tgt.name}" / variant.id / f"attempt{attempt}_{tgt.source_filename}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(tr.code, encoding="utf-8")
            translation_path = str(path.relative_to(ROOT))
            result = compare(expected, run_program(tgt, tr.code, inputs), inputs)

        record = {
            "run_id": run_id,
            "program_id": program.id,
            "variant_id": variant.id,
            "mutations": variant.mutations,
            "direction": direction,
            "attempt": attempt,
            "compiled": result.compiled,
            "ran_ok": result.ran_ok,
            "tests_passed": result.tests_passed,
            "tests_total": result.tests_total,
            "passed": result.all_passed,
            "first_failing_input": result.first_failing_input,
            "error": result.error,
            "input_tokens": tr.input_tokens,
            "output_tokens": tr.output_tokens,
            "cached": tr.cached,
            "translation_path": translation_path,
        }
        out.write(json.dumps(record) + "\n")
        out.flush()
        records.append(record)

        status = "PASS" if result.all_passed else ("FAIL" if result.compiled else "NO-COMPILE")
        log.info(
            "  %s %s attempt %d/%d: %s (%d/%d tests)%s",
            direction, variant.id, attempt, MAX_RETRIES, status,
            result.tests_passed, result.tests_total,
            f" — {_first_line(result.error)}" if result.error and not result.all_passed else "",
        )
        if result.all_passed:
            break
    return records


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0][:160] if text.strip() else ""


# ----------------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------------
def report(records: list[dict], mutation_stats: dict[str, dict[str, int]]) -> None:
    """Per direction: compilability and correctness over translation units.

    A unit is one (program, variant, direction); its outcome is its best attempt.
      compilability = units where some attempt compiled and ran every test
                      without crashing or timing out
      correctness   = units where some attempt also matched the original on
                      every test (always <= compilability)
    """
    units: dict[tuple, list[dict]] = defaultdict(list)
    for r in records:
        units[(r["direction"], r["program_id"], r["variant_id"])].append(r)

    by_dir: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for (direction, _, _), attempts in units.items():
        s = by_dir[direction]
        s["units"] += 1
        s["compiled"] += any(a["compiled"] and a["ran_ok"] for a in attempts)
        s["correct"] += any(a["passed"] for a in attempts)
        s["first_try"] += attempts[0]["passed"]
        s["attempts"] += len(attempts)
        s["tokens"] += sum(a["input_tokens"] + a["output_tokens"] for a in attempts if not a["cached"])

    def pct(n: int, d: int) -> str:
        return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "n/a"

    print("\n" + "=" * 72)
    print("REPORT")
    print("=" * 72)
    for direction in sorted(by_dir):
        s = by_dir[direction]
        m = mutation_stats.get(direction, {})
        print(f"\n{direction}")
        print(f"  mutated variants     : {m.get('generated', 0)} generated, {m.get('discarded', 0)} discarded by stage-2 check")
        print(f"  translation units    : {s['units']}  ({s['attempts']} attempts)")
        print(f"  compilability        : {pct(s['compiled'], s['units'])}")
        print(f"  correctness          : {pct(s['correct'], s['units'])}")
        print(f"  correct on attempt 1 : {pct(s['first_try'], s['units'])}")
        print(f"  tokens spent (uncached): {s['tokens']}")
    print()


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="stub the translator (no API calls)")
    p.add_argument(
        "--direction",
        action="append",
        metavar="SRC:TGT",
        help="translation direction, e.g. python:java (repeatable; default from DIRECTIONS)",
    )
    p.add_argument("--program", help="only run this corpus program id")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    directions = [tuple(d.split(":", 1)) for d in args.direction] if args.direction else DIRECTIONS
    pairs = [(get_language(s), get_language(t)) for s, t in directions]
    programs = load_corpus(CORPUS_DIR, args.program)
    translator: Translator = DryRunTranslator() if args.dry_run else AnthropicTranslator(MODEL, CACHE_DIR)
    rng = random.Random(SEED)
    run_id = time.strftime("%Y%m%d-%H%M%S")

    RESULTS_DIR.mkdir(exist_ok=True)
    records: list[dict] = []
    mutation_stats: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    log.info("run %s: %d program(s), directions=%s%s", run_id, len(programs),
             [f"{s.name}->{t.name}" for s, t in pairs], " [DRY RUN]" if args.dry_run else "")

    with RESULTS_FILE.open("w") as out:  # each run replaces the previous results
        for program in programs:
            inputs = program.tests[:NUM_TESTS]
            for src, tgt in pairs:
                direction = f"{src.name}->{tgt.name}"
                if src.name not in program.sources:
                    log.warning("%s: no %s source, skipping %s", program.id, src.name, direction)
                    continue
                log.info("%s [%s]", program.id, direction)
                source = program.sources[src.name]

                # Ground truth: the original source program's outputs.
                try:
                    expected = expected_outputs(run_program(src, source, inputs), inputs)
                except RuntimeError as e:
                    log.error("%s: original %s program is broken, skipping: %s", program.id, src.name, e)
                    continue

                # Stage 1: mutate (in the source language).
                mutants = generate_variants(source, src.name, NUM_VARIANTS, rng)

                # Stage 2: verify mutations — discard any that changed behavior.
                kept, discarded = verify_variants(mutants, src, inputs, expected)
                for v, why in discarded:
                    log.warning("  discarded bad mutation %s %s: %s", v.id, v.mutations, _first_line(why.error or ""))
                mutation_stats[direction]["generated"] += len(mutants)
                mutation_stats[direction]["discarded"] += len(discarded)

                # Stages 3 + 4: translate and verify, original first.
                for variant in [Variant("original", source, [])] + kept:
                    records += translate_and_verify(
                        program, variant, src, tgt, inputs, expected, translator, out, run_id
                    )

    report(records, mutation_stats)
    log.info("records written to %s", RESULTS_FILE.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
