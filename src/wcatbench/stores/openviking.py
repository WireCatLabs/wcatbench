"""OpenViking (openviking 0.4.17.1 from PyPI), its own server on this machine, records added as one folder of files.

Read in 0.4.17.1's code and docs in November 2026: embeddings default to Volcengine and the reranker to Volcengine's
doubao model, and the VLM (the model that writes summaries) has no provider until one is set. Here embeddings are
OpenAI text-embedding-3-small and the VLM is gpt-5-mini, reranking is not configured, tracing and the usage
reporter stay off (their defaults). `server.agent_evolution.enabled` is false in `openviking-evo-off` (Danil
Pismenny's profile) and true in `openviking-evo-on`. The key sits in the server's config file, mode 600, inside a
0700 folder, because the server reads its models from that file.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess  # nosec B404
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from wcatbench.core.errors import PermanentError
from wcatbench.core.secrets import keyring_secret
from wcatbench.core.types import BatchReceipt, Hit, ItemState, Record

# OpenViking lives in its own virtualenv: `uv venv` there, then `uv pip install openviking==0.4.17.1`.
VENV = Path(os.environ.get("WCATBENCH_OPENVIKING_VENV", "/var/tmp/wcat-dapi/openviking/venv"))  # noqa: S108  # nosec B108
WORKER = Path(__file__).with_name("openviking_worker.py")
PORT = 1933
VLM = "gpt-5-mini"
EMBEDDINGS = "text-embedding-3-small"
TARGET = "viking://resources/rules-trial"


class OpenVikingStore:
    name = "openviking"
    hosted = True
    evolution = False

    def __init__(self) -> None:
        self.root: Path | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self.names: dict[str, str] = {}

    @property
    def base(self) -> Path:
        if self.root is None:
            raise PermanentError("open() the store before using it")
        return self.root

    def version(self) -> str:
        return f"openviking 0.4.17.1 (vlm {VLM}, embeddings {EMBEDDINGS}, agent evolution {self.evolution})"

    def config(self) -> dict[str, Any]:
        key = keyring_secret("openai", "default")
        return {
            "server": {
                "host": "127.0.0.1",
                "port": PORT,
                "root_api_key": None,
                "agent_evolution": {"enabled": self.evolution},
            },
            "storage": {
                "workspace": str(self.base / "data"),
                "vectordb": {"name": "context", "backend": "local"},
                "agfs": {"backend": "local"},
            },
            "embedding": {
                "dense": {
                    "provider": "openai",
                    "api_base": "https://api.openai.com/v1",
                    "api_key": key,
                    "model": EMBEDDINGS,
                    "dimension": 1536,
                }
            },
            "vlm": {"provider": "openai", "api_base": "https://api.openai.com/v1", "api_key": key, "model": VLM},
        }

    def live(self) -> bool:
        try:
            return httpx.get(f"http://127.0.0.1:{PORT}/health", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    def open(self, space: str, workdir: Path, started: datetime) -> None:
        self.root = workdir / space
        (self.base / "home").mkdir(parents=True, exist_ok=True)
        (self.base / "files").mkdir(exist_ok=True)
        self.base.chmod(0o700)
        names = self.base / "names.json"
        self.names = json.loads(names.read_text()) if names.exists() else {}
        if self.live():
            raise PermanentError(f"something already answers on port {PORT}; stop it before this build")
        conf = self.base / "ov.conf"
        conf.touch(mode=0o600)
        conf.write_text(json.dumps(self.config(), indent=2))
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.base / "home"),
            "DBUS_SESSION_BUS_ADDRESS": "disabled:",
            "TZ": "UTC",
            "OPENVIKING_CONFIG_FILE": str(conf),
        }
        with (self.base / "server.log").open("ab") as log:
            self.process = subprocess.Popen(  # noqa: S603  # nosec B603
                [
                    str(VENV / "bin/openviking-server"),
                    "--config",
                    str(conf),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(PORT),
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
        raise PermanentError(f"OpenViking did not start; see {self.base / 'server.log'}")

    def call(self, op: str, **fields: Any) -> Any:
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.base / "home"), "DBUS_SESSION_BUS_ADDRESS": "disabled:"}
        done = subprocess.run(  # noqa: S603  # nosec B603
            [str(VENV / "bin/python"), "-I", str(WORKER)],
            input=json.dumps({"op": op, "url": f"http://127.0.0.1:{PORT}", **fields}, ensure_ascii=False),
            env=env,
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
        with (self.base / "worker.log").open("a") as log:
            log.write(done.stderr[-4000:])
        if done.returncode != 0:
            raise PermanentError(f"openviking worker {op} exited {done.returncode}; see {self.base / 'worker.log'}")
        return json.loads(done.stdout.strip().splitlines()[-1])

    def ingest(self, batch: Sequence[Record]) -> BatchReceipt:
        started = time.perf_counter()
        for record in batch:
            name = f"{record.timestamp[:10]}-{record.key}.md"
            (self.base / "files" / name).write_text(record.text + "\n")
            self.names[Path(name).stem] = record.key
        (self.base / "names.json").write_text(json.dumps(self.names, indent=2))
        reply = self.call("add", path=str(self.base / "files"), to=TARGET)
        (self.base / "add.json").write_text(json.dumps(reply, ensure_ascii=False, indent=2))
        return BatchReceipt(sent=tuple(record.key for record in batch), seconds=time.perf_counter() - started)

    def held(self) -> dict[str, ItemState]:
        if not (self.base / "add.json").exists():
            return {}
        return dict.fromkeys(self.names.values(), ItemState.DONE)

    def settled(self, held: dict[str, ItemState]) -> bool:
        return True

    def key_of(self, uri: str) -> str | None:
        return self.names.get(Path(uri.rstrip("/")).stem)

    def contents(self) -> list[str]:
        listing = self.call("ls", uri=TARGET)
        rows = listing if isinstance(listing, list) else listing.get("items", listing.get("result", []))
        texts = []
        for row in rows:
            uri = row.get("uri") if isinstance(row, dict) else str(row)
            if uri and uri.endswith(".md"):
                texts.append(str(self.call("read", uri=uri)["text"]))
        return texts

    def search(self, query: str, k: int) -> list[Hit]:
        reply = self.call("find", query=query, target=TARGET, k=k)
        found = reply.get("resources", []) + reply.get("memories", [])
        found.sort(key=lambda row: row.get("score") or 0.0, reverse=True)
        hits = []
        for row in found[:k]:
            uri = str(row.get("uri", ""))
            key = self.key_of(uri)
            text = (
                str(self.call("read", uri=uri)["text"])
                if key
                else str(row.get("abstract") or row.get("overview") or "")
            )
            hits.append(
                Hit(keys=(key,) if key else (), text=text, score=row.get("score"), kind=row.get("context_type"))
            )
        return hits

    def describe(self) -> dict[str, object]:
        return {"files": len(self.names), "vlm": VLM, "embeddings": EMBEDDINGS, "agent_evolution": self.evolution}

    def clear(self) -> None:
        raise PermanentError("an OpenViking build is a folder: start a new space instead")

    def close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            self.process.wait(timeout=60)
        self.process = None


class OpenVikingEvolutionStore(OpenVikingStore):
    name = "openviking-evo"
    evolution = True
