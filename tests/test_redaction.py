from __future__ import annotations

from wcatbench.observability.redaction import REDACTED, redact_mapping, register_secret, scrub_secrets


def describe_redaction() -> None:
    def it_hides_denied_keys_in_any_casing() -> None:
        redacted = redact_mapping({"X-API-Key": "abc", "apiKey": "abc", "idempotency_key": "keep", "tokenizer": "x"})
        assert redacted == {"X-API-Key": REDACTED, "apiKey": REDACTED, "idempotency_key": "keep", "tokenizer": "x"}

    def it_keeps_presence_flags_readable() -> None:
        assert redact_mapping({"token_present": True}) == {"token_present": True}

    def it_scrubs_a_registered_key_from_a_finished_string() -> None:
        register_secret("sk-test-0123456789")
        assert scrub_secrets("GET https://x/?k=sk-test-0123456789 failed") == f"GET https://x/?k={REDACTED} failed"

    def it_ignores_values_too_short_to_be_keys() -> None:
        register_secret("short")
        assert scrub_secrets("a short line") == "a short line"
