"""Logging: loguru with redaction in both formatters, one JSON object per line, and run context on every line.

Ported from an earlier project of ours. The context here is a benchmark's: the run, the setup, the
trial and the store a line belongs to.

**Never rebind `logger`.** It is a facade over shared state: `add()` and `remove()` change the sinks every module's
reference emits into. `logger.patch()` returns a new object, and modules holding the old one would emit into sinks
configured for the new.
"""

from __future__ import annotations

import inspect
import json
import logging
import sys
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

from loguru import logger

from wcatbench.observability.redaction import redact_mapping, scrub_secrets

if TYPE_CHECKING:
    from loguru import Message, Record

#: A reader who greps for this must land on why the payload is missing, not on the failure being logged.
REDACTION_FAILED = "[log line withheld: redaction failed]"

#: A library's INFO is chatter (httpx narrates every request). WARNING and above is what a person acts on.
STDLIB_LOG_LEVEL = "WARNING"

CONTEXT: dict[str, ContextVar[str | None]] = {
    name: ContextVar(name, default=None) for name in ("run_id", "setup", "trial_id", "store")
}


def _context() -> dict[str, str | None]:
    return {name: var.get() for name, var in CONTEXT.items()}


def serialize_record(record: dict[str, Any]) -> str:
    """One log line as one JSON object, redacted. Fails closed: never the raw payload."""
    try:
        subset: dict[str, Any] = {
            "timestamp": record["time"].isoformat(),
            "level": record["level"].name,
            "logger": record["name"],
            "message": record["message"],
            **{key: value for key, value in _context().items() if value is not None},
        }
        if record.get("exception"):
            error = record["exception"]
            subset["exception"] = {
                "type": error.type.__name__,
                "value": str(error.value),
                "traceback": "".join(traceback.format_exception(error.type, error.value, error.traceback)),
            }
        if record.get("extra"):
            subset["extra"] = redact_mapping(record["extra"])
        return scrub_secrets(json.dumps(subset, default=str, ensure_ascii=False))
    except Exception as error:  # noqa: BLE001 - fail closed, never emit the raw payload
        return _withheld(record, error)


def _withheld(record: dict[str, Any], error: Exception) -> str:
    """What and when, never the message: if scrubbing failed, the message is the string that was not scrubbed."""
    try:
        return json.dumps(
            {
                "timestamp": record["time"].isoformat(),
                "level": record["level"].name,
                "logger": record["name"],
                "message": REDACTION_FAILED,
                "redaction_error": type(error).__name__,
            }
        )
    except Exception:  # noqa: BLE001 - the record itself is unreadable; still emit something
        return json.dumps({"level": "ERROR", "message": REDACTION_FAILED})


def format_record_console(record: Record) -> str:
    try:
        return _format_record_console(record)
    except Exception:  # noqa: BLE001 - a console is still a sink; fail closed here too
        return f"<level>{REDACTION_FAILED}</level>\n"


def _format_record_console(record: Record) -> str:
    # This returns a loguru format string, so every brace that is not ours is escaped, after redaction.
    parts = [
        f"<green>{record['time'].strftime('%H:%M:%S.%f')[:-3]}</green>",
        f"<level>{record['level'].name:<7}</level>",
        f"<level>{_escape(record['message'])}</level>",
    ]
    parts += [f"<cyan>{key}={_escape(value)}</cyan>" for key, value in _context().items() if value is not None]
    for key, value in redact_mapping(record.get("extra") or {}).items():
        parts.append(f"<magenta>{key}</magenta>=<yellow>{_escape(str(value))}</yellow>")
    return scrub_secrets(" | ".join(parts)) + "\n{exception}"


def _escape(text: str) -> str:
    return text.replace("{", "{{").replace("}", "}}").replace("<", r"\<")


def _json_sink(stream: TextIO) -> Any:
    def write(message: Message) -> None:
        stream.write(serialize_record(dict(message.record)) + "\n")
        stream.flush()

    return write


def _json_file_sink(path: Path) -> Any:
    # Opened per line: a killed run keeps every line, and no handle outlives the run.
    def write(message: Message) -> None:
        with path.open("a", encoding="utf-8") as out:
            out.write(serialize_record(dict(message.record)) + "\n")

    return write


class InterceptHandler(logging.Handler):
    """Forward standard-library records into loguru, so a library's warnings get the same redaction and context."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        # inspect.currentframe, not logging.currentframe: the latter lands back inside the logging module.
        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1
        # bind, not keyword arguments: loguru would .format() a third party's already interpolated message.
        logger.bind(stdlib_logger=record.name).opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logging(fmt: str = "console", level: str = "INFO") -> None:
    """Logs go to stderr, so a command's stdout stays clean for its own output (`--json`)."""
    logger.remove()
    if fmt == "json":
        logger.add(_json_sink(sys.stderr), format="{message}", level=level, backtrace=False, diagnose=False)
    else:
        logger.add(sys.stderr, format=format_record_console, level=level, colorize=True, diagnose=False)
    logging.basicConfig(handlers=[InterceptHandler()], level=STDLIB_LOG_LEVEL, force=True)


def add_events_file(path: Path) -> int:
    """Every line of a run also goes to its events.jsonl, at DEBUG, whatever the console shows. Returns the sink id."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return logger.add(_json_file_sink(path), format="{message}", level="DEBUG", backtrace=False, diagnose=False)


@contextmanager
def log_context(**values: str) -> Iterator[None]:
    """Bind run context to every line inside, and restore what was bound before (tokens, so nesting is safe)."""
    unknown = set(values) - set(CONTEXT)
    if unknown:
        raise ValueError(f"unknown log context: {sorted(unknown)}")
    tokens = {name: CONTEXT[name].set(value) for name, value in values.items()}
    try:
        yield
    finally:
        for name, token in tokens.items():
            CONTEXT[name].reset(token)
