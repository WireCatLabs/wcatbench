"""Mem0 (hosted). One build is one user id.

What its API does that a reader would not guess, each seen in November 2026:
- An add is accepted at once and processed later. Only the organisation's event feed tells which record became
  which state, so `held()` reads it, newest first, back to the build's start.
- The feed returns `payload` and `metadata` sometimes as objects and sometimes as Python repr strings.
- Every add counts against the plan's monthly allowance, processed or not. A PENDING record is never sent again.
- The number of memories is not the number of records: one add can make several memories or none.
"""

from __future__ import annotations

import ast
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from wcatbench.config import get_settings
from wcatbench.core.errors import PermanentError, WcatbenchError
from wcatbench.core.http import JsonApi
from wcatbench.core.secrets import service_key
from wcatbench.core.types import BatchReceipt, Hit, ItemState, Record

BASE = "https://api.mem0.ai"
STATES = {"SUCCEEDED": ItemState.DONE, "FAILED": ItemState.FAILED}
# A record added twice keeps its best outcome.
RANK = {ItemState.FAILED: 0, ItemState.QUEUED: 1, ItemState.DONE: 2}
WORKERS = 4


def literal(value: Any) -> dict[str, Any]:
    if isinstance(value, str) and value.startswith("{"):
        parsed = ast.literal_eval(value)
        return parsed if isinstance(parsed, dict) else {}
    return value if isinstance(value, dict) else {}


class Mem0Store:
    name = "mem0"
    hosted = True

    def __init__(
        self, api_key: str | None = None, transport: httpx.BaseTransport | None = None, infer: bool = True
    ) -> None:
        self._key, self._transport, self.infer = api_key, transport, infer
        self._api: JsonApi | None = None
        self.user = ""
        self.started: datetime | None = None

    @property
    def api(self) -> JsonApi:
        if self._api is None:
            raise PermanentError("open() the store before using it")
        return self._api

    def version(self) -> str:
        return "api v3 memories, v1 events"

    def open(self, space: str, workdir: Path, started: datetime) -> None:
        key = self._key or service_key("mem0", get_settings().keyring_account)
        self._api = JsonApi(BASE, f"Token {key}", self._transport)
        self.user, self.started = space, started

    def _add(self, record: Record) -> str | None:
        body = {
            "messages": [{"role": "user", "content": record.text}],
            "user_id": self.user,
            "agent_id": "wcatbench",
            "metadata": {"rid": record.key},
            "infer": self.infer,
        }
        try:
            self.api.request("POST", "/v3/memories/add/", body)
        except WcatbenchError as error:
            return str(error)[:300]
        return None

    def ingest(self, batch: Sequence[Record]) -> BatchReceipt:
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            errors = list(pool.map(self._add, batch))
        refused = {record.key: error for record, error in zip(batch, errors, strict=True) if error}
        sent = tuple(record.key for record in batch if record.key not in refused)
        return BatchReceipt(sent=sent, refused=refused, seconds=time.perf_counter() - started)

    def held(self) -> dict[str, ItemState]:
        """Two walks of the feed, merged. While Mem0 processes, an event can move to a page already read, and one
        walk then misses it: on 2026-11-05 one walk of 6,500 adds listed 2 as absent. A record listed as absent is
        one a resume would pay for twice."""
        states = self._walk()
        for key, state in self._walk().items():
            if key not in states or RANK[state] > RANK[states[key]]:
                states[key] = state
        return states

    def _walk(self) -> dict[str, ItemState]:
        states: dict[str, ItemState] = {}
        page = 1
        while True:
            reply = self.api.request("GET", f"/v1/events/?page={page}&page_size=100")
            for event in reply.get("results", []):
                if self.started and datetime.fromisoformat(event["created_at"]) < self.started:
                    return states
                payload = literal(event.get("payload"))
                if event.get("event_type") != "ADD" or payload.get("user_id") != self.user:
                    continue
                key = literal(event.get("metadata")).get("rid") or literal(payload.get("metadata")).get("rid")
                if not key:
                    continue
                state = STATES.get(event["status"], ItemState.QUEUED)
                if key not in states or RANK[state] >= RANK[states[key]]:
                    states[key] = state
            if not reply.get("next"):
                return states
            page += 1

    def settled(self, held: dict[str, ItemState]) -> bool:
        return True

    def search(self, query: str, k: int) -> list[Hit]:
        reply = self.api.request(
            "POST", "/v3/memories/search/", {"query": query, "filters": {"user_id": self.user}, "top_k": k}
        )
        hits = []
        for item in reply.get("results", []):
            key = (item.get("metadata") or {}).get("rid")
            hits.append(
                Hit(keys=(key,) if key else (), score=item.get("score"), text=item.get("memory"), kind="memory")
            )
        return hits

    def describe(self) -> dict[str, object]:
        reply = self.api.request("POST", "/v3/memories/?page=1&page_size=1", {"filters": {"user_id": self.user}})
        return {"memories": reply.get("count")}

    def clear(self) -> None:
        raise PermanentError("wcatbench never deletes a hosted user; delete it in the Mem0 dashboard")

    def close(self) -> None:
        if self._api is not None:
            self._api.close()
            self._api = None
