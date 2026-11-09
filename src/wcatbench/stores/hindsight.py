"""Hindsight (self-hosted server, its own language model for fact extraction). One build is one memory bank.

The server runs on this machine, but `hosted` is True: retain sends every record to the server's language model
provider, so a private dataset must not reach it.

What its API does that a reader would not guess, each seen with Hindsight 1.2.0 in November 2026:
- An async retain returns at once. A document is listed only once its facts are extracted.
- Consolidation into observations runs after retain, also with the language model. Until it ends, a recall sees
  facts but not the observations built from them, so the bank is settled only when both queues are empty.
- An observation has no document id of its own; the documents behind it are those of its source facts.
"""

from __future__ import annotations

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

DEFAULT_URL = "http://127.0.0.1:18888"


class HindsightStore:
    name = "hindsight"
    hosted = True

    def __init__(self, base_url: str | None = None, transport: httpx.BaseTransport | None = None) -> None:
        self.base = base_url or os.environ.get("WCATBENCH_HINDSIGHT_URL", DEFAULT_URL)
        self._transport = transport
        self._api: JsonApi | None = None
        self.bank = ""

    @property
    def api(self) -> JsonApi:
        if self._api is None:
            raise PermanentError("open() the store before using it")
        return self._api

    def path(self, tail: str) -> str:
        return f"/v1/default/banks/{self.bank}{tail}"

    def version(self) -> str:
        return str(self.api.request("GET", "/version").get("api_version", "unknown"))

    def open(self, space: str, workdir: Path, started: datetime) -> None:
        # A local server takes no key; the header only satisfies JsonApi.
        self._api = JsonApi(self.base, "Bearer none", self._transport)
        self.bank = space
        self.api.request("PUT", self.path(""), {})

    def ingest(self, batch: Sequence[Record]) -> BatchReceipt:
        started = time.perf_counter()
        items = [
            {
                "content": record.text,
                "timestamp": record.timestamp,
                "context": record.kind,
                "document_id": record.key,
                "metadata": {"rid": record.key},
            }
            for record in batch
        ]
        try:
            self.api.request("POST", self.path("/memories"), {"items": items, "async": True}, timeout=300.0)
        except WcatbenchError as error:
            reason = str(error)[:300]
            return BatchReceipt(sent=(), refused={r.key: reason for r in batch}, seconds=time.perf_counter() - started)
        return BatchReceipt(sent=tuple(r.key for r in batch), refused={}, seconds=time.perf_counter() - started)

    def held(self) -> dict[str, ItemState]:
        states: dict[str, ItemState] = {}
        offset = 0
        while True:
            reply = self.api.request("GET", self.path(f"/documents?limit=100&offset={offset}"))
            items = reply.get("items", [])
            for item in items:
                states[item["id"]] = ItemState.DONE
            offset += len(items)
            if not items or offset >= reply.get("total", 0):
                break
        offset = 0
        while True:
            reply = self.api.request("GET", self.path(f"/operations?status=failed&limit=100&offset={offset}"))
            operations = reply.get("operations", [])
            for operation in operations:
                key = operation.get("document_id")
                if key and key not in states:
                    states[key] = ItemState.FAILED
            offset += len(operations)
            if not operations or offset >= reply.get("total", 0):
                return states

    def settled(self, held: dict[str, ItemState]) -> bool:
        stats = self.api.request("GET", self.path("/stats"))
        return not stats.get("pending_operations") and not stats.get("pending_consolidation")

    def search(self, query: str, k: int) -> list[Hit]:
        reply = self.api.request(
            "POST", self.path("/memories/recall"), {"query": query, "include": {"source_facts": {}}}, timeout=120.0
        )
        sources: dict[str, Any] = reply.get("source_facts") or {}
        hits = []
        for item in reply.get("results", [])[:k]:
            if item.get("document_id"):
                keys: tuple[str, ...] = (item["document_id"],)
            else:
                found = (sources.get(fact, {}).get("document_id") for fact in item.get("source_fact_ids") or ())
                keys = tuple(dict.fromkeys(key for key in found if key))
            hits.append(Hit(keys=keys, text=item.get("text"), kind=item.get("type") or "memory"))
        return hits

    def describe(self) -> dict[str, object]:
        stats = self.api.request("GET", self.path("/stats"))
        llm = self.api.request("GET", self.path("/llm-requests/stats?period=30d"))
        return {
            "documents": stats.get("total_documents"),
            "facts_by_type": stats.get("nodes_by_fact_type"),
            "observations": stats.get("total_observations"),
            "pending_operations": stats.get("pending_operations"),
            "pending_consolidation": stats.get("pending_consolidation"),
            "failed_operations": stats.get("failed_operations"),
            "llm_requests": sum(bucket.get("total", 0) for bucket in llm.get("buckets", [])),
            "llm_tokens": [bucket.get("tokens") for bucket in llm.get("buckets", []) if bucket.get("tokens")],
        }

    def clear(self) -> None:
        raise PermanentError("wcatbench never deletes a bank; delete it in Hindsight's control plane")

    def close(self) -> None:
        if self._api is not None:
            self._api.close()
            self._api = None
