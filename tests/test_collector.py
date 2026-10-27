"""C-01 ~ C-05：subprocess 全部 mock，不呼叫真實 agy。"""
import json
import subprocess
from types import SimpleNamespace

import pytest

from agents import collector, runner


def proc(stdout="", stderr="", code=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=code)


@pytest.fixture
def fake_run(monkeypatch):
    monkeypatch.setattr(runner.shutil, "which", lambda c: c)
    calls = []

    def install(*results):
        seq = iter(results)

        def run(*a, **k):
            calls.append(a)
            r = next(seq)
            if isinstance(r, Exception):
                raise r
            return r
        monkeypatch.setattr(runner.subprocess, "run", run)
        return calls
    return install


def test_c01_ok(cfg, make_draft, fake_run):
    draft = make_draft()
    fake_run(proc(json.dumps(draft)))
    assert collector.collect(cfg, "2026-10-18", "2026-10-25") == draft


def test_c02_empty_stdout_retries_once_then_fails(cfg, fake_run):
    calls = fake_run(proc(""), proc(""))
    with pytest.raises(runner.AgentError, match="為空"):
        collector.collect(cfg, "2026-10-18", "2026-10-25")
    assert len(calls) == 2


def test_c03_permission_denied_no_retry(cfg, fake_run):
    calls = fake_run(proc("", "tool was auto-denied"), proc(""))
    with pytest.raises(runner.AgentPermissionError):
        collector.collect(cfg, "2026-10-18", "2026-10-25")
    assert len(calls) == 1


def test_c04_timeout(cfg, fake_run):
    fake_run(subprocess.TimeoutExpired("agy", 1))
    with pytest.raises(runner.AgentError, match="逾時"):
        collector.collect(cfg, "2026-10-18", "2026-10-25")


def test_c05_bad_json_then_ok(cfg, make_draft, fake_run):
    draft = make_draft()
    fake_run(proc("抱歉我辦不到"), proc("```json\n" + json.dumps(draft) + "\n```"))
    assert collector.collect(cfg, "2026-10-18", "2026-10-25") == draft


def test_invalid_structure_counts_as_bad_output(cfg, make_draft, fake_run):
    bad = make_draft()
    bad["items"][0].pop("summary")
    fake_run(proc(json.dumps(bad)), proc(json.dumps(make_draft())))
    assert collector.collect(cfg, "2026-10-18", "2026-10-25")["items"]


# ---------- 結構化輸出（C-06 ~ C-08，SPEC §8.4）----------

def envelope(draft=None, status="SUCCESS"):
    env = {"conversation_id": "x", "status": status, "response": "...", "usage": {"total_tokens": 123}}
    if draft is not None:
        env["structured_output"] = draft
    return json.dumps(env, ensure_ascii=False)


def test_c06_structured_output_used(cfg, make_draft, fake_run):
    draft = make_draft()
    fake_run(proc(envelope(draft)))
    assert collector.collect(cfg, "2026-10-18", "2026-10-25") == draft


def test_c07_bad_status_or_missing_structured_output_retried(cfg, make_draft, fake_run):
    draft = make_draft()
    calls = fake_run(proc(envelope(draft, status="ERROR")), proc(envelope(None)))
    with pytest.raises(runner.AgentError):
        collector.collect(cfg, "2026-10-18", "2026-10-25")
    assert len(calls) == 2


def test_c08_args_include_schema_and_model(cfg):
    args = collector.build_args(cfg["agents"]["collector"], "PROMPT")
    assert args[:2] == ["-p", "PROMPT"]
    assert args[args.index("--output-format") + 1] == "json"
    assert args[args.index("--json-schema") + 1].endswith("draft.schema.json")
    assert args[args.index("--model") + 1] == cfg["agents"]["collector"]["model"]
    assert "--effort" not in args
    assert "--effort" in collector.build_args({**cfg["agents"]["collector"], "effort": "high"}, "P")
    assert collector.build_args({"command": "agy"}, "P") == ["-p", "P"]


def test_schema_file_is_valid_json_and_matches_validator(make_draft):
    from pathlib import Path
    schema = json.loads((Path(collector.ROOT) / "prompts" / "draft.schema.json").read_text(encoding="utf-8"))
    required = schema["properties"]["items"]["items"]["required"]
    assert {"id", "section", "title", "summary", "key_points", "heat", "sources"} <= set(required)
