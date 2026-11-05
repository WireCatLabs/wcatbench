"""A local floor: SQLite FTS5 over the record text, BM25 ranking, no model. Free, so anyone can reproduce a result."""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Sequence
from pathlib import Path

from wcatbench.core.errors import PermanentError
from wcatbench.core.types import BatchReceipt, Hit, ItemState, Record

_WORD = re.compile(r"\w+", re.UNICODE)


class FtsStore:
    name = "fts"
    hosted = False

    def __init__(self) -> None:
        self._db: sqlite3.Connection | None = None

    @property
    def db(self) -> sqlite3.Connection:
        if self._db is None:
            raise PermanentError("open() the store before using it")
        return self._db

    def version(self) -> str:
        return f"sqlite {sqlite3.sqlite_version}"

    def open(self, space: str, workdir: Path) -> None:
        workdir.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(workdir / f"{space}.sqlite")
        self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS records USING fts5(id UNINDEXED, kind UNINDEXED, text)")

    def ingest(self, batch: Sequence[Record]) -> BatchReceipt:
        started = time.perf_counter()
        with self.db:
            self.db.executemany("DELETE FROM records WHERE id = ?", [(record.id,) for record in batch])
            self.db.executemany(
                "INSERT INTO records (id, kind, text) VALUES (?, ?, ?)",
                [(record.id, record.kind, record.text) for record in batch],
            )
        return BatchReceipt(sent=tuple(record.id for record in batch), seconds=time.perf_counter() - started)

    def held(self) -> dict[str, ItemState]:
        return {row[0]: ItemState.DONE for row in self.db.execute("SELECT id FROM records")}

    def settled(self, held: dict[str, ItemState]) -> bool:
        return True

    def search(self, query: str, k: int) -> list[Hit]:
        # A question typed as a sentence is turned into OR words: FTS5's default is AND, which finds nothing.
        words = _WORD.findall(query)
        if not words:
            return []
        match = " OR ".join(f'"{word}"' for word in words)
        rows = self.db.execute(
            "SELECT id, kind, text, bm25(records) FROM records WHERE records MATCH ? ORDER BY bm25(records) LIMIT ?",
            (match, k),
        )
        return [Hit(record_ids=(rid,), kind=kind, text=text, score=-rank) for rid, kind, text, rank in rows]

    def describe(self) -> dict[str, object]:
        return {"records": self.db.execute("SELECT count(*) FROM records").fetchone()[0]}

    def clear(self) -> None:
        with self.db:
            self.db.execute("DELETE FROM records")

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None
