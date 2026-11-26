# Changelog

## Unreleased

### Added

- **The rules-trial round.** A reproduction of the design of Danil Pismenny's agent memory trials on our own
  synthetic data: 36 Russian sources, 3 coding tasks with hidden checks (13 known and 5 unknown each), and the
  `staged` scorer, which counts stored, retrieved, old version inactive, applied and unknown apart, one row per
  check. `wcatbench trial run | contexts | probe | report | summary` runs Hermes sessions and scores them.
- **Hermes agent sessions in bubblewrap.** Each session sees its workspace, its frozen retrieval and the throwaway
  Hermes folder, nothing else. `wcatbench trial probe` proves it with no model. A session whose transcript names
  the answer key or the hidden checks counts as wrong.
- **Stores for memo, AgentMemory 0.9.30, Mem0 OSS 2.2.1, Hindsight slim 1.0.0 and OpenViking 0.4.17.1.** Each one
  runs on this machine with its own folders. Mem0 OSS and OpenViking run from their own virtualenvs.
- **`bin/hermes-codex-signin`.** Signs the owner's ChatGPT account into the throwaway Hermes folder by device code.

- **The first skeleton of wcatbench.** The adapter contracts for stores, agents, bindings and datasets, a run ledger
  that resumes, redacted JSON logs, a local SQLite full-text store, the oracle and no-op agents, and the
  deterministic answer scorer.
- **The synthetic dataset.** `wcatbench dataset build synthetic -p records=10000` writes the corpus, the questions,
  the answer key and the Mem0 subset. The corpus and subset digests equal the ones the cli-testing rounds published,
  and a test keeps them equal.

- **A test that rescores the published 2K round.** The saved answers of all seven setups in the cli-testing results
  table score exactly the published numbers, strict counts included.

- **Store builds and search scores.** `wcatbench store build | status | search` loads a dataset into a store in
  batches, resumes from what the store holds, waits until it is ready to answer, and scores recall@1, 5 and 10 of
  its own search. The recall scorer gives the published Supermemory and Mem0 numbers on their saved searches.

- **Supermemory and Mem0 stores.** One build is one Supermemory container tag or one Mem0 user. A build made by
  the earlier cli-testing scripts can be adopted with `store status --import-ledger` or `--all-sent`.

### Fixed

- **A resume never sends a record the service already accepted.** While Mem0 processes, its event feed can move an
  event to a page already read, and one walk then misses it: on 2026-11-05 one walk of 6,500 adds listed 2 as
  absent. Mem0 is now read twice and merged, and a record the ledger shows as accepted is reported, not sent again.

### Changed

- **A record's time field is now `timestamp`.** It matches the corpus file, so the published digests hold.
- **Stores key records by their place in the corpus** (`r0001` …), as the earlier scripts did, so their hosted
  builds can be checked and resumed from wcatbench. `Hit.record_ids` is now `Hit.keys`, and `Store.open` takes
  the build's start time.
