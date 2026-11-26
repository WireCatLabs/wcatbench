"""rules-trial: the design of Danil Pismenny's experiment 1 (ready-made rules) on our own synthetic data.

36 sources, 3 coding tasks, 13 known and 5 unknown checks per task. Each task comes in three phrasings: phrasing 0
is the one his design runs twice on one frozen retrieval, phrasings 1 and 2 are our extra independent retrievals.

Files written beside the four standard ones, none of them reachable by an agent except `project/`:
- `checks.json`: every hidden check with its rule, expected value and the patterns the staged scorer reads;
- `runner.py`: the hidden test runner, evaluated against the agent's workspace after the session;
- `project/`: the skeleton the agent starts from;
- `files/his.md` (the 8 active rules) and `files/history.md` (the same plus the texts they replaced).
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from wcatbench.core import dataset_files
from wcatbench.core.manifest import sha256_file
from wcatbench.core.types import AnswerKey, DatasetManifest, Privacy, Question, Record
from wcatbench.datasets.rules_trial import content

VERSION = 1
PHRASINGS = 3
SEED = 20261126

RUNNER = '''"""Hidden checks for one rules-trial task. Prints one JSON object: check id to its outcome."""

import datetime
import importlib
import json
import sys
from zoneinfo import ZoneInfo


def msk(hour, minute):
    return datetime.datetime(2026, 11, 3, hour, minute, tzinfo=ZoneInfo("Europe/Moscow"))


def utc(hour, minute):
    return datetime.datetime(2026, 11, 3, hour, minute, tzinfo=datetime.UTC)


def is_unknown(value):
    return type(value).__name__ == "_Unknown" or repr(value) == "UNKNOWN"


def same(got, expected):
    if isinstance(expected, bool):
        return got is expected
    if isinstance(got, bool):
        return False
    if isinstance(expected, list) and isinstance(got, (list, tuple)):
        return list(got) == expected
    if isinstance(expected, str):
        return got == expected
    return not isinstance(got, str) and got == expected


def run(workspace, module_name, checks):
    sys.path.insert(0, workspace)
    try:
        module = importlib.import_module(module_name)
    except BaseException as error:
        return {check["id"]: {"status": "broken", "got": f"import failed: {type(error).__name__}"} for check in checks}
    scope = {**vars(module), "datetime": datetime, "msk": msk, "utc": utc}
    results = {}
    for check in checks:
        try:
            got = eval(check["expr"], scope)
        except NameError as error:
            results[check["id"]] = {"status": "broken", "got": f"missing: {error}"}
            continue
        except BaseException as error:
            status = "unknown" if type(error).__name__ == "UnknownRule" else "broken"
            results[check["id"]] = {"status": status, "got": type(error).__name__}
            continue
        if is_unknown(got):
            results[check["id"]] = {"status": "unknown", "got": "UNKNOWN"}
        elif check["kind"] == "known" and same(got, check["expected"]):
            results[check["id"]] = {"status": "pass", "got": repr(got)[:200]}
        else:
            results[check["id"]] = {"status": "wrong", "got": repr(got)[:200]}
    return results


if __name__ == "__main__":
    workspace, module_name, checks_path = sys.argv[1:4]
    checks = json.loads(open(checks_path, encoding="utf-8").read())
    print(json.dumps(run(workspace, module_name, checks), ensure_ascii=False))
'''


def records(seed: int = SEED) -> list[Record]:
    """The seed only shuffles the order the sources reach a store in: every text is written by hand.

    The date and author open each text, so every store gets them the same way: Mem0 OSS takes no timestamp
    ("Platform-only temporal parameter" in 2.2.1), and a store that reads only text still sees which text is newer.
    """
    rows = [
        Record(
            id=sid,
            kind=kind,
            timestamp=stamp,
            text=f"{stamp[:10]} · {author}\n{text}",
            source=project,
            author=author,
            metadata={"project": project},
        )
        for sid, project, kind, author, stamp, text in content.SOURCES
    ]
    random.Random(seed).shuffle(rows)  # noqa: S311  # nosec B311
    return rows


def task_text(task: dict[str, Any], phrasing: int) -> str:
    """The first paragraph is the retrieval query. The rest is the spec and the rules the hidden checks follow."""
    return f"{task['intro'][phrasing]}\n\n{task['spec']}\n{content.COMMON_RULES}"


def checks() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in content.TASKS:
        for check_id, rule_id, expr, expected in task["known"]:
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
                    "replaces": rule["replaces"],
                    "value": rule["value"],
                    "old": rule["old"],
                }
            )
        for check_id, name, trap in task["unknown"]:
            rows.append(
                {
                    "id": check_id,
                    "task": task["id"],
                    "module": task["module"],
                    "kind": "unknown",
                    "expr": name,
                    "expected": content.UNKNOWN_SENTINEL,
                    "trap": trap,
                }
            )
    return rows


def rule_files() -> dict[str, str]:
    by_id = {sid: (project, stamp, text) for sid, project, _, _, stamp, text in content.SOURCES}
    active = [content.RULES[rule]["source"] for rule in sorted(content.RULES)]
    replaced = [old for rule in content.RULES.values() for old in rule["replaces"]]

    def render(ids: list[str]) -> str:
        ordered = sorted(ids, key=lambda sid: by_id[sid][1])
        return "".join(f"## {by_id[sid][1][:10]}\n\n{by_id[sid][2]}\n\n" for sid in ordered)

    return {
        "his.md": "# Правила проекта «Сокол»\n\n" + render(active),
        "history.md": "# Правила проекта «Сокол» с историей\n\n" + render(active + replaced),
    }


class RulesTrialDataset:
    name = "rules-trial"

    def build(self, out: Path, params: dict[str, int]) -> DatasetManifest:
        seed = params.get("seed", SEED)
        corpus = records(seed)
        questions = [
            Question(id=f"{task['id']}.p{phrasing}", text=task_text(task, phrasing), category="rules-trial")
            for task in content.TASKS
            for phrasing in range(PHRASINGS)
        ]
        rows = checks()
        keys = [
            AnswerKey(
                question_id=question.id,
                answers=tuple(row["id"] for row in rows if row["task"] == question.id.split(".")[0]),
                sources=tuple(
                    sorted(
                        {
                            row["source"]
                            for row in rows
                            if row["task"] == question.id.split(".")[0] and row["kind"] == "known"
                        }
                    )
                ),
            )
            for question in questions
        ]
        corpus_sha, key_sha = dataset_files.write(out, corpus, questions, keys)
        dataset_files.write_json(out / "checks.json", rows)
        (out / "runner.py").write_text(RUNNER)
        for relative, text in content.PROJECT_FILES.items():
            (out / "project" / relative).parent.mkdir(parents=True, exist_ok=True)
            (out / "project" / relative).write_text(text)
        (out / "files").mkdir(exist_ok=True)
        for name, text in rule_files().items():
            (out / "files" / name).write_text(text)
        tasks = {task["id"]: {"module": task["module"], "path": task["path"]} for task in content.TASKS}
        dataset_files.write_json(out / "tasks.json", tasks)
        manifest = DatasetManifest(
            name=self.name,
            version=VERSION,
            privacy=Privacy.SYNTHETIC,
            params={"seed": seed, "phrasings": PHRASINGS},
            records=len(corpus),
            questions=len(questions),
            corpus_sha256=corpus_sha,
            key_sha256=key_sha,
            extra={
                "language": "ru",
                "target_project": content.TARGET,
                "rules": len(content.RULES),
                "known_checks": sum(row["kind"] == "known" for row in rows),
                "unknown_checks": sum(row["kind"] == "unknown" for row in rows),
                "checks_sha256": sha256_file(out / "checks.json"),
            },
        )
        dataset_files.write_json(out / dataset_files.MANIFEST, manifest.model_dump(mode="json"))
        return manifest
