"""wcatbench: benchmark AI agent memory."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("wcatbench")
except PackageNotFoundError:  # pragma: no cover - running from a source tree without an install
    __version__ = "0.0.0"
