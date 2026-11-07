"""The bridge to cli-testing's agent runners: a built dataset as their fixture folder, and their answers scored.

The runners (openclaw_runner.py, hermes_runner.py) read corpus.jsonl, queries.json and oracle.json from a folder
that cli-testing's run.py wrote, and run.py scores their predictions.json. run.py only knows versions 1 and 2, so
for version 3 this writes the same files from a wcatbench dataset and scores with wcatbench's scorer.
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from wcatbench.core import dataset_files
from wcatbench.core.errors import PermanentError
from wcatbench.core.types import AgentReply
from wcatbench.scoring.answer import AnswerScorer

KINDS = "kinds.json"
EXTRA = ("subset-mem0.json", KINDS)


def fixture_manifest(dataset: Path) -> dict[str, Any]:
    manifest = dataset_files.manifest(dataset)
    return {
        "fixture_version": manifest.version,
        "seed": manifest.params.get("seed"),
        "records": manifest.records,
        "questions": manifest.questions,
        "sha256": manifest.corpus_sha256,
        "wcatbench_dataset": dataset.name,
        **{key: value for key, value in manifest.extra.items() if key != "source_counts"},
    }


def export_fixture(dataset: Path, out: Path) -> dict[str, Any]:
    if out.exists():
        raise PermanentError(f"{out} exists; a fixture folder is written once")
    dataset_files.records(dataset)  # refuses a corpus that no longer matches its manifest
    out.mkdir(parents=True)
    shutil.copy2(dataset / dataset_files.CORPUS, out / "corpus.jsonl")
    for name in EXTRA:
        if (dataset / name).exists():
            shutil.copy2(dataset / name, out / name)
    keys = dataset_files.keys(dataset)
    queries, oracle = [], []
    for question in dataset_files.questions(dataset):
        key = keys[question.id]
        query = {"id": question.id, "question": question.text, "as_of": question.as_of}
        queries.append(query)
        oracle.append(
            {
                **query,
                "answers": list(key.answers),
                "required_citations": list(key.sources),
                "stale_answers": list(key.stale_answers),
                **({"form": key.form} if key.form else {}),
            }
        )
    manifest = fixture_manifest(dataset)
    for name, value in (("queries.json", queries), ("oracle.json", oracle), ("manifest.json", manifest)):
        dataset_files.write_json(out / name, value)
    return manifest


def score_predictions(dataset: Path, predictions: list[dict[str, Any]], engine: str, out: Path) -> dict[str, Any]:
    """Writes scores.json (run.py's shape plus totals by family), per-question.json, and the fixture files."""
    keys = dataset_files.keys(dataset)
    by_id = {row["id"]: row for row in predictions}
    if len(by_id) != len(predictions) or set(by_id) != set(keys):
        raise PermanentError("predictions must answer every question exactly once, with no extra ids")
    kinds = {row["id"]: row for row in json.loads((dataset / KINDS).read_text())} if (dataset / KINDS).exists() else {}
    scorer, totals, families = AnswerScorer(), Counter[str](), dict[str, Counter[str]]()
    rows = []
    for qid, key in keys.items():
        prediction = by_id[qid]
        reply = AgentReply(answer=str(prediction.get("answer", "")), sources=tuple(prediction.get("citations") or ()))
        result = scorer.score(reply, key)
        totals.update(name for name, hit in result.items() if hit)
        family = kinds.get(qid, {}).get("family", "all")
        families.setdefault(family, Counter()).update({"questions": 1, **{n: int(h) for n, h in result.items()}})
        rows.append({"id": qid, **kinds.get(qid, {}), "answer": reply.answer, "expected": key.answers[0], **result})
    scores = {
        "engine": engine,
        **{name: totals[name] for name in ("correct", "cited_correctly", "stale", "correct_strict")},
        "by_family": {family: dict(counts) for family, counts in families.items()},
    }
    if out.exists():
        raise PermanentError(f"{out} exists; a score folder is written once")
    export_fixture(dataset, out)
    dataset_files.write_json(out / "scores.json", scores)
    dataset_files.write_json(out / "per-question.json", rows)
    return scores
