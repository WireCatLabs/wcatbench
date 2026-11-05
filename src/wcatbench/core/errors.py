"""Transient failures are retried, permanent ones are not. Every adapter raises one of these two, never a bare error."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

T = TypeVar("T")


class WcatbenchError(Exception):
    """Base for every error this package raises on purpose."""


class TransientError(WcatbenchError):
    """Timeout, HTTP 429 or 5xx: the same call may succeed later."""


class PermanentError(WcatbenchError):
    """The same call gets the same answer: a bad key, a refused payload, a missing adapter."""


class PrivacyError(PermanentError):
    """A hosted store was given a dataset marked private."""


def retrying(attempts: int = 4, max_wait: float = 60.0) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Retry TransientError with exponential backoff and jitter. Paid calls go through this, nothing else retries."""
    return retry(
        retry=retry_if_exception_type(TransientError),
        stop=stop_after_attempt(attempts),
        wait=wait_exponential_jitter(multiplier=2, max=max_wait),
        reraise=True,
    )
