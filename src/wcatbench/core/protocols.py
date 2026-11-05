"""The four seams. A third-party package implements one of these and registers it under an entry point group."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from wcatbench.core.types import AgentReply, AnswerKey, BatchReceipt, Hit, ItemState, Question, Record


@runtime_checkable
class Store(Protocol):
    """A memory system. One instance works in one space: a tag, a user id or a folder."""

    name: str
    hosted: bool

    def version(self) -> str: ...
    def open(self, space: str, workdir: Path) -> None: ...
    def ingest(self, batch: Sequence[Record]) -> BatchReceipt: ...
    def held(self) -> dict[str, ItemState]:
        """What the store itself says it holds, by record id. Resume trusts this over our own ledger."""
        ...

    def settled(self, held: dict[str, ItemState]) -> bool:
        """Ready to answer, which can be later than indexed: Supermemory builds memories after `done`."""
        ...

    def search(self, query: str, k: int) -> list[Hit]: ...
    def describe(self) -> dict[str, object]: ...
    def clear(self) -> None: ...
    def close(self) -> None: ...


@runtime_checkable
class Agent(Protocol):
    name: str

    def version(self) -> str: ...
    def ask(self, question: Question, key: AnswerKey | None = None) -> AgentReply:
        """`key` goes to the oracle only. A real agent adapter ignores it, and the sandbox keeps it off disk."""
        ...


@runtime_checkable
class Scorer(Protocol):
    name: str

    def score(self, reply: AgentReply, key: AnswerKey) -> dict[str, bool]: ...
