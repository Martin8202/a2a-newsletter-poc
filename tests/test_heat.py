"""H-01 ~ H-08：HTTP 全部以假 session 取代，不連網。"""
from datetime import datetime, timedelta, timezone

import requests

from heat import classify, fetch_heat

HN = "https://news.ycombinator.com/item?id=50169053"
HF = "https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017"
GH = "https://github.com/microsoft/BitNet"


class Resp:
    def __init__(self, data=None, status=200):
        self.data, self.status_code = data, status

    def json(self):
        if self.data is None:
            raise ValueError
        return self.data


class FakeSession:
    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def iso(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def run(make_draft, cfg, session, *urls):
    d = make_draft(1, 0)
    d["items"][0]["heat"] = [{"kind": "x", "url": u} for u in urls]
    return fetch_heat(d, cfg, session, sleep=lambda s: None)["items"][0]["heat_metrics"]


def test_h01_hn_points_comments_and_score(make_draft, cfg):
    tree = {"points": 600, "created_at": iso(2),
            "children": [{"children": [{"children": []}]}, {"children": []}]}  # 3 則留言
    [m] = run(make_draft, cfg, FakeSession(Resp(tree)), HN)
    assert (m["points"], m["comments"], m["ok"], m["peak"]) == (600, 3, True, 600)
    assert m["score"] == 2  # 600/2 天 = 300/天 ≥ 50、≥ 200；留言未達 100


def test_h01_hn_comment_bonus_and_min_one_day(make_draft, cfg):
    tree = {"points": 60, "created_at": iso(0.1), "children": [{"children": []} for _ in range(120)]}
    [m] = run(make_draft, cfg, FakeSession(Resp(tree)), HN)
    assert m["age_days"] == 1.0 and m["score"] == 2  # 60/天 → 1 分；留言 120 ≥ 100 → +1


def test_h02_hf(make_draft, cfg):
    data = {"downloads": 120000, "likes": 600, "createdAt": iso(2)}
    [m] = run(make_draft, cfg, FakeSession(Resp(data)), HF)
    assert (m["downloads"], m["likes"]) == (120000, 600)
    assert m["score"] == 3  # 50,000/天 → 2 分；likes 600 ≥ 500 → +1


def test_h03_github_headers_and_score(make_draft, cfg, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok123")
    s = FakeSession(Resp({"stargazers_count": 12000}))
    [m] = run(make_draft, cfg, s, GH)
    headers = s.calls[0][1]["headers"]
    assert headers["User-Agent"] and headers["Authorization"] == "Bearer tok123"
    assert s.calls[0][0] == "https://api.github.com/repos/microsoft/BitNet"
    assert m["score"] == 2 and m["stars"] == 12000


def test_h03_github_without_token_has_no_auth_header(make_draft, cfg, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    s = FakeSession(Resp({"stargazers_count": 5}))
    run(make_draft, cfg, s, GH)
    assert "Authorization" not in s.calls[0][1]["headers"]


def test_h04_reddit_and_media_are_reference_only(make_draft, cfg):
    s = FakeSession()
    ms = run(make_draft, cfg, s, "https://www.reddit.com/r/LocalLLaMA/comments/abc/x/",
             "https://techcrunch.com/a", "https://techcrunch.com/b", "https://www.theverge.com/c")
    assert s.calls == []
    assert [m["score"] for m in ms] == [0.5, 0.5, 0, 0.5]  # 同網域第二篇不重複計


def test_h05_retry_after_429_then_ok(make_draft, cfg):
    tree = {"points": 300, "created_at": iso(1), "children": []}
    s = FakeSession(Resp(status=429), Resp(tree))
    [m] = run(make_draft, cfg, s, HN)
    assert m["ok"] and len(s.calls) == 2


def test_h05_timeout_then_ok(make_draft, cfg):
    s = FakeSession(requests.Timeout(), Resp({"stargazers_count": 2000}))
    [m] = run(make_draft, cfg, s, GH)
    assert m["ok"] and m["score"] == 1


def test_h06_still_failing_scores_zero_without_raising(make_draft, cfg):
    [m] = run(make_draft, cfg, FakeSession(Resp(status=429), Resp(status=429)), HN)
    assert m["ok"] is False and m["score"] == 0 and "429" in m["reason"]


def test_h06_unexpected_exception_is_contained(make_draft, cfg):
    [m] = run(make_draft, cfg, FakeSession(Resp({"points": "bad", "children": []})), HN)
    assert m["ok"] is False and m["score"] == 0


def test_h07_same_url_fetched_once_across_items(make_draft, cfg):
    d = make_draft(2, 0)
    for i in d["items"]:
        i["heat"] = [{"kind": "hn", "url": HN}]
    s = FakeSession(Resp({"points": 500, "created_at": iso(1), "children": []}))
    out = fetch_heat(d, cfg, s, sleep=lambda x: None)
    assert len(s.calls) == 1
    assert all(i["heat_metrics"][0]["points"] == 500 for i in out["items"])


def test_h08_unparseable_urls_fail_softly(make_draft, cfg):
    s = FakeSession()
    ms = run(make_draft, cfg, s, "https://news.ycombinator.com/news", "https://huggingface.co/datasets/a/b",
             "https://github.com/onlyowner")
    assert s.calls == [] and all(m["ok"] is False and m["score"] == 0 for m in ms)


def test_classify():
    assert classify(HN) == ("hn", "50169053")
    assert classify(HF) == ("hf", "deepseek-ai/DeepSeek-V4.1-Flash-1017")
    assert classify("https://github.com/a/b/releases/tag/v1") == ("github", "a/b")
    assert classify("https://www.reddit.com/r/x")[0] == "reddit"
    assert classify("https://www.techcrunch.com/x") == ("media", "techcrunch.com")


def test_input_draft_not_mutated(make_draft, cfg):
    d = make_draft(1, 0)
    fetch_heat(d, cfg, FakeSession(Resp({"points": 1, "children": []})), sleep=lambda x: None)
    assert "heat_metrics" not in d["items"][0]


def test_h09_stale_hn_thread_scores_zero(make_draft, cfg):
    tree = {"points": 900, "created_at": iso(30), "children": []}
    [m] = run(make_draft, cfg, FakeSession(Resp(tree)), HN)
    assert m["ok"] is False and m["score"] == 0 and "太舊" in m["reason"]
