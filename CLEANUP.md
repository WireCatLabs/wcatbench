# Cleanup

Things to remove later, one per line: the path, why, the date. Removals happen in a batch after confirmation.
- /var/tmp/wcat-dapi/ (Hermes clone and its signed-in home, store venvs, builds, runs): rules-trial work folder; keep until the results are in cli-testing. 2026-11-27
- /var/tmp/wcat-dapi/hermes-home/auth.json: the owner's Codex sign-in for the benchmark; remove (or sign out) once the rules-trial round ends. 2026-11-27
- /var/tmp/wcat-dapi/superseded-corpus-187b3c8e/: retrievals and the Mem0 build of the corpus without date lines, kept as evidence of the amendment. 2026-11-27
- /var/tmp/wcat-dapi/probe-artifacts/: files the first Hermes probe left in its home. 2026-11-27
- Docker container wcat-dapi-hindsight-slim and image ghcr.io/vectorize-io/hindsight:1.0.0-slim (1.4 GB): Hindsight slim variant. 2026-11-27
- /var/tmp/wcat-dapi/node and /var/tmp/wcat-dapi/memo-cli: node and memo copies the jailed agent runs in experiment 2 and the unrestricted rows. 2026-11-27
- /var/tmp/wcat-dapi/memo-template: memo state with e5-small downloaded once, copied per session. 2026-11-27
- /var/tmp/wcat-dapi/agent-tools/: search tool scripts bound into the jail. 2026-11-27
- /var/tmp/wcat-dapi/wcatbench-home/builds-dev and builds-e3: dev set and e3 gate store builds. 2026-11-27
- /var/tmp/wcat-dapi/superseded-memo-titles, superseded-ov-levels, superseded-e3-hindsight-race: pre-fix evidence, reported apart. 2026-11-27
- /var/tmp/wcat-dapi/agentmemory: AgentMemory npm install and its throwaway home. 2026-11-27
- /var/tmp/wcat-dapi/wcatbench-home/runs/e1-prefix: symlinks to the pre-fix memo and OpenViking evidence, for their summary rows. 2026-11-27
- /var/tmp/wcat-dapi/superseded-e2-ov-loop: experiment 2 OpenViking chains that failed on the SDK event-loop bug, kept as evidence. 2026-11-27
- /var/tmp/wcat-dapi/hermes-stray-e2-kill: Hermes home files left by a session I stopped mid-run (contains no sign-in). 2026-11-27
