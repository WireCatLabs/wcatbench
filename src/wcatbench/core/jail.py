"""Operating-system isolation for one agent session: bubblewrap with only the named folders visible.

A throwaway HOME (core.sandbox) hides the owner's config from a polite agent. It does not stop an agent with a shell
from reading any file the user can read: in our LoCoMo round agents went after the gold answers 14 times until a
sandbox stopped them. Here the agent sees the system's programs, the folders bound below and nothing else: no home
folder, no answer key, no other session's files.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from wcatbench.core.errors import PermanentError

SYSTEM_READ_ONLY = (
    "/usr",
    "/etc/ssl",
    "/etc/ca-certificates",
    "/etc/pki",
    "/etc/hosts",
    "/etc/nsswitch.conf",
    "/etc/passwd",
    "/etc/group",
    "/run/systemd/resolve",
)
SYSTEM_LINKS = (("usr/bin", "/bin"), ("usr/sbin", "/sbin"), ("usr/lib", "/lib"), ("usr/lib64", "/lib64"))
INSIDE_HOME = "/home/agent"


@dataclass(frozen=True)
class Jail:
    read_only: tuple[Path, ...] = ()
    # (outside, inside) pairs the session may write.
    writable: tuple[tuple[Path, str], ...] = ()
    workdir: str = "/work"
    env: dict[str, str] = field(default_factory=dict)
    network: bool = True

    def command(self, argv: list[str]) -> list[str]:
        tool = shutil.which("bwrap")
        if tool is None:
            raise PermanentError("bubblewrap (bwrap) is not installed; agent sessions refuse to run without it")
        args = [tool, "--die-with-parent", "--new-session", "--unshare-all"]
        if self.network:
            args.append("--share-net")
        for path in SYSTEM_READ_ONLY:
            if Path(path).exists():
                args += ["--ro-bind", path, path]
        for target, link in SYSTEM_LINKS:
            args += ["--symlink", target, link]
        args += ["--symlink", "/run/systemd/resolve/stub-resolv.conf", "/etc/resolv.conf"]
        args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", INSIDE_HOME]  # nosec B108
        for folder in self.read_only:
            args += ["--ro-bind", str(folder), str(folder)]
        for outside, inside in self.writable:
            args += ["--bind", str(outside), inside]
        args += ["--clearenv"]
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "HOME": INSIDE_HOME,
            "TMPDIR": "/tmp",  # nosec B108
            "TZ": "UTC",
            "DBUS_SESSION_BUS_ADDRESS": "disabled:",
            **self.env,
        }
        for name, value in env.items():
            args += ["--setenv", name, value]
        return [*args, "--chdir", self.workdir, "--", *argv]
