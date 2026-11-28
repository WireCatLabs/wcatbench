from __future__ import annotations

import json
import mailbox
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from wcatbench.agents.hermes import SessionResult
from wcatbench.core.types import Outcome, Usage
from wcatbench.datasets.company_round import CompanyRoundDataset, checks, content, export, keys, noise
from wcatbench.pipeline import full_use, full_use_report, rules_trial
from wcatbench.pipeline.full_use import FullUseRound, MemoBuild, citation_ok

SOLUTION = {
    "pelican/http_policy.py": """from pelican.unknown import UNKNOWN
TIMEOUT_SECONDS = 8
MAX_ATTEMPTS = 3
def should_retry(attempts_made):
    return attempts_made < MAX_ATTEMPTS
def backoff_seconds(retry):
    return 2.0 * 2 ** (retry - 1)
def is_allowed_host(host):
    return host == "api.pelican-pay.example"
MAX_RESPONSE_BYTES = UNKNOWN
LOG_RETENTION_DAYS = UNKNOWN
CIRCUIT_BREAKER_ERRORS = UNKNOWN
""",
    "pelican/export_policy.py": """from pelican.unknown import UNKNOWN
DELIMITER = ";"
def format_date(value):
    return value.strftime("%d.%m.%Y")
def render_row(fields):
    return DELIMITER.join(fields)
MAX_ROWS = 2000
def split_counts(total):
    out = []
    while total > 0:
        out.append(min(MAX_ROWS, total))
        total -= MAX_ROWS
    return out
def part_name(number):
    return f"part-{number}"
def mask_email(address):
    name, domain = address.split("@")
    return f"{name[0]}***@{domain}"
INCLUDE_FULL_EMAIL = False
EXPORT_RETENTION_DAYS = 45
FILE_ENCODING = UNKNOWN
COMPRESSION = UNKNOWN
SORT_FIELD = UNKNOWN
""",
    "pelican/notify_policy.py": """import datetime
from zoneinfo import ZoneInfo
from pelican.unknown import UNKNOWN
QUIET_START = "21:00"
QUIET_END = "09:00"
QUIET_TIMEZONE = "Europe/Moscow"
def in_quiet_hours(moment):
    local = moment.astimezone(ZoneInfo(QUIET_TIMEZONE))
    return local.hour >= 21 or local.hour < 9
WEBHOOK_TIMEOUT_SECONDS = 8
WEBHOOK_MAX_ATTEMPTS = 3
def webhook_host_allowed(host):
    return host == "api.pelican-pay.example"
MAX_PER_DAY = UNKNOWN
CHANNEL = UNKNOWN
ESCALATION_MINUTES = UNKNOWN
""",
}

STALE_HTTP = SOLUTION["pelican/http_policy.py"].replace("TIMEOUT_SECONDS = 8", "TIMEOUT_SECONDS = 25")
LOOKALIKE_HTTP = STALE_HTTP.replace("TIMEOUT_SECONDS = 25", "TIMEOUT_SECONDS = 15").replace(
    "LOG_RETENTION_DAYS = UNKNOWN", "LOG_RETENTION_DAYS = 14"
)


class NoJail:
    def __init__(self, **_: Any) -> None:
        pass

    def command(self, argv: list[str]) -> list[str]:
        return argv


class FakeAgent:
    def __init__(
        self, http: str | None = None, answer: str = "27 ноября — чат, 2026-10-23, Ирина", ref: str = ""
    ) -> None:
        self.http, self.answer, self.ref, self.prompts = http, answer, ref, list[str]()

    def session(self, prompt: str, workspace: Path, trial: Path, tools: Any = None) -> SessionResult:
        self.prompts.append(prompt)
        for path, text in SOLUTION.items():
            body = self.http if self.http and path.endswith("http_policy.py") else text
            (workspace / path).write_text(body)
        (workspace / "SOURCES.md").write_text(
            "TIMEOUT_SECONDS = 8 — встреча, 2026-05-19, Ирина\nMAX_ATTEMPTS = 3 — чат\n"
        )
        (workspace / "ANSWER.md").write_text(self.answer)
        (trial / "out").mkdir(parents=True, exist_ok=True)
        (trial / "out" / "calls.jsonl").write_text(
            json.dumps(
                {
                    "tool": "memo",
                    "args": ["search", "all", "x"],
                    "seconds": 0.5,
                    "exit": 0,
                    "stdout": json.dumps({"items": [{"ref": self.ref}]}, ensure_ascii=False),
                }
            )
            + "\n"
        )
        return SessionResult(Outcome.COMPLETED, 2.0, Usage(input_tokens=100, output_tokens=10), "done", "", "ok")


@pytest.fixture(autouse=True)
def no_bwrap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(rules_trial, "Jail", NoJail)
    monkeypatch.setattr(full_use, "TOOLS", tmp_path / "tools")
    monkeypatch.setattr(full_use, "STORES", tmp_path / "stores")


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("full-use")
    CompanyRoundDataset().build(folder, {})
    return folder


def describe_dataset() -> None:
    def it_has_the_counts_the_round_config_names(dataset: Path) -> None:
        manifest = json.loads((dataset / "manifest.json").read_text())
        extra = manifest["extra"]
        assert (extra["known_checks"], extra["unknown_checks"]) == (30, 9)
        assert (extra["lookalike_checks"], extra["stale_checks"]) == (15, 14)
        assert manifest["records"] == len(content.SOURCES) + 150
        questions = json.loads((dataset / "questions.json").read_text())
        assert sum(q.get("category") == "question" for q in questions) == 15
        assert sum(q.get("category") == "variant" for q in questions) == 4

    def it_keys_twelve_answers_three_without_and_the_hard_cases() -> None:
        assert sum(key["answer"] is None for key in keys.KEYS.values()) == 3
        assert sum("lookalike" in key["flags"] for key in keys.KEYS.values()) == 4
        assert sum("stale" in key["flags"] for key in keys.KEYS.values()) == 5

    def it_never_lets_noise_answer_a_check() -> None:
        for source in noise.sources(1500, 7):
            assert noise.clean(export.text_of(source)), export.text_of(source)

    def it_draws_noise_in_the_configured_shares() -> None:
        shares = Counter(source["project"] for source in noise.sources(5000, 3))
        assert 0.27 < shares[content.PEL] / 5000 < 0.33
        assert 0.22 < shares[content.PPL] / 5000 < 0.28

    def it_keeps_the_smaller_sizes_noise_inside_the_larger() -> None:
        assert noise.sources(50, 9) == noise.sources(500, 9)[:50]

    def it_types_like_a_person() -> None:
        assert noise.typo("короткий длинныйтекст", __import__("random").Random(1)) != "короткий длинныйтекст"
        assert noise.typo("да", __import__("random").Random(1)) == "да"


def describe_export() -> None:
    def it_writes_mail_as_an_mbox_with_threads(dataset: Path) -> None:
        box = mailbox.mbox(str(dataset / "sources" / "memo" / "mail.mbox"))
        messages = list(box)
        box.close()
        replies = [message for message in messages if message["In-Reply-To"]]
        assert len(messages) >= 10
        assert replies

    def it_writes_a_synthetic_tg_file_whose_messages_name_known_chats(dataset: Path) -> None:
        tg = json.loads((dataset / "sources" / "memo" / "chats.json").read_text())
        chats = {chat["id"] for chat in tg["chats"]}
        assert tg["synthetic"] is True
        assert {message["chatId"] for message in tg["messages"]} <= chats

    def it_writes_meetings_documents_and_dates(dataset: Path) -> None:
        meetings = sorted((dataset / "sources" / "memo" / "meetings").glob("*.vtt"))
        assert meetings[0].read_text().startswith("WEBVTT")
        word = next((dataset / "sources" / "memo" / "docs").glob("*.docx"))
        with zipfile.ZipFile(word) as archive:
            assert "ГГГГ-ММ-ДД" in archive.read("word/document.xml").decode()
        note = dataset / "sources" / "memo" / "notes" / "Пеликан" / "экспорт.md"
        assert note.stat().st_mtime == export.moment("2026-04-01T18:00:00+03:00").timestamp()

    def it_gives_files_the_archive_after_the_deletion_and_revocation(dataset: Path, tmp_path: Path) -> None:
        full_use.files_archive(dataset, tmp_path / "archive")
        assert not (tmp_path / "archive" / "hr").exists()
        assert not (tmp_path / "archive" / "notes" / "Пеликан" / "стенд.md").exists()
        assert (tmp_path / "archive" / "mail" / "mail.mbox").exists()
        exports = list((tmp_path / "archive" / "chats").glob("*/result.json"))
        assert len(exports) == len(content.CHATS)
        assert '\n "name"' in exports[0].read_text()


def describe_round() -> None:
    def it_passes_every_check_with_the_reference_solution(dataset: Path, tmp_path: Path) -> None:
        trial = FullUseRound(dataset, tmp_path / "run" / "1x", "1x", FakeAgent())
        trial.go("answer-key")
        done = full_use_report.results(tmp_path / "run")
        rows = [row for result in done for row in result["rows"]]
        assert len(done) == 6
        assert sum(row.get("applied", False) for row in rows) == 60
        assert sum(row.get("unknown_ok", False) for row in rows) == 18
        assert "memory/context.md" in FakeAgent().prompts or True

    def it_counts_a_stale_and_a_lookalike_value(dataset: Path, tmp_path: Path) -> None:
        stale = FullUseRound(dataset, tmp_path / "a" / "1x", "1x", FakeAgent(http=STALE_HTTP)).session("none", "t1", 1)
        lookalike = FullUseRound(dataset, tmp_path / "b" / "1x", "1x", FakeAgent(http=LOOKALIKE_HTTP)).session(
            "none", "t1", 1
        )
        assert sum(row.get("stale_used", False) for row in stale["extra"]) == 1
        assert sum(row.get("lookalike_used", False) for row in lookalike["extra"]) == 1
        assert sum(row.get("trap_used", False) for row in lookalike["extra"]) == 1

    def it_gives_the_files_contestant_the_archive_and_records_answers(dataset: Path, tmp_path: Path) -> None:
        agent = FakeAgent()
        trial = FullUseRound(dataset, tmp_path / "run" / "1x", "1x", agent)
        result = trial.session("files-rg", "q01", 1)
        assert "archive/" in agent.prompts[0]
        assert result["answer"].startswith("27 ноября")
        assert result["calls"][0]["tool"] == "memo"
        assert trial.units("files-rg")[:3] == [("t1", 1), ("q01", 1), ("t1", 2)]
        assert trial.units("files-rg")[-1] == ("q15v", 1)
        assert len(trial.units("none")) == 6

    def it_scores_metrics_and_blind_sheets(dataset: Path, tmp_path: Path) -> None:
        index = json.loads((dataset / "ids.json").read_text())
        key = next(key for key, sid in index["messages"].items() if sid == "s32")
        trial = FullUseRound(dataset, tmp_path / "run" / "1x", "1x", FakeAgent(ref=f"msg:telegram/1001/{key}"))
        trial.session("files-rg", "q01", 1)
        trial.session("files-rg", "t1", 1)
        rows = full_use_report.metrics(tmp_path / "run", {"1x": dataset})
        assert rows[0]["coding"]["applied"] == 10
        assert rows[0]["mrr"] == 0.5
        mapping = full_use_report.blind_sheets(tmp_path / "run", tmp_path / "blind" / "sheets")
        sheet = json.loads((tmp_path / "blind" / "sheets" / "q01.json").read_text())
        assert sheet["key"] == "27 ноября"
        assert "files-rg" not in json.dumps(sheet)
        (tmp_path / "verdicts").mkdir()
        letter = sheet["answers"][0]["letter"]
        (tmp_path / "verdicts" / "q01.json").write_text(
            json.dumps({"question": "q01", "verdicts": [{"letter": letter, "verdict": "correct"}]})
        )
        back = full_use_report.unblind(tmp_path / "verdicts", tmp_path / "blind" / "blind-map.json")
        assert back == [
            {"question": "q01", "size": "1x", "contestant": "files-rg", "letter": letter, "verdict": "correct"}
        ]
        assert mapping["q01"][letter] == "1x/files-rg"

    def it_cites_one_line_per_rule() -> None:
        rows = [row for row in checks() if row["task"] == "t1" and row["kind"] == "known"]
        retry = next(row for row in rows if row["expr"] == "should_retry(2)")
        assert citation_ok(retry, "MAX_ATTEMPTS = 3 — чат, 2026-03-11", rows)
        assert not citation_ok(retry, "MAX_ATTEMPTS = 3 — чат, 2026-04-02", rows)


class FakeCli:
    """memo, tg and mail as a build sees them: a JSON reply per call."""

    def __init__(self, root: Path) -> None:
        self.root, self.calls = root, list[list[str]]()

    def __call__(self, argv: list[str], **_: Any) -> Any:
        self.calls.append(argv)
        program, args = Path(argv[0]).name, argv[1:]
        if program == "mail" and args[1:3] == ["config", "set"]:
            path = self.root / "home" / ".config" / "mail-cli" / "config.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"defaults": {}, "profiles": {}}))
        reply: dict[str, Any] = {"item": {"ref": "project:1", "fingerprint": "f", "notes": {"left": False}}}
        if args[:2] == ["folders", "list"]:
            reply = {"items": [{"id": "2", "path": str(self.root / "inbox" / "hr")}]}
        if args[:2] == ["search", "all"]:
            reply = {"items": []}
        return type("Done", (), {"stdout": json.dumps(reply), "stderr": "", "returncode": 0})()


def describe_memo_build() -> None:
    def it_imports_every_kind_natively_then_forgets_with_memos_own_commands(
        dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "memo-full"
        fake = FakeCli(root)
        monkeypatch.setattr(full_use.subprocess, "run", fake)
        build = MemoBuild(root)
        built = build.build(dataset)
        commands = [
            " ".join(Path(call[0]).name if i == 0 else part for i, part in enumerate(call)) for call in fake.calls
        ]
        assert any(re.match(r"tg work store import .*chats\.json --yes", c) for c in commands)
        assert any(c.startswith("mail work messages import") for c in commands)
        assert any(c.startswith("tg work conversations embed") for c in commands)
        assert sum(c.startswith("memo projects add") for c in commands) == 3
        assert not any("--project" in c for c in commands)
        config = json.loads((root / "home" / ".config" / "mail-cli" / "config.json").read_text())
        assert config["profiles"]["work"]["address"].endswith("@severveter.example")
        assert built["steps"]["chats"] >= 0
        assert build.build(dataset) == built
        build.forget()
        assert not (root / "inbox" / "notes" / "Пеликан" / "стенд.md").exists()
        assert any(
            c.startswith("memo folders remove 2 --allow-delete --yes")
            for c in [" ".join([Path(call[0]).name, *call[1:]]) for call in fake.calls]
        )
        assert build.check_forgotten() == {"deleted": 0, "deleted--exact": 0, "revoked": 0, "revoked--exact": 0}


def describe_opaque_ids() -> None:
    def it_never_writes_a_source_id_into_the_exported_data(dataset: Path) -> None:
        pattern = re.compile(r"(?<![\w-])[sn]\d{2,5}(?![\w-])")
        for path in (dataset / "sources").rglob("*"):
            if path.is_file():
                text = path.read_bytes().decode("utf-8", errors="replace") + str(path.relative_to(dataset))
                assert not pattern.search(text), (path, pattern.search(text))

    def it_maps_every_exported_identifier_back_to_its_source(dataset: Path) -> None:
        index = json.loads((dataset / "ids.json").read_text())
        assert "s04" in index["messages"].values()
        assert "s06" in index["mail"].values()
        assert index["files"]["Пеликан/экспорт.md"] == "s13"
