from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from wcatbench.core import dataset_files
from wcatbench.core.types import AgentReply
from wcatbench.datasets.synthetic import SyntheticDataset
from wcatbench.scoring.answer import AnswerScorer

PUBLISHED = json.loads((Path(__file__).parent / "fixtures" / "published-2k-predictions.json").read_text())


@pytest.fixture(scope="module")
def built_2k(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("2k")
    SyntheticDataset().build(folder, {})
    return folder


def describe_rescoring_the_published_2k_round() -> None:
    @pytest.mark.parametrize("row", PUBLISHED["rows"], ids=[row["setup"] for row in PUBLISHED["rows"]])
    def it_gives_the_published_numbers(built_2k: Path, row: dict[str, Any]) -> None:
        keys = dataset_files.keys(built_2k)
        scorer = AnswerScorer()
        counts: Counter[str] = Counter()
        for prediction in row["predictions"]:
            reply = AgentReply(answer=prediction["answer"], sources=tuple(prediction["citations"]))
            counts.update(name for name, hit in scorer.score(reply, keys[prediction["id"]]).items() if hit)
        assert {name: counts[name] for name in row["published"]} == row["published"]
