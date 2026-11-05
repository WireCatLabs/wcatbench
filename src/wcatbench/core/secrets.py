"""Keys come from the system keyring into this process only: never printed, logged, or put on a command line."""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404

from wcatbench.core.errors import PermanentError
from wcatbench.observability.redaction import register_secret


def keyring_secret(service: str, account: str) -> str:
    tool = shutil.which("secret-tool")
    if tool is None:
        raise PermanentError("secret-tool not found; install libsecret-tools to read keys from the system keyring")
    done = subprocess.run(  # noqa: S603  # nosec B603
        [tool, "lookup", "service", service, "account", account], capture_output=True, text=True, check=False
    )
    secret = done.stdout.strip()
    if done.returncode != 0 or not secret:
        raise PermanentError(f"no keyring entry for service {service!r} account {account!r}")
    register_secret(secret)
    return secret


def service_key(service: str, account: str) -> str:
    """`<SERVICE>_API_KEY` from the environment if set, else the keyring entry `service`/`account`."""
    from_env = os.environ.get(f"{service.upper()}_API_KEY", "").strip()
    if from_env:
        register_secret(from_env)
        return from_env
    return keyring_secret(service, account)
