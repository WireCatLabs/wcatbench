from __future__ import annotations

import json
from pathlib import Path

import pytest

from wcatbench.agents.noop import NoopAgent
from wcatbench.agents.oracle import OracleAgent
from wcatbench.core import dataset_files
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


def describe_answer_forms() -> None:
    def _scored(answer: str, key: AnswerKey) -> dict[str, bool]:
        return AnswerScorer().score(AgentReply(answer=answer), key)

    @pytest.mark.parametrize("answer", ["EUR 12,500", "€12,500", "12 500 EUR", "12.5k euros", "12500"])
    def it_reads_an_amount_in_any_spelling(answer: str) -> None:
        key = AnswerKey(question_id="q1", answers=("EUR 12,500",), stale_answers=("EUR 10,000",), form="amount")
        assert _scored(answer, key)["correct"]
        assert _scored("EUR 10,000", key)["stale"]

    def it_reads_a_date_and_time_with_its_zone_named() -> None:
        key = AnswerKey(question_id="q1", answers=("2026-10-26 22:30",), form="datetime")
        assert _scored("2026-10-26 22:30 Madrid time", key)["correct"]
        assert not _scored("2026-10-26 21:30", key)["correct"]

    def it_keeps_cancelled_as_text_when_a_date_is_expected() -> None:
        key = AnswerKey(question_id="q1", answers=("cancelled",), stale_answers=("2026-11-17",), form="date")
        assert _scored("Cancelled", key)["correct"]
        assert _scored("2026-11-17", key)["stale"]

    def it_reads_a_count_and_a_weekday() -> None:
        count = AnswerKey(question_id="q1", answers=("3",), form="count")
        weekday = AnswerKey(question_id="q2", answers=("Thursday",), form="weekday")
        assert _scored("three times", count)["correct"]
        assert _scored("on Thursdays", weekday)["correct"]

    def it_writes_a_key_without_a_form_as_before(tmp_path: Path) -> None:
        keys = [AnswerKey(question_id="q1", answers=("x",)), AnswerKey(question_id="q2", answers=("3",), form="count")]
        dataset_files.write(tmp_path, [], [], keys)
        assert [sorted(row) for row in json.loads((tmp_path / dataset_files.KEY).read_text())] == [
            ["answers", "question_id", "sources", "stale_answers"],
            ["answers", "form", "question_id", "sources", "stale_answers"],
        ]
