"""E-01 ~ E-04：兩個 Agent 與寄信全部 mock，在 tmp_path 內執行。"""
import copy
import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest

import orchestrator
from agents.runner import AgentError

ROOT = Path(__file__).resolve().parents[1]


def _with_heat(draft, score):
    d = copy.deepcopy(draft)
    for i in d["items"]:
        i["heat_metrics"] = [{"kind": "media", "ok": None, "score": score, "peak": 0}]
    return d


@pytest.fixture
def env(tmp_path, monkeypatch, make_draft, pass_review):
    shutil.copy(ROOT / "config.yaml", tmp_path / "config.yaml")
    sent = []
    monkeypatch.setattr(orchestrator.mailer, "send_mail", lambda c, subject, html, *a, **k: sent.append((subject, html)))
    draft = make_draft()
    monkeypatch.setattr(orchestrator.heat, "fetch_heat", lambda d, cfg, **k: _with_heat(d, 1.5))  # 不連網
    monkeypatch.setattr(orchestrator.url_resolver, "check_sources", lambda d, cfg, rd: (d, []))  # 不連網
    monkeypatch.setattr(orchestrator.collector, "collect", lambda *a: draft)
    monkeypatch.setattr(orchestrator.reviewer, "review_items", lambda cfg, d, s, e: pass_review(d))
    monkeypatch.setattr(orchestrator.reviewer, "write_top3",
                        lambda cfg, items: [{"text": "重寫焦點", "related_ids": [items[0]["id"]]}] if items else [])
    monkeypatch.setattr(orchestrator.reviewer, "check_top3",
                        lambda cfg, top3, items: [{"index": n, "verdict": "pass"} for n, _ in enumerate(top3)])
    return SimpleEnv(tmp_path, sent, draft, monkeypatch, pass_review)


class SimpleEnv:
    def __init__(self, base, sent, draft, mp, pass_review):
        self.base, self.sent, self.draft, self.mp, self.pass_review = base, sent, draft, mp, pass_review

    def run(self):
        return orchestrator.main(self.base, datetime(2026, 10, 25, 9, 30))

    @property
    def run_dir(self):
        return self.base / "runs" / "2026-10-25_0930"


def boom(*a, **k):
    raise AgentError("模擬失敗")


def test_e01_success(env):
    assert env.run() == 0
    assert "週報" in env.sent[0][0] and "[失敗]" not in env.sent[0][0]
    for f in ("draft.json", "draft_resolved.json", "review.json", "decisions.json", "newsletter.html", "run.log",
              "summary.json"):
        assert (env.run_dir / f).exists(), f
    assert json.loads((env.run_dir / "summary.json").read_text(encoding="utf-8"))["status"] == "ok"


def test_e02_collect_failure(env):
    env.mp.setattr(orchestrator.collector, "collect", boom)
    assert env.run() == 1
    assert len(env.sent) == 1 and env.sent[0][0].startswith("[失敗]") and "collect" in env.sent[0][1]


def test_e03_review_failure_sends_no_draft(env):
    env.mp.setattr(orchestrator.reviewer, "review_items", boom)
    assert env.run() == 1
    assert [s[0].startswith("[失敗]") for s in env.sent] == [True]
    assert "標題1" not in env.sent[0][1]


def test_quota_exhausted_sends_failure_not_insufficient(env):
    from agents.runner import AgentQuotaError

    def quota(*a, **k):
        raise AgentQuotaError("claude 訂閱用量已耗盡")
    env.mp.setattr(orchestrator.reviewer, "review_items", quota)
    assert env.run() == 1
    assert [s[0][:4] for s in env.sent] == ["[失敗]"] and "用量" in env.sent[0][1]


def test_e04_fake_news_removed(env):
    def review(cfg, d, s, e):
        r = env.pass_review(d)
        r["items"][1]["core"]["event_supported"] = False
        r["items"][1]["issues"] = ["編造數字"]
        return r
    env.mp.setattr(orchestrator.reviewer, "review_items", review)
    assert env.run() == 0
    assert "標題2" not in env.sent[0][1]
    rec = json.loads((env.base / "failures.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["id"] == "L2" and rec["stage"] == "review"


def test_mail_to_env_overrides_config(tmp_path, monkeypatch):
    from config import load_config
    shutil.copy(ROOT / "config.yaml", tmp_path / "config.yaml")
    monkeypatch.setenv("MAIL_TO", "me@example.org")
    assert load_config(tmp_path / "config.yaml")["mail"]["to"] == "me@example.org"


def test_mail_failure_exit_code(env):
    def bad(*a, **k):
        raise orchestrator.mailer.MailError("x")
    env.mp.setattr(orchestrator.mailer, "send_mail", bad)
    assert env.run() == 1


def test_same_day_reruns_do_not_overwrite(env):
    env.run()
    orchestrator.main(env.base, datetime(2026, 10, 25, 14, 5))
    assert (env.base / "runs" / "2026-10-25_0930" / "draft.json").exists()
    assert (env.base / "runs" / "2026-10-25_1405" / "draft.json").exists()


def test_failure_records_have_run_at(env):
    env.mp.setattr(orchestrator.reviewer, "review_items", lambda cfg, d, s, e: {"items": [], "errors": {}})
    env.run()
    rec = json.loads((env.base / "failures.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["run_at"].startswith(datetime.now().strftime("%Y-%m-%d"))


# ---------- 品質不足、重播、不寄信（E-05 ~ E-07）----------

def _all_low_heat(env):
    env.mp.setattr(orchestrator.heat, "fetch_heat", lambda d, cfg, **k: _with_heat(d, 0.5))


def test_e05_insufficient_sends_notice_not_newsletter(env):
    _all_low_heat(env)
    assert env.run() == 1
    assert len(env.sent) == 1 and env.sent[0][0].startswith("[品質不足]")
    assert (env.run_dir / "newsletter.html").exists()
    assert json.loads((env.run_dir / "summary.json").read_text(encoding="utf-8"))["status"] == "insufficient"


def test_e05_send_with_warning_mode(env):
    _all_low_heat(env)
    cfg_path = env.base / "config.yaml"
    cfg_path.write_text(cfg_path.read_text(encoding="utf-8")
                        .replace("on_insufficient: notify", "on_insufficient: send_with_warning")
                        .replace("onprem: 1.0", "onprem: 0"), encoding="utf-8")
    assert env.run() == 0
    assert "週報" in env.sent[0][0] and "[品質不足]" not in env.sent[0][0]


def test_e06_from_run_skips_collect_and_uses_saved_draft(env):
    src = env.base / "runs" / "old"
    src.mkdir(parents=True)
    (src / "draft.json").write_text(json.dumps(env.draft, ensure_ascii=False), encoding="utf-8")

    def no_collect(*a):
        raise AssertionError("重播模式不可呼叫 collect()")
    env.mp.setattr(orchestrator.collector, "collect", no_collect)
    assert orchestrator.main(env.base, datetime(2026, 10, 25, 11, 0), from_run="runs/old") == 0
    assert (env.base / "runs" / "2026-10-25_1100" / "draft.json").exists()
    assert (src / "draft.json").exists()  # 原資料夾不動


def test_e07_no_mail_sends_nothing_but_writes_files(env):
    assert orchestrator.main(env.base, datetime(2026, 10, 25, 9, 30), send=False) == 0
    assert env.sent == []
    assert (env.run_dir / "newsletter.html").exists() and (env.run_dir / "summary.json").exists()


def test_source_dead_items_never_reach_reviewer(env):
    seen = []
    env.mp.setattr(orchestrator.url_resolver, "check_sources",
                   lambda d, cfg, rd: ({**d, "items": d["items"][:2]}, []))
    env.mp.setattr(orchestrator.reviewer, "review_items",
                   lambda cfg, d, s, e: seen.append(len(d["items"])) or env.pass_review(d))
    env.run()
    assert seen == [2]


def test_k01_decisions_include_items_dropped_before_review(env):
    dead = [{"id": "L3", "failed_checks": ["source_dead"]}]
    env.mp.setattr(orchestrator.url_resolver, "check_sources",
                   lambda d, cfg, rd: ({**d, "items": [i for i in d["items"] if i["id"] != "L3"]},
                                       [{**f, "issues": ["整則剔除"], "title": "", "sources": []} for f in dead]))
    env.run()
    dec = json.loads((env.run_dir / "decisions.json").read_text(encoding="utf-8"))
    assert dec["L3"] == {"status": "dropped", "stage": "resolve", "reasons": ["source_dead"]}
    assert dec["L1"]["status"] == "kept"


def test_top3_rewritten_from_kept_items_not_draft(env):
    seen = []
    env.mp.setattr(orchestrator.reviewer, "check_top3",
                   lambda cfg, top3, items: seen.append(top3) or [{"index": 0, "verdict": "pass"}])
    assert env.run() == 0
    assert seen[0][0]["text"] == "重寫焦點" and "重寫焦點" in env.sent[0][1]
    assert json.loads((env.run_dir / "review.json").read_text(encoding="utf-8"))["top3_written"] == seen[0]


def test_top3_check_failure_still_sends_newsletter(env):
    env.mp.setattr(orchestrator.reviewer, "check_top3", lambda cfg, top3, items: None)
    assert env.run() == 0
    assert "本週無通過查核的焦點" in env.sent[0][1]
