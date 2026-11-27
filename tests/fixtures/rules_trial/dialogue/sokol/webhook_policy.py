from sokol.unknown import UNKNOWN

TIMEOUT_SECONDS = 10
MAX_ATTEMPTS = 5
RETRY_DELAYS = (1, 5, 30)
SIGNATURE_HEADER = "X-Sokol-Signature"
MAX_PAYLOAD_BYTES = UNKNOWN
DEAD_LETTER_QUEUE = UNKNOWN
RATE_LIMIT_PER_MINUTE = UNKNOWN

UNSIGNED = frozenset({"acme"})


def needs_signature(partner):
    return partner not in UNSIGNED
