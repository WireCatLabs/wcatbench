"""Tables of the full-use round: one row per contestant and size, each metric on its own, never one blended score.

Questions are scored blind: `blind_sheets` writes every answer under a random letter with the key, a separate agent
scores the sheet, and `unblind` maps its verdicts back. Coding checks are scored by the hidden tests.
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
import statistics
import urllib.parse
from pathlib import Path
from typing import Any

from wcatbench.datasets.company_round import content, export, keys, question_texts

VERDICTS = ("correct", "partial", "wrong", "no_data")


def results(run: Path) -> list[dict[str, Any]]:
    """Every finished session; an aborted copy (`.aborted-…`) is not a result."""
    return [
        json.loads(path.read_text())
        for path in sorted(run.glob("*/trials/*/*/result.json"))
        if ".aborted-" not in path.parent.name and ".quota-" not in path.parent.name
    ]


def needed_sources(unit: str) -> list[str]:
    if unit in keys.KEYS or unit in keys.VARIANTS:
        return list(keys.KEYS[keys.VARIANTS.get(unit, unit)]["sources"])
    task = next(task for task in content.TASKS if task["id"] == unit)
    return sorted({content.RULES[check[1]]["source"] for check in task["known"]})


def needed(unit: str) -> list[str]:
    return [keys.PROBES[source] for source in needed_sources(unit)]


class Identity:
    """Which source a hit is, by the identifiers the export gave it (dataset ids.json) and by store record keys."""

    def __init__(self, dataset: Path, memo_db: Path | None = None) -> None:
        index = json.loads((dataset / "ids.json").read_text())
        self.marks: dict[str, list[str]] = {}
        for key, sid in index["messages"].items():
            self.marks.setdefault(sid, []).append(f'/{key}"')
        for key, sid in index["mail"].items():
            if not key.startswith("<"):
                self.marks.setdefault(sid, []).append(f'/{key}"')
        for path, sid in index["files"].items():
            self.marks.setdefault(sid, []).append(f'"title": "{Path(path).stem}"')
        for title, sid in index.get("titles", {}).items():
            self.marks.setdefault(sid, []).append(f'"title": "{title}"')
        corpus = (dataset / "corpus.jsonl").read_text().splitlines()
        self.by_key = {f"r{n + 1:04}": json.loads(line)["id"] for n, line in enumerate(corpus)}
        # memo's `document:N` refs, resolved through the store's own documents table: titles repeat across notes.
        self.documents: dict[str, str] = {}
        if memo_db is not None and memo_db.exists():
            files = index["files"]
            with sqlite3.connect(f"file:{memo_db}?mode=ro", uri=True) as con:
                for number, external in con.execute("select id, external_id from documents"):
                    path = urllib.parse.unquote(str(external).replace("~", "%"))
                    found = [k for k in files if path == k or path.endswith(k) or path.endswith("/" + k)]
                    found = found or [k for k in files if k.startswith(path.split("%")[0][:30])]
                    if len(found) == 1:
                        self.documents[f"document:{number}"] = files[found[0]]

    def relevant(self, hit: dict[str, Any], sources: list[str]) -> bool:
        if "keys" in hit:
            return any(self.by_key.get(key) in sources for key in hit["keys"])
        ref = hit.get("ref")
        if isinstance(ref, str) and ref in self.documents:
            return self.documents[ref] in sources
        text = hit["json"]
        if isinstance(ref, str) and ref.startswith("document:") and self.documents:
            return False
        return any(mark in text for sid in sources for mark in self.marks.get(sid, []))


COMPACT_HIT = re.compile(r"(?m)^((?:msg:\S+|document:\d+)) · ")


def ranked_lists(trial: Path) -> list[list[dict[str, Any]]]:
    """Each search that returns a ranked list: memo's `search` calls (hits as JSON) and the proxy's (hits by key)."""
    lists: list[list[dict[str, Any]]] = []
    calls = trial / "out" / "calls.jsonl"
    if calls.exists():
        for line in calls.read_text().splitlines():
            call = json.loads(line)
            if call["tool"] != "memo" or not call["args"] or call["args"][0] != "search":
                continue
            try:
                reply = json.loads(call["stdout"].strip().splitlines()[-1])
            except (json.JSONDecodeError, IndexError):
                # `--compact` prints one hit per line, its ref first: "ref · kind · date · title · …".
                refs = [m.group(1) for m in COMPACT_HIT.finditer(call["stdout"])]
                lists.append([{"ref": ref, "json": json.dumps({"ref": ref})} for ref in refs])
                continue
            lists.append(
                [
                    {"ref": item.get("ref"), "json": json.dumps(item, ensure_ascii=False)}
                    for item in reply.get("items", [])
                ]
            )
    searches = trial / "searches.jsonl"
    if searches.exists():
        for line in searches.read_text().splitlines():
            lists.append([{"keys": hit.get("keys", [])} for hit in json.loads(line)["hits"]])
    return lists


def search_quality(trial: Path, sources: list[str], identity: Identity) -> dict[str, float | None]:
    lists = [hits for hits in ranked_lists(trial) if hits]
    if not lists:
        return {"mrr": None, "precision": None, "searches": 0}
    reciprocal, precision = [], []
    for hits in lists:
        relevant = [identity.relevant(hit, sources) for hit in hits]
        first = next((rank for rank, ok in enumerate(relevant, 1) if ok), None)
        reciprocal.append(1 / first if first else 0.0)
        precision.append(sum(relevant) / len(relevant))
    return {"mrr": statistics.mean(reciprocal), "precision": statistics.mean(precision), "searches": len(lists)}


def recall(trial: Path, patterns: list[str]) -> float | None:
    seen = (trial / "seen.txt").read_text() if (trial / "seen.txt").exists() else ""
    if not patterns:
        return None
    return sum(bool(re.search(p, seen, re.IGNORECASE)) for p in patterns) / len(patterns)


def key_recall(trial: Path, sources: list[str], identity: Identity) -> float | None:
    """For a store whose hits are extracted text (Mem0, OpenViking): needed sources among the records it returned."""
    path = trial / "searches.jsonl"
    if not sources or not path.exists():
        return None
    seen = {
        identity.by_key.get(key)
        for line in path.read_text().splitlines()
        for hit in json.loads(line)["hits"]
        for key in hit.get("keys", [])
    }
    return sum(source in seen for source in sources) / len(sources)


def median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 1) if values else None


def coding_row(done: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row for result in done for row in result.get("rows", [])]
    extra = [row for result in done for row in result.get("extra", [])]
    by_check = {(c["id"]): c for c in json.loads(json.dumps(_checks()))}
    known = [row for row in rows if row["kind"] == "known"]
    unknown = [row for row in rows if row["kind"] == "unknown"]
    cited = [row["cited"] for row in extra if row.get("cited") is not None]
    return {
        "sessions": len(done),
        "valid": sum(result["valid"] for result in done),
        "applied": sum(row["applied"] for row in known),
        "known": len(known),
        "unknown_ok": sum(row["unknown_ok"] for row in unknown),
        "unknown": len(unknown),
        "wrong_concrete": sum(row["outcome"] == "wrong_concrete" for row in rows),
        "stale_used": sum(row.get("stale_used", False) for row in extra),
        "stale_checks": sum(
            by_check[row["check"]].get("stale") is not None
            for row in extra
            if row["check"] in by_check and by_check[row["check"]]["kind"] == "known"
        ),
        "lookalike_used": sum(row.get("lookalike_used", False) for row in extra),
        "lookalike_checks": sum(
            by_check[row["check"]].get("lookalike") is not None
            for row in extra
            if row["check"] in by_check and by_check[row["check"]]["kind"] == "known"
        ),
        "trap_used": sum(row.get("trap_used", False) for row in extra),
        "cited": sum(cited),
        "cited_of": len(cited),
        "retrieved": sum(bool(row.get("retrieved")) for row in known),
    }


def _checks() -> list[dict[str, Any]]:
    from wcatbench.datasets.company_round import checks

    return checks()


def metrics(run: Path, datasets: dict[str, Path], memo_dbs: dict[str, Path] | None = None) -> list[dict[str, Any]]:
    out = []
    identities = {size: Identity(folder, (memo_dbs or {}).get(size)) for size, folder in datasets.items()}
    every = results(run)
    groups = sorted({(r["size"], r["contestant"]) for r in every})
    for size, contestant in groups:
        done = [r for r in every if r["size"] == size and r["contestant"] == contestant]
        coding = [r for r in done if "rows" in r]
        asked = [r for r in done if "rows" not in r]
        trials = {id(r): run / size / "trials" / contestant / f"{r['unit']}.a{r['application']}" for r in done}
        quality = [search_quality(trials[id(r)], needed_sources(r["unit"]), identities[size]) for r in done]
        recalls = [
            x
            for r in done
            if (
                x := key_recall(trials[id(r)], needed_sources(r["unit"]), identities[size])
                if (trials[id(r)] / "searches.jsonl").exists()
                else recall(trials[id(r)], needed(r["unit"]))
            )
            is not None
        ]
        search_seconds = [
            c["seconds"]
            for r in done
            for c in r.get("calls", [])
            if c["tool"] == "memo" and c["args"] and c["args"][0] == "search"
        ]
        search_seconds += [
            json.loads(line).get("seconds") or 0.0
            for r in done
            if (trials[id(r)] / "searches.jsonl").exists()
            for line in (trials[id(r)] / "searches.jsonl").read_text().splitlines()
        ]
        out.append(
            {
                "size": size,
                "contestant": contestant,
                "coding": coding_row(coding) if coding else None,
                "questions": len(asked),
                "recall": mean([x * 100 for x in recalls]),
                "mrr": mean([q["mrr"] for q in quality if q["mrr"] is not None]),
                "precision": mean([q["precision"] * 100 for q in quality if q["precision"] is not None]),
                "input_tokens": mean([r["usage"]["input_tokens"] for r in done]),
                "output_tokens": mean([r["usage"]["output_tokens"] for r in done]),
                "seconds_median": median([r["seconds"] for r in done]),
                "search_seconds_median": round(statistics.median(search_seconds), 2) if search_seconds else None,
                "tool_calls": mean([r["tool_calls"] for r in done]),
                "markers_seen": sum(bool(r["markers_seen"]) for r in done),
                "leaks": sum(bool(r["leaks"]) for r in done),
                "invalid": sum(not r["valid"] for r in done),
            }
        )
    return out


# Tool names an answer may mention; the judge sees letters, so these are masked. Citation styles stay: the judge
# needs the source to score it, which leaves some contestants guessable by their reference format.
TOOL_WORDS = re.compile(r"(?i)\b(memo|ripgrep|rg|grep|mem0|openviking|viking|memory[- ]bank)\b")


def masked(text: str) -> str:
    return TOOL_WORDS.sub("[tool]", text)


def precheck(answer: str, key: dict[str, Any]) -> str:
    """A regex pre-check, only to flag sheets for a hand read where it disagrees with the judge."""
    text = answer.lower()
    if not key["answer"]:
        return "no_data" if "нет данных" in text else "wrong"
    numbers = re.findall(r"\d+", key["answer"])
    if numbers and all(re.search(rf"(?<!\d){n}(?!\d)", text) for n in numbers):
        return "correct"
    words = list(re.findall(r"[а-яёa-z]{5,}", key["answer"].lower()))[:3]
    if not numbers and words and all(w[:5] in text for w in words):
        return "correct"
    return "no_data" if "нет данных" in text else "wrong"


def blind_sheets(runs: Path | list[Path], out: Path, seed: int = 20261128) -> dict[str, Any]:
    """One sheet per question across runs: the key, what the traps say, every answer under a random letter.

    The map from letter to run, size and contestant stays beside the sheets, never in them.
    """
    rng = random.Random(seed)  # noqa: S311  # nosec B311
    out.mkdir(parents=True, exist_ok=True)
    by_id = {source["id"]: source for source in content.SOURCES}
    mapping: dict[str, dict[str, str]] = {}
    asked = question_texts(Path())
    answers = [
        r | {"run": run.name}
        for run in ([runs] if isinstance(runs, Path) else runs)
        for r in results(run)
        if "answer" in r
    ]
    for unit in sorted({r["unit"] for r in answers}):
        rows = [r for r in answers if r["unit"] == unit]
        rng.shuffle(rows)
        key = keys.KEYS[keys.VARIANTS.get(unit, unit)]
        letters = [f"A{n:03d}" for n in range(1, len(rows) + 1)]
        mapping[unit] = {
            letter: f"{r['run']}/{r['size']}/{r['contestant']}" for letter, r in zip(letters, rows, strict=True)
        }
        sheet = {
            "question": unit,
            "asked": asked.get(unit, ""),
            "key": key["answer"] or "нет данных: в памяти ответа нет",
            "key_source_dates": sorted({_date(s) for s in key["sources"]}),
            "traps": [export.text_of(by_id[s])[:600] for s in key["traps"] if s in by_id],
            "answers": [
                {"letter": letter, "text": masked(r["answer"][-4000:])} for letter, r in zip(letters, rows, strict=True)
            ],
        }
        (out / f"{unit}.json").write_text(json.dumps(sheet, ensure_ascii=False, indent=2))
    (out.parent / "blind-map.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2))
    return mapping


def _date(source_id: str) -> str:
    source = next(s for s in content.SOURCES if s["id"] == source_id)
    return str(source.get("at") or source["messages"][0][-3 if source["kind"] == "mail" else 1])[:10]


def unblind(verdicts: Path, mapping_path: Path) -> list[dict[str, Any]]:
    mapping = json.loads(mapping_path.read_text())
    rows = []
    for path in sorted(verdicts.glob("*.json")):
        sheet = json.loads(path.read_text())
        for verdict in sheet["verdicts"]:
            run, size, contestant = mapping[sheet["question"]][verdict["letter"]].split("/")
            rows.append({"question": sheet["question"], "run": run, "size": size, "contestant": contestant, **verdict})
    return rows
