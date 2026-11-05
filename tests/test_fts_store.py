from __future__ import annotations

from pathlib import Path

from wcatbench.core.protocols import Store
from wcatbench.core.types import ItemState, Record
from wcatbench.stores.fts import FtsStore


def describe_fts_store() -> None:
    def it_is_a_store() -> None:
        assert isinstance(FtsStore(), Store)

    def it_finds_a_record_from_a_question_typed_as_a_sentence(tmp_path: Path, records: list[Record]) -> None:
        store = FtsStore()
        store.open("space", tmp_path)
        store.ingest(records)
        hits = store.search("Who owns Amber Kite?", k=2)
        store.close()
        assert hits[0].record_ids == ("r0001",)

    def it_holds_each_record_once_after_a_resend(tmp_path: Path, records: list[Record]) -> None:
        store = FtsStore()
        store.open("space", tmp_path)
        store.ingest(records)
        store.ingest(records[:1])
        assert store.held() == {record.id: ItemState.DONE for record in records}
        assert store.describe() == {"records": 3}
        store.close()

    def it_finds_nothing_for_a_query_without_words(tmp_path: Path) -> None:
        store = FtsStore()
        store.open("space", tmp_path)
        assert store.search("?!", k=5) == []
        store.clear()
        store.close()
