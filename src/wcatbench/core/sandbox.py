"""The environment every agent trial runs in. Defaults here, so no adapter has to remember them.

A throwaway HOME hides the user's agent config. It does not hide the system keyring, which is reached over D-Bus;
`DBUS_SESSION_BUS_ADDRESS=disabled:` does. Unsetting the variable is not enough: D-Bus then falls back to
`$XDG_RUNTIME_DIR/bus`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PASSED_THROUGH = ("PATH", "LANG", "LC_ALL", "TERM", "TZ")


@dataclass(frozen=True)
class Sandbox:
    home: Path
    workdir: Path
    extra_env: dict[str, str] = field(default_factory=dict)

    def prepare(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.workdir.mkdir(parents=True, exist_ok=True)

    def env(self) -> dict[str, str]:
        base = {name: os.environ[name] for name in PASSED_THROUGH if name in os.environ}
        return {
            **base,
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local" / "share"),
            "XDG_CACHE_HOME": str(self.home / ".cache"),
            "DBUS_SESSION_BUS_ADDRESS": "disabled:",
            **self.extra_env,
        }

    def can_reach(self, path: Path) -> bool:
        """The answer key and the run folder must not sit under anything the agent can list (BUG-518)."""
        target = path.resolve()
        return any(target.is_relative_to(root.resolve()) for root in (self.home, self.workdir))
