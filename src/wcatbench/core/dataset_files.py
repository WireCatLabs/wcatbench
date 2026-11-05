"""A built dataset on disk: corpus.jsonl, questions.json, key.json and manifest.json in one folder.

Questions and the key are separate files so an agent's sandbox can receive the questions without the answers.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from wcatbench.core.errors import PermanentError
from wcatbench.core.manifest import sha256_file
from wcatbench.core.types import AnswerKey, DatasetManifest, Question, Record

CORPUS, QUESTIONS, KEY, MANIFEST = "corpus.jsonl", "questions.json", "key.json", "manifest.json"


def corpus_lines(records: Iterable[Record]) -> str:
    return "".join(
        json.dumps(record.model_dump(exclude_defaults=True), ensure_ascii=False) + "\n" for record in records
    )


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write(folder: Path, records: list[Record], questions: list[Question], keys: list[AnswerKey]) -> tuple[str, str]:
    """Returns the corpus and key digests."""
    (folder / CORPUS).write_text(corpus_lines(records))
    write_json(folder / QUESTIONS, [question.model_dump(exclude_defaults=True) for question in questions])
    write_json(folder / KEY, [key.model_dump(mode="json") for key in keys])
    return sha256_file(folder / CORPUS), sha256_file(folder / KEY)


def manifest(folder: Path) -> DatasetManifest:
    path = folder / MANIFEST
    if not path.is_file():
        raise PermanentError(f"{folder} is not a built dataset: {MANIFEST} is missing")
    return DatasetManifest.model_validate_json(path.read_text())


def records(folder: Path) -> list[Record]:
    """Refuses a corpus whose digest is not the manifest's: a run must never measure data it cannot name."""
    expected = manifest(folder).corpus_sha256
    if sha256_file(folder / CORPUS) != expected:
        raise PermanentError(f"{folder / CORPUS} does not match its manifest digest {expected[:12]}")
    with (folder / CORPUS).open() as lines:
        return [Record.model_validate_json(line) for line in lines]


def questions(folder: Path) -> list[Question]:
    return [Question.model_validate(row) for row in json.loads((folder / QUESTIONS).read_text())]


def keys(folder: Path) -> dict[str, AnswerKey]:
    rows = [AnswerKey.model_validate(row) for row in json.loads((folder / KEY).read_text())]
    return {key.question_id: key for key in rows}
