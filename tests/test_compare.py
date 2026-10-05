import pytest

from harness.compare import ContractViolation, canonicalize, compare, expected_outputs
from harness.execute import ProgramRun
from harness.execute import TestRun as Run  # aliased so pytest doesn't collect it


def ok(stdout):
    return Run(status="ok", stdout=stdout, returncode=0)


def test_whitespace_and_key_order_do_not_matter():
    assert canonicalize("[1, 2]\n") == canonicalize("[1,2]")
    assert canonicalize('{"b": 1, "a": 2}') == canonicalize('{"a":2,"b":1}')


def test_int_and_float_are_different():
    assert canonicalize("1") != canonicalize("1.0")


def test_equivalent_float_spellings_match():
    assert canonicalize("1e20") == canonicalize("1.0E20")


@pytest.mark.parametrize("stdout", ["", "   \n", "[1]\n[2]", "hello", "NaN", "[Infinity]"])
def test_contract_violations(stdout):
    with pytest.raises(ContractViolation):
        canonicalize(stdout)


def test_compare_counts_passes_and_reports_first_failure():
    inputs = [[1], [2], [3]]
    expected = [canonicalize("1"), canonicalize("2"), canonicalize("3")]
    run = ProgramRun(compiled=True, tests=[ok("1"), ok("20"), ok("3.0")])
    result = compare(expected, run, inputs)
    assert (result.tests_passed, result.tests_total) == (1, 3)
    assert result.ran_ok and not result.all_passed
    assert result.first_failing_input == [2]
    assert "mismatch" in result.error


def test_compare_crash_marks_not_ran_ok():
    run = ProgramRun(compiled=True, tests=[Run(status="crash", stderr="boom", returncode=1)])
    result = compare([canonicalize("1")], run, [[1]])
    assert not result.ran_ok and result.tests_passed == 0
    assert "boom" in result.error


def test_compare_not_compiled():
    result = compare([canonicalize("1")], ProgramRun(compiled=False, compile_error="syntax"), [[1]])
    assert not result.compiled and not result.all_passed and result.error == "syntax"


def test_expected_outputs_rejects_broken_reference():
    with pytest.raises(RuntimeError):
        expected_outputs(ProgramRun(compiled=True, tests=[ok("not json")]), [[1]])
    with pytest.raises(RuntimeError):
        expected_outputs(ProgramRun(compiled=False, compile_error="x"), [[1]])
