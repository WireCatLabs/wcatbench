from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from wcatbench.observability.logging import add_events_file, log_context, setup_logging
from wcatbench.observability.redaction import REDACTED


def describe_events_file() -> None:
    def it_writes_redacted_json_with_the_run_context(tmp_path: Path) -> None:
        setup_logging("json", "WARNING")
        sink = add_events_file(tmp_path / "events.jsonl")
        with log_context(run_id="run-1", setup="hermes+memo"):
            logger.bind(api_key="sk-live-abcdefgh", records=3).info("ingested")
        logger.remove(sink)
        line = json.loads((tmp_path / "events.jsonl").read_text().splitlines()[0])
        assert line["run_id"] == "run-1"
        assert line["setup"] == "hermes+memo"
        assert line["extra"] == {"api_key": REDACTED, "records": 3}

    def it_restores_the_outer_context(tmp_path: Path) -> None:
        sink = add_events_file(tmp_path / "events.jsonl")
        with log_context(run_id="outer"):
            with log_context(run_id="inner"):
                pass
            logger.info("after")
        logger.remove(sink)
        assert json.loads((tmp_path / "events.jsonl").read_text())["run_id"] == "outer"
