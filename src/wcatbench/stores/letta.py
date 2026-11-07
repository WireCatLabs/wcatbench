"""Letta 0.16.8 archival passages (self-hosted server): a plain vector store, the baseline without extraction.

No language model reads a record: inserting a passage only embeds it (OpenAI text-embedding-3-small). `hosted` is
still True, because the text goes to the embedding provider.

What its API does that a reader would not guess, from Letta 0.16.8's source in November 2026:
- A passage is embedded inside the request, so a 200 means stored and searchable; there is nothing to wait for.
- An archive has no route that lists its passages, so which records it holds is kept in the build's folder.
- Only the organisation-level `/v1/passages/search` returns a passage's metadata, where the record key is.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import httpx

from wcatbench.core.errors import PermanentError, WcatbenchError
from wcatbench.core.http import JsonApi
from wcatbench.core.types import BatchReceipt, Hit, ItemState, Record

DEFAULT_URL = "http://127.0.0.1:18283"
EMBEDDING = "openai/text-embedding-3-small"
HELD = "letta-held.json"


class LettaStore:
    name = "letta"
    hosted = True

    def __init__(self, base_url: str | None = None, transport: httpx.BaseTransport | None = None) -> None:
        self.base = base_url or os.environ.get("WCATBENCH_LETTA_URL", DEFAULT_URL)
        self._transport = transport
        self._api: JsonApi | None = None
        self.archive = ""
        self.ledger = Path()
        self.keys: list[str] = []

    @property
    def api(self) -> JsonApi:
        if self._api is None:
            raise PermanentError("open() the store before using it")
        return self._api

    def version(self) -> str:
        return str(self.api.request("GET", "/v1/health/").get("version", "unknown"))

    def open(self, space: str, workdir: Path, started: datetime) -> None:
        self._api = JsonApi(self.base, "Bearer none", self._transport)
        found = [a for a in self.api.request("GET", f"/v1/archives/?name={space}") if a.get("name") == space]
        archive = (
            found[0] if found else self.api.request("POST", "/v1/archives/", {"name": space, "embedding": EMBEDDING})
        )
        self.archive = archive["id"]
        workdir.mkdir(parents=True, exist_ok=True)
        self.ledger = workdir / HELD
        self.keys = json.loads(self.ledger.read_text()) if self.ledger.exists() else []

    def ingest(self, batch: Sequence[Record]) -> BatchReceipt:
        started = time.perf_counter()
        passages = [
            {"text": r.text, "metadata": {"rid": r.key, "kind": r.kind}, "tags": [r.kind], "created_at": r.timestamp}
            for r in batch
        ]
        try:
            self.api.request("POST", f"/v1/archives/{self.archive}/passages/batch", {"passages": passages}, timeout=300)
        except WcatbenchError as error:
            reason = str(error)[:300]
            return BatchReceipt(sent=(), refused={r.key: reason for r in batch}, seconds=time.perf_counter() - started)
        self.keys.extend(r.key for r in batch)
        self.ledger.write_text(json.dumps(self.keys))
        return BatchReceipt(sent=tuple(r.key for r in batch), refused={}, seconds=time.perf_counter() - started)

    def held(self) -> dict[str, ItemState]:
        return dict.fromkeys(self.keys, ItemState.DONE)

    def settled(self, held: dict[str, ItemState]) -> bool:
        return True

    def search(self, query: str, k: int) -> list[Hit]:
        body = {"query": query, "archive_id": self.archive, "limit": k}
        reply = self.api.request("POST", "/v1/passages/search", body, timeout=120.0)
        hits = []
        for item in reply:
            passage = item.get("passage") or {}
            rid = (passage.get("metadata") or {}).get("rid")
            hits.append(Hit(keys=(rid,) if rid else (), score=item.get("score"), text=passage.get("text")))
        return hits

    def describe(self) -> dict[str, object]:
        return {"archive": self.archive, "passages_sent": len(self.keys), "embedding": EMBEDDING}

    def clear(self) -> None:
        raise PermanentError("wcatbench never deletes an archive; delete it in Letta itself")

    def close(self) -> None:
        if self._api is not None:
            self._api.close()
            self._api = None
