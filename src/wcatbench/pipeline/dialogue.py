"""Experiment 2 of the rules-trial round: three sessions per chain, the rules carried only by the variant's memory.

Layout under <run>/e2/<variant>/<scenario>.r<rep>/:
  memory/            files-agent: the agent's own notes, carried from session to session
  memo/              memo-agent: the memo store the agent reads and writes with the memo CLI
  store/             memo-transcript and OpenViking: the store each finished conversation goes into
  <session>/         workspace, Hermes output, hidden results, the context handed over, result.json
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess  # nosec B404
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from wcatbench.agents.hermes import Tools
from wcatbench.core.jail import Jail
from wcatbench.core.types import Outcome, Record
from wcatbench.datasets.rules_trial import dialogue
from wcatbench.pipeline import memory_bank
from wcatbench.pipeline.rules_trial import K, cut, run_hidden
from wcatbench.scoring import staged
from wcatbench.stores.memo import MemoStore
from wcatbench.stores.openviking import OpenVikingEvolutionStore, OpenVikingStore

NODE = Path("/var/tmp/wcat-dapi/node")  # nosec B108
MEMO_CLI = Path("/var/tmp/wcat-dapi/memo-cli")  # nosec B108
MEMO_TEMPLATE = Path("/var/tmp/wcat-dapi/memo-template")  # nosec B108

VARIANTS = (
    "none",
    "files-agent",
    "memo-agent",
    "memo-transcript",
    "openviking-evo-off",
    "openviking-evo-on",
    "memory-bank-agent",
)

MEMO_ENV = {
    "PATH": f"{MEMO_CLI}/node_modules/.bin:{NODE}/bin:/usr/local/bin:/usr/bin:/bin",
    "MEMO_CONFIG_DIR": "/memo/config",
    "MEMO_STATE_DIR": "/memo/state",
    "MEMO_CACHE_DIR": "/memo/cache",
    "WIRECAT_STATE_DIR": "/memo/wc-state",
    "WIRECAT_CONFIG_DIR": "/memo/wc-config",
    "MEMO_NO_UPDATE_CHECK": "1",
    "MEMO_TIMEOUT": "30m",
}

NOTE = {
    "none": "Памяти между разговорами у тебя нет.",
    "files-agent": (
        "Папка `memory/` — твоя память между разговорами, она переживёт эту сессию, всё остальное нет. В начале "
        "прочитай `memory/NOTES.md`, в конце запиши туда то, что пригодится в следующих разговорах."
    ),
    "memo-agent": (
        "У тебя есть память между разговорами: команда `memo` (WireCat memo). В начале найди, что уже известно "
        "(`memo notes list --json`, `memo search all '<запрос>' --json`). В конце сохрани то, что пригодится в "
        "следующих разговорах: `memo notes add '<текст>'`, а устаревшее поправь через `memo notes edit`."
    ),
    "context": "Опыт прошлых разговоров, найденный в памяти, лежит в `memory/context.md`. Другой памяти у тебя нет.",
    "memory-bank-agent": (
        "Папка `memory-bank/` (Memory Bank) — твоя память между разговорами, она переживёт эту сессию, всё остальное "
        "нет. Как с ней работать, сказано в `AGENTS.md`. В конце сохрани в ней то, что пригодится в следующих "
        "разговорах, по её правилам."
    ),
}


def memo_template() -> Path:
    """A memo store with e5-small downloaded and chosen, copied into each chain, so no session pays the download."""
    if (MEMO_TEMPLATE / "ready").exists():
        return MEMO_TEMPLATE
    MEMO_TEMPLATE.mkdir(parents=True, exist_ok=True)
    jail = Jail(read_only=(NODE, MEMO_CLI), writable=((MEMO_TEMPLATE, "/memo"),), workdir="/memo", env=MEMO_ENV)
    for args in (["models", "download", "e5-small"], ["models", "set", "e5-small"]):
        done = subprocess.run(  # noqa: S603  # nosec B603
            jail.command(["memo", *args, "--json"]), capture_output=True, text=True, check=False, timeout=1800
        )
        if done.returncode != 0:
            raise RuntimeError(f"memo {' '.join(args)} failed: {done.stderr[-300:]}")
    (MEMO_TEMPLATE / "ready").write_text("e5-small\n")
    return MEMO_TEMPLATE


def outcome(check: dict[str, Any], status: str) -> str:
    return "invalid" if status == "invalid" else staged.outcome_kind(check, status)


@dataclass
class DialogueRound:
    dataset: Path
    run: Path
    builds: Path
    agent: Any

    def chain(self, variant: str, scenario: str, rep: int) -> Path:
        return self.run / "e2" / variant / f"{scenario}.r{rep}"

    def store(self, variant: str, chain: Path) -> Any:
        if variant == "memo-transcript":
            store: Any = MemoStore(binary=str(MEMO_CLI / "node_modules/.bin/memo"))
        elif variant == "openviking-evo-on":
            store = OpenVikingEvolutionStore()
        else:
            store = OpenVikingStore()
        store.open("store", chain, datetime.now(UTC))
        return store

    def context(self, variant: str, chain: Path, query: str) -> dict[str, Any]:
        if variant not in ("memo-transcript", "openviking-evo-off", "openviking-evo-on"):
            return {"text": None, "tokens": 0, "hits": []}
        if not (chain / "store").exists():
            return {"text": None, "tokens": 0, "hits": [], "note": "nothing stored yet"}
        store = self.store(variant, chain)
        try:
            hits = store.search(query, K) if variant == "memo-transcript" else store.recall(query, K)
        finally:
            store.close()
        rows = [{"sources": list(hit.keys), "text": hit.text or "", "score": hit.score} for hit in hits]
        text, tokens, kept = cut(rows)
        return {"text": text or None, "tokens": tokens, "hits": kept, "query": query}

    def remember(self, variant: str, chain: Path, scenario: str, session: str, prompt: str, reply: str) -> None:
        if variant == "files-agent":
            return
        if variant == "memo-transcript":
            when = f"2026-11-{10 + dialogue.SESSIONS.index(session):02}T10:00:00+00:00"
            text = f"{when[:10]} · разговор {session}\n{prompt}\n\nОтвет агента:\n{reply}"
            store = self.store(variant, chain)
            store.ingest([Record(id=f"{scenario}.{session}", kind="dialogue", timestamp=when, text=text)])
            store.close()
        elif variant.startswith("openviking"):
            store = self.store(variant, chain)
            try:
                store.remember_dialogue(
                    f"{scenario}-{chain.name}-{session}".replace(".", "-"),
                    [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}],
                )
            finally:
                store.close()

    def session(self, variant: str, scenario: str, rep: int, session: str) -> dict[str, Any]:
        chain = self.chain(variant, scenario, rep)
        trial = chain / session
        done_file = trial / "result.json"
        if done_file.exists():
            return dict(json.loads(done_file.read_text()))
        if trial.exists():
            shutil.move(str(trial), str(trial.with_name(f"{session}.aborted-{int(datetime.now(UTC).timestamp())}")))
        trial.mkdir(parents=True)
        workspace = trial / "workspace"
        shutil.copytree(self.dataset / "project", workspace)
        task = dialogue.prompt_of(scenario, session)
        entry = self.context(variant, chain, task.split("\n\n", 1)[0])
        (trial / "context.json").write_text(json.dumps(entry, ensure_ascii=False, indent=2))
        tools = None
        if variant == "files-agent":
            (chain / "memory").mkdir(parents=True, exist_ok=True)
            (chain / "memory" / "NOTES.md").touch()
            shutil.copytree(chain / "memory", workspace / "memory")
            note = NOTE["files-agent"]
        elif variant == "memory-bank-agent":
            if not (chain / "bank").exists():
                memory_bank.install(chain / "bank")
            for name in ("memory-bank", "init.sh", "AGENTS.md"):
                copy = shutil.copytree if (chain / "bank" / name).is_dir() else shutil.copy2
                copy(chain / "bank" / name, workspace / name)
            note = NOTE["memory-bank-agent"]
        elif variant == "memo-agent":
            if not (chain / "memo").exists():
                shutil.copytree(memo_template(), chain / "memo")
            tools = Tools(read_only=(NODE, MEMO_CLI), writable=((chain / "memo", "/memo"),), env=MEMO_ENV)
            note = NOTE["memo-agent"]
        elif entry["text"]:
            (workspace / "memory").mkdir()
            (workspace / "memory" / "context.md").write_text(entry["text"])
            note = NOTE["context"]
        else:
            note = NOTE["none"]
        prompt = (
            f"Ты работаешь в папке /work: это репозиторий проекта «Сокол».\n{note}\n\n{task}\n"
            "Когда закончишь, коротко напиши, что сделал."
        )
        (trial / "prompt.txt").write_text(prompt)
        reply = (
            self.agent.session(prompt, workspace, trial, tools)
            if tools
            else self.agent.session(prompt, workspace, trial)
        )
        (trial / "stdout.txt").write_text(reply.stdout)
        (trial / "stderr.txt").write_text(reply.stderr)
        if variant == "files-agent" and (workspace / "memory").exists():
            shutil.rmtree(chain / "memory")
            shutil.copytree(workspace / "memory", chain / "memory")
            shutil.copytree(workspace / "memory", trial / "memory-after")
        if variant == "memory-bank-agent" and (workspace / "memory-bank").exists():
            # The bank and the instruction file carry over, as a repository would keep them between sessions.
            shutil.rmtree(chain / "bank")
            (chain / "bank").mkdir()
            shutil.copytree(workspace / "memory-bank", chain / "bank" / "memory-bank")
            for name in ("init.sh", "AGENTS.md"):
                if (workspace / name).exists():
                    shutil.copy2(workspace / name, chain / "bank" / name)
            shutil.copytree(chain / "bank", trial / "bank-after")
        leaks = staged.leaked(reply.transcript + reply.stdout)
        checks = dialogue.checks_of(scenario, session)
        completed = reply.outcome is Outcome.COMPLETED
        statuses = run_hidden(self.dataset, trial, workspace, checks) if completed else {}
        valid = completed and not leaks
        rows = []
        for check in checks:
            status = statuses.get(check["id"], {}).get("status", "broken") if valid else "invalid"
            carried = check["origin"] is not None and check["origin"] < session
            rows.append(
                {
                    "check": check["id"],
                    "kind": check["kind"],
                    "origin": check["origin"],
                    "transfer": carried,
                    "old": check["old"],
                    "status": status,
                    "got": statuses.get(check["id"], {}).get("got"),
                    "outcome": outcome(check, status),
                }
            )
        self.remember(variant, chain, scenario, session, task, reply.stdout.strip())
        result = {
            "variant": variant,
            "scenario": scenario,
            "rep": rep,
            "session": session,
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

    def go(self, variant: str, reps: int) -> None:
        status = self.run / "e2" / "status.csv"
        status.parent.mkdir(parents=True, exist_ok=True)
        new = not status.exists()
        with status.open("a", newline="") as handle:
            writer = csv.writer(handle)
            if new:
                writer.writerow(["id", "status", "detail", "time"])
            for rep in range(1, reps + 1):
                for scenario in (item["id"] for item in dialogue.SCENARIOS):
                    for session in dialogue.SESSIONS:
                        result = self.session(variant, scenario, rep, session)
                        applied = sum(row["outcome"] == "applied" for row in result["rows"])
                        detail = f"{result['outcome']} applied={applied}/{len(result['rows'])} {result['seconds']}s"
                        name = f"{variant}/{scenario}.r{rep}/{session}"
                        writer.writerow([name, "done", detail, result["finished"]])
                        handle.flush()
                        logger.info("{} {}", name, detail)

    def results(self, variant: str) -> list[dict[str, Any]]:
        folder = self.run / "e2" / variant
        return [json.loads(path.read_text()) for path in sorted(folder.glob("*/[ABC]/result.json"))]

    def summary(self) -> tuple[str, list[dict[str, Any]]]:
        lines = [
            "| Variant | Sessions | Transfer checks applied | Old version kept out (B, C) | Known in A | "
            "Unknown correct | Wrong concrete | Broken | Invalid | Seconds | Agent tokens in/out |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        every: list[dict[str, Any]] = []
        for variant in VARIANTS:
            done = self.results(variant)
            if not done:
                continue
            rows = [
                {**row, "variant": variant, "chain": f"{r['scenario']}.r{r['rep']}", "session": r["session"]}
                for r in done
                for row in r["rows"]
            ]
            every += rows
            transfer = [row for row in rows if row["transfer"]]
            old = [row for row in rows if row["old"] and row["session"] != "A"]
            first = [row for row in rows if row["session"] == "A" and row["kind"] == "known"]
            unknown = [row for row in rows if row["kind"] == "unknown"]
            kinds = Counter(row["outcome"] for row in rows)

            def share(part: list[dict[str, Any]]) -> str:
                return f"{sum(row['outcome'] == 'applied' for row in part)}/{len(part)}"

            lines.append(
                f"| {variant} | {len(done)} | {share(transfer)} | {share(old)} | {share(first)} | "
                f"{sum(row['outcome'] == 'justified_unknown' for row in unknown)}/{len(unknown)} | "
                f"{kinds.get('wrong_concrete', 0)} | {kinds.get('broken', 0)} | {kinds.get('invalid', 0)} | "
                f"{round(sum(r['seconds'] for r in done), 1)} | "
                f"{sum(r['usage']['input_tokens'] for r in done)}/{sum(r['usage']['output_tokens'] for r in done)} |"
            )
        return "\n".join(lines) + "\n", every
