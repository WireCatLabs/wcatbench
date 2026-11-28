"""Claude Code headless (`claude -p`) in the same bubblewrap jail as Hermes, on the owner's subscription token.

The token is a long-lived subscription token the owner made with `claude setup-token` and stored in the keyring
(service claude, account benchmark). It is read in-process here and handed to the jail's environment only; it is
never printed, and a transcript that carries it is redacted before it is written. Inside the jail HOME is empty and
the config folder is a fresh one per session, so Claude Code sees no CLAUDE.md, no settings, no MCP server and no
memory of the owner's; `--strict-mcp-config` and `--setting-sources ""` say the same on the command line.
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404
import time
from pathlib import Path
from typing import Any

from wcatbench.agents.hermes import SessionResult, Tools
from wcatbench.core.errors import PermanentError
from wcatbench.core.jail import Jail
from wcatbench.core.types import Outcome, Usage

BINARY = Path(os.environ.get("WCATBENCH_CLAUDE_BIN", str(Path.home() / ".local/share/claude/versions/2.1.332")))
KEYRING = ("service", "claude", "account", "benchmark")


def token() -> str:
    done = subprocess.run(  # noqa: S603  # nosec B603
        ["/usr/bin/secret-tool", "lookup", *KEYRING], capture_output=True, text=True, check=False
    )
    value = done.stdout.strip()
    if not value:
        raise PermanentError("no Claude token in the keyring under service claude, account benchmark")
    return value


def activity(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_tool: dict[str, int] = {}
    outputs: list[str] = []
    for event in events:
        for block in (event.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            if event.get("type") == "assistant" and block.get("type") == "tool_use":
                by_tool[str(block.get("name"))] = by_tool.get(str(block.get("name")), 0) + 1
            if event.get("type") == "user" and block.get("type") == "tool_result":
                content = block.get("content")
                if isinstance(content, list):
                    outputs += [str(part.get("text", "")) for part in content if isinstance(part, dict)]
                else:
                    outputs.append(str(content or ""))
    return {"tool_calls": sum(by_tool.values()), "by_tool": by_tool, "outputs": "\n".join(outputs)}


class ClaudeAgent:
    name = "claude"

    def __init__(self, model: str = "opus", timeout: int = 900, binary: Path = BINARY) -> None:
        self.model, self.timeout, self.binary = model, timeout, binary

    def version(self) -> str:
        return f"claude-code {self.binary.name}"

    def jail(self, workspace: Path, out: Path, tools: Tools | None = None, secret: str = "") -> Jail:  # nosec B107
        tools = tools or Tools()
        config = out / "claude-config"
        config.mkdir(parents=True, exist_ok=True)
        env = {
            "HOME": "/home/agent",
            "CLAUDE_CONFIG_DIR": "/out/claude-config",
            "DISABLE_AUTOUPDATER": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_TELEMETRY": "1",
            "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
            "DBUS_SESSION_BUS_ADDRESS": "disabled:",
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            **tools.env,
        }
        # The jail clears the environment; this drops an API key a tool's env might carry, so nothing bills the API.
        env = {key: value for key, value in env.items() if not key.startswith("ANTHROPIC_")}
        if secret:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = secret
        return Jail(
            read_only=(self.binary, *tools.read_only),
            writable=((workspace, "/work"), (out, "/out"), *tools.writable),
            env=env,
        )

    def argv(self, prompt: str) -> list[str]:
        return [
            str(self.binary),
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--model",
            self.model,
            "--strict-mcp-config",
            "--setting-sources",
            "",
            "--dangerously-skip-permissions",
            "--no-session-persistence",
        ]

    def session(self, prompt: str, workspace: Path, trial: Path, tools: Tools | None = None) -> SessionResult:
        out = trial / "out"
        out.mkdir(parents=True, exist_ok=True)
        secret = token()
        started = time.perf_counter()
        outcome = Outcome.COMPLETED
        try:
            done = subprocess.run(  # noqa: S603  # nosec B603
                self.jail(workspace, out, tools, secret).command(self.argv(prompt)),
                stdin=subprocess.DEVNULL,
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
        stdout, stderr = stdout.replace(secret, "<token>"), stderr.replace(secret, "<token>")
        events: list[dict[str, Any]] = []
        for line in stdout.splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        (trial / "events.jsonl").write_text(stdout)
        result: dict[str, Any] = next((event for event in reversed(events) if event.get("type") == "result"), {})
        if outcome is Outcome.COMPLETED and (code != 0 or result.get("is_error") or not result):
            outcome = Outcome.ERROR
        usage = result.get("usage") or {}
        tools_used = activity(events)
        return SessionResult(
            outcome=outcome,
            seconds=seconds,
            usage=Usage(
                input_tokens=int(usage.get("input_tokens") or 0)
                + int(usage.get("cache_creation_input_tokens") or 0)
                + int(usage.get("cache_read_input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
                source="agent-files" if usage else "none",
            ),
            stdout=str(result.get("result") or ""),
            stderr=stderr,
            transcript=stdout,
            details={
                "exit": code,
                "tools": tools_used,
                "init": next((event for event in events if event.get("subtype") == "init"), {}),
                "cost_usd": result.get("total_cost_usd"),
                "turns": result.get("num_turns"),
            },
        )
