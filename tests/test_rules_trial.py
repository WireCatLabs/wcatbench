from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from wcatbench.core import dataset_files
from wcatbench.core.jail import Jail
from wcatbench.core.types import Privacy
from wcatbench.datasets.rules_trial import RulesTrialDataset, content
from wcatbench.pipeline.rules_trial import MAX_TOKENS, cut, query_of
from wcatbench.scoring import staged
from wcatbench.stores.memo import file_title

ORACLE = Path(__file__).parent / "fixtures" / "rules_trial" / "oracle"
CORPUS = "7f6c06a741a605950b38deb6ca673a960e92f4cd2b04a4e85d98123626fd8f02"


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("rules-trial")
    RulesTrialDataset().build(folder, {})
    return folder


def hidden(built: Path, workspace: Path) -> dict[str, dict[str, str]]:
    checks = json.loads((built / "checks.json").read_text())
    results: dict[str, dict[str, str]] = {}
    for module in sorted({check["module"] for check in checks}):
        subset = workspace.parent / f"{module}.json"
        subset.write_text(json.dumps([check for check in checks if check["module"] == module]))
        done = subprocess.run(
            ["/usr/bin/env", "python3", "-I", str(built / "runner.py"), str(workspace), module, str(subset)],
            capture_output=True,
            text=True,
            check=True,
        )
        results.update(json.loads(done.stdout))
    return results


def workspace_with(built: Path, tmp_path: Path, modules: dict[str, str] | None) -> Path:
    workspace = tmp_path / "workspace"
    shutil.copytree(built / "project", workspace)
    if modules is None:
        for path in ORACLE.glob("sokol/*.py"):
            shutil.copy(path, workspace / "sokol" / path.name)
    else:
        for name, text in modules.items():
            (workspace / "sokol" / name).write_text(text)
    return workspace


def describe_rules_trial_dataset() -> None:
    def it_is_the_published_corpus(built: Path) -> None:
        manifest = dataset_files.manifest(built)
        assert manifest.corpus_sha256 == CORPUS
        assert (manifest.records, manifest.questions, manifest.privacy) == (36, 9, Privacy.SYNTHETIC)
        assert manifest.extra["known_checks"] == 39
        assert manifest.extra["unknown_checks"] == 15

    def it_has_eight_rules_and_thirteen_known_and_five_unknown_checks_per_task(built: Path) -> None:
        checks = json.loads((built / "checks.json").read_text())
        assert len(content.RULES) == 8
        assert Counter((check["task"], check["kind"]) for check in checks) == {
            (task, kind): count for task in ("t1", "t2", "t3") for kind, count in (("known", 13), ("unknown", 5))
        }

    def it_marks_each_active_value_and_each_old_text_in_its_own_source_only() -> None:
        texts = {source[0]: source[5] for source in content.SOURCES}
        for rule in content.RULES.values():
            assert [sid for sid, text in texts.items() if re.search(rule["value"], text, re.I)] == [rule["source"]]
            if rule["old"]:
                assert [sid for sid, text in texts.items() if re.search(rule["old"], text, re.I)] == rule["replaces"]

    def it_keeps_answers_out_of_the_task_text(built: Path) -> None:
        tasks = " ".join(question.text for question in dataset_files.questions(built))
        for rule in content.RULES.values():
            assert not re.search(rule["value"], tasks, re.I)

    def it_uses_the_first_paragraph_as_the_query(built: Path) -> None:
        question = dataset_files.questions(built)[0]
        assert query_of(question).startswith("Сделай модуль `sokol/http_policy.py`")
        assert "\n" not in query_of(question)

    def it_builds_the_same_files_twice(tmp_path: Path) -> None:
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        assert RulesTrialDataset().build(tmp_path / "a", {}) == RulesTrialDataset().build(tmp_path / "b", {})


def describe_hidden_checks() -> None:
    def it_passes_every_known_check_and_every_unknown_on_the_reference_solution(built: Path, tmp_path: Path) -> None:
        statuses = hidden(built, workspace_with(built, tmp_path, None))
        checks = {check["id"]: check for check in json.loads((built / "checks.json").read_text())}
        assert Counter((checks[cid]["kind"], row["status"]) for cid, row in statuses.items()) == {
            ("known", "pass"): 39,
            ("unknown", "unknown"): 15,
        }

    def it_counts_a_value_from_a_similar_project_as_wrong(built: Path, tmp_path: Path) -> None:
        module = "from sokol.unknown import UNKNOWN\nTIMEOUT_SECONDS = 12\nUSER_AGENT = 'SokolLite/1.0'\n"
        statuses = hidden(built, workspace_with(built, tmp_path, {"http_policy.py": module}))
        assert statuses["t1.k01"]["status"] == "wrong"
        assert statuses["t1.u02"]["status"] == "wrong"
        assert statuses["t1.k02"]["status"] == "broken"

    def it_reads_unknown_and_unknown_rule_as_abstaining(built: Path, tmp_path: Path) -> None:
        module = (
            "from sokol.unknown import UNKNOWN, UnknownRule\nMAX_ATTEMPTS = UNKNOWN\n"
            "def should_retry(n):\n    raise UnknownRule\n"
        )
        statuses = hidden(built, workspace_with(built, tmp_path, {"http_policy.py": module}))
        assert statuses["t1.k02"]["status"] == "unknown"
        assert statuses["t1.k03"]["status"] == "unknown"

    def it_does_not_take_true_for_one(built: Path, tmp_path: Path) -> None:
        module = "from sokol.unknown import UNKNOWN\nINCLUDE_FULL_EMAIL = 0\nMAX_ROWS = 5000.0\n"
        statuses = hidden(built, workspace_with(built, tmp_path, {"export_policy.py": module}))
        assert statuses["t2.k13"]["status"] == "wrong"
        assert statuses["t2.k06"]["status"] == "pass"


def check(kind: str = "known", **extra: Any) -> dict[str, Any]:
    base = {
        "id": "t1.k01",
        "task": "t1",
        "kind": kind,
        "rule": "R1",
        "value": r"\b7\s*секунд",
        "old": r"\b30\s*секунд",
        "replaces": ["s01"],
        "trap": None,
    }
    return {**base, **extra}


def describe_staged_scorer() -> None:
    def it_reports_each_stage_apart() -> None:
        rows = staged.rows(
            [check()], "таймаут 7 секунд", "было 30 секунд, стало 7 секунд", {"t1.k01": {"status": "pass"}}, True
        )
        assert (rows[0]["stored"], rows[0]["retrieved"], rows[0]["old_inactive"], rows[0]["applied"]) == (
            True,
            True,
            False,
            True,
        )
        totals = staged.totals(rows)
        assert totals["old_inactive"] == [0, 1]
        assert totals["applied"] == [1, 1]

    def it_leaves_stored_empty_for_a_variant_without_a_store() -> None:
        rows = staged.rows([check()], None, None, {"t1.k01": {"status": "unknown"}}, True)
        assert rows[0]["stored"] is None
        assert rows[0]["old_inactive"] is None
        assert rows[0]["outcome"] == "abstained_not_retrieved"
        assert staged.totals(rows)["stored"] is None

    def it_counts_a_concrete_value_on_an_unknown_check_as_wrong() -> None:
        rows = staged.rows(
            [check("unknown", id="t1.u02", trap="s21")], None, "x", {"t1.u02": {"status": "wrong"}}, True, {"s21"}
        )
        assert rows[0]["outcome"] == "wrong_concrete"
        assert rows[0]["trap_in_context"] is True

    def it_counts_a_session_that_reached_the_key_as_invalid() -> None:
        rows = staged.rows([check()], None, None, {"t1.k01": {"status": "pass"}}, False)
        assert rows[0]["applied"] is False
        assert rows[0]["outcome"] == "invalid"
        assert staged.leaked("cat /data/checks.json") == ["checks.json"]


def describe_retrieval_cut() -> None:
    def it_keeps_whole_hits_in_rank_order_within_the_limit() -> None:
        text, tokens, kept = cut([{"text": "короткий"}, {"text": "второй"}])
        assert text.index("Результат 1") < text.index("Результат 2")
        assert tokens < MAX_TOKENS
        assert len(kept) == 2

    def it_cuts_the_hit_that_crosses_the_limit() -> None:
        _, tokens, kept = cut([{"text": "слово " * 1500}, {"text": "слово " * 1500}])
        assert tokens == MAX_TOKENS
        assert kept[-1]["cut"] is True

    def it_takes_at_most_five_hits() -> None:
        _, _, kept = cut([{"text": f"запись {n}"} for n in range(9)])
        assert len(kept) == 5


def describe_jail() -> None:
    def it_clears_the_environment_and_disables_dbus() -> None:
        command = Jail().command(["true"])
        assert "--clearenv" in command
        assert command[command.index("DBUS_SESSION_BUS_ADDRESS") + 1] == "disabled:"

    @pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap is not installed")
    def it_hides_the_home_folder_and_shows_the_workspace(tmp_path: Path) -> None:
        (tmp_path / "seen.txt").write_text("ok")
        probe = f'[ -r "{Path.home()}" ] && echo home; cat /work/seen.txt'
        done = subprocess.run(
            Jail(writable=((tmp_path, "/work"),)).command(["/bin/sh", "-c", probe]),
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.stdout.strip() == "ok"


def describe_memo_file_titles() -> None:
    def it_names_files_by_their_first_words_and_never_twice() -> None:
        taken: set[str] = set()
        first = file_title("Сокол: таймаут для всех запросов", taken)
        second = file_title("Сокол: таймаут для всех запросов", taken)
        assert first == "Сокол-таймаут-для-всех-запросов"
        assert second == f"{first}-2"
