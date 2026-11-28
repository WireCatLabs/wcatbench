"""The `wcatbench` command."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from wcatbench import __version__
from wcatbench.config import get_settings
from wcatbench.core import dataset_files, registry
from wcatbench.core.errors import PermanentError
from wcatbench.observability.logging import setup_logging
from wcatbench.pipeline.build import Build, Selection
from wcatbench.pipeline.corrections import STORES as GATE_STORES
from wcatbench.pipeline.corrections import Gate
from wcatbench.pipeline.dialogue import VARIANTS as DIALOGUE_VARIANTS
from wcatbench.pipeline.dialogue import DialogueRound
from wcatbench.pipeline.full_use import KIND as FULL_USE
from wcatbench.pipeline.full_use import FullUseRound, curate_memory_bank
from wcatbench.pipeline.rules_trial import VARIANTS
from wcatbench.pipeline.rules_trial import Round as RulesTrialRound
from wcatbench.pipeline.search import REWRITES, search_run
from wcatbench.pipeline.unrestricted import VARIANTS as UNRESTRICTED
from wcatbench.pipeline.unrestricted import UnrestrictedRound

app = typer.Typer(
    help="Benchmark AI agent memory: any agent, any memory store, the same questions.", no_args_is_help=True
)
adapters_app = typer.Typer(help="Installed adapters.", no_args_is_help=True)
app.add_typer(adapters_app, name="adapters")
dataset_app = typer.Typer(help="Datasets: build one, see what is built.", no_args_is_help=True)
app.add_typer(dataset_app, name="dataset")
store_app = typer.Typer(help="Store builds: load a dataset into a store, check it, search it.", no_args_is_help=True)
app.add_typer(store_app, name="store")


def _version(value: bool) -> None:
    if value:
        typer.echo(f"wcatbench {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Print the version and exit.")
    ] = False,
) -> None:
    settings = get_settings()
    setup_logging(settings.log_format, settings.log_level)


@adapters_app.command("list")
def adapters_list(as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False) -> None:
    """Every adapter wcatbench can load, by kind."""
    found = {kind: registry.available(kind) for kind in registry.GROUPS}
    if as_json:
        typer.echo(json.dumps(found, indent=2))
        return
    for kind, adapters in found.items():
        typer.echo(f"{kind}: {', '.join(sorted(adapters)) or '-'}")


@app.command()
def doctor() -> None:
    """Check that this machine can run wcatbench: the data folder and SQLite full-text search."""
    settings = get_settings()
    checks = {
        "data folder": str(settings.home),
        "sqlite fts5": _has_fts5(),
        "adapters": sum(len(registry.available(kind)) for kind in registry.GROUPS),
    }
    for name, value in checks.items():
        typer.echo(f"{name}: {value}")
    if checks["sqlite fts5"] is not True:
        raise typer.Exit(code=1)


def _has_fts5() -> bool:
    with closing(sqlite3.connect(":memory:")) as db:
        try:
            db.execute("CREATE VIRTUAL TABLE probe USING fts5(text)")
        except sqlite3.OperationalError:
            return False
    return True


def _params(pairs: list[str]) -> dict[str, int]:
    params = {}
    for pair in pairs:
        name, _, value = pair.partition("=")
        if not name or not value.isdigit():
            raise typer.BadParameter(f"{pair!r} is not name=number", param_hint="--param")
        params[name] = int(value)
    return params


@dataset_app.command("build")
def dataset_build(
    name: Annotated[str, typer.Argument(help="An installed dataset adapter, such as synthetic.")],
    param: Annotated[
        list[str] | None, typer.Option("--param", "-p", help="name=number, repeatable: -p records=10000 -p seed=7.")
    ] = None,
) -> None:
    """Build a dataset into the data folder, named by its corpus digest. Building it again changes nothing."""
    datasets = get_settings().home / "datasets"
    datasets.mkdir(parents=True, exist_ok=True)
    try:
        dataset = registry.load("datasets", name)()
        with tempfile.TemporaryDirectory(dir=datasets, prefix=".building-") as scratch:
            manifest = dataset.build(Path(scratch), _params(param or []))
            target = datasets / f"{name}-{manifest.records}-{manifest.corpus_sha256[:8]}"
            if not target.exists():
                shutil.copytree(scratch, target)
    except PermanentError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=2) from error
    built = dataset_files.manifest(target)
    typer.echo(f"{target}")
    typer.echo(f"records {built.records}, questions {built.questions}, corpus sha256 {built.corpus_sha256}")


def _fail(error: PermanentError) -> typer.Exit:
    typer.echo(f"error: {error}", err=True)
    return typer.Exit(code=2)


def _dataset_folder(dataset: str) -> Path:
    """A path, or a folder name under the data folder's datasets/ (as `dataset build` printed it)."""
    path = Path(dataset).expanduser()
    if not path.is_dir():
        path = get_settings().home / "datasets" / dataset
    if not (path / dataset_files.MANIFEST).is_file():
        raise PermanentError(f"no built dataset at {dataset}; run `wcatbench dataset build` first")
    return path


StoreName = Annotated[str, typer.Argument(help="An installed store adapter, such as fts or supermemory.")]
DatasetOption = Annotated[
    str, typer.Option("--dataset", "-d", help="A dataset folder, or its name from `dataset build`.")
]
SpaceOption = Annotated[str, typer.Option("--space", help="Tag, user id or folder inside the store; one per build.")]
SubsetOption = Annotated[str | None, typer.Option("--subset", help="Load only the dataset's subset-<name>.json.")]
StartedOption = Annotated[
    datetime | None,
    typer.Option("--started", help="When a build made elsewhere began (UTC); only read when the build is new here."),
]


def _build(store: str, dataset: str, space: str, subset: str | None) -> Build:
    folder = _dataset_folder(dataset)
    selection = Selection.load(folder, subset)
    where = get_settings().home / "builds" / store / folder.name / space
    return Build(registry.load("stores", store)(), folder, space, where, selection)


@store_app.command("build")
def store_build(
    store: StoreName,
    dataset: DatasetOption,
    space: SpaceOption,
    subset: SubsetOption = None,
    resume: Annotated[
        bool, typer.Option("--resume", help="Continue a stopped build: send only what is missing.")
    ] = False,
    wait_minutes: Annotated[float, typer.Option(help="Stop waiting for the store after this long.")] = 30,
    poll_seconds: Annotated[float, typer.Option(help="Seconds between two checks while waiting.")] = 300,
) -> None:
    """Load a dataset into a store, then wait until the store is ready to answer."""
    try:
        build = _build(store, dataset, space, subset)
        with closing(build.store):
            summary = build.run(resume=resume, wait_seconds=wait_minutes * 60, poll_seconds=poll_seconds)
    except PermanentError as error:
        raise _fail(error) from error
    typer.echo(f"{build.folder}")
    typer.echo(json.dumps({key: summary[key] for key in ("sent_this_run", "by_status", "settled")}))


@store_app.command("status")
def store_status(
    store: StoreName,
    dataset: DatasetOption,
    space: SpaceOption,
    subset: SubsetOption = None,
    started: StartedOption = None,
    import_ledger: Annotated[
        Path | None, typer.Option(help="The ledger.jsonl of a build made by the earlier cli-testing scripts.")
    ] = None,
    all_sent: Annotated[
        bool, typer.Option("--all-sent", help="A build made elsewhere with no ledger, known to have sent every record.")
    ] = False,
) -> None:
    """Ask the store what it holds for a build, and save the answer as status-<time>.json. Sends nothing."""
    try:
        build = _build(store, dataset, space, subset)
        with closing(build.store):
            build.open(resume=True, started=started.replace(tzinfo=UTC) if started else None)
            if import_ledger:
                typer.echo(f"imported {build.import_ledger(import_ledger)} batches")
            if all_sent:
                build.adopt_all_sent()
            _, status = build.check()
            path = build.write_status(status)
    except PermanentError as error:
        raise _fail(error) from error
    typer.echo(f"{path}")
    typer.echo(json.dumps(status, indent=2))


@store_app.command("search")
def store_search(
    store: StoreName,
    dataset: DatasetOption,
    space: SpaceOption,
    subset: SubsetOption = None,
    rewrite: Annotated[
        list[str] | None, typer.Option(help=f"Question forms, repeatable: {', '.join(REWRITES)}. Default both.")
    ] = None,
) -> None:
    """Ask the store's own search every question and score recall@1, 5 and 10. No answer model."""
    forms = rewrite or list(REWRITES)
    unknown = set(forms) - set(REWRITES)
    if unknown:
        raise typer.BadParameter(f"unknown form {', '.join(sorted(unknown))}", param_hint="--rewrite")
    try:
        build = _build(store, dataset, space, subset)
        with closing(build.store):
            build.open(resume=True)
            folder = build.folder / "searches" / f"{datetime.now(UTC):%Y%m%dT%H%M%S%f}"
            results = search_run(build.store, build.dataset, dataset_files.records(build.dataset), folder, forms)
    except PermanentError as error:
        raise _fail(error) from error
    typer.echo(f"{folder}")
    for form, row in results["scores"].items():
        typer.echo(
            f"{form}: recall@1 {row['recall@1']:.2f}, @5 {row['recall@5']:.2f}, @10 {row['recall@10']:.2f}, "
            f"empty {row['empty_replies']}"
        )


trial_app = typer.Typer(help="Agent trials: sessions in a jail, hidden checks, staged scores.", no_args_is_help=True)
app.add_typer(trial_app, name="trial")
RunOption = Annotated[str, typer.Option("--run", help="Run folder name under the data folder's runs/.")]
DesignOption = Annotated[str, typer.Option("--design", help="his (3 tasks x 2 applications), ours or all.")]


def _round(dataset: str, run: str, model: str) -> RulesTrialRound:
    home = get_settings().home
    agent = registry.load("agents", "hermes")(model=model)
    return RulesTrialRound(
        dataset=_dataset_folder(dataset), run=home / "runs" / run, builds=home / "builds", agent=agent
    )


@trial_app.command("run")
def trial_run(
    variant: Annotated[str, typer.Argument(help=f"One of: {', '.join(VARIANTS)}.")],
    dataset: DatasetOption,
    run: RunOption,
    design: DesignOption = "his",
    model: Annotated[str, typer.Option("--model", help="Hermes model through the Codex sign-in.")] = "gpt-5.6-terra",
) -> None:
    """Run one variant's sessions. A finished session is skipped on the next run."""
    try:
        _round(dataset, run, model).go(variant, design)
    except PermanentError as error:
        raise _fail(error) from error


@trial_app.command("report")
def trial_report(
    variant: Annotated[str, typer.Argument(help=f"One of: {', '.join(VARIANTS)}.")],
    dataset: DatasetOption,
    run: RunOption,
    design: DesignOption = "his",
) -> None:
    """Per-stage totals for one variant, as JSON. Stages are never added into one score."""
    typer.echo(json.dumps(_round(dataset, run, "unused").report(variant, design), ensure_ascii=False, indent=2))


@trial_app.command("contexts")
def trial_contexts(
    variant: Annotated[str, typer.Argument(help=f"One of: {', '.join(VARIANTS)}.")],
    dataset: DatasetOption,
    run: RunOption,
) -> None:
    """Build and freeze one variant's retrievals with no agent: the free stored and retrieved stages."""
    try:
        contexts = _round(dataset, run, "unused").contexts(variant)
    except PermanentError as error:
        raise _fail(error) from error
    typer.echo(json.dumps({qid: entry["tokens"] for qid, entry in sorted(contexts.items())}))


@trial_app.command("probe")
def trial_probe(dataset: DatasetOption, run: RunOption) -> None:
    """No model: prove the agent's jail hides the owner's home, the answer key and the hidden checks."""
    result = _round(dataset, run, "unused").probe()
    typer.echo("\n".join(result["output"]))
    if result["readable"]:
        raise typer.Exit(code=1)


@trial_app.command("summary")
def trial_summary(dataset: DatasetOption, run: RunOption, design: DesignOption = "his") -> None:
    """Every variant's stages as one Markdown table; writes rows-<design>.jsonl and summary-<design>.md to the run."""
    trial_round = _round(dataset, run, "unused")
    table, rows = trial_round.summary(design)
    (trial_round.run / f"summary-{design}.md").write_text(table)
    with (trial_round.run / f"rows-{design}.jsonl").open("w") as lines:
        for row in rows:
            lines.write(json.dumps(row, ensure_ascii=False) + "\n")
    typer.echo(table)


E2_VARIANTS = ", ".join(DIALOGUE_VARIANTS)


def _dialogue(dataset: str, run: str, model: str) -> DialogueRound:
    home = get_settings().home
    agent = registry.load("agents", "hermes")(model=model)
    return DialogueRound(dataset=_dataset_folder(dataset), run=home / "runs" / run, builds=home / "builds", agent=agent)


@trial_app.command("dialogue")
def trial_dialogue(
    variant: Annotated[str, typer.Argument(help=f"One of: {E2_VARIANTS}.")],
    dataset: DatasetOption,
    run: RunOption,
    reps: Annotated[int, typer.Option("--reps", help="Independent chains per scenario.")] = 2,
    model: Annotated[str, typer.Option("--model", help="Hermes model through the Codex sign-in.")] = "gpt-5.6-terra",
) -> None:
    """Experiment 2: chains of sessions A, B and C per scenario. A finished session is skipped on the next run."""
    if variant not in DIALOGUE_VARIANTS:
        raise typer.BadParameter(f"unknown variant {variant}; one of: {E2_VARIANTS}")
    _dialogue(dataset, run, model).go(variant, reps)


@trial_app.command("dialogue-summary")
def trial_dialogue_summary(dataset: DatasetOption, run: RunOption) -> None:
    """Experiment 2's table; writes e2/summary.md and e2/rows.jsonl to the run."""
    trial_round = _dialogue(dataset, run, "unused")
    table, rows = trial_round.summary()
    (trial_round.run / "e2" / "summary.md").write_text(table)
    with (trial_round.run / "e2" / "rows.jsonl").open("w") as lines:
        for row in rows:
            lines.write(json.dumps(row, ensure_ascii=False) + "\n")
    typer.echo(table)


def _unrestricted(dataset: str, run: str, model: str, builds: str | None) -> UnrestrictedRound:
    home = get_settings().home
    agent = registry.load("agents", "hermes")(model=model)
    return UnrestrictedRound(
        dataset=_dataset_folder(dataset), run=home / "runs" / run, builds=home / (builds or "builds"), agent=agent
    )


BuildsOption = Annotated[str | None, typer.Option("--builds", help="Builds folder under the home (dev set: its own).")]


@trial_app.command("unrestricted")
def trial_unrestricted(
    variant: Annotated[str, typer.Argument(help=f"One of: {', '.join(UNRESTRICTED)}.")],
    dataset: DatasetOption,
    run: RunOption,
    design: DesignOption = "his",
    builds: BuildsOption = None,
    model: Annotated[str, typer.Option("--model", help="Hermes model through the Codex sign-in.")] = "gpt-5.6-terra",
) -> None:
    """Ours, unrestricted: the agent searches memory itself with the frozen strategy prompt."""
    if variant not in UNRESTRICTED:
        raise typer.BadParameter(f"unknown variant {variant}; one of: {', '.join(UNRESTRICTED)}")
    _unrestricted(dataset, run, model, builds).go(variant, design)


@trial_app.command("unrestricted-summary")
def trial_unrestricted_summary(
    dataset: DatasetOption, run: RunOption, design: DesignOption = "his", builds: BuildsOption = None
) -> None:
    """The unrestricted rows as one table; writes summary-unrestricted-<design>.md to the run."""
    trial_round = _unrestricted(dataset, run, "unused", builds)
    table, rows = trial_round.summary(design)
    (trial_round.run / f"summary-unrestricted-{design}.md").write_text(table)
    with (trial_round.run / f"rows-unrestricted-{design}.jsonl").open("w") as lines:
        for row in rows:
            lines.write(json.dumps(row, ensure_ascii=False) + "\n")
    typer.echo(table)


@trial_app.command("corrections")
def trial_corrections(
    store: Annotated[str, typer.Argument(help=f"One of: {', '.join(GATE_STORES)}.")],
    run: RunOption,
) -> None:
    """Experiment 3: three versions of eleven rules into one store, then the 44 checks of the gate. No agent."""
    home = get_settings().home
    result = Gate(builds=home / "builds-e3", run=home / "runs" / run).check(store)
    typer.echo(f"{store}: {result['passed']}/{result['total']} gate {'pass' if result['gate'] else 'fail'}")


@trial_app.command("corrections-summary")
def trial_corrections_summary(run: RunOption) -> None:
    """Experiment 3's table; writes e3/summary.md to the run."""
    home = get_settings().home
    table = Gate(builds=home / "builds-e3", run=home / "runs" / run).summary()
    (home / "runs" / run / "e3" / "summary.md").write_text(table)
    typer.echo(table)


def _full_use(size: str, run: str, model: str, timeout: int = 900, agent_name: str = "hermes") -> FullUseRound:
    home = get_settings().home
    agent = registry.load("agents", agent_name)(model=model, timeout=timeout)
    return FullUseRound(
        dataset=_dataset_folder(f"full-use-{size}"), run=home / "runs" / run / size, size=size, agent=agent
    )


@trial_app.command("full-use")
def trial_full_use(
    contestant: Annotated[str, typer.Argument(help=f"One of: {', '.join(FULL_USE)}.")],
    size: Annotated[str, typer.Option("--size", help="1x, 10x or 100x.")],
    run: RunOption,
    limit: Annotated[int, typer.Option("--limit", help="Only the first N sessions (stages 2 and 5).")] = 0,
    model: Annotated[str, typer.Option("--model", help="Hermes model through the Codex sign-in.")] = "gpt-5.6-terra",
    agent: Annotated[
        str, typer.Option("--agent", help="hermes (Codex sign-in), hermes-api (OpenAI API key) or claude.")
    ] = "hermes",
) -> None:
    """The full-use round: one contestant at one archive size. A finished session is skipped on the next run."""
    try:
        trial_round = _full_use(size, run, model, agent_name=agent)
        if contestant == "memory-bank":
            curator = registry.load("agents", "hermes")(model=model, timeout=3600)
            curate_memory_bank(trial_round.dataset, trial_round.stores / "memory-bank", curator)
        trial_round.go(contestant, limit or None)
    except PermanentError as error:
        raise _fail(error) from error


@trial_app.command("full-use-summary")
def trial_full_use_summary(
    run: RunOption,
    also: Annotated[list[str] | None, typer.Option("--also", help="More runs to blind together with this one.")] = None,
) -> None:
    """Every contestant and size of a full-use run as JSON rows; writes metrics.json and blind sheets to the run."""
    from wcatbench.pipeline import full_use_report

    home = get_settings().home
    folder = home / "runs" / run
    datasets = {
        path.name: _dataset_folder(f"full-use-{path.name}")
        for path in folder.iterdir()
        if path.is_dir() and (path / "trials").is_dir()
    }
    rows = full_use_report.metrics(folder, datasets)
    (folder / "metrics.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    full_use_report.blind_sheets([folder, *(home / "runs" / name for name in also or [])], folder / "blind" / "sheets")
    typer.echo(json.dumps(rows, ensure_ascii=False, indent=1))
