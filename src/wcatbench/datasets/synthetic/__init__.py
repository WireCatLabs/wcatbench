"""The synthetic memory corpus: 2,000 records (version 1) or an archive of 3,000 and more (version 2)."""

from __future__ import annotations

from pathlib import Path

from wcatbench.core import dataset_files
from wcatbench.core.errors import PermanentError
from wcatbench.core.types import AnswerKey, DatasetManifest, Privacy, Question, Record
from wcatbench.datasets.synthetic import generator

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
        records = [Record.model_validate(row) for row in rows]
        questions = [Question(id=row["id"], text=row["question"], as_of=row["as_of"]) for row in asked_rows]
        keys = [
            AnswerKey(
                question_id=row["id"],
                answers=tuple(row["answers"]),
                sources=tuple(row["required_citations"]),
                stale_answers=tuple(row["stale_answers"]),
            )
            for row in asked_rows
        ]
        corpus_sha, key_sha = dataset_files.write(out, records, questions, keys)
        kinds = {kind: sum(record.kind == kind for record in records) for kind in generator.KINDS}
        manifest = DatasetManifest(
            name=self.name,
            version=1 if size == SMALL else 2,
            privacy=Privacy.SYNTHETIC,
            params={"records": size, "seed": seed},
            records=len(records),
            questions=len(questions),
            corpus_sha256=corpus_sha,
            key_sha256=key_sha,
            extra={"source_counts": kinds, **extra},
        )
        dataset_files.write_json(out / dataset_files.MANIFEST, manifest.model_dump(mode="json"))
        return manifest
