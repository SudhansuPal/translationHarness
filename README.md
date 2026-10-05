# Translation harness (Python <-> Java)

Differential test of LLM code translation: mutate -> verify mutants -> translate -> verify translations.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   # requirements.txt + pytest
.venv/bin/python -m pytest                                       # test suite (~1 min, needs a JDK)
.venv/bin/python -m harness.runner --dry-run                     # plumbing only, free
export ANTHROPIC_API_KEY=...
.venv/bin/python -m harness.runner --direction python:java       # real run
.venv/bin/python -m harness.runner --direction java:python --program merge_sort
```

- Config constants (`NUM_VARIANTS`, `NUM_TESTS`, `MAX_RETRIES`, `DIRECTIONS`, `MODEL`) are at the top of `harness/runner.py`.
- I/O contract: a program reads one JSON array on stdin and prints one JSON value on stdout. Java programs get `harness/runtime/Json.java` on the classpath.
- Corpus layout: `corpus/<id>/program.py`, `corpus/<id>/Main.java` (either or both), `corpus/<id>/tests.json` (list of input arrays).
- Results: `results/results.jsonl` (replaced each run), translated programs under `results/translations/`, API responses cached in `.cache/translations/`.
- New language pair: add `Language` entries in `harness/languages.py` and operators in `harness/mutate.py`.
- Mutation operators in `harness/mutate.py`: Python ones use the stdlib `ast`; Java ones call `tools/JavaMutator.java` (JavaParser). The first Java mutation downloads the pinned, checksum-verified JavaParser jar with `curl` and compiles the tool into `.cache/tools/`.
- Requirements: Python 3.11+ and a JDK (17+) with `javac`/`java` on PATH.
