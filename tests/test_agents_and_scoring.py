from __future__ import annotations

import pytest

from wcatbench.agents.noop import NoopAgent
from wcatbench.agents.oracle import OracleAgent
from wcatbench.core.errors import PermanentError
from wcatbench.core.types import AgentReply, AnswerKey, Question
from wcatbench.scoring.answer import AnswerScorer, normalized


def describe_sanity_agents() -> None:
    def it_gives_the_oracle_a_full_score(question: Question, key: AnswerKey) -> None:
        verdict = AnswerScorer().score(OracleAgent().ask(question, key), key)
        assert verdict == {"correct": True, "correct_strict": True, "cited_correctly": True, "stale": False}

    def it_gives_the_noop_agent_nothing(question: Question, key: AnswerKey) -> None:
        assert not any(AnswerScorer().score(NoopAgent().ask(question), key).values())

    def it_refuses_to_run_the_oracle_without_its_key(question: Question) -> None:
        with pytest.raises(PermanentError):
            OracleAgent().ask(question)


def describe_answer_scorer() -> None:
    def it_ignores_a_leading_article_but_counts_it_strictly(key: AnswerKey) -> None:
        reply = AgentReply(answer="the  ari vale", sources=("r0001",))
        verdict = AnswerScorer().score(reply, key)
        assert verdict["correct"] is True
        assert verdict["correct_strict"] is False

    def it_flags_a_stale_answer(key: AnswerKey) -> None:
        assert AnswerScorer().score(AgentReply(answer="Bo Lind"), key)["stale"] is True

    def it_normalizes_space_and_case() -> None:
        assert normalized("  An  Amber\tKite ") == "amber kite"
