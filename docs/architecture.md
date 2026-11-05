# wcatbench: architecture

Status: alpha. The core contracts exist; the adapters listed under v0.1 are being ported from the earlier scripts.

## What it is

wcatbench measures how well an AI agent remembers. It is an open source Python tool. You can plug in:

- any memory store (WireCat memo, Mem0, Supermemory, plain files, your own);
- any agent (OpenClaw, Hermes, later Claude Code and others);
- any dataset (our synthetic corpus, later LongMemEval and LoCoMo).

It runs them against each other and reports:

- correctness;
- sources;
- stale answers;
- time;
- cost.

### Where it goes past memorybench

The closest tool is [supermemoryai/memorybench](https://github.com/supermemoryai/memorybench). It ingests a store,
searches it, has a fixed model answer and has a model judge the answer. wcatbench does that too. It adds the following:

1. **The agent in the loop.** The real question is whether an agent that has the memory answers better, faster and
   cheaper. wcatbench runs the agent itself, with the store attached the way a user would attach it: a plugin, a CLI
   and its skill, an MCP server, or files. memorybench never runs an agent.
2. **Store builds are their own artifacts.** Hosted ingests take hours and cost money. A build is made once, kept on
   disk with its ledger and manifest, and reused by every run that names it.
3. **Valid runs, not only scored runs.** Each trial has an outcome apart from its score: `completed`, `error`,
   `timeout` or `invalid`. `invalid` means the agent could reach the answer key, or a tool ran in the wrong folder.
   We hit both in the earlier scripts: a CLI agent started in the home folder and listed the answer key's file name. An oracle setup must score everything and a no-op setup nothing on every dataset. A broken
   harness shows up before money is spent.
4. **Deterministic scoring first.** The answer key carries the expected value and its source records. The score is
   correct, strict, exact sources and stale, with no judge model needed. A model judge is a plug-in for datasets
   without a key.
5. **Cost of the whole setup.** Agent tokens are counted per trial: from the agent's own usage files, or from a small
   proxy on the model API. The source of each number is recorded. Store-side costs are reported per build.
6. **Local-first stores are first-class.** memo, plain files and an SQLite FTS floor run with no account, so anyone
   can reproduce a result for free.

## Concepts

| Concept | What it is |
|---|---|
| **Dataset** | records (the corpus) + questions with an answer key. Has a manifest (digests, generator version, `privacy: synthetic \| public \| private`). |
| **Record** | one message, mail, note or meeting: `id, kind, source, thread, author, time, text, metadata`. |
| **Question** | `id, text, as_of, answer, sources, category` (`fact`, `update`, `temporal`, `multi-hop`, `absent`). |
| **Store** | a memory system behind a store adapter. |
| **Build** | one dataset ingested into one store under one namespace (tag, user id, folder). Kept under `builds/`. |
| **Agent** | a program that answers questions, behind an agent adapter. `direct` is a fixed model with retrieved context, as in memorybench. |
| **Binding** | how one store is attached to one agent: plugin, CLI + skill, MCP, files. One per (agent, store) pair. |
| **Setup** | agent + binding + store build + model. One cell of the comparison. |
| **Round** | a config file: dataset, setups, limits, budget. Running it makes a **run**. |
| **Trial** | one question on one setup: answer, transcript, usage, outcome. |
| **Score** | a scorer's verdict on a trial. Stored apart, so a scorer change rescores without rerunning. |

## Adapters: the four seams

All four are Python `Protocol`s in `wcatbench.core`. Third parties ship their own as packages, registered through
entry points (`wcatbench.stores`, `wcatbench.agents`, `wcatbench.bindings`, `wcatbench.datasets`). Nothing in the
core imports a concrete adapter.

### Store adapter

```python
class Store(Protocol):
    name: str
    hosted: bool  # hosted stores refuse datasets whose privacy is "private"

    def version(self) -> str: ...
    def open(self, space: str, workdir: Path) -> None: ...  # space = tag / user id / folder
    def ingest(self, batch: list[Record]) -> BatchReceipt: ...  # one ledger line per call
    def held(self) -> dict[str, ItemState]: ...  # what the store holds now, by record id
    def settled(self, held: dict[str, ItemState]) -> bool: ...  # done building (memories, vectors, index)
    def search(self, query: str, k: int) -> list[Hit]: ...  # Hit = record ids, score, text, kind
    def describe(self) -> dict: ...  # counts for the manifest (documents, memories)
    def clear(self) -> None: ...
```

- `held()` is the store's own truth. The ledger is ours. Resume sends `records − held` plus failed records. A record
  that is still queued is not missing. This is the rule that stopped Mem0's add allowance being spent twice
  (measured on Mem0, November 2026).
- `settled()` exists because "indexed" and "ready to answer" differ. Supermemory reports a document `done` while its
  memories are still being built (seen November 2026).
- Record ids travel as metadata, never in the text, so a hit maps back to the corpus.

### Agent adapter

```python
class Agent(Protocol):
    name: str

    def version(self) -> str: ...
    def install(self, home: Sandbox) -> None: ...  # into a throwaway HOME, once per setup
    def ask(self, question: Question, ctx: TrialContext) -> AgentReply: ...

    # AgentReply: text, cited sources, usage (+ usage source), transcript path, outcome, seconds
```

- Built in: `oracle` (answers from the key), `noop` (answers nothing), `direct` (fixed model plus `store.search`),
  `openclaw`, `hermes`.
- The agent never parses the store: that is the binding's job.

### Binding

```python
class Binding(Protocol):
    agent: str
    store: str

    def attach(self, sandbox: Sandbox, build: Build) -> None: ...  # write plugin config, skill, MCP entry, files
    def checks(self, sandbox: Sandbox) -> list[Check]: ...  # proves the store is reachable before the run
```

- Every quirk we found lives here, not in the agents:
  - one memory plugin per OpenClaw home;
  - Mem0 changes the user id unless the agent is named `main`;
  - Hermes turns other characters in the tag into `_`;
  - memo's skill version.
- Planning a round fails early when a setup names a pair with no binding.

### Dataset

```python
class Dataset(Protocol):
    name: str

    def build(self, out: Path, **params) -> Manifest: ...  # seeded; same params, same digests
```

- `synthetic`: today's generator (`run.py`): projects, milestones, filler, changed facts, four kinds of record.
- Later: `longmemeval`, `locomo`, so a blog number sits beside the vendors' numbers.

### Scorers

`exact` (normalized, a leading article ignored), `strict`, `sources`, `stale`, `retrieval` (recall@k,
MRR). Later: `judge` (a model, for datasets without a key).

## Sandbox (defaults, not adapter duty)

Every agent trial runs with:

- a throwaway `HOME` per setup;
- `DBUS_SESSION_BUS_ADDRESS=disabled:`, so the system keyring is unreachable;
- a fixed working folder;
- a scrubbed environment.

The answer key and the run folder are outside anything the agent can reach. A post-trial check scans the transcript
for the key's path and marks the trial `invalid` if it shows up. Secrets come from the keyring into the wcatbench
process only. Every log line passes a redaction filter.

## Pipeline and resume

```
dataset build ─► store build (ingest → wait until settled) ─► trials (ask) ─► score ─► report
     manifest          ledger.jsonl, status-*.json, manifest       result.json        scores.jsonl   report.md
```

- Each stage reads the previous stage's manifest and checks digests, so a run cannot mix a 2K build with 10K
  questions.
- **Resume everywhere, one rule:** a unit (batch or trial) is done when its line or `result.json` exists. A rerun
  skips done units. `--force <stage>` redoes one stage.
- `wcatbench rescore <run>` reruns scorers only.
- `wcatbench restart <run>` makes a new run that records `restarted_from`.
- Parallel trials go through a small worker pool with a per-setup concurrency limit. Default 1: memory on this
  machine is the limit, not the API.

## On disk

```
~/.local/share/wcatbench/            (or --home)
  datasets/<name>-<digest8>/         corpus.jsonl, questions.json, key.json, manifest.json
  builds/<store>/<dataset>/<space>/  ledger.jsonl, status-<t>.json, manifest.json, store-local files (memo DB)
  runs/<run-id>/
    run.json                         resolved round config, versions, digests, host
    events.jsonl                     loguru JSON lines, OTel GenAI field names (gen_ai.usage.input_tokens …)
    trials/<setup>/<question>/       result.json, transcript.jsonl, usage.json, stdout.txt, stderr.txt
    scores.jsonl
    report.md
```

Reports are DuckDB queries over the JSONL. No database server.

## Package layout

```
wcatbench/                           this repository
  pyproject.toml                     uv, hatchling, Python ≥ 3.12; ruff, pytest, pyright
  LICENSE                            Apache-2.0, as cli-testing
  README.md                          30-second quick start: free local run (synthetic 2K × memo × direct)
  docs/
    architecture.md                  this file, moved
    adapters/store.md, agent.md, binding.md, dataset.md   how to write one, with a template
    results.md                       how results are published (cli-testing pages)
  configs/rounds/                    kg-2k.yml, kg-10k.yml (today's rounds as configs)
  src/wcatbench/
    core/                            types, protocols, manifest, ledger, sandbox, secrets, errors, registry
    observability/                   loguru setup, redaction, run context on every line
    datasets/synthetic/              generator (ported run.py) + its question templates
    stores/                          memo.py, files.py, fts.py, supermemory.py, mem0.py
    agents/                          oracle.py, noop.py, direct.py, openclaw/, hermes/
    bindings/                        openclaw_memo.py, openclaw_mem0.py, hermes_supermemory.py, …
    scoring/                         answer.py, sources.py, retrieval.py
    usage/                           agent_files.py, proxy.py (Anthropic-compatible, JSONL per trial), pricing.py
    pipeline/                        plan.py, build.py, trials.py, score.py
    report/                          duckdb queries, markdown tables
    cli.py                           Typer
  tests/
    unit/                            scorer, ledger, resume, manifest digests, redaction
    contract/                        one suite every store/agent adapter must pass (fake + real behind a flag)
    integration/                     2K synthetic × fts × direct with a fake model: the whole pipeline, offline
```

`tests/contract/` is what keeps it extensible: a new adapter is accepted when the same suite passes for it as for
ours.

## CLI

```
wcatbench dataset build synthetic --records 10000 --seed 7
wcatbench store build supermemory --dataset kg-10k [--space TAG] [--resume]
wcatbench store status supermemory --dataset kg-10k --space TAG
wcatbench run configs/rounds/kg-10k.yml [--resume] [--only q01] [--setup hermes+memo]
wcatbench rescore <run> | report <run> | compare <run> <run>
wcatbench show <run> <setup> <question>         one trial: answer, sources, tool calls, usage
wcatbench doctor                                adapters found, keys present (never printed), sandbox works
```

## Libraries

- Typer (CLI).
- pydantic and pydantic-settings (types, config).
- tenacity (retries on paid calls).
- loguru (logs and JSONL events, with the redaction from an earlier project of ours). The survey suggested structlog. loguru won because the redaction and the stdlib bridge already existed for it.
- DuckDB (reports).
- httpx (HTTP and the usage proxy).
- Nothing else in the core. Each adapter declares its own extras (`[mem0]`, `[supermemory]`).

## v0.1 scope, and what waits

v0.1 contains only what today's rounds use:

- the synthetic dataset;
- memo, files, fts, Supermemory and Mem0;
- the oracle, noop, direct, OpenClaw and Hermes agents;
- the deterministic scorers;
- usage from agent files;
- JSONL and DuckDB reports.

Later, not built now:

- Zep;
- the judge scorer;
- LongMemEval and LoCoMo;
- the usage proxy, once OpenClaw and Hermes are checked against a custom base URL;
- a web viewer;
- Phoenix export;
- Claude Code as an agent.

## Migration gates

The current scripts in `cli-testing/performance/agents/knowledge-graph-memory/` stay until these pass, as tests in
wcatbench:

1. The ported generator reproduces the published digests. Passes, in `tests/test_synthetic_dataset.py`:
   - the 10K corpus `e99e1e52…b8f0`;
   - the Mem0 subset `6273370e…b973`;
   - the 2K fixture.
2. Rescoring the saved 2K and 10K predictions gives exactly the numbers in RESULTS.md, strict counts included.
   Passes for all seven 2K rows, in `tests/test_published_results.py`. The 10K round has no answers yet.
3. The oracle scores 50/50 and the no-op 0/50 on both datasets. Passes on the 10K corpus.

Until the gates pass, nothing is published from wcatbench. The 10K round finishes on the current scripts.

## Results

- The tool lives in its own repository.
- Results stay in cli-testing: `performance/memory/<topic>/README.md`, with the round config and the wcatbench
  version that produced them.
- Real data stays private; this is the cli-testing rule.
