"""Ours, unrestricted: the agent searches memory itself, as often as it likes, one strategy prompt for every engine.

His design hands the agent one frozen top-5 retrieval. Here the agent gets a search tool and a written strategy:
several searches, whole records, dates and which version is active, the project's exact name. The strategy is the
same text for every engine; only the line naming the tool differs. It was tuned on the dev set (rules-trial-dev,
another task, other values, another seed) and frozen before the first test session.

Tools: memo is its own CLI with its own skill (`memo skill show`), which counts as part of the product. The archive is
the 36 sources as files the agent greps. Every other engine gets a thin `search` command that calls the engine's own
search through a local proxy, so no key reaches the jail.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from wcatbench.agents.hermes import Tools, tool_activity
from wcatbench.core.types import Outcome
from wcatbench.pipeline import memory_bank
from wcatbench.pipeline.dialogue import MEMO_CLI, NODE
from wcatbench.pipeline.rules_trial import Round
from wcatbench.scoring import staged
from wcatbench.stores.memo import MemoStore

PROXY_PORT = 18990
TOOLS_ROOT = Path(os.environ.get("WCATBENCH_TOOLS_ROOT", "/var/tmp/wcat-dapi/agent-tools"))  # nosec B108
MAX_K = 20
STRATEGY_VERSION = "1"

# variant: (tool, store adapter or None, the e1 variant whose stored text it shares)
VARIANTS: dict[str, tuple[str, str | None, str | None]] = {
    "u-archive": ("archive", None, None),
    "u-memory-bank": ("memory-bank", None, None),
    "u-memo": ("memo", "memo", "memo"),
    "u-files-top5": ("proxy", "fts", "files-top5"),
    "u-agentmemory": ("proxy", "agentmemory", "agentmemory"),
    "u-mem0-oss": ("proxy", "mem0-oss", "mem0-oss"),
    "u-hindsight-slim": ("proxy", "hindsight-slim", "hindsight-slim"),
    "u-openviking-evo-off": ("proxy", "openviking", "openviking-evo-off"),
    "u-openviking-evo-on": ("proxy", "openviking-evo", "openviking-evo-on"),
}

STRATEGY = """Как работать с памятью проекта:
1. Сначала выпиши для себя, какие значения нужны задаче. Ищи каждое отдельно, разными словами: по теме, по имени \
параметра, по-русски и по-английски. Одного поиска мало.
2. Читай найденную запись целиком, а не только фрагмент.
3. У каждой записи есть дата, автор и проект. Значение годится, только если запись про этот проект: название должно \
совпасть точно, похожий проект — другой проект.
4. Решения меняются. Для каждого значения найди все записи на эту тему и возьми самую позднюю, которая его \
устанавливает. Ищи слова вроде «поправка», «теперь», «отменяем», «отзываем», «больше не»: отмена или отзыв тоже \
решение.
5. Обсуждение без решения — не решение. Если для значения нет действующего решения этого проекта, это UNKNOWN.
6. Не останавливайся на первом совпадении: перед тем как писать код, проверь каждое значение ещё одним поиском."""

TOOL_LINE = {
    "archive": "Память проекта: папка `archive/`, один файл на запись. Ищи в ней сам (`grep -ri`, `rg`), читай файлы.",
    "memory-bank": (
        "Память проекта: папка `memory-bank/` (Memory Bank), как с ней работать, сказано в `AGENTS.md`. Ищи в ней сам "
        "(`grep -ri`, `rg`), читай файлы."
    ),
    "memo": (
        "Память проекта: команда `memo` (WireCat memo). Как ей пользоваться, написано в `memo skill show`: прочитай "
        "это в начале. Ищи через `memo search all '<запрос>' --json`, запись целиком — `memo notes show <ref>`. Память "
        "только для чтения: ничего в неё не пиши."
    ),
    "proxy": (
        "Память проекта: команда `search '<запрос>' [--k N]` печатает до N найденных записей (по умолчанию 10, "
        f"не больше {MAX_K}), каждую целиком. Других способов прочитать память нет."
    ),
}

SEARCH_TOOL = f'''#!/usr/bin/python3 -I
"""search '<query>' [--k N]: the project memory's own search, through the benchmark's local proxy."""
import json
import sys
import urllib.parse
import urllib.request

args = sys.argv[1:]
k = 10
if "--k" in args:
    at = args.index("--k")
    k = int(args[at + 1])
    del args[at:at + 2]
query = " ".join(args)
url = "http://127.0.0.1:{PROXY_PORT}/search?" + urllib.parse.urlencode({{"q": query, "k": k}})
with urllib.request.urlopen(url, timeout=300) as reply:
    hits = json.loads(reply.read())
for hit in hits:
    print(f"### Результат {{hit['rank']}}\\n{{hit['text']}}\\n")
if not hits:
    print("ничего не найдено")
'''


class Proxy:
    """A local HTTP search over one open store; each query is written to the current session's log."""

    def __init__(self, store: Any) -> None:
        self.store = store
        self.log: Path | None = None
        self.lock = threading.Lock()
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                params = parse_qs(urlparse(self.path).query)
                query = params.get("q", [""])[0]
                k = max(1, min(MAX_K, int(params.get("k", ["10"])[0])))
                with proxy.lock:
                    hits = proxy.store.search(query, k)
                rows = [{"rank": n, "text": hit.text or "", "keys": list(hit.keys)} for n, hit in enumerate(hits, 1)]
                if proxy.log is not None:
                    with proxy.log.open("a") as lines:
                        lines.write(json.dumps({"q": query, "k": k, "hits": rows}, ensure_ascii=False) + "\n")
                body = json.dumps([{"rank": row["rank"], "text": row["text"]} for row in rows], ensure_ascii=False)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body.encode())

            def log_message(self, *_: Any) -> None:
                return None

        self.server = ThreadingHTTPServer(("127.0.0.1", PROXY_PORT), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> Proxy:
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.server.shutdown()
        self.server.server_close()


class UnrestrictedRound(Round):
    proxy: Proxy | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.variants = tuple(VARIANTS)
        # Outside the run folder: the agent sees this path, and a path into the runs counts as a leak.
        self.tools_dir = TOOLS_ROOT / self.run.name
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        tool = self.tools_dir / "search"
        tool.write_text(SEARCH_TOOL)
        tool.chmod(0o755)

    def contexts(self, variant: str) -> dict[str, dict[str, Any]]:
        return {qid: {"text": None, "tokens": 0, "hits": []} for qid in self.questions}

    def memo_copy(self) -> MemoStore:
        """A copy of the e1 memo build, at the build's own path inside the jail, so its folder paths still hold."""
        store: MemoStore = self.open_store("u-memo", "memo")
        copy = self.run / "unrestricted-memo"
        if not copy.exists():
            shutil.copytree(store.base, copy, symlinks=True)
        return store

    def tools(self, variant: str) -> Tools | None:
        tool, _, _ = VARIANTS[variant]
        if tool == "proxy":
            return Tools(read_only=(self.tools_dir,), env={"PATH": f"{self.tools_dir}:/usr/local/bin:/usr/bin:/bin"})
        if tool == "memo":
            store = self.memo_copy()
            env = {name: value for name, value in store.env().items() if name not in ("PATH", "HOME")}
            env["PATH"] = f"{MEMO_CLI}/node_modules/.bin:{NODE}/bin:/usr/local/bin:/usr/bin:/bin"
            return Tools(
                read_only=(NODE, MEMO_CLI), writable=((self.run / "unrestricted-memo", str(store.base)),), env=env
            )
        return None

    def prompt(self, variant: str, qid: str, into: Path) -> str:
        shutil.copytree(self.dataset / "project", into)
        tool, _, _ = VARIANTS[variant]
        if tool == "memory-bank":
            memory_bank.install(into, self.records)
        if tool == "archive":
            (into / "archive").mkdir()
            for record in self.records:
                (into / "archive" / f"{record.key}.md").write_text(record.text + "\n")
        task = self.questions[qid].text
        (into / "TASK.md").write_text(task)
        return (
            "Ты работаешь в папке /work: это репозиторий проекта «Сокол». Задача ниже, она же в TASK.md.\n"
            f"{TOOL_LINE[tool]}\n\n{STRATEGY}\n\n{task}\nКогда закончишь, коротко напиши, что сделал."
        )

    def session(self, variant: str, qid: str, application: int) -> dict[str, Any]:
        trial = self.run / "trials" / variant / f"{qid}.a{application}"
        done_file = trial / "result.json"
        if done_file.exists():
            return dict(json.loads(done_file.read_text()))
        if trial.exists():
            shutil.move(str(trial), str(trial.with_name(f"{trial.name}.aborted-{int(datetime.now(UTC).timestamp())}")))
        trial.mkdir(parents=True)
        workspace = trial / "workspace"
        prompt = self.prompt(variant, qid, workspace)
        (trial / "prompt.txt").write_text(prompt)
        if self.proxy is not None:
            self.proxy.log = trial / "searches.jsonl"
        reply = self.agent.session(prompt, workspace, trial, self.tools(variant))
        (trial / "stdout.txt").write_text(reply.stdout)
        (trial / "stderr.txt").write_text(reply.stderr)
        activity = tool_activity(trial / "hermes-home-after")
        returned = str(activity["outputs"])
        if (trial / "searches.jsonl").exists():
            returned += "\n".join(
                hit["text"]
                for line in (trial / "searches.jsonl").read_text().splitlines()
                for hit in json.loads(line)["hits"]
            )
        leaks = staged.leaked(reply.transcript + reply.stdout)
        task = qid.split(".")[0]
        statuses = self.hidden(trial, workspace, task) if reply.outcome is Outcome.COMPLETED else {}
        valid = not leaks and reply.outcome is Outcome.COMPLETED
        _, _, shared = VARIANTS[variant]
        stored_path = self.run / "stored" / f"{shared}.txt"
        stored = stored_path.read_text() if shared and stored_path.exists() else None
        checks = [check for check in self.checks if check["task"] == task]
        rows = staged.rows(checks, stored, returned or None, statuses, valid)
        result = {
            "variant": variant,
            "label": "ours, unrestricted",
            "strategy_version": STRATEGY_VERSION,
            "question": qid,
            "application": application,
            "outcome": reply.outcome.value,
            "leaks": leaks,
            "seconds": round(reply.seconds, 1),
            "usage": reply.usage.model_dump(),
            "tool_calls": activity["tool_calls"],
            "by_tool": activity["by_tool"],
            "searches": len((trial / "searches.jsonl").read_text().splitlines())
            if (trial / "searches.jsonl").exists()
            else None,
            "context_tokens": 0,
            "rows": rows,
            "finished": datetime.now(UTC).isoformat(),
        }
        done_file.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    def session_result(self, variant: str, qid: str, application: int) -> dict[str, Any] | None:
        path = self.run / "trials" / variant / f"{qid}.a{application}" / "result.json"
        return dict(json.loads(path.read_text())) if path.exists() else None

    def go(self, variant: str, design: str = "his") -> None:
        tool, name, _ = VARIANTS[variant]
        if tool != "proxy":
            super().go(variant, design)
            return
        store = self.open_store(variant, name or "")
        try:
            with Proxy(store) as proxy:
                self.proxy = proxy
                super().go(variant, design)
        finally:
            self.proxy = None
            store.close()
