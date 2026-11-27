"""Hermes Agent, one fresh session per task, inside bubblewrap (core.jail).

The sign-in stays in one HERMES_HOME that the owner signed into by device code (NEED-2155): it is never copied.
Everything else a session leaves there (its state database, session dumps, logs, skills, memories) is moved into the
trial folder after the session, so the next session starts with no history and the transcript is kept for the scan.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404
import time
from dataclasses import dataclass, field
from pathlib import Path

from wcatbench.core.errors import PermanentError
from wcatbench.core.jail import Jail
from wcatbench.core.types import Outcome, Usage

# Hermes v0.23.4 cloned there with its own venv; the home is the one bin/hermes-codex-signin signed in.
HERMES_ROOT = Path(os.environ.get("WCATBENCH_HERMES_ROOT", "/var/tmp/wcat-dapi/hermes-agent"))  # nosec B108
HERMES_HOME = Path(os.environ.get("WCATBENCH_HERMES_HOME", "/var/tmp/wcat-dapi/hermes-home"))  # nosec B108
KEEP = frozenset(
    {
        "auth.json",
        "auth.lock",
        "config.yaml",
        "SOUL.md",
        "install_id",
        ".install_id.lock",
        "installs",
        "cache",
        "models_dev_cache.json",
        "models_dev_cache.etag",
        "log_hash_salt",
        ".codex_gpt55_autoraise_notice",
    }
)
CONFIG = """model:
  default: {model}
  provider: openai-codex
memory:
  memory_enabled: false
  user_profile_enabled: false
"""


@dataclass(frozen=True)
class SessionResult:
    outcome: Outcome
    seconds: float
    usage: Usage
    stdout: str
    stderr: str
    transcript: str
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Tools:
    """What a session may use beyond its workspace: a program's folders (read-only) and its own store (writable)."""

    read_only: tuple[Path, ...] = ()
    writable: tuple[tuple[Path, str], ...] = ()
    env: dict[str, str] = field(default_factory=dict)


def interpreter_root(python: Path) -> Path:
    """The venv's base interpreter lives outside it, so the jail binds its install folder read-only."""
    real = python.resolve()
    return real.parent.parent


class HermesAgent:
    name = "hermes"

    def __init__(
        self,
        model: str,
        toolsets: str = "file,terminal",
        timeout: int = 900,
        root: Path = HERMES_ROOT,
        home: Path = HERMES_HOME,
    ) -> None:
        self.model, self.toolsets, self.timeout, self.root, self.home = model, toolsets, timeout, root, home
        self.python = root / "venv" / "bin" / "python"

    def version(self) -> str:
        done = subprocess.run(  # noqa: S603  # nosec B603
            ["/usr/bin/git", "-C", str(self.root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        return f"hermes-agent v0.23.4 {done.stdout.strip()}"

    def prepare(self) -> None:
        if not (self.home / "auth.json").exists():
            raise PermanentError(f"{self.home} has no sign-in: the owner runs bin/hermes-codex-signin first")
        stray = sorted(entry.name for entry in self.home.iterdir() if entry.name not in KEEP)
        if stray:
            raise PermanentError(f"{self.home} holds files from an earlier session: {', '.join(stray)}")
        (self.home / "config.yaml").write_text(CONFIG.format(model=self.model))

    def jail(self, workspace: Path, out: Path, tools: Tools | None = None) -> Jail:
        tools = tools or Tools()
        return Jail(
            read_only=(interpreter_root(self.python), self.root, *tools.read_only),
            writable=((workspace, "/work"), (out, "/out"), (self.home, str(self.home)), *tools.writable),
            env={
                "HERMES_HOME": str(self.home),
                "CODEX_HOME": "/tmp/codex-empty",  # nosec B108
                "PYTHONDONTWRITEBYTECODE": "1",
                **tools.env,
            },
        )

    def session(self, prompt: str, workspace: Path, trial: Path, tools: Tools | None = None) -> SessionResult:
        self.prepare()
        out = trial / "out"
        out.mkdir(parents=True, exist_ok=True)
        argv = [
            str(self.python),
            str(self.root / "hermes"),
            "-z",
            prompt,
            "--usage-file",
            "/out/usage.json",
            "-m",
            self.model,
            "--provider",
            "openai-codex",
            "-t",
            self.toolsets,
            "--yolo",
        ]
        started = time.perf_counter()
        outcome = Outcome.COMPLETED
        try:
            done = subprocess.run(  # noqa: S603  # nosec B603
                self.jail(workspace, out, tools).command(argv),
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
            stdout, stderr, code = done.stdout, done.stderr, done.returncode
        except subprocess.TimeoutExpired as error:
            stdout = error.stdout.decode() if isinstance(error.stdout, bytes) else (error.stdout or "")
            stderr, code, outcome = f"timeout after {self.timeout}s", None, Outcome.TIMEOUT
        seconds = time.perf_counter() - started
        usage_raw = json.loads((out / "usage.json").read_text()) if (out / "usage.json").exists() else {}
        if outcome is Outcome.COMPLETED and (code != 0 or usage_raw.get("failed")):
            outcome = Outcome.ERROR
        after = trial / "hermes-home-after"
        self.collect(after)
        usage = Usage(
            input_tokens=int(usage_raw.get("input_tokens") or 0),
            output_tokens=int(usage_raw.get("output_tokens") or 0),
            cache_read_tokens=int(usage_raw.get("cache_read_tokens") or 0),
            source="agent-files" if usage_raw else "none",
        )
        return SessionResult(
            outcome=outcome,
            seconds=seconds,
            usage=usage,
            stdout=stdout,
            stderr=stderr,
            transcript=transcript_text(after),
            details={"exit": code, "usage": usage_raw, "tools": tool_activity(after)},
        )

    def collect(self, into: Path) -> None:
        into.mkdir(parents=True, exist_ok=True)
        for entry in list(self.home.iterdir()):
            if entry.name not in KEEP:
                shutil.move(str(entry), str(into / entry.name))


def transcript_text(after: Path) -> str:
    """Every message and tool call of the session, as one text, for the scan."""
    import sqlite3

    parts: list[str] = []
    database = after / "state.db"
    if database.exists():
        db = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            rows = db.execute("SELECT coalesce(content, ''), coalesce(tool_calls, '') FROM messages").fetchall()
        finally:
            db.close()
        parts += [f"{content}\n{calls}" for content, calls in rows]
    for dump in sorted((after / "sessions").glob("*.json")) if (after / "sessions").exists() else []:
        parts.append(dump.read_text(errors="replace"))
    return "\n".join(parts)


def tool_activity(after: Path) -> dict[str, object]:
    """How many tool calls the session made, by tool, and the text the tools returned (the retrieved stage)."""
    import sqlite3

    database = after / "state.db"
    if not database.exists():
        return {"tool_calls": 0, "by_tool": {}, "outputs": ""}
    db = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        calls = db.execute("SELECT coalesce(tool_calls, '') FROM messages WHERE role = 'assistant'").fetchall()
        outputs = db.execute("SELECT coalesce(content, '') FROM messages WHERE role = 'tool'").fetchall()
    finally:
        db.close()
    by_tool: dict[str, int] = {}
    for (raw,) in calls:
        try:
            items = json.loads(raw) if raw else []
        except json.JSONDecodeError:
            items = []
        for item in items if isinstance(items, list) else []:
            name = str((item.get("function") or {}).get("name") or item.get("name") or "?")
            by_tool[name] = by_tool.get(name, 0) + 1
    return {
        "tool_calls": sum(by_tool.values()),
        "by_tool": by_tool,
        "outputs": "\n".join(text for (text,) in outputs),
    }
