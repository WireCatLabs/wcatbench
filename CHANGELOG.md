# Changelog

## Unreleased

### Added

- **The first skeleton of wcatbench.** The adapter contracts for stores, agents, bindings and datasets, a run ledger
  that resumes, redacted JSON logs, a local SQLite full-text store, the oracle and no-op agents, and the
  deterministic answer scorer.
- **The synthetic dataset.** `wcatbench dataset build synthetic -p records=10000` writes the corpus, the questions,
  the answer key and the Mem0 subset. The corpus and subset digests equal the ones the cli-testing rounds published,
  and a test keeps them equal.

- **A test that rescores the published 2K round.** The saved answers of all seven setups in the cli-testing results
  table score exactly the published numbers, strict counts included.

### Changed

- **A record's time field is now `timestamp`.** It matches the corpus file, so the published digests hold.
