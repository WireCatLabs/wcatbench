"""Mem0 OSS (mem0ai 2.2.1, self-hosted, not the hosted platform): local Qdrant and SQLite, OpenAI for extraction.

Each record goes through `add(..., infer=True)`: Mem0's language model turns it into memories and may update or
delete earlier ones. So a memory names the record it came from in metadata, and the stored stage reads Mem0's own
memories, not our records. Telemetry to PostHog is on by default in 2.2.1 (`MEM0_TELEMETRY`); it is turned off.
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from wcatbench.core.errors import PermanentError
from wcatbench.core.secrets import keyring_secret
from wcatbench.core.types import BatchReceipt, Hit, ItemState, Record

# Mem0 OSS lives in its own virtualenv: `uv venv` there, then `uv pip install mem0ai==2.2.1 qdrant-client`.
VENV_PYTHON = Path(os.environ.get("WCATBENCH_MEM0_PYTHON", "/var/tmp/wcat-dapi/mem0/venv/bin/python"))  # noqa: S108  # nosec B108
WORKER = Path(__file__).with_name("mem0_oss_worker.py")
LLM = "gpt-5-mini"
EMBEDDER = "text-embedding-3-small"


class Mem0OssStore:
    name = "mem0-oss"
    hosted = True  # extraction and embeddings run at OpenAI

    def __init__(self, python: Path = VENV_PYTHON) -> None:
        self.python = python
        self.root: Path | None = None
        self.space = ""

    @property
    def base(self) -> Path:
        if self.root is None:
            raise PermanentError("open() the store before using it")
        return self.root

    def version(self) -> str:
        return f"mem0ai 2.2.1 (llm {LLM}, embedder {EMBEDDER})"

    def call(self, op: str, **fields: Any) -> Any:
        request = {"op": op, "root": str(self.base), "llm": LLM, "embedder": EMBEDDER, "user_id": self.space, **fields}
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.base / "home"),
            "MEM0_DIR": str(self.base),
            "MEM0_TELEMETRY": "False",
            "MEM0_REQUEST_ROOT_JSON": json.dumps(str(self.base)),
            "DBUS_SESSION_BUS_ADDRESS": "disabled:",
            "OPENAI_API_KEY": keyring_secret("openai", "default"),
        }
        done = subprocess.run(  # noqa: S603  # nosec B603
            [str(self.python), "-I", str(WORKER)],
            input=json.dumps(request, ensure_ascii=False),
            env=env,
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
        with (self.base / "worker.log").open("a") as log:
            log.write(done.stderr[-4000:])
        if done.returncode != 0:
            raise PermanentError(f"mem0 worker {op} exited {done.returncode}; see {self.base / 'worker.log'}")
        return json.loads(done.stdout.strip().splitlines()[-1])

    def open(self, space: str, workdir: Path, started: datetime) -> None:
        self.root = workdir / space
        (self.base / "home").mkdir(parents=True, exist_ok=True)
        self.base.chmod(0o700)
        self.space = space.replace("-", "_")

    def ingest(self, batch: Sequence[Record]) -> BatchReceipt:
        started = time.perf_counter()
        done = self.call("add", records=[{"key": record.key, "text": record.text} for record in batch])
        with (self.base / "adds.jsonl").open("a") as lines:
            for row in done:
                lines.write(json.dumps(row, ensure_ascii=False) + "\n")
        return BatchReceipt(sent=tuple(row["key"] for row in done), seconds=time.perf_counter() - started)

    def held(self) -> dict[str, ItemState]:
        adds = self.base / "adds.jsonl"
        if not adds.exists():
            return {}
        return {json.loads(line)["key"]: ItemState.DONE for line in adds.read_text().splitlines()}

    def settled(self, held: dict[str, ItemState]) -> bool:
        return True

    def contents(self) -> list[str]:
        return [str(row["memory"]) for row in self.call("all")]

    def search(self, query: str, k: int) -> list[Hit]:
        hits = []
        for row in self.call("search", query=query, k=k)[:k]:
            key = (row.get("metadata") or {}).get("key")
            hits.append(Hit(keys=(key,) if key else (), text=str(row["memory"]), score=row.get("score")))
        return hits

    def forget(self, keys: Sequence[str]) -> int:
        """Delete every memory Mem0 made from these records, through its own `delete`."""
        return int(self.call("forget", keys=list(keys))["deleted"])

    def describe(self) -> dict[str, object]:
        return {"memories": len(self.call("all")), "llm": LLM, "embedder": EMBEDDER}

    def clear(self) -> None:
        raise PermanentError("a Mem0 OSS build is a folder: start a new space instead")

    def close(self) -> None:
        return None
