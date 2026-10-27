"""R-01 ~ R-07：requests 以假 session 取代，不連網。"""
import requests

from url_resolver import resolve_urls

REDIR = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc"


class Resp:
    def __init__(self, url, status=200):
        self.url, self.status_code = url, status

    def close(self):
        pass


class FakeSession:
    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def get(self, url, **kw):
        self.calls.append(url)
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def draft_with(make_draft, url):
    d = make_draft(1, 0)
    d["items"][0]["sources"][0]["url"] = url
    return d


def run(make_draft, cfg, session, url=REDIR):
    return resolve_urls(draft_with(make_draft, url), cfg, "2026-10-25", session)


def test_r01_resolved(make_draft, cfg):
    out, fails = run(make_draft, cfg, FakeSession(Resp("https://real.com/a")))
    s = out["items"][0]["sources"][0]
    assert (s["url"], s["original_url"], s["domain"]) == ("https://real.com/a", REDIR, "real.com")
    assert fails == []


def test_r02_bad_status_removes_link(make_draft, cfg):
    out, fails = run(make_draft, cfg, FakeSession(Resp("https://real.com/a", 403), Resp("https://real.com/a", 403)))
    assert out["items"] == []
    assert fails[0]["failed_checks"] == ["url_resolve"] and "403" in fails[0]["issues"][0]


def test_r03_still_redirect_domain(make_draft, cfg):
    out, fails = run(make_draft, cfg, FakeSession(Resp(REDIR), Resp(REDIR)))
    assert out["items"] == [] and "轉址" in fails[0]["issues"][0]


def test_r04_non_redirect_untouched(make_draft, cfg):
    s = FakeSession()
    out, fails = run(make_draft, cfg, s, "https://example.com/x?utm_source=a")
    assert s.calls == [] and out["items"][0]["sources"][0]["url"] == "https://example.com/x?utm_source=a"
    assert out["items"][0]["sources"][0]["domain"] == "example.com"


def test_r05_strip_utm_keep_others(make_draft, cfg):
    out, _ = run(make_draft, cfg, FakeSession(Resp("https://real.com/a?utm_source=x&id=7&utm_medium=y")))
    assert out["items"][0]["sources"][0]["url"] == "https://real.com/a?id=7"


def test_r06_item_dropped_when_all_sources_fail(make_draft, cfg):
    d = make_draft(2, 0)
    d["items"][0]["sources"][0]["url"] = REDIR
    out, fails = resolve_urls(d, cfg, "2026-10-25", FakeSession(Resp("x", 404), Resp("x", 404)))
    assert [i["id"] for i in out["items"]] == ["L2"]
    assert any(f["id"] == "L1" and "整則剔除" in f["issues"][0] for f in fails)


def test_r07_timeout_then_ok(make_draft, cfg):
    out, fails = run(make_draft, cfg, FakeSession(requests.Timeout(), Resp("https://real.com/a")))
    assert out["items"][0]["sources"][0]["url"] == "https://real.com/a" and fails == []


def test_google_url_redirect_with_path(make_draft, cfg):
    s = FakeSession(Resp("https://real.com/a"))
    run(make_draft, cfg, s, "https://www.google.com/url?q=https://real.com/a")
    assert len(s.calls) == 1


# ---------- 來源預檢（R-08 ~ R-11，SPEC §6.2）----------

from url_resolver import check_sources  # noqa: E402


def precheck(make_draft, cfg, session, n_sources=1):
    d = make_draft(1, 0)
    d["items"][0]["sources"] = [{"label": f"s{i}", "type": "original", "url": f"https://site{i}.com/a"}
                                for i in range(n_sources)]
    return check_sources(d, cfg, "2026-10-26", session)


def test_r08_all_sources_dead_item_dropped(make_draft, cfg):
    out, fails = precheck(make_draft, cfg, FakeSession(Resp("u", 404), Resp("u", 410)), n_sources=2)
    assert out["items"] == []
    assert fails[-1]["failed_checks"] == ["source_dead"] and "整則剔除" in fails[-1]["issues"][0]


def test_r09_blocked_statuses_are_kept(make_draft, cfg):
    for code in (401, 403, 419, 429, 500, 503):
        out, fails = precheck(make_draft, cfg, FakeSession(Resp("u", code)))
        assert len(out["items"]) == 1 and fails == [], code


def test_r10_only_dead_link_removed(make_draft, cfg):
    out, fails = precheck(make_draft, cfg, FakeSession(Resp("u", 404), Resp("u", 200)), n_sources=2)
    assert [s["label"] for s in out["items"][0]["sources"]] == ["s1"]
    assert len(fails) == 1 and "連結移除" in fails[0]["issues"][0]


def test_r11_connection_failure_is_dead(make_draft, cfg):
    s = FakeSession(requests.Timeout(), requests.ConnectionError())
    out, _ = precheck(make_draft, cfg, s)
    assert out["items"] == [] and len(s.calls) == 2  # 重試 1 次後判死


def test_precheck_does_not_mutate_input(make_draft, cfg):
    d = make_draft(1, 0)
    check_sources(d, cfg, "2026-10-26", FakeSession(Resp("u", 404)))
    assert len(d["items"]) == 1
