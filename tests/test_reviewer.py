"""SPEC §13.2 Phase 3 reviewer：V-01 ~ V-06。subprocess 全部 mock。"""
import json
import threading
from types import SimpleNamespace

import pytest

from agents import reviewer, runner
from conftest import ok_review


@pytest.fixture
def fake_claude(monkeypatch):
    """依 stdin 內容中的 id 決定回應；回傳呼叫紀錄。responder(item_id, attempt) -> stdout 或 Exception。"""
    monkeypatch.setattr(runner.shutil, "which", lambda c: c)
    calls, lock, attempts = [], threading.Lock(), {}

    def install(responder):
        def run(argv, **kw):
            item = json.loads(kw["input"][kw["input"].index("{\n"):])
            with lock:
                calls.append((argv, kw["input"]))
                attempts[item["id"]] = attempts.get(item["id"], 0) + 1
                n = attempts[item["id"]]
            out = responder(item["id"], n)
            if isinstance(out, Exception):
                raise out
            return SimpleNamespace(stdout=out, stderr="", returncode=0)
        monkeypatch.setattr(runner.subprocess, "run", run)
        return calls
    return install


def test_v01_one_call_per_item_via_stdin(cfg, make_draft, fake_claude):
    d = make_draft()
    calls = fake_claude(lambda item_id, n: json.dumps(ok_review(item_id)))
    out = reviewer.review_items(cfg, d, "2026-10-18", "2026-10-25")
    assert len(calls) == 4 and [r["id"] for r in out["items"]] == ["L1", "L2", "L3", "I1"]
    argv, prompt = calls[0]
    assert "--model" in argv and "WebFetch WebSearch" in argv
    assert "2026-10-18" in prompt and '"id": "' in prompt and "標題" in prompt
    assert out["errors"] == {}


def test_v02_single_item_failure_recorded(cfg, make_draft, fake_claude):
    d = make_draft()
    calls = fake_claude(lambda item_id, n: "不是 JSON" if item_id == "L2" else json.dumps(ok_review(item_id)))
    out = reviewer.review_items(cfg, d, "2026-10-18", "2026-10-25")
    assert [r["id"] for r in out["items"]] == ["L1", "L3", "I1"]
    assert "L2" in out["errors"]
    assert sum('"id": "L2"' in c[1] for c in calls) == 2  # 重試 1 次


def test_v03_all_items_failing_raises(cfg, make_draft, fake_claude):
    fake_claude(lambda item_id, n: "")
    with pytest.raises(runner.AgentError, match="全部則查核失敗"):
        reviewer.review_items(cfg, make_draft(), "2026-10-18", "2026-10-25")


def test_v04_permission_denied_raises(cfg, make_draft, fake_claude):
    fake_claude(lambda item_id, n: "tool was auto-denied")
    with pytest.raises(runner.AgentPermissionError):
        reviewer.review_items(cfg, make_draft(), "2026-10-18", "2026-10-25")


def test_v07_quota_exhausted_aborts_without_retry(cfg, make_draft, fake_claude):
    calls = fake_claude(lambda item_id, n: "You've hit your session limit · resets 7:50am (Asia/Taipei)")
    with pytest.raises(runner.AgentQuotaError, match="用量"):
        reviewer.review_items(cfg, make_draft(1, 0), "2026-10-18", "2026-10-25")
    assert len(calls) == 1


def test_parse_failure_message_includes_output_head(cfg, make_draft, fake_claude):
    fake_claude(lambda item_id, n: "抱歉，我無法完成")
    with pytest.raises(runner.AgentError, match="抱歉"):
        reviewer.review_items(cfg, make_draft(1, 0), "2026-10-18", "2026-10-25")


def test_v05_id_taken_from_call_not_model(cfg, make_draft, fake_claude):
    fake_claude(lambda item_id, n: json.dumps(ok_review("WRONG")))
    out = reviewer.review_items(cfg, make_draft(1, 0), "2026-10-18", "2026-10-25")
    assert out["items"][0]["id"] == "L1"


def test_missing_core_is_invalid_output(cfg, make_draft, fake_claude):
    fake_claude(lambda item_id, n: json.dumps({"id": item_id, "fields": []}))
    with pytest.raises(runner.AgentError):
        reviewer.review_items(cfg, make_draft(1, 0), "2026-10-18", "2026-10-25")


def test_v08_write_top3(cfg, make_draft, monkeypatch):
    d = make_draft()
    monkeypatch.setattr(runner.shutil, "which", lambda c: c)
    seen = {}
    reply = {"top3": [{"text": " 焦點A ", "related_ids": ["L1", "X9"]},   # X9 不在入選項目 → 去掉
                      {"text": "焦點B", "related_ids": ["X9"]},           # 沒有有效引用 → 捨棄
                      {"text": "", "related_ids": ["L2"]},                # 空文字 → 捨棄
                      {"text": "焦點D", "related_ids": ["I1"]},
                      {"text": "第四點", "related_ids": ["L3"]}]}          # 只取前 3 點

    def run(argv, **kw):
        seen.update(argv=argv, input=kw["input"])
        return SimpleNamespace(stdout=json.dumps(reply, ensure_ascii=False), stderr="", returncode=0)
    monkeypatch.setattr(runner.subprocess, "run", run)
    assert reviewer.write_top3(cfg, d["items"]) == [{"text": "焦點A", "related_ids": ["L1"]}]
    assert "--allowedTools" not in seen["argv"] and "細節1a" in seen["input"]

    monkeypatch.setattr(runner.subprocess, "run", lambda argv, **kw: SimpleNamespace(stdout="", stderr="", returncode=0))
    assert reviewer.write_top3(cfg, d["items"]) == []
    assert reviewer.write_top3(cfg, []) == []


def test_v06_check_top3(cfg, make_draft, monkeypatch):
    d = make_draft()
    monkeypatch.setattr(runner.shutil, "which", lambda c: c)
    seen = {}

    def run(argv, **kw):
        seen.update(argv=argv, input=kw["input"])
        return SimpleNamespace(stdout='{"top3":[{"index":0,"verdict":"pass","reason":""}]}', stderr="", returncode=0)
    monkeypatch.setattr(runner.subprocess, "run", run)
    out = reviewer.check_top3(cfg, d["top3"], d["items"])
    assert out == [{"index": 0, "verdict": "pass", "reason": ""}]
    assert "--allowedTools" not in seen["argv"] and "細節1a" in seen["input"]

    monkeypatch.setattr(runner.subprocess, "run", lambda argv, **kw: SimpleNamespace(stdout="", stderr="", returncode=0))
    assert reviewer.check_top3(cfg, d["top3"], d["items"]) is None
    assert reviewer.check_top3(cfg, [], d["items"]) == []
