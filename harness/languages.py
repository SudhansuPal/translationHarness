"""Language registry — the ONLY place that knows language-specific details.

Everything else in the harness (execute, compare, translate, runner) talks to a
`Language` object, never to "python" or "java" directly. To add a new pair
(e.g. CUDA -> OpenMP), add two `Language` entries here with their build/run
commands, I/O-contract instructions, and any runtime support files; the core
pipeline does not change.

I/O contract (all languages): a program reads ONE JSON array from stdin and
writes ONE JSON value to stdout. Nothing else may be printed to stdout
(diagnostics go to stderr). This makes outputs directly comparable across
languages.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

RUNTIME_DIR = Path(__file__).parent / "runtime"


@dataclass(frozen=True)
class Language:
    name: str
    # File name the program is written to inside its build directory. Also the
    # file name used for this language's source in corpus/<program>/.
    source_filename: str
    # Tag for the markdown code fence the LLM is asked to answer in.
    fence: str
    # Command run in the build dir before executing; None = no build step.
    # A non-zero exit means "did not compile".
    build_cmd: list[str] | None
    # Command run in the build dir once per test input (input fed on stdin).
    run_cmd: list[str]
    # Language-specific I/O-contract text inserted into translation prompts.
    io_contract: str
    # Support files copied next to the program before building (e.g. a JSON
    # helper for languages without one in the stdlib).
    runtime_files: tuple[Path, ...] = field(default_factory=tuple)


PYTHON = Language(
    name="python",
    source_filename="program.py",
    fence="python",
    build_cmd=[sys.executable, "-m", "py_compile", "program.py"],
    run_cmd=[sys.executable, "program.py"],
    io_contract=(
        "- Standard library only.\n"
        "- Read the input with `json.load(sys.stdin)`; it is always a JSON array.\n"
        "- Print exactly one JSON value to stdout with `print(json.dumps(result))`.\n"
        "- Print nothing else to stdout (use stderr for any diagnostics).\n"
        "- Integers must stay integers and floats must stay floats in the output."
    ),
)

JAVA = Language(
    name="java",
    source_filename="Main.java",
    fence="java",
    build_cmd=["javac", "-encoding", "UTF-8", "-d", "out", "Main.java", "Json.java"],
    run_cmd=["java", "-cp", "out", "Main"],
    io_contract=(
        "- Standard library only, plus the provided `Json` helper class (already on the\n"
        "  classpath; do NOT define or paste your own `Json` class):\n"
        "    Object Json.parse(String text)   // JSON -> Java: array=List<Object>,\n"
        "        // object=Map<String,Object>, string=String, integer=Long,\n"
        "        // non-integer number=Double, true/false=Boolean, null=null\n"
        "    String Json.stringify(Object v)  // accepts the types above, any\n"
        "        // Collection/Map, Integer/Long/Double, and primitive/object arrays\n"
        "- Put everything in a single file with `public class Main` and a\n"
        "  `public static void main(String[] args)`; no package declaration.\n"
        "- Read ALL of stdin as a String and parse it with `Json.parse`; the input is\n"
        "  always a JSON array.\n"
        "- Print exactly one JSON value with `System.out.println(Json.stringify(result))`.\n"
        "- Print nothing else to stdout (use System.err for any diagnostics).\n"
        "- Integers must stay integers (Long/Integer) and floats must stay floats\n"
        "  (Double) in the output."
    ),
    runtime_files=(RUNTIME_DIR / "Json.java",),
)

LANGUAGES: dict[str, Language] = {lang.name: lang for lang in (PYTHON, JAVA)}


def get_language(name: str) -> Language:
    try:
        return LANGUAGES[name]
    except KeyError:
        raise ValueError(f"unknown language {name!r}; known: {sorted(LANGUAGES)}") from None
