from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from wcatbench.cli import app
from wcatbench.config import get_settings
from wcatbench.core import dataset_files
from wcatbench.core.errors import PermanentError, PrivacyError
from wcatbench.core.types import BatchReceipt, Hit, ItemState, Record
from wcatbench.datasets.synthetic import SyntheticDataset
from wcatbench.pipeline.build import Build, Selection
from wcatbench.pipeline.search import keywords
from wcatbench.stores.fts import FtsStore


class QueueStore:
    """A hosted store that takes `polls` checks to finish a record, refuses some keys, and settles late."""

    name = "queue"
    hosted = True

    def __init__(self, polls: int = 1, refuse: frozenset[str] = frozenset(), settle_after: int = 0) -> None:
        self.polls, self.refuse, self.settle_after = polls, refuse, settle_after
        self.items: dict[str, int] = {}
        self.sent: list[str] = []
        self.checks = 0
        self.started: datetime | None = None

    def version(self) -> str:
        return "1"

    def open(self, space: str, workdir: Path, started: datetime) -> None:
        self.started = started

    def ingest(self, batch: Sequence[Record]) -> BatchReceipt:
        keys = [record.key for record in batch]
        self.sent += keys
        for key in keys:
            self.items[key] = -1 if key in self.refuse else 0
        return BatchReceipt(sent=tuple(keys), refused={key: "no" for key in keys if key in self.refuse})

    def held(self) -> dict[str, ItemState]:
        self.checks += 1
        for key, age in self.items.items():
            if age >= 0:
                self.items[key] = age + 1
        return {
            key: ItemState.FAILED if age < 0 else ItemState.DONE if age > self.polls else ItemState.QUEUED
            for key, age in self.items.items()
        }

    def settled(self, held: dict[str, ItemState]) -> bool:
        return self.checks > self.settle_after

    def search(self, query: str, k: int) -> list[Hit]:
        return []

    def describe(self) -> dict[str, object]:
        return {"documents": len(self.items)}

    def clear(self) -> None:
        self.items.clear()

    def close(self) -> None:
        pass


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("2k")
    SyntheticDataset().build(folder, {})
    return folder


def make(store: QueueStore | FtsStore, dataset: Path, folder: Path, records: int = 250) -> Build:
    selection = Selection(dataset_files.records(dataset)[:records])
    return Build(store, dataset, "space", folder, selection, sleep=lambda _: None)


def describe_records() -> None:
    def it_names_records_by_place_without_changing_the_corpus_file(dataset: Path) -> None:
        records = dataset_files.records(dataset)
        assert [record.key for record in records[:2]] == ["r0001", "r0002"]
        assert dataset_files.corpus_lines(records) == (dataset / dataset_files.CORPUS).read_text()

    def it_rewrites_a_question_as_keywords_like_the_published_runs() -> None:
        assert keywords("What is the current date for Amber Kite?") == '"current" OR "date" OR "amber" OR "kite"'


def describe_build() -> None:
    def it_sends_in_batches_and_waits_until_every_record_is_final_and_settled(dataset: Path, tmp_path: Path) -> None:
        store = QueueStore(polls=2, settle_after=4)
        summary = make(store, dataset, tmp_path).run(resume=False, wait_seconds=3600, poll_seconds=1)
        lines = (tmp_path / "ledger.jsonl").read_text().splitlines()
        assert [json.loads(line)["sent"] for line in lines] == [100, 100, 50]
        assert summary["by_status"] == {"done": 250}
        assert summary["settled"] is True
        assert store.checks == 5

    def it_stops_waiting_at_the_deadline_and_says_so(dataset: Path, tmp_path: Path) -> None:
        build = make(QueueStore(polls=99), dataset, tmp_path)
        summary = build.run(resume=False, wait_seconds=0, poll_seconds=1)
        assert summary["deadline_reached"] is True
        assert summary["by_status"] == {"queued": 250}

    def it_resumes_by_sending_only_failed_records_never_queued_ones(dataset: Path, tmp_path: Path) -> None:
        store = QueueStore(polls=99, refuse=frozenset({"r0003"}))
        make(store, dataset, tmp_path, records=100).run(resume=False, wait_seconds=0, poll_seconds=1)
        store.sent.clear()
        make(store, dataset, tmp_path, records=100).run(resume=True, wait_seconds=0, poll_seconds=1)
        assert store.sent == ["r0003"]

    def it_does_not_resend_an_accepted_record_the_store_stopped_listing(dataset: Path, tmp_path: Path) -> None:
        store = QueueStore(polls=99)
        make(store, dataset, tmp_path, records=10).run(resume=False, wait_seconds=0)
        del store.items["r0004"]
        store.sent.clear()
        summary = make(store, dataset, tmp_path, records=10).run(resume=True, wait_seconds=0)
        assert store.sent == []
        assert summary["accepted_not_listed"] == 1

    def it_imports_the_ledger_of_the_earlier_scripts(dataset: Path, tmp_path: Path) -> None:
        old = tmp_path / "old.jsonl"
        lines = [
            {
                "at": "x",
                "batch": 0,
                "rids": ["r0001", "r0002"],
                "sent": 2,
                "failed": [{"rid": "r0002", "error": "e"}],
                "s": 1.0,
            },
            {"at": "x", "note": "not a batch"},
        ]
        old.write_text("".join(json.dumps(line) + "\n" for line in lines))
        build = make(QueueStore(), dataset, tmp_path / "build", records=10)
        build.open(resume=True)
        assert build.import_ledger(old) == 1
        assert build.sent_before() == {"r0001"}
        with pytest.raises(PermanentError, match="not empty"):
            build.import_ledger(old)

    def it_adopts_a_build_known_to_have_sent_everything(dataset: Path, tmp_path: Path) -> None:
        build = make(QueueStore(), dataset, tmp_path, records=10)
        build.open(resume=True)
        with pytest.raises(PermanentError, match="no ledger"):
            build.import_ledger(tmp_path / "missing.jsonl")
        build.adopt_all_sent()
        assert len(build.sent_before()) == 10
        assert build.to_resend({}, build.selection.records) == []

    def it_refuses_to_resume_with_another_selection(dataset: Path, tmp_path: Path) -> None:
        make(QueueStore(), dataset, tmp_path, records=100).run(resume=False, wait_seconds=0)
        with pytest.raises(PermanentError, match="records differ"):
            make(QueueStore(), dataset, tmp_path, records=150).run(resume=True, wait_seconds=0)

    def it_records_refusals_in_the_ledger(dataset: Path, tmp_path: Path) -> None:
        make(QueueStore(refuse=frozenset({"r0001"})), dataset, tmp_path, 10).run(resume=False, wait_seconds=0)
        entry = json.loads((tmp_path / "ledger.jsonl").read_text())
        assert entry["refused"] == {"r0001": "no"}

    def it_refuses_to_start_over_an_existing_build(dataset: Path, tmp_path: Path) -> None:
        make(QueueStore(), dataset, tmp_path, 10).run(resume=False, wait_seconds=0)
        with pytest.raises(PermanentError, match="--resume"):
            make(QueueStore(), dataset, tmp_path, 10).run(resume=False, wait_seconds=0)

    def it_keeps_the_start_time_of_the_first_run(dataset: Path, tmp_path: Path) -> None:
        first = datetime(2026, 11, 5, 2, 37, 35, tzinfo=UTC)
        make(QueueStore(), dataset, tmp_path, 10).open(resume=True, started=first)
        store = QueueStore()
        make(store, dataset, tmp_path, 10).open(resume=True, started=datetime.now(UTC))
        assert store.started == first

    def it_refuses_a_private_dataset_for_a_hosted_store(dataset: Path, tmp_path: Path) -> None:
        private = tmp_path / "private"
        private.mkdir()
        for name in (dataset_files.CORPUS, dataset_files.QUESTIONS, dataset_files.KEY):
            (private / name).write_bytes((dataset / name).read_bytes())
        manifest = json.loads((dataset / dataset_files.MANIFEST).read_text()) | {"privacy": "private"}
        (private / dataset_files.MANIFEST).write_text(json.dumps(manifest))
        with pytest.raises(PrivacyError):
            make(QueueStore(), private, tmp_path / "build")

    def it_loads_a_named_subset_and_checks_its_digest(tmp_path: Path) -> None:
        SyntheticDataset().build(tmp_path, {"records": 10000})
        selection = Selection.load(tmp_path, "mem0")
        assert len(selection.records) == 6500
        assert selection.records[0].key.startswith("r")
        with pytest.raises(PermanentError, match="no subset"):
            Selection.load(tmp_path, "zep")


def describe_store_commands() -> None:
    @pytest.fixture(autouse=True)
    def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setenv("WCATBENCH_HOME", str(tmp_path))
        get_settings.cache_clear()
        return tmp_path

    def it_builds_checks_and_searches_the_local_fts_store() -> None:
        runner = CliRunner()
        built = runner.invoke(app, ["dataset", "build", "synthetic"])
        name = Path(built.stdout.splitlines()[0]).name
        args = ["--dataset", name, "--space", "kg"]
        build = runner.invoke(app, ["store", "build", "fts", *args, "--wait-minutes", "0"])
        status = runner.invoke(app, ["store", "status", "fts", *args])
        search = runner.invoke(app, ["store", "search", "fts", *args, "--rewrite", "keywords"])
        get_settings.cache_clear()
        assert build.exit_code == 0, build.output
        assert '"settled": true' in build.stdout
        assert '"done": 2000' in status.stdout
        assert search.exit_code == 0, search.output
        assert "keywords: recall@1" in search.stdout

    def it_explains_a_missing_dataset() -> None:
        result = CliRunner().invoke(app, ["store", "status", "fts", "--dataset", "nothing", "--space", "kg"])
        get_settings.cache_clear()
        assert result.exit_code == 2
        assert "dataset build" in result.stderr
