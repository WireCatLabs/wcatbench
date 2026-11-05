from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from wcatbench.core import dataset_files
from wcatbench.datasets.synthetic import SyntheticDataset
from wcatbench.scoring.retrieval import SearchRow, score_search

PUBLISHED = json.loads((Path(__file__).parent / "fixtures" / "published-2k-search.json").read_text())


@pytest.fixture(scope="module")
def built_2k(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("2k")
    SyntheticDataset().build(folder, {})
    return folder


def describe_rescoring_the_published_2k_searches() -> None:
    @pytest.mark.parametrize("row", PUBLISHED["rows"], ids=[row["setup"] for row in PUBLISHED["rows"]])
    def it_gives_the_published_recall(built_2k: Path, row: dict[str, Any]) -> None:
        rows = [SearchRow(**search) for search in row["searches"]]
        scores = score_search(rows, dataset_files.keys(built_2k))
        assert {name: scores[name] for name in row["published"]} == pytest.approx(row["published"])
