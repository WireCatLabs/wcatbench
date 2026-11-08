# Cleanup

Things to remove later, one per line: the path, why, the date. Removals happen in a batch after confirmation.
- ~/.local/share/wcatbench/builds/graphiti/synthetic-10444-74290fb3/wcatbench_graphiti_mem0_20261107/store/graphiti-episodes.json.before-crash-fix — ledger copy before dropping 34 episodes lost in the FalkorDB crash; remove once the build is scored (2026-11-08)
- ~/.local/share/wcatbench/builds/graphiti/synthetic-10444-74290fb3/wcatbench_graphiti_mem0_20261107/store/graphiti-episodes.json.truncated-0014 — the ledger cut by the full disk on 8 Nov; rebuilt from the graph; remove once the build is scored (2026-11-08)
- Docker container wcatbench-falkordb (FalkorDB 4.14.6, stopped) — replaced by wcatbench-falkordb-422 on the same volume after repeated crashes; remove after Graphiti is scored (2026-11-08)
- ~/.cache/wirecat-bench/falkordb-backup-20261108 — copy of the graph volume before the 4.22.3 switch; remove after Graphiti is scored (2026-11-08)
