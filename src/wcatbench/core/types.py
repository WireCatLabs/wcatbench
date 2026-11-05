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
    """One message, mail, note or meeting. `id` travels as metadata to a store, never inside the text."""

    id: str
    kind: str
    text: str
    time: str
    source: str | None = None
    thread: str | None = None
    author: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


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


class Hit(Frozen):
    record_ids: tuple[str, ...]
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
