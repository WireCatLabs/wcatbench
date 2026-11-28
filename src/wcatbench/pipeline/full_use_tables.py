"""full-use tables and hypotheses, recounted from the per-check rows (result.json) and the blind verdicts only.

Nothing here reads a summary written earlier: every number on the page comes out of this one pass, so a reader can
rerun it on the published run folders.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from wcatbench.datasets.company_round import keys
from wcatbench.pipeline import full_use_report

LABEL = {
    "memo-full": "memo, full use",
    "memory-bank": "Memory Bank (curated Markdown)",
    "mem0-oss": "Mem0 OSS",
    "openviking": "OpenViking",
    "memo-limited": "memo under hard limits (bonus)",
    "files-rg": "ceiling: raw export plus rg, not a tool people use",
    "answer-key": "gate: the answer key",
    "none": "gate: no memory",
}
RIVALS = ["memo-full", "memory-bank", "mem0-oss", "openviking", "memo-limited"]
ORDER = [*RIVALS, "files-rg", "answer-key", "none"]
BASE = sorted(keys.KEYS)
NO_DATA = [qid for qid in BASE if not keys.KEYS[qid]["answer"]]
STALE_Q = [
    qid for qid in BASE if "stale" in keys.KEYS[qid].get("flags", []) or "cancelled" in keys.KEYS[qid].get("flags", [])
]
LOOKALIKE_Q = [qid for qid in BASE if "lookalike" in keys.KEYS[qid].get("flags", [])]


def tasks21(done: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The pre-registered task set: 6 coding runs and the 15 base questions, no second wordings."""
    return [r for r in done if "rows" in r or r["unit"] in BASE]


def question_scores(verdicts: list[dict[str, Any]], run: str, size: str, contestant: str) -> dict[str, Any]:
    mine = {v["question"]: v for v in verdicts if (v["run"], v["size"], v["contestant"]) == (run, size, contestant)}
    if not mine:
        return {}

    def good(qid: str) -> bool:
        verdict = mine.get(qid, {})
        if qid in NO_DATA:
            return verdict.get("verdict") == "correct"
        return verdict.get("verdict") == "correct" and bool(verdict.get("source_ok"))

    return {
        "scored": sum(qid in mine for qid in BASE),
        "correct": sum(good(qid) for qid in BASE),
        "correct_any_source": sum(mine.get(qid, {}).get("verdict") == "correct" for qid in BASE),
        "partial": sum(mine.get(qid, {}).get("verdict") == "partial" for qid in BASE),
        "no_data_ok": sum(good(qid) for qid in NO_DATA),
        "variants": sum(good(v) for v in keys.VARIANTS if v in mine),
        "variants_scored": sum(v in mine for v in keys.VARIANTS),
        "stale_used": sum(bool(mine.get(qid, {}).get("stale_used")) for qid in BASE),
        "lookalike_used": sum(bool(mine.get(qid, {}).get("lookalike_used")) for qid in BASE),
        "good": {qid: good(qid) for qid in BASE if qid in mine},
        "cited": sum(
            bool(mine.get(qid, {}).get("source_ok"))
            for qid in BASE
            if mine.get(qid, {}).get("verdict") == "correct" and qid not in NO_DATA
        ),
        "correct_with_answer": sum(mine.get(qid, {}).get("verdict") == "correct" for qid in BASE if qid not in NO_DATA),
    }


def collect(
    runs: dict[str, Path],
    datasets: dict[str, Path],
    memo_dbs: dict[str, dict[str, Path]],
    verdicts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for run, folder in runs.items():
        every = full_use_report.results(folder)
        for metric in full_use_report.metrics(folder, datasets, memo_dbs.get(run)):
            done = [r for r in every if (r["size"], r["contestant"]) == (metric["size"], metric["contestant"])]
            task = tasks21(done)
            providers = sorted(
                {
                    r.get(
                        "provider",
                        "openai-codex" if run.startswith("r1") and "claude" not in run else "claude-subscription",
                    )
                    for r in done
                }
            )
            rows.append(
                metric
                | {
                    "run": run,
                    "providers": providers,
                    "questions_scored": question_scores(verdicts, run, metric["size"], metric["contestant"]),
                    "tokens_per_task": statistics.mean(r["usage"]["input_tokens"] for r in task) if task else None,
                    "output_per_task": statistics.mean(r["usage"]["output_tokens"] for r in task) if task else None,
                    "seconds_per_task_median": statistics.median(r["seconds"] for r in task) if task else None,
                    "tasks": len(task),
                    # The bank is curated prose without source identity, so a probe on its wording measures the
                    # curation's phrasing, not retrieval.
                    **({"recall": None} if metric["contestant"] == "memory-bank" else {}),
                }
            )
    return rows


def _n(value: Any, digits: int = 0) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool) or not isinstance(value, int | float):
        return str(value)
    return f"{value:,.{digits}f}"


def markdown(rows: list[dict[str, Any]], size: str, run: str) -> str:
    chosen = sorted(
        (r for r in rows if r["size"] == size and r["run"] == run),
        key=lambda r: ORDER.index(r["contestant"]) if r["contestant"] in ORDER else 99,
    )
    providers = ", ".join(f"{LABEL.get(r['contestant'], r['contestant'])}: {'+'.join(r['providers'])}" for r in chosen)
    out = [
        f"Agent provider per contestant: {providers}.",
        "",
        f"#### Coding, {size}, run {run}",
        "",
        "| Contestant | Sessions | Known applied | UNKNOWN right | Old version used | Look-alike value used | "
        "Right source cited | Wrong concrete value |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in chosen:
        c = r["coding"]
        if not c:
            continue
        out.append(
            f"| {LABEL.get(r['contestant'], r['contestant'])} | {c['sessions']} | {c['applied']}/{c['known']} | "
            f"{c['unknown_ok']}/{c['unknown']} | {c['stale_used']}/{c['stale_checks']} | "
            f"{c['lookalike_used']}/{c['lookalike_checks']} | {c['cited']}/{c['cited_of']} | {c['wrong_concrete']} |"
        )
    out += [
        "",
        f"#### Questions, {size}, run {run} (blind scores)",
        "",
        "| Contestant | Right with a dated source, of 15 (primary) | Right answer, of 15 | Partial | "
        '"No data" right (of 3) | '
        "Second wording right (of 4) | Old version used | Look-alike used |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in chosen:
        q = r["questions_scored"]
        if not q:
            continue
        out.append(
            f"| {LABEL.get(r['contestant'], r['contestant'])} | {q['correct']}/{q['scored']} | "
            f"{q['correct_any_source']}/{q['scored']} | {q['partial']} | {q['no_data_ok']}/{len(NO_DATA)} | "
            f"{q['variants']}/{q['variants_scored']} | {q['stale_used']}/{len(STALE_Q)} | "
            f"{q['lookalike_used']}/{len(LOOKALIKE_Q)} |"
        )
    out += [
        "",
        f"#### Cost and retrieval, {size}, run {run}",
        "",
        "| Contestant | Input tokens per task | Output tokens per task | Median wall time per task, s | "
        "Median search, s | Tool calls per session | Needed sources seen, % | MRR | Precision, % |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in chosen:
        out.append(
            f"| {LABEL.get(r['contestant'], r['contestant'])} | {_n(r['tokens_per_task'])} | "
            f"{_n(r['output_per_task'])} | {_n(r['seconds_per_task_median'], 1)} | "
            f"{_n(r['search_seconds_median'], 2)} | "
            f"{_n(r['tool_calls'], 1)} | {_n(r['recall'], 1)} | {_n(r['mrr'], 2)} | {_n(r['precision'], 1)} |"
        )
    return "\n".join(out) + "\n"


def _pick(rows: list[dict[str, Any]], run: str, size: str, contestant: str) -> dict[str, Any] | None:
    return next((r for r in rows if (r["run"], r["size"], r["contestant"]) == (run, size, contestant)), None)


def hypotheses_1x(rows: list[dict[str, Any]], run: str) -> list[dict[str, Any]]:
    """h1, h5 (1x leg), h6, h7 (1x leg) and h8 by their pre-registered wording and denominators."""
    memo, files = _pick(rows, run, "1x", "memo-full"), _pick(rows, run, "1x", "files-rg")
    # Only a complete run is scored: 6 coding runs and 15 questions each, as pre-registered.
    if memo is None or files is None or not memo["coding"] or not files["coding"]:
        return []
    if memo["tasks"] != 21 or files["tasks"] != 21:
        return []
    mc, fc = memo["coding"], files["coding"]
    mq, fq = memo["questions_scored"], files["questions_scored"]
    checks_m, checks_f = mc["applied"] + mc["unknown_ok"], fc["applied"] + fc["unknown_ok"]
    out = [
        {
            "id": "h1",
            "against": "ceiling",
            "measured": f"checks {checks_m}/78 vs {checks_f}/78; "
            f"answers {mq.get('correct')}/15 vs {fq.get('correct')}/15",
            "fails": checks_f - checks_m > 3 or (fq.get("correct", 0) - mq.get("correct", 0)) > 1,
        },
        {
            "id": "h5 (1x leg)",
            "against": "ceiling",
            "measured": f"stale uses {mc['stale_used'] + mq.get('stale_used', 0)} vs "
            f"{fc['stale_used'] + fq.get('stale_used', 0)} of {mc['stale_checks']} checks + {len(STALE_Q)} questions",
            "fails": (fc["stale_used"] + fq.get("stale_used", 0)) - (mc["stale_used"] + mq.get("stale_used", 0)) >= 2,
        },
        {
            "id": "h6",
            "against": "ceiling",
            "measured": f"input tokens per task {memo['tokens_per_task']:,.0f} vs {files['tokens_per_task']:,.0f} "
            f"({memo['tasks']} and {files['tasks']} tasks)",
            "fails": memo["tokens_per_task"] <= files["tokens_per_task"],
        },
        {
            "id": "h7 (1x leg)",
            "against": "none",
            "measured": f"sessions that saw a marker: {memo['markers_seen']} "
            f"of {memo['coding']['sessions'] + memo['questions']}",
            "fails": memo["markers_seen"] > 0,
        },
    ]
    cited = mc["cited"] + mq.get("cited", 0)
    of = mc["cited_of"] + mq.get("correct_with_answer", 0)
    out.append(
        {
            "id": "h8",
            "against": "none",
            "measured": f"right source {cited}/{of} = {100 * cited / of:.1f}%" if of else "no applied checks",
            "fails": (cited / of) < 0.9 if of else True,
        }
    )
    return out


def write(out: Path, rows: list[dict[str, Any]]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str))
    parts = []
    for run in sorted({r["run"] for r in rows}):
        for size in ("1x", "10x", "100x"):
            if any(r["run"] == run and r["size"] == size for r in rows):
                parts.append(markdown(rows, size, run))
        hyps = hypotheses_1x(rows, run)
        if hyps:
            parts.append(
                f"#### Hypotheses at 1x, run {run}\n\n| Id | Against | Measured | Result |\n|---|---|---|---|\n"
                + "\n".join(
                    f"| {h['id']} | {h['against']} | {h['measured']} | {'fails' if h['fails'] else 'holds'} |"
                    for h in hyps
                )
                + "\n"
            )
    (out / "tables.md").write_text("\n".join(parts))
