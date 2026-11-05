from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from loguru import logger
from pytest_mock import MockerFixture

from wcatbench.core import secrets
from wcatbench.core.errors import PermanentError, TransientError, retrying
from wcatbench.core.manifest import sha256_file, sha256_text
from wcatbench.observability.logging import log_context, setup_logging
from wcatbench.observability.redaction import scrub_secrets


def describe_manifest() -> None:
    def it_digests_a_file_and_its_text_the_same(tmp_path: Path) -> None:
        path = tmp_path / "corpus.jsonl"
        path.write_text('{"id": "r0001"}\n')
        assert sha256_file(path) == sha256_text('{"id": "r0001"}\n')


def describe_retrying() -> None:
    def it_retries_a_transient_error_and_not_a_permanent_one(mocker: MockerFixture) -> None:
        mocker.patch("time.sleep")
        calls = {"transient": 0, "permanent": 0}

        @retrying(attempts=3, max_wait=0.01)
        def flaky() -> str:
            calls["transient"] += 1
            if calls["transient"] < 3:
                raise TransientError("HTTP 503")
            return "ok"

        @retrying(attempts=3, max_wait=0.01)
        def refused() -> None:
            calls["permanent"] += 1
            raise PermanentError("HTTP 401")

        assert flaky() == "ok"
        with pytest.raises(PermanentError):
            refused()
        assert calls == {"transient": 3, "permanent": 1}


def describe_keyring_secret() -> None:
    def it_registers_the_key_with_the_log_redaction(mocker: MockerFixture) -> None:
        mocker.patch("shutil.which", return_value="/usr/bin/secret-tool")
        mocker.patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="sm-key-0123456789\n"),
        )
        assert secrets.keyring_secret("supermemory", "wirecat") == "sm-key-0123456789"
        assert "sm-key-0123456789" not in scrub_secrets("key sm-key-0123456789")

    def it_names_the_missing_entry_without_a_value(mocker: MockerFixture) -> None:
        mocker.patch("shutil.which", return_value="/usr/bin/secret-tool")
        mocker.patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=1, stdout=""))
        with pytest.raises(PermanentError, match="service 'mem0' account 'wirecat'"):
            secrets.keyring_secret("mem0", "wirecat")

    def it_says_how_to_get_secret_tool(mocker: MockerFixture) -> None:
        mocker.patch("shutil.which", return_value=None)
        with pytest.raises(PermanentError, match="libsecret-tools"):
            secrets.keyring_secret("mem0", "wirecat")


def describe_console_logging() -> None:
    def it_prints_context_and_redacted_extras_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
        setup_logging("console", "INFO")
        with log_context(trial_id="q01"):
            logger.bind(**{"password": "hunter2-long", "payload": "{json}"}).info("asked <agent>")
        err = capsys.readouterr().err
        assert "trial_id=q01" in err
        assert "hunter2-long" not in err
        assert "{json}" in err
        assert "asked <agent>" in err

    def it_refuses_unknown_context() -> None:
        with pytest.raises(ValueError, match="unknown log context"), log_context(user="x"):
            pass
