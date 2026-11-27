"""Hindsight API slim 1.0.0 (`ghcr.io/vectorize-io/hindsight:1.0.0-slim`), the version Danil Pismenny tested.

The same HTTP API as `hindsight` (1.2), with this adapter starting and stopping its own container. Read in the
v1.0.0 source (hindsight-api-slim/hindsight_api/config.py) in November 2026: the language model defaults to OpenAI
gpt-4o-mini, embeddings and reranking to local models, which the slim image does not bundle. Here the language
model is gpt-5-mini and embeddings are OpenAI text-embedding-3-small, as for every extracting system in this round,
and the reranker is `rrf`, the passthrough that needs no model. The key reaches the container through an env file
of mode 600 that is removed once the container runs, never through a command line.
"""

from __future__ import annotations

import subprocess  # nosec B404
import time
from datetime import datetime
from pathlib import Path

import httpx

from wcatbench.core.errors import PermanentError
from wcatbench.core.secrets import keyring_secret
from wcatbench.stores.hindsight import HindsightStore

IMAGE = "ghcr.io/vectorize-io/hindsight:1.0.0-slim"
CONTAINER = "wcat-dapi-hindsight-slim"
PORT = 18888
LLM = "gpt-5-mini"
EMBEDDINGS = "text-embedding-3-small"


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)  # noqa: S603,S607  # nosec


class HindsightSlimStore(HindsightStore):
    name = "hindsight-slim"
    hosted = True

    def __init__(self) -> None:
        super().__init__(base_url=f"http://127.0.0.1:{PORT}")
        self.root: Path | None = None

    def start(self, root: Path) -> None:
        data = root / "pg0"
        data.mkdir(parents=True, exist_ok=True)
        data.chmod(0o777)  # the image's own user writes here; the parent folder is 0700
        if docker("ps", "-q", "--filter", f"name=^{CONTAINER}$").stdout.strip():
            return
        if docker("ps", "-aq", "--filter", f"name=^{CONTAINER}$").stdout.strip():
            docker("start", CONTAINER)
        else:
            env_file = root / "hindsight.env"
            env_file.touch(mode=0o600)
            env_file.write_text(
                "\n".join(
                    [
                        "HINDSIGHT_API_LLM_PROVIDER=openai",
                        f"HINDSIGHT_API_LLM_MODEL={LLM}",
                        f"HINDSIGHT_API_LLM_API_KEY={keyring_secret('openai', 'default')}",
                        "HINDSIGHT_API_EMBEDDINGS_PROVIDER=openai",
                        f"HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL={EMBEDDINGS}",
                        f"HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY={keyring_secret('openai', 'default')}",
                        "HINDSIGHT_API_RERANKER_PROVIDER=rrf",
                        "HINDSIGHT_API_OTEL_TRACES_ENABLED=false",
                    ]
                )
                + "\n"
            )
            try:
                docker(
                    "run",
                    "-d",
                    "--name",
                    CONTAINER,
                    "--env-file",
                    str(env_file),
                    "-p",
                    f"127.0.0.1:{PORT}:8888",
                    "-v",
                    f"{data}:/home/hindsight/.pg0",
                    IMAGE,
                )
            finally:
                env_file.unlink()
        for _ in range(120):
            try:
                if httpx.get(f"http://127.0.0.1:{PORT}/health", timeout=3).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(3)
        raise PermanentError(f"Hindsight slim did not answer on port {PORT}; see `docker logs {CONTAINER}`")

    def open(self, space: str, workdir: Path, started: datetime) -> None:
        self.root = workdir / space
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self.start(self.root)
        super().open(space, workdir, started)

    def version(self) -> str:
        return f"{IMAGE} (api {super().version()}, llm {LLM}, embeddings {EMBEDDINGS}, reranker rrf)"

    def contents(self) -> list[str]:
        texts, offset = [], 0
        while True:
            reply = self.api.request("GET", self.path(f"/memories/list?limit=100&offset={offset}"))
            items = reply.get("items", [])
            texts += [str(item.get("text", "")) for item in items]
            offset += len(items)
            if not items or offset >= reply.get("total", 0):
                return texts

    def close(self) -> None:
        super().close()
        docker("stop", CONTAINER, check=False)
