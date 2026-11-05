from __future__ import annotations

from pathlib import Path

import pytest

from wcatbench.core import registry
from wcatbench.core.errors import PermanentError
from wcatbench.core.sandbox import Sandbox


def describe_sandbox() -> None:
    def it_hides_the_keyring_and_the_real_home(tmp_path: Path) -> None:
        env = Sandbox(home=tmp_path / "home", workdir=tmp_path / "work").env()
        assert env["DBUS_SESSION_BUS_ADDRESS"] == "disabled:"
        assert env["HOME"] == str(tmp_path / "home")

    def it_sees_when_the_answer_key_is_reachable(tmp_path: Path) -> None:
        sandbox = Sandbox(home=tmp_path / "home", workdir=tmp_path / "work")
        sandbox.prepare()
        assert sandbox.can_reach(tmp_path / "work" / "key.json")
        assert not sandbox.can_reach(tmp_path / "run" / "key.json")


def describe_registry() -> None:
    def it_lists_the_built_in_adapters() -> None:
        assert {"oracle", "noop"} <= set(registry.available("agents"))
        assert "fts" in registry.available("stores")

    def it_names_the_choices_when_an_adapter_is_missing() -> None:
        with pytest.raises(PermanentError, match="installed: fts"):
            registry.load("stores", "zep")

    def it_loads_an_adapter_by_name() -> None:
        assert registry.load("stores", "fts").name == "fts"
