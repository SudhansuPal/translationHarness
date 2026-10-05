import json

from harness.languages import JAVA, PYTHON
from harness.translate import AnthropicTranslator, DryRunTranslator, build_prompt, extract_code


def test_extract_code_prefers_target_fence():
    text = "```python\nprint(1)\n```\n```java\nclass Main {}\n```"
    assert extract_code(text, JAVA) == "class Main {}\n"


def test_extract_code_falls_back_to_longest_untagged_block():
    text = "```\nshort\n```\nsome prose\n```\nmuch longer block\n```"
    assert extract_code(text, JAVA) == "much longer block\n"


def test_extract_code_none_without_block():
    assert extract_code("no code here", PYTHON) is None


def test_prompt_contains_source_and_target_contract():
    prompt = build_prompt("print(42)", PYTHON, JAVA)
    assert "print(42)" in prompt
    assert JAVA.io_contract in prompt
    assert "```java" in prompt


def test_dry_run_returns_reference_or_error():
    t = DryRunTranslator()
    assert t.translate("src", PYTHON, JAVA, 1, "class Main {}").code == "class Main {}"
    missing = t.translate("src", PYTHON, JAVA, 1, None)
    assert missing.code is None and "Main.java" in missing.error


def test_cached_response_is_used_without_calling_the_api(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    translator = AnthropicTranslator("some-model", tmp_path)

    class NoNetwork:
        def __getattr__(self, name):
            raise AssertionError("API must not be called on a cache hit")

    translator.client = NoNetwork()
    prompt = build_prompt("print(1)", PYTHON, JAVA)
    cache_file = tmp_path / f"{translator._cache_key(prompt, 1)}.json"
    cache_file.write_text(
        json.dumps({"text": "```java\nclass Main {}\n```", "input_tokens": 10, "output_tokens": 5})
    )

    result = translator.translate("print(1)", PYTHON, JAVA, 1, None)
    assert result.cached and result.code == "class Main {}\n"
    assert (result.input_tokens, result.output_tokens) == (10, 5)
    # A different attempt number is a separate request, so it is not a cache hit.
    assert translator._cache_key(prompt, 2) != translator._cache_key(prompt, 1)
