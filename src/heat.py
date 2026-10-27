"""熱度數字取得與計分（SPEC §6.4）。數字一律由公開 API 取得，不信任 AI 填的值；任何失敗只記 0 分，不中斷流程。"""
import copy
import logging
import os
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import requests

UA = "ai-weekly-newsletter/0.4"
HF_NON_MODEL = {"datasets", "spaces", "papers", "collections", "blog", "docs", "models"}


def classify(url):
    """依網址決定走哪個 API，回傳 (kind, key)。kind: hn / hf / github / reddit / media；key 為 API 用的識別，無法解析時為 None。"""
    p = urlsplit(url)
    host = (p.hostname or "").lower().removeprefix("www.")
    parts = [x for x in p.path.split("/") if x]
    if host == "news.ycombinator.com":
        item_id = parse_qs(p.query).get("id", [""])[0]
        return "hn", item_id if item_id.isdigit() else None
    if host == "huggingface.co":
        ok = len(parts) >= 2 and parts[0] not in HF_NON_MODEL
        return "hf", f"{parts[0]}/{parts[1]}" if ok else None
    if host == "github.com":
        return "github", f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else None
    if host.endswith("reddit.com") or host == "redd.it":
        return "reddit", url
    return "media", host


def _age_days(iso):
    """存在天數，最少算 1 天（SPEC §6.4）。時間缺漏或格式錯誤時當作 1 天。"""
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return max((datetime.now(timezone.utc) - t).total_seconds() / 86400, 1.0)
    except (AttributeError, ValueError):
        return 1.0


def _count_comments(node):
    n, stack = 0, list(node.get("children") or [])
    while stack:  # 迭代而非遞迴，避免超長討論串爆堆疊
        n += 1
        stack.extend(stack.pop().get("children") or [])
    return n


def _tiers(value, thresholds):
    return sum(value >= t for t in thresholds)


class _Client:
    """帶逾時、重試與最小請求間隔的 HTTP 取 JSON。"""

    def __init__(self, hcfg, session, sleep):
        self.cfg, self.session, self.sleep, self.last = hcfg, session, sleep, 0.0

    def get_json(self, url, headers=None):
        reason = ""
        for _ in range(self.cfg["retries"] + 1):
            wait = self.cfg["min_interval_seconds"] - (time.monotonic() - self.last)
            if wait > 0:
                self.sleep(wait)
            self.last = time.monotonic()
            try:
                r = self.session.get(url, headers={"User-Agent": UA, **(headers or {})},
                                     timeout=self.cfg["timeout_seconds"])
            except requests.RequestException as e:
                reason = type(e).__name__
                continue
            if r.status_code == 200:
                try:
                    return r.json(), ""
                except ValueError:
                    return None, "回應不是 JSON"
            reason = f"HTTP {r.status_code}"
            if r.status_code not in (403, 429, 500, 502, 503, 504):
                break
        return None, reason


def _fail(kind, reason):
    return {"kind": kind, "ok": False, "reason": reason, "score": 0, "peak": 0}


def _hn(c, key, h):
    d, why = c.get_json(f"https://hn.algolia.com/api/v1/items/{key}")
    if d is None:
        return _fail("hn", why)
    points, comments, age = d.get("points") or 0, _count_comments(d), _age_days(d.get("created_at"))
    t = h["hn"]
    if age > t["max_age_days"]:  # AI 常給出無關的舊討論串；舊的不計分
        return _fail("hn", f"討論串太舊（{age:.0f} 天）")
    score = _tiers(points / age, t["per_day"]) + (comments >= t["comments_bonus"])
    return {"kind": "hn", "ok": True, "points": points, "comments": comments,
            "age_days": round(age, 1), "score": score, "peak": points}


def _hf(c, key, h):
    d, why = c.get_json(f"https://huggingface.co/api/models/{key}")
    if d is None:
        return _fail("hf", why)
    downloads, likes, age = d.get("downloads") or 0, d.get("likes") or 0, _age_days(d.get("createdAt"))
    t = h["hf"]
    score = _tiers(downloads / age, t["downloads_per_day"]) + (likes >= t["likes_bonus"])
    return {"kind": "hf", "ok": True, "downloads": downloads, "likes": likes,
            "age_days": round(age, 1), "score": score, "peak": downloads}


def _github(c, key, h):
    headers = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    d, why = c.get_json(f"https://api.github.com/repos/{key}", headers)
    if d is None:
        return _fail("github", why)
    stars = d.get("stargazers_count") or 0
    return {"kind": "github", "ok": True, "stars": stars,
            "score": _tiers(stars, h["github"]["stars"]), "peak": stars}


_FETCHERS = {"hn": _hn, "hf": _hf, "github": _github}


def fetch_heat(draft, cfg, session=None, sleep=time.sleep):
    """為每則加上 heat_metrics（與 heat 同順序）。回傳新的 draft，不修改傳入值。"""
    h = cfg["heat"]
    client = _Client(h, session or requests.Session(), sleep)
    out, cache = copy.deepcopy(draft), {}
    for item in out["items"]:
        seen, metrics = set(), []
        for entry in item.get("heat", []):
            url = entry.get("url", "")
            kind, key = classify(url)
            dedupe = (kind, key if kind == "media" else url)  # 媒體以網域計；其餘以連結計
            if dedupe in seen:
                metrics.append({"kind": kind, "url": url, "ok": None, "score": 0, "peak": 0, "dup": True})
                continue
            seen.add(dedupe)
            if kind in _FETCHERS:
                if key is None:
                    m = _fail(kind, "無法解析網址")
                else:
                    if (kind, key) not in cache:
                        try:
                            cache[(kind, key)] = _FETCHERS[kind](client, key, h)
                        except Exception as e:  # 單筆失敗不可拖垮整個流程
                            logging.warning("熱度取得例外 %s: %r", url, e)
                            cache[(kind, key)] = _fail(kind, type(e).__name__)
                    m = dict(cache[(kind, key)])
            else:  # reddit / media：不呼叫 API，僅作參考
                m = {"kind": kind, "ok": None, "score": h["reference_score"], "peak": 0}
                if kind == "media":
                    m["domain"] = key
            m["url"] = url
            metrics.append(m)
        item["heat_metrics"] = metrics
    return out
