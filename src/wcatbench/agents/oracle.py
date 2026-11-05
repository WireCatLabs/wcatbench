"""Answers from the key. Must score every question on every dataset: if not, the harness or the key is broken."""

from __future__ import annotations

from wcatbench.core.errors import PermanentError
from wcatbench.core.types import AgentReply, AnswerKey, Question


class OracleAgent:
    name = "oracle"

    def version(self) -> str:
        return "1"

    def ask(self, question: Question, key: AnswerKey | None = None) -> AgentReply:
        if key is None or key.question_id != question.id:
            raise PermanentError(f"the oracle needs the key of question {question.id}")
        return AgentReply(answer=key.answers[0], sources=key.sources)
