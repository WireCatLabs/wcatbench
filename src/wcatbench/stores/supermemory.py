"""Supermemory (hosted). One build is one container tag.

What its API does that a reader would not guess, each seen in November 2026:
- A batch can come back as HTTP 200 with `success: false` or a single "Failed to save documents" item.
- One batch of 100 took 88 s on average; a 60 s timeout failed four times in a row.
- A document is `done` before its memories exist. Those are built later and show as `dreamingStatus`, which only
  the per-document GET returns, so `settled()` samples 50 documents.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from wcatbench.config import get_settings
from wcatbench.core.errors import PermanentError
from wcatbench.core.http import JsonApi
from wcatbench.core.secrets import service_key
from wcatbench.core.types import BatchReceipt, Hit, ItemState, Record

BASE = "https://api.supermemory.ai"
STATES = {"done": ItemState.DONE, "failed": ItemState.FAILED}
SAMPLE = 50


class SupermemoryStore:
    name = "supermemory"
    hosted = True

    def __init__(
        self,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._key, self._transport, self._sleep = api_key, transport, sleep
        self._api: JsonApi | None = None
        self.tag = ""
        self.documents: dict[str, str] = {}

    @property
    def api(self) -> JsonApi:
        if self._api is None:
            raise PermanentError("open() the store before using it")
        return self._api

    def version(self) -> str:
        return "api v3 documents, v4 search"

    def open(self, space: str, workdir: Path, started: datetime) -> None:
        key = self._key or service_key("supermemory", get_settings().keyring_account)
        self._api = JsonApi(BASE, f"Bearer {key}", self._transport)
        self.tag = space

    def ingest(self, batch: Sequence[Record]) -> BatchReceipt:
        documents = [
            {
                "content": record.text,
                "containerTag": self.tag,
                "customId": record.key,
                "metadata": {"rid": record.key},
                "documentDate": record.timestamp,
            }
            for record in batch
        ]
        started = time.perf_counter()
        reply: dict[str, Any] = {}
        for attempt in range(3):
            reply = self.api.request("POST", "/v3/documents/batch", {"documents": documents}, timeout=300)
            if reply.get("success"):
                break
            self._sleep(10 * (attempt + 1))
        items = reply.get("results", [])
        keys = [record.key for record in batch]
        if len(items) == len(documents):
            refused = {
                key: json.dumps(item)[:300]
                for key, item in zip(keys, items, strict=True)
                if item.get("status") == "error"
            }
        else:
            refused = dict.fromkeys(keys, json.dumps(items)[:300])
        return BatchReceipt(
            sent=tuple(key for key in keys if key not in refused),
            refused=refused,
            seconds=time.perf_counter() - started,
        )

    def held(self) -> dict[str, ItemState]:
        states: dict[str, ItemState] = {}
        page = 1
        while True:
            reply = self.api.request(
                "POST", "/v3/documents/list", {"containerTags": [self.tag], "limit": 500, "page": page, "order": "asc"}
            )
            for document in reply.get("memories", []):
                key = document.get("customId") or (document.get("metadata") or {}).get("rid")
                if key:
                    states[key] = STATES.get(document["status"], ItemState.QUEUED)
                    self.documents[key] = document["id"]
            if page >= reply["pagination"]["totalPages"]:
                return states
            page += 1

    def settled(self, held: dict[str, ItemState]) -> bool:
        keys = sorted(held)[:: max(1, len(held) // SAMPLE)]
        sample = [self.documents[key] for key in keys if key in self.documents]
        states = [self.api.request("GET", f"/v3/documents/{document}").get("dreamingStatus") for document in sample]
        return all(state in STATES for state in states)

    def search(self, query: str, k: int) -> list[Hit]:
        body = {
            "q": query,
            "containerTag": self.tag,
            "searchMode": "hybrid",
            "limit": k,
            "include": {"documents": True},
        }
        reply = self.api.request("POST", "/v4/search", body)
        hits = []
        for item in reply.get("results", []):
            keys = [(document.get("metadata") or {}).get("rid") for document in item.get("documents") or []]
            keys.append((item.get("metadata") or {}).get("rid"))
            kind = "memory" if "memory" in item else "chunk" if "chunk" in item else None
            hits.append(
                Hit(keys=tuple(dict.fromkeys(key for key in keys if key)), score=item.get("similarity"), kind=kind)
            )
        return hits

    def describe(self) -> dict[str, object]:
        tags = self.api.request("GET", "/v3/container-tags/list")
        for tag in tags if isinstance(tags, list) else tags.get("containerTags", []):
            if tag["containerTag"] == self.tag:
                return {
                    "documents": tag.get("documentCount"),
                    "memories": tag.get("memoryCount"),
                    "last_activity": tag.get("lastActivityAt"),
                }
        return {"documents": 0, "memories": 0}

    def clear(self) -> None:
        raise PermanentError("wcatbench never deletes a hosted tag; delete it in the Supermemory console")

    def close(self) -> None:
        if self._api is not None:
            self._api.close()
            self._api = None
