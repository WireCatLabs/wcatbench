"""Experiment 3 of the rules-trial round: the corrections gate, store by store, with no agent.

Each store gets the eleven rules three times, one version at a time, through its own update path:
- a store of documents (files, memo, OpenViking, Hindsight) gets the new version under the same key, as an edit of
  the same note or document;
- a store of statements (Mem0, AgentMemory) gets each version as a new statement, and its own logic decides whether
  an older one is updated, deleted or kept.
Then four checks per rule (datasets.rules_trial.corrections). The gate passes only at 44 of 44.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wcatbench.core import registry
from wcatbench.core.types import Record
from wcatbench.datasets.rules_trial import corrections

STORES = ("fts", "memo", "agentmemory", "mem0-oss", "hindsight-slim", "openviking", "openviking-evo")
STATEMENT_STORES = ("mem0-oss", "agentmemory")
K = 5


def versions(store: str, n: int) -> list[Record]:
    rows = []
    for rule, spec in corrections.RULES.items():
        date, author, text, _ = spec["versions"][n]
        key = f"{rule}-v{n + 1}" if store in STATEMENT_STORES else rule
        rows.append(
            Record(
                id=f"{rule}.v{n + 1}",
                kind="decision",
                timestamp=f"{date}T10:00:00+03:00",
                text=f"{date} · {author}\n{text}",
                name=key,
            )
        )
    return rows


def found(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


@dataclass
class Gate:
    builds: Path
    run: Path

    def build(self, name: str) -> Any:
        store = registry.load("stores", name)()
        if hasattr(store, "dated_names"):
            store.dated_names = False
        workdir = self.builds / name
        store.open("corrections", workdir, datetime.now(UTC))
        done = workdir / "corrections" / "revisions.json"
        applied: list[int] = json.loads(done.read_text()) if done.exists() else []
        for n in range(3):
            if n in applied:
                continue
            receipt = store.ingest(versions(name, n))
            for _ in range(360):
                if store.settled(store.held()):
                    break
                time.sleep(10)
            applied.append(n)
            done.parent.mkdir(parents=True, exist_ok=True)
            done.write_text(json.dumps(applied))
            with (workdir / "corrections" / "ledger.jsonl").open("a") as lines:
                lines.write(
                    json.dumps({"revision": n + 1, "sent": len(receipt.sent), "refused": receipt.refused}) + "\n"
                )
        return store

    def check(self, name: str) -> dict[str, Any]:
        out = self.run / "e3" / name
        out.mkdir(parents=True, exist_ok=True)
        if (out / "result.json").exists():
            return dict(json.loads((out / "result.json").read_text()))
        store = self.build(name)
        try:
            contents = getattr(store, "contents", None)
            stored = "\n\n".join(contents()) if contents else ""
            hits = {rule: store.search(spec["question"], K) for rule, spec in corrections.RULES.items()}
        finally:
            store.close()
        (out / "stored.txt").write_text(stored)
        rows: list[dict[str, Any]] = []
        for rule, spec in corrections.RULES.items():
            current = spec["versions"][-1][3]
            older = [version[3] for version in spec["versions"][:-1]]
            context = "\n\n".join(hit.text or "" for hit in hits[rule])
            results = {
                "stored_current": found(current, stored),
                "stored_old_gone": not any(found(pattern, stored) for pattern in older),
                "retrieved_current": found(current, context),
                "retrieved_old_absent": not any(found(pattern, context) for pattern in older),
            }
            rows += [
                {"store": name, "rule": rule, "check": check, "pass": results[check]} for check in corrections.CHECKS
            ]
        (out / "hits.json").write_text(
            json.dumps(
                {rule: [hit.text for hit in found_hits] for rule, found_hits in hits.items()},
                ensure_ascii=False,
                indent=2,
            )
        )
        result = {
            "store": name,
            "passed": sum(bool(row["pass"]) for row in rows),
            "total": len(rows),
            "gate": all(bool(row["pass"]) for row in rows),
            "by_check": {
                check: sum(row["pass"] for row in rows if row["check"] == check) for check in corrections.CHECKS
            },
            "rows": rows,
            "finished": datetime.now(UTC).isoformat(),
        }
        (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    def summary(self) -> str:
        lines = [
            "| Store | Gate (44/44) | Passed | Stored current | Old gone from store | Retrieved current | "
            "Old absent from top 5 |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for name in STORES:
            path = self.run / "e3" / name / "result.json"
            if not path.exists():
                continue
            result = json.loads(path.read_text())
            by = result["by_check"]
            lines.append(
                f"| {name} | {'pass' if result['gate'] else 'fail'} | {result['passed']}/{result['total']} | "
                f"{by['stored_current']}/11 | {by['stored_old_gone']}/11 | {by['retrieved_current']}/11 | "
                f"{by['retrieved_old_absent']}/11 |"
            )
        return "\n".join(lines) + "\n"
