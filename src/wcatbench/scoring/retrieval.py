"""Recall@k of a store's own search, ported unchanged from cli-testing's memo_baseline.py `score_run`.

Partial credit: a question with two source records found one of them scores 0.5. Questions with no source (the
"unknown" budget questions) are left out, so the 2K and 10K sets score 40 of 50.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from wcatbench.core.types import AnswerKey

KS = (1, 5, 10)


class SearchRow(BaseModel):
    """One question's search: the corpus record ids it returned, best first."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    query: str
    hits: tuple[str, ...]
    seconds: float
    results: int = 0
    unmapped: int = 0


def percentile(values: Sequence[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(share * (len(ordered) - 1)))]


def score_search(rows: Sequence[SearchRow], keys: Mapping[str, AnswerKey]) -> dict[str, float | int]:
    scored = [row for row in rows if keys[row.id].sources]
    summary: dict[str, float | int] = {"questions_scored": len(scored)}
    for k in KS:
        found = [len(set(keys[row.id].sources) & set(row.hits[:k])) / len(keys[row.id].sources) for row in scored]
        summary[f"recall@{k}"] = sum(found) / len(found) if found else 0.0
    times = [row.seconds for row in rows]
    summary["p50_s"] = statistics.median(times) if times else 0.0
    summary["p95_s"] = percentile(times, 0.95) if times else 0.0
    summary["empty_replies"] = sum(not row.hits for row in rows)
    return summary
