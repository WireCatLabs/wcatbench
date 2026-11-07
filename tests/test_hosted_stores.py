from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from wcatbench.core.errors import PermanentError, TransientError
from wcatbench.core.http import JsonApi
from wcatbench.core.protocols import Store
from wcatbench.core.types import ItemState, Record
from wcatbench.stores.cognee import CogneeStore
from wcatbench.stores.hindsight import HindsightStore
from wcatbench.stores.honcho import HonchoStore
from wcatbench.stores.letta import LettaStore
from wcatbench.stores.mem0 import Mem0Store
from wcatbench.stores.supermemory import SupermemoryStore

STARTED = datetime(2026, 11, 5, 2, 37, 35, tzinfo=UTC)
Handler = Callable[[httpx.Request], httpx.Response]


def record(n: int) -> Record:
    return Record(id=f"id-{n}", kind="notes", timestamp="2026-01-05T09:00:00Z", text=f"text {n}", name=f"r{n:04}")


class Calls:
    """A fake service: answers by method and path, and keeps every request for the test to read."""

    def __init__(self, routes: dict[str, Callable[[httpx.Request], Any]]) -> None:
        self.routes, self.seen = routes, list[httpx.Request]()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        route = f"{request.method} {request.url.path}"
        reply = self.routes[route](request)
        return reply if isinstance(reply, httpx.Response) else httpx.Response(200, json=reply)

    def bodies(self, route: str) -> list[Any]:
        return [json.loads(r.content) for r in self.seen if f"{r.method} {r.url.path}" == route]


def supermemory(calls: Calls, tmp_path: Path) -> SupermemoryStore:
    store = SupermemoryStore(api_key="sm-test-key", transport=httpx.MockTransport(calls), sleep=lambda _: None)
    store.open("wirecat_bench_20261105_023737", tmp_path, STARTED)
    return store


def mem0(calls: Calls, tmp_path: Path) -> Mem0Store:
    store = Mem0Store(api_key="m0-test-key", transport=httpx.MockTransport(calls))
    store.open("wirecat_bench_20261105_023735", tmp_path, STARTED)
    return store


def describe_json_api() -> None:
    @pytest.fixture(autouse=True)
    def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(JsonApi.request.retry, "sleep", lambda _: None)  # type: ignore[attr-defined]

    def it_retries_a_rate_limit_and_then_succeeds() -> None:
        replies = iter([httpx.Response(429), httpx.Response(200, json={"ok": True})])
        api = JsonApi("https://x.test", "Bearer k", httpx.MockTransport(lambda _: next(replies)))
        assert api.request("GET", "/a") == {"ok": True}
        assert api.calls == 2

    def it_gives_up_on_a_service_that_stays_down() -> None:
        api = JsonApi("https://x.test", "Bearer k", httpx.MockTransport(lambda _: httpx.Response(503)))
        with pytest.raises(TransientError):
            api.request("GET", "/a")
        assert api.calls == 4

    def it_does_not_retry_a_refusal_and_keeps_the_key_out_of_the_message() -> None:
        api = JsonApi(
            "https://x.test", "Bearer sk-secret", httpx.MockTransport(lambda _: httpx.Response(401, text="no"))
        )
        with pytest.raises(PermanentError) as error:
            api.request("GET", "/a")
        assert api.calls == 1
        assert "sk-secret" not in str(error.value)

    def it_treats_a_timeout_as_transient() -> None:
        def slow(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=request)

        api = JsonApi("https://x.test", "Bearer k", httpx.MockTransport(slow))
        with pytest.raises(TransientError, match="timed out"):
            api.request("GET", "/a")


def describe_supermemory_store() -> None:
    def it_is_a_hosted_store() -> None:
        assert isinstance(SupermemoryStore(), Store)
        assert SupermemoryStore.hosted

    def it_sends_the_record_name_as_custom_id_and_metadata(tmp_path: Path) -> None:
        calls = Calls({"POST /v3/documents/batch": lambda _: {"success": True, "results": [{}, {}]}})
        receipt = supermemory(calls, tmp_path).ingest([record(1), record(2)])
        document = calls.bodies("POST /v3/documents/batch")[0]["documents"][0]
        assert document["customId"] == "r0001"
        assert document["metadata"] == {"rid": "r0001"}
        assert document["containerTag"] == "wirecat_bench_20261105_023737"
        assert receipt.sent == ("r0001", "r0002")
        assert calls.seen[0].headers["Authorization"] == "Bearer sm-test-key"

    def it_counts_a_batch_answered_with_one_failure_item_as_refused(tmp_path: Path) -> None:
        failed = {"success": False, "results": [{"status": "error", "error": "Failed to save documents"}]}
        calls = Calls({"POST /v3/documents/batch": lambda _: failed})
        receipt = supermemory(calls, tmp_path).ingest([record(1), record(2)])
        assert len(calls.seen) == 3
        assert set(receipt.refused) == {"r0001", "r0002"}
        assert receipt.sent == ()

    def it_reads_what_the_tag_holds_page_by_page(tmp_path: Path) -> None:
        pages = {
            1: [
                {"id": "d1", "customId": "r0001", "status": "done"},
                {"id": "d2", "customId": "r0002", "status": "queued"},
            ],
            2: [{"id": "d3", "metadata": {"rid": "r0003"}, "status": "failed"}],
        }

        def listing(request: httpx.Request) -> Any:
            page = json.loads(request.content)["page"]
            return {"memories": pages[page], "pagination": {"totalPages": 2}}

        held = supermemory(Calls({"POST /v3/documents/list": listing}), tmp_path).held()
        assert held == {"r0001": ItemState.DONE, "r0002": ItemState.QUEUED, "r0003": ItemState.FAILED}

    def it_is_settled_only_when_the_sampled_memories_are_built(tmp_path: Path) -> None:
        listing = {"memories": [{"id": "d1", "customId": "r0001", "status": "done"}], "pagination": {"totalPages": 1}}
        dreaming = iter(["processing", "done"])
        calls = Calls(
            {
                "POST /v3/documents/list": lambda _: listing,
                "GET /v3/documents/d1": lambda _: {"dreamingStatus": next(dreaming)},
            }
        )
        store = supermemory(calls, tmp_path)
        held = store.held()
        assert store.settled(held) is False
        assert store.settled(held) is True

    def it_names_every_record_a_memory_came_from(tmp_path: Path) -> None:
        result = {"memory": "m", "documents": [{"metadata": {"rid": "r0002"}}, {"metadata": {"rid": "r0001"}}]}
        calls = Calls({"POST /v4/search": lambda _: {"results": [result, {"chunk": "c"}]}})
        hits = supermemory(calls, tmp_path).search("question", 10)
        assert [hit.keys for hit in hits] == [("r0002", "r0001"), ()]
        assert calls.bodies("POST /v4/search")[0]["limit"] == 10

    def it_describes_its_tag_from_either_reply_shape(tmp_path: Path) -> None:
        tag = {"containerTag": "wirecat_bench_20261105_023737", "documentCount": 10000, "memoryCount": 1229}
        for shape in ([tag], {"containerTags": [tag]}):
            store = supermemory(Calls({"GET /v3/container-tags/list": lambda _, shape=shape: shape}), tmp_path)
            assert store.describe()["memories"] == 1229

    def it_never_deletes_a_tag(tmp_path: Path) -> None:
        with pytest.raises(PermanentError, match="never deletes"):
            supermemory(Calls({}), tmp_path).clear()


def event(rid: str, status: str, user: str = "wirecat_bench_20261105_023735", **extra: Any) -> dict[str, Any]:
    return {
        "event_type": "ADD",
        "status": status,
        "created_at": "2026-11-05T02:50:00+00:00",
        "payload": repr({"user_id": user, "metadata": {"rid": rid}}),
        **extra,
    }


def describe_mem0_store() -> None:
    def it_is_a_hosted_store() -> None:
        assert isinstance(Mem0Store(), Store)

    def it_adds_each_record_with_its_name_and_reports_failures_as_refused(tmp_path: Path) -> None:
        def add(request: httpx.Request) -> Any:
            body = json.loads(request.content)
            return httpx.Response(400, text="bad") if body["metadata"]["rid"] == "r0002" else {"status": "PENDING"}

        receipt = mem0(Calls({"POST /v3/memories/add/": add}), tmp_path).ingest([record(1), record(2), record(3)])
        assert receipt.sent == ("r0001", "r0003")
        assert list(receipt.refused) == ["r0002"]

    def it_reads_the_event_feed_back_to_the_build_start(tmp_path: Path) -> None:
        old = event("r0009", "SUCCEEDED") | {"created_at": "2026-11-05T02:00:00+00:00"}
        pages = {
            "1": {
                "results": [
                    event("r0001", "SUCCEEDED"),
                    event("r0002", "PENDING"),
                    event("r0001", "FAILED"),
                    event("r0005", "SUCCEEDED", user="someone_else"),
                    {**event("r0006", "SUCCEEDED"), "event_type": "SEARCH"},
                ],
                "next": "page 2",
            },
            "2": {
                "results": [
                    event(
                        "r0003",
                        "FAILED",
                        payload={"user_id": "wirecat_bench_20261105_023735"},
                        metadata="{'rid': 'r0003'}",
                    ),
                    old,
                    event("r0004", "SUCCEEDED"),
                ]
            },
        }
        calls = Calls({"GET /v1/events/": lambda request: pages[request.url.params["page"]]})
        held = mem0(calls, tmp_path).held()
        assert held == {"r0001": ItemState.DONE, "r0002": ItemState.QUEUED, "r0003": ItemState.FAILED}

    def it_merges_two_walks_so_an_event_that_moved_is_not_missed(tmp_path: Path) -> None:
        walks = iter([[event("r0001", "SUCCEEDED")], [event("r0001", "PENDING"), event("r0002", "SUCCEEDED")]])
        calls = Calls({"GET /v1/events/": lambda _: {"results": next(walks)}})
        held = mem0(calls, tmp_path).held()
        assert held == {"r0001": ItemState.DONE, "r0002": ItemState.DONE}

    def it_maps_search_results_to_record_names(tmp_path: Path) -> None:
        results = {"results": [{"memory": "a", "metadata": {"rid": "r0001"}}, {"memory": "b", "metadata": None}]}
        hits = mem0(Calls({"POST /v3/memories/search/": lambda _: results}), tmp_path).search("q", 10)
        assert [hit.keys for hit in hits] == [("r0001",), ()]

    def it_counts_memories_for_its_user(tmp_path: Path) -> None:
        calls = Calls({"POST /v3/memories/": lambda _: {"count": 2966}})
        assert mem0(calls, tmp_path).describe() == {"memories": 2966}
        assert calls.bodies("POST /v3/memories/")[0] == {"filters": {"user_id": "wirecat_bench_20261105_023735"}}

    def it_needs_open_before_use() -> None:
        with pytest.raises(PermanentError, match="open"):
            Mem0Store().describe()


BANK = "/v1/default/banks/wcatbench_hindsight_pilot100"


def hindsight(calls: Calls, tmp_path: Path) -> HindsightStore:
    store = HindsightStore(base_url="http://hindsight.test", transport=httpx.MockTransport(calls))
    store.open("wcatbench_hindsight_pilot100", tmp_path, STARTED)
    return store


def describe_hindsight_store() -> None:
    def it_retains_each_record_with_its_own_time_and_id(tmp_path: Path) -> None:
        calls = Calls({f"PUT {BANK}": lambda _: {}, f"POST {BANK}/memories": lambda _: {"success": True}})
        receipt = hindsight(calls, tmp_path).ingest([record(1), record(2)])
        (body,) = calls.bodies(f"POST {BANK}/memories")
        assert receipt.sent == ("r0001", "r0002")
        assert body["async"] is True
        assert body["items"][0] == {
            "content": "text 1",
            "timestamp": "2026-01-05T09:00:00Z",
            "context": "notes",
            "document_id": "r0001",
            "metadata": {"rid": "r0001"},
        }

    def it_names_the_records_behind_an_observation(tmp_path: Path) -> None:
        reply = {
            "results": [
                {"id": "f1", "text": "a fact", "type": "world", "document_id": "r0007"},
                {"id": "o1", "text": "an observation", "type": "observation", "source_fact_ids": ["f2", "f3"]},
            ],
            "source_facts": {"f2": {"document_id": "r0002"}, "f3": {"document_id": "r0003"}},
        }
        calls = Calls({f"PUT {BANK}": lambda _: {}, f"POST {BANK}/memories/recall": lambda _: reply})
        hits = hindsight(calls, tmp_path).search("when", 10)
        assert [hit.keys for hit in hits] == [("r0007",), ("r0002", "r0003")]
        assert hits[1].kind == "observation"

    def it_is_settled_only_when_consolidation_is_done_too(tmp_path: Path) -> None:
        stats = iter([{"pending_operations": 0, "pending_consolidation": 3}, {"pending_operations": 0}])
        calls = Calls({f"PUT {BANK}": lambda _: {}, f"GET {BANK}/stats": lambda _: next(stats)})
        store = hindsight(calls, tmp_path)
        assert store.settled({}) is False
        assert store.settled({}) is True


WS = "/v3/workspaces/wcatbench_honcho_pilot"


def honcho(calls: Calls, tmp_path: Path) -> HonchoStore:
    store = HonchoStore(base_url="http://honcho.test", transport=httpx.MockTransport(calls))
    store.open("wcatbench_honcho_pilot", tmp_path, STARTED)
    return store


def honcho_routes(**more: Callable[[httpx.Request], Any]) -> dict[str, Callable[[httpx.Request], Any]]:
    return {
        "POST /v3/workspaces": lambda _: {},
        f"POST {WS}/peers": lambda _: {},
        f"POST {WS}/sessions/list": lambda _: {"items": [{"id": "notes"}], "pages": 1},
        **more,
    }


def describe_honcho_store() -> None:
    def it_sends_each_record_as_the_owners_message_in_its_kinds_session(tmp_path: Path) -> None:
        mail = record(3).model_copy(update={"kind": "mail"})
        calls = Calls(
            honcho_routes(
                **{
                    f"POST {WS}/sessions": lambda _: {},
                    f"POST {WS}/sessions/notes/messages": lambda _: [],
                    f"POST {WS}/sessions/mail/messages": lambda _: [],
                }
            )
        )
        receipt = honcho(calls, tmp_path).ingest([record(1), mail, record(2)])
        (notes,) = calls.bodies(f"POST {WS}/sessions/notes/messages")
        assert receipt.sent == ("r0001", "r0002", "r0003")
        assert calls.bodies(f"POST {WS}/sessions") == [{"id": "mail", "peers": {"owner": {}}}]
        assert notes["messages"][0] == {
            "content": "text 1",
            "peer_id": "owner",
            "created_at": "2026-01-05T09:00:00Z",
            "metadata": {"rid": "r0001", "kind": "notes"},
        }

    def it_names_the_records_behind_a_conclusion(tmp_path: Path) -> None:
        listed = {"items": [{"id": "m1", "metadata": {"rid": "r0001"}}, {"id": "m2", "metadata": {"rid": "r0002"}}]}
        conclusions = [{"content": "owner heard X", "level": "explicit", "source_message_ids": ["m2", "m1", "m9"]}]
        calls = Calls(
            honcho_routes(
                **{
                    f"POST {WS}/sessions/notes/messages/list": lambda _: {**listed, "pages": 1},
                    f"POST {WS}/conclusions/query": lambda _: conclusions,
                }
            )
        )
        (hit,) = honcho(calls, tmp_path).search("when", 5)
        (query,) = calls.bodies(f"POST {WS}/conclusions/query")
        assert hit.keys == ("r0002", "r0001")
        assert query["filters"] == {"observer": "owner", "observed": "owner"}

    def it_is_settled_only_when_the_queue_is_empty(tmp_path: Path) -> None:
        states = iter([{"pending_work_units": 0, "in_progress_work_units": 1}, {"pending_work_units": 0}])
        calls = Calls(honcho_routes(**{f"GET {WS}/queue/status": lambda _: next(states)}))
        store = honcho(calls, tmp_path)
        assert store.settled({}) is False
        assert store.settled({}) is True


def letta(calls: Calls, tmp_path: Path) -> LettaStore:
    store = LettaStore(base_url="http://letta.test", transport=httpx.MockTransport(calls))
    store.open("wcatbench_letta_pilot", tmp_path / "store", STARTED)
    return store


def describe_letta_store() -> None:
    def _routes(**more: Callable[[httpx.Request], Any]) -> dict[str, Callable[[httpx.Request], Any]]:
        return {"GET /v1/archives/": lambda _: [], "POST /v1/archives/": lambda _: {"id": "archive-1"}, **more}

    def it_keeps_what_it_sent_because_an_archive_cannot_list_its_passages(tmp_path: Path) -> None:
        calls = Calls(_routes(**{"POST /v1/archives/archive-1/passages/batch": lambda _: []}))
        letta(calls, tmp_path).ingest([record(1), record(2)])
        (body,) = calls.bodies("POST /v1/archives/archive-1/passages/batch")
        assert body["passages"][0]["metadata"] == {"rid": "r0001", "kind": "notes"}
        assert set(letta(calls, tmp_path).held()) == {"r0001", "r0002"}

    def it_reads_the_record_key_from_a_passage(tmp_path: Path) -> None:
        reply = [{"passage": {"text": "t", "metadata": {"rid": "r0007"}}, "score": 0.9}, {"passage": {}}]
        calls = Calls(_routes(**{"POST /v1/passages/search": lambda _: reply}))
        hits = letta(calls, tmp_path).search("when", 5)
        assert [hit.keys for hit in hits] == [("r0007",), ()]


def cognee(calls: Calls, tmp_path: Path, mode: str = "graph") -> CogneeStore:
    store = CogneeStore(base_url="http://cognee.test", transport=httpx.MockTransport(calls))
    store.mode = mode
    store.open("wcatbench_cognee_pilot", tmp_path / "store", STARTED)
    return store


def describe_cognee_store() -> None:
    def _routes(**more: Callable[[httpx.Request], Any]) -> dict[str, Callable[[httpx.Request], Any]]:
        return {"GET /api/v1/datasets": lambda _: [], "POST /api/v1/add": lambda _: {"dataset_id": "d1"}, **more}

    def it_opens_each_text_with_its_date_and_kind_so_equal_texts_stay_apart(tmp_path: Path) -> None:
        calls = Calls(_routes())
        store = cognee(calls, tmp_path)
        store.ingest([record(1), record(2)])
        (sent,) = [r for r in calls.seen if r.url.path == "/api/v1/add"]
        assert b"[2026-01-05 09:00 notes] text 1" in sent.content
        assert store.held() == {"r0001": ItemState.DONE, "r0002": ItemState.DONE}

    def it_names_the_records_behind_the_chunks_a_graph_search_used(tmp_path: Path) -> None:
        chunk = {"node_attributes": {"type": "DocumentChunk", "text": "[2026-01-05 09:00 notes] text 2"}}
        entity = {"node_attributes": {"type": "Entity", "text": None}}
        reply = [{"objects_result": [{"node1": chunk, "node2": entity}, {"node1": entity, "node2": chunk}]}]
        calls = Calls(_routes(**{"POST /api/v1/search": lambda _: reply}))
        store = cognee(calls, tmp_path)
        store.ingest([record(2)])
        assert [hit.keys for hit in store.search("when", 5)] == [("r0002",)]

    def it_starts_cognify_once_and_waits_for_every_item(tmp_path: Path) -> None:
        pending = iter([{"pending": 3}, {"pending": 0}])
        calls = Calls(
            _routes(
                **{
                    "GET /api/v1/datasets/d1/processing-status": lambda _: next(pending),
                    "GET /api/v1/datasets/status": lambda _: {"d1": "DATASET_PROCESSING_COMPLETED"},
                    "POST /api/v1/cognify": lambda _: {},
                }
            )
        )
        store = cognee(calls, tmp_path)
        store.ingest([record(1)])
        assert store.settled({}) is False
        assert store.settled({}) is True
        assert len(calls.bodies("POST /api/v1/cognify")) == 1
