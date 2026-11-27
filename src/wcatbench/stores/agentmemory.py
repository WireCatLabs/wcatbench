"""AgentMemory (`@agentmemory/agentmemory`, pinned 0.9.30), its own server on this machine, records saved by `remember`.

What its code does that a reader would not guess, read in 0.9.30's dist in November 2026:
- The first start runs an interactive setup that wires it into every coding agent it finds. Without a terminal
  (stdin not a TTY) it writes default preferences instead and wires nothing. It runs here only under a throwaway
  HOME, with stdin closed.
- With no LLM key it runs "zero-LLM": no compression, no consolidation, BM25 plus the embedding provider.
  `OPENAI_EMBEDDING_API_KEY` gives it OpenAI embeddings without making OpenAI its LLM provider, so nothing else is
  sent. The local MiniLM model is English only and the corpus is Russian, so the local model is not used.
- `smart-search` returns ids and titles. Memories saved by `remember` are not expanded by `expandIds`, so the text
  of a hit is read from `/agentmemory/memories`, which also gives what the store holds.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess  # nosec B404
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from wcatbench.core.errors import PermanentError, TransientError
from wcatbench.core.secrets import keyring_secret
from wcatbench.core.types import BatchReceipt, Hit, ItemState, Record

VERSION = "0.9.30"
PORT = 3111


class AgentMemoryStore:
    name = "agentmemory"
    hosted = True  # every record's text goes to OpenAI for its embedding

    def __init__(self) -> None:
        self.root: Path | None = None
        self.keys: dict[str, str] = {}
        self.process: subprocess.Popen[bytes] | None = None

    @property
    def base(self) -> Path:
        if self.root is None:
            raise PermanentError("open() the store before using it")
        return self.root

    def version(self) -> str:
        return f"@agentmemory/agentmemory {VERSION}"

    def client(self) -> httpx.Client:
        secret = (self.base / "home/.agentmemory/secret").read_text().strip()
        return httpx.Client(
            base_url=f"http://127.0.0.1:{PORT}", headers={"Authorization": f"Bearer {secret}"}, timeout=120
        )

    def live(self) -> bool:
        try:
            return httpx.get(f"http://127.0.0.1:{PORT}/agentmemory/livez", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    def open(self, space: str, workdir: Path, started: datetime) -> None:
        self.root = workdir / space
        for folder in ("home", "data", "npm-cache"):
            (self.base / folder).mkdir(parents=True, exist_ok=True)
        keys = self.base / "keys.json"
        self.keys = json.loads(keys.read_text()) if keys.exists() else {}
        if self.live():
            raise PermanentError(f"something already answers on port {PORT}; stop it before this build")
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.base / "home"),
            "DBUS_SESSION_BUS_ADDRESS": "disabled:",
            "CI": "1",
            "TZ": "UTC",
            "EMBEDDING_PROVIDER": "openai",
            "OPENAI_EMBEDDING_API_KEY": keyring_secret("openai", "default"),
            "III_TELEMETRY_ENABLED": "false",
            "AGENTMEMORY_AUTO_COMPRESS": "false",
            "npm_config_cache": str(self.base / "npm-cache"),
        }
        npx = shutil.which("npx") or "npx"
        with (self.base / "server.log").open("ab") as log:
            self.process = subprocess.Popen(  # noqa: S603  # nosec B603
                [
                    npx,
                    "-y",
                    f"@agentmemory/agentmemory@{VERSION}",
                    "--data-dir",
                    str(self.base / "data"),
                    "--no-update-check",
                ],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                cwd=self.base / "home",
                start_new_session=True,
            )
        (self.base / "server.pid").write_text(str(self.process.pid))
        for _ in range(90):
            if self.live():
                return
            time.sleep(2)
        raise PermanentError(f"AgentMemory did not start; see {self.base / 'server.log'}")

    def ingest(self, batch: Sequence[Record]) -> BatchReceipt:
        started = time.perf_counter()
        sent, refused = [], {}
        with self.client() as client:
            for record in batch:
                if record.key in self.keys.values():
                    continue
                reply = client.post("/agentmemory/remember", json={"content": record.text})
                if reply.status_code >= 500:
                    raise TransientError(f"remember: HTTP {reply.status_code}")
                if reply.status_code >= 400:
                    refused[record.key] = f"HTTP {reply.status_code}"
                    continue
                self.keys[reply.json()["memory"]["id"]] = record.key
                sent.append(record.key)
                (self.base / "keys.json").write_text(json.dumps(self.keys, indent=2))
        return BatchReceipt(sent=tuple(sent), refused=refused, seconds=time.perf_counter() - started)

    def memories(self) -> list[dict[str, Any]]:
        with self.client() as client:
            reply = client.get("/agentmemory/memories", params={"agentId": "*"})
        reply.raise_for_status()
        return list(reply.json()["memories"])

    def held(self) -> dict[str, ItemState]:
        found = {memory["id"] for memory in self.memories()}
        return {key: ItemState.DONE for mem_id, key in self.keys.items() if mem_id in found}

    def settled(self, held: dict[str, ItemState]) -> bool:
        return True

    def contents(self) -> list[str]:
        """What the store keeps as active: superseded versions are left out of every recall path."""
        return [memory["content"] for memory in self.memories() if memory.get("isLatest", True)]

    def search(self, query: str, k: int) -> list[Hit]:
        with self.client() as client:
            reply = client.post("/agentmemory/smart-search", json={"query": query, "limit": k})
        reply.raise_for_status()
        texts = {memory["id"]: memory["content"] for memory in self.memories()}
        hits = []
        for row in reply.json().get("results", [])[:k]:
            key = self.keys.get(row["obsId"])
            hits.append(
                Hit(
                    keys=(key,) if key else (),
                    text=texts.get(row["obsId"], row.get("title", "")),
                    score=row.get("score"),
                )
            )
        return hits

    def describe(self) -> dict[str, object]:
        return {"memories": len(self.memories()), "embeddings": "openai text-embedding-3-small"}

    def clear(self) -> None:
        raise PermanentError("an AgentMemory build is a data folder: start a new space instead")

    def close(self) -> None:
        """Stops the server this adapter started, by its process group, never by name."""
        if self.process is not None and self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            self.process.wait(timeout=30)
        engine = self.base / "home/.agentmemory/iii.pid"
        if engine.exists():
            pid = int(engine.read_text().strip())
            try:
                cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")
            except FileNotFoundError:
                cmdline = ""
            if str(self.base) in cmdline:
                os.kill(pid, signal.SIGTERM)
        self.process = None
