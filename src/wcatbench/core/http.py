"""One JSON client for hosted stores: HTTP 429, 5xx and timeouts are transient and retried, the rest is permanent.

The auth header is set on the client, never passed per call, so it cannot end up in an error message or a log line.
"""

from __future__ import annotations

from typing import Any

import httpx

from wcatbench.core.errors import PermanentError, TransientError, retrying

TRANSIENT = frozenset({429, 500, 502, 503, 504})


class JsonApi:
    def __init__(self, base: str, auth: str, transport: httpx.BaseTransport | None = None) -> None:
        self.client = httpx.Client(
            base_url=base, headers={"Authorization": auth}, transport=transport, timeout=httpx.Timeout(60.0)
        )
        self.calls = 0

    @retrying()
    def request(self, method: str, path: str, body: Any = None, timeout: float = 60.0) -> Any:
        self.calls += 1
        try:
            reply = self.client.request(method, path, json=body, timeout=timeout)
        except httpx.TimeoutException as error:
            raise TransientError(f"{method} {path} timed out after {timeout:.0f} s") from error
        except httpx.TransportError as error:
            raise TransientError(f"{method} {path}: {type(error).__name__}") from error
        if reply.status_code in TRANSIENT:
            raise TransientError(f"{method} {path} -> HTTP {reply.status_code}")
        if reply.is_error:
            raise PermanentError(f"{method} {path} -> HTTP {reply.status_code}: {reply.text[:300]}")
        return reply.json() if reply.content else {}

    @retrying()
    def request_form(self, method: str, path: str, fields: list[tuple[str, str]], timeout: float = 60.0) -> Any:
        """A multipart form, each field a part; a field may repeat (Cognee's raw_data takes one part per item)."""
        self.calls += 1
        try:
            reply = self.client.request(method, path, files=[(k, (None, v)) for k, v in fields], timeout=timeout)
        except httpx.TimeoutException as error:
            raise TransientError(f"{method} {path} timed out after {timeout:.0f} s") from error
        except httpx.TransportError as error:
            raise TransientError(f"{method} {path}: {type(error).__name__}") from error
        if reply.status_code in TRANSIENT:
            raise TransientError(f"{method} {path} -> HTTP {reply.status_code}")
        if reply.is_error:
            raise PermanentError(f"{method} {path} -> HTTP {reply.status_code}: {reply.text[:300]}")
        return reply.json() if reply.content else {}

    def close(self) -> None:
        self.client.close()
