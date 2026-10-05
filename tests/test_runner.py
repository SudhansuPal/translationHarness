import json

import pytest

from harness import runner

from .conftest import requires_java


@pytest.fixture
def results_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(runner, "RESULTS_FILE", tmp_path / "results.jsonl")
    monkeypatch.setattr(runner, "TRANSLATIONS_DIR", tmp_path / "translations")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    return tmp_path


@requires_java
def test_dry_run_end_to_end(results_dir, capsys):
    assert runner.main(["--dry-run", "--direction", "python:java", "--direction", "java:python",
                        "--program", "merge_sort"]) == 0
    records = [json.loads(line) for line in (results_dir / "results.jsonl").read_text().splitlines()]
    variants = {(r["direction"], r["variant_id"]) for r in records}
    assert ("python->java", "original") in variants and ("java->python", "original") in variants
    # Mutated variants are generated in both directions and the reference passes on them.
    assert any(v != "original" for d, v in variants if d == "python->java")
    assert any(v != "original" for d, v in variants if d == "java->python")
    assert all(r["passed"] and r["attempt"] == 1 for r in records)
    out = capsys.readouterr().out
    assert "REPORT" in out and "discarded by stage-2 check" in out


def test_load_corpus_rejects_non_array_tests(tmp_path):
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "program.py").write_text("print(1)")
    (tmp_path / "p" / "tests.json").write_text('[{"a": 1}]')
    with pytest.raises(ValueError):
        runner.load_corpus(tmp_path)


def test_report_counts_best_attempt(capsys):
    base = {"direction": "python->java", "program_id": "p", "variant_id": "original",
            "compiled": True, "ran_ok": True, "input_tokens": 1, "output_tokens": 1, "cached": False}
    runner.report([{**base, "passed": False}, {**base, "passed": True}], {})
    out = capsys.readouterr().out
    assert "correctness          : 1/1 (100%)" in out
    assert "correct on attempt 1 : 0/1 (0%)" in out
