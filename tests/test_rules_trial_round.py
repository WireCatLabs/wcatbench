from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from wcatbench.agents import hermes
from wcatbench.agents.hermes import HermesAgent, SessionResult
from wcatbench.core.types import Outcome, Record, Usage
from wcatbench.datasets.rules_trial import RulesTrialDataset
from wcatbench.pipeline import rules_trial
from wcatbench.pipeline.rules_trial import Round
from wcatbench.stores import agentmemory, hindsight_slim, mem0_oss, memo, openviking

ORACLE = Path(__file__).parent / "fixtures" / "rules_trial" / "oracle"
STARTED = datetime(2026, 11, 27, tzinfo=UTC)


def record(n: int, text: str = "Сокол: таймаут 7 секунд") -> Record:
    return Record(id=f"s{n:02}", kind="decision", timestamp="2026-03-02T10:00:00+00:00", text=text, name=f"r{n}")


class Done(subprocess.CompletedProcess[str]):
    def __init__(self, stdout: Any = "", code: int = 0, stderr: str = "") -> None:
        text = stdout if isinstance(stdout, str) else json.dumps(stdout, ensure_ascii=False)
        super().__init__([], code, text, stderr)


class NoJail:
    """The hidden checks run the same runner, without bubblewrap, so the round runs where bwrap is missing."""

    def __init__(self, **_: Any) -> None:
        pass

    def command(self, argv: list[str]) -> list[str]:
        return argv


class OracleAgent:
    """Writes the reference solution, or a module that answers UNKNOWN to everything, and may read the key."""

    def __init__(self, solve: bool = True, peek: bool = False) -> None:
        self.solve, self.peek, self.prompts = solve, peek, list[str]()

    def session(self, prompt: str, workspace: Path, trial: Path) -> SessionResult:
        self.prompts.append(prompt)
        for path in ORACLE.glob("sokol/*.py"):
            text = path.read_text() if self.solve else "from sokol.unknown import UNKNOWN\n"
            (workspace / "sokol" / path.name).write_text(text)
        transcript = "cat /data/checks.json" if self.peek else "read memory/context.md"
        return SessionResult(Outcome.COMPLETED, 1.0, Usage(), "done", "", transcript)

    def jail(self, workspace: Path, out: Path) -> NoJail:
        return NoJail()


@pytest.fixture
def dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("dataset")
    RulesTrialDataset().build(folder, {})
    return folder


@pytest.fixture(autouse=True)
def no_bwrap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rules_trial, "Jail", NoJail)


def describe_round() -> None:
    def it_scores_a_full_store_variant_stage_by_stage(dataset: Path, tmp_path: Path) -> None:
        trial = Round(dataset, tmp_path / "run", tmp_path / "builds", OracleAgent())
        trial.go("files-top5", "his")
        report = trial.report("files-top5")
        assert (report["sessions"], report["applied"], report["unknown"]) == (6, [78, 78], [30, 30])
        assert report["stored"] == [78, 78]
        assert report["retrieved"][0] < 78
        status = (tmp_path / "run" / "status.csv").read_text().splitlines()
        assert status[0] == "id,status,detail,time"
        assert len(status) == 7

    def it_gives_the_file_variants_the_whole_file_and_resumes_without_a_new_session(
        dataset: Path, tmp_path: Path
    ) -> None:
        agent = OracleAgent()
        trial = Round(dataset, tmp_path / "run", tmp_path / "builds", agent)
        trial.go("files-his")
        trial.go("files-his")
        assert len(agent.prompts) == 6
        assert "memory/context.md" in agent.prompts[0]
        assert trial.report("files-his")["old_inactive"] == [48, 48]

    def it_puts_one_file_per_record_into_the_archive_variant(dataset: Path, tmp_path: Path) -> None:
        trial = Round(dataset, tmp_path / "run", tmp_path / "builds", OracleAgent(solve=False))
        result = trial.session("archive-in-workspace", "t1.p0", 1)
        workspace = tmp_path / "run" / "trials" / "archive-in-workspace" / "t1.p0.a1" / "workspace"
        assert len(list((workspace / "archive").glob("*.md"))) == 36
        assert len(result["rows"]) == 18

    def it_counts_every_check_of_a_session_that_read_the_key_as_invalid(dataset: Path, tmp_path: Path) -> None:
        trial = Round(dataset, tmp_path / "run", tmp_path / "builds", OracleAgent(peek=True))
        result = trial.session("none", "t1.p0", 1)
        assert result["leaks"] == ["checks.json"]
        assert {row["outcome"] for row in result["rows"]} == {"invalid"}

    def it_writes_one_table_row_per_variant_that_ran(dataset: Path, tmp_path: Path) -> None:
        trial = Round(dataset, tmp_path / "run", tmp_path / "builds", OracleAgent(solve=False))
        trial.go("none")
        table, rows = trial.summary("his")
        assert table.count("\n| none |") == 1
        assert "| none | 6/6 | n/a | n/a | n/a | 0/78 |" in table
        assert len(rows) == 108

    def it_runs_the_probe_in_the_agents_jail(dataset: Path, tmp_path: Path) -> None:
        trial = Round(dataset, tmp_path / "run", tmp_path / "builds", OracleAgent())
        probe = trial.probe()
        assert any(line.startswith("readable ") for line in probe["output"])
        assert (tmp_path / "run" / "probe" / "probe.json").exists()

    def it_plans_two_applications_of_one_phrasing_or_one_of_each_other(dataset: Path, tmp_path: Path) -> None:
        trial = Round(dataset, tmp_path / "run", tmp_path / "builds", OracleAgent())
        assert trial.plan("none", "his")[:2] == [("t1.p0", 1), ("t1.p0", 2)]
        assert len(trial.plan("none", "ours")) == 6
        assert len(trial.plan("none", "all")) == 12


@pytest.fixture
def home(tmp_path: Path) -> Path:
    folder = tmp_path / "hermes-home"
    folder.mkdir()
    (folder / "auth.json").write_text("{}")
    return folder


def describe_hermes_agent() -> None:
    def it_refuses_to_start_without_a_sign_in(tmp_path: Path) -> None:
        (tmp_path / "home").mkdir()
        with pytest.raises(Exception, match="no sign-in"):
            HermesAgent("gpt-5.6-terra", home=tmp_path / "home").prepare()

    def it_refuses_a_home_with_files_left_by_a_session(home: Path) -> None:
        (home / "state.db").write_text("")
        with pytest.raises(Exception, match=r"earlier session: state\.db"):
            HermesAgent("gpt-5.6-terra", home=home).prepare()

    def it_runs_one_session_and_moves_its_history_out_of_the_home(
        home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def run(argv: list[str], **_: Any) -> Done:
            assert argv[0].endswith("bwrap")
            assert argv[argv.index("-m") + 1] == "gpt-5.6-terra"
            (tmp_path / "trial" / "out" / "usage.json").write_text(
                json.dumps({"input_tokens": 900, "output_tokens": 40})
            )
            db = sqlite3.connect(home / "state.db")
            db.execute("CREATE TABLE messages (content TEXT, tool_calls TEXT)")
            db.execute("INSERT INTO messages VALUES ('готово', 'read_file TASK.md')")
            db.commit()
            db.close()
            (home / "sessions").mkdir()
            (home / "sessions" / "one.json").write_text('{"cmd": "ls /work"}')
            return Done("готово")

        monkeypatch.setattr(hermes.shutil, "which", lambda _: "/usr/bin/bwrap")
        monkeypatch.setattr(hermes.subprocess, "run", run)
        reply = HermesAgent("gpt-5.6-terra", home=home).session("задача", tmp_path / "work", tmp_path / "trial")
        assert reply.outcome is Outcome.COMPLETED
        assert (reply.usage.input_tokens, reply.usage.source) == (900, "agent-files")
        assert "read_file TASK.md" in reply.transcript
        assert "ls /work" in reply.transcript
        assert sorted(path.name for path in home.iterdir()) == ["auth.json", "config.yaml"]

    def it_reports_a_session_that_ran_out_of_time(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def run(argv: list[str], **_: Any) -> Done:
            raise subprocess.TimeoutExpired(argv, 5, output=b"half")

        monkeypatch.setattr(hermes.shutil, "which", lambda _: "/usr/bin/bwrap")
        monkeypatch.setattr(hermes.subprocess, "run", run)
        reply = HermesAgent("m", timeout=5, home=home).session("задача", tmp_path / "work", tmp_path / "trial")
        assert (reply.outcome, reply.stdout, reply.usage.source) == (Outcome.TIMEOUT, "half", "none")

    def it_binds_the_workspace_and_hides_the_owners_codex_sign_in(home: Path, tmp_path: Path) -> None:
        jail = HermesAgent("m", home=home).jail(tmp_path / "w", tmp_path / "o")
        assert (tmp_path / "w", "/work") in jail.writable
        assert jail.env["CODEX_HOME"] == "/tmp/codex-empty"  # noqa: S108


class FakeCli:
    """Answers subprocess.run by the first words of the command, and keeps every request."""

    def __init__(self, replies: dict[str, Any]) -> None:
        self.replies, self.calls = replies, list[list[str]]()

    def __call__(self, argv: list[str], **kwargs: Any) -> Done:
        self.calls.append([*argv, kwargs.get("input") or ""])
        words = " ".join(argv[1:3]) if "--json" in argv else json.loads(kwargs.get("input") or "{}").get("op", "")
        reply = self.replies[next(key for key in self.replies if words.startswith(key))]
        return reply(argv, kwargs) if callable(reply) else Done(reply)


def describe_memo_store() -> None:
    def it_writes_notes_embeds_them_and_maps_hits_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        left = iter([3, 0])
        cli = FakeCli(
            {
                "models download": {},
                "models set": {},
                "folders add": {"item": {"id": 1}},
                "sync": lambda *_: Done({"item": {"notes": {"left": next(left)}}}),
                "search all": {
                    "items": [
                        {
                            "title": "Сокол-таймаут-7-секунд",
                            "excerpt": "таймаут 7",
                            "timestamp": "2026-03-02T10:00:00Z",
                        },
                        {"title": "чужое"},
                    ]
                },
            }
        )
        monkeypatch.setattr(memo.subprocess, "run", cli)
        store = memo.MemoStore(binary="memo")
        store.open("rules-trial", tmp_path, STARTED)
        store.ingest([record(1, "2026-03-02 · Ирина Козлова\nСокол: таймаут 7 секунд")])
        hits = store.search("таймаут", 5)
        assert hits[0].keys == ("r1",)
        assert hits[0].text == "2026-03-02 · Ирина Козлова\nСокол: таймаут 7 секунд"
        assert hits[1].keys == ()
        assert store.held() == {"r1": memo.ItemState.DONE}
        assert (tmp_path / "rules-trial" / "data" / "Сокол-таймаут-7-секунд.md").exists()

    def it_names_the_failed_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(memo.subprocess, "run", lambda *_, **__: Done("", 2, "no model"))
        store = memo.MemoStore(binary="memo")
        store.open("rules-trial", tmp_path, STARTED)
        with pytest.raises(Exception, match="memo search all exited 2: no model"):
            store.search("x", 5)


@pytest.fixture(autouse=True)
def no_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    for module in (mem0_oss, openviking, agentmemory, hindsight_slim):
        monkeypatch.setattr(module, "keyring_secret", lambda *_: "sk-test")


def describe_mem0_oss_store() -> None:
    def it_keeps_what_mem0_accepted_and_maps_memories_to_records(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cli = FakeCli(
            {
                "add": [{"key": "r1", "events": 1}],
                "all": [{"memory": "таймаут 7 секунд"}],
                "search": [{"memory": "таймаут 7 секунд", "metadata": {"key": "r1"}, "score": 0.8}, {"memory": "x"}],
            }
        )
        monkeypatch.setattr(mem0_oss.subprocess, "run", cli)
        store = mem0_oss.Mem0OssStore(python=Path("/venv/python"))
        store.open("rules-trial", tmp_path, STARTED)
        store.ingest([record(1)])
        assert store.held() == {"r1": mem0_oss.ItemState.DONE}
        assert store.contents() == ["таймаут 7 секунд"]
        assert [hit.keys for hit in store.search("таймаут", 5)] == [("r1",), ()]
        assert json.loads(cli.calls[0][-1])["user_id"] == "rules_trial"

    def it_stops_when_the_worker_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mem0_oss.subprocess, "run", lambda *_, **__: Done("", 1, "LLM extraction failed"))
        store = mem0_oss.Mem0OssStore()
        store.open("rules-trial", tmp_path, STARTED)
        with pytest.raises(Exception, match="mem0 worker all exited 1"):
            store.contents()


class Server:
    def __init__(self, pid: int = 4242) -> None:
        self.pid, self.args = pid, list[list[str]]()

    def __call__(self, argv: list[str], **_: Any) -> Server:
        self.args.append(argv)
        return self

    def poll(self) -> int | None:
        return 0


def describe_openviking_store() -> None:
    def it_adds_the_records_as_one_folder_and_reads_hits_from_their_files(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        up = iter([False, True, True])
        monkeypatch.setattr(openviking.OpenVikingStore, "live", lambda _: next(up))
        server = Server()
        monkeypatch.setattr(openviking.subprocess, "Popen", server)
        monkeypatch.setattr(openviking.time, "sleep", lambda _: None)
        cli = FakeCli(
            {
                "add": {"root_uri": "viking://resources/rules-trial"},
                "find": {
                    "resources": [{"uri": "viking://resources/rules-trial/2026-03-02-r1.md", "score": 0.5}],
                    "memories": [{"uri": "viking://user/memories/x", "abstract": "про таймаут", "score": 0.9}],
                },
                "read": {"text": "таймаут 7 секунд"},
                "ls": [{"uri": "viking://resources/rules-trial/2026-03-02-r1.md"}, {"uri": "viking://resources/x/"}],
            }
        )
        monkeypatch.setattr(openviking.subprocess, "run", cli)
        store = openviking.OpenVikingEvolutionStore()
        store.open("rules-trial", tmp_path, STARTED)
        conf = json.loads((tmp_path / "rules-trial" / "ov.conf").read_text())
        assert conf["server"]["agent_evolution"]["enabled"] is True
        assert oct((tmp_path / "rules-trial" / "ov.conf").stat().st_mode)[-3:] == "600"
        store.ingest([record(1)])
        assert store.held() == {"r1": openviking.ItemState.DONE}
        hits = store.search("таймаут", 5)
        assert [(hit.keys, hit.text) for hit in hits] == [((), "про таймаут"), (("r1",), "таймаут 7 секунд")]
        assert store.contents() == ["таймаут 7 секунд"]
        assert "agent evolution True" in store.version()
        store.close()

    def it_refuses_to_start_beside_a_running_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(openviking.OpenVikingStore, "live", lambda _: True)
        with pytest.raises(Exception, match="already answers on port 1933"):
            openviking.OpenVikingStore().open("rules-trial", tmp_path, STARTED)


def describe_agentmemory_store() -> None:
    def it_remembers_each_record_once_and_takes_hit_text_from_memories(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        memories = [
            {"id": "m1", "content": "таймаут 7 секунд"},
            {"id": "m0", "content": "30 секунд", "isLatest": False},
        ]

        def answer(request: httpx.Request) -> httpx.Response:
            assert request.headers["Authorization"] == "Bearer s3cret"
            if request.url.path.endswith("/remember"):
                return httpx.Response(200, json={"memory": {"id": "m1"}})
            if request.url.path.endswith("/memories"):
                return httpx.Response(200, json={"memories": memories})
            return httpx.Response(200, json={"results": [{"obsId": "m1", "score": 1.0}, {"obsId": "zz", "title": "t"}]})

        real_client = httpx.Client
        monkeypatch.setattr(
            agentmemory.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(answer), **kw)
        )
        up = iter([False, True])
        monkeypatch.setattr(agentmemory.AgentMemoryStore, "live", lambda _: next(up))
        monkeypatch.setattr(agentmemory.subprocess, "Popen", Server())
        store = agentmemory.AgentMemoryStore()
        store.open("rules-trial", tmp_path, STARTED)
        (tmp_path / "rules-trial" / "home" / ".agentmemory").mkdir()
        (tmp_path / "rules-trial" / "home" / ".agentmemory" / "secret").write_text("s3cret\n")
        assert store.ingest([record(1), record(1)]).sent == ("r1",)
        assert store.held() == {"r1": agentmemory.ItemState.DONE}
        assert store.contents() == ["таймаут 7 секунд"]
        assert [(hit.keys, hit.text) for hit in store.search("таймаут", 5)] == [
            (("r1",), "таймаут 7 секунд"),
            ((), "t"),
        ]
        store.close()


def describe_hindsight_slim_store() -> None:
    def it_starts_its_container_with_the_key_in_a_removed_env_file(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[list[str]] = []

        def docker(*args: str, check: bool = True) -> Done:
            seen.append(list(args))
            if args[0] == "run":
                env_file = Path(args[args.index("--env-file") + 1])
                assert oct(env_file.stat().st_mode)[-3:] == "600"
                assert "HINDSIGHT_API_RERANKER_PROVIDER=rrf" in env_file.read_text()
            return Done("")

        monkeypatch.setattr(hindsight_slim, "docker", docker)
        monkeypatch.setattr(hindsight_slim.httpx, "get", lambda *_, **__: httpx.Response(200))
        store = hindsight_slim.HindsightSlimStore()
        store.start(tmp_path)
        assert [args[0] for args in seen] == ["ps", "ps", "run"]
        assert not (tmp_path / "hindsight.env").exists()
        assert all("sk-test" not in " ".join(args) for args in seen)

    def it_reads_every_page_of_memories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        pages = iter([{"items": [{"text": "a"}], "total": 2}, {"items": [{"text": "b"}], "total": 2}])
        store = hindsight_slim.HindsightSlimStore()
        store._api = type("Api", (), {"request": lambda *_: next(pages)})()  # type: ignore[assignment]
        assert store.contents() == ["a", "b"]


def test_the_oracle_fixture_is_complete() -> None:
    assert sorted(path.name for path in ORACLE.glob("sokol/*.py")) == [
        "export_policy.py",
        "http_policy.py",
        "notify_policy.py",
    ]
    assert shutil.which("python3")
