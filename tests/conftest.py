from __future__ import annotations

import pytest

from wcatbench.core.types import AnswerKey, Question, Record


@pytest.fixture
def records() -> list[Record]:
    return [
        Record(id="r0001", kind="telegram", timestamp="2026-01-05", text="Ari Vale owns the Amber Kite project."),
        Record(
            id="r0002",
            kind="mail",
            timestamp="2026-02-10",
            text="Amber Kite moved its launch to the accessibility review.",
        ),
        Record(id="r0003", kind="notes", timestamp="2026-03-01", text="Archive item 3: nothing about any project."),
    ]


@pytest.fixture
def question() -> Question:
    return Question(id="q01", text="Who owns Amber Kite?")


@pytest.fixture
def key() -> AnswerKey:
    return AnswerKey(question_id="q01", answers=("Ari Vale",), sources=("r0001",), stale_answers=("Bo Lind",))
