"""還原搜尋轉址連結（SPEC §6.2）。只發 HTTP 請求，不呼叫 AI。"""
import copy
import fnmatch
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from storage import failure

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _host_path(url):
    p = urlsplit(url)
    return (p.hostname or "").lower() + p.path


def is_redirect(url, redirect_domains):
    """redirect_domains 可含路徑（如 www.google.com/url），以 host+path 前綴比對。"""
    hp = _host_path(url)
    return any(hp == d or hp.startswith(d.rstrip("/") + "/") for d in redirect_domains)


def strip_params(url, patterns):
    p = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
         if not any(fnmatch.fnmatch(k, pat) for pat in patterns)]
    return urlunsplit(p._replace(query=urlencode(q)))


def resolve_one(url, rcfg, session):
    """回傳 (最終網址, None) 或 (None, 失敗原因)。"""
    reason = ""
    for _ in range(rcfg["retries"] + 1):
        try:
            r = session.get(url, allow_redirects=True, timeout=rcfg["timeout_seconds"],
                            headers={"User-Agent": UA}, stream=True)
            r.close()
        except requests.Timeout:
            reason = "逾時"
            continue
        except requests.RequestException as e:
            reason = f"請求錯誤: {type(e).__name__}"
            continue
        if not 200 <= r.status_code < 300:
            reason = f"HTTP {r.status_code}"
        elif is_redirect(r.url, rcfg["redirect_domains"]):
            reason = "最終網址仍為轉址網域"
        else:
            return strip_params(r.url, rcfg["strip_params"]), None
    return None, reason


def resolve_urls(draft, cfg, run_date, session=None):
    """回傳 (draft_resolved, failures)。不修改傳入的 draft。"""
    rcfg = cfg["url_resolver"]
    if session is None:
        session = requests.Session()
        session.max_redirects = rcfg["max_redirects"]
    out, fails = copy.deepcopy(draft), []
    kept = []
    for item in out["items"]:
        def fix(links):
            good = []
            for link in links:
                orig = link["url"]
                if is_redirect(orig, rcfg["redirect_domains"]):
                    final, why = resolve_one(orig, rcfg, session)
                    if final is None:
                        fails.append(failure(run_date, "resolve", item["id"], item["title"],
                                             ["url_resolve"], [why], [orig]))
                        continue
                else:
                    final = orig
                link.update(url=final, original_url=orig, domain=(urlsplit(final).hostname or "").lower())
                good.append(link)
            return good

        item["signals"] = fix(item["signals"])
        item["sources"] = fix(item["sources"])
        if item["sources"]:
            kept.append(item)
        else:
            fails.append(failure(run_date, "resolve", item["id"], item["title"], ["url_resolve"],
                                 ["sources 全部還原失敗，整則剔除"]))
    out["items"] = kept
    return out, fails


def _is_dead(url, pc, session):
    """404、410 或連線失敗（含重試後仍逾時）視為已死；其他非 2xx 可能是擋程式，視為無法預檢（不算死）。"""
    for _ in range(pc["retries"] + 1):
        try:
            r = session.get(url, allow_redirects=True, timeout=pc["timeout_seconds"],
                            headers={"User-Agent": UA}, stream=True)
            r.close()
        except requests.RequestException:
            continue
        return r.status_code in pc["dead_statuses"]
    return True


def check_sources(draft, cfg, run_date, session=None):
    """來源預檢（SPEC §6.2）：移除已死的來源連結；某則 sources 全死則整則剔除，不送查核。回傳 (draft, failures)。"""
    pc = cfg["url_resolver"]["precheck"]
    session = session or requests.Session()
    out, fails, kept = copy.deepcopy(draft), [], []
    for item in out["items"]:
        alive, dead = [], []
        for link in item["sources"]:
            (dead if _is_dead(link["url"], pc, session) else alive).append(link)
        if not alive:
            fails.append(failure(run_date, "resolve", item["id"], item["title"], ["source_dead"],
                                 ["所有來源皆已死（404、410 或連線失敗），整則剔除"], [l["url"] for l in dead]))
            continue
        for link in dead:
            fails.append(failure(run_date, "resolve", item["id"], item["title"], ["source_dead"],
                                 ["來源已死，連結移除"], [link["url"]]))
        item["sources"] = alive
        kept.append(item)
    out["items"] = kept
    return out, fails
