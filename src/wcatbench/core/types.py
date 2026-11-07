"""The data that crosses an adapter boundary. Adapters exchange these and nothing else."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Privacy(StrEnum):
    """Hosted stores refuse `private` datasets: real people's data never leaves the machine by accident."""

    SYNTHETIC = "synthetic"
    PUBLIC = "public"
    PRIVATE = "private"


class Record(Frozen):
    """One message, mail, note or meeting. `id` travels as metadata to a store, never inside the text.

    Field order is the corpus file's key order: the published corpus digests depend on it.
    """

    id: str
    kind: str
    timestamp: str
    text: str
    source: str | None = None
    thread: str | None = None
    author: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    # Set by the loader from the record's place in the whole corpus (r0001, r0002 …), never written to the corpus
    # file. Stores and agents use it: the hosted builds of November 2026 are keyed by it, and agents cite it.
    name: str | None = Field(default=None, exclude=True)

    @property
    def key(self) -> str:
        """What a store keys this record by, and what its hits name."""
        return self.name or self.id


class Question(Frozen):
    id: str
    text: str
    as_of: str | None = None
    category: str = "fact"


class AnswerKey(Frozen):
    """What a correct answer is. Kept apart from Question, so nothing that reaches an agent can carry it."""

    question_id: str
    answers: tuple[str, ...]
    sources: tuple[str, ...] = ()
    stale_answers: tuple[str, ...] = ()
    # How answers compare: "amount", "datetime", "date", "count" or "weekday". None is the exact match of the
    # published rounds, and a key without a form is written without the field so its digest stays the same.
    form: str | None = None


class Hit(Frozen):
    """One search result. A memory distilled from several records names all of them, at one rank."""

    keys: tuple[str, ...]
    score: float | None = None
    text: str | None = None
    kind: str | None = None


class ItemState(StrEnum):
    """A store's own word for one record, mapped to these. `queued` is never `missing`: resume must not resend it."""

    QUEUED = "queued"
    DONE = "done"
    FAILED = "failed"


class BatchReceipt(Frozen):
    sent: tuple[str, ...]
    refused: dict[str, str] = Field(default_factory=dict)
    seconds: float = 0.0


class Usage(Frozen):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float | None = None
    source: Literal["agent-files", "proxy", "none"] = "none"


class Outcome(StrEnum):
    """Kept apart from the score: a harness failure must never count as the agent's wrong answer."""

    COMPLETED = "completed"
    ERROR = "error"
    TIMEOUT = "timeout"
    INVALID = "invalid"


class AgentReply(Frozen):
    answer: str
    sources: tuple[str, ...] = ()
    outcome: Outcome = Outcome.COMPLETED
    usage: Usage = Usage()
    seconds: float = 0.0
    note: str | None = None


class DatasetManifest(Frozen):
    """What a built dataset is. A store build and a run record `corpus_sha256`, so results name their data."""

    name: str
    version: int
    privacy: Privacy
    params: dict[str, int]
    records: int
    questions: int
    corpus_sha256: str
    key_sha256: str
    extra: dict[str, object] = Field(default_factory=dict)
