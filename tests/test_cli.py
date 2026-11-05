from __future__ import annotations

import json

from typer.testing import CliRunner

from wcatbench import __version__
from wcatbench.cli import app

runner = CliRunner()


def describe_cli() -> None:
    def it_prints_its_version() -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.stdout

    def it_lists_adapters_as_json() -> None:
        result = runner.invoke(app, ["adapters", "list", "--json"])
        assert json.loads(result.stdout)["stores"]["fts"] == "wcatbench.stores.fts:FtsStore"

    def it_passes_doctor_on_a_machine_with_fts5() -> None:
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "sqlite fts5: True" in result.stdout
