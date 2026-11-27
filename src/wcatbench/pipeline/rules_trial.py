"""Run the rules-trial round: frozen contexts per variant, Hermes sessions in a jail, hidden checks, staged scores.

Layout under the run folder:
  contexts/<variant>/<question>.json   the frozen retrieval: hits, the text given to the agent, its tokens
  stored/<variant>.txt                 what the store holds, as text, for the stored stage
  trials/<variant>/<question>.a<n>/    workspace, Hermes output, the moved Hermes files, hidden results, rows
  status.csv                           one row per session, flushed after each
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess  # nosec B404
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import tiktoken
from loguru import logger

from wcatbench.agents.hermes import tool_activity
from wcatbench.core import dataset_files, registry
from wcatbench.core.jail import Jail
from wcatbench.core.types import Outcome, Question, Record
from wcatbench.pipeline import memory_bank
from wcatbench.scoring import staged

K = 5
MAX_TOKENS = 2000
ENCODING = "o200k_base"

# variant id: (kind, store adapter name or file name)
VARIANTS: dict[str, tuple[str, str | None]] = {
    "none": ("none", None),
    "files-his": ("file", "his.md"),
    "files-history": ("file", "history.md"),
    "archive-in-workspace": ("archive", None),
    "memory-bank": ("memory-bank", None),
    "memory-bank-files": ("memory-bank-files", None),
    "files-top5": ("store", "fts"),
    "memo": ("store", "memo"),
    "agentmemory": ("store", "agentmemory"),
    "mem0-oss": ("store", "mem0-oss"),
    "hindsight-slim": ("store", "hindsight-slim"),
    "openviking-evo-off": ("store", "openviking"),
    "openviking-evo-on": ("store", "openviking-evo"),
}

NOTE = {
    "context": "Опыт проекта, найденный в памяти, лежит в `memory/context.md`. Другой памяти у тебя нет.",
    "archive": "Архив переписки и решений лежит в папке `archive/`, одна запись в файле.",
    "none": "Опыта проекта у тебя нет: ни памяти, ни архива.",
    "memory-bank": (
        "Память проекта лежит в папке `memory-bank/` (Memory Bank), как с ней работать, сказано в `AGENTS.md`."
    ),
}


def query_of(question: Question) -> str:
    """The task's first paragraph: what a user would type, without the list of names."""
    return question.text.split("\n\n", 1)[0]


def cut(hits: list[dict[str, Any]], limit: int = MAX_TOKENS) -> tuple[str, int, list[dict[str, Any]]]:
    """Whole hits in rank order while they fit, the crossing one cut to the tokens left (one counter for all)."""
    encoding = tiktoken.get_encoding(ENCODING)
    parts: list[str] = []
    used, kept = 0, []
    for rank, hit in enumerate(hits[:K], start=1):
        block = f"### Результат {rank}\n{hit['text'].strip()}\n\n"
        tokens = encoding.encode(block)
        if used + len(tokens) > limit:
            left = limit - used
            if left > 20:
                parts.append(encoding.decode(tokens[:left]))
                kept.append({**hit, "cut": True})
                used = limit
            break
        parts.append(block)
        kept.append(hit)
        used += len(tokens)
    return "".join(parts), used, kept


def run_hidden(dataset: Path, trial: Path, workspace: Path, checks: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """The hidden checks of one module, run by the dataset's runner in a jail with no network."""
    hidden = trial / "hidden"
    hidden.mkdir(exist_ok=True)
    (hidden / "checks.json").write_text(json.dumps(checks, ensure_ascii=False))
    shutil.copy(dataset / "runner.py", hidden / "runner.py")
    jail = Jail(read_only=(workspace, hidden), network=False, workdir="/tmp")  # nosec B108
    argv = [
        "/usr/bin/python3",
        "-I",
        str(hidden / "runner.py"),
        str(workspace),
        checks[0]["module"],
        str(hidden / "checks.json"),
    ]
    done = subprocess.run(jail.command(argv), capture_output=True, text=True, timeout=120, check=False)  # noqa: S603  # nosec B603
    (hidden / "stderr.txt").write_text(done.stderr)
    try:
        return dict(json.loads(done.stdout.strip().splitlines()[-1]))
    except (json.JSONDecodeError, IndexError):
        return {}


@dataclass
class Round:
    dataset: Path
    run: Path
    builds: Path
    agent: Any
    applications: int = 2
    variants: tuple[str, ...] = tuple(VARIANTS)

    def __post_init__(self) -> None:
        self.records: list[Record] = dataset_files.records(self.dataset)
        self.by_key = {record.key: record for record in self.records}
        self.questions = {question.id: question for question in dataset_files.questions(self.dataset)}
        self.checks: list[dict[str, Any]] = json.loads((self.dataset / "checks.json").read_text())
        self.run.mkdir(parents=True, exist_ok=True)

    def source_of(self, key: str) -> str:
        record = self.by_key.get(key)
        return record.id if record else key

    def contexts(self, variant: str) -> dict[str, dict[str, Any]]:
        folder = self.run / "contexts" / variant
        if folder.exists() and len(list(folder.glob("*.json"))) == len(self.questions):
            return {path.stem: json.loads(path.read_text()) for path in folder.glob("*.json")}
        folder.mkdir(parents=True, exist_ok=True)
        kind, name = VARIANTS[variant]
        result: dict[str, dict[str, Any]] = {}
        if kind == "store":
            store = self.open_store(variant, name or "")
            stored = self.stored_text(store)
            (self.run / "stored").mkdir(exist_ok=True)
            (self.run / "stored" / f"{variant}.txt").write_text(stored)
        for qid, question in self.questions.items():
            if kind in ("none", "archive", "memory-bank"):
                entry: dict[str, Any] = {"text": None, "tokens": 0, "hits": []}
            elif kind == "memory-bank-files":
                text = memory_bank.whole_text(self.records)
                tokens = len(tiktoken.get_encoding(ENCODING).encode(text))
                entry = {"text": text, "tokens": tokens, "hits": [], "whole_file": "memory-bank layout"}
            elif kind == "file":
                text = (self.dataset / "files" / (name or "")).read_text()
                tokens = len(tiktoken.get_encoding(ENCODING).encode(text))
                entry = {"text": text, "tokens": tokens, "hits": [], "whole_file": name}
            else:
                started = time.perf_counter()
                hits = store.search(query_of(question), K)
                seconds = time.perf_counter() - started
                rows = [
                    {"sources": [self.source_of(key) for key in hit.keys], "text": hit.text or "", "score": hit.score}
                    for hit in hits
                ]
                text, tokens, kept = cut(rows)
                entry = {
                    "text": text,
                    "tokens": tokens,
                    "hits": kept,
                    "query": query_of(question),
                    "search_seconds": seconds,
                }
            (folder / f"{qid}.json").write_text(json.dumps(entry, ensure_ascii=False, indent=2))
            result[qid] = entry
        if kind == "store":
            store.close()
        return result

    def open_store(self, variant: str, name: str) -> Any:
        store = registry.load("stores", name)()
        workdir = self.builds / name
        store.open("rules-trial", workdir, datetime.now(UTC))
        held = store.held()
        missing = [record for record in self.records if record.key not in held]
        if missing:
            receipt = store.ingest(missing)
            ledger = workdir / "ledger.jsonl"
            with ledger.open("a") as lines:
                lines.write(
                    json.dumps(
                        {
                            "sent": len(receipt.sent),
                            "refused": receipt.refused,
                            "seconds": receipt.seconds,
                            "at": datetime.now(UTC).isoformat(),
                        }
                    )
                    + "\n"
                )
        for _ in range(360):
            if store.settled(store.held()):
                break
            time.sleep(10)
        return store

    def stored_text(self, store: Any) -> str:
        contents: Callable[[], list[str]] | None = getattr(store, "contents", None)
        if contents is not None:
            return "\n\n".join(contents())
        return "\n\n".join(self.by_key[key].text for key in store.held() if key in self.by_key)

    def workspace(self, variant: str, qid: str, entry: dict[str, Any], into: Path) -> str:
        shutil.copytree(self.dataset / "project", into)
        kind, _ = VARIANTS[variant]
        if entry.get("text"):
            (into / "memory").mkdir()
            (into / "memory" / "context.md").write_text(entry["text"])
            note = NOTE["context"]
        elif kind == "memory-bank":
            memory_bank.install(into, self.records)
            note = NOTE["memory-bank"]
        elif kind == "archive":
            (into / "archive").mkdir()
            for record in self.records:
                (into / "archive" / f"{record.key}.md").write_text(record.text + "\n")
            note = NOTE["archive"]
        else:
            note = NOTE["none"]
        task = self.questions[qid].text
        (into / "TASK.md").write_text(task)
        return (
            f"Ты работаешь в папке /work: это репозиторий проекта «Сокол». Задача ниже, она же в TASK.md.\n"
            f"{note}\n\n{task}\nКогда закончишь, коротко напиши, что сделал."
        )

    def hidden(self, trial: Path, workspace: Path, task: str) -> dict[str, dict[str, str]]:
        return run_hidden(self.dataset, trial, workspace, [check for check in self.checks if check["task"] == task])

    def session(self, variant: str, qid: str, application: int) -> dict[str, Any]:
        trial = self.run / "trials" / variant / f"{qid}.a{application}"
        done_file = trial / "result.json"
        if done_file.exists():
            return dict(json.loads(done_file.read_text()))
        if trial.exists():
            shutil.move(str(trial), str(trial.with_name(f"{trial.name}.aborted-{int(time.time())}")))
        trial.mkdir(parents=True)
        entry = self.contexts(variant)[qid]
        workspace = trial / "workspace"
        prompt = self.workspace(variant, qid, entry, workspace)
        reply = self.agent.session(prompt, workspace, trial)
        (trial / "stdout.txt").write_text(reply.stdout)
        (trial / "stderr.txt").write_text(reply.stderr)
        leaks = staged.leaked(reply.transcript + reply.stdout)
        task = qid.split(".")[0]
        statuses = self.hidden(trial, workspace, task) if reply.outcome is Outcome.COMPLETED else {}
        valid = not leaks and reply.outcome is Outcome.COMPLETED
        stored_path = self.run / "stored" / f"{variant}.txt"
        stored = stored_path.read_text() if stored_path.exists() else None
        sources = {source for hit in entry.get("hits", []) for source in hit["sources"]} if entry.get("hits") else None
        checks = [check for check in self.checks if check["task"] == task]
        rows = staged.rows(checks, stored, entry.get("text"), statuses, valid, sources)
        result = {
            "variant": variant,
            "question": qid,
            "application": application,
            "outcome": reply.outcome.value,
            "leaks": leaks,
            "seconds": round(reply.seconds, 1),
            "usage": reply.usage.model_dump(),
            "context_tokens": entry.get("tokens", 0),
            "rows": rows,
            "finished": datetime.now(UTC).isoformat(),
        }
        done_file.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    def probe(self) -> dict[str, Any]:
        """No model: a shell in the agent's exact jail tries to reach what it must not see. Proof for the results."""
        folder = self.run / "probe"
        workspace, out = folder / "workspace", folder / "out"
        workspace.mkdir(parents=True, exist_ok=True)
        out.mkdir(exist_ok=True)
        targets = [
            str(Path.home()),
            str(Path.home() / ".hermes"),
            str(Path.home() / ".codex"),
            str(Path.home() / ".local/share/WireCat"),
            str(self.dataset),
            str(self.dataset / "checks.json"),
            str(self.dataset / "key.json"),
            str(self.run),
            str(self.builds),
            str(Path(__file__).parent),
        ]
        script = "; ".join(
            f'if [ -r "{target}" ]; then echo "readable {target}"; else echo "hidden {target}"; fi'
            for target in targets
        )
        script += '; echo "home-tree:"; find /home -maxdepth 4 | head -20; echo "dbus=$DBUS_SESSION_BUS_ADDRESS"'
        jail = self.agent.jail(workspace, out)
        done = subprocess.run(jail.command(["/bin/sh", "-c", script]), capture_output=True, text=True, check=False)  # noqa: S603  # nosec B603
        lines = done.stdout.splitlines()
        result = {
            "command": jail.command(["/bin/sh", "-c", "<probe>"]),
            "output": lines,
            "readable": [line for line in lines if line.startswith("readable ")],
            "at": datetime.now(UTC).isoformat(),
        }
        (folder / "probe.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    def plan(self, variant: str, design: str) -> list[tuple[str, int]]:
        his = [
            (qid, n) for qid in sorted(self.questions) if qid.endswith(".p0") for n in range(1, self.applications + 1)
        ]
        ours = [(qid, 1) for qid in sorted(self.questions) if not qid.endswith(".p0")]
        return {"his": his, "ours": ours, "all": his + ours}[design]

    def go(self, variant: str, design: str = "his") -> None:
        status = self.run / "status.csv"
        logger.info("status file: {}", status)
        new = not status.exists()
        units = self.plan(variant, design)
        with status.open("a", newline="") as handle:
            writer = csv.writer(handle)
            if new:
                writer.writerow(["id", "status", "detail", "time"])
            for index, (qid, application) in enumerate(units, start=1):
                result = self.session(variant, qid, application)
                applied = sum(row.get("applied", False) for row in result["rows"])
                unknown = sum(row.get("unknown_ok", False) for row in result["rows"])
                detail = f"{result['outcome']} applied={applied} unknown={unknown} {result['seconds']}s"
                writer.writerow([f"{variant}/{qid}.a{application}", "done", detail, result["finished"]])
                handle.flush()
                logger.info("{}/{} {}/{}.a{} {}", index, len(units), variant, qid, application, detail)

    def report(self, variant: str, design: str = "his") -> dict[str, Any]:
        results = [self.session_result(variant, qid, n) for qid, n in self.plan(variant, design)]
        done = [result for result in results if result]
        rows = [row for result in done for row in result["rows"]]
        return {
            "variant": variant,
            "design": design,
            "sessions": len(done),
            "planned": len(results),
            "session_outcomes": [result["outcome"] for result in done],
            "seconds": round(sum(result["seconds"] for result in done), 1),
            "agent_tokens": [
                sum(result["usage"]["input_tokens"] for result in done),
                sum(result["usage"]["output_tokens"] for result in done),
            ],
            "context_tokens": sum(result["context_tokens"] for result in done),
            "tool_calls": sum(int(result.get("tool_calls") or 0) for result in done),
            **staged.totals(rows),
        }

    def summary(self, design: str) -> tuple[str, list[dict[str, Any]]]:
        """A Markdown table with one column per stage, and every check row of every session."""
        lines = [
            "| Variant | Sessions | Stored | Retrieved | Retrieved by source | Old version inactive | "
            "Old inactive by source | Applied (known) | Unknown | "
            "Missed available | Not retrieved | Wrong concrete | Broken | Invalid | Seconds | Agent tokens in/out | "
            "Tool calls | "
            "Total as in his table |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        all_rows: list[dict[str, Any]] = []
        for variant in self.variants:
            report = self.report(variant, design)
            if not report["sessions"]:
                continue
            for qid, application in self.plan(variant, design):
                result = self.session_result(variant, qid, application)
                for row in (result or {}).get("rows", []):
                    all_rows.append({"variant": variant, "question": qid, "application": application, **row})

            def frac(value: list[int] | None) -> str:
                return "n/a" if value is None else f"{value[0]}/{value[1]}"

            outcomes = report["outcomes"]
            lines.append(
                f"| {variant} | {report['sessions']}/{report['planned']} | {frac(report['stored'])} | "
                f"{frac(report['retrieved'])} | {frac(report['retrieved_source'])} | {frac(report['old_inactive'])} | "
                f"{frac(report['old_inactive_source'])} | {frac(report['applied'])} | "
                f"{frac(report['unknown'])} | {outcomes.get('missed_available', 0)} | "
                f"{outcomes.get('abstained_not_retrieved', 0)} | "
                f"{outcomes.get('wrong_concrete', 0)} | {outcomes.get('broken', 0)} | {outcomes.get('invalid', 0)} | "
                f"{report['seconds']} | {report['agent_tokens'][0]}/{report['agent_tokens'][1]} | "
                f"{report['tool_calls']} | "
                f"{frac(report['his_total_for_comparison'])} |"
            )
        return "\n".join(lines) + "\n", all_rows

    def session_result(self, variant: str, qid: str, application: int) -> dict[str, Any] | None:
        """A finished session, rescored from its saved check outcomes: a scorer change needs no new session."""
        path = self.run / "trials" / variant / f"{qid}.a{application}" / "result.json"
        if not path.exists():
            return None
        result = dict(json.loads(path.read_text()))
        statuses = {row["check"]: {"status": row["status"], "got": row["got"]} for row in result["rows"]}
        valid = not result["leaks"] and result["outcome"] == Outcome.COMPLETED.value
        entry = self.contexts(variant)[qid]
        stored_path = self.run / "stored" / f"{variant}.txt"
        stored = stored_path.read_text() if stored_path.exists() else None
        sources = {source for hit in entry.get("hits", []) for source in hit["sources"]} if entry.get("hits") else None
        task = qid.split(".")[0]
        checks = [check for check in self.checks if check["task"] == task]
        result["rows"] = staged.rows(checks, stored, entry.get("text"), statuses, valid, sources)
        if "tool_calls" not in result:
            result["tool_calls"] = tool_activity(path.parent / "hermes-home-after")["tool_calls"]
        return result
