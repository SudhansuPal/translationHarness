"""Stage 3: translate a program into the target language with Claude.

- `AnthropicTranslator` calls the Messages API and caches every response on disk,
  keyed by a hash of (model, system prompt, user prompt, attempt number), so a
  re-run never re-spends credits on a request it has already made.
- `DryRunTranslator` makes no API calls: it returns the corpus's reference
  implementation in the target language, so you can exercise the full pipeline
  plumbing for free.

Retries are driven by runner.py. Each attempt is an independent sample: the
attempt number is part of the cache key, so attempt 2 is a fresh request, not
a cache hit on attempt 1.

Language-agnostic: all language-specific prompt text comes from `Language`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .languages import Language

log = logging.getLogger(__name__)

MAX_TOKENS = 16000

SYSTEM_PROMPT = (
    "You are an expert programmer translating programs between languages. "
    "Your translations must preserve observable behavior exactly: for every input, "
    "the translated program must print byte-for-byte the same JSON value as the original."
)

# The I/O co-translation prompt: the program's I/O handling is translated along
# with its logic, and both sides are held to the same JSON stdin/stdout contract.
PROMPT_TEMPLATE = """\
Translate the following {src_name} program into {tgt_name}.

Behavior must be identical: on every input the {tgt_name} program must produce the \
same output as the {src_name} program. Translate the program's I/O handling together \
with its logic.

I/O contract (both programs follow it):
- The program reads exactly one JSON array from standard input.
- The program writes exactly one JSON value (its result) to standard output, and \
nothing else.
- The output JSON must match the original's output exactly: same values, same \
element order, same types (an integer must not become a float, or vice versa).

{tgt_name}-specific requirements:
{tgt_contract}

Additional rules:
- Translate the whole program faithfully, including any code that looks unused \
or redundant. Do not optimize, simplify, or "fix" the original's behavior.
- Respond with the complete {tgt_name} program in a single ```{tgt_fence} code \
block and nothing else.

{src_name} program:
```{src_fence}
{source}
```
"""


def build_prompt(source: str, src: Language, tgt: Language) -> str:
    return PROMPT_TEMPLATE.format(
        src_name=src.name.capitalize(),
        tgt_name=tgt.name.capitalize(),
        src_fence=src.fence,
        tgt_fence=tgt.fence,
        tgt_contract=tgt.io_contract,
        source=source,
    )


def extract_code(text: str, lang: Language) -> str | None:
    """Pull the program out of the model's reply (prefers a block tagged with the target fence)."""
    blocks = re.findall(r"```([\w+#-]*)[ \t]*\n(.*?)```", text, flags=re.DOTALL)
    tagged = [body for tag, body in blocks if tag.lower() == lang.fence]
    chosen = tagged or [body for _, body in blocks]
    if not chosen:
        return None
    # If several blocks came back, the longest is almost always the full program.
    return max(chosen, key=len).strip() + "\n"


@dataclass
class Translation:
    code: str | None  # None if the request failed or no code block was found
    raw_text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cached: bool = False
    error: str | None = None


class Translator(Protocol):
    def translate(
        self, source: str, src: Language, tgt: Language, attempt: int, reference: str | None
    ) -> Translation: ...


class DryRunTranslator:
    """Stub translator for --dry-run: returns the corpus reference in the target language."""

    def translate(self, source, src, tgt, attempt, reference):
        if reference is None:
            return Translation(code=None, error=f"dry-run: corpus has no reference {tgt.source_filename}")
        return Translation(code=reference, raw_text="(dry-run)")


class AnthropicTranslator:
    """Claude-backed translator with an on-disk response cache."""

    def __init__(self, model: str, cache_dir: Path):
        import anthropic  # imported lazily so --dry-run works without the SDK installed

        self._anthropic = anthropic
        # Credentials: ANTHROPIC_API_KEY from the environment (or an `ant auth login` profile).
        self.client = anthropic.Anthropic()
        self.model = model
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_key(self, prompt: str, attempt: int) -> str:
        payload = json.dumps(
            {"model": self.model, "system": SYSTEM_PROMPT, "prompt": prompt, "attempt": attempt},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def translate(self, source, src, tgt, attempt, reference):
        prompt = build_prompt(source, src, tgt)
        cache_file = self.cache_dir / f"{self._cache_key(prompt, attempt)}.json"

        if cache_file.exists():
            entry = json.loads(cache_file.read_text())
            text = entry["text"]
            code = extract_code(text, tgt)
            return Translation(
                code=code,
                raw_text=text,
                input_tokens=entry["input_tokens"],
                output_tokens=entry["output_tokens"],
                cached=True,
                error=None if code else "no code block in cached response",
            )

        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                # If a safety classifier declines, re-run server-side on Anthropic's
                # recommended fallback model instead of returning a refusal.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except self._anthropic.APIStatusError as e:
            # The SDK already retried 408/409/429/5xx; anything reaching here is final.
            return Translation(code=None, error=f"API error {e.status_code}: {e.message}")
        except self._anthropic.APIConnectionError as e:
            return Translation(code=None, error=f"API connection error: {e}")

        usage = response.usage
        if response.stop_reason == "refusal":
            return Translation(
                code=None,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                error="model refused the request",
            )

        text = "".join(block.text for block in response.content if block.type == "text")
        # Only cache complete responses; a truncated one should be retried for real.
        if response.stop_reason != "max_tokens":
            cache_file.write_text(
                json.dumps(
                    {
                        "model": self.model,
                        "attempt": attempt,
                        "text": text,
                        "input_tokens": usage.input_tokens,
                        "output_tokens": usage.output_tokens,
                    },
                    indent=2,
                )
            )
        code = extract_code(text, tgt)
        error = None
        if response.stop_reason == "max_tokens":
            error = "response truncated at max_tokens"
        elif code is None:
            error = "no code block in response"
        return Translation(
            code=code,
            raw_text=text,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            error=error,
        )
