from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from wcatbench.agents.noop import NoopAgent
from wcatbench.agents.oracle import OracleAgent
from wcatbench.cli import app
from wcatbench.config import get_settings
from wcatbench.core import dataset_files
from wcatbench.core.errors import PermanentError
from wcatbench.core.types import Privacy
from wcatbench.datasets.synthetic import SyntheticDataset
from wcatbench.pipeline.build import Selection
from wcatbench.scoring.answer import AnswerScorer

# The digests published with the cli-testing rounds. A change here means the old results no longer name this data.
CORPUS_2K = "1d36697c60e6f9ebad2074e9d0d45499c3ef78d5a798e50473238394af5e8802"
CORPUS_10K = "e99e1e524875a7ca087f90952f061aac70856bdfbbe56d3915de1bd4c1f6b8f0"
MEM0_SUBSET_10K = "6273370e89cb74e034e6e7e72f683975e3da4d87feae9f3c0fd5b245268cb973"


@pytest.fixture(scope="module")
def built_10k(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("10k")
    SyntheticDataset().build(folder, {"records": 10000})
    return folder


def totals(folder: Path, agent: OracleAgent | NoopAgent) -> Counter[str]:
    keys = dataset_files.keys(folder)
    scorer = AnswerScorer()
    counts: Counter[str] = Counter()
    for question in dataset_files.questions(folder):
        key = keys[question.id]
        counts.update(name for name, hit in scorer.score(agent.ask(question, key), key).items() if hit)
    return counts


def describe_synthetic_dataset() -> None:
    def it_reproduces_the_published_2k_corpus(tmp_path: Path) -> None:
        manifest = SyntheticDataset().build(tmp_path, {})
        assert manifest.corpus_sha256 == CORPUS_2K
        assert (manifest.version, manifest.records, manifest.questions) == (1, 2000, 50)
        assert manifest.privacy is Privacy.SYNTHETIC

    def it_reproduces_the_published_10k_corpus_and_mem0_subset(built_10k: Path) -> None:
        manifest = dataset_files.manifest(built_10k)
        subset = json.loads((built_10k / "subset-mem0.json").read_text())
        assert manifest.corpus_sha256 == CORPUS_10K
        assert subset["sha256"] == MEM0_SUBSET_10K
        assert subset["records"] == 6500

    def it_keeps_the_answers_out_of_the_questions_file(built_10k: Path) -> None:
        text = (built_10k / dataset_files.QUESTIONS).read_text()
        assert "answers" not in text
        assert "stale" not in text

    def it_scores_the_oracle_on_everything_and_the_noop_on_nothing(built_10k: Path) -> None:
        assert totals(built_10k, OracleAgent()) == {"correct": 50, "correct_strict": 50, "cited_correctly": 50}
        assert totals(built_10k, NoopAgent()) == Counter()

    def it_refuses_a_corpus_that_no_longer_matches_its_manifest(built_10k: Path, tmp_path: Path) -> None:
        for name in (dataset_files.CORPUS, dataset_files.MANIFEST):
            (tmp_path / name).write_bytes((built_10k / name).read_bytes())
        with (tmp_path / dataset_files.CORPUS).open("a") as corpus:
            corpus.write('{"id": "x", "kind": "notes", "timestamp": "2026-01-01", "text": "added later"}\n')
        with pytest.raises(PermanentError, match="does not match"):
            dataset_files.records(tmp_path)

    def it_reads_back_every_record(built_10k: Path) -> None:
        assert len(dataset_files.records(built_10k)) == 10000

    def it_refuses_a_size_between_the_two_corpora(tmp_path: Path) -> None:
        with pytest.raises(PermanentError, match="at least 3000"):
            SyntheticDataset().build(tmp_path, {"records": 2500})


def describe_version_3() -> None:
    @pytest.fixture(scope="module")
    def built_v3(tmp_path_factory: pytest.TempPathFactory) -> Path:
        folder = tmp_path_factory.mktemp("v3")
        SyntheticDataset().build(folder, {"records": 10000, "version": 3})
        return folder

    def it_keeps_the_10k_corpus_byte_for_byte_and_appends_after_it(built_v3: Path) -> None:
        lines = (built_v3 / dataset_files.CORPUS).read_bytes().splitlines(keepends=True)
        assert hashlib.sha256(b"".join(lines[:10000])).hexdigest() == CORPUS_10K
        assert dataset_files.manifest(built_v3).version == 3
        assert len(lines) > 10000

    def it_asks_50_different_questions_of_many_kinds(built_v3: Path) -> None:
        kinds = json.loads((built_v3 / "kinds.json").read_text())
        texts = [question.text for question in dataset_files.questions(built_v3)]
        assert len(set(texts)) == 50
        assert len({row["kind"] for row in kinds}) == 21
        assert max(Counter(row["kind"] for row in kinds).values()) == 3

    def it_scores_the_oracle_on_everything(built_v3: Path) -> None:
        assert totals(built_v3, OracleAgent()) == {"correct": 50, "correct_strict": 50, "cited_correctly": 50}

    def it_cites_only_records_that_exist(built_v3: Path) -> None:
        ids = {record.id for record in dataset_files.records(built_v3)}
        assert all(set(key.sources) <= ids for key in dataset_files.keys(built_v3).values())

    def it_grows_the_mem0_subset_by_every_new_record(built_v3: Path) -> None:
        subset = json.loads((built_v3 / "subset-mem0.json").read_text())
        assert subset["records"] == 6500 + dataset_files.manifest(built_v3).records - 10000
        assert len(Selection.load(built_v3, "mem0").records) == subset["records"]


def describe_paraphrased_questions() -> None:
    def it_rewords_18_questions_over_the_same_records_and_key(tmp_path: Path) -> None:
        plain, reworded = tmp_path / "plain", tmp_path / "reworded"
        plain.mkdir(), reworded.mkdir()
        first = SyntheticDataset().build(plain, {"records": 10000, "version": 3})
        second = SyntheticDataset().build(reworded, {"records": 10000, "version": 3, "paraphrase": 1})
        before, after = dataset_files.questions(plain), dataset_files.questions(reworded)
        changed = [q.id for q, p in zip(before, after, strict=True) if q.text != p.text]
        marked = [row["id"] for row in json.loads((reworded / "kinds.json").read_text()) if row.get("paraphrased")]
        assert first.corpus_sha256 == second.corpus_sha256
        assert first.key_sha256 == second.key_sha256
        assert len(changed) == 18
        assert changed == marked


def describe_dataset_build_command() -> None:
    @pytest.fixture(autouse=True)
    def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
        monkeypatch.setenv("WCATBENCH_HOME", str(tmp_path))
        get_settings.cache_clear()
        yield tmp_path
        get_settings.cache_clear()

    def it_names_the_folder_by_digest_and_builds_it_once(home: Path) -> None:
        first = CliRunner().invoke(app, ["dataset", "build", "synthetic"])
        again = CliRunner().invoke(app, ["dataset", "build", "synthetic", "-p", "records=2000"])
        assert first.exit_code == 0, first.output
        assert first.stdout == again.stdout
        assert [path.name for path in (home / "datasets").iterdir()] == [f"synthetic-2000-{CORPUS_2K[:8]}"]

    def it_rejects_a_parameter_that_is_not_a_number() -> None:
        result = CliRunner().invoke(app, ["dataset", "build", "synthetic", "-p", "records=many"])
        assert result.exit_code == 2

    def it_reports_a_dataset_that_refuses_its_parameters() -> None:
        result = CliRunner().invoke(app, ["dataset", "build", "synthetic", "-p", "records=2500"])
        assert result.exit_code == 2
        assert "at least 3000" in result.stderr
