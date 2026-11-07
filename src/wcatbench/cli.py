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
from wcatbench.pipeline.fixture import export_fixture, score_predictions
from wcatbench.pipeline.search import REWRITES, search_run

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


@dataset_app.command("export-fixture")
def dataset_export_fixture(
    dataset: Annotated[str, typer.Argument(help="A dataset folder, or its name from `dataset build`.")],
    out: Annotated[Path, typer.Argument(help="A new folder for cli-testing's agent runners (--fixture).")],
) -> None:
    """Write a dataset as the fixture folder cli-testing's agent runners read."""
    try:
        manifest = export_fixture(_dataset_folder(dataset), out.expanduser())
    except PermanentError as error:
        raise _fail(error) from error
    typer.echo(f"{out}: fixture version {manifest['fixture_version']}, {manifest['records']} records")


@app.command()
def score(
    dataset: Annotated[str, typer.Option("--dataset", "-d", help="A dataset folder, or its name.")],
    predictions: Annotated[Path, typer.Option(help="An agent runner's predictions.json.")],
    engine: Annotated[str, typer.Option(help="What answered, recorded in scores.json.")],
    output: Annotated[Path, typer.Option(help="A new folder for scores.json and per-question.json.")],
) -> None:
    """Score an agent runner's answers against a dataset's key, in total and by family of question."""
    try:
        rows = json.loads(predictions.expanduser().read_text())
        result = score_predictions(_dataset_folder(dataset), rows, engine, output.expanduser())
    except PermanentError as error:
        raise _fail(error) from error
    typer.echo(json.dumps(result, indent=2))


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
