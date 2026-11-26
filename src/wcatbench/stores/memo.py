"""WireCat memo (`@wirecat/cli-memo`), local: records become Markdown notes of a folder in a throwaway store, embedded
with a local model and found by `search all`. `memo import` documents get no vectors in 0.154.0, notes do.

Every run gets its own config, state and cache folders and `DBUS_SESSION_BUS_ADDRESS=disabled:`, so the owner's
store and keyring are never reached. Files are named by their first words, not by record id: an id in the file
name goes into the document's vector and adds noise (BUG-618).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess  # nosec B404
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from wcatbench.core.errors import PermanentError
from wcatbench.core.types import BatchReceipt, Hit, ItemState, Record

EMBEDDING_MODEL = "e5-small"
_UNSAFE = re.compile(r"[^\w\-]+", re.UNICODE)


def file_title(text: str, taken: set[str]) -> str:
    words = re.findall(r"\w+", text, re.UNICODE)[:6]
    base = _UNSAFE.sub("-", "-".join(words)).strip("-")[:60] or "note"
    title, n = base, 2
    while title in taken:
        title, n = f"{base}-{n}", n + 1
    taken.add(title)
    return title


class MemoStore:
    name = "memo"
    hosted = False

    def __init__(self, binary: str | None = None) -> None:
        self.binary = binary or shutil.which("memo") or "memo"
        self.root: Path | None = None
        self.names: dict[str, str] = {}

    def env(self) -> dict[str, str]:
        root = self.base
        home = root / "home"
        return {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_STATE_HOME": str(home / ".local/state"),
            "XDG_DATA_HOME": str(home / ".local/share"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "MEMO_CONFIG_DIR": str(root / "memo-config"),
            "MEMO_STATE_DIR": str(root / "memo-state"),
            "MEMO_CACHE_DIR": str(root / "memo-cache"),
            "WIRECAT_STATE_DIR": str(root / "wirecat-state"),
            "WIRECAT_CONFIG_DIR": str(root / "wirecat-config"),
            "MEMO_NO_UPDATE_CHECK": "1",
            "MEMO_TIMEOUT": "30m",
            "DBUS_SESSION_BUS_ADDRESS": "disabled:",
            "TZ": "UTC",
        }

    @property
    def base(self) -> Path:
        if self.root is None:
            raise PermanentError("open() the store before using it")
        return self.root

    def memo(self, *args: str) -> Any:
        done = subprocess.run(  # noqa: S603  # nosec B603
            [self.binary, *args, "--json"], env=self.env(), capture_output=True, text=True, check=False, timeout=1800
        )
        if done.returncode != 0:
            raise PermanentError(
                f"memo {args[0]} {args[1] if len(args) > 1 else ''} exited {done.returncode}: "
                f"{done.stderr.strip()[:300]}"
            )
        return json.loads(done.stdout)

    def version(self) -> str:
        done = subprocess.run([self.binary, "--version"], capture_output=True, text=True, check=False)  # noqa: S603  # nosec B603
        return done.stdout.strip()

    def open(self, space: str, workdir: Path, started: datetime) -> None:
        self.root = workdir / space
        (self.base / "data").mkdir(parents=True, exist_ok=True)
        names = self.base / "names.json"
        self.names = json.loads(names.read_text()) if names.exists() else {}

    def ingest(self, batch: Sequence[Record]) -> BatchReceipt:
        started = time.perf_counter()
        taken = set(self.names)
        for record in batch:
            # The first line is the date and author: a title made of it says nothing about the topic.
            body = record.text.split("\n", 1)[-1]
            title = next((t for t, key in self.names.items() if key == record.key), None) or file_title(body, taken)
            self.names[title] = record.key
            path = self.base / "data" / f"{title}.md"
            path.write_text(record.text + "\n")
            stamp = datetime.fromisoformat(record.timestamp).timestamp()
            os.utime(path, (stamp, stamp))
        (self.base / "names.json").write_text(json.dumps(self.names, ensure_ascii=False, indent=2))
        if not (self.base / "folder.json").exists():
            self.memo("models", "download", EMBEDDING_MODEL)
            self.memo("models", "set", EMBEDDING_MODEL)
            folder = self.memo("folders", "add", str(self.base / "data"), "--format", "markdown")
            (self.base / "folder.json").write_text(json.dumps(folder["item"], ensure_ascii=False))
        self.embed()
        return BatchReceipt(sent=tuple(record.key for record in batch), seconds=time.perf_counter() - started)

    def embed(self) -> None:
        """One sync embeds a bounded number of chunks and says what is left, so it runs until nothing is."""
        for _ in range(200):
            item = self.memo("sync")["item"]
            parts = [value for value in item.values() if isinstance(value, dict) and "left" in value]
            if not any(part["left"] for part in parts):
                return
        raise PermanentError("memo sync still had chunks to embed after 200 runs")

    def held(self) -> dict[str, ItemState]:
        return dict.fromkeys(self.names.values(), ItemState.DONE)

    def settled(self, held: dict[str, ItemState]) -> bool:
        return True

    def key_of(self, item: dict[str, Any]) -> str | None:
        for field in ("title", "path", "name", "ref"):
            value = str(item.get(field) or "")
            stem = Path(value).stem
            if stem in self.names:
                return self.names[stem]
        return None

    def search(self, query: str, k: int) -> list[Hit]:
        reply = self.memo("search", "all", query, "--limit", str(k))
        hits = []
        for item in reply.get("items", [])[:k]:
            key = self.key_of(item)
            note = self.base / "data" / f"{Path(str(item.get('title') or '')).stem}.md"
            # The whole note, as `memo read` gives it and as the other stores give a hit: the excerpt drops the
            # first line, which holds the date and author.
            text = note.read_text().strip() if key and note.exists() else str(item.get("excerpt") or "")
            hits.append(Hit(keys=(key,) if key else (), text=text, kind=item.get("kind")))
        return hits

    def describe(self) -> dict[str, object]:
        return {"documents": len(self.names), "embedding_model": EMBEDDING_MODEL}

    def clear(self) -> None:
        raise PermanentError("a memo build is a folder: start a new space instead of clearing one")

    def close(self) -> None:
        return None
