# Cleanup

Things to remove later, one per line: the path, why, the date. Removals happen in a batch after confirmation.
- /var/tmp/wcat-dapi/ (Hermes clone and its signed-in home, store venvs, builds, runs): rules-trial work folder; keep until the results are in cli-testing. 2026-11-27
- /var/tmp/wcat-dapi/hermes-home/auth.json: the owner's Codex sign-in for the benchmark; remove (or sign out) once the rules-trial round ends. 2026-11-27
- /var/tmp/wcat-dapi/superseded-corpus-187b3c8e/: retrievals and the Mem0 build of the corpus without date lines, kept as evidence of the amendment. 2026-11-27
- /var/tmp/wcat-dapi/probe-artifacts/: files the first Hermes probe left in its home. 2026-11-27
- Docker container wcat-dapi-hindsight-slim and image ghcr.io/vectorize-io/hindsight:1.0.0-slim (1.4 GB): Hindsight slim variant. 2026-11-27
