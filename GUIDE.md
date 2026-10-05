# Translation Harness — Personal Manual

This is a plain-language walkthrough of what the harness does and how to use it.
For a short summary, see `README.md`.

---

## 1. What it is, in one paragraph

You give the harness a program in one language, for example Python. It asks
Claude to translate it into another language, for example Java. Then it
**checks** the translation by running both programs on the same inputs and
comparing their outputs exactly. A translation "passes" only when it compiles,
runs without crashing, and prints the same result as the original on every
test input. If an attempt fails, it asks Claude again, up to 3 attempts in
total. Every result is logged so you can see what worked and what didn't.

---

## 2. Quick start (copy/paste)

```bash
cd ~/translationHarness

# 0. Run the test suite (free, ~1 minute)
.venv/bin/python -m pytest

# 1. Free plumbing check (no API calls, no cost)
.venv/bin/python -m harness.runner --dry-run

# 2. Real run: translate every corpus program Python -> Java
.venv/bin/python -m harness.runner --direction python:java

# 3. Real run on ONE program only
.venv/bin/python -m harness.runner --direction python:java --program bubblesort

# 4. The other direction (needs a Main.java in the program's folder)
.venv/bin/python -m harness.runner --direction java:python --program merge_sort

# 5. Both directions in one run
.venv/bin/python -m harness.runner --direction python:java --direction java:python

# Add -v for debug-level logging
```

The API key comes from `ANTHROPIC_API_KEY`, which is exported in `~/.zshrc`.
Open a new terminal, or run `source ~/.zshrc`, after changing it.

In VS Code, the Run and Debug panel has two ready-made configurations:
"dry run" and "real run (python -> java)". They are defined in
`.vscode/launch.json`.

---

## 3. Adding a program to translate

Each program is a folder under `corpus/`:

```
corpus/
  bubblesort/
    program.py     <- Python source   (MUST be named exactly this)
    Main.java      <- Java source     (optional; MUST be named exactly this)
    tests.json     <- test inputs     (required)
```

The corpus ships with `binary_search`, `bubblesort`, `fibonacci`,
`merge_sort`, `stats` and `word_count`, each in both languages. When a
program has both, `tests/test_corpus.py` checks that the two versions print
identical output on every test, so run `pytest` after adding one.

- The folder name is the program's id, used with `--program <id>`.
- You need at least the source for the language you translate **from**.
- **`tests.json` is required.** If any folder is missing it, the whole run
  crashes.
- Other file names, such as `bubble.py`, are silently ignored.

### The I/O contract (the most important rule)

Every program must:

1. **Read ONE JSON array from stdin.**
2. **Print ONE JSON value to stdout**, and nothing else. Send debug prints to
   stderr.

The harness feeds each test input to the program through stdin and compares
what it prints. Programs with hard-coded inputs, like the first version of
`bubble.py` (`print(bubble_sort([5, 2, 9, 1, 5, 6]))`), can't be tested with
different inputs. So wrap the logic like this:

```python
import json
import sys

def my_function(arr):
    ...

def main():
    data = json.load(sys.stdin)          # e.g. [5, 2, 9, 1, 5, 6]
    print(json.dumps(my_function(data)))

if __name__ == "__main__":
    main()
```

If your function takes several arguments, pass them as elements of the array.
For example, with input `[[3,1,2], true]`, call `f(data[0], data[1])`.

Java programs follow the same rule. They use the helper
`harness/runtime/Json.java` (`Json.parse` and `Json.stringify`), which is
provided automatically. See `corpus/merge_sort/Main.java` for an example.

### tests.json

A JSON list where **each element is one input array**:

```json
[
  [5, 2, 9, 1, 5, 6],
  [],
  [3, 1, 2]
]
```

> ⚠️ Only the **first 5** tests are used (`NUM_TESTS = 5` in
> `harness/runner.py`). Put your most important cases first, or raise that
> number.

Quick sanity check that your program follows the contract:

```bash
echo '[5, 2, 9, 1, 5, 6]' | python3 corpus/bubblesort/program.py
# -> [1, 2, 5, 5, 6, 9]
```

---

## 4. How it processes everything (the pipeline)

`harness/runner.py` runs these steps for each program and each direction:

```
 original program.py
        │
        ├─► (0) Ground truth: run the ORIGINAL on every test input and record
        │       its outputs. If the original crashes or breaks the contract,
        │       the program is skipped.
        │
        ├─► (1) Mutate          [harness/mutate.py]
        │       Make variants by ADDING dead code (unused variables or unused
        │       functions). The goal is to test whether Claude's translation is
        │       robust to harmless changes.
        │       Python: stdlib `ast`. Java: tools/JavaMutator.java
        │       (JavaParser), downloaded + compiled into .cache/tools/ on
        │       first use. Each variant adds 1-3 pieces of dead code.
        │
        ├─► (2) Verify mutants  [runner.verify_variants]
        │       Run each variant and throw it away if its output differs from
        │       the original's. A buggy mutation can never be blamed on the
        │       translator.
        │
        ├─► (3) Translate       [harness/translate.py]
        │       Build a prompt (the source, the I/O contract, and the rule
        │       "translate faithfully") and send it to Claude (MODEL in
        │       runner.py). The code block is extracted from the reply.
        │
        └─► (4) Verify          [harness/execute.py + harness/compare.py]
                Write the translation to a temp dir, then compile it
                (javac / py_compile). Run it on every test input (10s
                timeout each) and compare its output with the ground truth.
                  - PASS       → stop
                  - FAIL / NO-COMPILE → try again (up to MAX_RETRIES = 3)
```

### How outputs are compared (`compare.py`)

Outputs are parsed as JSON and compared as **values**, not raw text:

- `[1, 2]` and `[1,2]` are **equal**. Spacing doesn't matter.
- `1` and `1.0` are **not equal**. An int turning into a float is a bug.
- List order matters, and types must match.
- Empty output, extra printed lines, or non-JSON output is a contract
  violation, which counts as a failure.

### What each file does

| File | Role |
|---|---|
| `harness/runner.py` | Main entry point. Holds the config constants, loads the corpus, runs the pipeline, writes results, and prints the report. |
| `harness/languages.py` | The only file that knows Python and Java details: file names, compile and run commands, and contract text for the prompt. |
| `harness/translate.py` | Builds the prompt, calls the Claude API, caches responses, and extracts code. Also holds `DryRunTranslator`. |
| `harness/execute.py` | Compiles and runs a program in a temp dir, one process per test input. |
| `harness/compare.py` | Compares outputs as JSON values. |
| `harness/mutate.py` | Mutation operators. Python ones work on the `ast`; Java ones call the helper below. |
| `tools/JavaMutator.java` | JavaParser-based helper that inserts dead code into Java source, keeping the original layout. |
| `harness/runtime/Json.java` | JSON helper copied next to every Java program. |
| `tests/` | pytest suite: comparison, execution, prompt/cache, mutation safety, corpus agreement, and an end-to-end dry run. |

---

## 5. Reading the results

### The terminal report

```
python->java
  mutated variants     : 0 generated, 0 discarded by stage-2 check
  translation units    : 1  (1 attempts)
  compilability        : 1/1 (100%)   <- some attempt compiled and ran every test without crashing
  correctness          : 1/1 (100%)   <- some attempt matched the original on every test
  correct on attempt 1 : 1/1 (100%)   <- got it right the first time
  tokens spent (uncached): 2488       <- what this run actually cost
```

A "translation unit" is one (program, variant, direction) combination.

Per-attempt log lines say `PASS`, `FAIL`, or `NO-COMPILE`, followed by the
first error.

### Files written

| Where | What |
|---|---|
| `results/results.jsonl` | One JSON line per attempt: pass/fail, tests passed, first failing input, error, and tokens. **Overwritten on every run**, so copy it somewhere first if you want to keep it. |
| `results/translations/<program>/<src>_to_<tgt>/<variant>/attemptN_<file>` | The code Claude produced for each attempt. Open these to read the translations. For example, `results/translations/bubblesort/python_to_java/original/attempt1_Main.java`. |
| `.cache/translations/*.json` | Raw API responses (see below). |

To pretty-print results:

```bash
cat results/results.jsonl | python3 -m json.tool --json-lines
```

---

## 6. Cost and caching

- Every API response is **cached** in `.cache/translations/`. The cache key
  is a hash of the model, prompt, and attempt number. **Re-running the same
  program costs nothing**: those attempts show `"cached": true` and aren't
  counted in "tokens spent".
- The cache is invalidated when you change the source program, the prompt,
  the model, or the language contract text.
- **To force a fresh translation**, delete the cache: `rm -rf .cache/translations`.
- `--dry-run` never calls the API. It returns the hand-written reference in
  the target language, such as `Main.java`. If a program has no reference in
  the target language, dry-run shows `NO-COMPILE — dry-run: corpus has no
  reference Main.java`. **That is expected**: dry-run only tests plumbing.
- The first bubblesort translation used about 2.5k tokens, which is a tiny
  amount.

---

## 7. Knobs you can turn (top of `harness/runner.py`)

| Setting | Default | Meaning |
|---|---|---|
| `NUM_VARIANTS` | 2 | Mutated variants per program and direction |
| `NUM_TESTS` | 5 | How many entries of `tests.json` are used |
| `MAX_RETRIES` | 3 | Translation attempts per unit |
| `DIRECTIONS` | `[("python","java")]` | Default direction when `--direction` isn't given |
| `MODEL` | `claude-opus-5-5` | Claude model used for translation |
| `SEED` | 0 | Makes mutation choices reproducible |

Timeouts are in `harness/execute.py`: 60s to compile, 10s per test run.

---

## 8. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `FileNotFoundError: .../tests.json` | A corpus folder has no `tests.json`. Add one or remove the folder. |
| Program silently not run / "no python source, skipping" | The file isn't named `program.py` (or `Main.java`). |
| `original python program is broken, skipping` | Your original crashes on a test input or prints non-JSON. Test it with `echo '[...]' \| python3 program.py`. |
| `API error 401` | Bad or missing key. Check `echo ${#ANTHROPIC_API_KEY}` (prints the length, not the key). |
| `No module named anthropic` | You used system python. Use `.venv/bin/python`. |
| "could not download JavaParser" | The first Java mutation needs internet once (Maven Central). After that the jar is cached in `.cache/tools/`. |
| "operator ... failed on java source" | Usually `javac`/`java` is missing from PATH. Check `javac -version`. |
| Translation looks huge (type helpers, etc.) | Normal. Claude is making Java mimic Python's dynamic comparisons exactly, because the prompt demands identical behavior. |
