"""Load one dataset into one store, in batches, then wait until the store is ready to answer.

A build folder holds `build.json` (what was loaded where), `ledger.jsonl` (one line per batch) and `status-<time>.json`
(what the store said it held). A stopped build resumes from what the store holds, not from our ledger: a hosted service
may still be processing a batch the ledger already counts, and sending it again is paid twice.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from wcatbench.core import dataset_files
from wcatbench.core.errors import PermanentError, PrivacyError
from wcatbench.core.ledger import Ledger
from wcatbench.core.manifest import sha256_text
from wcatbench.core.protocols import Store
from wcatbench.core.types import DatasetManifest, ItemState, Privacy, Record

BUILD, LEDGER = "build.json", "ledger.jsonl"
FINAL = (ItemState.DONE, ItemState.FAILED)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Selection:
    """The records a build loads: the whole corpus, or a named subset file of the dataset (`subset-<name>.json`)."""

    records: list[Record]
    subset: str | None = None
    sha256: str | None = None

    @classmethod
    def load(cls, dataset: Path, subset: str | None = None) -> Selection:
        records = dataset_files.records(dataset)
        if subset is None:
            return cls(records)
        path = dataset / f"subset-{subset}.json"
        if not path.is_file():
            raise PermanentError(f"{dataset} has no subset named {subset!r}")
        wanted = json.loads(path.read_text())
        ids = set(wanted["ids"])
        chosen = [record for record in records if record.id in ids]
        if len(chosen) != wanted["records"] or sha256_text(dataset_files.corpus_lines(chosen)) != wanted["sha256"]:
            raise PermanentError(f"subset {subset!r} does not match the corpus of {dataset}")
        return cls(chosen, subset, wanted["sha256"])


@dataclass
class Build:
    store: Store
    dataset: Path
    space: str
    folder: Path
    selection: Selection
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    ledger: Ledger = field(init=False)
    manifest: DatasetManifest = field(init=False)

    def __post_init__(self) -> None:
        self.manifest = dataset_files.manifest(self.dataset)
        if self.store.hosted and self.manifest.privacy is Privacy.PRIVATE:
            raise PrivacyError(f"{self.store.name} is hosted and {self.manifest.name} is private")
        self.ledger = Ledger(self.folder / LEDGER)

    def open(self, *, resume: bool, started: datetime | None = None) -> dict[str, Any]:
        """Start a new build, or reopen one. Refuses to mix two datasets, subsets or stores in one folder."""
        path = self.folder / BUILD
        expected = {
            "store": self.store.name,
            "space": self.space,
            "dataset": self.manifest.name,
            "corpus_sha256": self.manifest.corpus_sha256,
            "subset": self.selection.subset,
            "subset_sha256": self.selection.sha256,
            "records": len(self.selection.records),
        }
        if path.exists():
            if not resume:
                raise PermanentError(f"{self.folder} already holds a build; pass --resume to continue it")
            info: dict[str, Any] = json.loads(path.read_text())
            differs = {key for key, value in expected.items() if info.get(key) != value}
            if differs:
                raise PermanentError(f"{self.folder} holds another build: {', '.join(sorted(differs))} differ")
        else:
            self.folder.mkdir(parents=True, exist_ok=True)
            info = {**expected, "started": (started or datetime.now(UTC)).isoformat(timespec="seconds")}
            path.write_text(json.dumps(info, indent=2) + "\n")
        self.store.open(self.space, self.folder / "store", datetime.fromisoformat(info["started"]))
        return info

    def check(self) -> tuple[dict[str, ItemState], dict[str, Any]]:
        held = self.store.held()
        keys = [record.key for record in self.selection.records]
        entries = [entry for entry in self.ledger.entries() if entry["unit"] == "batch"]
        return held, {
            "store": self.store.name,
            "space": self.space,
            "checked_at": now(),
            "expected": len(keys),
            "by_status": dict(Counter(str(held[key]) if key in held else "absent" for key in keys)),
            "outside_selection": len(set(held) - set(keys)),
            "accepted_not_listed": len((set(keys) - set(held)) & self.sent_before()),
            "ledger": {
                "batches": len(entries),
                "sent": sum(entry["sent"] for entry in entries),
                "refused": sum(len(entry["refused"]) for entry in entries),
            },
            "store_counts": self.store.describe(),
        }

    def import_ledger(self, path: Path) -> int:
        """Adopt the ledger of a build made by the earlier cli-testing scripts, so resume knows what they sent."""
        self._refuse_if_ledger()
        if not path.is_file():
            raise PermanentError(f"no ledger at {path}")
        count = 0
        for line in path.read_text().splitlines():
            entry = json.loads(line)
            if "batch" not in entry:
                continue
            refused = {row["rid"]: row["error"] for row in entry["failed"]}
            self.ledger.write(
                "batch",
                keys=entry["rids"],
                sent=entry["sent"] - len(refused),
                refused=refused,
                s=entry["s"],
                imported_from=str(path),
            )
            count += 1
        return count

    def adopt_all_sent(self) -> None:
        """For a build made elsewhere without a ledger, whose operator knows every record was accepted."""
        self._refuse_if_ledger()
        keys = [record.key for record in self.selection.records]
        self.ledger.write("batch", keys=keys, sent=len(keys), refused={}, s=0, adopted="operator: every record sent")

    def _refuse_if_ledger(self) -> None:
        if any(True for _ in self.ledger.entries()):
            raise PermanentError(f"{self.ledger.path} is not empty; adopt only into a new build folder")

    def sent_before(self) -> set[str]:
        return {
            key
            for entry in self.ledger.entries()
            if entry["unit"] == "batch"
            for key in entry["keys"]
            if key not in entry["refused"]
        }

    def to_resend(self, held: dict[str, ItemState], records: Sequence[Record]) -> list[Record]:
        """Failed records, and absent ones the ledger never saw accepted. A record the service accepted and no longer
        lists is reported, not sent: a listing can miss a record, and a paid service would charge for it twice."""
        accepted = self.sent_before()
        unlisted = [record.key for record in records if record.key not in held and record.key in accepted]
        if unlisted:
            logger.warning("{} accepted records are not listed by the store; not sending them again", len(unlisted))
        return [
            record
            for record in records
            if held.get(record.key) is ItemState.FAILED or (record.key not in held and record.key not in accepted)
        ]

    def write_status(self, status: dict[str, Any]) -> Path:
        path = self.folder / f"status-{datetime.now(UTC):%Y%m%dT%H%M%S%f}.json"
        path.write_text(json.dumps(status, indent=2) + "\n")
        return path

    def send(self, todo: Sequence[Record], batch_size: int) -> None:
        for start in range(0, len(todo), batch_size):
            batch = todo[start : start + batch_size]
            receipt = self.store.ingest(batch)
            self.ledger.write(
                "batch",
                keys=[record.key for record in batch],
                sent=len(receipt.sent),
                refused=receipt.refused,
                s=round(receipt.seconds, 1),
            )
            logger.info("batch {} sent {}, refused {}", start // batch_size, len(receipt.sent), len(receipt.refused))

    def wait(self, wait_seconds: float, poll_seconds: float) -> dict[str, Any]:
        deadline = self.clock() + wait_seconds
        keys = [record.key for record in self.selection.records]
        while True:
            held, status = self.check()
            ready = all(held.get(key) in FINAL for key in keys) and self.store.settled(held)
            status["settled"] = ready
            if ready:
                return status
            if self.clock() >= deadline:
                status["deadline_reached"] = True
                return status
            logger.info("waiting: {}", status["by_status"])
            self.sleep(poll_seconds)

    def run(
        self, *, resume: bool, batch_size: int = 100, wait_seconds: float = 1800, poll_seconds: float = 300
    ) -> dict[str, Any]:
        info = self.open(resume=resume)
        todo = self.selection.records
        if resume:
            held, status = self.check()
            self.write_status(status)
            todo = self.to_resend(held, todo)
        logger.info("sending {} of {} records", len(todo), len(self.selection.records))
        self.send(todo, batch_size)
        status = self.wait(wait_seconds, poll_seconds)
        self.write_status(status)
        summary = {
            **info,
            "store_version": self.store.version(),
            "sent_this_run": len(todo),
            "finished": now(),
            **status,
        }
        (self.folder / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n")
        return summary
