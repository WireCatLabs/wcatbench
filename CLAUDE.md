# wcatbench: working rules

wcatbench benchmarks AI agent memory: any agent, any memory store, the same questions. Start with
[docs/architecture.md](docs/architecture.md) (the concepts and the four adapter seams) and
[docs/adapters.md](docs/adapters.md).

The WireCat handbook (`docs/standards/` in `@wirecat/cli-base`) applies where it is not about npm or TypeScript. This
is the first Python repository in WireCat. Its Python equivalents are below. A repository may be stricter than the
handbook, never looser.

## Commands

| Task | Command |
|---|---|
| Install, hooks | `task install` |
| Everything CI runs | `task gate` |
| Tests, stop at first failure | `task test:fast` |
| Tests against real paid services | `task test:live` (by hand only, never in CI) |

## Rules

1. **The core never imports an adapter.** Adapters register through entry points (`pyproject.toml`). Layers and
   adapter independence are enforced by import-linter (`task lint:imports`).
2. **Results are never committed here.** Published results go to `WireCatLabs/cli-testing` under `performance/`.
   Runs, builds and datasets live under `WCATBENCH_HOME` and are git-ignored.
3. **Hosted stores get synthetic or public data only.** A dataset marked private is refused by any store with
   `hosted = True`. Never weaken that check.
4. **Keys come from the keyring, through `core.secrets`.** Never print, log or pass a key on a command line. Every key
   resolved is registered with the log redaction.
5. **Agents run in `core.sandbox.Sandbox`.** A throwaway HOME and `DBUS_SESSION_BUS_ADDRESS=disabled:` (unsetting it
   is not enough). The answer key must never be reachable from the sandbox.
6. **Every unit of slow or paid work writes a ledger line when it finishes.** Resume skips what the ledger and the
   store say is done. Never re-send to a store that charges per add without asking `held()` first.
7. **Errors are `TransientError` or `PermanentError`.** Only transient ones are retried, through `core.errors.retrying`.
8. **The answer scorer stays bit-for-bit compatible** with the published cli-testing runs. A change to it needs a
   rescore of the published predictions in the same PR.

## Style

- Python 3.13+, ruff (120 columns), mypy strict, double quotes.
- Tests: pytest with `describe_*` / `it_*` (pytest-describe). Live tests are marked `live` and skipped by default.
- Comments are sparse and say why, never what.
- Public text (README, docs, changelog) follows WireCat's voice: no semicolons, no long dashes, no hype words.

## Git

- Conventional commits, PR titles too. Squash merge only. The PR body follows the template (Task, Why, What, Testing).
- `CHANGELOG.md`: `## Unreleased` on top with the five fixed headings (Added, Changed — may break callers, Fixed,
  Security, Removed). Each entry starts with a bold sentence.
- Before 1.0.0 a breaking change raises the minor version.
- Never delete mid-task: add a line to `CLEANUP.md` (path, why, date). Never kill a process by name.

## Private working folder

Plans, research and journals do not go in this repository. They live in the private `WireCatLabs/cli-private`.
