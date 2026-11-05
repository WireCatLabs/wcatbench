"""What must never reach a log sink, and how it is recognised.

Ported from an earlier project of ours. Applied in the two formatters every log line passes
through rather than at each call site, so a field nobody remembered to mark is still caught.

**Patterns are anchored on snake_case word boundaries, never substrings.** A bare `key` would redact `idempotency_key`;
`(?:^|_)token(?:_|$)` matches `token`, `bot_token` and `token_present`, and not `tokenizer`. Keys are normalised first,
so a service's own casing cannot walk through: `X-API-Key` becomes `x_api_key`.

Covered: key names, recursively; and known secret values, substituted out of the final string, so a key inside a URL
or an exception message is caught. Not covered: personal data inside free text. Benchmark data is synthetic, and a
log message never carries record text.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

#: One runaway payload otherwise fills the log. Applied per string, after redaction.
MAX_STRING_LENGTH = 3000

#: Deep enough for a pydantic error list inside a dict; shallow enough that a cyclic or
#: pathological structure cannot cost the process a log line.
MAX_DEPTH = 6

#: A secret shorter than this is more likely a test fixture or a common word, and
#: substituting it out of every line would corrupt legitimate text.
MIN_SECRET_LENGTH = 8

DENY_WORDS = (
    # Credentials
    "password",
    "passwd",
    "pwd",
    "secret",
    "secrets",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "signing_key",
    "encryption_key",
    "credential",
    "credentials",
    "authorization",
    "auth_header",
    "cookie",
    "set_cookie",
    "signature",
    # Personal data and record content
    "email",
    "email_address",
    "phone",
    "phone_number",
    "body",
    "text",
    "message_text",
    "caption",
    "first_name",
    "last_name",
    "full_name",
    "display_name",
    "username",
)

_DENY_PATTERN = re.compile(r"(?:^|_)(?:" + "|".join(DENY_WORDS) + r")(?:_|$)")

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_ACRONYM_BOUNDARY = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")


def normalize_key(key: str) -> str:
    """`TerminalKey` → `terminal_key`, `X-API-Key` → `x_api_key`."""
    split = _ACRONYM_BOUNDARY.sub("_", _CAMEL_BOUNDARY.sub("_", key))
    return re.sub(r"[-\s.]+", "_", split).lower()


def is_denied(key: str) -> bool:
    return bool(_DENY_PATTERN.search(normalize_key(key)))


_known: set[str] = set()


def register_secret(value: str) -> None:
    """Every key core.secrets resolves is registered here, so it is scrubbed even from a finished string."""
    if len(value) >= MIN_SECRET_LENGTH:
        _known.add(value)


def _known_secret_values() -> tuple[str, ...]:
    """Longest first, so a key containing another is substituted whole."""
    return tuple(sorted(_known, key=len, reverse=True))


def scrub_secrets(text: str) -> str:
    """Substitute configured secret values out of an already-serialized line.

    Applied to the whole string rather than to individual fields, because the leak this
    catches is a token inside a URL or an exception message — places no key names.
    """
    for secret in _known_secret_values():
        text = text.replace(secret, REDACTED)
    return text


def _truncate(value: str) -> str:
    if len(value) <= MAX_STRING_LENGTH:
        return value
    return f"{value[:MAX_STRING_LENGTH]}…[truncated {len(value) - MAX_STRING_LENGTH} chars]"


def _redact_value(value: Any, depth: int) -> Any:
    if depth >= MAX_DEPTH:
        return REDACTED
    if isinstance(value, dict):
        return redact_mapping(value, depth=depth + 1)
    if isinstance(value, (list, tuple, set)):
        return [_redact_value(item, depth + 1) for item in value]
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, str):
        return _truncate(value)
    return value


def redact_mapping(mapping: Any, depth: int = 0) -> dict[str, Any]:
    """Deny-listed keys replaced, everything else recursed into and truncated."""
    result: dict[str, Any] = {}
    for key, value in mapping.items():
        name = key if isinstance(key, str) else str(key)
        # A bool or a None carries presence and nothing else, so `token_present=True` and
        # `api_key_present=False` stay readable while `token=` never does.
        if is_denied(name) and not isinstance(value, bool) and value is not None:
            result[name] = REDACTED
        else:
            result[name] = _redact_value(value, depth)
    return result
