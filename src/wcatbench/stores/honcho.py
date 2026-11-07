"""Honcho (self-hosted server, its own language model for conclusions). One build is one workspace.

The server runs on this machine, but `hosted` is True: its deriver sends every message to the language model.

How the corpus maps onto Honcho, which models people talking: every record is a message from one peer, the
archive's owner, in one session per record kind. Honcho then derives conclusions about that peer, and search
reads those conclusions, the memory an agent's plugin reads too.

What its API does that a reader would not guess, each from Honcho 3.5.0's source in November 2026:
- A message is stored at once; the deriver works later, from a queue. Settled means that queue is empty.
- A conclusion names the messages it came from (`source_message_ids`, new in 3.5.0) by Honcho's own message ids,
  so search maps them back to records through the messages' metadata.
- A conclusion query must name the observer and the observed peer, here both the owner.
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

DEFAULT_URL = "http://127.0.0.1:18000"
OWNER = "owner"
PAGE = 100


class HonchoStore:
    name = "honcho"
    hosted = True

    def __init__(self, base_url: str | None = None, transport: httpx.BaseTransport | None = None) -> None:
        self.base = base_url or os.environ.get("WCATBENCH_HONCHO_URL", DEFAULT_URL)
        self._transport = transport
        self._api: JsonApi | None = None
        self.workspace = ""
        self.sessions: set[str] = set()
        self._keys: dict[str, str] = {}

    @property
    def api(self) -> JsonApi:
        if self._api is None:
            raise PermanentError("open() the store before using it")
        return self._api

    def path(self, tail: str = "") -> str:
        return f"/v3/workspaces/{self.workspace}{tail}"

    def version(self) -> str:
        reply = self.api.request("GET", "/openapi.json")
        return str(reply.get("info", {}).get("version", "unknown"))

    def open(self, space: str, workdir: Path, started: datetime) -> None:
        # A local server with auth off takes no key; the header only satisfies JsonApi.
        self._api = JsonApi(self.base, "Bearer none", self._transport)
        self.workspace = space
        self.api.request("POST", "/v3/workspaces", {"id": space})
        self.api.request("POST", self.path("/peers"), {"id": OWNER})
        listed = self.api.request("POST", self.path(f"/sessions/list?page=1&size={PAGE}"), {})
        self.sessions = {item["id"] for item in listed.get("items", [])}

    def session(self, kind: str) -> str:
        if kind not in self.sessions:
            self.api.request("POST", self.path("/sessions"), {"id": kind, "peers": {OWNER: {}}})
            self.sessions.add(kind)
        return kind

    def ingest(self, batch: Sequence[Record]) -> BatchReceipt:
        started = time.perf_counter()
        refused: dict[str, str] = {}
        sent: list[str] = []
        for kind in dict.fromkeys(record.kind for record in batch):
            group = [record for record in batch if record.kind == kind]
            messages = [
                {
                    "content": record.text,
                    "peer_id": OWNER,
                    "created_at": record.timestamp,
                    "metadata": {"rid": record.key, "kind": record.kind},
                }
                for record in group
            ]
            try:
                session = self.session(kind)
                for start in range(0, len(messages), PAGE):
                    chunk = messages[start : start + PAGE]
                    self.api.request("POST", self.path(f"/sessions/{session}/messages"), {"messages": chunk})
                    sent.extend(record.key for record in group[start : start + PAGE])
            except WcatbenchError as error:
                reason = str(error)[:300]
                refused.update({r.key: reason for r in group if r.key not in sent})
        return BatchReceipt(sent=tuple(sent), refused=refused, seconds=time.perf_counter() - started)

    def messages(self) -> dict[str, str]:
        """Honcho's message id to our record key, for every message in the workspace."""
        keys: dict[str, str] = {}
        for session in sorted(self.sessions):
            page = 1
            while True:
                tail = f"/sessions/{session}/messages/list?page={page}&size={PAGE}"
                reply = self.api.request("POST", self.path(tail), {})
                for item in reply.get("items", []):
                    rid = (item.get("metadata") or {}).get("rid")
                    if rid:
                        keys[item["id"]] = rid
                if page >= reply.get("pages", 0):
                    break
                page += 1
        return keys

    def held(self) -> dict[str, ItemState]:
        self._keys = self.messages()
        return dict.fromkeys(self._keys.values(), ItemState.DONE)

    def queue(self) -> dict[str, Any]:
        return dict(self.api.request("GET", self.path("/queue/status")))

    def settled(self, held: dict[str, ItemState]) -> bool:
        status = self.queue()
        return not status.get("pending_work_units") and not status.get("in_progress_work_units")

    def search(self, query: str, k: int) -> list[Hit]:
        if not self._keys:
            self._keys = self.messages()
        body = {"query": query, "top_k": k, "filters": {"observer": OWNER, "observed": OWNER}}
        reply = self.api.request("POST", self.path("/conclusions/query"), body, timeout=120.0)
        hits = []
        for item in reply:
            found = (self._keys.get(message) for message in item.get("source_message_ids") or ())
            keys = tuple(dict.fromkeys(key for key in found if key))
            hits.append(Hit(keys=keys, text=item.get("content"), kind=item.get("level") or "conclusion"))
        return hits

    def describe(self) -> dict[str, object]:
        listed = self.api.request(
            "POST", self.path("/conclusions/list?page=1&size=1"), {"filters": {"observer": OWNER, "observed": OWNER}}
        )
        return {"sessions": sorted(self.sessions), "conclusions": listed.get("total"), "queue": self.queue()}

    def clear(self) -> None:
        raise PermanentError("wcatbench never deletes a workspace; delete it in Honcho itself")

    def close(self) -> None:
        if self._api is not None:
            self._api.close()
            self._api = None
