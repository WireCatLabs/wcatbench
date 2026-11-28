"""Run the full-use round: memo as it is built against its rivals, at three archive sizes, sessions in a jail.

Layout under the run folder (one per size):
  trials/<contestant>/<unit>.a<n>/   workspace, Hermes files, calls.jsonl (timed tool calls), hidden results, result
  status.csv                         one row per session, flushed after each
Stores live under STORES/<size>/<contestant>, outside the run folder: memo prints its own paths, and a path into the
runs counts as a leak.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess  # nosec B404
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from wcatbench.agents.hermes import Tools, tool_activity
from wcatbench.core import dataset_files, registry
from wcatbench.core.types import Outcome, Record
from wcatbench.datasets.company_round import content
from wcatbench.pipeline import memory_bank
from wcatbench.pipeline.dialogue import NODE
from wcatbench.pipeline.rules_trial import cut, run_hidden
from wcatbench.pipeline.unrestricted import SEARCH_TOOL, STRATEGY, Proxy
from wcatbench.scoring import staged

ROOT = Path("/home/leemour/.cache/wcat-dapi-full")
MEMO_CLI = ROOT / "memo-cli"
BIN = MEMO_CLI / "node_modules" / ".bin"
STORES = ROOT / "stores"
TOOLS = ROOT / "agent-tools"
PROMPT_VERSION = "1"
APPLICATIONS = 2
FROZEN_K = 5

# contestant: how the agent reaches memory
KIND = {
    "answer-key": "context",
    "none": "none",
    "memo-full": "memo",
    "files-rg": "files",
    "memory-bank": "memory-bank",
    "mem0-oss": "proxy",
    "openviking": "proxy",
    "memo-limited": "frozen",
}
STORE_OF = {"mem0-oss": "mem0-oss", "openviking": "openviking", "memo-limited": "memo"}
GATES = ("answer-key", "none")

TOOL_LINE = {
    "memo": (
        "Память: команда `memo` (WireCat memo) — заметки, почта, переписка, встречи и документы Олега в одном месте. "
        "Как ей пользоваться, написано в `memo skill show`: прочитай это в начале. Память только для чтения: ничего "
        "в неё не пиши."
    ),
    "files": (
        "Память: папка `archive/` — архив Олега: переписка в Telegram (выгрузка Telegram Desktop, `chats/*/"
        "result.json`), почта (`mail/mail.mbox`), записи встреч (`meetings/*.vtt`), заметки (`notes/`) и документы "
        "(`docs/`). Ищи в нём сам: `rg`, `grep`, `jq`, Python."
    ),
    "memory-bank": (
        "Память: папка `memory-bank/` (Memory Bank), как с ней работать, сказано в `AGENTS.md`. Ищи в ней сам "
        "(`grep -ri`, `rg`), читай файлы."
    ),
    "proxy": (
        "Память: команда `search '<запрос>' [--k N]` печатает до N найденных записей (по умолчанию 10, не больше 20), "
        "каждую целиком. Других способов прочитать память нет."
    ),
}
CONTEXT_NOTE = "Опыт проекта, найденный в памяти, лежит в `memory/context.md`. Другой памяти у тебя нет."
NONE_NOTE = "Опыта проекта у тебя нет: ни памяти, ни архива."

# The real programs a timed wrapper stands in for; the wrapper writes each call and its time to /out/calls.jsonl.
TIMED = {"memo": str(BIN / "memo"), "rg": "/usr/bin/rg", "grep": "/usr/bin/grep", "jq": "/usr/bin/jq"}
WRAPPER = """#!/usr/bin/python3 -I
import json, subprocess, sys, time
started = time.perf_counter()
done = subprocess.run([{real!r}, *sys.argv[1:]], capture_output=True)
seconds = time.perf_counter() - started
sys.stdout.buffer.write(done.stdout)
sys.stderr.buffer.write(done.stderr)
try:
    with open("/out/calls.jsonl", "a") as lines:
        lines.write(json.dumps({{"tool": {name!r}, "args": sys.argv[1:], "seconds": round(seconds, 3),
                                "exit": done.returncode, "stdout": done.stdout.decode(errors="replace")[:200000]}},
                               ensure_ascii=False) + "\\n")
except OSError:
    pass
sys.exit(done.returncode)
"""

LEAK_MARKERS = (*staged.FORBIDDEN, "company_round", "qkeys.json", "wcat-dapi-full/runs", "current.md")


def memo_env(root: Path) -> dict[str, str]:
    home = root / "home"
    return {
        "PATH": f"{TOOLS}/timed:{BIN}:{NODE}/bin:/usr/local/bin:/usr/bin:/bin",
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_STATE_HOME": str(home / ".local/state"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "MEMO_CONFIG_DIR": str(root / "memo-config"),
        "MEMO_STATE_DIR": str(root / "memo-state"),
        "MEMO_CACHE_DIR": str(root / "memo-cache"),
        "WIRECAT_STATE_DIR": str(root / "wirecat-state"),
        "WIRECAT_CONFIG_DIR": str(root / "wirecat-config"),
        "MESSAGING_STORE": str(root / "wirecat-state" / "wirecat.db"),
        "MEMO_NO_UPDATE_CHECK": "1",
        "MEMO_TIMEOUT": "60m",
        "DBUS_SESSION_BUS_ADDRESS": "disabled:",
        "TZ": "Europe/Moscow",
    }


@dataclass
class MemoBuild:
    """memo with every kind imported natively, as a user would set it up once. No source is tagged for memo."""

    root: Path
    log: list[dict[str, Any]] = field(default_factory=list)

    @property
    def inbox(self) -> Path:
        return self.root / "inbox"

    def run(self, program: str, *args: str, check: bool = True) -> dict[str, Any]:
        env = memo_env(self.root)
        env["PATH"] = f"{BIN}:{NODE}/bin:/usr/bin:/bin"
        started = time.perf_counter()
        done = subprocess.run(  # noqa: S603  # nosec B603
            [str(BIN / program), *args, "--json"], capture_output=True, text=True, env=env, timeout=7200, check=False
        )
        seconds = time.perf_counter() - started
        last = done.stdout.strip().splitlines()[-1] if done.stdout.strip() else "{}"
        try:
            reply: dict[str, Any] = json.loads(last)
        except json.JSONDecodeError:
            reply = {"raw": last[:500]}
        self.log.append({"cmd": [program, *args], "seconds": round(seconds, 2), "exit": done.returncode})
        if check and (done.returncode != 0 or "error" in reply):
            raise RuntimeError(f"{program} {' '.join(args[:3])} failed: {done.stdout[-400:]} {done.stderr[-400:]}")
        return reply

    def mail_profile(self) -> None:
        """mail-cli refuses `config set address` from an agent. The synthetic address goes into the throwaway config
        file instead: no sign-in exists, so mail-cli only reads the mbox it is given."""
        self.run("mail", "work", "config", "set", "limit", "20")
        path = self.root / "home" / ".config" / "mail-cli" / "config.json"
        config = json.loads(path.read_text())
        config["profiles"]["work"] = {"address": content.PEOPLE[content.OWNER][2], "imap_host": "imap.gmail.com"}
        path.write_text(json.dumps(config, indent=2))

    def setup_projects(self) -> None:
        added = {}
        for name, key in ((content.PEL, "PEL"), (content.PPL, "PPL"), (content.ORB, "ORB")):
            added[name] = self.run("memo", "projects", "add", name, "--key", key, "--type", "work")["item"]["ref"]
        for name, alias in ((content.PEL, "Pelican"), (content.PPL, "ПП"), (content.PPL, "Pelican Plus")):
            fingerprint = self.run("memo", "vocabulary", "list")["item"]["fingerprint"]
            self.run("memo", "vocabulary", "aliases", "add", added[name], alias, "--fingerprint", fingerprint)

    def sync(self) -> None:
        for _ in range(400):
            item = self.run("memo", "sync")["item"]
            parts = [value for value in item.values() if isinstance(value, dict) and "left" in value]
            if not any(part["left"] for part in parts):
                return
        raise RuntimeError("memo sync still had chunks to embed after 400 runs")

    def build(self, dataset: Path) -> dict[str, Any]:
        if (self.root / "built.json").exists():
            return dict(json.loads((self.root / "built.json").read_text()))
        self.root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(dataset / "sources" / "memo", self.inbox, dirs_exist_ok=True)
        steps: dict[str, float] = {}

        def step(name: str, *calls: tuple[str, ...]) -> None:
            started = time.perf_counter()
            for call in calls:
                self.run(*call)
            steps[name] = round(time.perf_counter() - started, 1)

        step("models", ("memo", "models", "download", "embeddinggemma"))
        self.run("tg", "work", "config", "set", "limit", "20")
        step("reranker", ("tg", "work", "models", "download", "mmarco"))
        self.mail_profile()
        started = time.perf_counter()
        self.setup_projects()
        steps["projects"] = round(time.perf_counter() - started, 1)
        step("chats", ("tg", "work", "store", "import", str(self.inbox / "chats.json"), "--yes"))
        step("mail", ("mail", "work", "messages", "import", str(self.inbox / "mail.mbox")))
        step(
            "documents",
            ("memo", "import", str(self.inbox / "docs"), "--account", "import:docs"),
            ("memo", "import", str(self.inbox / "meetings"), "--account", "import:meetings"),
        )
        step(
            "notes",
            ("memo", "folders", "add", str(self.inbox / "notes"), "--format", "markdown"),
            ("memo", "folders", "add", str(self.inbox / "hr"), "--format", "markdown"),
        )
        started = time.perf_counter()
        self.sync()
        steps["sync"] = round(time.perf_counter() - started, 1)
        step("chat_vectors", ("tg", "work", "conversations", "embed"))
        doctor = self.run("memo", "doctor", check=False)
        built = {
            "steps": steps,
            "seconds": round(sum(steps.values()), 1),
            "bytes": folder_bytes(self.root),
            "doctor": doctor,
            "at": datetime.now(UTC).isoformat(),
        }
        (self.root / "built.json").write_text(json.dumps(built, ensure_ascii=False, indent=2))
        (self.root / "build-log.json").write_text(json.dumps(self.log, ensure_ascii=False, indent=2))
        return built

    def forget(self) -> dict[str, Any]:
        """The deletion and the revocation, each with memo's own way: the note file gone and a sync, the HR folder
        removed with its notes."""
        done = self.root / "forgotten.json"
        if done.exists():
            return dict(json.loads(done.read_text()))
        deleted = next(s for s in content.SOURCES if s.get("deleted"))
        (self.inbox / deleted["folder"] / deleted["path"]).unlink(missing_ok=True)
        self.sync()
        folders = self.run("memo", "folders", "list")["items"]
        hr = next(item for item in folders if str(item.get("path", "")).endswith("/inbox/hr"))
        removed = self.run("memo", "folders", "remove", str(hr["id"]), "--allow-delete", "--yes")
        result = {"deleted": deleted["path"], "revoked": removed, "at": datetime.now(UTC).isoformat()}
        done.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    def check_forgotten(self) -> dict[str, int]:
        """No agent: search the markers with and without --exact."""
        hits = {}
        for name, marker in content.MARKERS.items():
            for mode in ((), ("--exact",)):
                reply = self.run("memo", "search", "all", marker, *mode, check=False)
                hits[f"{name}{''.join(mode)}"] = sum(
                    marker in json.dumps(item, ensure_ascii=False) for item in reply.get("items", [])
                )
        return hits


def folder_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file() and not item.is_symlink())


def install_wrappers() -> Path:
    folder = TOOLS / "timed"
    folder.mkdir(parents=True, exist_ok=True)
    for name, real in TIMED.items():
        (folder / name).write_text(WRAPPER.format(real=real, name=name))
        (folder / name).chmod(0o755)
    (TOOLS / "proxy").mkdir(parents=True, exist_ok=True)
    (TOOLS / "proxy" / "search").write_text(SEARCH_TOOL)
    (TOOLS / "proxy" / "search").chmod(0o755)
    return folder


def files_archive(dataset: Path, into: Path) -> None:
    """The archive as the user keeps it after the deletion and the revocation: the note gone, the HR folder out of
    the agent's reach."""
    shutil.copytree(dataset / "sources" / "files", into, symlinks=False)
    deleted = next(s for s in content.SOURCES if s.get("deleted"))
    (into / deleted["folder"] / deleted["path"]).unlink(missing_ok=True)
    shutil.rmtree(into / "hr", ignore_errors=True)


def sources_file(workspace: Path) -> str:
    path = workspace / "SOURCES.md"
    return path.read_text() if path.exists() else ""


def citation_ok(check: dict[str, Any], sources_md: str, checks: list[dict[str, Any]]) -> bool | None:
    """A SOURCES.md line naming any value of the check's rule carries the active source's date. One rule sets several
    names (MAX_ATTEMPTS and should_retry), and one line per rule is a correct citation."""
    if check["kind"] != "known":
        return None
    names = {other["expr"].split("(")[0] for other in checks if other.get("rule") == check["rule"]}
    lines = [line for line in sources_md.splitlines() if any(name in line for name in names)]
    return any(check["source_date"] in line for line in lines)


def extra_rows(
    checks: list[dict[str, Any]], statuses: dict[str, dict[str, str]], sources_md: str
) -> list[dict[str, Any]]:
    out = []
    for check in checks:
        got = statuses.get(check["id"], {}).get("got")
        row: dict[str, Any] = {"check": check["id"]}
        if check["kind"] == "known":
            row["stale_used"] = check.get("stale") is not None and got == check["stale"]
            row["lookalike_used"] = check.get("lookalike") is not None and got == check["lookalike"]
            row["cited"] = (
                citation_ok(check, sources_md, checks)
                if statuses.get(check["id"], {}).get("status") == "pass"
                else None
            )
        else:
            row["trap_used"] = check.get("trap_value") is not None and got == check["trap_value"]
        out.append(row)
    return out


CURATE = (
    "Ты работаешь в папке /work. В `raw/` лежит архив Олега Тестова, руководителя разработки компании «Северный "
    "ветер»: переписка в Telegram (`raw/chats/*/result.json`), почта (`raw/mail/mail.mbox`), записи встреч "
    "(`raw/meetings/*.vtt`), заметки (`raw/notes/`) и документы (`raw/docs/`). В папке установлен Memory Bank: как "
    "с ним работать, сказано в `AGENTS.md`. Перенеси в `memory-bank/` по его правилам всё, что пригодится агенту для "
    "работы над проектом «Пеликан»: решения, их историю, людей и роли. Архив после этого агенту доступен не будет. "
    "Ищи в архиве сам: `rg`, `grep`, `jq`, Python. Когда закончишь, коротко напиши, что сделал."
)


def curate_memory_bank(dataset: Path, store: Path, agent: Any) -> dict[str, Any]:
    """Memory Bank as its author intends it: an agent curates the archive into the bank once, then sessions read the
    bank only. It curates the archive after the deletion and the revocation."""
    done = store / "curated.json"
    if done.exists():
        return dict(json.loads(done.read_text()))
    trial = store / "curation"
    if trial.exists():
        shutil.move(str(trial), str(trial.with_name(f"curation.aborted-{int(time.time())}")))
    workspace = trial / "workspace"
    workspace.mkdir(parents=True)
    memory_bank.install(workspace)
    files_archive(dataset, workspace / "raw")
    reply = agent.session(
        CURATE, workspace, trial, Tools(read_only=(TOOLS,), env={"PATH": f"{TOOLS}/timed:/usr/bin:/bin"})
    )
    (trial / "stdout.txt").write_text(reply.stdout)
    curated = store / "curated"
    if curated.exists():
        shutil.rmtree(curated)
    curated.mkdir(parents=True)
    shutil.copytree(workspace / "memory-bank", curated / "memory-bank")
    for name in ("AGENTS.md", "init.sh"):
        if (workspace / name).exists():
            shutil.copy2(workspace / name, curated / name)
    result = {
        "outcome": reply.outcome.value,
        "seconds": round(reply.seconds, 1),
        "usage": reply.usage.model_dump(),
        "files": sum(1 for _ in (curated / "memory-bank").rglob("*.md")),
        "bytes": folder_bytes(curated),
        "at": datetime.now(UTC).isoformat(),
    }
    done.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


QUOTA = re.compile(r"quota exhausted \(429\); retry after (\d+)s")


def quota_wait(trial: Path) -> int | None:
    """A session the provider refused for quota is no result: set it aside and say how long to wait."""
    result = trial / "result.json"
    if not result.exists() or json.loads(result.read_text())["outcome"] != "error":
        return None
    text = "".join((trial / name).read_text() for name in ("stdout.txt", "stderr.txt") if (trial / name).exists())
    found = QUOTA.search(text)
    if found is None and "HTTP 429" not in text:
        return None
    shutil.move(str(trial), str(trial.with_name(f"{trial.name}.quota-{int(time.time())}")))
    return min(int(found.group(1)) + 60, 4 * 3600) if found else 1800


@dataclass
class FullUseRound:
    dataset: Path
    run: Path
    size: str
    agent: Any
    applications: int = APPLICATIONS
    proxy: Proxy | None = None

    def __post_init__(self) -> None:
        self.records: list[Record] = dataset_files.records(self.dataset)
        self.questions = {question.id: question for question in dataset_files.questions(self.dataset)}
        self.checks: list[dict[str, Any]] = json.loads((self.dataset / "checks.json").read_text())
        self.qkeys: dict[str, Any] = json.loads((self.dataset / "qkeys.json").read_text())
        self.run.mkdir(parents=True, exist_ok=True)
        # Each agent gets its own stores: two agents' sessions may run at once, and memo keeps one writer per store.
        name = getattr(self.agent, "name", "hermes")
        self.stores = STORES / (self.size if name == "hermes" else f"{self.size}-{name}")
        install_wrappers()

    def units(self, contestant: str) -> list[tuple[str, int]]:
        coding = [(task["id"], n) for task in content.TASKS for n in range(1, self.applications + 1)]
        if contestant in GATES:
            return coding
        # Interleaved, so the first 2 and 5 sessions of the staged run cover both kinds of unit.
        asked = [(qid, 1) for qid in sorted(self.qkeys, key=lambda qid: (qid.endswith("v"), qid))]
        mixed: list[tuple[str, int]] = []
        for index in range(max(len(coding), len(asked))):
            mixed += coding[index : index + 1] + asked[index : index + 1]
        return mixed

    def memo(self) -> MemoBuild:
        return MemoBuild(self.stores / "memo-full")

    def store(self, contestant: str) -> Any:
        """An adapter store, built once per size; the forgotten records are deleted through the store's own API."""
        name = STORE_OF[contestant]
        store = registry.load("stores", name)()
        workdir = self.stores / contestant
        store.open("full-use", workdir, datetime.now(UTC))
        forgotten = {s["id"] for s in content.SOURCES if s.get("deleted") or s.get("revoked")}
        records = self.records
        if contestant == "memo-limited":
            # Under hard limits, as in rules-trial: one notes folder. The forgotten notes never went in.
            records = [record for record in self.records if record.id not in forgotten]
        held = store.held()
        marker = workdir / "forgotten.json"
        # After the deletion the forgotten records are no longer held; re-adding them would undo it.
        missing = [
            record for record in records if record.key not in held and not (marker.exists() and record.id in forgotten)
        ]
        if missing:
            started = time.perf_counter()
            receipt = store.ingest(missing)
            with (workdir / "ledger.jsonl").open("a") as lines:
                lines.write(
                    json.dumps(
                        {
                            "sent": len(receipt.sent),
                            "seconds": round(time.perf_counter() - started, 1),
                            "bytes": folder_bytes(workdir),
                            "at": datetime.now(UTC).isoformat(),
                        }
                    )
                    + "\n"
                )
        if contestant != "memo-limited" and not marker.exists():
            keys = [record.key for record in self.records if record.id in forgotten]
            marker.write_text(json.dumps({"forgot": store.forget(keys), "at": datetime.now(UTC).isoformat()}))
        return store

    def frozen(self, qid: str, store: Any) -> dict[str, Any]:
        path = self.run / "contexts" / "memo-limited" / f"{qid}.json"
        if path.exists():
            return dict(json.loads(path.read_text()))
        path.parent.mkdir(parents=True, exist_ok=True)
        question = self.questions[qid]
        query = question.text.split("\n\n", 1)[0]
        started = time.perf_counter()
        hits = store.search(query, FROZEN_K)
        seconds = time.perf_counter() - started
        rows = [{"sources": list(hit.keys), "text": hit.text or ""} for hit in hits]
        text, tokens, kept = cut(rows)
        entry = {"text": text, "tokens": tokens, "hits": kept, "query": query, "search_seconds": round(seconds, 3)}
        path.write_text(json.dumps(entry, ensure_ascii=False, indent=2))
        return entry

    def tools(self, contestant: str) -> Tools | None:
        kind = KIND[contestant]
        if kind == "proxy":
            return Tools(read_only=(TOOLS,), env={"PATH": f"{TOOLS}/proxy:/usr/local/bin:/usr/bin:/bin"})
        if kind == "files":
            return Tools(read_only=(TOOLS,), env={"PATH": f"{TOOLS}/timed:/usr/local/bin:/usr/bin:/bin"})
        if kind == "memo":
            root = self.memo().root
            return Tools(read_only=(NODE, MEMO_CLI, TOOLS), writable=((root, str(root)),), env=memo_env(root))
        return None

    def prompt(self, contestant: str, qid: str, into: Path, entry: dict[str, Any] | None) -> str:
        shutil.copytree(self.dataset / "project", into)
        kind = KIND[contestant]
        task = self.questions[qid].text
        (into / "TASK.md").write_text(task)
        if kind == "context":
            (into / "memory").mkdir()
            (into / "memory" / "context.md").write_text((self.dataset / "files" / "current.md").read_text())
            note = CONTEXT_NOTE
        elif kind == "frozen":
            (into / "memory").mkdir()
            (into / "memory" / "context.md").write_text((entry or {}).get("text") or "")
            note = CONTEXT_NOTE
        elif kind == "none":
            note = NONE_NOTE
        else:
            if kind == "files":
                files_archive(self.dataset, into / "archive")
            if kind == "memory-bank":
                shutil.copytree(self.stores / "memory-bank" / "curated", into, dirs_exist_ok=True)
            note = f"{TOOL_LINE[kind]}\n\n{STRATEGY}"
        return (
            "Ты работаешь в папке /work: это репозиторий проекта «Пеликан» компании «Северный ветер». Ты помогаешь "
            "Олегу Тестову, руководителю разработки. Задача ниже, она же в TASK.md.\n"
            f"{note}\n\n{task}\nКогда закончишь, коротко напиши, что сделал."
        )

    def session(self, contestant: str, qid: str, application: int, store: Any = None) -> dict[str, Any]:
        trial = self.run / "trials" / contestant / f"{qid}.a{application}"
        done_file = trial / "result.json"
        if done_file.exists():
            return dict(json.loads(done_file.read_text()))
        if trial.exists():
            shutil.move(str(trial), str(trial.with_name(f"{trial.name}.aborted-{int(time.time())}")))
        trial.mkdir(parents=True)
        entry = self.frozen(qid, store) if KIND[contestant] == "frozen" else None
        workspace = trial / "workspace"
        prompt = self.prompt(contestant, qid, workspace, entry)
        (trial / "prompt.txt").write_text(prompt)
        if self.proxy is not None:
            self.proxy.log = trial / "searches.jsonl"
        reply = self.agent.session(prompt, workspace, trial, self.tools(contestant))
        (trial / "stdout.txt").write_text(reply.stdout)
        (trial / "stderr.txt").write_text(reply.stderr)
        activity = reply.details.get("tools") or tool_activity(trial / "hermes-home-after")
        seen = str(activity["outputs"])
        if (trial / "searches.jsonl").exists():
            seen += "\n".join(
                hit["text"]
                for line in (trial / "searches.jsonl").read_text().splitlines()
                for hit in json.loads(line)["hits"]
            )
        if entry:
            seen += "\n" + (entry.get("text") or "")
        (trial / "seen.txt").write_text(seen)
        leaks = [marker for marker in LEAK_MARKERS if marker in reply.transcript + reply.stdout]
        markers = [name for name, marker in content.MARKERS.items() if marker in seen + reply.transcript]
        calls = (
            [json.loads(line) for line in (trial / "out" / "calls.jsonl").read_text().splitlines()]
            if (trial / "out" / "calls.jsonl").exists()
            else []
        )
        searches = (
            [
                {"q": json.loads(line)["q"], "seconds": json.loads(line).get("seconds")}
                for line in (trial / "searches.jsonl").read_text().splitlines()
            ]
            if (trial / "searches.jsonl").exists()
            else []
        )
        valid = not leaks and reply.outcome is Outcome.COMPLETED
        result: dict[str, Any] = {
            "contestant": contestant,
            "provider": getattr(self.agent, "provider", "unknown"),
            "size": self.size,
            "prompt_version": PROMPT_VERSION,
            "unit": qid,
            "application": application,
            "outcome": reply.outcome.value,
            "valid": valid,
            "leaks": leaks,
            "markers_seen": markers,
            "seconds": round(reply.seconds, 1),
            "usage": reply.usage.model_dump(),
            "tool_calls": activity["tool_calls"],
            "by_tool": activity["by_tool"],
            "calls": [{k: c[k] for k in ("tool", "args", "seconds", "exit")} for c in calls],
            "proxy_searches": len(searches),
            "context_tokens": (entry or {}).get("tokens", 0),
            "finished": datetime.now(UTC).isoformat(),
        }
        if qid in self.qkeys:
            answer = workspace / "ANSWER.md"
            result["answer"] = answer.read_text() if answer.exists() else (reply.stdout or "")[-3000:]
        else:
            statuses = (
                run_hidden(self.dataset, trial, workspace, [c for c in self.checks if c["task"] == qid])
                if (reply.outcome is Outcome.COMPLETED)
                else {}
            )
            checks = [check for check in self.checks if check["task"] == qid]
            result["rows"] = staged.rows(checks, None, seen or None, statuses, valid)
            result["extra"] = extra_rows(checks, statuses, sources_file(workspace))
        done_file.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    def go(self, contestant: str, limit: int | None = None) -> None:
        store = None
        if contestant in STORE_OF:
            store = self.store(contestant)
        if contestant == "memo-full":
            built = self.memo().build(self.dataset)
            logger.info("memo-full built in {}s, {} bytes", built["seconds"], built["bytes"])
            self.memo().forget()
        units = self.units(contestant)[:limit] if limit else self.units(contestant)
        status = self.run / "status.csv"
        logger.info("status file: {}", status)
        new = not status.exists()
        try:
            if KIND[contestant] == "proxy":
                self.proxy = Proxy(store)
                self.proxy.__enter__()
            with status.open("a", newline="") as handle:
                writer = csv.writer(handle)
                if new:
                    writer.writerow(["id", "status", "detail", "time"])
                for index, (qid, application) in enumerate(units, start=1):
                    result = self.session(contestant, qid, application, store)
                    while (wait := quota_wait(self.run / "trials" / contestant / f"{qid}.a{application}")) is not None:
                        logger.warning("Codex quota exhausted; waiting {}s, then {} again", wait, qid)
                        time.sleep(wait)
                        result = self.session(contestant, qid, application, store)
                    applied = sum(row.get("applied", False) for row in result.get("rows", []))
                    detail = f"{result['outcome']} applied={applied} {result['seconds']}s leaks={result['leaks']}"
                    writer.writerow(
                        [f"{self.size}/{contestant}/{qid}.a{application}", "done", detail, result["finished"]]
                    )
                    handle.flush()
                    logger.info(
                        "{}/{} {}/{}/{}.a{} {}", index, len(units), self.size, contestant, qid, application, detail
                    )
        finally:
            if self.proxy is not None:
                self.proxy.__exit__()
                self.proxy = None
            if store is not None:
                store.close()
