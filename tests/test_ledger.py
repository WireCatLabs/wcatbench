from __future__ import annotations

from pathlib import Path

from wcatbench.core.ledger import Ledger


def describe_ledger() -> None:
    def it_names_every_finished_unit(tmp_path: Path) -> None:
        ledger = Ledger(tmp_path / "ledger.jsonl")
        ledger.write("batch-0", sent=100)
        ledger.write("batch-1", sent=100)
        assert ledger.done() == {"batch-0", "batch-1"}

    def it_survives_a_torn_last_line(tmp_path: Path) -> None:
        path = tmp_path / "ledger.jsonl"
        Ledger(path).write("batch-0", sent=100)
        with path.open("a") as out:
            out.write('{"unit": "batch-1", "se')
        assert Ledger(path).done() == {"batch-0"}

    def it_is_empty_before_the_first_unit(tmp_path: Path) -> None:
        assert Ledger(tmp_path / "missing.jsonl").done() == set()
