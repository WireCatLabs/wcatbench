"""The staged scorer of rules-trial: one row per check, a total per stage, never one blended score.

Order, as in Danil Pismenny's trials: was the rule stored, was it retrieved, is the old version no longer active,
and only then was the agent's work correct. Unknown checks are counted apart. Stages are read from text with the
check's patterns: a rule's active value in the store's own content (stored) and in the frozen context the agent got
(retrieved); the replaced text's pattern absent from that context (old version inactive).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

# The answer key, the hidden checks, the generator and the run folders. A store's build folder is not here: memo's
# unrestricted row reads its own store there.
FORBIDDEN = (
    "checks.json",
    "runner.py",
    "key.json",
    "rules_trial",
    "wcatbench-home/datasets",
    "wcatbench-home/runs",
    "/home/leemour/Projects",
)


def found(pattern: str | None, text: str) -> bool:
    return bool(pattern) and re.search(pattern, text, re.IGNORECASE) is not None  # type: ignore[arg-type]


def leaked(transcript: str) -> list[str]:
    return [marker for marker in FORBIDDEN if marker in transcript]


def outcome_kind(check: dict[str, Any], status: str) -> str:
    if check["kind"] == "known":
        return {"pass": "applied", "unknown": "missed_available", "wrong": "wrong_concrete"}.get(status, "broken")  # nosec B105
    return {"unknown": "justified_unknown", "wrong": "wrong_concrete", "pass": "wrong_concrete"}.get(status, "broken")  # nosec B105


def rows(
    checks: list[dict[str, Any]],
    stored_text: str | None,
    context: str | None,
    statuses: dict[str, dict[str, str]],
    valid: bool,
    context_sources: set[str] | None = None,
) -> list[dict[str, Any]]:
    """One session's checks. `stored_text` None means the variant has no store; `context` None means no context."""
    out = []
    for check in checks:
        status = statuses.get(check["id"], {}).get("status", "broken") if valid else "invalid"
        row: dict[str, Any] = {
            "check": check["id"],
            "task": check["task"],
            "kind": check["kind"],
            "status": status,
            "got": statuses.get(check["id"], {}).get("got"),
        }
        if check["kind"] == "known":
            row["rule"] = check["rule"]
            row["stored"] = None if stored_text is None else found(check["value"], stored_text)
            # No context at all (no memory, or an archive the agent searches itself): the stage does not apply.
            row["retrieved"] = found(check["value"], context) if context else None
            row["has_old"] = bool(check["replaces"])
            row["old_inactive"] = (not found(check["old"], context)) if check["replaces"] and context else None
            # By source id: an extracting store rewrites or translates the text, which the value pattern can miss.
            row["retrieved_source"] = None if context_sources is None else check.get("source") in context_sources
            row["old_inactive_source"] = (
                None
                if context_sources is None or not check["replaces"]
                else not set(check["replaces"]) & context_sources
            )
            row["applied"] = status == "pass"
        else:
            row["trap"] = check["trap"]
            row["trap_in_context"] = None if context_sources is None else check["trap"] in context_sources
            row["unknown_ok"] = status == "unknown"
        row["outcome"] = "invalid" if status == "invalid" else outcome_kind(check, status)
        if row["outcome"] == "missed_available" and not (row["retrieved"] or row.get("retrieved_source")):
            # The agent declined, and the rule never reached it: that is the store's loss, not the agent's.
            row["outcome"] = "abstained_not_retrieved"
        out.append(row)
    return out


def fraction(rows: list[dict[str, Any]], stage: str) -> list[int] | None:
    applies = [row for row in rows if row.get(stage) is not None]
    return [sum(bool(row[stage]) for row in applies), len(applies)] if applies else None


def totals(all_rows: list[dict[str, Any]]) -> dict[str, Any]:
    known = [row for row in all_rows if row["kind"] == "known"]
    unknown = [row for row in all_rows if row["kind"] == "unknown"]
    with_store = [row for row in known if row["stored"] is not None]
    with_old = [row for row in known if row["old_inactive"] is not None]
    return {
        "stored": [sum(bool(row["stored"]) for row in with_store), len(with_store)] if with_store else None,
        "retrieved": [sum(bool(row["retrieved"]) for row in known), len(known)]
        if any(row["retrieved"] is not None for row in known)
        else None,
        "old_inactive": [sum(bool(row["old_inactive"]) for row in with_old), len(with_old)] if with_old else None,
        "retrieved_source": fraction(known, "retrieved_source"),
        "old_inactive_source": fraction(known, "old_inactive_source"),
        "applied": [sum(row["applied"] for row in known), len(known)],
        "unknown": [sum(row["unknown_ok"] for row in unknown), len(unknown)],
        "outcomes": dict(Counter(row["outcome"] for row in all_rows)),
        "his_total_for_comparison": [
            sum(row["applied"] for row in known) + sum(row["unknown_ok"] for row in unknown),
            len(known) + len(unknown),
        ],
    }
