"""Ask a built store each question through its own search, with no answer model, and score recall@k."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wcatbench.core import dataset_files
from wcatbench.core.protocols import Store
from wcatbench.core.types import Hit, Record
from wcatbench.scoring.retrieval import SearchRow, score_search

# Generic English function words, fixed before any run: the keyword rewrite must not be tuned on the answer key.
STOP_WORDS = frozenset(
    "a an and are as at be before by did do does for from had has have how in is it of on or "  # noqa: SIM905
    "the this to was were what when where which who whom why will with".split()
)


def keywords(question: str) -> str:
    words = [word for word in re.findall(r"[\w-]+", question.casefold()) if word not in STOP_WORDS]
    return " OR ".join(f'"{word}"' for word in words)


REWRITES: dict[str, Callable[[str], str]] = {"typed": lambda question: question, "keywords": keywords}


def corpus_ids(hits: Iterable[Hit], names: dict[str, str]) -> tuple[tuple[str, ...], int]:
    """Hit keys to corpus record ids, deduplicated in rank order, and the number of hits that named no record."""
    seen: list[str] = []
    unmapped = 0
    for hit in hits:
        unmapped += not hit.keys
        for key in hit.keys:
            source = names.get(key, f"unmapped:{key}")
            if source not in seen:
                seen.append(source)
    return tuple(seen), unmapped


def search_run(
    store: Store,
    dataset: Path,
    records: list[Record],
    folder: Path,
    rewrites: Iterable[str] = ("typed", "keywords"),
    k: int = 10,
) -> dict[str, Any]:
    """`records` is the whole corpus, so a hit maps back even when the store holds a subset."""
    names = {record.key: record.id for record in records}
    questions = dataset_files.questions(dataset)
    keys = dataset_files.keys(dataset)
    folder.mkdir(parents=True, exist_ok=False)
    held_at_search = store.describe()
    scores = {}
    for rewrite in rewrites:
        rows = []
        for question in questions:
            query = REWRITES[rewrite](question.text)
            started = time.perf_counter()
            hits = store.search(query, k)
            seconds = time.perf_counter() - started
            ids, unmapped = corpus_ids(hits, names)
            rows.append(
                SearchRow(id=question.id, query=query, hits=ids, seconds=seconds, results=len(hits), unmapped=unmapped)
            )
        with (folder / f"{rewrite}.jsonl").open("w") as out:
            out.writelines(row.model_dump_json() + "\n" for row in rows)
        scores[rewrite] = {**score_search(rows, keys), "unmapped": sum(row.unmapped for row in rows)}
    results = {
        "store": store.name,
        "store_version": store.version(),
        "searched": datetime.now(UTC).isoformat(timespec="seconds"),
        "k": k,
        # A store still building memories scores lower: what it held is part of the result.
        "at_search": held_at_search,
        "scores": scores,
    }
    (folder / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    return results
