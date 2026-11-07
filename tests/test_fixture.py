from __future__ import annotations

import json
from pathlib import Path

import pytest

from wcatbench.core import dataset_files
from wcatbench.core.errors import PermanentError
from wcatbench.datasets.synthetic import SyntheticDataset
from wcatbench.pipeline.fixture import export_fixture, score_predictions


@pytest.fixture(scope="module")
def v3(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("v3")
    SyntheticDataset().build(folder, {"records": 10000, "version": 3})
    return folder


def oracle_answers(fixture: Path) -> list[dict[str, object]]:
    rows = json.loads((fixture / "oracle.json").read_text())
    return [{"id": row["id"], "answer": row["answers"][0], "citations": row["required_citations"]} for row in rows]


def describe_agent_runner_bridge() -> None:
    def it_writes_the_files_the_runners_read_without_answers_in_the_queries(v3: Path, tmp_path: Path) -> None:
        manifest = export_fixture(v3, tmp_path / "fixture")
        queries = (tmp_path / "fixture" / "queries.json").read_text()
        assert manifest["fixture_version"] == 3
        assert manifest["sha256"] == dataset_files.manifest(v3).corpus_sha256
        assert "answers" not in queries
        assert len(json.loads(queries)) == 50

    def it_scores_the_oracle_on_everything_by_family(v3: Path, tmp_path: Path) -> None:
        export_fixture(v3, tmp_path / "fixture")
        scores = score_predictions(v3, oracle_answers(tmp_path / "fixture"), "oracle", tmp_path / "score")
        assert (scores["correct"], scores["cited_correctly"], scores["stale"]) == (50, 50, 0)
        assert sum(family["questions"] for family in scores["by_family"].values()) == 50
        assert json.loads((tmp_path / "score" / "manifest.json").read_text())["records"] == 10444

    def it_refuses_predictions_that_skip_a_question(v3: Path, tmp_path: Path) -> None:
        export_fixture(v3, tmp_path / "fixture")
        with pytest.raises(PermanentError, match="every question"):
            score_predictions(v3, oracle_answers(tmp_path / "fixture")[1:], "oracle", tmp_path / "score")
