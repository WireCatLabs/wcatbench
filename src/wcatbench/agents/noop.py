"""Answers nothing. Must score zero: if not, the scorer accepts empty answers."""

from __future__ import annotations

from wcatbench.core.types import AgentReply, AnswerKey, Question


class NoopAgent:
    name = "noop"

    def version(self) -> str:
        return "1"

    def ask(self, question: Question, key: AnswerKey | None = None) -> AgentReply:
        return AgentReply(answer="")
