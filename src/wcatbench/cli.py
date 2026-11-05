"""The `wcatbench` command."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from typing import Annotated

import typer

from wcatbench import __version__
from wcatbench.config import get_settings
from wcatbench.core import registry
from wcatbench.observability.logging import setup_logging

app = typer.Typer(
    help="Benchmark AI agent memory: any agent, any memory store, the same questions.", no_args_is_help=True
)
adapters_app = typer.Typer(help="Installed adapters.", no_args_is_help=True)
app.add_typer(adapters_app, name="adapters")


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
