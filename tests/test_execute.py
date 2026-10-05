import pytest

from harness.execute import run_program
from harness.languages import JAVA, PYTHON

from .conftest import requires_java

ECHO_PY = "import json, sys\nprint(json.dumps(sum(json.load(sys.stdin))))\n"


def test_python_runs_each_input_in_its_own_process():
    run = run_program(PYTHON, ECHO_PY, [[1, 2], [], [5]])
    assert run.compiled
    assert [t.status for t in run.tests] == ["ok", "ok", "ok"]
    assert [t.stdout.strip() for t in run.tests] == ["3", "0", "5"]


def test_python_syntax_error_does_not_compile():
    run = run_program(PYTHON, "def broken(:\n", [[1]])
    assert not run.compiled and run.compile_error


def test_python_crash_is_reported():
    run = run_program(PYTHON, "raise SystemExit(3)\n", [[1]])
    assert run.tests[0].status == "crash" and run.tests[0].returncode == 3


def test_inputs_must_be_arrays():
    with pytest.raises(ValueError):
        run_program(PYTHON, ECHO_PY, [{"not": "an array"}])


@requires_java
def test_java_gets_json_helper_on_classpath():
    source = (
        "import java.util.List;\n"
        "public class Main { public static void main(String[] a) throws Exception {\n"
        "  List<?> d = (List<?>) Json.parse(new String(System.in.readAllBytes()));\n"
        "  System.out.println(Json.stringify(d.size()));\n"
        "} }\n"
    )
    run = run_program(JAVA, source, [[1, 2, 3]])
    assert run.compiled, run.compile_error
    assert run.tests[0].stdout.strip() == "3"


@requires_java
def test_java_compile_error():
    run = run_program(JAVA, "public class Main { oops }", [[1]])
    assert not run.compiled and "error" in run.compile_error
