"""The deterministic answer scorer, ported unchanged from cli-testing's knowledge-graph-memory run.py.

Unchanged on purpose: rescoring the published runs must give the published numbers. A key with a `form`
(dataset version 3) compares the value instead of the text, so "€12,500" and "EUR 12,500" are the same amount.
"""

from __future__ import annotations

import re

from wcatbench.core.types import AgentReply, AnswerKey

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
NUMBERS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def normalized(value: str, *, strict: bool = False) -> str:
    text = re.sub(r"\s+", " ", value.strip().casefold())
    # "the accessibility review" names the same thing as the key's "accessibility review".
    return text if strict else re.sub(r"^(the|a|an) ", "", text)


def formed(value: str, form: str | None, *, strict: bool = False) -> str:
    """The value an answer states, in one spelling; text that states none falls back to `normalized`."""
    text = normalized(value, strict=strict)
    found: str | None = None
    if form == "amount" and (match := re.search(r"(\d[\d,. ]*\d|\d)\s*(k\b)?", text)):
        digits = re.sub(r"[ ,]", "", match[1])
        amount = float(digits) * (1000 if match[2] else 1) if digits.count(".") <= 1 else None
        found = f"{amount:.2f}" if amount is not None else None
    elif form == "datetime" and (match := re.search(r"(\d{4}-\d{2}-\d{2})\D+?(\d{1,2}):(\d{2})", text)):
        found = f"{match[1]} {int(match[2]):02}:{match[3]}"
    elif form == "date" and (match := re.search(r"\d{4}-\d{2}-\d{2}", text)):
        found = match[0]
    elif form == "count" and (match := re.search(r"\d+|" + "|".join(rf"\b{n}\b" for n in NUMBERS), text)):
        found = match[0] if match[0].isdigit() else str(NUMBERS.index(match[0]))
    elif form == "weekday":
        found = next((day for day in WEEKDAYS if day in text), None)
    return found or text


class AnswerScorer:
    name = "answer"

    def score(self, reply: AgentReply, key: AnswerKey) -> dict[str, bool]:
        answer = formed(reply.answer, key.form)
        correct = answer in {formed(value, key.form) for value in key.answers}
        strict = normalized(reply.answer, strict=True) in {normalized(value, strict=True) for value in key.answers}
        cited = set(reply.sources) == set(key.sources) if key.sources else not reply.sources
        return {
            "correct": correct,
            "correct_strict": strict,
            "cited_correctly": correct and cited,
            "stale": answer in {formed(value, key.form) for value in key.stale_answers},
        }
