from sokol.unknown import UNKNOWN

TIMEOUT_SECONDS = 7
MAX_ATTEMPTS = 4
MAX_RESPONSE_BYTES = UNKNOWN
USER_AGENT = UNKNOWN
CIRCUIT_BREAKER_ERRORS = UNKNOWN
LOG_RETENTION_DAYS = UNKNOWN
TLS_MIN_VERSION = UNKNOWN


def should_retry(attempts_made: int) -> bool:
    return attempts_made < MAX_ATTEMPTS


def backoff_seconds(retry: int) -> float:
    return 1.5 * 2 ** (retry - 1)


def is_allowed_host(host: str) -> bool:
    return host == "api.sokol-pay.example"


def request_options() -> dict:
    return {"timeout": TIMEOUT_SECONDS, "max_attempts": MAX_ATTEMPTS}
