"""The deterministic answer scorer, ported unchanged from cli-testing's knowledge-graph-memory run.py.

Unchanged on purpose: rescoring the published runs must give the published numbers.
"""

from __future__ import annotations

import re

from wcatbench.core.types import AgentReply, AnswerKey


def normalized(value: str, *, strict: bool = False) -> str:
    text = re.sub(r"\s+", " ", value.strip().casefold())
    # "the accessibility review" names the same thing as the key's "accessibility review".
    return text if strict else re.sub(r"^(the|a|an) ", "", text)


class AnswerScorer:
    name = "answer"

    def score(self, reply: AgentReply, key: AnswerKey) -> dict[str, bool]:
        answer = normalized(reply.answer)
        correct = answer in {normalized(value) for value in key.answers}
        strict = normalized(reply.answer, strict=True) in {normalized(value, strict=True) for value in key.answers}
        cited = set(reply.sources) == set(key.sources) if key.sources else not reply.sources
        return {
            "correct": correct,
            "correct_strict": strict,
            "cited_correctly": correct and cited,
            "stale": answer in {normalized(value) for value in key.stale_answers},
        }
