"""Graphiti (graphiti-core 0.31.2 over FalkorDB): each record is an episode a language model turns into a temporal
knowledge graph of entities and facts. One build is one group. Install with `uv sync --extra graphiti`.

The library is driven directly, not through Graphiti's REST server: that server's single worker stops for good on
the first failed episode while new posts still return 202. `hosted` is True: every episode goes to OpenAI.

What it does that a reader would not guess, from graphiti-core 0.31.2's source in November 2026:
- Episodes are processed one after another; each uses earlier ones as context, so ingest is slow by design.
- An episode's `uuid` argument loads an existing episode; the record key goes in `name` instead.
- Both of its model slots default to another model, so both are set to gpt-4o-mini here, the reranker's too.
- A search hit is a fact (an edge) naming the episodes it came from; the build folder maps those to records.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from wcatbench.core.errors import PermanentError
from wcatbench.core.secrets import service_key
from wcatbench.core.types import BatchReceipt, Hit, ItemState, Record

MODEL = os.environ.get("WCATBENCH_GRAPHITI_MODEL", "gpt-4o-mini")
EMBEDDING = "text-embedding-3-small"
LEDGER = "graphiti-episodes.json"


class GraphitiStore:
    name = "graphiti"
    hosted = True

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.graph: Any = None
        self.group = ""
        self.ledger = Path()
        self.episodes: dict[str, str] = {}
        self.failed: dict[str, str] = {}

    def run(self, work: Any) -> Any:
        return self.loop.run_until_complete(work)

    def version(self) -> str:
        from importlib.metadata import version

        return version("graphiti-core")

    def open(self, space: str, workdir: Path, started: datetime) -> None:
        try:
            from graphiti_core import Graphiti
            from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
            from graphiti_core.driver.falkordb_driver import FalkorDriver
            from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
            from graphiti_core.llm_client.config import LLMConfig
            from graphiti_core.llm_client.openai_client import OpenAIClient
        except ImportError as error:
            raise PermanentError("the Graphiti store needs `uv sync --extra graphiti`") from error
        key = service_key("openai", "default")
        llm = LLMConfig(api_key=key, model=MODEL, small_model=MODEL)
        driver = FalkorDriver(
            host=os.environ.get("WCATBENCH_FALKORDB_HOST", "127.0.0.1"),
            port=int(os.environ.get("WCATBENCH_FALKORDB_PORT", "16379")),
        )
        self.graph = Graphiti(
            graph_driver=driver,
            llm_client=OpenAIClient(config=llm),
            embedder=OpenAIEmbedder(OpenAIEmbedderConfig(api_key=key, embedding_model=EMBEDDING)),
            cross_encoder=OpenAIRerankerClient(config=llm),
        )
        self.run(self.graph.build_indices_and_constraints())
        self.group = space
        workdir.mkdir(parents=True, exist_ok=True)
        self.ledger = workdir / LEDGER
        if self.ledger.exists():
            saved = json.loads(self.ledger.read_text())
            self.episodes, self.failed = saved["episodes"], saved.get("failed", {})

    def save(self) -> None:
        # Written aside and renamed: a full disk once cut the ledger mid-write and lost the build's place.
        partial = self.ledger.with_suffix(".tmp")
        partial.write_text(json.dumps({"episodes": self.episodes, "failed": self.failed}))
        partial.replace(self.ledger)

    def ingest(self, batch: Sequence[Record]) -> BatchReceipt:
        from graphiti_core.nodes import EpisodeType
        from redis.exceptions import ConnectionError as DatabaseGone

        started = time.perf_counter()
        sent: list[str] = []
        refused: dict[str, str] = {}
        for record in batch:
            try:
                result = self.run(
                    self.graph.add_episode(
                        name=record.key,
                        episode_body=record.text,
                        source_description=record.kind,
                        reference_time=datetime.fromisoformat(record.timestamp.replace("Z", "+00:00")),
                        source=EpisodeType.message if record.kind != "notes" else EpisodeType.text,
                        group_id=self.group,
                    )
                )
            # A lost database is not this record's fault: marking every remaining record failed took 6,686 records
            # in seconds when FalkorDB 4.14.6 crashed. Stop instead; --resume continues from the ledger.
            except DatabaseGone as error:
                self.save()
                raise PermanentError(f"FalkorDB stopped answering at {record.key}: {error}") from error
            # One bad episode must not stop the build, the failure the REST server has.
            except Exception as error:  # noqa: BLE001
                refused[record.key] = f"{type(error).__name__}: {str(error)[:200]}"
                self.failed[record.key] = refused[record.key]
                continue
            self.episodes[result.episode.uuid] = record.key
            self.failed.pop(record.key, None)
            sent.append(record.key)
            self.save()
        self.save()
        return BatchReceipt(sent=tuple(sent), refused=refused, seconds=time.perf_counter() - started)

    def held(self) -> dict[str, ItemState]:
        states = dict.fromkeys(self.episodes.values(), ItemState.DONE)
        states.update({key: ItemState.FAILED for key in self.failed if key not in states})
        return states

    def settled(self, held: dict[str, ItemState]) -> bool:
        return True

    def search(self, query: str, k: int) -> list[Hit]:
        edges = self.run(self.graph.search(query, group_ids=[self.group], num_results=k))
        hits = []
        for edge in edges:
            keys = tuple(dict.fromkeys(self.episodes[uuid] for uuid in edge.episodes or () if uuid in self.episodes))
            hits.append(Hit(keys=keys, text=edge.fact, kind="fact"))
        return hits

    def describe(self) -> dict[str, object]:
        return {"group": self.group, "episodes": len(self.episodes), "failed": len(self.failed), "model": MODEL}

    def clear(self) -> None:
        raise PermanentError("wcatbench never deletes a graph; drop the group in FalkorDB itself")

    def close(self) -> None:
        if self.graph is not None:
            self.run(self.graph.close())
            self.graph = None
        self.loop.close()
