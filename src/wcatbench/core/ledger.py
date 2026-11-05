"""An append-only JSONL file, one short line per finished unit (a batch, a trial). Resume skips what it names.

Each line is written and closed at once, so a killed process leaves every finished unit on disk. Lines hold names and
counts, never full service replies, so the file stays small at 10,000 records.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class Ledger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, unit: str, **entry: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "unit": unit, **entry}
        with self.path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(line, ensure_ascii=False) + "\n")

    def entries(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as lines:
            for line in lines:
                # A process killed mid-write leaves at most one torn last line; it is not a finished unit.
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def done(self) -> set[str]:
        return {entry["unit"] for entry in self.entries()}
