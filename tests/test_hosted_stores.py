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
