"""The `wcatbench` command."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Annotated

import typer

from wcatbench import __version__
from wcatbench.config import get_settings
from wcatbench.core import dataset_files, registry
from wcatbench.core.errors import PermanentError
from wcatbench.observability.logging import setup_logging

app = typer.Typer(
    help="Benchmark AI agent memory: any agent, any memory store, the same questions.", no_args_is_help=True
)
adapters_app = typer.Typer(help="Installed adapters.", no_args_is_help=True)
app.add_typer(adapters_app, name="adapters")
dataset_app = typer.Typer(help="Datasets: build one, see what is built.", no_args_is_help=True)
app.add_typer(dataset_app, name="dataset")


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
