"""Cognee 1.6.7 (self-hosted server): records become a knowledge graph built by a language model. One build is one
dataset. `hosted` is True: cognify sends every record to the language model provider.

Search reads the graph the way Cognee's own retrieval does (GRAPH_COMPLETION with only the context, so no answer
model runs); WCATBENCH_COGNEE_SEARCH=chunks asks plain vector search over the records instead.

What its API does that a reader would not guess, each seen with Cognee 1.6.7 in November 2026:
- `add` only stores; `cognify` builds the graph afterwards, so settling starts it and waits for every item.
- The same text twice in one dataset is one item (a content hash), so the record's date and kind open its text.
- A graph hit names graph nodes, not items; its record is found by the text of the document chunks it used.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from wcatbench.core.errors import PermanentError, WcatbenchError
from wcatbench.core.http import JsonApi
from wcatbench.core.types import BatchReceipt, Hit, ItemState, Record

DEFAULT_URL = "http://127.0.0.1:18100"
LEDGER = "cognee-ledger.json"


def opening(record: Record) -> str:
    return f"[{record.timestamp[:16].replace('T', ' ')} {record.kind}] {record.text}"


class CogneeStore:
    name = "cognee"
    hosted = True

    def __init__(self, base_url: str | None = None, transport: httpx.BaseTransport | None = None) -> None:
        self.base = base_url or os.environ.get("WCATBENCH_COGNEE_URL", DEFAULT_URL)
        self.mode = os.environ.get("WCATBENCH_COGNEE_SEARCH", "graph")
        self._transport = transport
        self._api: JsonApi | None = None
        self.dataset = ""
        self.dataset_id = ""
        self.ledger = Path()
        self.by_text: dict[str, list[str]] = {}

    @property
    def api(self) -> JsonApi:
        if self._api is None:
            raise PermanentError("open() the store before using it")
        return self._api

    def version(self) -> str:
        return str(self.api.request("GET", "/health").get("version", "unknown"))

    def open(self, space: str, workdir: Path, started: datetime) -> None:
        self._api = JsonApi(self.base, "Bearer none", self._transport)
        self.dataset = space
        workdir.mkdir(parents=True, exist_ok=True)
        self.ledger = workdir / LEDGER
        if self.ledger.exists():
            self.by_text = json.loads(self.ledger.read_text())
        self.dataset_id = next((d["id"] for d in self.api.request("GET", "/api/v1/datasets") if d["name"] == space), "")

    def ingest(self, batch: Sequence[Record]) -> BatchReceipt:
        started = time.perf_counter()
        form: list[tuple[str, str]] = [("datasetName", self.dataset)]
        form += [("raw_data", opening(record)) for record in batch]
        form += [
            ("labels", json.dumps([r.key for r in batch])),
            ("external_metadata", json.dumps([{"rid": r.key, "kind": r.kind} for r in batch])),
        ]
        try:
            reply = self.api.request_form("POST", "/api/v1/add", form, timeout=600.0)
        except WcatbenchError as error:
            reason = str(error)[:300]
            return BatchReceipt(sent=(), refused={r.key: reason for r in batch}, seconds=time.perf_counter() - started)
        self.dataset_id = reply.get("dataset_id") or self.dataset_id
        for record in batch:
            keys = self.by_text.setdefault(opening(record), [])
            if record.key not in keys:
                keys.append(record.key)
        self.ledger.write_text(json.dumps(self.by_text))
        return BatchReceipt(sent=tuple(r.key for r in batch), refused={}, seconds=time.perf_counter() - started)

    def held(self) -> dict[str, ItemState]:
        return {key: ItemState.DONE for keys in self.by_text.values() for key in keys}

    def progress(self) -> dict[str, Any]:
        return dict(
            self.api.request("GET", f"/api/v1/datasets/{self.dataset_id}/processing-status?pipeline=cognify_pipeline")
        )

    def running(self) -> bool:
        reply = self.api.request("GET", f"/api/v1/datasets/status?dataset={self.dataset_id}")
        state = str(reply.get(self.dataset_id, "")).upper()
        return "STARTED" in state or "INITIATED" in state

    def settled(self, held: dict[str, ItemState]) -> bool:
        if not self.dataset_id:
            return False
        progress = self.progress()
        # Right after `add`, processing-status may count nothing yet; settled means every record went through cognify.
        if not progress.get("pending") and progress.get("completed", 0) >= len(held) > 0:
            return True
        if not self.running():
            self.api.request("POST", "/api/v1/cognify", {"datasetIds": [self.dataset_id], "runInBackground": True})
        return False

    def search(self, query: str, k: int) -> list[Hit]:
        if self.mode == "chunks":
            body = {"searchType": "CHUNKS", "datasetIds": [self.dataset_id], "query": query, "topK": k}
            reply = self.api.request("POST", "/api/v1/search", body, timeout=120.0)
            return [self.chunk_hit(item.get("text", ""), item.get("score")) for item in reply[:k]]
        body = {
            "searchType": "GRAPH_COMPLETION",
            "datasetIds": [self.dataset_id],
            "query": query,
            "topK": k,
            "onlyContext": True,
            "verbose": True,
        }
        reply = self.api.request("POST", "/api/v1/search", body, timeout=300.0)
        texts: list[str] = []
        for result in reply:
            for triplet in result.get("objects_result") or []:
                for side in ("node1", "node2"):
                    node = (triplet.get(side) or {}).get("node_attributes") or {}
                    if node.get("type") == "DocumentChunk" and node.get("text") and node["text"] not in texts:
                        texts.append(node["text"])
        return [self.chunk_hit(text, None) for text in texts[:k]]

    def chunk_hit(self, text: str, score: float | None) -> Hit:
        return Hit(keys=tuple(self.by_text.get(text, [])), score=score, text=text, kind="chunk")

    def describe(self) -> dict[str, object]:
        progress = self.progress() if self.dataset_id else {}
        return {
            "dataset_id": self.dataset_id,
            "search": self.mode,
            **{key: progress.get(key) for key in ("total", "completed", "pending")},
        }

    def clear(self) -> None:
        raise PermanentError("wcatbench never deletes a dataset; delete it in Cognee itself")

    def close(self) -> None:
        if self._api is not None:
            self._api.close()
            self._api = None
