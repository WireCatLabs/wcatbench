"""The synthetic memory corpus: 2,000 records (version 1), an archive of 3,000 and more (version 2), or that archive
with new records appended and 50 questions of 21 kinds (version 3, `version=3`)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from wcatbench.core import dataset_files
from wcatbench.core.errors import PermanentError
from wcatbench.core.types import AnswerKey, DatasetManifest, Privacy, Question, Record
from wcatbench.datasets.synthetic import generator, generator_v3

SMALL = 2000
ARCHIVE_MIN = 3000


class SyntheticDataset:
    name = "synthetic"

    def build(self, out: Path, params: dict[str, int]) -> DatasetManifest:
        size = params.get("records", SMALL)
        if size != SMALL and size < ARCHIVE_MIN:
            raise PermanentError(f"records is {SMALL} (the original corpus) or at least {ARCHIVE_MIN} (the archive)")
        extra: dict[str, object] = {}
        if size == SMALL:
            seed = params.get("seed", generator.SMALL_SEED)
            rows, asked_rows = generator.corpus(seed)
        else:
            seed = params.get("seed", generator.ARCHIVE_SEED)
            rows, asked_rows, asked = generator.archive_corpus(size, seed)
            subset_size = params.get("mem0_subset", generator.MEM0_SUBSET)
            subset = generator.provider_subset(rows, asked, subset_size, seed)
            dataset_files.write_json(out / "subset-mem0.json", subset)
            extra = {
                "projects": len(generator.ARCHIVE_PROJECTS),
                "asked_milestones": asked["subjects"],
                "mem0_subset": {key: subset[key] for key in ("records", "sha256", "tiers")},
            }
            if params.get("version", 2) == 3:
                rows, asked_rows, subset = self.extend(out, rows, asked_rows, subset, params)
                extra = {"version_2_records": size, "added_records": len(rows) - size, **extra, **subset}
        records = [Record.model_validate(row) for row in rows]
        questions = [Question(id=row["id"], text=row["question"], as_of=row["as_of"]) for row in asked_rows]
        keys = [
            AnswerKey(
                question_id=row["id"],
                answers=tuple(row["answers"]),
                sources=tuple(row["required_citations"]),
                stale_answers=tuple(row["stale_answers"]),
                form=row.get("form"),
            )
            for row in asked_rows
        ]
        corpus_sha, key_sha = dataset_files.write(out, records, questions, keys)
        kinds = {kind: sum(record.kind == kind for record in records) for kind in generator.KINDS}
        manifest = DatasetManifest(
            name=self.name,
            version=1 if size == SMALL else params.get("version", 2),
            privacy=Privacy.SYNTHETIC,
            params={"records": size, "seed": seed, **({"version": 3} if params.get("version") == 3 else {})},
            records=len(records),
            questions=len(questions),
            corpus_sha256=corpus_sha,
            key_sha256=key_sha,
            extra={"source_counts": kinds, **extra},
        )
        dataset_files.write_json(out / dataset_files.MANIFEST, manifest.model_dump(mode="json"))
        return manifest

    @staticmethod
    def extend(
        out: Path, rows: list[Any], asked_rows: list[Any], subset: dict[str, Any], params: dict[str, int]
    ) -> tuple[list[Any], list[Any], dict[str, object]]:
        """Version 2's records unchanged and the new ones after them, so a version 2 store takes only the rest."""
        lines = dataset_files.corpus_lines(Record.model_validate(row) for row in rows)
        base_sha = hashlib.sha256(lines.encode()).hexdigest()
        added, questions, kinds = generator_v3.extension(rows, asked_rows, params.get("v3_seed", generator_v3.V3_SEED))
        dataset_files.write_json(out / "kinds.json", kinds)
        # Mem0's subset grows by every new record: they are all the version 3 questions are about, or close noise.
        ids = [*subset["ids"], *(record["id"] for record in added)]
        wanted = set(ids)
        chosen = dataset_files.corpus_lines(
            Record.model_validate(row) for row in [*rows, *added] if row["id"] in wanted
        )
        sha = hashlib.sha256(chosen.encode()).hexdigest()
        dataset_files.write_json(out / "subset-mem0.json", {"records": len(ids), "sha256": sha, "ids": ids})
        return [*rows, *added], questions, {"version_2_corpus_sha256": base_sha, "mem0_subset_v3": len(ids)}
