<div align="center">

<h1>wcatbench</h1>

**How well does your AI agent remember? Put any agent next to any memory store and ask both the same questions.**

[Quick start](#quick-start) · [How it works](#how-it-works) · [Adapters](#adapters) · [Results](#results) ·
[Development](#development)

![Status: alpha](https://img.shields.io/badge/status-alpha-orange)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue)

</div>

Memory tools for agents publish their own numbers, measured their own way. I wanted one harness where the agent itself
runs with the memory attached the way a user would attach it, and every setup answers the same questions from the same
data. wcatbench is that harness. It comes from the benchmarks we ran for [WireCat](https://wirecat.dev), and it is
early.

**Example.** 50 questions on a 2,000 record synthetic corpus, Hermes with Claude Sonnet and three memory setups.
These come from the scripts wcatbench grows out of, not from wcatbench itself yet:

```text
setup                  correct  strict  exact sources  stale  s/question  $ / 50 questions
hermes alone           50       40      37             0      8.5         0.88
hermes + mem0          48       38      10             2      11.4        0.78
hermes + wirecat memo  50       40      33             0      10.3        0.98
```

## Quick start

wcatbench is not on PyPI yet. Run it straight from GitHub with [uv](https://docs.astral.sh/uv/):

```sh
uvx --from git+https://github.com/WireCatLabs/wcatbench wcatbench doctor
uvx --from git+https://github.com/WireCatLabs/wcatbench wcatbench adapters list
```

`doctor` checks the data folder and SQLite full text search. `adapters list` shows every store, agent and scorer it
can load.

## What it measures

- **Correct answers.** The answer key holds the expected value, so no judge model is needed. A leading "the" or "a"
  does not count against an answer, and the strict count keeps it.
- **Exact sources.** Did the agent cite the records the answer came from?
- **Stale answers.** The corpus changes facts over time. An agent that answers with the old value is counted apart
  from one that is just wrong.
- **Time and cost.** Seconds per question and the agent's own token spend, with the place each number came from.
- **Validity.** A trial where the agent could reach the answer key is marked invalid, not scored.

## How it works

```text
dataset ──► store build ──► trials ──► scores ──► report
            ingest, wait     one question     answer key     tables
            until settled    on one setup
```

- A **dataset** is a corpus of records (messages, mail, notes, meetings) plus questions and an answer key. Each
  dataset says whether it is synthetic, public or private. A hosted store refuses a private one.
- A **store build** loads one dataset into one memory store. Hosted stores take hours and cost money, so a build is
  made once and reused by every run that names it. It keeps a ledger, one line per batch, so a stopped build continues
  where it stopped and never pays twice.
- A **setup** is an agent, a memory store, the way the store is attached (a plugin, a CLI with its instructions, an
  MCP server or plain files) and a model.
- A **trial** is one question on one setup. Each trial keeps its answer, a transcript, usage and an outcome. A rerun
  skips finished trials, and scores can be recomputed without running any agent again.
- Two built-in agents check the harness itself. The oracle answers from the key and must score everything. The no-op
  agent answers nothing and must score zero.

The full design is in [docs/architecture.md](docs/architecture.md).

## Adapters

wcatbench finds adapters through Python entry points, so a package installed next to it adds a store or an agent
without a change here.

| Kind | Built in now | Next |
|---|---|---|
| Stores | `fts` (SQLite full text, no model) | WireCat memo, plain files, Mem0, Supermemory |
| Agents | `oracle`, `noop` | Hermes, OpenClaw, a fixed model with search results |
| Scorers | `answer` (correct, strict, sources, stale) | recall@k for search only runs |
| Datasets | | the synthetic corpus (2,000 and 10,000 records), later LongMemEval and LoCoMo |

How to write one: [docs/adapters.md](docs/adapters.md).

## Security

- Keys for paid services come from the system keyring into the wcatbench process. They are never printed, logged or
  put on a command line, and every log line passes a filter that removes known keys.
- Agents run in a throwaway home folder with the system keyring out of reach.
- Synthetic data only goes to hosted stores unless you say otherwise.

Found a problem? See [SECURITY.md](SECURITY.md).

## Limits

- Alpha. The command line and the adapter contracts will change before 1.0.
- Linux is what it is tested on. macOS should work.
- The numbers above come from the earlier scripts in
  [cli-testing](https://github.com/WireCatLabs/cli-testing/tree/main/performance/agents/knowledge-graph-memory).
  wcatbench reproduces them before it publishes anything of its own.

## Results

Published results live in [cli-testing](https://github.com/WireCatLabs/cli-testing) under `performance/`, each with
the round config and the wcatbench version that produced it.

## Part of WireCat

[WireCat](https://wirecat.dev) is a set of local CLIs that give AI agents your messages, mail, meetings and notes.
wcatbench is how we check whether that memory helps, against other tools and against no memory at all.

## Development

```sh
task install     # uv sync and the git hooks
task gate        # lint, format, import contracts, mypy strict, bandit, tests with coverage
task test:fast   # stop at the first failure
```

Rules for contributors and agents: [AGENTS.md](AGENTS.md). Changes: [CHANGELOG.md](CHANGELOG.md).

## License

[Apache License 2.0](LICENSE)
