"""full-use: memo as it is built against its rivals, on one synthetic company in every kind memo imports.

Three coding tasks with hidden checks (10 known and 3 UNKNOWN each) and 15 questions written as a user asks them,
plus 4 second wordings. The same rule sources at three archive sizes; only the background noise grows.

Files beside the four standard ones, none reachable by an agent except `project/` and copies of `sources/`:
- `checks.json`, `runner.py`: the hidden checks and their runner;
- `qkeys.json`: the question keys;
- `files/current.md`: the active rules of «Пеликан» as one file, for the answer-key gate;
- `sources/memo/` and `sources/files/`: the archive in memo's import formats and as a user keeps it.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from wcatbench.core import dataset_files
from wcatbench.core.manifest import sha256_file
from wcatbench.core.types import AnswerKey, DatasetManifest, Privacy, Question, Record
from wcatbench.datasets.company_round import content, export, keys, noise
from wcatbench.datasets.rules_trial import RUNNER

VERSION = 1
SEED = 20261128
SIZES = {"1x": 150, "10x": 1500, "100x": 15000}

QUESTION_NOTE = (
    "Ответь в файле `ANSWER.md`: сам ответ, а под ним откуда он (чат, письмо, встреча, заметка или документ, дата "
    "ГГГГ-ММ-ДД, кто). Если в памяти ответа нет, так и напиши: «нет данных». Код не пиши."
)


def all_sources(size: str, seed: int = SEED) -> list[dict[str, Any]]:
    return content.SOURCES + noise.sources(SIZES[size], seed)


def records(sources: list[dict[str, Any]], seed: int) -> list[Record]:
    """One record per source. The date and place open each text, as in rules-trial, for stores that read text only."""
    rows = [
        Record(
            id=source["id"],
            kind=source["kind"],
            timestamp=source.get("at") or source["messages"][0][-3 if source["kind"] == "mail" else 1],
            text=export.text_of(source),
            source=source["project"],
            metadata={"project": source["project"], "kind": source["kind"]},
        )
        for source in sources
    ]
    random.Random(seed).shuffle(rows)  # noqa: S311  # nosec B311
    return rows


def task_text(task: dict[str, Any]) -> str:
    return f"{task['intro']}\n\n{task['spec']}\n{content.COMMON_RULES}"


def source_date(sid: str) -> str:
    source = next(s for s in content.SOURCES if s["id"] == sid)
    return str(source.get("at") or source["messages"][0][-3 if source["kind"] == "mail" else 1])[:10]


def checks() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in content.TASKS:
        for check_id, rule_id, expr, expected, stale, lookalike in task["known"]:
            rule = content.RULES[rule_id]
            rows.append(
                {
                    "id": check_id,
                    "task": task["id"],
                    "module": task["module"],
                    "kind": "known",
                    "expr": expr,
                    "expected": expected,
                    "rule": rule_id,
                    "source": rule["source"],
                    "source_date": source_date(rule["source"]),
                    "replaces": rule["replaces"],
                    "value": rule["value"],
                    "old": rule["old"],
                    "stale": None if stale is None else repr(stale),
                    "lookalike": None if lookalike is None else repr(lookalike),
                }
            )
        for check_id, name, trap, trap_value in task["unknown"]:
            rows.append(
                {
                    "id": check_id,
                    "task": task["id"],
                    "module": task["module"],
                    "kind": "unknown",
                    "expr": name,
                    "expected": content.UNKNOWN_SENTINEL,
                    "trap": trap,
                    "trap_value": None if trap_value is None else repr(trap_value),
                }
            )
    return rows


def current_rules() -> str:
    by_id = {source["id"]: source for source in content.SOURCES}
    active = sorted({rule["source"] for rule in content.RULES.values()})
    return "# Действующие решения проекта «Пеликан»\n\n" + "\n\n".join(export.text_of(by_id[s]) for s in active) + "\n"


def question_texts(folder: Path) -> dict[str, str]:
    """Written by the question agents (keys.py says how); absent until they ran."""
    path = Path(__file__).with_name("questions.json")
    if not path.exists():
        return {}
    import json

    return dict(json.loads(path.read_text()))


class CompanyRoundDataset:
    name = "full-use"
    size = "1x"
    seed = SEED

    def build(self, out: Path, params: dict[str, int]) -> DatasetManifest:
        seed = params.get("seed", self.seed)
        sources = all_sources(self.size, seed)
        corpus = records(sources, seed)
        asked = question_texts(out)
        questions = [Question(id=task["id"], text=task_text(task), category="coding") for task in content.TASKS]
        questions += [
            Question(id=qid, text=f"{text}\n\n{QUESTION_NOTE}", category="variant" if qid.endswith("v") else "question")
            for qid, text in sorted(asked.items())
        ]
        rows = checks()
        answer_keys = [
            AnswerKey(
                question_id=task["id"],
                answers=tuple(row["id"] for row in rows if row["task"] == task["id"]),
                sources=tuple(sorted({row["source"] for row in rows if row["task"] == task["id"] and "source" in row})),
            )
            for task in content.TASKS
        ]
        corpus_sha, key_sha = dataset_files.write(out, corpus, questions, answer_keys)
        dataset_files.write_json(out / "checks.json", rows)
        qkeys = {qid: keys.KEYS[keys.VARIANTS.get(qid, qid)] | {"base": keys.VARIANTS.get(qid, qid)} for qid in asked}
        dataset_files.write_json(out / "qkeys.json", qkeys)
        (out / "runner.py").write_text(RUNNER)
        for relative, text in content.PROJECT_FILES.items():
            (out / "project" / relative).parent.mkdir(parents=True, exist_ok=True)
            (out / "project" / relative).write_text(text)
        (out / "files").mkdir(exist_ok=True)
        (out / "files" / "current.md").write_text(current_rules())
        counts = export.write(out / "sources", sources)
        tasks = {task["id"]: {"module": task["module"], "path": task["path"]} for task in content.TASKS}
        dataset_files.write_json(out / "tasks.json", tasks)
        manifest = DatasetManifest(
            name=f"{self.name}-{self.size}",
            version=VERSION,
            privacy=Privacy.SYNTHETIC,
            params={"seed": seed, "noise": SIZES[self.size]},
            records=len(corpus),
            questions=len(questions),
            corpus_sha256=corpus_sha,
            key_sha256=key_sha,
            extra={
                "language": "ru",
                "target_project": content.PEL,
                "size": self.size,
                "kinds": counts,
                "rules": len(content.RULES),
                "known_checks": sum(row["kind"] == "known" for row in rows),
                "unknown_checks": sum(row["kind"] == "unknown" for row in rows),
                "lookalike_checks": sum(bool(row.get("lookalike")) for row in rows),
                "stale_checks": sum(bool(row.get("stale")) for row in rows),
                "checks_sha256": sha256_file(out / "checks.json"),
            },
        )
        dataset_files.write_json(out / dataset_files.MANIFEST, manifest.model_dump(mode="json"))
        return manifest


class CompanyRound10x(CompanyRoundDataset):
    size = "10x"


class CompanyRound100x(CompanyRoundDataset):
    size = "100x"
